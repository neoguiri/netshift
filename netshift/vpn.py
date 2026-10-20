"""Connexions VPN Windows (module PowerShell VpnClient + rasdial) : lister, créer, modifier, supprimer,
connecter, déconnecter, routes du split tunneling."""
from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field

from . import netbackend as nb
from .i18n import _

TUNNEL_TYPES = {"Automatic": _("Automatique"), "Ikev2": "IKEv2", "Sstp": "SSTP", "L2tp": "L2TP/IPsec", "Pptp": "PPTP"}
AUTH_METHODS = {"MSChapv2": "MS-CHAP v2", "Eap": "EAP", "Pap": "PAP", "Chap": "CHAP",
                "MachineCertificate": _("Certificat machine")}
ENCRYPTION = {"Required": _("Requis"), "Maximum": _("Maximal"), "Optional": _("Optionnel"), "NoEncryption": _("Aucun"),
              "Custom": _("Personnalisé")}


@dataclass
class Vpn:
    name: str
    server: str
    tunnel: str = "Automatic"
    auth: str = "MSChapv2"
    encryption: str = "Required"
    split: bool = False
    remember: bool = True
    dns_suffix: str = ""
    all_users: bool = False
    status: str = "Disconnected"
    routes: list[str] = field(default_factory=list)
    idle: int = 0
    ips: list[str] = field(default_factory=list)

    @property
    def connected(self) -> bool:
        return self.status.lower() == "connected"

    @property
    def key(self) -> str:
        return f"{'all' if self.all_users else 'me'}:{self.name}"

    def to_dict(self) -> dict:
        return {"name": self.name, "server": self.server, "tunnel": self.tunnel, "auth": self.auth,
                "encryption": self.encryption, "split": self.split, "remember": self.remember,
                "dns_suffix": self.dns_suffix, "all_users": self.all_users, "routes": list(self.routes),
                "psk": ""}


_PS_LIST = r"""
$ErrorActionPreference='SilentlyContinue'
$res = @()
foreach ($all in @($false, $true)) {
  $list = if ($all) { Get-VpnConnection -AllUserConnection } else { Get-VpnConnection }
  foreach ($v in @($list)) {
    if (-not $v) { continue }
    $ips = @()
    if ("$($v.ConnectionStatus)" -eq 'Connected') {
      $ips = @(Get-NetIPAddress -InterfaceAlias $v.Name -AddressFamily IPv4 | ForEach-Object { "$($_.IPAddress)/$($_.PrefixLength)" })
    }
    $res += [pscustomobject]@{
      name=$v.Name; server=$v.ServerAddress; tunnel="$($v.TunnelType)"
      auth=@($v.AuthenticationMethod | ForEach-Object { "$_" }); encryption="$($v.EncryptionLevel)"
      split=[bool]$v.SplitTunneling; remember=[bool]$v.RememberCredential; dns_suffix="$($v.DnsSuffix)"
      all_users=$all; status="$($v.ConnectionStatus)"; idle=[int]$v.IdleDisconnectSeconds
      routes=@($v.Routes | ForEach-Object { "$($_.DestinationPrefix)" }); ips=$ips
    }
  }
}
ConvertTo-Json -InputObject @($res) -Depth 4 -Compress
"""


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def parse_list(out: str) -> list[Vpn]:
    start = out.find("[")
    data = json.loads(out[start:]) if start >= 0 else []
    vpns = []
    for d in _as_list(data):
        auth = _as_list(d.get("auth"))
        vpns.append(Vpn(
            name=d.get("name") or "", server=d.get("server") or "", tunnel=d.get("tunnel") or "Automatic",
            auth=auth[0] if auth else "MSChapv2", encryption=d.get("encryption") or "Required",
            split=bool(d.get("split")), remember=bool(d.get("remember")), dns_suffix=d.get("dns_suffix") or "",
            all_users=bool(d.get("all_users")), status=d.get("status") or "Disconnected",
            routes=[r for r in _as_list(d.get("routes")) if r], idle=int(d.get("idle") or 0),
            ips=[i for i in _as_list(d.get("ips")) if i],
        ))
    return sorted(vpns, key=lambda v: (not v.connected, v.name.lower()))


