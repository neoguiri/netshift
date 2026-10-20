"""Capture de paquets IPv4 légère (socket brut Windows), décodage, filtres, export pcap, lancement de Wireshark."""
from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from .i18n import _

PROTO_NAMES = {1: "ICMP", 2: "IGMP", 6: "TCP", 17: "UDP", 47: "GRE", 50: "ESP", 58: "ICMPv6", 89: "OSPF", 132: "SCTP"}
TCP_FLAGS = [(0x01, "FIN"), (0x02, "SYN"), (0x04, "RST"), (0x08, "PSH"), (0x10, "ACK"), (0x20, "URG")]
ICMP_TYPES = {0: "Echo reply", 3: "Destination unreachable", 5: "Redirect", 8: "Echo request", 11: "Time exceeded"}
WELL_KNOWN = {20: "FTP-data", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 67: "DHCP", 68: "DHCP",
              69: "TFTP", 80: "HTTP", 123: "NTP", 137: "NetBIOS-NS", 138: "NetBIOS-DGM", 139: "NetBIOS", 161: "SNMP",
              162: "SNMP-trap", 389: "LDAP", 443: "TLS", 445: "SMB", 502: "Modbus", 514: "Syslog", 1900: "SSDP",
              3389: "RDP", 5353: "mDNS", 5355: "LLMNR", 8080: "HTTP"}
DNS_TYPES = {1: "A", 2: "NS", 5: "CNAME", 6: "SOA", 12: "PTR", 15: "MX", 16: "TXT", 28: "AAAA", 33: "SRV", 65: "HTTPS"}


# --------------------------------------------------------------------------- #
#  Décodage
# --------------------------------------------------------------------------- #
@dataclass
class Packet:
    no: int
    ts: float                    # horodatage absolu (epoch)
    raw: bytes                   # datagramme IP complet
    src: str = ""
    dst: str = ""
    proto: str = ""              # TCP, UDP, ICMP, DNS, TLS…
    transport: str = ""          # TCP / UDP / ICMP / autre
    sport: int | None = None
    dport: int | None = None
    ttl: int = 0
    length: int = 0
    info: str = ""
    flags: list[str] = field(default_factory=list)
    details: list[tuple[str, str]] = field(default_factory=list)
    exportable: bool = True      # False : trame non IPv4 (ARP, IPv6…) issue d'un fichier ouvert


