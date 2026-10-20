"""Génère les captures d'écran de la documentation avec des données fictives.

Usage :  python scripts/make_screenshots.py [dossier_sortie]

Aucune donnée réelle n'est lue : cartes, scan, ping et historique sont simulés
(plages d'adresses de documentation RFC 5737 et réseaux privés génériques).

Les images sont obtenues avec PrintWindow, qui rend uniquement le contenu de la fenêtre
de NetShift : une autre fenêtre placée devant ne peut jamais apparaître sur les captures.
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from netshift import app as A  # noqa: E402
from netshift import netbackend as nb  # noqa: E402
from netshift import nettools as nt  # noqa: E402
from netshift import tools_view as tv  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def grab_window(hwnd: int) -> Image.Image:
    """Rend la zone client d'une fenêtre via PrintWindow (indépendant de ce qui est affiché à l'écran)."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    H = ctypes.c_void_p
    user32.GetDC.restype = H
    user32.GetDC.argtypes = [H]
    user32.ReleaseDC.argtypes = [H, H]
    user32.GetClientRect.argtypes = [H, ctypes.POINTER(wintypes.RECT)]
    user32.PrintWindow.argtypes = [H, H, wintypes.UINT]
    gdi32.CreateCompatibleDC.restype = H
    gdi32.CreateCompatibleDC.argtypes = [H]
    gdi32.CreateCompatibleBitmap.restype = H
    gdi32.CreateCompatibleBitmap.argtypes = [H, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = H
    gdi32.SelectObject.argtypes = [H, H]
    gdi32.GetDIBits.argtypes = [H, H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi32.DeleteObject.argtypes = [H]
    gdi32.DeleteDC.argtypes = [H]

    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    w, h = rect.right, rect.bottom
    hdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        if not user32.PrintWindow(hwnd, mdc, 3):  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
            raise RuntimeError("PrintWindow a échoué")
        bmi = _BITMAPINFOHEADER(biSize=ctypes.sizeof(_BITMAPINFOHEADER), biWidth=w, biHeight=-h, biPlanes=1,
                                biBitCount=32, biCompression=0)
        buf = ctypes.create_string_buffer(w * h * 4)
        if gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0) != h:
            raise RuntimeError("GetDIBits a échoué")
        return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, hdc)

DEMO_ADAPTERS = [
    nb.Adapter("Ethernet", "Intel(R) Ethernet Connection I219-LM", "Up", "3C-52-82-1A-2B-3C", "1 Gbps", 12,
               "{demo-1}", False, False, True, 1500, [nb.IPAddr("192.168.10.25", 24, "Manual")],
               ["192.168.10.1"], ["192.168.10.1", "1.1.1.1"]),
    nb.Adapter("Wi-Fi", "Intel(R) Wi-Fi 6E AX211 160MHz", "Up", "A4-6B-B6-11-22-33", "866.7 Mbps", 18,
               "{demo-2}", False, True, False, 1500, [nb.IPAddr("10.20.30.142", 24, "Dhcp")],
               ["10.20.30.1"], ["10.20.30.1"]),
    nb.Adapter("USB Lab", "ASIX AX88179 USB 3.0 to Gigabit Ethernet", "Up", "00-0E-C6-AA-BB-CC", "1 Gbps", 33,
               "{demo-3}", False, True, False, 1500, [nb.IPAddr("169.254.77.12", 16, "WellKnown")], [], []),
    nb.Adapter("Ethernet 2", "Realtek USB GbE Family Controller", "Disconnected", "50-3E-AA-01-02-03", "0 bps", 7,
               "{demo-4}", False, False, True, 1500, [nb.IPAddr("10.0.0.10", 24, "Manual")], [], []),
]

