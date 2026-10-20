"""Thème, polices et widgets réutilisables."""
from __future__ import annotations

import ipaddress
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import customtkinter as ctk

from . import netbackend as nb
from .i18n import _
from .store import EMPTY_CONFIG, PUBLIC_DNS, normalize_config

# --------------------------------------------------------------------------- #
#  Palette (clair, sombre)
# --------------------------------------------------------------------------- #
BG = ("#F3F5F9", "#0E1116")
SIDEBAR = ("#E8EBF1", "#12161D")
SURFACE = ("#FFFFFF", "#171B23")
SURFACE2 = ("#F1F3F7", "#1F242E")
HOVER = ("#E6E9F0", "#262C38")
BORDER = ("#DDE1E8", "#2A303C")
TEXT = ("#111827", "#E6E9EF")
MUTED = ("#6B7280", "#8A93A4")
ACCENT = ("#2563EB", "#3B82F6")
ACCENT_HOVER = ("#1D4ED8", "#2563EB")
ACCENT_SOFT = ("#DBE7FE", "#1B2A47")
GREEN = ("#15803D", "#22C55E")
GREEN_SOFT = ("#DCFCE7", "#14301F")
RED = ("#DC2626", "#F87171")
RED_SOFT = ("#FEE2E2", "#3A1A1C")
ORANGE = ("#B45309", "#FBBF24")
ORANGE_SOFT = ("#FEF3C7", "#3A2E12")
GREY_SOFT = ("#E5E7EB", "#2A303C")

FONT_FAMILY = "Segoe UI"
MONO_FAMILY = "Cascadia Mono"


class Fonts:
    """Initialisé après la création de la fenêtre racine."""

    @classmethod
    def init(cls):
        families = set(tkfont.families())
        mono = MONO_FAMILY if MONO_FAMILY in families else "Consolas"
        cls.title = ctk.CTkFont(FONT_FAMILY, 22, "bold")
        cls.h1 = ctk.CTkFont(FONT_FAMILY, 20, "bold")
        cls.h2 = ctk.CTkFont(FONT_FAMILY, 15, "bold")
        cls.h3 = ctk.CTkFont(FONT_FAMILY, 13, "bold")
        cls.body = ctk.CTkFont(FONT_FAMILY, 13)
        cls.small = ctk.CTkFont(FONT_FAMILY, 11)
        cls.small_bold = ctk.CTkFont(FONT_FAMILY, 11, "bold")
        cls.mono = ctk.CTkFont(mono, 12)
        cls.mono_small = ctk.CTkFont(mono, 11)
        cls.mono_tk = (mono, 10)


def mode_color(c):
    """Couleur effective (clair/sombre) d'un tuple."""
    if isinstance(c, (tuple, list)):
        return c[1] if ctk.get_appearance_mode() == "Dark" else c[0]
    return c


# --------------------------------------------------------------------------- #
#  Briques
# --------------------------------------------------------------------------- #
def card(master, **kw) -> ctk.CTkFrame:
    opts = dict(fg_color=SURFACE, corner_radius=12, border_width=1, border_color=BORDER)
    opts.update(kw)
    return ctk.CTkFrame(master, **opts)


def label(master, text="", font=None, color=TEXT, **kw) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=text, font=font or Fonts.body, text_color=color, **kw)


BUTTON_STYLES = {
    "primary": dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=("#FFFFFF", "#FFFFFF")),
    "secondary": dict(fg_color=SURFACE2, hover_color=HOVER, text_color=TEXT, border_width=1, border_color=BORDER),
    "ghost": dict(fg_color="transparent", hover_color=HOVER, text_color=TEXT),
    "danger": dict(fg_color=RED_SOFT, hover_color=("#FECACA", "#4A1F22"), text_color=RED),
    "success": dict(fg_color=GREEN, hover_color=("#166534", "#16A34A"), text_color=("#FFFFFF", "#0B1F12")),
}
# Désactivé : fond neutre + texte atténué (un texte gris sur fond vert/bleu/rouge est illisible)
DISABLED_LOOK = dict(fg_color=SURFACE2, border_width=1, border_color=BORDER)
DISABLED_TEXT = ("#9CA3AF", "#6B7280")