def list_vpns() -> list[Vpn]:
    code, out = nb.run_ps(_PS_LIST, timeout=30)
    if code != 0 and "[" not in out:
        raise RuntimeError(out or _("Impossible de lire les connexions VPN"))
    return parse_list(out)


# --------------------------------------------------------------------------- #
#  Validation et construction des commandes
# --------------------------------------------------------------------------- #
def validate(cfg: dict, existing_names: set[str] | None = None) -> tuple[list[str], list[str]]:
    errors, warns = [], []
    name = (cfg.get("name") or "").strip()
    if not name:
        errors.append(_("Nom de la connexion manquant"))
    elif any(c in name for c in '\\/:*?"<>|'):
        errors.append(_('Le nom ne peut pas contenir \\ / : * ? " < > |'))
    elif existing_names and name in existing_names:
        errors.append(_("Une connexion « {0} » existe déjà", name))
    if not (cfg.get("server") or "").strip():
        errors.append(_("Adresse du serveur manquante"))
    tunnel = cfg.get("tunnel", "Automatic")
    if tunnel not in TUNNEL_TYPES:
        errors.append(_("Type de tunnel inconnu : {0}", tunnel))
    if cfg.get("auth", "MSChapv2") not in AUTH_METHODS:
        errors.append(_("Méthode d'authentification inconnue : {0}", cfg.get('auth')))
    if cfg.get("encryption", "Required") not in ENCRYPTION:
        errors.append(_("Niveau de chiffrement inconnu : {0}", cfg.get('encryption')))
    if cfg.get("psk") and tunnel != "L2tp":
        errors.append(_("La clé pré-partagée ne s'utilise qu'avec L2TP/IPsec"))
    if tunnel == "Pptp":
        warns.append(_("PPTP est obsolète et peu sûr : préfère IKEv2 ou SSTP si le serveur le permet"))
    if cfg.get("encryption") == "NoEncryption":
        warns.append(_("Sans chiffrement, le trafic du VPN circule en clair"))
    if tunnel == "Ikev2" and cfg.get("auth") in ("Pap", "Chap", "MSChapv2"):
        warns.append(_("IKEv2 s'utilise en général avec EAP ou un certificat machine"))
    for r in cfg.get("routes") or []:
        try:
            ipaddress.ip_network(r.strip(), strict=False)
        except ValueError:
            errors.append(_("Route invalide : {0} (format attendu : 10.0.0.0/8)", r))
    if cfg.get("routes") and not cfg.get("split"):
        warns.append(_("Les routes ne servent qu'avec le split tunneling activé"))
    return errors, warns


