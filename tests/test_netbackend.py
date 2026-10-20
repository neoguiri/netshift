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


@pytest.mark.parametrize("args,kind", [
    (("Ethernet", "Intel(R) Ethernet Connection I219-LM", "802.3", "802.3", 6), "ethernet"),
    (("Wi-Fi", "Intel(R) Wi-Fi 6E AX211 160MHz", "Native 802.11", "Native 802.11", 71), "wifi"),
    (("Connexion réseau Bluetooth", "Bluetooth Device (Personal Area Network)", "802.3", "BlueTooth", 6), "bluetooth"),
    (("wg0", "WireGuard Tunnel", "", "Unspecified", 53), "vpn"),
    (("Ethernet 3", "TAP-Windows Adapter V9", "802.3", "Unspecified", 6), "vpn"),
    (("Ethernet 4", "Cisco AnyConnect Secure Mobility Client Virtual Miniport Adapter", "802.3", "", 6), "vpn"),
    (("vEthernet (WSL)", "Hyper-V Virtual Ethernet Adapter", "802.3", "Unspecified", 6), "virtual"),
    (("Ethernet", "Parallels VirtIO Ethernet Adapter", "802.3", "Unspecified", 6), "virtual"),
    (("Cellular", "Generic Mobile Broadband Adapter", "Wireless WAN", "Wireless WAN", 243), "mobile"),
    (("Bizarre", "Something", "", "", 1), "other"),
])
def test_classify(args, kind):
    assert nb.classify(*args) == kind
    assert kind in nb.KINDS


def test_advanced_options_commands():
    base = {"mode": "dhcp", "dns_mode": "auto", "adv": True, "metric": "15", "dns_suffix": "corp.example"}
    cmds = nb.build_commands(make_adapter(), base)
    assert "Set-NetIPInterface -InterfaceIndex 12 -AddressFamily IPv4 -InterfaceMetric 15" in cmds
    assert "Set-DnsClient -InterfaceIndex 12 -ConnectionSpecificSuffix 'corp.example'" in cmds
    auto = nb.build_commands(make_adapter(), {**base, "metric": "auto", "dns_suffix": ""})
    assert "Set-NetIPInterface -InterfaceIndex 12 -AddressFamily IPv4 -AutomaticMetric Enabled" in auto
    assert "Set-DnsClient -InterfaceIndex 12 -ConnectionSpecificSuffix ''" in auto
    assert all(isinstance(c, list) for c in nb.build_commands(make_adapter(), {**base, "adv": False}))


@pytest.mark.parametrize("metric,suffix,ok", [
    ("auto", "", True), ("1", "corp.example", True), ("9999", "a-b.c", True),
    ("0", "", False), ("abc", "", False), ("10", "bad suffix", False), ("10", "-x.com", False),
])
def test_advanced_options_validation(metric, suffix, ok):
    errors, _ = nb.validate_config({"mode": "dhcp", "dns_mode": "auto", "adv": True, "metric": metric,
                                    "dns_suffix": suffix})
    assert (not errors) == ok, errors


def test_to_config_includes_advanced():
    a = make_adapter(metric=25, auto_metric=False, dns_suffix="lab.local")
    cfg = a.to_config()
    assert cfg["adv"] and cfg["metric"] == "25" and cfg["dns_suffix"] == "lab.local"
    assert make_adapter().to_config()["metric"] == "auto"