class StyledButton(ctk.CTkButton):
    """Bouton coloré qui prend un aspect neutre et lisible quand il est désactivé."""

    def __init__(self, *args, kind: str = "secondary", **kw):
        self._kind_look = {k: kw.get(k, BUTTON_STYLES[kind].get(k)) for k in ("fg_color", "border_width", "border_color")}
        self._colored = kind in ("primary", "danger", "success")
        super().__init__(*args, text_color_disabled=DISABLED_TEXT, **kw)
        if kw.get("state") == "disabled":
            self._apply_look("disabled")

    def _apply_look(self, state):
        if not self._colored:
            return
        look = DISABLED_LOOK if state == "disabled" else {k: v for k, v in self._kind_look.items() if v is not None}
        super().configure(**look)

    def configure(self, require_redraw=False, **kwargs):
        super().configure(require_redraw=require_redraw, **kwargs)
        if "state" in kwargs:
            self._apply_look(kwargs["state"])


def button(master, text, command=None, kind="secondary", width=0, **kw) -> ctk.CTkButton:
    opts = dict(corner_radius=8, height=32, font=Fonts.body, width=width or 0)
    opts.update(BUTTON_STYLES[kind])
    opts.update(kw)
    return StyledButton(master, text=text, command=command, kind=kind, **opts)


def entry(master, placeholder="", width=200, **kw) -> ctk.CTkEntry:
    opts = dict(height=34, corner_radius=8, fg_color=SURFACE2, border_color=BORDER, border_width=1,
                text_color=TEXT, placeholder_text_color=MUTED, font=Fonts.body)
    opts.update(kw)
    return ctk.CTkEntry(master, placeholder_text=placeholder, width=width, **opts)


def pill(master, text, fg=GREY_SOFT, color=TEXT) -> ctk.CTkLabel:
    return ctk.CTkLabel(master, text=f"  {text}  ", font=Fonts.small_bold, fg_color=fg, text_color=color,
                        corner_radius=10, height=22)


def option_menu(master, values, command=None, width=200, **kw) -> ctk.CTkOptionMenu:
    opts = dict(fg_color=SURFACE2, button_color=SURFACE2, button_hover_color=HOVER, text_color=TEXT,
                dropdown_fg_color=SURFACE, dropdown_hover_color=HOVER, dropdown_text_color=TEXT,
                font=Fonts.body, dropdown_font=Fonts.body, corner_radius=8, height=34, dynamic_resizing=False)
    opts.update(kw)
    return ctk.CTkOptionMenu(master, values=values or ["—"], command=command, width=width, **opts)


def segmented(master, values, command=None, **kw) -> ctk.CTkSegmentedButton:
    opts = dict(font=Fonts.body, height=32, corner_radius=8, fg_color=SURFACE2, unselected_color=SURFACE2,
                unselected_hover_color=HOVER, selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                text_color=TEXT)
    opts.update(kw)
    return ctk.CTkSegmentedButton(master, values=values, command=command, **opts)


