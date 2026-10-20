import json

import pytest

from netshift import vpn

SAMPLE = json.dumps([
    {"name": "Bureau", "server": "vpn.example.com", "tunnel": "Ikev2", "auth": ["Eap"], "encryption": "Required",
     "split": True, "remember": True, "dns_suffix": "corp.example", "all_users": False, "status": "Disconnected",
     "idle": 0, "routes": ["10.0.0.0/8", "172.16.0.0/12"], "ips": []},
    {"name": "Labo", "server": "203.0.113.10", "tunnel": "L2tp", "auth": "MSChapv2", "encryption": "Optional",
     "split": False, "remember": False, "dns_suffix": "", "all_users": True, "status": "Connected",
     "idle": 600, "routes": None, "ips": "10.8.0.6/32"},
])


def cfg(**kw):
    base = {"name": "Bureau", "server": "vpn.example.com", "tunnel": "Sstp", "auth": "MSChapv2",
            "encryption": "Required", "split": False, "remember": True, "dns_suffix": "", "all_users": False,
            "routes": [], "psk": ""}
    base.update(kw)
    return base


def test_parse_list_sorts_connected_first_and_normalizes():
    vs = vpn.parse_list("garbage before json " + SAMPLE)
    assert [v.name for v in vs] == ["Labo", "Bureau"]
    labo, bureau = vs
    assert labo.connected and labo.all_users and labo.ips == ["10.8.0.6/32"] and labo.routes == []
    assert bureau.auth == "Eap" and bureau.split and bureau.routes == ["10.0.0.0/8", "172.16.0.0/12"]
    assert labo.key != vpn.Vpn("Labo", "x").key  # même nom, portée différente


def test_parse_empty():
    assert vpn.parse_list("[]") == []
    assert vpn.parse_list("") == []


def test_validate_ok():
    assert vpn.validate(cfg()) == ([], [])


@pytest.mark.parametrize("kw,expected", [
    ({"name": ""}, "Nom de la connexion manquant"),
    ({"name": "a/b"}, "Le nom ne peut pas contenir"),
    ({"server": " "}, "Adresse du serveur manquante"),
    ({"tunnel": "OpenVPN"}, "Type de tunnel inconnu"),
    ({"psk": "secret"}, "clé pré-partagée"),
    ({"routes": ["10.0.0.0/33"], "split": True}, "Route invalide"),
])
def test_validate_errors(kw, expected):
    errors, _ = vpn.validate(cfg(**kw))
    assert any(expected in e for e in errors), errors


def test_validate_duplicate_name():
    errors, _ = vpn.validate(cfg(), existing_names={"Bureau"})
    assert any("existe déjà" in e for e in errors)


def test_validate_warnings():
    _, warns = vpn.validate(cfg(tunnel="Pptp", encryption="NoEncryption", routes=["10.0.0.0/8"]))
    assert any("PPTP" in w for w in warns)
    assert any("en clair" in w for w in warns)
    assert any("split tunneling" in w for w in warns)


def test_build_create_with_routes_and_scope():
    cmds = vpn.build_create(cfg(name="O'Neil VPN", split=True, routes=["10.0.0.0/8"], all_users=True,
                                dns_suffix="corp.example"))
    assert cmds[0].startswith("Add-VpnConnection -Name 'O''Neil VPN' -ServerAddress 'vpn.example.com'")
    assert "-SplitTunneling:$true" in cmds[0] and "-RememberCredential:$true" in cmds[0]
    assert "-DnsSuffix 'corp.example'" in cmds[0] and cmds[0].endswith("-AllUserConnection -Force")
    assert cmds[1] == "Add-VpnConnectionRoute -ConnectionName 'O''Neil VPN' -DestinationPrefix '10.0.0.0/8' -AllUserConnection"


def test_build_create_l2tp_psk_masked_in_log():
    cmds = vpn.build_create(cfg(tunnel="L2tp", psk="s3cr'et"))
    assert "-L2tpPsk 's3cr''et'" in cmds[0]
    masked = vpn._mask_psk(cmds[0])
    assert "s3cr" not in masked and "-L2tpPsk '••••••'" in masked and masked.endswith("-Force")


def test_build_update_diffs_routes():
    old = vpn.Vpn("Bureau", "vpn.example.com", split=True, routes=["10.0.0.0/8", "192.168.50.0/24"])
    cmds = vpn.build_update(old, cfg(split=True, routes=["10.0.0.0/8", "172.16.0.0/12"]))
    assert cmds[0].startswith("Set-VpnConnection -Name 'Bureau'")
    assert any(c.startswith("Remove-VpnConnectionRoute") and "192.168.50.0/24" in c for c in cmds)
    assert any(c.startswith("Add-VpnConnectionRoute") and "172.16.0.0/12" in c for c in cmds)
    assert not any("'10.0.0.0/8'" in c for c in cmds[1:])


def test_build_remove_and_recreate():
    old = vpn.Vpn("Old", "a", all_users=True)
    assert vpn.build_remove(old) == "Remove-VpnConnection -Name 'Old' -AllUserConnection -Force"
    cmds = vpn.build_recreate(old, cfg(name="New"))
    assert cmds[0].startswith("Remove-VpnConnection -Name 'Old'") and cmds[1].startswith("Add-VpnConnection -Name 'New'")


def test_connect_error_hint(monkeypatch):
    monkeypatch.setattr(vpn.nb, "run", lambda args, timeout=0: (691, "Erreur distante 691 : accès refusé"))
    ok, msg = vpn.connect(vpn.Vpn("Bureau", "x"), "user", "pw")
    assert not ok and msg.startswith("Identifiant ou mot de passe refusé")


def test_connect_passes_credentials(monkeypatch):
    seen = {}
    monkeypatch.setattr(vpn.nb, "run", lambda args, timeout=0: (seen.setdefault("args", args), (0, "Connecté"))[1])
    assert vpn.connect(vpn.Vpn("Bureau", "x"), "alice", "pw") == (True, "Connecté")
    assert seen["args"] == ["rasdial", "Bureau", "alice", "pw"]