DEMO_HOSTS = [
    ("192.168.10.1", "router.lan", "00-1D-7E-10-20-30", 1, "ICMP+ARP"),
    ("192.168.10.2", "switch-core.lan", "F0-9F-C2-44-55-66", 2, "ICMP+ARP"),
    ("192.168.10.10", "nas.lan", "00-11-32-AB-CD-EF", 1, "ICMP+ARP"),
    ("192.168.10.20", "printer-2f.lan", "3C-2A-F4-12-34-56", 3, "ICMP+ARP"),
    ("192.168.10.25", "WORKSTATION-01", "3C-52-82-1A-2B-3C", 0, "ICMP+ARP"),
    ("192.168.10.31", "", "B8-27-EB-98-76-54", None, "ARP"),
    ("192.168.10.40", "cam-entrance.lan", "BC-AD-28-01-02-03", 4, "ICMP+ARP"),
    ("192.168.10.41", "cam-parking.lan", "BC-AD-28-04-05-06", 5, "ICMP+ARP"),
    ("192.168.10.50", "ap-floor1.lan", "74-83-C2-AA-00-11", 2, "ICMP+ARP"),
    ("192.168.10.51", "ap-floor2.lan", "74-83-C2-AA-00-22", 2, "ICMP+ARP"),
    ("192.168.10.100", "", "00-50-56-C0-00-08", None, "ARP"),
]


def fake_scan(network, on_result, on_progress, stop, **kw):
    for ip, name, mac, rtt, via in DEMO_HOSTS:
        on_result(nt.HostResult(ip, True, rtt, mac, name, via))
    on_progress(254, 254)


def fake_ping(host, timeout_ms=1000, size=32, ttl=128):
    time.sleep(0.02)
    return nt.PingResult(True, rtt=[1, 1, 2, 1, 3, 1, 1, 2][int(time.time() * 10) % 8], ttl=64, reply_from=host)


nb.list_adapters = lambda: [a for a in DEMO_ADAPTERS]
nb.is_admin = lambda: True
nt.scan_hosts = fake_scan
nt.ping = fake_ping
tv.time.sleep = lambda s: None
tmp = Path(tempfile.mkdtemp())
A.data_dir = lambda: tmp


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    theme = os.environ.get("THEME", "dark")
    app = A.App()
    import customtkinter as ctk
    ctk.set_appearance_mode(theme)
    app.theme_seg.set("Sombre" if theme == "dark" else "Clair")
    app.after(300, app._restyle)
    app.journal.clear()  # n'affiche aucun chemin local de la machine qui génère les captures
    app.log(f"NetShift {A.VERSION} démarré — administrateur", "muted")
    app.geometry("1320x840+10+10")
    app.presets.add("Bureau — VLAN 10", {"mode": "static", "ip": "192.168.10.25", "mask": "24",
                                         "gateway": "192.168.10.1", "dns1": "192.168.10.1", "dns2": "1.1.1.1"},
                    "Poste fixe, prise murale B12")
    app.presets.add("Automate atelier", {"mode": "static", "ip": "172.16.5.200", "mask": "255.255.0.0"},
                    "Câble direct sur l'automate, pas de passerelle")
    app.history.add("Ethernet", "Intel(R) Ethernet Connection I219-LM", {"mode": "dhcp", "dns_mode": "auto"},
                    {"mode": "static", "ip": "192.168.10.25", "mask": "255.255.255.0", "gateway": "192.168.10.1",
                     "dns1": "192.168.10.1"}, "Preset « Bureau — VLAN 10 »", True)
    app._presets_changed()

    steps = [
        ("configuration", lambda: app.tabs.set("Configuration")),
        ("presets", lambda: (app.tabs.set("Presets"), app._select_preset(app.presets.presets[-2]["id"]))),
        ("scan", lambda: (app.tabs.set("Outils"), app.tools.show("Scan réseau"), app.tools._scan_start())),
        ("ping", lambda: (app.tools.show("Ping"), app.tools._quick_ping("192.168.10.1"))),
        ("calc", lambda: (app.tools.show("Calcul IP"), app.tools._set_entry(app.tools.calc_ip, "192.168.10.37/26"),
                          app.tools._calc())),
        ("history", lambda: app.tabs.set("Historique & journal")),
    ]

    def run(i=0, pending=None):
        if pending:
            grab_window(int(app.wm_frame(), 16)).save(OUT / f"{pending}-{theme}.png")
        if i < len(steps):
            name, fn = steps[i]
            fn()
            app.after(2500, lambda: run(i + 1, name))
        else:
            app._on_close()

    app.after(2500, run)
    app.mainloop()


if __name__ == "__main__":
    threading.excepthook = lambda a: None
    main()