def _q(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _common_params(cfg: dict) -> list[str]:
    p = [f"-ServerAddress {_q(cfg['server'].strip())}",
         f"-TunnelType {cfg.get('tunnel', 'Automatic')}",
         f"-AuthenticationMethod {cfg.get('auth', 'MSChapv2')}",
         f"-EncryptionLevel {cfg.get('encryption', 'Required')}",
         f"-SplitTunneling:${str(bool(cfg.get('split'))).lower()}",
         f"-RememberCredential:${str(bool(cfg.get('remember', True))).lower()}"]
    if (cfg.get("dns_suffix") or "").strip():
        p.append(f"-DnsSuffix {_q(cfg['dns_suffix'].strip())}")
    if cfg.get("tunnel") == "L2tp" and cfg.get("psk"):
        p.append(f"-L2tpPsk {_q(cfg['psk'])}")
    return p


def _scope(all_users: bool) -> str:
    return " -AllUserConnection" if all_users else ""


def _route_cmds(name: str, all_users: bool, add: list[str], remove: list[str]) -> list[str]:
    out = [f"Remove-VpnConnectionRoute -ConnectionName {_q(name)} -DestinationPrefix {_q(r)}{_scope(all_users)} "
           f"-Confirm:$false" for r in remove]
    out += [f"Add-VpnConnectionRoute -ConnectionName {_q(name)} -DestinationPrefix {_q(r)}{_scope(all_users)}"
            for r in add]
    return out


def build_create(cfg: dict) -> list[str]:
    name = cfg["name"].strip()
    cmds = [f"Add-VpnConnection -Name {_q(name)} " + " ".join(_common_params(cfg))
            + _scope(cfg.get("all_users", False)) + " -Force"]
    routes = [r.strip() for r in cfg.get("routes") or [] if r.strip()]
    cmds += _route_cmds(name, cfg.get("all_users", False), routes, [])
    return cmds


def build_update(old: Vpn, cfg: dict) -> list[str]:
    """Modifie une connexion existante. Le nom et la portée ne sont pas modifiables (contrainte Windows) :
    un renommage passe par une recréation (voir build_recreate)."""
    cmds = [f"Set-VpnConnection -Name {_q(old.name)} " + " ".join(_common_params(cfg))
            + _scope(old.all_users) + " -Force"]
    new_routes = [r.strip() for r in cfg.get("routes") or [] if r.strip()]
    cmds += _route_cmds(old.name, old.all_users, [r for r in new_routes if r not in old.routes],
                        [r for r in old.routes if r not in new_routes])
    return cmds


def build_recreate(old: Vpn, cfg: dict) -> list[str]:
    return [build_remove(old)] + build_create(cfg)


def build_remove(v: Vpn) -> str:
    return f"Remove-VpnConnection -Name {_q(v.name)}{_scope(v.all_users)} -Force"


def run_commands(cmds: list[str], log=print) -> bool:
    ok = True
    for c in cmds:
        log("PS> " + _mask_psk(c))
        code, out = nb.run_ps(c, timeout=60)
        if out:
            log(out)
        if code != 0:
            ok = False
            break
    return ok


def _mask_psk(cmd: str) -> str:
    """Le journal ne doit jamais contenir la clé pré-partagée."""
    return re.sub(r"-L2tpPsk '(?:[^']|'')*'", "-L2tpPsk '••••••'", cmd)


# --------------------------------------------------------------------------- #
#  Connexion / déconnexion
# --------------------------------------------------------------------------- #
RASDIAL_ERRORS = {
    "691": _("Identifiant ou mot de passe refusé"),
    "800": _("Le serveur VPN ne répond pas (adresse, pare-feu ou type de tunnel)"),
    "809": _("Connexion bloquée en chemin (NAT/pare-feu, ports IPsec UDP 500/4500)"),
    "789": _("Échec de la négociation L2TP/IPsec (clé pré-partagée ou certificat)"),
    "812": _("Connexion refusée par la stratégie du serveur"),
    "868": _("Nom du serveur introuvable (DNS)"),
    "13801": _("Certificat IKE invalide ou non approuvé"),
    "703": _("Identifiants requis : utilise « Connecter avec la fenêtre Windows » ou saisis-les"),
}


def connect(v: Vpn, user: str = "", password: str = "") -> tuple[bool, str]:
    args = ["rasdial", v.name]
    if user:
        args += [user, password]
    code, out = nb.run(args, timeout=90)
    if code == 0:
        return True, out
    hint = next((msg for num, msg in RASDIAL_ERRORS.items() if f" {num}" in f" {out}" or str(code) == num), "")
    return False, (f"{hint}\n{out}" if hint else out)


def connect_dialog(v: Vpn):
    """Ouvre la boîte de connexion Windows (saisie et mémorisation des identifiants par Windows)."""
    return nb.popen_stream(["rasphone", "-d", v.name])


def disconnect(v: Vpn) -> tuple[bool, str]:
    code, out = nb.run(["rasdial", v.name, "/disconnect"], timeout=30)
    return code == 0, out
