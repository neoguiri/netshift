"""Accès système Windows : lecture et application des configurations IP."""
from __future__ import annotations

import base64
import ctypes
import ipaddress
import json
import queue
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# --------------------------------------------------------------------------- #
#  Exécution de commandes
# --------------------------------------------------------------------------- #
def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "oem", "cp850", "cp1252"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """Lance une commande sans fenêtre console, renvoie (code, sortie)."""
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return p.returncode, _decode(p.stdout).strip()
    except subprocess.TimeoutExpired:
        return 1, f"Délai dépassé ({timeout}s) : {' '.join(cmd)}"
    except FileNotFoundError as e:
        return 1, str(e)


_PS_PREFIX = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ProgressPreference='SilentlyContinue';"


def run_ps_oneshot(script: str, timeout: int = 60) -> tuple[int, str]:
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _PS_PREFIX + script], timeout)


class _PSSession:
    """Processus PowerShell persistant : évite ~3 s de démarrage à chaque requête."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()

    def _start(self):
        self._proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NoLogo", "-ExecutionPolicy", "Bypass", "-Command", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
        self._lines = queue.Queue()
        threading.Thread(target=self._reader, args=(self._proc, self._lines), daemon=True).start()
        self._send(_PS_PREFIX)

    @staticmethod
    def _reader(proc: subprocess.Popen, q: queue.Queue):
        for raw in iter(proc.stdout.readline, b""):
            q.put(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        q.put(None)

    def _send(self, line: str):
        self._proc.stdin.write((line + "\n").encode("utf-8"))
        self._proc.stdin.flush()

    def run(self, script: str, timeout: int = 60) -> tuple[int, str]:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._start()
            marker = f"__END_{uuid.uuid4().hex}__"
            b64 = base64.b64encode(script.encode("utf-8")).decode()
            self._send(
                "$__ok=$true; $ErrorActionPreference='Stop'; try { iex ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + b64 + "')))"
                " 2>&1 | Out-String -Width 4096 -Stream } catch { $__ok=$false; $_ | Out-String -Stream };"
                f" if(-not $?){{$__ok=$false}}; '{marker}' + [int](-not $__ok)"
            )
            out, deadline = [], time.monotonic() + timeout
            while True:
                try:
                    line = self._lines.get(timeout=max(0.1, deadline - time.monotonic()))
                except queue.Empty:
                    self.close()
                    return 1, f"Délai PowerShell dépassé ({timeout}s)"
                if line is None:
                    self._proc = None
                    return 1, "\n".join(out)
                if line.startswith(marker):
                    return int(line[len(marker):] or 0), "\n".join(out).strip()
                if line.startswith("PS ") and line.rstrip().endswith(">"):
                    continue
                out.append(line)

    def close(self):
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
        self._proc = None


_ps = _PSSession()


def run_ps(script: str, timeout: int = 60) -> tuple[int, str]:
    try:
        return _ps.run(script, timeout)
    except OSError:
        _ps.close()
        return run_ps_oneshot(script, timeout)


def warmup_ps():
    run_ps("$null = Get-NetAdapter; $null = Get-NetIPInterface", timeout=60)


def popen_stream(cmd: list[str]) -> subprocess.Popen:
    """Process dont on lit la sortie ligne par ligne (ping continu, tracert...)."""
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# --------------------------------------------------------------------------- #
#  Modèle
# --------------------------------------------------------------------------- #
@dataclass
class IPAddr:
    ip: str
    prefix: int
    origin: str = ""

    @property
    def mask(self) -> str:
        return prefix_to_mask(self.prefix)


@dataclass
class Adapter:
    name: str
    description: str
    status: str
    mac: str
    speed: str
    index: int
    guid: str
    virtual: bool
    dhcp: bool
    dns_static: bool
    mtu: int | None
    ips: list[IPAddr] = field(default_factory=list)
    gateways: list[str] = field(default_factory=list)
    dns: list[str] = field(default_factory=list)
    kind: str = "ethernet"   # voir KINDS / classify()

    @property
    def up(self) -> bool:
        return self.status.lower() == "up"

    @property
    def disabled(self) -> bool:
        return self.status.lower() == "disabled"

    @property
    def primary_ip(self) -> IPAddr | None:
        real = [i for i in self.ips if not i.ip.startswith("169.254.")]
        return (real or self.ips or [None])[0]

    def to_config(self) -> dict:
        """Convertit la config actuelle en dictionnaire de preset."""
        p = self.primary_ip
        return {
            "mode": "dhcp" if self.dhcp else "static",
            "ip": "" if self.dhcp or not p else p.ip,
            "mask": "" if self.dhcp or not p else p.mask,
            "gateway": "" if self.dhcp else (self.gateways[0] if self.gateways else ""),
            "dns_mode": "static" if (self.dns_static or not self.dhcp) else "auto",
            "dns1": self.dns[0] if len(self.dns) > 0 and (self.dns_static or not self.dhcp) else "",
            "dns2": self.dns[1] if len(self.dns) > 1 and (self.dns_static or not self.dhcp) else "",
            "extra_ips": [] if self.dhcp else [f"{i.ip}/{i.prefix}" for i in self.ips if p and i.ip != p.ip],
        }


# --------------------------------------------------------------------------- #
#  Type de carte (pour l'affichage et les filtres)
# --------------------------------------------------------------------------- #
KINDS = {  # clé : (libellé, libellé court)
    "ethernet": ("Ethernet", "ETH"),
    "wifi": ("Wi-Fi", "WI-FI"),
    "mobile": ("Mobile (4G/5G)", "WWAN"),
    "vpn": ("VPN", "VPN"),
    "bluetooth": ("Bluetooth", "BT"),
    "virtual": ("Virtuelles", "VIRT"),
    "other": ("Autres", "AUTRE"),
}

_VPN_HINTS = ("wireguard", "wintun", "openvpn", "tap-windows", "tap adapter", "tap-protonvpn", "vpn", "anyconnect",
              "fortinet", "fortissl", "fortivpn", "globalprotect", "pangp", "juniper", "pulse secure", "zscaler",
              "nordlynx", "tailscale", "zerotier", "forticlient", "check point", "sonicwall", "f5 ", "wan miniport")
_VIRTUAL_HINTS = ("hyper-v", "vethernet", "vmware", "virtualbox", "parallels", "virtio", "loopback", "npcap",
                  "docker", "wsl", "kernel debug", "teredo", "isatap", "6to4", "host-only", "qemu", "xen ")


def classify(name: str, description: str, media: str = "", physical: str = "", if_type: int = 0,
             virtual: bool = False, hardware: bool = True) -> str:
    """Devine le type d'une carte à partir des propriétés renvoyées par Get-NetAdapter."""
    text = f"{name} {description}".lower()
    media, physical = (media or "").lower(), (physical or "").lower()
    if if_type in (23, 131) or any(h in text for h in _VPN_HINTS):          # PPP, tunnel
        return "vpn"
    if "bluetooth" in physical or "bluetooth" in text:
        return "bluetooth"
    if "wireless wan" in media or "wwan" in physical or "mobile broadband" in text or if_type == 243:
        return "mobile"
    if "802.11" in media or "802.11" in physical or if_type == 71 or any(
            h in text for h in ("wi-fi", "wifi", "wireless", "wlan")):
        return "wifi"
    if virtual or any(h in text for h in _VIRTUAL_HINTS) or (not hardware and if_type != 6):
        return "virtual"
    if "802.3" in media or "802.3" in physical or if_type == 6:
        return "ethernet"
    return "other"