def decode(raw: bytes, no: int = 0, ts: float | None = None) -> Packet:
    p = Packet(no=no, ts=time.time() if ts is None else ts, raw=raw, length=len(raw))
    if len(raw) < 20 or raw[0] >> 4 != 4:
        p.proto = p.transport = "?"
        p.info = _("Paquet non IPv4")
        return p
    ihl = (raw[0] & 0x0F) * 4
    total_len, ident, frag, ttl, proto_num = struct.unpack("!HHHBB", raw[2:10])
    p.src, p.dst = socket.inet_ntoa(raw[12:16]), socket.inet_ntoa(raw[16:20])
    p.ttl = ttl
    p.length = total_len or len(raw)
    p.transport = PROTO_NAMES.get(proto_num, f"IP/{proto_num}")
    p.proto = p.transport
    payload = raw[ihl:]
    p.details = [
        ("IPv4", f"{p.src} → {p.dst}"),
        ("Longueur totale", str(p.length)),
        ("TTL", str(ttl)),
        ("Identification", f"0x{ident:04x}"),
        ("Fragment", f"DF={(frag >> 14) & 1} MF={(frag >> 13) & 1} offset={frag & 0x1FFF}"),
        ("Protocole", f"{p.transport} ({proto_num})"),
    ]
    if frag & 0x1FFF:
        p.info = f"Fragment IP (offset {(frag & 0x1FFF) * 8})"
        return p

    if proto_num == 6 and len(payload) >= 20:
        sport, dport, seq, ack, off_flags, win = struct.unpack("!HHIIHH", payload[:16])
        hlen = (off_flags >> 12) * 4
        fl = off_flags & 0x3F
        p.sport, p.dport = sport, dport
        p.flags = [n for bit, n in TCP_FLAGS if fl & bit]
        data_len = max(0, len(payload) - hlen)
        p.proto = _app_proto(sport, dport, "TCP")
        p.info = f"{sport} → {dport} [{', '.join(p.flags) or '—'}] seq={seq} ack={ack} win={win} len={data_len}"
        if p.proto == "TLS" and data_len and payload[hlen:hlen + 1] == b"\x16":
            p.info += "  (TLS handshake)"
        elif p.proto == "HTTP" and data_len:
            first = payload[hlen:hlen + 80].split(b"\r\n", 1)[0]
            if first[:4] in (b"GET ", b"POST", b"HTTP", b"PUT ", b"HEAD", b"DELE", b"OPTI"):
                p.info = first.decode("latin-1", errors="replace")
        p.details += [("TCP", f"{sport} → {dport}"), ("Flags", " ".join(p.flags) or "—"),
                      (_("Séquence / ACK"), f"{seq} / {ack}"), (_("Fenêtre"), str(win)),
                      (_("Données"), _("{0} octets", data_len))]
    elif proto_num == 17 and len(payload) >= 8:
        sport, dport, ulen = struct.unpack("!HHH", payload[:6])
        p.sport, p.dport = sport, dport
        p.proto = _app_proto(sport, dport, "UDP")
        data = payload[8:]
        p.info = f"{sport} → {dport} len={max(0, ulen - 8)}"
        if p.proto in ("DNS", "mDNS", "LLMNR"):
            dns = _dns_summary(data)
            if dns:
                p.info = dns
        p.details += [("UDP", f"{sport} → {dport}"), ("Longueur UDP", str(ulen))]
    elif proto_num == 1 and len(payload) >= 4:
        t, code = payload[0], payload[1]
        name = ICMP_TYPES.get(t, f"type {t}")
        p.info = f"{name}" + (f" (code {code})" if code else "")
        if t in (0, 8) and len(payload) >= 8:
            ident_i, seq_i = struct.unpack("!HH", payload[4:8])
            p.info += f" id=0x{ident_i:04x} seq={seq_i} ttl={ttl}"
        p.details += [("ICMP", f"type {t}, code {code} — {name}")]
    else:
        p.info = f"{p.transport} {len(payload)} octets"
    return p


def _app_proto(sport: int, dport: int, transport: str) -> str:
    for port in (min(sport, dport), max(sport, dport)):
        name = WELL_KNOWN.get(port)
        if name:
            return name
    return transport


def _dns_name(data: bytes, off: int, depth: int = 0) -> tuple[str, int]:
    labels = []
    while off < len(data) and depth < 10:
        n = data[off]
        if n == 0:
            return ".".join(labels), off + 1
        if n & 0xC0 == 0xC0:
            if off + 1 >= len(data):
                break
            ptr = ((n & 0x3F) << 8) | data[off + 1]
            name, _end = _dns_name(data, ptr, depth + 1)
            labels.append(name)
            return ".".join(labels), off + 2
        labels.append(data[off + 1:off + 1 + n].decode("ascii", errors="replace"))
        off += 1 + n
    return ".".join(labels), off


def _dns_summary(data: bytes) -> str:
    if len(data) < 12:
        return ""
    tid, flags, qd, an = struct.unpack("!HHHH", data[:8])
    if not qd:
        return ""
    try:
        name, off = _dns_name(data, 12)
        qtype = struct.unpack("!H", data[off:off + 2])[0] if off + 2 <= len(data) else 0
    except (IndexError, struct.error):
        return ""
    kind = _("Réponse") if flags & 0x8000 else _("Requête")
    rtype = DNS_TYPES.get(qtype, str(qtype))
    rcode = flags & 0x000F
    tail = _(" ({0} réponse(s))", an) if flags & 0x8000 and not rcode else (" NXDOMAIN" if rcode == 3 else "")
    return _("{0} DNS 0x{1:04x} {2} {3}{4}", kind, tid, rtype, name, tail)


ETHERTYPES = {0x0800: "IPv4", 0x0806: "ARP", 0x86DD: "IPv6", 0x8100: "VLAN", 0x88CC: "LLDP", 0x8899: "Realtek",
              0x88E1: "HomePlug", 0x8863: "PPPoE", 0x8864: "PPPoE", 0x88F7: "PTP", 0x8892: "PROFINET"}
IPV6_NEXT = {6: "TCP", 17: "UDP", 58: "ICMPv6", 0: "Hop-by-hop", 43: "Routing", 44: "Fragment"}