class TabHost(ctk.CTkFrame):
    """Onglets : barre segmentée + pages (remplace CTkTabview, plus aéré)."""

    def __init__(self, master, names, command=None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.command = command
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.nav = segmented(self, names, command=self.set, height=38, font=Fonts.h3)
        self.nav.grid(row=0, column=0, sticky="w", pady=(0, 10))
        self._pages: dict[str, ctk.CTkFrame] = {}
        for n in names:
            f = ctk.CTkFrame(self, fg_color="transparent")
            f.grid_columnconfigure(0, weight=1)
            f.grid_rowconfigure(0, weight=1)
            self._pages[n] = f
        self._current = None
        self.set(names[0])

    def tab(self, name) -> ctk.CTkFrame:
        return self._pages[name]

    def get(self) -> str:
        return self._current

    def set(self, name):
        if name == self._current:
            return
        for n, f in self._pages.items():
            if n == name:
                f.grid(row=1, column=0, sticky="nsew")
            else:
                f.grid_remove()
        self._current = name
        self.nav.set(name)
        if self.command:
            self.command()


class Console(ctk.CTkTextbox):
    """Zone de sortie monospace, avec couleurs pour succès / erreurs."""

    def __init__(self, master, **kw):
        opts = dict(font=Fonts.mono, fg_color=SURFACE2, border_width=1, border_color=BORDER, corner_radius=10,
                    text_color=TEXT, wrap="none", activate_scrollbars=True)
        opts.update(kw)
        super().__init__(master, **opts)
        self._refresh_tags()
        self.configure(state="disabled")

    def _refresh_tags(self):
        self.tag_config("ok", foreground=mode_color(GREEN))
        self.tag_config("err", foreground=mode_color(RED))
        self.tag_config("warn", foreground=mode_color(ORANGE))
        self.tag_config("muted", foreground=mode_color(MUTED))
        self.tag_config("accent", foreground=mode_color(ACCENT))

    def write(self, text: str, tag: str | None = None, newline: bool = True):
        self._refresh_tags()
        self.configure(state="normal")
        self.insert("end", text + ("\n" if newline else ""), tag)
        self.see("end")
        self.configure(state="disabled")

    def clear(self):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")

    def text(self) -> str:
        return self.get("1.0", "end").rstrip()


def ui_scale(widget) -> float:
    try:
        return ctk.ScalingTracker.get_widget_scaling(widget)
    except Exception:
        return 1.0


def style_treeview(root: tk.Misc):
    k = ui_scale(root)
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    bg, fg, head, sel, border = (mode_color(SURFACE2), mode_color(TEXT), mode_color(SURFACE),
                                 mode_color(ACCENT), mode_color(BORDER))
    s.configure("IPM.Treeview", background=bg, fieldbackground=bg, foreground=fg, rowheight=int(30 * k),
                borderwidth=0, font=(FONT_FAMILY, 10))
    s.configure("IPM.Treeview.Heading", background=head, foreground=mode_color(MUTED), relief="flat",
                font=(FONT_FAMILY, 10, "bold"), borderwidth=0, padding=(int(8 * k), int(6 * k)))
    s.map("IPM.Treeview.Heading", background=[("active", mode_color(HOVER))])
    s.map("IPM.Treeview", background=[("selected", sel)], foreground=[("selected", "#FFFFFF")])
    s.layout("IPM.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("IPM.Vertical.TScrollbar", background=head, troughcolor=bg, bordercolor=border,
                arrowcolor=mode_color(MUTED), lightcolor=head, darkcolor=head)


# --------------------------------------------------------------------------- #
#  Dialogues modaux
# --------------------------------------------------------------------------- #
class Dialog(ctk.CTkToplevel):
    def __init__(self, master, title: str, message: str = "", ok_text="OK", cancel_text=_("Annuler"),
                 kind="primary", input_value: str | None = None, input_label: str = "", detail: str = ""):
        super().__init__(master)
        self.result = None
        self.title(title)
        self.configure(fg_color=SURFACE)
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(20, 16))
        label(body, title, Fonts.h2).pack(anchor="w")
        if message:
            label(body, message, Fonts.body, MUTED, justify="left", wraplength=440).pack(anchor="w", pady=(6, 0))
        if detail:
            box = ctk.CTkFrame(body, fg_color=SURFACE2, corner_radius=8)
            box.pack(fill="x", pady=(12, 0))
            label(box, detail, Fonts.mono_small, TEXT, justify="left", wraplength=440).pack(anchor="w", padx=12,
                                                                                           pady=10)
        self._entry = None
        if input_value is not None:
            if input_label:
                label(body, input_label, Fonts.small, MUTED).pack(anchor="w", pady=(12, 2))
            self._entry = entry(body, width=420)
            self._entry.insert(0, input_value)
            self._entry.pack(fill="x")
            self._entry.bind("<Return>", lambda e: self._ok())

        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=(20, 0))
        button(row, ok_text, self._ok, kind=kind, width=110).pack(side="right")
        if cancel_text:
            button(row, cancel_text, self.destroy, kind="ghost", width=90).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        # positions en pixels physiques : on contourne le redimensionnement DPI de CTk
        mw = master.winfo_toplevel()
        x = mw.winfo_rootx() + (mw.winfo_width() - self.winfo_reqwidth()) // 2
        y = mw.winfo_rooty() + (mw.winfo_height() - self.winfo_reqheight()) // 3
        tk.Toplevel.wm_geometry(self, f"+{max(0, x)}+{max(0, y)}")
        self.after(60, self._focus)
        ico = getattr(mw, "icon_path", None)
        if ico:
            self.after(250, lambda: self.iconbitmap(ico))  # CTkToplevel impose son icône après 200 ms

    def _focus(self):
        self.lift()
        self.focus_force()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        if self._entry:
            self._entry.focus_set()
            self._entry.select_range(0, "end")

    def _ok(self):
        self.result = self._entry.get() if self._entry else True
        self.destroy()

    def show(self):
        self.wait_window()
        return self.result