_PS_LIST = r"""
$ErrorActionPreference='SilentlyContinue'
$ipifs  = Get-NetIPInterface -AddressFamily IPv4 | Group-Object ifIndex -AsHashTable -AsString
$addrs  = Get-NetIPAddress -AddressFamily IPv4 | Group-Object InterfaceIndex -AsHashTable -AsString
$addrsP = Get-NetIPAddress -AddressFamily IPv4 -PolicyStore PersistentStore | Group-Object InterfaceIndex -AsHashTable -AsString
$rts    = Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Group-Object ifIndex -AsHashTable -AsString
$rtsP   = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -PolicyStore PersistentStore | Group-Object ifIndex -AsHashTable -AsString
$dnss   = Get-DnsClientServerAddress -AddressFamily IPv4 | Group-Object InterfaceIndex -AsHashTable -AsString
if (-not $ipifs) { $ipifs=@{} }; if (-not $addrs) { $addrs=@{} }; if (-not $addrsP) { $addrsP=@{} }
if (-not $rts) { $rts=@{} }; if (-not $rtsP) { $rtsP=@{} }; if (-not $dnss) { $dnss=@{} }
$res = foreach ($a in (Get-NetAdapter | Sort-Object ifIndex)) {
  $i = "$($a.ifIndex)"
  $ipif = $ipifs[$i] | Select-Object -First 1
  $ips = @($addrs[$i])
  if (-not $addrs[$i]) { $ips = @($addrsP[$i] | Where-Object { $_ }) }
  $gw = @($rts[$i] | ForEach-Object { $_.NextHop })
  if (-not $rts[$i]) { $gw = @($rtsP[$i] | ForEach-Object { $_.NextHop }) }
  $dns = @(($dnss[$i] | Select-Object -First 1).ServerAddresses)
  $reg = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\$($a.InterfaceGuid)"
  $dhcp = if ($ipif) { "$($ipif.Dhcp)" -eq 'Enabled' } else { [int]$reg.EnableDHCP -eq 1 }
  [pscustomobject]@{
    name=$a.Name; desc=$a.InterfaceDescription; status="$($a.Status)"; mac=$a.MacAddress
    speed="$($a.LinkSpeed)"; index=[int]$a.ifIndex; guid="$($a.InterfaceGuid)"; virtual=[bool]$a.Virtual
    dhcp=$dhcp; dns_static=[bool]($reg.NameServer); mtu=$ipif.NlMtu
    media="$($a.MediaType)"; physical="$($a.PhysicalMediaType)"; iftype=[int]$a.InterfaceType
    hardware=[bool]$a.HardwareInterface
    ips=@($ips | ForEach-Object { [pscustomobject]@{ip=$_.IPAddress; prefix=[int]$_.PrefixLength; origin="$($_.PrefixOrigin)"} })
    gateways=@($gw | Where-Object { $_ -and $_ -ne '0.0.0.0' } | Select-Object -Unique)
    dns=$dns
  }
}
ConvertTo-Json -InputObject @($res) -Depth 5 -Compress
"""