def _mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def decode_frame(frame: bytes, linktype: int, no: int = 0, ts: float | None = None) -> Packet:
    """Décode une trame lue dans un fichier (Ethernet, IP brut, Linux SLL)."""
    vlan = None
    if linktype in (LINKTYPE_RAW, 12, 14, 228):          # IP brut (IPv4 ou IPv6)
        payload, ethertype = frame, 0x0800 if frame[:1] and frame[0] >> 4 == 4 else 0x86DD
    elif linktype == 113 and len(frame) >= 16:           # Linux cooked capture
        payload, ethertype = frame[16:], struct.unpack("!H", frame[14:16])[0]
    elif linktype == 1 and len(frame) >= 14:             # Ethernet
        ethertype, off = struct.unpack("!H", frame[12:14])[0], 14
        while ethertype in (0x8100, 0x88A8) and len(frame) >= off + 4:
            vlan = struct.unpack("!H", frame[off:off + 2])[0] & 0x0FFF
            ethertype = struct.unpack("!H", frame[off + 2:off + 4])[0]
            off += 4
        payload = frame[off:]
    else:
        p = Packet(no=no, ts=time.time() if ts is None else ts, raw=frame, length=len(frame), proto="?",
                   transport="?", info=_("Type de lien {0} non pris en charge", linktype), exportable=False)
        return p

    if ethertype == 0x0800:
        p = decode(payload, no, ts)
    elif ethertype == 0x0806 and len(payload) >= 28:
        op = struct.unpack("!H", payload[6:8])[0]
        sha, spa, tha, tpa = payload[8:14], payload[14:18], payload[18:24], payload[24:28]
        src, dst = socket.inet_ntoa(spa), socket.inet_ntoa(tpa)
        info = (_("Qui a {0} ? Répondre à {1}", dst, src) if op == 1 else _("{0} est à {1}", src, _mac(sha))
                if op == 2 else _("ARP opération {0}", op))
        p = Packet(no=no, ts=time.time() if ts is None else ts, raw=payload, src=src, dst=dst, proto="ARP",
                   transport="ARP", length=len(frame), info=info, exportable=False,
                   details=[("ARP", _("requête") if op == 1 else _("réponse") if op == 2 else str(op)),
                            (_("Émetteur"), f"{src} ({_mac(sha)})"), (_("Cible"), f"{dst} ({_mac(tha)})")])
    elif ethertype == 0x86DD and len(payload) >= 40:
        nxt, hop = payload[6], payload[7]
        src = socket.inet_ntop(socket.AF_INET6, payload[8:24])
        dst = socket.inet_ntop(socket.AF_INET6, payload[24:40])
        tname = IPV6_NEXT.get(nxt, f"IPv6/{nxt}")
        p = Packet(no=no, ts=time.time() if ts is None else ts, raw=payload, src=src, dst=dst, proto=tname,
                   transport=tname, ttl=hop, length=len(frame), exportable=False)
        body = payload[40:]
        if nxt in (6, 17) and len(body) >= 4:
            p.sport, p.dport = struct.unpack("!HH", body[:4])
            p.proto = _app_proto(p.sport, p.dport, tname)
            if nxt == 6 and len(body) >= 14:
                p.flags = [n for bit, n in TCP_FLAGS if body[13] & bit]
            p.info = f"{p.sport} → {p.dport}" + (f" [{', '.join(p.flags)}]" if p.flags else "")
        else:
            p.info = f"IPv6 {tname}"
        p.details = [("IPv6", f"{src} → {dst}"), ("Hop limit", str(hop)), (_("En-tête suivant"), tname)]
    else:
        name = ETHERTYPES.get(ethertype, f"0x{ethertype:04x}")
        src = _mac(frame[6:12]) if linktype == 1 else ""
        dst = _mac(frame[0:6]) if linktype == 1 else ""
        p = Packet(no=no, ts=time.time() if ts is None else ts, raw=payload, src=src, dst=dst, proto=name,
                   transport=name, length=len(frame), info=f"Trame {name}", exportable=False)
    if linktype == 1 and len(frame) >= 12:
        p.details.insert(0, ("Ethernet", f"{_mac(frame[6:12])} → {_mac(frame[0:6])}"))
    if vlan is not None:
        p.details.insert(1, ("VLAN", str(vlan)))
        p.info = f"[VLAN {vlan}] {p.info}"
    p.length = len(frame)
    return p


