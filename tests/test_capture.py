import socket
import struct

import pytest

from netshift import capture as cap


def ipv4(src, dst, proto, payload, ttl=64, ident=0x1234):
    total = 20 + len(payload)
    hdr = struct.pack("!BBHHHBBH4s4s", 0x45, 0, total, ident, 0x4000, ttl, proto, 0,
                      socket.inet_aton(src), socket.inet_aton(dst))
    return hdr + payload


def tcp(sport, dport, flags, data=b"", seq=1000, ack=0):
    return struct.pack("!HHIIHHHH", sport, dport, seq, ack, (5 << 12) | flags, 64240, 0, 0) + data


def udp(sport, dport, data=b""):
    return struct.pack("!HHHH", sport, dport, 8 + len(data), 0) + data


def dns_query(name, qtype=1, tid=0xBEEF):
    q = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    return struct.pack("!HHHHHH", tid, 0x0100, 1, 0, 0, 0) + q + struct.pack("!HH", qtype, 1)


SYN = ipv4("192.168.1.10", "93.184.216.34", 6, tcp(51000, 443, 0x02))
RST = ipv4("93.184.216.34", "192.168.1.10", 6, tcp(443, 51000, 0x14))
HTTP_GET = ipv4("192.168.1.10", "192.168.1.20", 6, tcp(51001, 80, 0x18, b"GET /index.html HTTP/1.1\r\nHost: x\r\n\r\n"))
DNS = ipv4("192.168.1.10", "192.168.1.1", 17, udp(53000, 53, dns_query("example.com")))
PING = ipv4("192.168.1.10", "192.168.1.1", 1, struct.pack("!BBHHH", 8, 0, 0, 0x0001, 7) + b"abcd")


def test_decode_tcp_syn():
    p = cap.decode(SYN, 1)
    assert (p.src, p.dst, p.sport, p.dport) == ("192.168.1.10", "93.184.216.34", 51000, 443)
    assert p.transport == "TCP" and p.proto == "TLS" and p.flags == ["SYN"]
    assert "[SYN]" in p.info


def test_decode_http_request_line():
    p = cap.decode(HTTP_GET)
    assert p.proto == "HTTP" and p.info == "GET /index.html HTTP/1.1"


def test_decode_dns_query():
    p = cap.decode(DNS)
    assert p.proto == "DNS"
    assert p.info == "Requête DNS 0xbeef A example.com"


def test_decode_icmp_echo():
    p = cap.decode(PING)
    assert p.proto == "ICMP" and p.info.startswith("Echo request") and "seq=7" in p.info


def test_decode_garbage():
    assert cap.decode(b"\x00\x01").info == "Paquet non IPv4"


@pytest.mark.parametrize("expr,expected", [
    ("tcp", [True, True, True, False, False]),
    ("udp", [False, False, False, True, False]),
    ("dns", [False, False, False, True, False]),
    ("port 443", [True, True, False, False, False]),
    ("443", [True, True, False, False, False]),
    ("rst", [False, True, False, False, False]),
    ("not tcp", [False, False, False, True, True]),
    ("!icmp tcp", [True, True, True, False, False]),
    ("host 192.168.1.20", [False, False, True, False, False]),
    ("dst 192.168.1.1", [False, False, False, True, True]),
    ("93.184.0.0/16", [True, True, False, False, False]),
    ("example.com", [False, False, False, True, False]),
    ("", [True] * 5),
])
def test_filters(expr, expected):
    f = cap.compile_filter(expr)
    pkts = [cap.decode(r) for r in (SYN, RST, HTTP_GET, DNS, PING)]
    assert [f(p) for p in pkts] == expected


@pytest.mark.parametrize("expr", ["port abc", "host", "not", "host 999.1.1.1"])
def test_filter_errors(expr):
    with pytest.raises(cap.FilterError):
        cap.compile_filter(expr)


def test_pcap_roundtrip(tmp_path):
    pkts = [cap.decode(r, i, 1_700_000_000.123456 + i) for i, r in enumerate((SYN, DNS, PING), 1)]
    path = tmp_path / "t.pcap"
    assert cap.write_pcap(str(path), pkts) == 3
    data = path.read_bytes()
    assert struct.unpack("<IHHiIII", data[:24])[6] == cap.LINKTYPE_RAW
    assert cap.read_pcap(str(path)) == [SYN, DNS, PING]


def test_hexdump():
    out = cap.hexdump(b"ABC\x00" * 5)
    assert out.splitlines()[0].startswith("0000  41 42 43 00")
    assert out.splitlines()[1].startswith("0010")


def test_npcap_interface():
    assert cap.npcap_interface("{ABC}") == "\\Device\\NPF_{ABC}"


# ----------------------------------------------------------------- v1.1 : or, fichiers, statistiques
ETH_HDR = bytes.fromhex("ffffffffffff" "020000000001")


def eth(ethertype, payload, vlan=None):
    tag = struct.pack("!HH", 0x8100, vlan) if vlan is not None else b""
    return ETH_HDR + tag + struct.pack("!H", ethertype) + payload


