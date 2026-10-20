"""Outils réseau : ping ICMP natif, ARP, scan de sous-réseau, test de ports, calculs."""
from __future__ import annotations

import ctypes
import ipaddress
import socket
import struct
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from ctypes import wintypes
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
#  ICMP via iphlpapi (pas de sous-processus, pas besoin d'être admin)
# --------------------------------------------------------------------------- #
_iphlp = ctypes.windll.iphlpapi
_icmp = ctypes.windll.icmp if hasattr(ctypes.windll, "icmp") else _iphlp


class _IP_OPTION_INFORMATION(ctypes.Structure):
    _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte), ("Flags", ctypes.c_ubyte),
                ("OptionsSize", ctypes.c_ubyte), ("OptionsData", ctypes.c_void_p)]


class _ICMP_ECHO_REPLY(ctypes.Structure):
    _fields_ = [("Address", wintypes.ULONG), ("Status", wintypes.ULONG), ("RoundTripTime", wintypes.ULONG),
                ("DataSize", wintypes.USHORT), ("Reserved", wintypes.USHORT), ("Data", ctypes.c_void_p),
                ("Options", _IP_OPTION_INFORMATION)]


_iphlp.IcmpCreateFile.restype = wintypes.HANDLE
_iphlp.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
_iphlp.IcmpSendEcho.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.WORD,
                                ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
_iphlp.IcmpSendEcho.restype = wintypes.DWORD
_iphlp.SendARP.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG)]
_iphlp.SendARP.restype = wintypes.DWORD

_ICMP_STATUS = {
    11002: "Réseau de destination inaccessible",
    11003: "Hôte de destination inaccessible",
    11010: "Délai d'attente dépassé",
    11013: "TTL expiré",
    11050: "Échec général",
}


def _ip_to_ulong(ip: str) -> int:
    return struct.unpack("<I", socket.inet_aton(ip))[0]


@dataclass
class PingResult:
    ok: bool
    rtt: int | None = None
    ttl: int | None = None
    reply_from: str = ""
    error: str = ""


def ping(host: str, timeout_ms: int = 1000, size: int = 32, ttl: int = 128) -> PingResult:
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        return PingResult(False, error=f"Hôte introuvable : {host}")
    handle = _iphlp.IcmpCreateFile()
    if not handle or handle == wintypes.HANDLE(-1).value:
        return PingResult(False, error="IcmpCreateFile a échoué")
    try:
        data = ctypes.create_string_buffer(b"\x61" * size, size)
        opts = _IP_OPTION_INFORMATION(Ttl=ttl)
        buf_size = ctypes.sizeof(_ICMP_ECHO_REPLY) + size + 64
        buf = ctypes.create_string_buffer(buf_size)
        n = _iphlp.IcmpSendEcho(handle, _ip_to_ulong(ip), data, size, ctypes.byref(opts), buf, buf_size, timeout_ms)
        rep = _ICMP_ECHO_REPLY.from_buffer(buf)
        if n == 0:
            err = ctypes.GetLastError()
            src = socket.inet_ntoa(struct.pack("<I", rep.Address)) if rep.Address else ""
            return PingResult(False, reply_from=src, error=_ICMP_STATUS.get(rep.Status or err, "Délai d'attente dépassé"))
        src = socket.inet_ntoa(struct.pack("<I", rep.Address))
        if rep.Status != 0:
            return PingResult(False, reply_from=src, error=_ICMP_STATUS.get(rep.Status, f"Statut ICMP {rep.Status}"))
        return PingResult(True, rtt=rep.RoundTripTime, ttl=rep.Options.Ttl, reply_from=src)
    finally:
        _iphlp.IcmpCloseHandle(handle)


def arp_lookup(ip: str) -> str:
    """MAC d'un hôte du sous-réseau local via SendARP ('' si absent)."""
    mac = (ctypes.c_ubyte * 8)()
    length = wintypes.ULONG(6)
    try:
        if _iphlp.SendARP(_ip_to_ulong(ip), 0, ctypes.byref(mac), ctypes.byref(length)) != 0:
            return ""
    except OSError:
        return ""
    if length.value == 0:
        return ""
    return "-".join(f"{b:02X}" for b in mac[: length.value])


_OUI: dict[str, str] | None = None


def mac_vendor(mac: str) -> str:
    """Fabricant d'après le préfixe MAC (registre IEEE embarqué, aucune requête réseau)."""
    global _OUI
    h = "".join(c for c in (mac or "").upper() if c in "0123456789ABCDEF")
    if len(h) < 6:
        return ""
    if int(h[:2], 16) & 0x02:
        return "Adresse privée (aléatoire)"
    if _OUI is None:
        try:
            import gzip

            from .store import resource_dir
            raw = gzip.decompress((resource_dir() / "assets" / "oui.tsv.gz").read_bytes()).decode("utf-8")
            _OUI = dict(line.split("\t", 1) for line in raw.splitlines() if "\t" in line)
        except OSError:
            _OUI = {}
    return _OUI.get(h[:6], "")


