"""Fenêtre principale de NetShift."""
from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from . import __version__
from . import netbackend as nb
from . import nettools as nt
from .store import History, PresetStore, Settings, app_dir, data_dir, normalize_config, resource_dir, summarize
from .tools_view import ToolsView
from .ui import (
    ACCENT,
    ACCENT_SOFT,
    BG,
    BORDER,
    GREEN,
    GREEN_SOFT,
    GREY_SOFT,
    HOVER,
    MUTED,
    ORANGE,
    ORANGE_SOFT,
    RED,
    RED_SOFT,
    SIDEBAR,
    SURFACE,
    SURFACE2,
    TEXT,
    ConfigForm,
    Console,
    Fonts,
    TabHost,
    ask_string,
    button,
    card,
    confirm,
    entry,
    info,
    label,
    option_menu,
    pill,
    segmented,
    style_treeview,
    ui_scale,
)
from .vpn_view import VpnView

APP_NAME = "NetShift"
VERSION = __version__
LOAD_PRESET = "Charger un preset…"


def describe(cfg: dict) -> str:
    cfg = normalize_config(cfg)
    lines = []
    if cfg["mode"] == "dhcp":
        lines.append("Adresse    : automatique (DHCP)")
    else:
        try:
            p = nb.parse_mask(cfg["mask"])
            mask = f"{nb.prefix_to_mask(p)} (/{p})"
        except ValueError:
            mask = cfg["mask"]
        lines.append(f"Adresse    : {cfg['ip']}")
        lines.append(f"Masque     : {mask}")
        lines.append(f"Passerelle : {cfg['gateway'] or 'aucune'}")
        for x in cfg["extra_ips"]:
            lines.append(f"IP suppl.  : {x}")
    if cfg["dns_mode"] == "auto" and cfg["mode"] == "dhcp":
        lines.append("DNS        : automatiques (DHCP)")
    else:
        dns = ", ".join(d for d in (cfg["dns1"], cfg["dns2"]) if d) or "aucun"
        lines.append(f"DNS        : {dns}")
    return "\n".join(lines)


# =========================================================================== #
#  Carte réseau dans la barre latérale
# =========================================================================== #
class AdapterCard(ctk.CTkFrame):
    def __init__(self, master, adapter: nb.Adapter, on_click):
        super().__init__(master, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER,
                         cursor="hand2")
        self.adapter = adapter
        self.on_click = on_click
        self.grid_columnconfigure(1, weight=1)
        # hauteurs explicites : un CTkLabel fait 28 px minimum par défaut
        self.dot = label(self, "●", ctk.CTkFont("Segoe UI", 11), height=18, width=10)
        self.dot.grid(row=0, column=0, sticky="w", padx=(10, 6), pady=(7, 0))
        self.name = label(self, "", Fonts.h3, anchor="w", height=18)
        self.name.grid(row=0, column=1, sticky="ew", pady=(7, 0), padx=(0, 4))
        self.badge = ctk.CTkLabel(self, text="", font=ctk.CTkFont("Segoe UI", 9, "bold"), height=16,
                                  corner_radius=4, fg_color=GREY_SOFT, text_color=MUTED)
        self.badge.grid(row=0, column=2, sticky="e", pady=(7, 0), padx=(0, 10))
        self.ip = label(self, "", Fonts.mono_small, anchor="w", height=16)
        self.ip.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 10), pady=(1, 0))
        self.desc = label(self, "", Fonts.small, MUTED, anchor="w", height=15)
        self.desc.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(0, 7), padx=(0, 10))
        for w in (self, self.dot, self.name, self.badge, self.ip, self.desc):
            w.bind("<Button-1>", lambda e: self.on_click(self.adapter.guid))
            w.bind("<Enter>", lambda e: self._hover(True))
            w.bind("<Leave>", lambda e: self._hover(False))
        self._selected = False
        self.update_adapter(adapter)

    def update_adapter(self, a: nb.Adapter):
        self.adapter = a
        color = GREEN if a.up else (RED if a.disabled else MUTED)
        self.dot.configure(text_color=color)
        self.name.configure(text=a.name)
        self.badge.configure(text=f" {nb.KINDS.get(a.kind, nb.KINDS['other'])[1]} ")
        p = a.primary_ip
        if a.disabled:
            ip_txt, ip_col = "Désactivée", RED
        elif p and not p.ip.startswith("169.254."):
            ip_txt, ip_col = f"{p.ip}/{p.prefix}" + ("  · DHCP" if a.dhcp else ""), TEXT
        elif not a.up:
            ip_txt, ip_col = ("Câble déconnecté" if a.kind == "ethernet" else "Déconnectée"), MUTED
        else:
            ip_txt, ip_col = ("APIPA " + p.ip if p else "Aucune IP"), ORANGE
        self.ip.configure(text=ip_txt, text_color=ip_col)
        d = a.description
        self.desc.configure(text=d if len(d) <= 36 else d[:34] + "…")

    def set_selected(self, sel: bool):
        self._selected = sel
        self.configure(border_color=ACCENT if sel else BORDER, border_width=2 if sel else 1,
                       fg_color=ACCENT_SOFT if sel else SURFACE)

    def _hover(self, on: bool):
        if not self._selected:
            self.configure(fg_color=HOVER if on else SURFACE)