ARP_REQ = struct.pack("!HHBBH6s4s6s4s", 1, 0x0800, 6, 4, 1, bytes.fromhex("020000000001"),
                      socket.inet_aton("192.168.1.10"), b"\x00" * 6, socket.inet_aton("192.168.1.1"))
IPV6_TCP = (struct.pack("!IHBB", 0x60000000, 20, 6, 64) + socket.inet_pton(socket.AF_INET6, "fe80::1")
            + socket.inet_pton(socket.AF_INET6, "fe80::2") + tcp(50000, 22, 0x02))


@pytest.mark.parametrize("expr,expected", [
    ("dns or icmp", [False, False, False, True, True]),
    ("rst or port 80", [False, True, True, False, False]),
    ("udp or host 192.168.1.20 not port 80", [False, False, False, True, False]),
])
def test_filters_or(expr, expected):
    f = cap.compile_filter(expr)
    assert [f(cap.decode(r)) for r in (SYN, RST, HTTP_GET, DNS, PING)] == expected


@pytest.mark.parametrize("expr", ["or tcp", "tcp or", "tcp or or udp"])
def test_filter_or_errors(expr):
    with pytest.raises(cap.FilterError):
        cap.compile_filter(expr)


def test_decode_frame_ethernet_vlan_arp_ipv6():
    p = cap.decode_frame(eth(0x0800, SYN, vlan=20), 1)
    assert p.proto == "TLS" and p.info.startswith("[VLAN 20]") and ("VLAN", "20") in p.details
    a = cap.decode_frame(eth(0x0806, ARP_REQ), 1)
    assert a.proto == "ARP" and a.info == "Qui a 192.168.1.1 ? Répondre à 192.168.1.10" and not a.exportable
    v6 = cap.decode_frame(eth(0x86DD, IPV6_TCP), 1)
    assert v6.src == "fe80::1" and v6.proto == "SSH" and v6.flags == ["SYN"]
    assert cap.compile_filter("arp")(a) and cap.compile_filter("port 22")(v6)


def _pcap_le(frames, linktype=1, nano=False):
    out = struct.pack("<IHHiIII", 0xA1B23C4D if nano else 0xA1B2C3D4, 2, 4, 0, 0, 65535, linktype)
    for i, fr in enumerate(frames):
        out += struct.pack("<IIII", 1_700_000_000 + i, 500 if nano else 250_000, len(fr), len(fr)) + fr
    return out


def test_read_pcap_ethernet(tmp_path):
    path = tmp_path / "eth.pcap"
    path.write_bytes(_pcap_le([eth(0x0800, DNS), eth(0x0806, ARP_REQ)]))
    rows = cap.read_capture_file(str(path))
    assert [lt for _, lt, _ in rows] == [1, 1]
    assert rows[0][0] == pytest.approx(1_700_000_000.25)
    assert cap.decode_frame(rows[0][2], rows[0][1]).proto == "DNS"


def test_read_pcap_nanoseconds(tmp_path):
    path = tmp_path / "ns.pcap"
    path.write_bytes(_pcap_le([SYN], linktype=cap.LINKTYPE_RAW, nano=True))
    ts, lt, frame = cap.read_capture_file(str(path))[0]
    assert lt == cap.LINKTYPE_RAW and frame == SYN and ts == pytest.approx(1_700_000_000 + 500e-9)


def _block(btype, body):
    pad = body + b"\x00" * (-len(body) % 4)
    n = 12 + len(pad)
    return struct.pack("<II", btype, n) + pad + struct.pack("<I", n)


def test_read_pcapng(tmp_path):
    shb = _block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
    idb = _block(1, struct.pack("<HHI", 1, 0, 65535))
    frame = eth(0x0800, PING)
    ts_us = 1_700_000_000_500_000
    epb = _block(6, struct.pack("<IIIII", 0, ts_us >> 32, ts_us & 0xFFFFFFFF, len(frame), len(frame)) + frame)
    path = tmp_path / "t.pcapng"
    path.write_bytes(shb + idb + epb)
    (ts, lt, data), = cap.read_capture_file(str(path))
    assert lt == 1 and ts == pytest.approx(1_700_000_000.5)
    assert cap.decode_frame(data, lt).info.startswith("Echo request")


def test_read_capture_rejects_garbage(tmp_path):
    path = tmp_path / "x.pcap"
    path.write_bytes(b"not a capture file at all....")
    with pytest.raises(ValueError):
        cap.read_capture_file(str(path))


def test_export_skips_non_ipv4(tmp_path):
    pkts = [cap.decode(SYN, 1), cap.decode_frame(eth(0x0806, ARP_REQ), 2)]
    assert cap.write_pcap(str(tmp_path / "o.pcap"), pkts) == 1


def test_statistics():
    pkts = [cap.decode(r) for r in (SYN, RST, HTTP_GET, DNS, PING)]
    st = cap.statistics(pkts)
    assert st["packets"] == 5
    assert st["conversations"][0] == (("192.168.1.1", "192.168.1.10"), 2, 89)   # DNS + ping
    assert st["conversations"][1] == (("192.168.1.10", "93.184.216.34"), 2, 80)  # SYN + RST
    assert {h for h, _, _ in st["hosts"]} >= {"192.168.1.10", "192.168.1.1"}
    assert cap.human_bytes(1500) == "1.5 ko"