def reverse_dns(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except OSError:
        return ""


# --------------------------------------------------------------------------- #
#  Scan de sous-réseau
# --------------------------------------------------------------------------- #
@dataclass
class HostResult:
    ip: str
    alive: bool
    rtt: int | None
    mac: str
    hostname: str
    via: str  # "ICMP", "ARP", "ICMP+ARP"


def scan_hosts(network: str, on_result, on_progress, stop: threading.Event,
               resolve_names: bool = True, use_arp: bool = True, workers: int = 256, timeout_ms: int = 600):
    net = ipaddress.IPv4Network(network, strict=False)
    if net.num_addresses > 4096:
        raise ValueError("Plage trop grande (max /20, soit 4096 adresses)")
    hosts = [str(h) for h in (net.hosts() if net.prefixlen < 31 else net)]
    total, done = len(hosts), 0
    lock = threading.Lock()

    def probe(ip: str) -> HostResult | None:
        if stop.is_set():
            return None
        p = ping(ip, timeout_ms)
        mac = arp_lookup(ip) if use_arp and not stop.is_set() else ""
        alive = p.ok or bool(mac)
        if not alive:
            return HostResult(ip, False, None, "", "", "")
        via = "+".join(x for x, ok in (("ICMP", p.ok), ("ARP", bool(mac))) if ok)
        name = reverse_dns(ip) if resolve_names and not stop.is_set() else ""
        return HostResult(ip, True, p.rtt if p.ok else None, mac, name, via)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, total))) as ex:
        futures = [ex.submit(probe, ip) for ip in hosts]
        for f in as_completed(futures):
            r = f.result()
            with lock:
                done += 1
            if r and r.alive:
                on_result(r)
            on_progress(done, total)
            if stop.is_set():
                for other in futures:
                    other.cancel()
                break


# --------------------------------------------------------------------------- #
#  Ports TCP
# --------------------------------------------------------------------------- #
COMMON_PORTS = {
    20: "FTP-data", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 80: "HTTP", 88: "Kerberos",
    110: "POP3", 123: "NTP", 135: "RPC", 139: "NetBIOS", 143: "IMAP", 161: "SNMP", 389: "LDAP", 443: "HTTPS",
    445: "SMB", 502: "Modbus", 554: "RTSP", 587: "SMTP-sub", 636: "LDAPS", 993: "IMAPS", 995: "POP3S",
    1433: "MSSQL", 1883: "MQTT", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL", 5900: "VNC",
    5985: "WinRM", 8080: "HTTP-alt", 8443: "HTTPS-alt", 9100: "Imprimante",
}


def parse_ports(spec: str) -> list[int]:
    ports: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            if a > b:
                a, b = b, a
            ports.update(range(max(1, a), min(65535, b) + 1))
        else:
            p = int(part)
            if 1 <= p <= 65535:
                ports.add(p)
    if not ports:
        raise ValueError("Aucun port valide")
    if len(ports) > 10000:
        raise ValueError("Trop de ports (max 10000)")
    return sorted(ports)


def check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def scan_ports(host: str, ports: list[int], on_open, on_progress, stop: threading.Event, timeout: float = 0.8):
    ip = socket.gethostbyname(host)
    total, done = len(ports), 0
    with ThreadPoolExecutor(max_workers=min(200, len(ports))) as ex:
        futs = {ex.submit(lambda p: None if stop.is_set() else check_port(ip, p, timeout), p): p for p in ports}
        for f in as_completed(futs):
            done += 1
            if f.result():
                on_open(futs[f])
            on_progress(done, total)
            if stop.is_set():
                for other in futs:
                    other.cancel()
                break


# --------------------------------------------------------------------------- #
#  Calculs
# --------------------------------------------------------------------------- #
def subnet_info(text: str, mask: str | None = None) -> list[tuple[str, str]]:
    t = text.strip()
    if mask and "/" not in t:
        t = f"{t}/{mask.strip().lstrip('/')}"
    if "/" not in t:
        t += "/24"
    iface = ipaddress.IPv4Interface(t)
    net = iface.network
    hosts = net.num_addresses - 2 if net.prefixlen < 31 else net.num_addresses
    first = net.network_address + 1 if net.prefixlen < 31 else net.network_address
    last = net.broadcast_address - 1 if net.prefixlen < 31 else net.broadcast_address
    ip = iface.ip
    cls = "A" if ip in ipaddress.IPv4Network("0.0.0.0/1") else "B" if ip in ipaddress.IPv4Network("128.0.0.0/2") \
        else "C" if ip in ipaddress.IPv4Network("192.0.0.0/3") else "D (multicast)" if ip.is_multicast else "E"
    kind = "Privée" if ip.is_private else "Loopback" if ip.is_loopback else "Link-local (APIPA)" if ip.is_link_local \
        else "Multicast" if ip.is_multicast else "Publique"
    return [
        ("Adresse", str(ip)),
        ("Masque", f"{net.netmask}  (/{net.prefixlen})"),
        ("Masque inverse", str(net.hostmask)),
        ("Réseau", str(net.network_address)),
        ("Broadcast", str(net.broadcast_address)),
        ("Première IP", str(first)),
        ("Dernière IP", str(last)),
        ("Hôtes utilisables", f"{hosts:,}".replace(",", " ")),
        ("Classe / type", f"{cls} — {kind}"),
        ("Binaire", ".".join(f"{int(o):08b}" for o in str(ip).split("."))),
    ]


def public_ip(timeout: float = 5.0) -> str:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read().decode().strip()
        except Exception:
            continue
    raise RuntimeError("Impossible de joindre un service d'IP publique")


def resolve(name: str) -> list[str]:
    infos = socket.getaddrinfo(name, None)
    seen, out = set(), []
    for fam, *_rest, addr in infos:
        a = addr[0]
        if a not in seen:
            seen.add(a)
            out.append(("IPv6  " if fam == socket.AF_INET6 else "IPv4  ") + a)
    return out