def read_capture_file(path: str) -> list[tuple[float, int, bytes]]:
    """Lit un fichier pcap (µs/ns, les deux boutismes) ou pcapng. Renvoie [(horodatage, linktype, trame)]."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 24:
        raise ValueError("Fichier trop court")
    if data[:4] == b"\x0a\x0d\x0d\x0a":
        return _read_pcapng(data)
    magic = data[:4]
    formats = {b"\xd4\xc3\xb2\xa1": ("<", 1e-6), b"\xa1\xb2\xc3\xd4": (">", 1e-6),
               b"\x4d\x3c\xb2\xa1": ("<", 1e-9), b"\xa1\xb2\x3c\x4d": (">", 1e-9)}
    if magic not in formats:
        raise ValueError(_("Format non reconnu (pcap ou pcapng attendu)"))
    e, unit = formats[magic]
    linktype = struct.unpack(e + "I", data[20:24])[0] & 0x0FFFFFFF
    off, out = 24, []
    while off + 16 <= len(data):
        sec, frac, incl, _orig = struct.unpack(e + "IIII", data[off:off + 16])
        out.append((sec + frac * unit, linktype, data[off + 16:off + 16 + incl]))
        off += 16 + incl
    return out


def _read_pcapng(data: bytes) -> list[tuple[float, int, bytes]]:
    out: list[tuple[float, int, bytes]] = []
    ifaces: list[tuple[int, float]] = []   # (linktype, résolution)
    e, off = "<", 0
    while off + 12 <= len(data):
        btype = struct.unpack(e + "I", data[off:off + 4])[0]
        if btype == 0x0A0D0D0A:  # Section Header : détermine le boutisme
            e = "<" if data[off + 8:off + 12] == b"\x4d\x3c\x2b\x1a" else ">"
            ifaces = []
        blen = struct.unpack(e + "I", data[off + 4:off + 8])[0]
        if blen < 12 or off + blen > len(data):
            break
        body = data[off + 8:off + blen - 4]
        if btype == 1 and len(body) >= 8:  # Interface Description
            linktype = struct.unpack(e + "H", body[:2])[0]
            res = 1e-6
            o = 8
            while o + 4 <= len(body):
                code, ln = struct.unpack(e + "HH", body[o:o + 4])
                if code == 0:
                    break
                if code == 9 and ln >= 1:  # if_tsresol
                    v = body[o + 4]
                    res = 2.0 ** -(v & 0x7F) if v & 0x80 else 10.0 ** -v
                o += 4 + ((ln + 3) & ~3)
            ifaces.append((linktype, res))
        elif btype == 6 and len(body) >= 20:  # Enhanced Packet
            iface, hi, lo, cap_len, _orig = struct.unpack(e + "IIIII", body[:20])
            linktype, res = ifaces[iface] if iface < len(ifaces) else (1, 1e-6)
            out.append((((hi << 32) | lo) * res, linktype, body[20:20 + cap_len]))
        elif btype == 3 and len(body) >= 4:  # Simple Packet
            linktype = ifaces[0][0] if ifaces else 1
            out.append((0.0, linktype, body[4:]))
        off += blen
    return out


def hexdump(raw: bytes, width: int = 16) -> str:
    lines = []
    for i in range(0, len(raw), width):
        chunk = raw[i:i + width]
        hx = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:04x}  {hx:<{width * 3}} {asc}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Filtre d'affichage (syntaxe simple, inspirée de Wireshark/tcpdump)
# --------------------------------------------------------------------------- #
class FilterError(ValueError):
    pass


FILTER_HELP = _("""Termes combinés en ET ; « or » (ou « || ») sépare des alternatives.

  tcp  udp  icmp  igmp          protocole de transport
  dns  http  tls  ssh  arp …    protocole applicatif (colonne Proto)
  port 443   ou   443           port source ou destination
  host 10.0.0.1                 adresse source ou destination
  src 10.0.0.1   dst 10.0.0.1   sens précis
  net 10.0.0.0/8  ou  10.0.0.0/8   réseau
  syn  ack  fin  rst  psh       drapeau TCP présent
  not tcp   ou   !tcp           négation
  example.com                   texte libre cherché dans Info