# =========================================================================== #
#  Application
# =========================================================================== #
class App(ctk.CTk):
    def __init__(self):
        ddir = data_dir()
        self.settings = Settings(ddir)
        ctk.set_appearance_mode({"light": "light", "dark": "dark"}.get(self.settings.get("theme"), "system"))
        super().__init__(fg_color=BG)
        Fonts.init()
        self.presets = PresetStore(ddir)
        self.history = History(ddir)
        self.admin = nb.is_admin()

        self.adapters: list[nb.Adapter] = []
        self.selected_guid: str | None = self.settings.get("last_adapter")
        self.cards: dict[str, AdapterCard] = {}
        self._uiq: queue.Queue = queue.Queue()
        self._busy = 0
        self._refreshing = False
        self._applying = False
        self._toast_job = None
        self.selected_preset: str | None = None
        self._preset_cards: dict[str, ctk.CTkFrame] = {}

        self.title(f"{APP_NAME}{'' if self.admin else '  —  lecture seule'}")
        self.geometry(self.settings.get("geometry", "1320x840"))
        self.minsize(1120, 720)
        ico = resource_dir() / "assets" / "netshift.ico"
        self.icon_path = str(ico) if ico.exists() else None
        if self.icon_path:
            try:
                self.iconbitmap(self.icon_path)
            except tk.TclError:
                self.icon_path = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
        self._build_statusbar()
        style_treeview(self)

        self.bind("<F5>", lambda e: self.refresh_adapters())
        self.bind("<Control-Return>", lambda e: self.apply_editor())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(40, self._pump)
        self.after(100, lambda: self.refresh_adapters(first=True))
        self.log(f"{APP_NAME} {VERSION} démarré — {'administrateur' if self.admin else 'LECTURE SEULE (pas admin)'}"
                 f" — données : {ddir}", "muted")

    # ------------------------------------------------------------------ infra
    def ui(self, fn, *args, **kw):
        """Exécute fn dans le thread de l'interface (appelable depuis n'importe quel thread)."""
        self._uiq.put((fn, args, kw))

    def _pump(self):
        try:
            while True:
                fn, args, kw = self._uiq.get_nowait()
                try:
                    fn(*args, **kw)
                except Exception:
                    self.log(traceback.format_exc(), "err")
        except queue.Empty:
            pass
        self.after(40, self._pump)

    def bg(self, work, done=None, busy: str | None = None, error=None):
        if busy:
            self._set_busy(+1, busy)

        def runner():
            try:
                res = work()
                if done:
                    self.ui(done, res)
            except Exception as e:
                if error:
                    self.ui(error, e)
                else:
                    self.ui(self.toast, f"Erreur : {e}", "err")
                    self.ui(self.log, f"Erreur : {e}", "err")
            finally:
                if busy:
                    self.ui(self._set_busy, -1)

        threading.Thread(target=runner, daemon=True).start()

    def _set_busy(self, delta, msg=None):
        self._busy = max(0, self._busy + delta)
        if self._busy:
            self.progress.grid()
            self.progress.start()
            if msg:
                self.status.configure(text=msg, text_color=MUTED)
        else:
            self.progress.stop()
            self.progress.grid_remove()
            if self.status.cget("text").endswith("…"):   # message d'attente non remplacé par un toast
                self.status.configure(text="Prêt", text_color=MUTED)

    def toast(self, msg: str, kind: str = "info"):
        colors = {"ok": GREEN, "err": RED, "warn": ORANGE, "info": TEXT}
        icons = {"ok": "✓  ", "err": "✕  ", "warn": "⚠  ", "info": ""}
        self.status.configure(text=icons[kind] + msg, text_color=colors[kind])
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(8000, lambda: self.status.configure(text="Prêt", text_color=MUTED))

    def log(self, msg: str, tag: str | None = None):
        stamp = time.strftime("%H:%M:%S")
        if hasattr(self, "journal"):
            self.journal.write(f"[{stamp}] {msg}", tag)

    def copy(self, text: str, quiet: bool = False):
        self.clipboard_clear()
        self.clipboard_append(text)
        if not quiet:
            self.toast(f"Copié : {text if len(text) < 60 else text[:57] + '…'}", "ok")

    @property
    def selected(self) -> nb.Adapter | None:
        return next((a for a in self.adapters if a.guid == self.selected_guid), None)

    # ================================================================ SIDEBAR
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0, width=300)
        sb.grid(row=0, column=0, rowspan=2, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_rowconfigure(2, weight=1)

        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(20, 14))
        logo = self._logo_label(brand)
        logo.pack(side="left")
        t = ctk.CTkFrame(brand, fg_color="transparent")
        t.pack(side="left", padx=(10, 0))
        label(t, APP_NAME, Fonts.h2).pack(anchor="w")
        label(t, "Configurations réseau", Fonts.small, MUTED).pack(anchor="w")

        head = ctk.CTkFrame(sb, fg_color="transparent")
        head.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 4))
        top = ctk.CTkFrame(head, fg_color="transparent")
        top.pack(fill="x")
        label(top, "CARTES RÉSEAU", Fonts.small_bold, MUTED).pack(side="left")
        self.refresh_btn = button(top, "⟳", self.refresh_adapters, kind="ghost", width=30, height=26,
                                  font=ctk.CTkFont("Segoe UI", 15))
        self.refresh_btn.pack(side="right")
        self.kind_bar = ctk.CTkFrame(head, fg_color="transparent")
        self.kind_bar.pack(fill="x", pady=(4, 0))
        self._kind_sig = None
        if "hidden_kinds" not in self.settings.data:   # reprise de l'ancien réglage « cartes virtuelles »
            self.settings.set("hidden_kinds", [] if self.settings.get("show_virtual", True) else ["virtual"])

        self.card_list = ctk.CTkScrollableFrame(sb, fg_color="transparent", corner_radius=0)
        self.card_list.grid(row=2, column=0, sticky="nsew", padx=(10, 4))
        self.card_list.grid_columnconfigure(0, weight=1)
        self.loading_lbl = label(self.card_list, "Lecture des cartes…", Fonts.small, MUTED)
        self.loading_lbl.grid(row=0, column=0, pady=20)

        opts = ctk.CTkFrame(sb, fg_color="transparent")
        opts.grid(row=3, column=0, sticky="ew", padx=18, pady=(8, 0))
        self.show_down = ctk.CTkSwitch(opts, text="Cartes déconnectées", font=Fonts.small, text_color=MUTED,
                                       progress_color=ACCENT, command=self._toggle_show_down)
        if self.settings.get("show_disconnected", True):
            self.show_down.select()
        self.show_down.pack(anchor="w", pady=2)
        self.auto_refresh = ctk.CTkSwitch(opts, text="Actualisation auto (5 s)", font=Fonts.small, text_color=MUTED,
                                          progress_color=ACCENT,
                                          command=lambda: self.settings.set("auto_refresh",
                                                                            bool(self.auto_refresh.get())))
        if self.settings.get("auto_refresh", True):
            self.auto_refresh.select()
        self.auto_refresh.pack(anchor="w", pady=2)
        self.confirm_sw = ctk.CTkSwitch(opts, text="Confirmer avant d'appliquer", font=Fonts.small,
                                        text_color=MUTED, progress_color=ACCENT,
                                        command=lambda: self.settings.set("confirm", bool(self.confirm_sw.get())))
        if self.settings.get("confirm", True):
            self.confirm_sw.select()
        self.confirm_sw.pack(anchor="w", pady=2)

        bottom = ctk.CTkFrame(sb, fg_color="transparent")
        bottom.grid(row=4, column=0, sticky="ew", padx=18, pady=(12, 16))
        bottom.grid_columnconfigure(0, weight=1)
        self.theme_seg = segmented(bottom, ["Clair", "Sombre", "Auto"], command=self._set_theme, height=28,
                                   font=Fonts.small)
        self.theme_seg.set({"light": "Clair", "dark": "Sombre"}.get(self.settings.get("theme"), "Auto"))
        self.theme_seg.grid(row=0, column=0, sticky="ew")
        button(bottom, "Créer un raccourci sur le bureau", self.create_shortcut, kind="ghost", font=Fonts.small,
               height=26).grid(row=1, column=0, sticky="ew", pady=(8, 0))

    def _logo_label(self, master) -> ctk.CTkLabel:
        """Logo PNG à la taille la plus proche de 38 px × facteur d'échelle (PNG natif Tk, sans Pillow)."""
        target = 38 * ui_scale(self)
        files = sorted((resource_dir() / "assets").glob("logo-*.png"), key=lambda p: abs(int(p.stem[5:]) - target))
        if files:
            try:
                self._logo_img = tk.PhotoImage(file=str(files[0]))
                return ctk.CTkLabel(master, text="", image=self._logo_img, fg_color="transparent")
            except tk.TclError:
                pass
        return ctk.CTkLabel(master, text="⇄", font=ctk.CTkFont("Segoe UI", 20, "bold"), width=38, height=38,
                            corner_radius=10, fg_color=ACCENT, text_color="#FFFFFF")

    def _toggle_show_down(self):
        self.settings.set("show_disconnected", bool(self.show_down.get()))
        self._render_cards(force=True)

    def _render_kind_chips(self):
        """Une pastille par type de carte présent : clic = afficher / masquer ce type."""
        counts: dict[str, int] = {}
        for a in self.adapters:
            counts[a.kind] = counts.get(a.kind, 0) + 1
        hidden = set(self.settings.get("hidden_kinds", []))
        sig = (tuple(sorted(counts.items())), tuple(sorted(hidden)))
        if sig == self._kind_sig:
            return
        self._kind_sig = sig
        for w in self.kind_bar.winfo_children():
            w.destroy()
        kinds = [k for k in nb.KINDS if k in counts]
        for i, k in enumerate(kinds):
            shown = k not in hidden
            b = ctk.CTkButton(self.kind_bar, text=f"{nb.KINDS[k][0]} {counts[k]}", width=0, height=22,
                              corner_radius=11, font=Fonts.small, border_width=1,
                              fg_color=ACCENT_SOFT if shown else "transparent", hover_color=HOVER,
                              border_color=ACCENT if shown else BORDER, text_color=ACCENT if shown else MUTED,
                              command=lambda k=k: self._toggle_kind(k))
            b.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 4), pady=2)

    def _toggle_kind(self, kind: str):
        hidden = set(self.settings.get("hidden_kinds", []))
        hidden.symmetric_difference_update({kind})
        self.settings.set("hidden_kinds", sorted(hidden))
        self._render_kind_chips()
        self._render_cards(force=True)

    def _set_theme(self, v):
        mode = {"Clair": "light", "Sombre": "dark", "Auto": "system"}[v]
        self.settings.set("theme", mode)
        ctk.set_appearance_mode(mode)
        self.after(50, self._restyle)

    def _restyle(self):
        style_treeview(self)
        self.tools.restyle()
        self.journal._refresh_tags()

    def _visible_adapters(self) -> list[nb.Adapter]:
        hidden = set(self.settings.get("hidden_kinds", []))
        out = []
        for a in self.adapters:
            if not self.show_down.get() and not a.up and a.guid != self.selected_guid:
                continue
            if a.kind in hidden and a.guid != self.selected_guid:
                continue
            out.append(a)
        return out

    def _render_cards(self, force=False):
        self._render_kind_chips()
        visible = self._visible_adapters()
        keys = [a.guid for a in visible]
        if force or keys != list(self.cards.keys()):
            for c in self.cards.values():
                c.destroy()
            self.cards = {}
            self.loading_lbl.grid_remove()
            for i, a in enumerate(visible):
                c = AdapterCard(self.card_list, a, self.select_adapter)
                c.grid(row=i + 1, column=0, sticky="ew", pady=3, padx=(0, 6))
                self.cards[a.guid] = c
            masked = len(self.adapters) - len(visible)
            if not visible or masked:
                txt = f"{masked} carte(s) masquée(s) par les filtres" if masked else "Aucune carte à afficher"
                self.loading_lbl.configure(text=txt)
                self.loading_lbl.grid(row=len(visible) + 1, column=0, pady=(6, 10))
        else:
            for a in visible:
                self.cards[a.guid].update_adapter(a)
        for g, c in self.cards.items():
            c.set_selected(g == self.selected_guid)

    # =================================================================== MAIN
    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=20, pady=(16, 0))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        if not self.admin:
            ban = ctk.CTkFrame(main, fg_color=ORANGE_SOFT, corner_radius=10)
            ban.grid(row=0, column=0, sticky="ew", pady=(0, 12))
            label(ban, "⚠  Mode lecture seule — modifier une configuration IP nécessite les droits administrateur.",
                  Fonts.body, ORANGE).pack(side="left", padx=14, pady=10)
            button(ban, "Relancer en administrateur", self.relaunch_admin, kind="primary", height=30).pack(
                side="right", padx=10, pady=8)

        self._build_header(main)

        self.tabs = TabHost(main, ["Configuration", "Presets", "VPN", "Outils", "Historique & journal"],
                            command=self._on_tab)
        self.tabs.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        self._build_config_tab(self.tabs.tab("Configuration"))
        self._build_presets_tab(self.tabs.tab("Presets"))
        self.vpn = VpnView(self.tabs.tab("VPN"), self)
        self.vpn.grid(row=0, column=0, sticky="nsew")
        self._vpn_loaded = False
        self.tools = ToolsView(self.tabs.tab("Outils"), self)
        self.tools.grid(row=0, column=0, sticky="nsew")
        self._build_history_tab(self.tabs.tab("Historique & journal"))

    def _on_tab(self):
        if not hasattr(self, "tabs"):   # appelé par TabHost pendant sa construction
            return
        tab = self.tabs.get()
        if hasattr(self, "hist_list") and tab == "Historique & journal":
            self._render_history()
        elif tab == "VPN" and hasattr(self, "vpn"):
            self.vpn.refresh(quiet=self._vpn_loaded)
            self._vpn_loaded = True

    # ----------------------------------------------------------------- header
    def _build_header(self, main):
        h = card(main)
        h.grid(row=1, column=0, sticky="ew")
        h.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(h, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 0))
        self.h_name = label(top, "Chargement…", Fonts.h1)
        self.h_name.pack(side="left")
        self.h_status = pill(top, "…")
        self._pills_shown = False
        self.h_mode = pill(top, "…")

        actions = ctk.CTkFrame(top, fg_color="transparent")
        actions.pack(side="right")
        self.btn_undo = button(actions, "↶  Annuler le dernier changement", self.undo_last, width=0)
        self.btn_undo.pack(side="left", padx=(0, 6))
        self.btn_renew = button(actions, "⟳  Renouveler DHCP", self.renew_dhcp, width=0)
        self.btn_renew.pack(side="left", padx=(0, 6))
        self.btn_toggle = button(actions, "⏻  Désactiver", self.toggle_adapter, width=0)
        self.btn_toggle.pack(side="left", padx=(0, 6))
        self.btn_more = button(actions, "⋯", self._more_menu, width=36)
        self.btn_more.pack(side="left")

        self.h_desc = label(h, "", Fonts.small, MUTED, anchor="w")
        self.h_desc.grid(row=1, column=0, sticky="w", padx=18)
        chips = ctk.CTkFrame(h, fg_color="transparent")
        chips.grid(row=2, column=0, sticky="w", padx=18, pady=(8, 14))
        self.h_chips = {}
        for key, txt in (("mac", "MAC"), ("speed", "Vitesse"), ("mtu", "MTU"), ("index", "Index")):
            f = ctk.CTkFrame(chips, fg_color=SURFACE2, corner_radius=8, cursor="hand2")
            f.pack(side="left", padx=(0, 8))
            label(f, txt, Fonts.small, MUTED).pack(side="left", padx=(10, 6), pady=4)
            v = label(f, "—", Fonts.mono_small)
            v.pack(side="left", padx=(0, 10), pady=4)
            for w in (f, v):
                w.bind("<Button-1>", lambda e, v=v: self.copy(v.cget("text")))
            self.h_chips[key] = v

    def _more_menu(self):
        a = self.selected
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Renommer la carte…", command=self.rename_adapter)
        m.add_command(label="Modifier le MTU…", command=self.change_mtu)
        m.add_command(label="Libérer le bail DHCP", command=self.release_dhcp)
        m.add_separator()
        m.add_command(label="Copier le résumé de la carte", command=self.copy_summary)
        m.add_command(label="Enregistrer la config actuelle comme preset", command=self.save_current_as_preset)
        m.add_separator()
        m.add_command(label="Ouvrir les connexions réseau (ncpa.cpl)", command=lambda: os.startfile("ncpa.cpl"))
        if not a:
            for i in (0, 1, 2, 4, 5):
                m.entryconfigure(i, state="disabled")
        x = self.btn_more.winfo_rootx()
        y = self.btn_more.winfo_rooty() + self.btn_more.winfo_height()
        m.tk_popup(x, y)

    def _render_header(self):
        a = self.selected
        if not a:
            self.h_name.configure(text="Aucune carte sélectionnée")
            self.h_desc.configure(text="")
            for b in (self.btn_undo, self.btn_renew, self.btn_toggle, self.btn_more):
                b.configure(state="disabled")
            return
        self.h_name.configure(text=a.name)
        self.h_desc.configure(text=a.description)
        if not self._pills_shown:
            self.h_status.pack(side="left", padx=(12, 0))
            self.h_mode.pack(side="left", padx=(6, 0))
            self._pills_shown = True
        if a.up:
            self.h_status.configure(text="  Connectée  ", fg_color=GREEN_SOFT, text_color=GREEN)
        elif a.disabled:
            self.h_status.configure(text="  Désactivée  ", fg_color=RED_SOFT, text_color=RED)
        else:
            self.h_status.configure(text="  Déconnectée  ", fg_color=GREY_SOFT, text_color=MUTED)
        self.h_mode.configure(text="  DHCP  " if a.dhcp else "  IP fixe  ",
                              fg_color=ACCENT_SOFT if a.dhcp else ORANGE_SOFT,
                              text_color=ACCENT if a.dhcp else ORANGE)
        self.h_chips["mac"].configure(text=a.mac or "—")
        self.h_chips["speed"].configure(text=a.speed if a.up else "—")
        self.h_chips["mtu"].configure(text=str(a.mtu or "—"))
        self.h_chips["index"].configure(text=str(a.index))
        st = "normal" if self.admin else "disabled"
        self.btn_toggle.configure(text="⏻  Activer" if a.disabled else "⏻  Désactiver", state=st)
        self.btn_renew.configure(state=st if a.dhcp and a.up else "disabled")
        self.btn_undo.configure(state=st if self.history.last_for(a.description) else "disabled")
        self.btn_more.configure(state="normal")

    # ========================================================== CONFIG TAB
    def _build_config_tab(self, tab):
        wrap = ctk.CTkFrame(tab, fg_color="transparent")
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.grid_columnconfigure(1, weight=1)
        wrap.grid_rowconfigure(0, weight=1)

        # --- configuration actuelle
        cur = card(wrap, width=340)
        cur.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        cur.grid_propagate(False)
        cur.grid_columnconfigure(0, weight=1)
        cur.grid_rowconfigure(1, weight=1)
        label(cur, "Configuration actuelle", Fonts.h2).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 6))
        self.cur_body = ctk.CTkFrame(cur, fg_color="transparent")
        self.cur_body.grid(row=1, column=0, sticky="nsew", padx=18)
        self.cur_body.grid_columnconfigure(1, weight=1)
        btns = ctk.CTkFrame(cur, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 16))
        btns.grid_columnconfigure(0, weight=1)
        button(btns, "Copier dans l'éditeur  →", self.copy_current_to_editor).grid(row=0, column=0, sticky="ew")
        button(btns, "Enregistrer comme preset", self.save_current_as_preset).grid(row=1, column=0, sticky="ew",
                                                                                  pady=(6, 0))
        label(cur, "Clic sur une valeur pour la copier", Fonts.small, MUTED).grid(row=3, column=0, pady=(0, 12))

        # --- éditeur
        ed = card(wrap)
        ed.grid(row=0, column=1, sticky="nsew")
        ed.grid_columnconfigure(0, weight=1)
        ed.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(ed, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        label(top, "Nouvelle configuration", Fonts.h2).pack(side="left")
        self.cfg_loader = option_menu(top, [LOAD_PRESET], self._load_preset_into_editor, width=230)
        self.cfg_loader.pack(side="right")

        scroll = ctk.CTkScrollableFrame(ed, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", padx=(10, 6))
        scroll.grid_columnconfigure(0, weight=1)
        self.form = ConfigForm(scroll)
        self.form.grid(row=0, column=0, sticky="nsew", padx=(8, 8), pady=(0, 8))

        bar = ctk.CTkFrame(ed, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=18, pady=(4, 16))
        self.apply_btn = button(bar, "Appliquer", self.apply_editor, kind="primary", height=40,
                                font=Fonts.h3, width=260)
        self.apply_btn.pack(side="left")
        button(bar, "Enregistrer comme preset", self.save_editor_as_preset, height=40).pack(side="left", padx=(8, 0))
        button(bar, "Réinitialiser", lambda: self.form.set_config({"mode": "static"}), kind="ghost",
               height=40).pack(side="right")
        label(bar, "Ctrl+Entrée", Fonts.small, MUTED).pack(side="left", padx=(12, 0))

    def _render_current(self):
        for w in self.cur_body.winfo_children():
            w.destroy()
        a = self.selected
        if not a:
            return
        rows: list[tuple[str, str, object]] = []
        rows.append(("Mode", "DHCP (automatique)" if a.dhcp else "Statique (manuelle)", ACCENT if a.dhcp else ORANGE))
        if a.ips:
            for i, ip in enumerate(a.ips):
                warn = ip.ip.startswith("169.254.")
                rows.append(("Adresse IP" if i == 0 else "", f"{ip.ip}/{ip.prefix}", ORANGE if warn else TEXT))
            p = a.primary_ip
            rows.append(("Masque", p.mask, TEXT))
        else:
            rows.append(("Adresse IP", "aucune", MUTED))
        if a.gateways:
            for i, g in enumerate(a.gateways):
                rows.append(("Passerelle" if i == 0 else "", g, TEXT))
        else:
            rows.append(("Passerelle", "aucune", MUTED))
        dns_src = "manuels" if (a.dns_static or not a.dhcp) else "DHCP"
        if a.dns:
            for i, d in enumerate(a.dns):
                rows.append((f"DNS ({dns_src})" if i == 0 else "", d, TEXT))
        else:
            rows.append(("DNS", "aucun", MUTED))
        if a.primary_ip and a.primary_ip.ip.startswith("169.254."):
            rows.append(("", "⚠ APIPA : aucun serveur DHCP n'a répondu", ORANGE))

        for r, (k, v, col) in enumerate(rows):
            label(self.cur_body, k, Fonts.small, MUTED, anchor="w").grid(row=r, column=0, sticky="nw", pady=4,
                                                                          padx=(0, 12))
            lv = label(self.cur_body, v, Fonts.mono if r else Fonts.body, col, anchor="w", justify="left",
                       wraplength=190, cursor="hand2")
            lv.grid(row=r, column=1, sticky="w", pady=4)
            lv.bind("<Button-1>", lambda e, v=v: self.copy(v.split("/")[0] if "/" in v and "." in v else v))

    def _update_apply_btn(self):
        a = self.selected
        name = a.name if a else "—"
        self.apply_btn.configure(text=f"Appliquer à « {name if len(name) < 22 else name[:20] + '…'} »",
                                 state="normal" if (a and self.admin) else "disabled")

    def copy_current_to_editor(self):
        a = self.selected
        if a:
            self.form.set_config(a.to_config())
            self.toast("Configuration actuelle copiée dans l'éditeur", "ok")

    def _load_preset_into_editor(self, name):
        p = self.presets.by_name(name)
        if p:
            self.form.set_config(p["config"])
            self.toast(f"Preset « {name} » chargé dans l'éditeur", "ok")
        self.cfg_loader.set(LOAD_PRESET)

    def apply_editor(self):
        a = self.selected
        if a:
            self.apply(a, self.form.get_config(), "Éditeur")

    def save_editor_as_preset(self):
        cfg = self.form.get_config()
        errors, _ = nb.validate_config(cfg)
        if errors:
            info(self, "Configuration invalide", "Corrige les erreurs avant d'enregistrer :", "\n".join(errors))
            return
        self._save_preset_dialog(cfg, "Nouveau preset")

    def save_current_as_preset(self):
        a = self.selected
        if a:
            self._save_preset_dialog(a.to_config(), f"{a.name} — {time.strftime('%d/%m %H:%M')}")

    def _save_preset_dialog(self, cfg, default_name):
        name = ask_string(self, "Enregistrer un preset", f"Donne un nom à ce preset ({summarize(cfg)}) :",
                          default_name, "Enregistrer")
        if name and name.strip():
            p = self.presets.add(name.strip(), cfg)
            self._presets_changed(select=p["id"])
            self.toast(f"Preset « {p['name']} » enregistré", "ok")
            self.log(f"Preset enregistré : {p['name']} ({summarize(cfg)})")

    # ------------------------------------------------------------- appliquer
    def apply(self, adapter: nb.Adapter, cfg: dict, label_txt: str):
        if not self.admin:
            info(self, "Droits insuffisants", "Relance NetShift en administrateur pour appliquer une configuration.")
            return
        if self._applying:
            self.toast("Une application est déjà en cours…", "warn")
            return
        cfg = normalize_config(cfg)
        errors, warns = nb.validate_config(cfg)
        if errors:
            info(self, "Configuration invalide", "Impossible d'appliquer :", "\n".join(errors))
            return
        detail = f"Carte      : {adapter.name}\n{describe(cfg)}"
        if warns:
            detail += "\n\n⚠ " + "\n⚠ ".join(warns)
        if (self.settings.get("confirm", True) or warns) and not confirm(
                self, "Appliquer la configuration ?",
                f"La configuration IP de « {adapter.name} » va être modifiée. "
                "Les connexions en cours sur cette carte peuvent être coupées.",
                "Appliquer", detail=detail):
            return
        before = adapter.to_config()
        self._applying = True
        self.apply_btn.configure(state="disabled")
        self.log(f"Application sur {adapter.name} ({label_txt}) : {summarize(cfg)}", "accent")

        def work():
            logs = []
            ok = nb.apply_config(adapter, cfg, log=lambda s: logs.append(s))
            return ok, logs

        def done(res):
            ok, logs = res
            self._applying = False
            for line in logs:
                self.log("   " + line.replace("\n", "\n   "), "muted")
            self.history.add(adapter.name, adapter.description, before, cfg, label_txt, ok)
            if ok:
                self.toast(f"Configuration appliquée à {adapter.name}", "ok")
                self.log(f"✓ Configuration appliquée à {adapter.name}", "ok")
            else:
                self.toast(f"Échec partiel sur {adapter.name} — voir le journal", "err")
                self.log(f"✕ Des erreurs sont survenues sur {adapter.name}", "err")
            self.refresh_adapters(quiet=True)
            for delay in (2000, 5000, 10000):
                self.after(delay, lambda: self.refresh_adapters(quiet=True))
            if ok and cfg["mode"] == "static" and cfg["gateway"]:
                self.after(2500, lambda: self._verify_gateway(cfg["gateway"]))
            self._update_apply_btn()

        def error(e):
            self._applying = False
            self._update_apply_btn()
            self.toast(f"Erreur : {e}", "err")
            self.log(f"Erreur : {e}", "err")

        self.bg(work, done, busy=f"Application de la configuration sur {adapter.name}…", error=error)

    def _verify_gateway(self, gw):
        def work():
            for _ in range(3):
                r = nt.ping(gw, 1000)
                if r.ok:
                    return r
                time.sleep(0.8)
            return r

        def done(r):
            if r.ok:
                self.log(f"   Vérification : passerelle {gw} joignable ({r.rtt} ms)", "ok")
            else:
                self.log(f"   Vérification : passerelle {gw} injoignable ({r.error})", "warn")
                self.toast(f"Appliqué, mais la passerelle {gw} ne répond pas au ping", "warn")

        self.bg(work, done)

    def undo_last(self):
        a = self.selected
        e = self.history.last_for(a.description) if a else None
        if not e:
            return
        self.apply(a, e["before"], f"Annulation ({e['time']})")

    # ------------------------------------------------------- actions carte
    def toggle_adapter(self):
        a = self.selected
        if not a:
            return
        enable = a.disabled
        if not enable and not confirm(self, "Désactiver la carte ?",
                                      f"« {a.name} » sera désactivée jusqu'à ce que tu la réactives.",
                                      "Désactiver", kind="danger"):
            return
        verb = "Activation" if enable else "Désactivation"
        self.log(f"{verb} de {a.name}")

        def done(res):
            code, out = res
            if code == 0:
                self.toast(f"{a.name} {'activée' if enable else 'désactivée'}", "ok")
            else:
                self.toast(f"{verb} impossible — voir le journal", "err")
                self.log(out, "err")
            self.refresh_adapters(quiet=True)
            self.after(3000, lambda: self.refresh_adapters(quiet=True))

        self.bg(lambda: nb.set_adapter_enabled(a, enable), done, busy=f"{verb} de {a.name}…")

    def renew_dhcp(self):
        a = self.selected
        if a:
            self._ipconfig(nb.dhcp_renew, a, "Renouvellement DHCP")

    def release_dhcp(self):
        a = self.selected
        if a and confirm(self, "Libérer le bail DHCP ?", f"« {a.name} » perdra son adresse IP jusqu'au "
                                                         "prochain renouvellement.", "Libérer", kind="danger"):
            self._ipconfig(nb.dhcp_release, a, "Libération DHCP")

    def _ipconfig(self, fn, a, what):
        self.log(f"{what} : {a.name}")

        def done(res):
            code, out = res
            self.log(out or "(pas de sortie)", "muted" if code == 0 else "err")
            self.toast(f"{what} {'terminé' if code == 0 else 'en échec'}", "ok" if code == 0 else "err")
            self.refresh_adapters(quiet=True)

        self.bg(lambda: fn(a), done, busy=f"{what} de {a.name}…")

    def rename_adapter(self):
        a = self.selected
        if not a or not self.admin:
            return
        new = ask_string(self, "Renommer la carte", f"Nouveau nom pour « {a.name} » :", a.name, "Renommer")
        if not new or new.strip() == a.name:
            return

        def done(res):
            code, out = res
            if code == 0:
                self.toast(f"Carte renommée en « {new.strip()} »", "ok")
                self.log(f"Carte « {a.name} » renommée en « {new.strip()} »")
            else:
                self.toast("Renommage impossible", "err")
                self.log(out, "err")
            self.refresh_adapters(quiet=True)

        self.bg(lambda: nb.rename_adapter(a, new.strip()), done, busy="Renommage…")

    def change_mtu(self):
        a = self.selected
        if not a or not self.admin:
            return
        v = ask_string(self, "Modifier le MTU", "Valeur entre 576 et 9000 (1500 par défaut, 9000 pour les "
                                                "jumbo frames si l'équipement le supporte).", str(a.mtu or 1500),
                       "Appliquer")
        if not v:
            return
        try:
            mtu = int(v)
            assert 576 <= mtu <= 9216
        except (ValueError, AssertionError):
            self.toast("MTU invalide", "err")
            return

        def done(res):
            code, out = res
            self.log(f"MTU {mtu} sur {a.name} : {out or 'OK'}", None if code == 0 else "err")
            self.toast(f"MTU réglé à {mtu}" if code == 0 else "Échec du changement de MTU",
                       "ok" if code == 0 else "err")
            self.refresh_adapters(quiet=True)

        self.bg(lambda: nb.set_mtu(a, mtu), done, busy="Changement du MTU…")

    def copy_summary(self):
        a = self.selected
        if not a:
            return
        lines = [f"{a.name} — {a.description}", f"État : {a.status}   MAC : {a.mac}   Vitesse : {a.speed}",
                 f"Mode : {'DHCP' if a.dhcp else 'Statique'}"]
        lines += [f"IP : {i.ip}/{i.prefix} ({i.mask})" for i in a.ips]
        lines += [f"Passerelle : {g}" for g in a.gateways]
        lines.append("DNS : " + (", ".join(a.dns) or "aucun"))
        self.copy("\n".join(lines), quiet=True)
        self.toast("Résumé de la carte copié", "ok")

    # ========================================================= PRESETS TAB
    def _build_presets_tab(self, tab):
        wrap = ctk.CTkFrame(tab, fg_color="transparent")
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.grid_columnconfigure(1, weight=1)
        wrap.grid_rowconfigure(0, weight=1)

        left = card(wrap, width=360)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.grid_propagate(False)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(left, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 6))
        label(top, "Mes presets", Fonts.h2).pack(side="left")
        button(top, "+ Nouveau", self.new_preset, kind="primary", width=0, height=30).pack(side="right")
        self.preset_search = entry(left, "Rechercher…", width=0)
        self.preset_search.grid(row=1, column=0, sticky="ew", padx=16, pady=(4, 6))
        self.preset_search.bind("<KeyRelease>", lambda e: self._render_preset_list())
        self.preset_list = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.preset_list.grid(row=2, column=0, sticky="nsew", padx=(8, 4))
        self.preset_list.grid_columnconfigure(0, weight=1)
        io = ctk.CTkFrame(left, fg_color="transparent")
        io.grid(row=3, column=0, sticky="ew", padx=16, pady=(6, 14))
        io.grid_columnconfigure((0, 1), weight=1)
        button(io, "Importer…", self.import_presets, height=30).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        button(io, "Exporter…", self.export_presets, height=30).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        label(left, "Double-clic : appliquer à la carte sélectionnée", Fonts.small, MUTED).grid(row=4, column=0,
                                                                                                pady=(0, 10))

        right = card(wrap)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)
        self.pe_title = label(right, "Sélectionne un preset", Fonts.h2, anchor="w")
        self.pe_title.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 6))
        meta = ctk.CTkFrame(right, fg_color="transparent")
        meta.grid(row=1, column=0, sticky="ew", padx=18)
        meta.grid_columnconfigure((0, 1), weight=1, uniform="m")
        label(meta, "Nom", Fonts.small, MUTED).grid(row=0, column=0, sticky="w", padx=(0, 6))
        label(meta, "Description", Fonts.small, MUTED).grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.pe_name = entry(meta, "Nom du preset", width=0)
        self.pe_name.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.pe_desc = entry(meta, "Notes (lieu, équipement, VLAN…)", width=0)
        self.pe_desc.grid(row=1, column=1, sticky="ew", padx=(6, 0))
        scroll = ctk.CTkScrollableFrame(right, fg_color="transparent")
        scroll.grid(row=2, column=0, sticky="nsew", padx=(10, 6), pady=(12, 0))
        scroll.grid_columnconfigure(0, weight=1)
        self.pe_form = ConfigForm(scroll)
        self.pe_form.grid(row=0, column=0, sticky="nsew", padx=8)

        bar = ctk.CTkFrame(right, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew", padx=18, pady=(8, 4))
        self.pe_save = button(bar, "Enregistrer", self.save_preset_edit, kind="success", width=120)
        self.pe_save.pack(side="left")
        self.pe_dup = button(bar, "Dupliquer", self.duplicate_preset, width=0)
        self.pe_dup.pack(side="left", padx=(8, 0))
        self.pe_up = button(bar, "↑", lambda: self._move_preset(-1), width=34)
        self.pe_up.pack(side="left", padx=(8, 0))
        self.pe_down = button(bar, "↓", lambda: self._move_preset(1), width=34)
        self.pe_down.pack(side="left", padx=(4, 0))
        self.pe_del = button(bar, "Supprimer", self.delete_preset, kind="danger", width=0)
        self.pe_del.pack(side="right")

        sep = ctk.CTkFrame(right, fg_color=BORDER, height=1)
        sep.grid(row=4, column=0, sticky="ew", padx=18, pady=10)
        ap = ctk.CTkFrame(right, fg_color="transparent")
        ap.grid(row=5, column=0, sticky="ew", padx=18, pady=(0, 16))
        label(ap, "Appliquer à", Fonts.body, MUTED).pack(side="left")
        self.pe_target = option_menu(ap, ["—"], width=260)
        self.pe_target.pack(side="left", padx=(8, 8))
        self.pe_apply = button(ap, "Appliquer", self.apply_preset_edit, kind="primary", width=120, height=36)
        self.pe_apply.pack(side="left")
        button(ap, "Vers l'éditeur", self.preset_to_editor, kind="ghost", width=0).pack(side="right")

        self._presets_changed()

    def _presets_changed(self, select: str | None = None):
        if select:
            self.selected_preset = select
        if self.selected_preset and not self.presets.get(self.selected_preset):
            self.selected_preset = None
        if not self.selected_preset and self.presets.presets:
            self.selected_preset = self.presets.presets[0]["id"]
        self.cfg_loader.configure(values=[LOAD_PRESET] + [p["name"] for p in self.presets.presets])
        self._render_preset_list()
        self._load_preset_editor()

    def _render_preset_list(self):
        for w in self.preset_list.winfo_children():
            w.destroy()
        self._preset_cards = {}
        q = self.preset_search.get().strip().lower()
        shown = [p for p in self.presets.presets
                 if not q or q in (p["name"] + " " + p["description"] + " " + summarize(p["config"])).lower()]
        if not shown:
            label(self.preset_list, "Aucun preset" if not q else "Aucun résultat", Fonts.small, MUTED).grid(
                row=0, column=0, pady=20)
        for i, p in enumerate(shown):
            sel = p["id"] == self.selected_preset
            c = ctk.CTkFrame(self.preset_list, fg_color=ACCENT_SOFT if sel else SURFACE2, corner_radius=10,
                             border_width=2 if sel else 1, border_color=ACCENT if sel else BORDER, cursor="hand2")
            c.grid(row=i, column=0, sticky="ew", pady=3, padx=(0, 6))
            c.grid_columnconfigure(1, weight=1)
            dhcp = p["config"]["mode"] == "dhcp"
            badge = ctk.CTkLabel(c, text="DHCP" if dhcp else "FIXE", width=44, height=18, corner_radius=5,
                                 font=Fonts.small_bold, fg_color=ACCENT_SOFT if dhcp else ORANGE_SOFT,
                                 text_color=ACCENT if dhcp else ORANGE)
            badge.grid(row=0, column=0, rowspan=2, padx=(10, 10), pady=(8, 0), sticky="n")
            n = label(c, p["name"], Fonts.h3, anchor="w", height=18)
            n.grid(row=0, column=1, sticky="ew", pady=(7, 0), padx=(0, 10))
            summ = "Adresse attribuée automatiquement" if summarize(p["config"]) == "DHCP" else summarize(p["config"])
            s = label(c, summ, Fonts.mono_small, MUTED, anchor="w", height=16)
            s.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(1, 0 if p["description"] else 7))
            widgets = [c, badge, n, s]
            if p["description"]:
                d = label(c, p["description"], Fonts.small, MUTED, anchor="w", justify="left", wraplength=250,
                          height=15)
                d.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=(0, 7))
                widgets.append(d)
            for w in widgets:
                w.bind("<Button-1>", lambda e, pid=p["id"]: self._select_preset(pid))
                w.bind("<Double-Button-1>", lambda e, pid=p["id"]: self._apply_preset_quick(pid))
            self._preset_cards[p["id"]] = c

    def _select_preset(self, pid):
        if pid == self.selected_preset:
            return
        self.selected_preset = pid
        for k, c in self._preset_cards.items():
            sel = k == pid
            c.configure(fg_color=ACCENT_SOFT if sel else SURFACE2, border_width=2 if sel else 1,
                        border_color=ACCENT if sel else BORDER)
        self._load_preset_editor()

    def _load_preset_editor(self):
        p = self.presets.get(self.selected_preset) if self.selected_preset else None
        st = "normal" if p else "disabled"
        for b in (self.pe_save, self.pe_dup, self.pe_del, self.pe_up, self.pe_down):
            b.configure(state=st)
        self.pe_title.configure(text=p["name"] if p else "Aucun preset")
        self.pe_name.delete(0, "end")
        self.pe_desc.delete(0, "end")
        if p:
            self.pe_name.insert(0, p["name"])
            self.pe_desc.insert(0, p["description"])
            self.pe_form.set_config(p["config"])
        self._update_preset_target()

    def _update_preset_target(self):
        names = [a.name for a in self.adapters] or ["—"]
        self.pe_target.configure(values=names)
        cur = self.pe_target.get()
        if cur not in names:
            self.pe_target.set(self.selected.name if self.selected else names[0])
        self.pe_apply.configure(state="normal" if self.admin and self.adapters and self.selected_preset
                                else "disabled")

    def new_preset(self):
        p = self.presets.add("Nouveau preset", {"mode": "static", "mask": "255.255.255.0"})
        self._presets_changed(select=p["id"])
        self.pe_name.focus_set()
        self.pe_name.select_range(0, "end")

    def save_preset_edit(self):
        p = self.presets.get(self.selected_preset)
        if not p:
            return
        cfg = self.pe_form.get_config()
        errors, _ = nb.validate_config(cfg)
        if errors:
            info(self, "Preset invalide", "Corrige les erreurs avant d'enregistrer :", "\n".join(errors))
            return
        name = self.pe_name.get().strip() or p["name"]
        if name != p["name"] and self.presets.by_name(name):
            name = self.presets.unique_name(name)
        self.presets.update(p["id"], name=name, description=self.pe_desc.get().strip(), config=cfg)
        self._presets_changed()
        self.toast(f"Preset « {name} » enregistré", "ok")

    def duplicate_preset(self):
        p = self.presets.get(self.selected_preset)
        if p:
            n = self.presets.add(f"{p['name']} (copie)", p["config"], p["description"])
            self._presets_changed(select=n["id"])

    def delete_preset(self):
        p = self.presets.get(self.selected_preset)
        if p and confirm(self, "Supprimer le preset ?", f"« {p['name']} » sera définitivement supprimé.",
                         "Supprimer", kind="danger"):
            self.presets.delete(p["id"])
            self.selected_preset = None
            self._presets_changed()
            self.toast("Preset supprimé", "ok")

    def _move_preset(self, delta):
        if self.selected_preset:
            self.presets.move(self.selected_preset, delta)
            self._presets_changed()

    def apply_preset_edit(self):
        p = self.presets.get(self.selected_preset)
        target = next((a for a in self.adapters if a.name == self.pe_target.get()), None)
        if p and target:
            self.apply(target, self.pe_form.get_config(), f"Preset « {p['name']} »")

    def _apply_preset_quick(self, pid):
        p = self.presets.get(pid)
        a = self.selected
        if p and a:
            self.apply(a, p["config"], f"Preset « {p['name']} »")

    def preset_to_editor(self):
        self.form.set_config(self.pe_form.get_config())
        self.tabs.set("Configuration")
        self.toast("Preset chargé dans l'éditeur", "ok")

    def import_presets(self):
        path = filedialog.askopenfilename(title="Importer des presets", filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            n = self.presets.import_file(path)
            self._presets_changed()
            self.toast(f"{n} preset(s) importé(s)", "ok")
            self.log(f"{n} preset(s) importé(s) depuis {path}")
        except Exception as e:
            info(self, "Import impossible", str(e))

    def export_presets(self):
        path = filedialog.asksaveasfilename(title="Exporter les presets", defaultextension=".json",
                                            initialfile="netshift-presets.json", filetypes=[("JSON", "*.json")])
        if path:
            self.presets.export(path)
            self.toast(f"Presets exportés vers {os.path.basename(path)}", "ok")

    # ========================================================= HISTORY TAB
    def _build_history_tab(self, tab):
        tab.grid_rowconfigure(0, weight=2)
        tab.grid_rowconfigure(1, weight=3)
        h = card(tab)
        h.grid(row=0, column=0, sticky="nsew", pady=(0, 7))
        h.grid_columnconfigure(0, weight=1)
        h.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(h, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
        label(top, "Historique des changements", Fonts.h2).pack(side="left")
        button(top, "Effacer", self._clear_history, kind="ghost", height=28).pack(side="right")
        self.hist_list = ctk.CTkScrollableFrame(h, fg_color="transparent")
        self.hist_list.grid(row=1, column=0, sticky="nsew", padx=(10, 4), pady=(0, 10))
        self.hist_list.grid_columnconfigure(0, weight=1)

        j = card(tab)
        j.grid(row=1, column=0, sticky="nsew", pady=(7, 0))
        j.grid_columnconfigure(0, weight=1)
        j.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(j, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
        label(top, "Journal", Fonts.h2).pack(side="left")
        button(top, "Exporter…", self._export_journal, kind="ghost", height=28).pack(side="right")
        button(top, "Copier", lambda: self.copy(self.journal.text(), quiet=True) or self.toast("Journal copié", "ok"),
               kind="ghost", height=28).pack(side="right")
        button(top, "Vider", lambda: self.journal.clear(), kind="ghost", height=28).pack(side="right")
        self.journal = Console(j, wrap="word")
        self.journal.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 16))

    def _render_history(self):
        for w in self.hist_list.winfo_children():
            w.destroy()
        if not self.history.entries:
            label(self.hist_list, "Aucun changement enregistré pour l'instant.", Fonts.small, MUTED).grid(
                row=0, column=0, pady=16)
            return
        for i, e in enumerate(self.history.entries):
            row = ctk.CTkFrame(self.hist_list, fg_color=SURFACE2, corner_radius=8)
            row.grid(row=i, column=0, sticky="ew", pady=3, padx=(0, 6))
            row.grid_columnconfigure(2, weight=1)
            ok = e.get("ok", True)
            ctk.CTkLabel(row, text="✓" if ok else "✕", width=26, height=26, corner_radius=13,
                         fg_color=GREEN_SOFT if ok else RED_SOFT, text_color=GREEN if ok else RED,
                         font=Fonts.small_bold).grid(row=0, column=0, rowspan=2, padx=10, pady=8)
            label(row, e["time"], Fonts.mono_small, MUTED).grid(row=0, column=1, sticky="w", padx=(0, 12),
                                                                pady=(6, 0))
            label(row, f"{e['adapter']}  ·  {e['label']}", Fonts.h3, anchor="w").grid(row=0, column=2, sticky="w",
                                                                                     pady=(6, 0))
            label(row, f"{summarize(e['before'])}   →   {summarize(e['after'])}", Fonts.mono_small, MUTED,
                  anchor="w").grid(row=1, column=1, columnspan=2, sticky="w", pady=(0, 6))
            target = next((a for a in self.adapters if a.description == e["adapter_desc"]), None)
            st = "normal" if target and self.admin else "disabled"
            button(row, "Restaurer l'avant", lambda e=e, t=target: self.apply(t, e["before"], f"Restauration "
                                                                                              f"({e['time']})"),
                   height=28, font=Fonts.small, state=st).grid(row=0, column=3, rowspan=2, padx=(6, 4))
            button(row, "Réappliquer", lambda e=e, t=target: self.apply(t, e["after"], f"Réapplication "
                                                                                      f"({e['time']})"),
                   height=28, font=Fonts.small, state=st).grid(row=0, column=4, rowspan=2, padx=(0, 10))

    def _clear_history(self):
        if confirm(self, "Effacer l'historique ?", "La possibilité d'annuler les changements passés sera perdue.",
                   "Effacer", kind="danger"):
            self.history.clear()
            self._render_history()
            self._render_header()

    def _export_journal(self):
        path = filedialog.asksaveasfilename(title="Exporter le journal", defaultextension=".txt",
                                            initialfile=f"netshift-journal-{time.strftime('%Y%m%d-%H%M')}.txt")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.journal.text())
            self.toast("Journal exporté", "ok")

    # ============================================================ STATUSBAR
    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, fg_color="transparent", height=34)
        bar.grid(row=1, column=1, sticky="ew", padx=20, pady=(6, 8))
        bar.grid_columnconfigure(0, weight=1)
        self.status = label(bar, "Prêt", Fonts.small, MUTED, anchor="w")
        self.status.grid(row=0, column=0, sticky="ew")
        self.progress = ctk.CTkProgressBar(bar, mode="indeterminate", width=140, height=6, progress_color=ACCENT)
        self.progress.grid(row=0, column=1, padx=(10, 10))
        self.progress.grid_remove()
        if self.admin:
            pill(bar, "Administrateur", GREEN_SOFT, GREEN).grid(row=0, column=2)
        else:
            pill(bar, "Lecture seule", ORANGE_SOFT, ORANGE).grid(row=0, column=2)

    # ============================================================ ADAPTERS
    def refresh_adapters(self, quiet: bool = False, first: bool = False):
        if self._refreshing:
            return
        self._refreshing = True
        if not quiet:
            self.refresh_btn.configure(state="disabled")

        def done(adapters):
            self._refreshing = False
            self.refresh_btn.configure(state="normal")
            self._on_adapters(adapters, quiet)
            if first:
                self.after(5000, self._auto_loop)

        def error(e):
            self._refreshing = False
            self.refresh_btn.configure(state="normal")
            self.toast(f"Lecture des cartes impossible : {e}", "err")
            self.log(f"Lecture des cartes impossible : {e}", "err")
            if first:
                self.after(5000, self._auto_loop)

        self.bg(nb.list_adapters, done, busy=None if quiet else "Lecture des cartes réseau…", error=error)

    def _auto_loop(self):
        if self.auto_refresh.get() and not self._applying and self.state() != "iconic":
            self.refresh_adapters(quiet=True)
        self.after(5000, self._auto_loop)

    def _on_adapters(self, adapters: list[nb.Adapter], quiet: bool):
        old = {a.guid: a for a in self.adapters}
        changed = [a.guid for a in adapters] != list(old.keys()) or any(old.get(a.guid) != a for a in adapters)
        if self.adapters and quiet:
            for a in adapters:
                o = old.get(a.guid)
                if o and o.status != a.status:
                    self.log(f"{a.name} : {o.status} → {a.status}", "warn" if not a.up else "ok")
                    self.toast(f"{a.name} : {'connectée' if a.up else a.status.lower()}", "info")
                elif o and o.primary_ip != a.primary_ip:
                    p = a.primary_ip
                    self.log(f"{a.name} : nouvelle adresse {p.ip + '/' + str(p.prefix) if p else 'aucune'}")
                elif not o:
                    self.log(f"Nouvelle carte détectée : {a.name} ({a.description})", "accent")
        self.adapters = adapters
        if self.selected_guid not in {a.guid for a in adapters}:
            up = [a for a in adapters if a.up and not a.virtual]
            self.selected_guid = (up or adapters or [None])[0].guid if adapters else None
        if changed or not quiet:
            self._render_cards()
            self._render_header()
            self._render_current()
            self._update_apply_btn()
            self._update_preset_target()
        if not quiet:
            self.toast(f"{len(adapters)} carte(s) réseau détectée(s)", "ok")
            if not self.form.ip.get() and self.selected:
                self.form.set_config(self.selected.to_config())

    def select_adapter(self, guid: str):
        self.selected_guid = guid
        self.settings.set("last_adapter", guid)
        for g, c in self.cards.items():
            c.set_selected(g == guid)
        self._render_header()
        self._render_current()
        self._update_apply_btn()
        a = self.selected
        if a and a.name in (self.pe_target.cget("values") or []):
            self.pe_target.set(a.name)

    # ================================================================ MISC
    def relaunch_admin(self):
        if relaunch_as_admin():
            self._on_close()

    def create_shortcut(self):
        desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
                desktop = winreg.QueryValueEx(k, "Desktop")[0]
        except OSError:
            pass
        lnk = os.path.join(desktop, f"{APP_NAME}.lnk")
        if getattr(sys, "frozen", False):
            target, args = sys.executable, ""
        else:
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            target = pyw if os.path.exists(pyw) else sys.executable
            args = f'"{app_dir() / "NetShift.pyw"}"'
        ico = Path(sys.executable) if getattr(sys, "frozen", False) else app_dir() / "assets" / "netshift.ico"
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
              f"$s.TargetPath='{target}';$s.Arguments='{args}';$s.WorkingDirectory='{app_dir()}';"
              + (f"$s.IconLocation='{ico}';" if ico.exists() else "") + "$s.Save()")

        def done(res):
            code, out = res
            if code == 0:
                self.toast("Raccourci créé sur le bureau", "ok")
            else:
                self.toast("Impossible de créer le raccourci", "err")
                self.log(out, "err")

        self.bg(lambda: nb.run_ps(ps), done)

    def _on_close(self):
        try:
            if self.state() == "normal":
                self.settings.set("geometry", self.geometry())
        except tk.TclError:
            pass
        self.tools.capture.shutdown()
        nb._ps.close()
        self.destroy()


def relaunch_as_admin() -> bool:
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, ""
    else:
        exe = sys.executable
        params = f'"{app_dir() / "NetShift.pyw"}"'
    params += " --elevated"
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, str(app_dir()), 1)
    return r > 32


def main():
    if sys.platform != "win32":
        print("NetShift fonctionne uniquement sous Windows.")
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    # Élévation automatique au lancement (une seule tentative, sinon mode lecture seule)
    if not nb.is_admin() and "--elevated" not in sys.argv and "--no-elevate" not in sys.argv:
        if relaunch_as_admin():
            return
    threading.Thread(target=nb.warmup_ps, daemon=True).start()
    App().mainloop()