def confirm(master, title, message, ok_text=_("Confirmer"), kind="primary", detail="") -> bool:
    return bool(Dialog(master, title, message, ok_text=ok_text, kind=kind, detail=detail).show())


def info(master, title, message, detail=""):
    Dialog(master, title, message, ok_text="OK", cancel_text="", detail=detail).show()


def ask_string(master, title, message, value="", ok_text="OK", input_label="") -> str | None:
    return Dialog(master, title, message, ok_text=ok_text, input_value=value, input_label=input_label).show()


# --------------------------------------------------------------------------- #
#  Formulaire de configuration IP
# --------------------------------------------------------------------------- #
V6_LABELS = {"unchanged": _("Inchangé"), "auto": _("Automatique"), "static": _("Statique"), "disabled": _("Désactivé")}
_V6_KEYS = {v: k for k, v in V6_LABELS.items()}


class ConfigForm(ctk.CTkFrame):
    def __init__(self, master, on_change=None, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.on_change = on_change
        self.grid_columnconfigure((0, 1), weight=1, uniform="cols")

        self.mode = segmented(self, ["DHCP", _("Statique")], command=lambda v: self._update_state())
        self.mode.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self.ip = self._field(_("Adresse IP"), 1, 0, "192.168.1.50")
        self.mask = self._field(_("Masque  (255.255.255.0 ou /24)"), 1, 1, "255.255.255.0")
        self.mask_hint = label(self, "", Fonts.small, MUTED, anchor="w")
        self.mask_hint.grid(row=3, column=1, sticky="w", padx=(6, 0))

        gw_label = label(self, _("Passerelle"), Fonts.small, MUTED, anchor="w")
        gw_label.grid(row=4, column=0, sticky="w", padx=(0, 6), pady=(8, 2))
        gw_row = ctk.CTkFrame(self, fg_color="transparent")
        gw_row.grid(row=5, column=0, sticky="ew", padx=(0, 6))
        gw_row.grid_columnconfigure(0, weight=1)
        self.gateway = entry(gw_row, "optionnelle")
        self.gateway.grid(row=0, column=0, sticky="ew")
        self.gw_auto = button(gw_row, ".1", self._auto_gateway, kind="secondary", width=40, height=34)
        self.gw_auto.grid(row=0, column=1, padx=(6, 0))
        self._watch(self.gateway)

        # DNS
        dns_head = ctk.CTkFrame(self, fg_color="transparent")
        dns_head.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(16, 2))
        label(dns_head, _("Serveurs DNS"), Fonts.h3).pack(side="left")
        self.dns_auto = ctk.CTkSwitch(dns_head, text=_("Automatiques (DHCP)"), font=Fonts.small, text_color=MUTED,
                                      progress_color=ACCENT, command=self._update_state)
        self.dns_auto.pack(side="left", padx=(14, 0))
        self.dns_preset = option_menu(dns_head, [_("DNS publics…"), *PUBLIC_DNS.keys()], self._pick_dns, width=140,
                                      height=28)
        self.dns_preset.pack(side="right")

        self.dns1 = self._field(_("DNS primaire"), 7, 0, _("ex. 1.1.1.1"))
        self.dns2 = self._field(_("DNS secondaire"), 7, 1, "optionnel")

        label(self, _("IP supplémentaires (une par ligne, ex. 10.0.0.5/24)"), Fonts.small, MUTED, anchor="w").grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(10, 2))
        self.extra = ctk.CTkTextbox(self, height=58, font=Fonts.mono, fg_color=SURFACE2, border_color=BORDER,
                                    border_width=1, corner_radius=8, text_color=TEXT)
        self.extra.grid(row=10, column=0, columnspan=2, sticky="ew")
        self.extra.bind("<KeyRelease>", lambda e: self._changed())

        # --- IPv6
        v6_head = ctk.CTkFrame(self, fg_color="transparent")
        v6_head.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(16, 2))
        label(v6_head, "IPv6", Fonts.h3).pack(side="left")
        self.v6_mode = segmented(v6_head, list(V6_LABELS.values()), command=lambda v: self._update_state(),
                                 height=28, font=Fonts.small)
        self.v6_mode.pack(side="left", padx=(14, 0))
        self.v6_box = ctk.CTkFrame(self, fg_color="transparent")
        self.v6_box.grid_columnconfigure((0, 1), weight=1, uniform="v6")

        def v6field(text, row, col, placeholder):
            label(self.v6_box, text, Fonts.small, MUTED, anchor="w").grid(
                row=row, column=col, sticky="w", padx=(0, 6) if col == 0 else (6, 0), pady=(6, 2))
            e = entry(self.v6_box, placeholder)
            e.grid(row=row + 1, column=col, sticky="ew", padx=(0, 6) if col == 0 else (6, 0))
            self._watch(e)
            return e

        self.v6_ip = v6field(_("Adresse IPv6"), 0, 0, _("ex. 2001:db8:10::25"))
        self.v6_prefix = v6field(_("Longueur de préfixe"), 0, 1, "64")
        self.v6_gw = v6field(_("Passerelle IPv6 (souvent fe80::1)"), 2, 0, "optionnelle")
        self.v6_dns1 = v6field(_("DNS IPv6 primaire (vide = automatiques)"), 4, 0, _("ex. 2606:4700:4700::1111"))
        self.v6_dns2 = v6field(_("DNS IPv6 secondaire"), 4, 1, "optionnel")
        self.v6_hint = label(self.v6_box, "", Fonts.small, MUTED, anchor="w", justify="left", wraplength=560)
        self.v6_hint.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.adv = ctk.CTkSwitch(self, text=_("Options avancées : métrique d'interface et suffixe DNS"),
                                 font=Fonts.small, text_color=MUTED, progress_color=ACCENT,
                                 command=self._update_state)
        self.adv.grid(row=13, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.adv_box = ctk.CTkFrame(self, fg_color="transparent")
        self.adv_box.grid_columnconfigure((0, 1), weight=1, uniform="adv")
        label(self.adv_box, _("Métrique (auto ou 1–9999, plus petit = prioritaire)"), Fonts.small, MUTED,
              anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=(6, 2))
        label(self.adv_box, _("Suffixe DNS de la connexion"), Fonts.small, MUTED, anchor="w").grid(
            row=0, column=1, sticky="w", padx=(6, 0), pady=(6, 2))
        self.metric = entry(self.adv_box, "auto")
        self.metric.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.dns_suffix = entry(self.adv_box, _("ex. corp.example (vide = aucun)"))
        self.dns_suffix.grid(row=1, column=1, sticky="ew", padx=(6, 0))
        for e in (self.metric, self.dns_suffix):
            self._watch(e)

        self.feedback = label(self, "", Fonts.small, MUTED, anchor="w", justify="left", wraplength=560)
        self.feedback.grid(row=15, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.set_config(EMPTY_CONFIG)

    def _field(self, text, row, col, placeholder):
        label(self, text, Fonts.small, MUTED, anchor="w").grid(row=row, column=col, sticky="w",
                                                                padx=(0, 6) if col == 0 else (6, 0), pady=(8, 2))
        e = entry(self, placeholder)
        e.grid(row=row + 1, column=col, sticky="ew", padx=(0, 6) if col == 0 else (6, 0))
        self._watch(e)
        return e

    def _watch(self, e):
        e.bind("<KeyRelease>", lambda ev: self._changed())
        e.bind("<FocusOut>", lambda ev: self._changed())

    @staticmethod
    def _set(e: ctk.CTkEntry, value: str):
        state = e.cget("state")
        e.configure(state="normal")
        e.delete(0, "end")
        if value:
            e.insert(0, value)
        e.configure(state=state)

    def _auto_gateway(self):
        try:
            net = ipaddress.IPv4Network(f"{self.ip.get().strip()}/{nb.parse_mask(self.mask.get() or '24')}",
                                        strict=False)
            self._set(self.gateway, str(net.network_address + 1))
            self._changed()
        except ValueError:
            pass

    def _pick_dns(self, name):
        if name in PUBLIC_DNS:
            if self.mode.get() == "DHCP":
                self.dns_auto.deselect()
            self._update_state()
            self._set(self.dns1, PUBLIC_DNS[name][0])
            self._set(self.dns2, PUBLIC_DNS[name][1])
        self.dns_preset.set(_("DNS publics…"))
        self._changed()

    def _update_state(self):
        static = self.mode.get() == _("Statique")
        st = "normal" if static else "disabled"
        for w in (self.ip, self.mask, self.gateway):
            w.configure(state=st, text_color=TEXT if static else MUTED)
        self.gw_auto.configure(state=st)
        self.extra.configure(state=st, text_color=TEXT if static else MUTED)
        if static:
            self.dns_auto.deselect()
            self.dns_auto.configure(state="disabled")
        else:
            self.dns_auto.configure(state="normal")
        dns_st = "disabled" if (not static and self.dns_auto.get()) else "normal"
        for w in (self.dns1, self.dns2):
            w.configure(state=dns_st, text_color=TEXT if dns_st == "normal" else MUTED)
        if self.adv.get():
            self.adv_box.grid(row=14, column=0, columnspan=2, sticky="ew")
        else:
            self.adv_box.grid_remove()
        v6 = _V6_KEYS[self.v6_mode.get()]
        if v6 in ("auto", "static"):
            self.v6_box.grid(row=12, column=0, columnspan=2, sticky="ew")
            st6 = "normal" if v6 == "static" else "disabled"
            for w in (self.v6_ip, self.v6_prefix, self.v6_gw):
                w.configure(state=st6, text_color=TEXT if st6 == "normal" else MUTED)
            self.v6_hint.configure(text=(
                _("Adresses obtenues automatiquement (annonces du routeur / DHCPv6). Les DNS IPv6 restent "
                "automatiques si les champs DNS sont vides.") if v6 == "auto" else
                _("La découverte de routeur est désactivée : seule l'adresse ci-dessus est utilisée "
                "(l'adresse de lien local fe80:: est conservée).")))
        else:
            self.v6_box.grid_remove()
        self._changed()

    def set_config(self, cfg: dict):
        cfg = normalize_config(cfg)
        for w in (self.ip, self.mask, self.gateway, self.dns1, self.dns2):
            w.configure(state="normal")
        self.extra.configure(state="normal")
        self._set(self.ip, cfg["ip"])
        self._set(self.mask, cfg["mask"] or ("255.255.255.0" if cfg["mode"] == "static" else ""))
        self._set(self.gateway, cfg["gateway"])
        self._set(self.dns1, cfg["dns1"])
        self._set(self.dns2, cfg["dns2"])
        self.extra.delete("1.0", "end")
        self.extra.insert("1.0", "\n".join(cfg["extra_ips"]))
        self.mode.set("DHCP" if cfg["mode"] == "dhcp" else _("Statique"))
        self.adv.select() if cfg.get("adv") else self.adv.deselect()
        v6 = cfg["v6"]
        self.v6_mode.set(V6_LABELS.get(v6["mode"], V6_LABELS["unchanged"]))
        for e in (self.v6_ip, self.v6_prefix, self.v6_gw):
            e.configure(state="normal")
        self._set(self.v6_ip, v6["ip"])
        self._set(self.v6_prefix, v6["prefix"] if v6["mode"] == "static" else "64")
        self._set(self.v6_gw, v6["gateway"])
        self._set(self.v6_dns1, v6["dns1"])
        self._set(self.v6_dns2, v6["dns2"])
        self._set(self.metric, "" if str(cfg.get("metric", "auto")) == "auto" else str(cfg.get("metric")))
        self._set(self.dns_suffix, cfg.get("dns_suffix", ""))
        if cfg["mode"] == "dhcp" and cfg["dns_mode"] != "static":
            self.dns_auto.select()
        else:
            self.dns_auto.deselect()
        self._update_state()

    def get_config(self) -> dict:
        static = self.mode.get() == _("Statique")
        dns_static = static or not self.dns_auto.get()
        return {
            "mode": "static" if static else "dhcp",
            "ip": self.ip.get().strip() if static else "",
            "mask": self.mask.get().strip() if static else "",
            "gateway": self.gateway.get().strip() if static else "",
            "dns_mode": "static" if dns_static else "auto",
            "dns1": self.dns1.get().strip() if dns_static else "",
            "dns2": self.dns2.get().strip() if dns_static else "",
            "extra_ips": [ln.strip() for ln in self.extra.get("1.0", "end").splitlines() if ln.strip()] if static else [],
            "v6": self._get_v6(),
            "adv": bool(self.adv.get()),
            "metric": self.metric.get().strip() or "auto",
            "dns_suffix": self.dns_suffix.get().strip(),
        }

    def _get_v6(self) -> dict:
        mode = _V6_KEYS[self.v6_mode.get()]
        static = mode == "static"
        return {
            "mode": mode,
            "ip": self.v6_ip.get().strip() if static else "",
            "prefix": (self.v6_prefix.get().strip().lstrip("/") or "64") if static else "64",
            "gateway": self.v6_gw.get().strip() if static else "",
            "dns1": self.v6_dns1.get().strip() if mode in ("auto", "static") else "",
            "dns2": self.v6_dns2.get().strip() if mode in ("auto", "static") else "",
        }

    def validate(self) -> tuple[list[str], list[str]]:
        cfg = self.get_config()
        errors, warns = nb.validate_config(cfg)
        # Bordures rouges sur les champs fautifs
        def mark(e, ok):
            e.configure(border_color=BORDER if ok else RED)
        if cfg["mode"] == "static":
            mark(self.ip, not cfg["ip"] or _valid_ip(cfg["ip"]))
            try:
                if cfg["mask"]:
                    nb.parse_mask(cfg["mask"])
                mark(self.mask, True)
            except ValueError:
                mark(self.mask, False)
            mark(self.gateway, not cfg["gateway"] or _valid_ip(cfg["gateway"]))
        else:
            for e in (self.ip, self.mask, self.gateway):
                mark(e, True)
        mark(self.dns1, not cfg["dns1"] or _valid_ip(cfg["dns1"]))
        mark(self.dns2, not cfg["dns2"] or _valid_ip(cfg["dns2"]))
        return errors, warns

    def _changed(self):
        cfg = self.get_config()
        hint = ""
        if cfg["mode"] == "static":
            try:
                p = nb.parse_mask(cfg["mask"])
                hosts = 2 ** (32 - p) - 2 if p < 31 else 2 ** (32 - p)
                hint = _("/{0} = {1} · {2:,} hôtes", p, nb.prefix_to_mask(p), hosts).replace(",", " ")
                if _valid_ip(cfg["ip"]):
                    net = ipaddress.IPv4Network(f"{cfg['ip']}/{p}", strict=False)
                    hint += _(" · réseau {0}", net.network_address)
            except ValueError:
                hint = ""
        self.mask_hint.configure(text=hint)
        errors, warns = self.validate()
        has_input = cfg["mode"] == "dhcp" or cfg["ip"]
        if errors and has_input:
            self.feedback.configure(text="✕  " + "\n✕  ".join(errors), text_color=RED)
        elif warns:
            self.feedback.configure(text="⚠  " + "\n⚠  ".join(warns), text_color=ORANGE)
        elif has_input:
            self.feedback.configure(text=_("✓  Configuration valide"), text_color=GREEN)
        else:
            self.feedback.configure(text="")
        if self.on_change:
            self.on_change()


def _valid_ip(v: str) -> bool:
    try:
        ipaddress.IPv4Address(v.strip())
        return True
    except ValueError:
        return False