Exemples :
  tcp port 443
  dns or icmp
  host 192.168.1.10 not port 22
  rst or unreachable            (erreurs de connexion)""")


def compile_filter(expr: str) -> Callable[[Packet], bool]:
    """Filtre d'affichage : termes en ET, groupes séparés par « or ». Syntaxe : voir FILTER_HELP."""
    groups: list[list[str]] = [[]]
    for tok in expr.strip().split():
        if tok.lower() in ("or", "||"):
            groups.append([])
        else:
            groups[-1].append(tok)
    if len(groups) > 1 and any(not g for g in groups):
        raise FilterError(_("« or » doit relier deux conditions"))
    compiled = [_compile_and(g) for g in groups]
    if len(compiled) == 1:
        return compiled[0]
    return lambda p: any(f(p) for f in compiled)


def _compile_and(tokens: list[str]) -> Callable[[Packet], bool]:
    tests: list[Callable[[Packet], bool]] = []
    i = 0
    while i < len(tokens):
        neg = False
        t = tokens[i].lower()
        if t in ("not", "!"):
            neg = True
            i += 1
            if i >= len(tokens):
                raise FilterError(_("« not » doit être suivi d'un terme"))
            t = tokens[i].lower()
        elif t.startswith("!") and len(t) > 1:
            neg, t = True, t[1:]
        if t in ("and", "&&"):
            i += 1
            continue
        if t in ("port", "host", "src", "dst", "net"):
            if i + 1 >= len(tokens):
                raise FilterError(_("« {0} » attend une valeur", t))
            test = _keyword_test(t, tokens[i + 1])
            i += 2
        else:
            test = _single_test(t)
            i += 1
        tests.append((lambda f: (lambda p: not f(p)))(test) if neg else test)
    return lambda p: all(f(p) for f in tests)


def _keyword_test(kw: str, value: str) -> Callable[[Packet], bool]:
    if kw == "port":
        try:
            port = int(value)
        except ValueError:
            raise FilterError(_("Port invalide : {0}", value)) from None
        return lambda p: port in (p.sport, p.dport)
    net = _parse_net(value)
    if kw == "src":
        return lambda p: _in(p.src, net)
    if kw == "dst":
        return lambda p: _in(p.dst, net)
    return lambda p: _in(p.src, net) or _in(p.dst, net)


def _single_test(t: str) -> Callable[[Packet], bool]:
    protos = {"tcp": "TCP", "udp": "UDP", "icmp": "ICMP", "igmp": "IGMP"}
    if t in protos:
        return lambda p: p.transport == protos[t]
    if t in ("syn", "ack", "fin", "rst", "psh"):
        flag = t.upper()
        return lambda p: flag in p.flags
    if t.isdigit():
        port = int(t)
        return lambda p: port in (p.sport, p.dport)
    try:
        net = _parse_net(t)
        return lambda p: _in(p.src, net) or _in(p.dst, net)
    except FilterError:
        pass
    return lambda p: t == p.proto.lower() or t in p.info.lower()


def _parse_net(v: str) -> ipaddress.IPv4Network:
    try:
        return ipaddress.IPv4Network(v, strict=False)
    except ValueError:
        raise FilterError(_("Adresse ou réseau invalide : {0}", v)) from None


def _in(ip: str, net: ipaddress.IPv4Network) -> bool:
    try:
        return ipaddress.IPv4Address(ip) in net
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
#  Export pcap (LINKTYPE_RAW : datagrammes IP sans en-tête Ethernet)
# --------------------------------------------------------------------------- #
LINKTYPE_RAW = 101


def write_pcap(path: str, packets: Iterable[Packet]) -> int:
    """Écrit les datagrammes IPv4 (les trames ARP/IPv6 ouvertes depuis un fichier sont ignorées)."""
    n = 0
    with open(path, "wb") as f:
        f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, LINKTYPE_RAW))
        for p in packets:
            if not p.exportable:
                continue
            sec = int(p.ts)
            usec = int(round((p.ts - sec) * 1_000_000)) % 1_000_000
            f.write(struct.pack("<IIII", sec, usec, len(p.raw), len(p.raw)))
            f.write(p.raw)
            n += 1
    return n