def _as_list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def list_adapters() -> list[Adapter]:
    code, out = run_ps(_PS_LIST, timeout=45)
    if code != 0 or not out:
        raise RuntimeError(out or "Impossible de lire les cartes réseau")
    start = out.find("[")
    data = json.loads(out[start:]) if start >= 0 else []
    adapters = []
    for d in _as_list(data):
        adapters.append(
            Adapter(
                name=d.get("name") or "",
                description=d.get("desc") or "",
                status=d.get("status") or "",
                mac=d.get("mac") or "",
                speed=d.get("speed") or "",
                index=int(d.get("index") or 0),
                guid=d.get("guid") or "",
                virtual=bool(d.get("virtual")),
                dhcp=bool(d.get("dhcp")),
                dns_static=bool(d.get("dns_static")),
                mtu=d.get("mtu"),
                ips=[IPAddr(x["ip"], int(x["prefix"]), x.get("origin", "")) for x in _as_list(d.get("ips")) if x and x.get("ip")],
                gateways=[g for g in _as_list(d.get("gateways")) if g],
                dns=[s for s in _as_list(d.get("dns")) if s],
                kind=classify(d.get("name") or "", d.get("desc") or "", d.get("media") or "",
                              d.get("physical") or "", int(d.get("iftype") or 0), bool(d.get("virtual")),
                              bool(d.get("hardware", True))),
            )
        )
    return adapters


# --------------------------------------------------------------------------- #
#  Validation
# --------------------------------------------------------------------------- #
def prefix_to_mask(prefix: int) -> str:
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)


def parse_mask(value: str) -> int:
    """Accepte '255.255.255.0', '/24' ou '24'. Renvoie le préfixe."""
    v = value.strip().lstrip("/")
    if not v:
        raise ValueError("Masque manquant")
    if v.isdigit():
        p = int(v)
        if not 0 <= p <= 32:
            raise ValueError("Préfixe hors limites (0-32)")
        return p
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{v}").prefixlen
    except ValueError:
        raise ValueError(f"Masque invalide : {value}") from None


def check_ip(value: str, label: str = "Adresse") -> str:
    try:
        return str(ipaddress.IPv4Address(value.strip()))
    except ValueError:
        raise ValueError(f"{label} invalide : {value or '(vide)'}") from None


def split_ip_prefix(text: str, default_prefix: int) -> tuple[str, int]:
    t = text.strip()
    if "/" in t:
        ip, m = t.split("/", 1)
        return check_ip(ip, "IP supplémentaire"), parse_mask(m)
    return check_ip(t, "IP supplémentaire"), default_prefix


