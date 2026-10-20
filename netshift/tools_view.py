"""Onglet Outils : ping, traceroute, scan réseau, ports, capture, DNS, calculatrice, commandes système."""
from __future__ import annotations

import ipaddress
import os
import socket
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk

import customtkinter as ctk

from . import netbackend as nb
from . import nettools as nt
from .capture_view import CaptureSection
from .i18n import _
from .ui import (
    ACCENT,
    BORDER,
    GREEN,
    MUTED,
    RED,
    SURFACE2,
    TEXT,
    Console,
    Fonts,
    button,
    card,
    entry,
    label,
    segmented,
    style_treeview,
    ui_scale,
)


class ToolsView(ctk.CTkFrame):
    SECTIONS = [_("Ping"), _("Traceroute"), _("Scan réseau"), _("Ports"), _("Capture"), "DNS", _("Calcul IP"), _("Système")]

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.nav = segmented(self, self.SECTIONS, command=self.show)
        self.nav.grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.frames: dict[str, ctk.CTkFrame] = {}
        builders = {
            _("Ping"): self._build_ping, _("Traceroute"): self._build_trace, _("Scan réseau"): self._build_scan,
            _("Ports"): self._build_ports, _("Capture"): self._build_capture, "DNS": self._build_dns,
            _("Calcul IP"): self._build_calc,
            _("Système"): self._build_system,
        }
        for name, fn in builders.items():
            f = card(self)
            f.grid_columnconfigure(0, weight=1)
            fn(f)
            self.frames[name] = f
        self.nav.set(_("Ping"))
        self.show(_("Ping"))

    def show(self, name):
        for n, f in self.frames.items():
            if n == name:
                f.grid(row=1, column=0, sticky="nsew")
            else:
                f.grid_forget()
        self.nav.set(name)

    # ------------------------------------------------------------------ utils
    def _default_target(self) -> str:
        a = self.app.selected
        if a and a.gateways:
            return a.gateways[0]
        return "8.8.8.8"

    def _default_network(self) -> str:
        a = self.app.selected
        p = a.primary_ip if a else None
        if p and not p.ip.startswith("169.254."):
            prefix = max(p.prefix, 20)
            return str(ipaddress.IPv4Network(f"{p.ip}/{prefix}", strict=False))
        return "192.168.1.0/24"

    def _header(self, parent, title, subtitle):
        h = ctk.CTkFrame(parent, fg_color="transparent")
        h.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        label(h, title, Fonts.h2).pack(anchor="w")
        label(h, subtitle, Fonts.small, MUTED).pack(anchor="w")
        return h

    def _toolbar(self, parent, row=1):
        t = ctk.CTkFrame(parent, fg_color="transparent")
        t.grid(row=row, column=0, sticky="ew", padx=18, pady=(0, 8))
        return t

    @staticmethod
    def _small_label(parent, text):
        return label(parent, text, Fonts.small, MUTED)

    # =================================================================== PING
    def _build_ping(self, f):
        f.grid_rowconfigure(4, weight=1)
        self._header(f, _("Ping"), _("Test de joignabilité ICMP (natif, sans console)"))
        t = self._toolbar(f)
        self.ping_host = entry(t, _("hôte ou IP"), width=220)
        self.ping_host.pack(side="left")
        self.ping_host.bind("<Return>", lambda e: self._ping_start())
        self._small_label(t, _("  Nombre")).pack(side="left")
        self.ping_count = entry(t, "", width=56)
        self.ping_count.insert(0, "4")
        self.ping_count.pack(side="left", padx=(6, 0))
        self.ping_cont = ctk.CTkSwitch(t, text=_("Continu"), font=Fonts.small, text_color=MUTED, progress_color=ACCENT)
        self.ping_cont.pack(side="left", padx=(12, 0))
        self._small_label(t, _("  Taille")).pack(side="left")
        self.ping_size = entry(t, "", width=60)
        self.ping_size.insert(0, "32")
        self.ping_size.pack(side="left", padx=(6, 0))
        self.ping_stop_btn = button(t, _("■ Stop"), self._ping_stop, kind="danger", width=80, state="disabled")
        self.ping_stop_btn.pack(side="right")
        self.ping_btn = button(t, _("▶ Lancer"), self._ping_start, kind="primary", width=100)
        self.ping_btn.pack(side="right", padx=(0, 8))

        q = self._toolbar(f, 2)
        self._small_label(q, _("Raccourcis :")).pack(side="left", padx=(0, 6))
        for txt, fn in ((_("Passerelle"), lambda: self._gw_or_none()), ("DNS", self._dns_or_none),
                        ("1.1.1.1", lambda: "1.1.1.1"), ("8.8.8.8", lambda: "8.8.8.8"),
                        ("localhost", lambda: "127.0.0.1")):
            button(q, txt, lambda fn=fn: self._quick_ping(fn()), kind="ghost", height=26, width=0,
                   font=Fonts.small).pack(side="left", padx=2)

        st = self._toolbar(f, 3)
        self.ping_stats = {}
        for key, txt in (("sent", _("Envoyés")), ("recv", _("Reçus")), ("loss", _("Perte")), ("rtt", _("Min / Moy / Max"))):
            box = ctk.CTkFrame(st, fg_color=SURFACE2, corner_radius=8)
            box.pack(side="left", padx=(0, 8))
            label(box, txt, Fonts.small, MUTED).pack(anchor="w", padx=12, pady=(6, 0))
            v = label(box, "—", Fonts.h3)
            v.pack(anchor="w", padx=12, pady=(0, 6))
            self.ping_stats[key] = v

        self.ping_out = Console(f)
        self.ping_out.grid(row=4, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self._ping_stop_evt = threading.Event()
        self._ping_running = False

    def _gw_or_none(self):
        a = self.app.selected
        return a.gateways[0] if a and a.gateways else None

    def _dns_or_none(self):
        a = self.app.selected
        return a.dns[0] if a and a.dns else None

    def _quick_ping(self, host):
        if not host:
            self.app.toast(_("Aucune adresse correspondante sur la carte sélectionnée"), "warn")
            return
        self.ping_host.delete(0, "end")
        self.ping_host.insert(0, host)
        self._ping_start()

    def ping_target(self, host):
        self.show(_("Ping"))
        self._quick_ping(host)

    def _ping_start(self):
        if self._ping_running:
            self._ping_stop()
            self.after(300, self._ping_start)
            return
        host = self.ping_host.get().strip() or self._default_target()
        self.ping_host.delete(0, "end")
        self.ping_host.insert(0, host)
        try:
            count = 0 if self.ping_cont.get() else max(1, int(self.ping_count.get() or 4))
            size = max(0, min(65500, int(self.ping_size.get() or 32)))
        except ValueError:
            self.app.toast(_("Nombre ou taille invalide"), "err")
            return
        self._ping_stop_evt = threading.Event()
        stop = self._ping_stop_evt
        self._ping_running = True
        self.ping_btn.configure(state="disabled")
        self.ping_stop_btn.configure(state="normal")
        self.ping_out.clear()
        for v in self.ping_stats.values():
            v.configure(text="—", text_color=TEXT)
        ui = self.app.ui

        def work():
            try:
                ip = socket.gethostbyname(host)
            except OSError:
                ui(self.ping_out.write, _("Hôte introuvable : {0}", host), "err")
                ui(self._ping_done)
                return
            ui(self.ping_out.write, _("Ping {0} [{1}] avec {2} octets :", host, ip, size), "accent")
            sent = recv = 0
            rtts: list[int] = []
            i = 0
            while not stop.is_set() and (count == 0 or i < count):
                i += 1
                t0 = time.monotonic()
                r = nt.ping(ip, 1000, size)
                sent += 1
                if r.ok:
                    recv += 1
                    rtts.append(r.rtt)
                    ui(self.ping_out.write, _("  #{0:<4} Réponse de {1} : temps={2} ms  TTL={3}", i, r.reply_from, r.rtt, r.ttl), "ok")
                else:
                    src = _(" (de {0})", r.reply_from) if r.reply_from and r.reply_from != ip else ""
                    ui(self.ping_out.write, f"  #{i:<4} {r.error}{src}", "err")
                ui(self._ping_update_stats, sent, recv, list(rtts))
                remaining = 1.0 - (time.monotonic() - t0)
                if remaining > 0 and (count == 0 or i < count):
                    stop.wait(remaining)
            loss = 100 * (sent - recv) / sent if sent else 0
            summary = _("Terminé : {0} envoyés, {1} reçus, {2:.0f}% de perte", sent, recv, loss)
            if rtts:
                summary += _(" · min {0} / moy {1:.0f} / max {2} ms", min(rtts), sum(rtts) / len(rtts), max(rtts))
            ui(self.ping_out.write, summary, "muted")
            ui(self._ping_done)

        threading.Thread(target=work, daemon=True).start()

    def _ping_update_stats(self, sent, recv, rtts):
        loss = 100 * (sent - recv) / sent if sent else 0
        self.ping_stats["sent"].configure(text=str(sent))
        self.ping_stats["recv"].configure(text=str(recv))
        self.ping_stats["loss"].configure(text=_("{0:.0f} %", loss), text_color=GREEN if loss == 0 else RED)
        if rtts:
            self.ping_stats["rtt"].configure(text=_("{0} / {1:.0f} / {2} ms", min(rtts), sum(rtts) / len(rtts), max(rtts)))

    def _ping_stop(self):
        self._ping_stop_evt.set()

    def _ping_done(self):
        self._ping_running = False
        self.ping_btn.configure(state="normal")
        self.ping_stop_btn.configure(state="disabled")

    # ============================================================= TRACEROUTE
    def _build_trace(self, f):
        f.grid_rowconfigure(2, weight=1)
        self._header(f, _("Traceroute"), _("Chemin réseau saut par saut (3 sondes ICMP par saut)"))
        t = self._toolbar(f)
        self.tr_host = entry(t, _("hôte ou IP"), width=240)
        self.tr_host.insert(0, "8.8.8.8")
        self.tr_host.pack(side="left")
        self.tr_host.bind("<Return>", lambda e: self._trace_start())
        self.tr_resolve = ctk.CTkSwitch(t, text=_("Résoudre les noms"), font=Fonts.small, text_color=MUTED,
                                        progress_color=ACCENT)
        self.tr_resolve.pack(side="left", padx=(12, 0))
        self._small_label(t, _("  Sauts max")).pack(side="left")
        self.tr_max = entry(t, "", width=50)
        self.tr_max.insert(0, "30")
        self.tr_max.pack(side="left", padx=(6, 0))
        self.tr_stop_btn = button(t, _("■ Stop"), lambda: self._tr_stop.set(), kind="danger", width=80, state="disabled")
        self.tr_stop_btn.pack(side="right")
        self.tr_btn = button(t, _("▶ Lancer"), self._trace_start, kind="primary", width=100)
        self.tr_btn.pack(side="right", padx=(0, 8))
        self.tr_out = Console(f)
        self.tr_out.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self._tr_stop = threading.Event()

    def _trace_start(self):
        host = self.tr_host.get().strip()
        if not host:
            return
        try:
            max_hops = max(1, min(64, int(self.tr_max.get() or 30)))
        except ValueError:
            max_hops = 30
        self._tr_stop = threading.Event()
        stop, resolve, ui = self._tr_stop, bool(self.tr_resolve.get()), self.app.ui
        self.tr_out.clear()
        self.tr_btn.configure(state="disabled")
        self.tr_stop_btn.configure(state="normal")

        def work():
            try:
                ip = socket.gethostbyname(host)
            except OSError:
                ui(self.tr_out.write, _("Hôte introuvable : {0}", host), "err")
                ui(self._trace_done)
                return
            ui(self.tr_out.write, _("Itinéraire vers {0} [{1}], {2} sauts max :\n", host, ip, max_hops), "accent")
            ui(self.tr_out.write, _("{0:>4}  {1:>8} {2:>8} {3:>8}   Adresse", 'Saut', 'Sonde 1', 'Sonde 2', 'Sonde 3'), "muted")
            for ttl in range(1, max_hops + 1):
                if stop.is_set():
                    break
                times, hop, reached = [], "", False
                for _probe in range(3):
                    r = nt.ping(ip, 1500, 32, ttl=ttl)
                    if r.reply_from:
                        hop = r.reply_from
                    if r.ok:
                        reached = True
                        times.append(_("{0} ms", r.rtt))
                    elif r.reply_from:
                        times.append("<TTL>" if r.rtt is None else _("{0} ms", r.rtt))
                    else:
                        times.append("*")
                name = ""
                if hop and resolve:
                    name = nt.reverse_dns(hop)
                addr = (f"{name} [{hop}]" if name else hop) or _("Délai d'attente dépassé")
                tag = "ok" if reached else ("err" if not hop else None)
                ui(self.tr_out.write, f"{ttl:>4}  {times[0]:>8} {times[1]:>8} {times[2]:>8}   {addr}", tag)
                if reached:
                    break
            ui(self.tr_out.write, _("\nTerminé.") if not stop.is_set() else _("\nInterrompu."), "muted")
            ui(self._trace_done)

        threading.Thread(target=work, daemon=True).start()

    def _trace_done(self):
        self.tr_btn.configure(state="normal")
        self.tr_stop_btn.configure(state="disabled")

    # ============================================================ SCAN RESEAU
    def _build_scan(self, f):
        f.grid_rowconfigure(3, weight=1)
        self._header(f, _("Scan réseau"), _("Découverte des équipements (ICMP + ARP — détecte aussi les hôtes "
                                       "qui bloquent le ping sur le réseau local)"))
        t = self._toolbar(f)
        self.scan_net = entry(t, _("ex. 192.168.1.0/24"), width=200)
        self.scan_net.pack(side="left")
        self.scan_net.bind("<Return>", lambda e: self._scan_start())
        button(t, _("Réseau de la carte"), lambda: self._set_entry(self.scan_net, self._default_network()),
               kind="ghost", width=0, font=Fonts.small, height=28).pack(side="left", padx=(6, 0))
        self.scan_names = ctk.CTkSwitch(t, text=_("Noms"), font=Fonts.small, text_color=MUTED, progress_color=ACCENT)
        self.scan_names.select()
        self.scan_names.pack(side="left", padx=(12, 0))
        self.scan_arp = ctk.CTkSwitch(t, text="ARP", font=Fonts.small, text_color=MUTED, progress_color=ACCENT)
        self.scan_arp.select()
        self.scan_arp.pack(side="left", padx=(6, 0))
        self.scan_stop_btn = button(t, _("■ Stop"), lambda: self._scan_stop.set(), kind="danger", width=80,
                                    state="disabled")
        self.scan_stop_btn.pack(side="right")
        self.scan_btn = button(t, _("▶ Scanner"), self._scan_start, kind="primary", width=110)
        self.scan_btn.pack(side="right", padx=(0, 8))

        p = self._toolbar(f, 2)
        self.scan_progress = ctk.CTkProgressBar(p, height=8, corner_radius=4, progress_color=ACCENT)
        self.scan_progress.set(0)
        self.scan_progress.pack(side="left", fill="x", expand=True)
        self.scan_info = label(p, _("Prêt"), Fonts.small, MUTED, width=230, anchor="e")
        self.scan_info.pack(side="left", padx=(10, 0))

        holder = ctk.CTkFrame(f, fg_color=SURFACE2, corner_radius=10, border_width=1, border_color=BORDER)
        holder.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 18))
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        cols = ("ip", "name", "mac", "vendor", "rtt", "via")
        self.scan_tree = ttk.Treeview(holder, columns=cols, show="headings", style="IPM.Treeview",
                                      selectmode="browse")
        for c, txt, w, anchor in (("ip", _("Adresse IP"), 130, "w"), ("name", _("Nom d'hôte"), 220, "w"),
                                  ("mac", _("Adresse MAC"), 150, "w"), ("vendor", _("Fabricant"), 190, "w"),
                                  ("rtt", _("Latence"), 75, "e"), ("via", _("Détecté par"), 100, "center")):
            self.scan_tree.heading(c, text=txt, command=lambda c=c: self._scan_sort(c))
            self.scan_tree.column(c, width=int(w * ui_scale(self)), anchor=anchor, stretch=c == "name")
        self.scan_tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        sb = ctk.CTkScrollbar(holder, command=self.scan_tree.yview)
        sb.grid(row=0, column=1, sticky="ns", pady=6)
        self.scan_tree.configure(yscrollcommand=sb.set)
        self.scan_tree.bind("<Button-3>", self._scan_menu)
        self.scan_tree.bind("<Double-1>", lambda e: self._scan_action("ping"))
        self._scan_stop = threading.Event()
        self._scan_sort_rev = False

    @staticmethod
    def _set_entry(e, value):
        e.delete(0, "end")
        e.insert(0, value)

    def _scan_start(self):
        net = self.scan_net.get().strip() or self._default_network()
        self._set_entry(self.scan_net, net)
        try:
            n = ipaddress.IPv4Network(net, strict=False)
        except ValueError:
            self.app.toast(_("Plage réseau invalide (format attendu : 192.168.1.0/24)"), "err")
            return
        if n.num_addresses > 4096:
            self.app.toast(_("Plage trop grande : maximum /20 (4096 adresses)"), "err")
            return
        self.scan_tree.delete(*self.scan_tree.get_children())
        self._scan_stop = threading.Event()
        stop, ui = self._scan_stop, self.app.ui
        self.scan_btn.configure(state="disabled")
        self.scan_stop_btn.configure(state="normal")
        self.scan_progress.set(0)
        self._scan_found = 0
        t0 = time.monotonic()
        resolve, use_arp = bool(self.scan_names.get()), bool(self.scan_arp.get())

        def on_result(r: nt.HostResult):
            ui(self._scan_add, r)

        def on_progress(done, total):
            if done % 4 == 0 or done == total:
                ui(self._scan_prog, done, total)

        def work():
            try:
                nt.scan_hosts(str(n), on_result, on_progress, stop, resolve_names=resolve, use_arp=use_arp)
            except Exception as e:
                ui(self.app.toast, _("Erreur de scan : {0}", e), "err")
            ui(self._scan_done, time.monotonic() - t0, stop.is_set())

        threading.Thread(target=work, daemon=True).start()
        self.app.log(_("Scan réseau de {0} lancé", n))

    def _scan_add(self, r: nt.HostResult):
        self._scan_found += 1
        own = {i.ip for a in self.app.adapters for i in a.ips}
        name = r.hostname + (_("  (cet ordinateur)") if r.ip in own else "")
        self.scan_tree.insert("", "end", values=(r.ip, name, r.mac, nt.mac_vendor(r.mac),
                                                 _("{0} ms", r.rtt) if r.rtt is not None else "—", r.via))
        self._scan_sort("ip", keep=True)

    def _scan_prog(self, done, total):
        self.scan_progress.set(done / total if total else 1)
        self.scan_info.configure(text=_("{0}/{1} testées · {2} trouvé(s)", done, total, self._scan_found))

    def _scan_done(self, elapsed, stopped):
        self.scan_btn.configure(state="normal")
        self.scan_stop_btn.configure(state="disabled")
        state = "interrompu" if stopped else _("terminé")
        self.scan_info.configure(text=_("Scan {0} · {1} équipement(s) · {2:.1f} s", state, self._scan_found, elapsed))
        self.app.log(_("Scan {0} : {1} équipement(s) en {2:.1f} s", state, self._scan_found, elapsed))

    def _scan_sort(self, col, keep=False):
        if not keep:
            self._scan_sort_rev = not self._scan_sort_rev if getattr(self, "_scan_sort_col", None) == col else False
        self._scan_sort_col = col
        items = [(self.scan_tree.set(k, col), k) for k in self.scan_tree.get_children("")]

        def key(v):
            s = v[0]
            if col == "ip":
                try:
                    return (0, int(ipaddress.IPv4Address(s)))
                except ValueError:
                    return (1, 0)
            if col == "rtt":
                return (0, int(s.split()[0])) if s and s[0].isdigit() else (1, 0)
            return (0, s.lower())

        items.sort(key=key, reverse=self._scan_sort_rev)
        for i, (_value, k) in enumerate(items):
            self.scan_tree.move(k, "", i)

    def _scan_menu(self, event):
        row = self.scan_tree.identify_row(event.y)
        if not row:
            return
        self.scan_tree.selection_set(row)
        m = tk.Menu(self, tearoff=0)
        m.add_command(label=_("Ping"), command=lambda: self._scan_action("ping"))
        m.add_command(label=_("Scanner les ports"), command=lambda: self._scan_action("ports"))
        m.add_command(label=_("Traceroute"), command=lambda: self._scan_action("trace"))
        m.add_separator()
        m.add_command(label=_("Ouvrir http://"), command=lambda: self._scan_action("http"))
        m.add_command(label=_("Ouvrir https://"), command=lambda: self._scan_action("https"))
        m.add_command(label=_("Bureau à distance (RDP)"), command=lambda: self._scan_action("rdp"))
        m.add_command(label="Explorer les partages (\\\\ip)", command=lambda: self._scan_action("smb"))
        m.add_separator()
        m.add_command(label=_("Copier l'IP"), command=lambda: self._scan_action("copy_ip"))
        m.add_command(label=_("Copier la MAC"), command=lambda: self._scan_action("copy_mac"))
        m.add_command(label=_("Copier tout le tableau"), command=lambda: self._scan_action("copy_all"))
        m.tk_popup(event.x_root, event.y_root)

    def _scan_action(self, action):
        sel = self.scan_tree.selection()
        if not sel and action != "copy_all":
            return
        vals = self.scan_tree.item(sel[0], "values") if sel else ()
        ip = vals[0] if vals else ""
        if action == "ping":
            self.ping_target(ip)
        elif action == "ports":
            self._set_entry(self.port_host, ip)
            self.show(_("Ports"))
        elif action == "trace":
            self._set_entry(self.tr_host, ip)
            self.show(_("Traceroute"))
            self._trace_start()
        elif action in ("http", "https"):
            webbrowser.open(f"{action}://{ip}")
        elif action == "rdp":
            os.startfile("mstsc.exe") if not ip else nb.popen_stream(["mstsc.exe", f"/v:{ip}"])
        elif action == "smb":
            os.startfile(f"\\\\{ip}")
        elif action == "copy_ip":
            self.app.copy(ip)
        elif action == "copy_mac":
            self.app.copy(vals[2])
        elif action == "copy_all":
            rows = ["\t".join(self.scan_tree.item(k, "values")) for k in self.scan_tree.get_children("")]
            self.app.copy(_("IP\tNom\tMAC\tFabricant\tLatence\tDétection\n") + "\n".join(rows))

    # ================================================================== PORTS
    def _build_ports(self, f):
        f.grid_rowconfigure(4, weight=1)
        self._header(f, _("Test de ports TCP"), _("Vérifie quels ports TCP répondent sur un hôte"))
        t = self._toolbar(f)
        self.port_host = entry(t, _("hôte ou IP"), width=220)
        self.port_host.pack(side="left")
        self.port_spec = entry(t, _("ports : 22,80,443 ou 1-1024"), width=260)
        self.port_spec.insert(0, "21,22,23,80,443,445,3389,8080")
        self.port_spec.pack(side="left", padx=(8, 0))
        self.port_spec.bind("<Return>", lambda e: self._ports_start())
        self.port_stop_btn = button(t, _("■ Stop"), lambda: self._port_stop.set(), kind="danger", width=80,
                                    state="disabled")
        self.port_stop_btn.pack(side="right")
        self.port_btn = button(t, _("▶ Tester"), self._ports_start, kind="primary", width=100)
        self.port_btn.pack(side="right", padx=(0, 8))

        q = self._toolbar(f, 2)
        self._small_label(q, _("Listes :")).pack(side="left", padx=(0, 6))
        common = ",".join(str(p) for p in nt.COMMON_PORTS)
        for txt, spec in ((_("Web"), "80,443,8080,8443"), (_("Windows"), "135,139,445,3389,5985"),
                          (_("Courants"), common), ("1-1024", "1-1024"), (_("Tous"), "1-65535")):
            button(q, txt, lambda s=spec: self._set_entry(self.port_spec, s), kind="ghost", height=26,
                   font=Fonts.small).pack(side="left", padx=2)

        p = self._toolbar(f, 3)
        self.port_progress = ctk.CTkProgressBar(p, height=8, corner_radius=4, progress_color=ACCENT)
        self.port_progress.set(0)
        self.port_progress.pack(side="left", fill="x", expand=True)
        self.port_info = label(p, _("Prêt"), Fonts.small, MUTED, width=200, anchor="e")
        self.port_info.pack(side="left", padx=(10, 0))
        self.port_out = Console(f)
        self.port_out.grid(row=4, column=0, sticky="nsew", padx=18, pady=(0, 18))
        self._port_stop = threading.Event()

    def _ports_start(self):
        host = self.port_host.get().strip() or self._default_target()
        self._set_entry(self.port_host, host)
        try:
            ports = nt.parse_ports(self.port_spec.get())
        except ValueError as e:
            self.app.toast(str(e) if "port" in str(e).lower() else _("Liste de ports invalide"), "err")
            return
        self._port_stop = threading.Event()
        stop, ui = self._port_stop, self.app.ui
        self.port_out.clear()
        self.port_btn.configure(state="disabled")
        self.port_stop_btn.configure(state="normal")
        self.port_progress.set(0)
        found: list[int] = []
        t0 = time.monotonic()

        def on_open(port):
            found.append(port)
            svc = nt.COMMON_PORTS.get(port, "")
            ui(self.port_out.write, _("  ● {0:>5}/tcp  ouvert   {1}", port, svc), "ok")

        def on_progress(done, total):
            if done % 10 == 0 or done == total:
                ui(self.port_progress.set, done / total)
                ui(self.port_info.configure, text=_("{0}/{1} · {2} ouvert(s)", done, total, len(found)))

        def work():
            ui(self.port_out.write, _("Test de {0} port(s) sur {1}…", len(ports), host), "accent")
            try:
                nt.scan_ports(host, ports, on_open, on_progress, stop)
                closed = len(ports) - len(found)
                ui(self.port_out.write, _("\n{0} ouvert(s), {1} fermé(s)/filtré(s) en {2:.1f} s", len(found), closed, time.monotonic() - t0), "muted")
            except OSError as e:
                ui(self.port_out.write, _("Erreur : {0}", e), "err")
            ui(self.port_btn.configure, state="normal")
            ui(self.port_stop_btn.configure, state="disabled")

        threading.Thread(target=work, daemon=True).start()

    # ================================================================ CAPTURE
    def _build_capture(self, f):
        self.capture = CaptureSection(f, self.app)

    # ==================================================================== DNS
    def _build_dns(self, f):
        f.grid_rowconfigure(3, weight=1)
        self._header(f, "DNS", _("Résolution de noms, recherche inverse et nslookup"))
        t = self._toolbar(f)
        self.dns_name = entry(t, _("nom ou IP (ex. google.com)"), width=280)
        self.dns_name.pack(side="left")
        self.dns_name.bind("<Return>", lambda e: self._dns_resolve())
        button(t, _("Résoudre"), self._dns_resolve, kind="primary", width=100).pack(side="left", padx=(8, 0))
        button(t, "nslookup", self._dns_nslookup, width=100).pack(side="left", padx=(8, 0))
        q = self._toolbar(f, 2)
        self._small_label(q, _("Serveur pour nslookup (optionnel) :")).pack(side="left")
        self.dns_server = entry(q, _("défaut du système"), width=160)
        self.dns_server.pack(side="left", padx=(6, 0))
        button(q, _("Vider le cache DNS"), lambda: self._sys_cmd(["ipconfig", "/flushdns"], self.dns_out),
               kind="secondary", width=0).pack(side="right")
        self.dns_out = Console(f)
        self.dns_out.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 18))

    def _dns_resolve(self):
        name = self.dns_name.get().strip()
        if not name:
            return
        ui = self.app.ui

        def work():
            t0 = time.monotonic()
            try:
                ipaddress.ip_address(name)
                host = socket.gethostbyaddr(name)
                ui(self.dns_out.write, f"{name}  →  {host[0]}", "ok")
                for alias in host[1]:
                    ui(self.dns_out.write, _("    alias : {0}", alias))
            except ValueError:
                try:
                    for line in nt.resolve(name):
                        ui(self.dns_out.write, f"{name}  →  {line}", "ok")
                except OSError as e:
                    ui(self.dns_out.write, _("{0}  →  échec : {1}", name, e), "err")
            except OSError as e:
                ui(self.dns_out.write, _("{0}  →  aucune entrée inverse ({1})", name, e.strerror or e), "err")
            ui(self.dns_out.write, _("    ({0:.0f} ms)", (time.monotonic() - t0) * 1000), "muted")

        threading.Thread(target=work, daemon=True).start()

    def _dns_nslookup(self):
        name = self.dns_name.get().strip()
        if not name:
            return
        cmd = ["nslookup", name] + ([self.dns_server.get().strip()] if self.dns_server.get().strip() else [])
        self._sys_cmd(cmd, self.dns_out)

    # ============================================================== CALCUL IP
    def _build_calc(self, f):
        f.grid_rowconfigure(3, weight=1)
        self._header(f, _("Calculatrice de sous-réseau"), _("Saisis une adresse avec préfixe (10.1.2.3/22) "
                                                      "ou une adresse et un masque"))
        t = self._toolbar(f)
        self.calc_ip = entry(t, _("ex. 192.168.10.37/26"), width=220)
        self.calc_ip.pack(side="left")
        self.calc_mask = entry(t, _("masque (optionnel)"), width=160)
        self.calc_mask.pack(side="left", padx=(8, 0))
        for e in (self.calc_ip, self.calc_mask):
            e.bind("<KeyRelease>", lambda ev: self._calc())
        button(t, _("IP de la carte"), self._calc_from_adapter, kind="ghost", font=Fonts.small, height=28).pack(
            side="left", padx=(8, 0))
        button(t, _("Mon IP publique"), self._public_ip, width=0).pack(side="right")

        self.calc_box = ctk.CTkFrame(f, fg_color=SURFACE2, corner_radius=10)
        self.calc_box.grid(row=2, column=0, sticky="ew", padx=18, pady=(4, 8))
        self.calc_box.grid_columnconfigure(1, weight=1)
        self.calc_rows = []
        for i in range(10):
            k = label(self.calc_box, "", Fonts.small, MUTED, anchor="w", width=150)
            k.grid(row=i, column=0, sticky="w", padx=(16, 8), pady=3)
            v = label(self.calc_box, "", Fonts.mono, TEXT, anchor="w", cursor="hand2")
            v.grid(row=i, column=1, sticky="w", pady=3)
            v.bind("<Button-1>", lambda e, v=v: self.app.copy(v.cget("text").split("  (")[0]))
            self.calc_rows.append((k, v))
        label(f, _("Astuce : clic sur une valeur pour la copier."), Fonts.small, MUTED).grid(
            row=3, column=0, sticky="nw", padx=18)
        self.calc_ip.insert(0, "192.168.1.0/24")
        self._calc()

    def _calc_from_adapter(self):
        a = self.app.selected
        p = a.primary_ip if a else None
        if p:
            self._set_entry(self.calc_ip, f"{p.ip}/{p.prefix}")
            self.calc_mask.delete(0, "end")
            self._calc()

    def _calc(self):
        try:
            rows = nt.subnet_info(self.calc_ip.get(), self.calc_mask.get().strip() or None)
            self.calc_ip.configure(border_color=BORDER)
        except ValueError:
            self.calc_ip.configure(border_color=RED)
            return
        for (k, v), (key, val) in zip(self.calc_rows, rows):
            k.configure(text=key)
            v.configure(text=val)

    def _public_ip(self):
        self.app.bg(nt.public_ip, lambda ip: (self.app.copy(ip, quiet=True),
                                              self.app.toast(_("IP publique : {0} (copiée)", ip), "ok"),
                                              self.app.log(_("IP publique : {0}", ip))),
                    busy=_("Recherche de l'IP publique…"))

    # ================================================================ SYSTEME
    def _build_system(self, f):
        f.grid_rowconfigure(3, weight=1)
        self._header(f, _("Commandes système"), _("Raccourcis vers les commandes réseau Windows courantes"))
        grid = ctk.CTkFrame(f, fg_color="transparent")
        grid.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 6))
        cmds = [
            ("ipconfig /all", ["ipconfig", "/all"]),
            (_("Vider le cache DNS"), ["ipconfig", "/flushdns"]),
            (_("Renouveler tous les DHCP"), ["ipconfig", "/renew"]),
            (_("Afficher le cache DNS"), ["ipconfig", "/displaydns"]),
            (_("Table ARP"), ["arp", "-a"]),
            (_("Vider le cache ARP"), ["netsh", "interface", "ip", "delete", "arpcache"]),
            (_("Table de routage"), ["route", "print", "-4"]),
            (_("Connexions actives"), ["netstat", "-ano", "-p", "TCP"]),
            (_("Profils Wi-Fi"), ["netsh", "wlan", "show", "profiles"]),
            ("Interfaces (netsh)", ["netsh", "interface", "ipv4", "show", "config"]),
        ]
        for i, (txt, cmd) in enumerate(cmds):
            b = button(grid, txt, lambda c=cmd: self._sys_cmd(c, self.sys_out), width=0)
            b.grid(row=i // 5, column=i % 5, sticky="ew", padx=3, pady=3)
            grid.grid_columnconfigure(i % 5, weight=1, uniform="sys")
        links = ctk.CTkFrame(f, fg_color="transparent")
        links.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 8))
        self._small_label(links, _("Ouvrir :")).pack(side="left", padx=(0, 6))
        for txt, target in ((_("Connexions réseau"), "ncpa.cpl"), (_("Paramètres réseau"), "ms-settings:network"),
                            (_("Pare-feu"), "firewall.cpl"), (_("Gestionnaire de périphériques"), "devmgmt.msc")):
            button(links, txt, lambda t=target: os.startfile(t), kind="ghost", font=Fonts.small, height=26).pack(
                side="left", padx=2)
        button(links, _("Copier la sortie"), lambda: self.app.copy(self.sys_out.text()), kind="ghost",
               font=Fonts.small, height=26).pack(side="right")
        self.sys_out = Console(f)
        self.sys_out.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 18))

    def _sys_cmd(self, cmd, console: Console):
        console.clear()
        console.write("$ " + " ".join(cmd), "accent")
        ui = self.app.ui

        def work():
            try:
                p = nb.popen_stream(cmd)
                for raw in iter(p.stdout.readline, b""):
                    ui(console.write, nb._decode(raw).rstrip("\r\n"))
                code = p.wait()
                ui(console.write, _("\n[code de sortie {0}]", code), "ok" if code == 0 else "err")
            except OSError as e:
                ui(console.write, str(e), "err")

        threading.Thread(target=work, daemon=True).start()
        self.app.log(_("Commande : ") + " ".join(cmd))

    # ------------------------------------------------------------------ theme
    def restyle(self):
        style_treeview(self)
        self.capture.restyle()
        for c in (self.ping_out, self.tr_out, self.port_out, self.dns_out, self.sys_out):
            c._refresh_tags()