def read_pcap(path: str) -> list[bytes]:
    """Relit un pcap (utilisé par les tests)."""
    with open(path, "rb") as f:
        data = f.read()
    magic = struct.unpack("<I", data[:4])[0]
    if magic != 0xA1B2C3D4:
        raise ValueError(_("Format pcap non supporté"))
    off, out = 24, []
    while off + 16 <= len(data):
        _sec, _usec, incl, _orig = struct.unpack("<IIII", data[off:off + 16])
        out.append(data[off + 16:off + 16 + incl])
        off += 16 + incl
    return out


# --------------------------------------------------------------------------- #
#  Statistiques
# --------------------------------------------------------------------------- #
def statistics(packets: Iterable[Packet]) -> dict:
    """Conversations (paire d'adresses), machines et protocoles, triés par octets décroissants."""
    conv: dict[tuple[str, str], list[int]] = {}
    hosts: dict[str, list[int]] = {}
    protos: dict[str, list[int]] = {}
    total = [0, 0]
    for p in packets:
        total[0] += 1
        total[1] += p.length
        if p.src and p.dst:
            key = tuple(sorted((p.src, p.dst)))
            c = conv.setdefault(key, [0, 0])
            c[0] += 1
            c[1] += p.length
            for h in (p.src, p.dst):
                e = hosts.setdefault(h, [0, 0])
                e[0] += 1
                e[1] += p.length
        pr = protos.setdefault(p.proto or "?", [0, 0])
        pr[0] += 1
        pr[1] += p.length

    def top(d):
        return sorted(((k, v[0], v[1]) for k, v in d.items()), key=lambda x: -x[2])

    return {"packets": total[0], "bytes": total[1], "conversations": top(conv), "hosts": top(hosts),
            "protocols": top(protos)}


def human_bytes(n: float) -> str:
    for unit in ("o", "ko", "Mo", "Go"):
        if n < 1000 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} Go"


# --------------------------------------------------------------------------- #
#  Capture (socket brut SIO_RCVALL — nécessite les droits administrateur)
# --------------------------------------------------------------------------- #
class RawCapture:
    """Reçoit tous les datagrammes IPv4 vus par l'interface dont l'adresse est `local_ip`."""

    def __init__(self, local_ip: str, on_packet: Callable[[bytes, float], None]):
        self.local_ip = local_ip
        self.on_packet = on_packet
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.error: str = ""

    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
        try:
            s.bind((self.local_ip, 0))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
            s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
        except OSError:
            s.close()
            raise
        s.settimeout(0.3)
        self._sock = s
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                data = self._sock.recv(65535)
            except socket.timeout:
                continue
            except OSError as e:
                if not self._stop.is_set():
                    self.error = str(e)
                break
            self.on_packet(data, time.time())

    def stop(self):
        self._stop.set()
        if self._sock:
            try:
                self._sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
            except OSError:
                pass
            self._sock.close()
        if self._thread:
            self._thread.join(timeout=1)


# --------------------------------------------------------------------------- #
#  Wireshark
# --------------------------------------------------------------------------- #
def find_wireshark() -> str | None:
    found = shutil.which("Wireshark") or shutil.which("wireshark")
    if found:
        return found
    candidates = []
    try:
        import winreg
        for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Wireshark.exe"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Wireshark")):
            try:
                with winreg.OpenKey(root, key) as k:
                    v = winreg.QueryValueEx(k, "")[0] if "App Paths" in key else winreg.QueryValueEx(k, "InstallDir")[0]
                    candidates.append(v if v.lower().endswith(".exe") else os.path.join(v, "Wireshark.exe"))
            except OSError:
                continue
    except ImportError:
        pass
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        if base:
            candidates.append(os.path.join(base, "Wireshark", "Wireshark.exe"))
    return next((c for c in candidates if c and os.path.isfile(c)), None)


def npcap_interface(guid: str) -> str:
    return f"\\Device\\NPF_{guid}"


def launch_wireshark(exe: str, interface_guid: str | None = None, pcap: str | None = None,
                     capture_filter: str = "") -> subprocess.Popen:
    args = [exe]
    if pcap:
        args += ["-r", pcap]
    elif interface_guid:
        args += ["-i", npcap_interface(interface_guid), "-k"]
        if capture_filter:
            args += ["-f", capture_filter]
    return subprocess.Popen(args, close_fds=True)