def validate_config(cfg: dict) -> tuple[list[str], list[str]]:
    """Renvoie (erreurs, avertissements)."""
    errors, warns = [], []
    if cfg.get("mode") == "static":
        try:
            ip = check_ip(cfg.get("ip", ""), "Adresse IP")
            prefix = parse_mask(cfg.get("mask", ""))
            net = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
            ipa = ipaddress.IPv4Address(ip)
            if prefix < 31 and ipa in (net.network_address, net.broadcast_address):
                errors.append(f"{ip} est l'adresse réseau ou broadcast de {net}")
            gw = (cfg.get("gateway") or "").strip()
            if gw:
                gwa = ipaddress.IPv4Address(check_ip(gw, "Passerelle"))
                if gwa not in net:
                    warns.append(f"La passerelle {gw} n'est pas dans le sous-réseau {net}")
                if gwa == ipa:
                    errors.append("La passerelle est identique à l'adresse IP")
            for extra in cfg.get("extra_ips") or []:
                if extra.strip():
                    split_ip_prefix(extra, prefix)
        except ValueError as e:
            errors.append(str(e))
    if cfg.get("dns_mode", "static") == "static" or cfg.get("mode") == "static":
        for k, lbl in (("dns1", "DNS primaire"), ("dns2", "DNS secondaire")):
            if (cfg.get(k) or "").strip():
                try:
                    check_ip(cfg[k], lbl)
                except ValueError as e:
                    errors.append(str(e))
    return errors, warns


# --------------------------------------------------------------------------- #
#  Application
# --------------------------------------------------------------------------- #
def _netsh(*args: str) -> list[str]:
    return ["netsh", "interface", "ipv4", *args]


def build_commands(adapter: Adapter, cfg: dict) -> list[list[str]]:
    n = f"name={adapter.index}"
    cmds: list[list[str]] = []
    if cfg.get("mode") == "dhcp":
        cmds.append(_netsh("set", "address", n, "source=dhcp"))
        dns_static = cfg.get("dns_mode") == "static" and (cfg.get("dns1") or cfg.get("dns2"))
    else:
        prefix = parse_mask(cfg["mask"])
        mask = prefix_to_mask(prefix)
        gw = (cfg.get("gateway") or "").strip()
        cmd = _netsh("set", "address", n, "source=static", f"address={cfg['ip'].strip()}", f"mask={mask}")
        cmd += [f"gateway={gw}", "gwmetric=0"] if gw else ["gateway=none"]
        cmds.append(cmd)
        for extra in cfg.get("extra_ips") or []:
            if extra.strip():
                ip, p = split_ip_prefix(extra, prefix)
                cmds.append(_netsh("add", "address", n, f"address={ip}", f"mask={prefix_to_mask(p)}"))
        dns_static = True

    if dns_static:
        servers = [s.strip() for s in (cfg.get("dns1"), cfg.get("dns2")) if s and s.strip()]
        if servers:
            cmds.append(_netsh("set", "dnsservers", n, "source=static", f"address={servers[0]}", "register=primary", "validate=no"))
            for idx, s in enumerate(servers[1:], start=2):
                cmds.append(_netsh("add", "dnsservers", n, f"address={s}", f"index={idx}", "validate=no"))
        else:
            cmds.append(_netsh("set", "dnsservers", n, "source=static", "address=none", "register=primary", "validate=no"))
    else:
        cmds.append(_netsh("set", "dnsservers", n, "source=dhcp"))
    return cmds


def apply_config(adapter: Adapter, cfg: dict, log=print) -> bool:
    ok = True
    for cmd in build_commands(adapter, cfg):
        log("$ " + " ".join(cmd))
        code, out = run(cmd, timeout=60)
        if out:
            log(out)
        # netsh renvoie 1 quand la config est déjà identique ("DHCP est déjà activé…")
        if code != 0 and not _harmless(out):
            ok = False
    return ok


def _harmless(out: str) -> bool:
    o = out.lower()
    return any(k in o for k in ("déjà", "already", "deja"))


def set_adapter_enabled(adapter: Adapter, enabled: bool) -> tuple[int, str]:
    verb = "Enable-NetAdapter" if enabled else "Disable-NetAdapter"
    return run_ps(f"{verb} -InterfaceDescription '{_ps_quote(adapter.description)}' -Confirm:$false", timeout=60)


def rename_adapter(adapter: Adapter, new_name: str) -> tuple[int, str]:
    return run_ps(
        f"Rename-NetAdapter -InterfaceDescription '{_ps_quote(adapter.description)}' -NewName '{_ps_quote(new_name)}' -Confirm:$false"
    )


def set_mtu(adapter: Adapter, mtu: int) -> tuple[int, str]:
    return run(_netsh("set", "subinterface", str(adapter.index), f"mtu={mtu}", "store=persistent"))


def dhcp_renew(adapter: Adapter) -> tuple[int, str]:
    return run(["ipconfig", "/renew", adapter.name], timeout=90)


def dhcp_release(adapter: Adapter) -> tuple[int, str]:
    return run(["ipconfig", "/release", adapter.name], timeout=60)


def _ps_quote(s: str) -> str:
    return s.replace("'", "''")
