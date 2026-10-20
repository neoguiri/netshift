import pytest

from netshift import netbackend as nb


def make_adapter(**kw):
    base = dict(name="Ethernet", description="Test NIC", status="Up", mac="00-11-22-33-44-55", speed="1 Gbps",
                index=12, guid="{guid}", virtual=False, dhcp=False, dns_static=True, mtu=1500,
                ips=[nb.IPAddr("192.168.1.10", 24, "Manual")], gateways=["192.168.1.1"], dns=["1.1.1.1", "8.8.8.8"])
    base.update(kw)
    return nb.Adapter(**base)


@pytest.mark.parametrize("value,prefix", [("24", 24), ("/16", 16), ("255.255.255.0", 24), ("255.255.252.0", 22),
                                          ("0", 0), ("32", 32)])
def test_parse_mask(value, prefix):
    assert nb.parse_mask(value) == prefix


@pytest.mark.parametrize("value", ["", "33", "255.0.255.0", "abc"])
def test_parse_mask_invalid(value):
    with pytest.raises(ValueError):
        nb.parse_mask(value)


def test_prefix_to_mask():
    assert nb.prefix_to_mask(24) == "255.255.255.0"
    assert nb.prefix_to_mask(20) == "255.255.240.0"


def test_validate_ok():
    errors, warns = nb.validate_config({"mode": "static", "ip": "10.0.0.5", "mask": "24", "gateway": "10.0.0.1",
                                        "dns1": "1.1.1.1"})
    assert errors == [] and warns == []


def test_validate_network_address_and_foreign_gateway():
    errors, warns = nb.validate_config({"mode": "static", "ip": "10.0.0.0", "mask": "24", "gateway": "192.168.0.1"})
    assert any("réseau ou broadcast" in e for e in errors)
    assert any("pas dans le sous-réseau" in w for w in warns)


def test_validate_bad_dns():
    errors, _ = nb.validate_config({"mode": "dhcp", "dns_mode": "static", "dns1": "999.1.1.1"})
    assert errors


def test_build_commands_static():
    cmds = nb.build_commands(make_adapter(), {"mode": "static", "ip": "192.168.1.50", "mask": "/24",
                                              "gateway": "192.168.1.1", "dns1": "1.1.1.1", "dns2": "9.9.9.9",
                                              "extra_ips": ["10.0.0.5/8"]})
    flat = [" ".join(c) for c in cmds]
    assert flat[0] == ("netsh interface ipv4 set address name=12 source=static address=192.168.1.50 "
                       "mask=255.255.255.0 gateway=192.168.1.1 gwmetric=0")
    assert "add address name=12 address=10.0.0.5 mask=255.0.0.0" in flat[1]
    assert "set dnsservers name=12 source=static address=1.1.1.1" in flat[2]
    assert "add dnsservers name=12 address=9.9.9.9 index=2" in flat[3]


def test_build_commands_static_without_gateway():
    cmds = nb.build_commands(make_adapter(), {"mode": "static", "ip": "10.0.0.10", "mask": "24"})
    assert "gateway=none" in cmds[0]
    assert "address=none" in cmds[1]


def test_build_commands_dhcp():
    cmds = nb.build_commands(make_adapter(), {"mode": "dhcp", "dns_mode": "auto"})
    assert [" ".join(c) for c in cmds] == [
        "netsh interface ipv4 set address name=12 source=dhcp",
        "netsh interface ipv4 set dnsservers name=12 source=dhcp",
    ]


def test_build_commands_dhcp_with_manual_dns():
    cmds = nb.build_commands(make_adapter(), {"mode": "dhcp", "dns_mode": "static", "dns1": "1.1.1.1"})
    assert "source=static" in cmds[1] and "address=1.1.1.1" in cmds[1]


def test_adapter_to_config_roundtrip():
    a = make_adapter(ips=[nb.IPAddr("192.168.1.10", 24), nb.IPAddr("10.0.0.5", 8)])
    cfg = a.to_config()
    assert cfg["mode"] == "static" and cfg["ip"] == "192.168.1.10" and cfg["mask"] == "255.255.255.0"
    assert cfg["extra_ips"] == ["10.0.0.5/8"]
    assert nb.validate_config(cfg) == ([], [])


def test_primary_ip_skips_apipa():
    a = make_adapter(ips=[nb.IPAddr("169.254.3.4", 16), nb.IPAddr("192.168.1.10", 24)])
    assert a.primary_ip.ip == "192.168.1.10"
