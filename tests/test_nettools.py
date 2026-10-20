import pytest

from netshift import nettools as nt


def test_parse_ports():
    assert nt.parse_ports("22, 80,440-443") == [22, 80, 440, 441, 442, 443]
    assert nt.parse_ports("443-440") == [440, 441, 442, 443]


@pytest.mark.parametrize("spec", ["", "0", "70000"])
def test_parse_ports_invalid(spec):
    with pytest.raises(ValueError):
        nt.parse_ports(spec)


def test_subnet_info():
    info = dict(nt.subnet_info("192.168.10.37/26"))
    assert info["Réseau"] == "192.168.10.0"
    assert info["Broadcast"] == "192.168.10.63"
    assert info["Première IP"] == "192.168.10.1"
    assert info["Dernière IP"] == "192.168.10.62"
    assert info["Hôtes utilisables"] == "62"


def test_subnet_info_with_mask():
    info = dict(nt.subnet_info("10.1.2.3", "255.255.252.0"))
    assert info["Réseau"] == "10.1.0.0"


def test_ping_localhost():
    r = nt.ping("127.0.0.1", 1000)
    assert r.ok and r.rtt is not None


def test_ping_unknown_host():
    r = nt.ping("does-not-exist.invalid", 500)
    assert not r.ok


@pytest.mark.parametrize("mac,vendor", [
    ("B8-27-EB-98-76-54", "Raspberry Pi Foundation"),
    ("00:0c:29:aa:bb:cc", "VMware"),
    ("0e-11-22-33-44-55", "Adresse privée (aléatoire)"),   # bit « administré localement »
    ("", ""),
    ("zz", ""),
])
def test_mac_vendor(mac, vendor):
    assert nt.mac_vendor(mac) == vendor
