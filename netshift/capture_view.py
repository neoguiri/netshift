"""Section « Capture » de l'onglet Outils : mini-analyseur de paquets + passerelle vers Wireshark."""
from __future__ import annotations

import collections
import os
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, ttk

import customtkinter as ctk

from . import capture as cap
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
    confirm,
    entry,
    label,
    mode_color,
    option_menu,
    ui_scale,
)

MAX_PACKETS = 50_000   # gardés en mémoire (pour l'export)
MAX_ROWS = 5_000       # affichés dans le tableau
PURPLE = ("#7C3AED", "#A78BFA")
TEAL = ("#0F766E", "#2DD4BF")


class CaptureSection:
    def __init__(self, f: ctk.CTkFrame, app):
        self.app = app
        self.f = f
        self.packets: list[cap.Packet] = []
        self.by_iid: dict[str, cap.Packet] = {}
        self.incoming: collections.deque[cap.Packet] = collections.deque()
        self.capture: cap.RawCapture | None = None
        self.counter = 0
        self.t0: float | None = None
        self.bytes = 0
        self.proto_count: collections.Counter[str] = collections.Counter()
        self.filter = cap.compile_filter("")
        self._filter_job = None
        self._rate_hist: collections.deque[tuple[float, int]] = collections.deque(maxlen=10)
        self._lock = threading.Lock()

        f.grid_rowconfigure(3, weight=1)
        h = ctk.CTkFrame(f, fg_color="transparent")
        h.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        label(h, _("Capture de paquets"), Fonts.h2).pack(anchor="w")
        label(h, _("Trafic IPv4 de la carte (droits administrateur requis) · ouverture de fichiers .pcap/.pcapng · "
                 "export pour Wireshark"), Fonts.small, MUTED).pack(anchor="w")

        t = ctk.CTkFrame(f, fg_color="transparent")
        t.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))
        label(t, _("Carte"), Fonts.small, MUTED).pack(side="left", padx=(0, 6))
        self.iface = option_menu(t, ["—"], width=260)
        self.iface.pack(side="left")
        self.start_btn = button(t, _("▶ Capturer"), self.start, kind="primary", width=110)
        self.start_btn.pack(side="left", padx=(10, 0))
        self.stop_btn = button(t, _("■ Arrêter"), self.stop, kind="danger", width=90, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))
        button(t, _("Effacer"), self.clear, kind="ghost", width=0).pack(side="left", padx=(6, 0))
        self.ws_btn = button(t, _("Wireshark"), self.open_wireshark, width=0)
        self.ws_btn.pack(side="right")
        button(t, _("Exporter"), self.export, width=0).pack(side="right", padx=(0, 6))
        button(t, _("Ouvrir…"), self.open_file, width=0).pack(side="right", padx=(0, 6))
        button(t, _("Statistiques"), self.show_stats, width=0).pack(side="right", padx=(0, 6))

        r = ctk.CTkFrame(f, fg_color="transparent")
        r.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 8))
        r.grid_columnconfigure(1, weight=1)
        label(r, _("Filtre"), Fonts.small, MUTED).grid(row=0, column=0, padx=(0, 6))
        self.filter_entry = entry(r, _("ex. tcp port 443 · dns or icmp · host 192.168.1.1 · not arp · texte libre"
                                     "   (Ctrl+F)"), width=0)
        self.filter_entry.grid(row=0, column=1, sticky="ew")
        self.filter_entry.bind("<KeyRelease>", lambda e: self._schedule_filter())
        self.filter_entry.bind("<Escape>", lambda e: self._set_filter(""))
        button(r, "?", self.show_help, kind="ghost", width=32).grid(row=0, column=2, padx=(4, 0))
        self.autoscroll = ctk.CTkSwitch(r, text=_("Défilement auto"), font=Fonts.small, text_color=MUTED,
                                        progress_color=ACCENT)
        self.autoscroll.select()
        self.autoscroll.grid(row=0, column=3, padx=(8, 0))
        under = ctk.CTkFrame(r, fg_color="transparent")
        under.grid(row=1, column=1, columnspan=3, sticky="ew", pady=(4, 0))
        chips = ctk.CTkFrame(under, fg_color="transparent")
        chips.pack(side="left")
        for txt, expr in ((_("Tout"), ""), ("TCP", "tcp"), ("UDP", "udp"), ("DNS", "dns or mdns or llmnr"),
                          ("ICMP", "icmp"), (_("Web"), "port 80 or port 443 or port 8080"), ("ARP", "arp"),
                          (_("Erreurs"), "rst or unreachable or nxdomain")):
            button(chips, txt, lambda e=expr: self._set_filter(e), kind="ghost", height=24, width=0,
                   font=Fonts.small).pack(side="left", padx=(0, 2))
        self.stats = label(under, _("Prêt"), Fonts.small, MUTED, anchor="e")
        self.stats.pack(side="right")
        f.winfo_toplevel().bind("<Control-f>", self._focus_filter, add="+")

        body = ctk.CTkFrame(f, fg_color="transparent")
        body.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 18))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=3)
        body.grid_rowconfigure(1, weight=2, minsize=int(170 * ui_scale(f)))

        holder = ctk.CTkFrame(body, fg_color=SURFACE2, corner_radius=10, border_width=1, border_color=BORDER)
        holder.grid(row=0, column=0, sticky="nsew")
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        cols = ("no", "time", "src", "dst", "proto", "len", "info")
        self.tree = ttk.Treeview(holder, columns=cols, show="headings", style="IPM.Treeview", selectmode="browse")
        k = ui_scale(f)
        for c, txt, w, anchor, stretch in (("no", "N°", 60, "e", False), ("time", _("Temps"), 80, "e", False),
                                           ("src", _("Source"), 130, "w", False), ("dst", _("Destination"), 130, "w", False),
                                           ("proto", _("Proto"), 70, "center", False), ("len", _("Long."), 70, "center", False),
                                           ("info", _("Info"), 460, "w", True)):
            self.tree.heading(c, text=txt, anchor="w" if c == "info" else "center")
            self.tree.column(c, width=int(w * k), anchor=anchor, stretch=stretch)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        sb = ctk.CTkScrollbar(holder, command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns", pady=6)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_details())
        self.tree.bind("<Button-3>", self._menu)

        details = ctk.CTkFrame(body, fg_color="transparent")
        details.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        details.grid_columnconfigure(0, weight=2)
        details.grid_columnconfigure(1, weight=3)
        details.grid_rowconfigure(0, weight=1)
        self.detail_out = Console(details, height=120, wrap="word")
        self.detail_out.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.hex_out = Console(details, height=120, font=Fonts.mono_small)
        self.hex_out.grid(row=0, column=1, sticky="nsew")
        self.detail_out.write(_("Sélectionne un paquet pour voir son détail."), "muted")

        self.restyle()
        self._refresh_ifaces()
        f.after(200, self._drain)

    # ------------------------------------------------------------- interfaces
    def _candidates(self):
        out = []
        for a in self.app.adapters:
            p = a.primary_ip
            if p and not a.disabled:
                out.append((f"{a.name} — {p.ip}", a, p.ip))
        return out

    def _refresh_ifaces(self):
        if not self.capture:
            cands = self._candidates()
            names = [c[0] for c in cands] or [_("Aucune carte avec IP")]
            self.iface.configure(values=names)
            if self.iface.get() not in names:
                sel = self.app.selected
                pref = next((c[0] for c in cands if sel and c[1].guid == sel.guid), names[0])
                self.iface.set(pref)
        self.f.after(3000, self._refresh_ifaces)

    def _current(self):
        return next(((a, ip) for n, a, ip in self._candidates() if n == self.iface.get()), (None, None))

    # ---------------------------------------------------------------- capture
    def start(self):
        if not self.app.admin:
            self.app.toast(_("La capture nécessite les droits administrateur"), "err")
            return
        adapter, ip = self._current()
        if not ip:
            self.app.toast(_("Choisis une carte qui a une adresse IPv4"), "err")
            return

        def on_packet(raw: bytes, ts: float):
            with self._lock:
                self.counter += 1
                no = self.counter
            self.incoming.append(cap.decode(raw, no, ts))

        self.capture = cap.RawCapture(ip, on_packet)
        try:
            self.capture.start()
        except OSError as e:
            self.capture = None
            self.app.toast(_("Capture impossible : {0}", e), "err")
            self.app.log(_("Capture impossible sur {0} : {1}", ip, e), "err")
            return
        if self.t0 is None:
            self.t0 = time.time()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.iface.configure(state="disabled")
        self.app.log(_("Capture démarrée sur {0} ({1})", adapter.name, ip), "accent")

    def stop(self):
        if self.capture:
            self.capture.stop()
            err = self.capture.error
            self.capture = None
            self.app.log(_("Capture arrêtée — {0} paquet(s)", self.counter) + (f" ({err})" if err else ""))
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.iface.configure(state="normal")

    def clear(self):
        self.packets.clear()
        self.by_iid.clear()
        self.incoming.clear()
        self.tree.delete(*self.tree.get_children())
        with self._lock:
            self.counter = 0
        self.bytes = 0
        self.proto_count.clear()
        self._rate_hist.clear()
        self.t0 = time.time() if self.capture else None
        self.detail_out.clear()
        self.hex_out.clear()
        self.stats.configure(text=_("Prêt"), text_color=MUTED)

    def _drain(self):
        batch = []
        while self.incoming and len(batch) < 2000:
            batch.append(self.incoming.popleft())
        if batch:
            self.packets.extend(batch)
            if len(self.packets) > MAX_PACKETS:
                del self.packets[: len(self.packets) - MAX_PACKETS]
            for p in batch:
                self.bytes += p.length
                self.proto_count[p.proto] += 1
                if self.filter(p):
                    self._insert(p)
            self._trim()
            if self.autoscroll.get():
                kids = self.tree.get_children()
                if kids:
                    self.tree.see(kids[-1])
        self._update_stats()
        if self.capture and self.capture.error:
            self.app.toast(_("Capture interrompue : {0}", self.capture.error), "err")
            self.stop()
        self.f.after(200, self._drain)

    def _insert(self, p: cap.Packet):
        iid = str(p.no)
        rel = p.ts - (self.t0 or p.ts)
        self.tree.insert("", "end", iid=iid, values=(p.no, f"{rel:.3f}", p.src, p.dst, p.proto, p.length, p.info),
                         tags=(self._tag(p),))
        self.by_iid[iid] = p

    def _trim(self):
        kids = self.tree.get_children()
        if len(kids) > MAX_ROWS:
            old = kids[: len(kids) - MAX_ROWS]
            self.tree.delete(*old)
            for iid in old:
                self.by_iid.pop(iid, None)

    @staticmethod
    def _tag(p: cap.Packet) -> str:
        if "RST" in p.flags:
            return "rst"
        if p.proto in ("DNS", "mDNS", "LLMNR"):
            return "dns"
        if p.transport == "ICMP":
            return "icmp"
        if p.transport == "UDP":
            return "udp"
        if "SYN" in p.flags or "FIN" in p.flags:
            return "syn"
        return "tcp"

    def _update_stats(self):
        n = len(self.packets)
        if not n:
            return
        now = time.time()
        self._rate_hist.append((now, self.counter))
        t_old, c_old = self._rate_hist[0]
        rate = (self.counter - c_old) / (now - t_old) if now > t_old else 0
        shown = len(self.tree.get_children())
        top = " · ".join(f"{k} {v * 100 // n}%" for k, v in self.proto_count.most_common(4))
        size = _("{0:.1f} Mo", self.bytes / 1e6) if self.bytes > 1e6 else _("{0:.0f} ko", self.bytes / 1e3)
        state = _("● capture") if self.capture else _("arrêtée")
        self.stats.configure(text=_("{0} · {1} paquet(s), {2} affiché(s) · {3} · {4:.0f} pkt/s · {5}", state, n, shown, size, rate, top),
                             text_color=GREEN if self.capture else MUTED)

    # ----------------------------------------------------------------- filtre
    def _schedule_filter(self):
        if self._filter_job:
            self.f.after_cancel(self._filter_job)
        self._filter_job = self.f.after(300, self._apply_filter)

    def _apply_filter(self):
        try:
            self.filter = cap.compile_filter(self.filter_entry.get())
            self.filter_entry.configure(border_color=BORDER)
        except cap.FilterError as e:
            self.filter_entry.configure(border_color=RED)
            self.app.toast(str(e), "warn")
            return
        self.tree.delete(*self.tree.get_children())
        self.by_iid.clear()
        for p in [p for p in self.packets if self.filter(p)][-MAX_ROWS:]:
            self._insert(p)

    # ---------------------------------------------------------------- détails
    def _show_details(self):
        sel = self.tree.selection()
        p = self.by_iid.get(sel[0]) if sel else None
        if not p:
            return
        self.detail_out.clear()
        self.detail_out.write(_("Paquet n°{0} · {1}.{2:03d} · {3} octets", p.no, time.strftime('%H:%M:%S', time.localtime(p.ts)), int(p.ts % 1 * 1000), p.length), "accent")
        for k, v in p.details:
            self.detail_out.write(f"{k:<16} {v}")
        self.hex_out.clear()
        self.hex_out.write(cap.hexdump(p.raw[:2048]) + ("\n…" if len(p.raw) > 2048 else ""))
        self.detail_out.see("1.0")
        self.hex_out.see("1.0")

    def _menu(self, event):
        row = self.tree.identify_row(event.y)
        p = self.by_iid.get(row) if row else None
        if not p:
            return
        self.tree.selection_set(row)
        m = tk.Menu(self.f, tearoff=0)
        m.add_command(label=_("Filtrer sur {0}", p.src), command=lambda: self._set_filter(f"host {p.src}"))
        m.add_command(label=_("Filtrer sur {0}", p.dst), command=lambda: self._set_filter(f"host {p.dst}"))
        if p.sport is not None:
            m.add_command(label=_("Filtrer cette conversation ({0} ↔ {1})", p.sport, p.dport),
                          command=lambda: self._set_filter(f"host {p.src} host {p.dst} port {p.sport} port {p.dport}"))
        m.add_separator()
        m.add_command(label=_("Copier la ligne"), command=lambda: self.app.copy(
            "\t".join(str(v) for v in self.tree.item(row, "values"))))
        m.add_command(label=_("Copier le hexdump"), command=lambda: self.app.copy(cap.hexdump(p.raw), quiet=True))
        m.tk_popup(event.x_root, event.y_root)

    def _focus_filter(self, _event=None):
        if self.f.winfo_ismapped():
            self.filter_entry.focus_set()
            self.filter_entry.select_range(0, "end")
            return "break"
        return None

    def show_help(self):
        _TextDialog(self.f, _("Syntaxe du filtre"), cap.FILTER_HELP)

    def open_file(self):
        path = filedialog.askopenfilename(
            title=_("Ouvrir une capture"),
            filetypes=[(_("Captures"), "*.pcap *.pcapng *.cap"), (_("Tous les fichiers"), "*.*")])
        if not path:
            return
        if self.packets and not confirm(self.f, _("Remplacer les paquets affichés ?"),
                                        _("{0} paquet(s) en mémoire seront remplacés.", len(self.packets)), _("Ouvrir")):
            return
        self.stop()

        def work():
            rows = cap.read_capture_file(path)
            truncated = max(0, len(rows) - MAX_PACKETS)
            rows = rows[:MAX_PACKETS]
            return [cap.decode_frame(fr, lt, i, ts) for i, (ts, lt, fr) in enumerate(rows, 1)], truncated

        def done(res):
            pkts, truncated = res
            self.clear()
            if not pkts:
                self.app.toast(_("Fichier vide"), "warn")
                return
            self.load_packets(pkts)
            msg = _("{0} paquet(s) chargé(s) depuis {1}", len(pkts), os.path.basename(path))
            if truncated:
                msg += _(" ({0} ignoré(s) au-delà de {1})", truncated, MAX_PACKETS)
            self.app.toast(msg, "warn" if truncated else "ok")
            self.app.log(msg)

        self.app.bg(work, done, busy=_("Lecture de {0}…", os.path.basename(path)),
                    error=lambda e: self.app.toast(_("Lecture impossible : {0}", e), "err"))

    def load_packets(self, pkts: list[cap.Packet]):
        """Affiche une liste de paquets déjà décodés (fichier ouvert, démonstration)."""
        self.t0 = pkts[0].ts
        self.packets = list(pkts)
        with self._lock:
            self.counter = len(pkts)
        for p in pkts:
            self.bytes += p.length
            self.proto_count[p.proto] += 1
        self._apply_filter()

    def show_stats(self):
        shown = [self.by_iid[i] for i in self.tree.get_children() if i in self.by_iid]
        if not shown:
            self.app.toast(_("Aucun paquet à analyser"), "warn")
            return
        st = cap.statistics(shown)
        hb = cap.human_bytes
        flt = self.filter_entry.get().strip()
        lines = [_("{0} paquet(s) affiché(s) · {1}", st['packets'], hb(st['bytes'])) + (_(" · filtre : {0}", flt) if flt else ""),
                 "", "PROTOCOLES", f"  {'Protocole':<14}{'Paquets':>9}{'Octets':>12}{'Part':>8}"]
        for name, n, b in st["protocols"][:15]:
            lines.append(f"  {name:<14}{n:>9}{hb(b):>12}{b * 100 / max(1, st['bytes']):>7.0f}%")
        lines += ["", _("CONVERSATIONS (top 20)"), f"  {'Adresse A':<28}{'Adresse B':<28}{'Paquets':>9}{'Octets':>12}"]
        for (a, b), n, by in st["conversations"][:20]:
            lines.append(f"  {a:<28}{b:<28}{n:>9}{hb(by):>12}")
        lines += ["", _("MACHINES (top 20)"), f"  {'Adresse':<40}{'Paquets':>9}{'Octets':>12}"]
        for h, n, by in st["hosts"][:20]:
            lines.append(f"  {h:<40}{n:>9}{hb(by):>12}")
        _TextDialog(self.f, _("Statistiques de capture"), "\n".join(lines), width=820, height=560)

    def _set_filter(self, expr):
        self.filter_entry.delete(0, "end")
        self.filter_entry.insert(0, expr)
        self._apply_filter()

    # ------------------------------------------------------------ Wireshark
    def export(self) -> str | None:
        rows = [self.by_iid[i] for i in self.tree.get_children() if i in self.by_iid]
        if not rows:
            self.app.toast(_("Aucun paquet à exporter"), "warn")
            return None
        path = filedialog.asksaveasfilename(
            title=_("Exporter la capture"), defaultextension=".pcap",
            initialfile=f"capture-{time.strftime('%Y%m%d-%H%M%S')}.pcap",
            filetypes=[(_("Capture pcap"), "*.pcap"), (_("Tous les fichiers"), "*.*")])
        if not path:
            return None
        n = cap.write_pcap(path, rows)
        skipped = len(rows) - n
        note = _(" — {0} trame(s) non IPv4 ignorée(s)", skipped) if skipped else ""
        self.app.toast(_("{0} paquet(s) exporté(s) vers {1}{2}", n, os.path.basename(path), note), "warn" if skipped else "ok")
        self.app.log(_("Capture exportée : {0} ({1} paquets){2}", path, n, note))
        exe = cap.find_wireshark()
        if exe and confirm(self.f, _("Ouvrir dans Wireshark ?"), _("{0} paquet(s) exporté(s). Ouvrir le fichier dans Wireshark ?", n), _("Ouvrir")):
            cap.launch_wireshark(exe, pcap=path)
        return path

    def open_wireshark(self):
        exe = cap.find_wireshark()
        if not exe:
            if confirm(self.f, _("Wireshark n'est pas installé"),
                       _("Wireshark (avec Npcap) permet une capture complète : Ethernet, ARP, VLAN, Wi-Fi… "
                       "Ouvrir la page de téléchargement ?"), _("Télécharger")):
                webbrowser.open("https://www.wireshark.org/download.html")
            return
        adapter, _ip = self._current()
        adapter = adapter or self.app.selected
        if not adapter:
            cap.launch_wireshark(exe)
            return
        cap.launch_wireshark(exe, interface_guid=adapter.guid)
        self.app.toast(_("Wireshark lancé en capture sur {0}", adapter.name), "ok")
        self.app.log(_("Wireshark lancé sur {0} ({1})", adapter.name, cap.npcap_interface(adapter.guid)))

    # ------------------------------------------------------------------ thème
    def restyle(self):
        colors = {"tcp": TEXT, "syn": MUTED, "udp": ACCENT, "dns": TEAL, "icmp": PURPLE, "rst": RED}
        for tag, c in colors.items():
            self.tree.tag_configure(tag, foreground=mode_color(c))
        for c in (self.detail_out, self.hex_out):
            c._refresh_tags()

    def shutdown(self):
        if self.capture:
            self.capture.stop()


class _TextDialog(ctk.CTkToplevel):
    """Fenêtre de texte monospace (aide, statistiques) avec bouton Copier."""

    def __init__(self, master, title: str, text: str, width: int = 640, height: int = 460):
        super().__init__(master)
        self.title(title)
        self.configure(fg_color=SURFACE2)
        self.transient(master.winfo_toplevel())
        self.geometry(f"{width}x{height}")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        label(self, title, Fonts.h2).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 6))
        out = Console(self, wrap="none")
        out.grid(row=1, column=0, sticky="nsew", padx=18)
        out.write(text)
        out.see("1.0")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=18, pady=12)
        button(bar, _("Fermer"), self.destroy, kind="primary", width=100).pack(side="right")
        button(bar, _("Copier"), lambda: (self.clipboard_clear(), self.clipboard_append(text)), width=90).pack(
            side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(80, self.lift)
