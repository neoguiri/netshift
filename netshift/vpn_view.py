"""Onglet VPN : liste des connexions VPN Windows, éditeur, connexion / déconnexion."""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from . import vpn
from .i18n import _
from .ui import (
    ACCENT,
    ACCENT_SOFT,
    BORDER,
    GREEN,
    GREEN_SOFT,
    GREY_SOFT,
    MUTED,
    ORANGE,
    RED,
    SURFACE,
    SURFACE2,
    TEXT,
    Fonts,
    button,
    card,
    confirm,
    entry,
    info,
    label,
    option_menu,
    pill,
)

NEW = "__new__"


def _label_of(mapping: dict, key: str) -> str:
    return mapping.get(key, key)


def _key_of(mapping: dict, text: str) -> str:
    return next((k for k, v in mapping.items() if v == text), text)


class VpnView(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.vpns: list[vpn.Vpn] = []
        self.selected: str | None = None      # clé Vpn.key, ou NEW
        self._cards: dict[str, ctk.CTkFrame] = {}
        self._busy = False
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_list()
        self._build_editor()
        self._load_editor(None)
        self.after(5000, self._auto_refresh)

    # ------------------------------------------------------------------ liste
    def _build_list(self):
        left = card(self, width=360)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.grid_propagate(False)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(left, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 6))
        label(top, _("Connexions VPN"), Fonts.h2).pack(side="left")
        button(top, _("+ Nouvelle"), self.new_vpn, kind="primary", width=0, height=30).pack(side="right")
        button(top, "⟳", self.refresh, kind="ghost", width=30, height=30,
               font=ctk.CTkFont("Segoe UI", 15)).pack(side="right", padx=(0, 4))
        self.list_frame = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=(8, 4))
        self.list_frame.grid_columnconfigure(0, weight=1)
        label(left, _("Les clients tiers (WireGuard, OpenVPN, AnyConnect…) apparaissent\n"
                    "dans la liste des cartes avec le type « VPN »."), Fonts.small, MUTED,
              justify="left").grid(row=2, column=0, sticky="w", padx=16, pady=(6, 12))

    def _render_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._cards = {}
        if not self.vpns:
            label(self.list_frame, _("Aucune connexion VPN Windows.\nCrée-en une avec « + Nouvelle »."),
                  Fonts.small, MUTED, justify="center").grid(row=0, column=0, pady=24)
            return
        for i, v in enumerate(self.vpns):
            sel = v.key == self.selected
            c = ctk.CTkFrame(self.list_frame, fg_color=ACCENT_SOFT if sel else SURFACE2, corner_radius=10,
                             border_width=2 if sel else 1, border_color=ACCENT if sel else BORDER, cursor="hand2")
            c.grid(row=i, column=0, sticky="ew", pady=3, padx=(0, 6))
            c.grid_columnconfigure(1, weight=1)
            dot = label(c, "●", ctk.CTkFont("Segoe UI", 11), GREEN if v.connected else MUTED, height=18, width=10)
            dot.grid(row=0, column=0, padx=(10, 6), pady=(7, 0), sticky="w")
            n = label(c, v.name, Fonts.h3, anchor="w", height=18)
            n.grid(row=0, column=1, sticky="ew", pady=(7, 0))
            badge = ctk.CTkLabel(c, text=f" {_label_of(vpn.TUNNEL_TYPES, v.tunnel)} ", height=16, corner_radius=4,
                                 font=ctk.CTkFont("Segoe UI", 9, "bold"), fg_color=GREY_SOFT, text_color=MUTED)
            badge.grid(row=0, column=2, padx=(4, 10), pady=(7, 0), sticky="e")
            sub = v.server + (_("  · connecté ") + ", ".join(v.ips) if v.connected and v.ips else
                              _("  · connecté") if v.connected else "")
            s = label(c, sub, Fonts.mono_small, GREEN if v.connected else MUTED, anchor="w", height=16)
            s.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 10))
            scope = label(c, _("Tous les utilisateurs") if v.all_users else _("Utilisateur courant"), Fonts.small, MUTED,
                          anchor="w", height=15)
            scope.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(0, 7), padx=(0, 10))
            for w in (c, dot, n, badge, s, scope):
                w.bind("<Button-1>", lambda e, k=v.key: self.select(k))
                w.bind("<Double-Button-1>", lambda e, k=v.key: self._toggle_connection(k))
            self._cards[v.key] = c

    # ---------------------------------------------------------------- éditeur
    def _build_editor(self):
        right = card(self)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)

        head = ctk.CTkFrame(right, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 4))
        self.title = label(head, "", Fonts.h2)
        self.title.pack(side="left")
        self.status_pill = pill(head, "")
        self.status_pill.pack(side="left", padx=(10, 0))

        bar = ctk.CTkFrame(right, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 6))
        self.connect_btn = button(bar, _("Connecter"), self.connect_saved, kind="success", width=110)
        self.connect_btn.pack(side="left")
        self.connect_creds_btn = button(bar, _("Avec identifiants…"), self.connect_with_creds, width=0)
        self.connect_creds_btn.pack(side="left", padx=(6, 0))
        self.connect_win_btn = button(bar, _("Fenêtre Windows"), self.connect_windows, kind="ghost", width=0)
        self.connect_win_btn.pack(side="left", padx=(6, 0))
        self.disconnect_btn = button(bar, _("Déconnecter"), self.disconnect, kind="danger", width=110)
        self.disconnect_btn.pack(side="right")

        form = ctk.CTkScrollableFrame(right, fg_color="transparent")
        form.grid(row=2, column=0, sticky="nsew", padx=(10, 6))
        form.grid_columnconfigure((0, 1), weight=1, uniform="vpn")
        self.form = form

        def field(row, col, text):
            label(form, text, Fonts.small, MUTED, anchor="w").grid(row=row, column=col, sticky="w",
                                                                   padx=(8, 6) if col == 0 else (6, 8), pady=(8, 2))

        def place(w, row, col, span=1):
            w.grid(row=row, column=col, columnspan=span, sticky="ew", padx=(8, 6) if col == 0 else (6, 8))

        field(0, 0, _("Nom de la connexion"))
        field(0, 1, _("Serveur (nom ou adresse IP)"))
        self.f_name = entry(form, _("ex. VPN Bureau"), width=0)
        place(self.f_name, 1, 0)
        self.f_server = entry(form, _("ex. vpn.example.com"), width=0)
        place(self.f_server, 1, 1)
        field(2, 0, _("Type de tunnel"))
        field(2, 1, _("Authentification"))
        self.f_tunnel = option_menu(form, list(vpn.TUNNEL_TYPES.values()), lambda v: self._changed(), width=0)
        place(self.f_tunnel, 3, 0)
        self.f_auth = option_menu(form, list(vpn.AUTH_METHODS.values()), lambda v: self._changed(), width=0)
        place(self.f_auth, 3, 1)
        field(4, 0, _("Chiffrement"))
        field(4, 1, _("Clé pré-partagée (L2TP/IPsec)"))
        self.f_enc = option_menu(form, list(vpn.ENCRYPTION.values()), lambda v: self._changed(), width=0)
        place(self.f_enc, 5, 0)
        self.f_psk = entry(form, _("laisser vide pour ne pas la changer"), width=0, show="•")
        place(self.f_psk, 5, 1)
        field(6, 0, _("Suffixe DNS (optionnel)"))
        self.f_dns = entry(form, _("ex. corp.example"), width=0)
        place(self.f_dns, 7, 0)

        sw = ctk.CTkFrame(form, fg_color="transparent")
        sw.grid(row=8, column=0, columnspan=2, sticky="ew", padx=8, pady=(14, 4))
        self.f_split = ctk.CTkSwitch(sw, text=_("Split tunneling (seules les routes ci-dessous passent par le VPN)"),
                                     font=Fonts.small, text_color=TEXT, progress_color=ACCENT, command=self._changed)
        self.f_split.pack(anchor="w", pady=2)
        self.f_remember = ctk.CTkSwitch(sw, text=_("Mémoriser les identifiants (Windows)"), font=Fonts.small,
                                        text_color=TEXT, progress_color=ACCENT, command=self._changed)
        self.f_remember.pack(anchor="w", pady=2)
        self.f_all = ctk.CTkSwitch(sw, text=_("Pour tous les utilisateurs du poste (choisi à la création)"),
                                   font=Fonts.small, text_color=TEXT, progress_color=ACCENT, command=self._changed)
        self.f_all.pack(anchor="w", pady=2)

        label(form, _("Routes du split tunneling (une par ligne, ex. 10.0.0.0/8)"), Fonts.small, MUTED,
              anchor="w").grid(row=9, column=0, columnspan=2, sticky="w", padx=8, pady=(10, 2))
        self.f_routes = ctk.CTkTextbox(form, height=74, font=Fonts.mono, fg_color=SURFACE2, border_color=BORDER,
                                       border_width=1, corner_radius=8, text_color=TEXT)
        self.f_routes.grid(row=10, column=0, columnspan=2, sticky="ew", padx=8)
        self.f_routes.bind("<KeyRelease>", lambda e: self._changed())
        for e in (self.f_name, self.f_server, self.f_psk, self.f_dns):
            e.bind("<KeyRelease>", lambda ev: self._changed())

        # hors de la zone défilante : toujours visible au-dessus des boutons
        self.feedback = label(right, "", Fonts.small, MUTED, anchor="w", justify="left", wraplength=620)
        self.feedback.grid(row=3, column=0, sticky="w", padx=18, pady=(6, 0))

        actions = ctk.CTkFrame(right, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", padx=18, pady=(6, 16))
        self.save_btn = button(actions, _("Créer la connexion"), self.save, kind="primary", width=180, height=36)
        self.save_btn.pack(side="left")
        self.dup_btn = button(actions, _("Dupliquer"), self.duplicate, width=0, height=36)
        self.dup_btn.pack(side="left", padx=(8, 0))
        self.del_btn = button(actions, _("Supprimer"), self.delete, kind="danger", width=0, height=36)
        self.del_btn.pack(side="right")

    # ------------------------------------------------------------- données
    def refresh(self, quiet: bool = False):
        if self._busy:
            return

        def done(vpns):
            old_sig = [(v.key, v.status, tuple(v.ips)) for v in self.vpns]
            self.vpns = vpns
            if self.selected not in (None, NEW) and not self.current():
                self.selected = None
            if [(v.key, v.status, tuple(v.ips)) for v in vpns] != old_sig or not quiet:
                self._render_list()
                self._update_status()
            if self.selected is None and vpns:
                self.select(vpns[0].key)
            elif self.selected is None:
                self.new_vpn()

        self.app.bg(vpn.list_vpns, done, busy=None if quiet else _("Lecture des connexions VPN…"),
                    error=lambda e: self.app.toast(_("Lecture des VPN impossible : {0}", e), "err"))

    def _auto_refresh(self):
        if self.winfo_ismapped() and self.app.auto_refresh.get() and not self._busy:
            self.refresh(quiet=True)
        self.after(5000, self._auto_refresh)

    def current(self) -> vpn.Vpn | None:
        return next((v for v in self.vpns if v.key == self.selected), None)

    def select(self, key: str):
        self.selected = key
        for k, c in self._cards.items():
            sel = k == key
            c.configure(fg_color=ACCENT_SOFT if sel else SURFACE2, border_width=2 if sel else 1,
                        border_color=ACCENT if sel else BORDER)
        self._load_editor(self.current())

    def new_vpn(self, template: dict | None = None):
        self.selected = NEW
        for c in self._cards.values():
            c.configure(fg_color=SURFACE2, border_width=1, border_color=BORDER)
        self._load_editor(None, template)
        self.f_name.focus_set()

    def _load_editor(self, v: vpn.Vpn | None, template: dict | None = None):
        d = v.to_dict() if v else (template or {"name": "", "server": "", "tunnel": "Automatic", "auth": "MSChapv2",
                                                "encryption": "Required", "split": False, "remember": True,
                                                "dns_suffix": "", "all_users": False, "routes": []})
        for e, val in ((self.f_name, d["name"]), (self.f_server, d["server"]), (self.f_dns, d["dns_suffix"]),
                       (self.f_psk, "")):
            e.delete(0, "end")
            if val:
                e.insert(0, val)
        self.f_tunnel.set(_label_of(vpn.TUNNEL_TYPES, d["tunnel"]))
        self.f_auth.set(_label_of(vpn.AUTH_METHODS, d["auth"]))
        self.f_enc.set(_label_of(vpn.ENCRYPTION, d["encryption"]))
        for sw, on in ((self.f_split, d["split"]), (self.f_remember, d["remember"]), (self.f_all, d["all_users"])):
            sw.select() if on else sw.deselect()
        self.f_all.configure(state="disabled" if v else "normal")
        self.f_routes.delete("1.0", "end")
        self.f_routes.insert("1.0", "\n".join(d["routes"]))
        editing = v is not None
        self.title.configure(text=v.name if v else _("Nouvelle connexion VPN"))
        self.save_btn.configure(text=_("Enregistrer") if editing else _("Créer la connexion"))
        self.dup_btn.configure(state="normal" if editing else "disabled")
        self.del_btn.configure(state="normal" if editing and self.app.admin else "disabled")
        self._update_status()
        self._changed()

    def _form(self) -> dict:
        return {
            "name": self.f_name.get().strip(), "server": self.f_server.get().strip(),
            "tunnel": _key_of(vpn.TUNNEL_TYPES, self.f_tunnel.get()),
            "auth": _key_of(vpn.AUTH_METHODS, self.f_auth.get()),
            "encryption": _key_of(vpn.ENCRYPTION, self.f_enc.get()),
            "psk": self.f_psk.get(), "dns_suffix": self.f_dns.get().strip(),
            "split": bool(self.f_split.get()), "remember": bool(self.f_remember.get()),
            "all_users": bool(self.f_all.get()),
            "routes": [r.strip() for r in self.f_routes.get("1.0", "end").splitlines() if r.strip()],
        }

    def _existing_names(self, exclude: vpn.Vpn | None = None) -> set[str]:
        cfg_all = bool(self.f_all.get())
        scope = exclude.all_users if exclude else cfg_all
        return {v.name for v in self.vpns if v.all_users == scope and v is not exclude}

    def _changed(self):
        cfg = self._form()
        tunnel_l2tp = cfg["tunnel"] == "L2tp"
        self.f_psk.configure(state="normal" if tunnel_l2tp else "disabled")
        if not tunnel_l2tp and cfg["psk"]:
            self.f_psk.delete(0, "end")
            cfg["psk"] = ""
        self.f_routes.configure(text_color=TEXT if cfg["split"] else MUTED)
        errors, warns = vpn.validate(cfg, self._existing_names(self.current()))
        if errors and (cfg["name"] or cfg["server"]):
            self.feedback.configure(text="✕  " + "\n✕  ".join(errors), text_color=RED)
        elif warns:
            self.feedback.configure(text="⚠  " + "\n⚠  ".join(warns), text_color=ORANGE)
        elif cfg["name"] and cfg["server"]:
            self.feedback.configure(text=_("✓  Configuration valide"), text_color=GREEN)
        else:
            self.feedback.configure(text="")
        self.save_btn.configure(state="normal" if self.app.admin and not errors else "disabled")

    def _update_status(self):
        v = self.current()
        if not v:
            self.status_pill.pack_forget()
            for b in (self.connect_btn, self.connect_creds_btn, self.connect_win_btn, self.disconnect_btn):
                b.configure(state="disabled")
            return
        self.status_pill.pack(side="left", padx=(10, 0))
        if v.connected:
            txt = _("  Connecté") + (f" · {', '.join(v.ips)}" if v.ips else "") + "  "
            self.status_pill.configure(text=txt, fg_color=GREEN_SOFT, text_color=GREEN)
        else:
            self.status_pill.configure(text=_("  Déconnecté  "), fg_color=GREY_SOFT, text_color=MUTED)
        st_on, st_off = ("disabled", "normal") if v.connected else ("normal", "disabled")
        for b in (self.connect_btn, self.connect_creds_btn, self.connect_win_btn):
            b.configure(state=st_on)
        self.disconnect_btn.configure(state=st_off)

    # --------------------------------------------------------------- actions
    def _run(self, cmds: list[str], what: str, on_ok=None):
        self._busy = True
        self.app.log(what, "accent")

        def work():
            logs: list[str] = []
            ok = vpn.run_commands(cmds, log=logs.append)
            return ok, logs

        def done(res):
            ok, logs = res
            self._busy = False
            for line in logs:
                self.app.log("   " + line.replace("\n", "\n   "), "muted" if ok else "err")
            if ok:
                self.app.toast(what + _(" : terminé"), "ok")
                if on_ok:
                    on_ok()
            else:
                self.app.toast(what + _(" : échec — voir le journal"), "err")
            self.refresh(quiet=True)

        def error(e):
            self._busy = False
            self.app.toast(f"{what} : {e}", "err")

        self.app.bg(work, done, busy=what + "…", error=error)

    def save(self):
        cfg = self._form()
        old = self.current()
        errors, warns = vpn.validate(cfg, self._existing_names(old))
        if errors:
            info(self, _("Connexion invalide"), _("Corrige ces points :"), "\n".join(errors))
            return
        if warns and not confirm(self, _("Enregistrer malgré les avertissements ?"), "", _("Enregistrer"),
                                 detail="\n".join(warns)):
            return
        if old is not None and old.connected:
            if not confirm(self, _("Déconnecter d'abord ?"), _("« {0} » est connecté : Windows ne permet pas de le modifier pendant la connexion. Le déconnecter puis enregistrer ?", old.name), _("Déconnecter")):
                return
            vpn.disconnect(old)
        if old is None:
            cmds = vpn.build_create(cfg)
            what = _("Création du VPN « {0} »", cfg['name'])
        elif cfg["name"] != old.name:
            if not confirm(self, _("Renommer la connexion ?"),
                           _("Windows ne permet pas de renommer un VPN : la connexion sera supprimée puis recréée. "
                           "Les identifiants mémorisés devront être ressaisis."), _("Renommer")):
                return
            cmds = vpn.build_recreate(old, cfg)
            what = _("Renommage du VPN « {0} » en « {1} »", old.name, cfg['name'])
        else:
            cmds = vpn.build_update(old, cfg)
            what = _("Modification du VPN « {0} »", old.name)
        scope = cfg["all_users"] if old is None else old.all_users
        new_key = f"{'all' if scope else 'me'}:{cfg['name']}"
        self._run(cmds, what, on_ok=lambda: setattr(self, "selected", new_key))

    def duplicate(self):
        v = self.current()
        if v:
            d = v.to_dict()
            d["name"] = _("{0} (copie)", v.name)
            self.new_vpn(d)

    def delete(self):
        v = self.current()
        if not v or not confirm(self, _("Supprimer la connexion VPN ?"), _("« {0} » sera supprimée de Windows.", v.name),
                                _("Supprimer"), kind="danger"):
            return
        if v.connected:
            vpn.disconnect(v)
        self.selected = None
        self._run([vpn.build_remove(v)], _("Suppression du VPN « {0} »", v.name))

    def _toggle_connection(self, key: str):
        self.select(key)
        v = self.current()
        if v:
            self.disconnect() if v.connected else self.connect_saved()

    def connect_saved(self, user: str = "", password: str = ""):
        v = self.current()
        if not v:
            return
        self.app.log(_("Connexion au VPN « {0} »", v.name) + (_(" (utilisateur {0})", user) if user else ""), "accent")

        def done(res):
            ok, out = res
            self.app.log(out or _("(pas de sortie)"), "muted" if ok else "err")
            if ok:
                self.app.toast(_("Connecté à « {0} »", v.name), "ok")
            else:
                first = (out or _("Échec")).splitlines()[0]
                self.app.toast(_("Connexion impossible : {0}", first), "err")
            self.refresh(quiet=True)
            self.app.refresh_adapters(quiet=True)

        self.app.bg(lambda: vpn.connect(v, user, password), done, busy=_("Connexion à « {0} »…", v.name))

    def connect_with_creds(self):
        v = self.current()
        if not v:
            return
        d = _CredentialsDialog(self, v.name)
        if d.result:
            self.connect_saved(*d.result)

    def connect_windows(self):
        v = self.current()
        if v:
            vpn.connect_dialog(v)
            self.app.log(_("Fenêtre de connexion Windows ouverte pour « {0} »", v.name))
            self.after(4000, lambda: self.refresh(quiet=True))

    def disconnect(self):
        v = self.current()
        if not v:
            return

        def done(res):
            ok, out = res
            self.app.log(_("Déconnexion de « {0} » : {1}", v.name, out or 'OK'), None if ok else "err")
            self.app.toast(_("« {0} » déconnecté", v.name) if ok else _("Déconnexion impossible"), "ok" if ok else "err")
            self.refresh(quiet=True)
            self.app.refresh_adapters(quiet=True)

        self.app.bg(lambda: vpn.disconnect(v), done, busy=_("Déconnexion de « {0} »…", v.name))


class _CredentialsDialog(ctk.CTkToplevel):
    """Identifiants pour une connexion ponctuelle : NetShift ne les enregistre nulle part."""

    def __init__(self, master, name: str):
        super().__init__(master)
        self.result = None
        self.title(_("Identifiants VPN"))
        self.configure(fg_color=SURFACE)
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=(20, 16))
        label(body, _("Connexion à « {0} »", name), Fonts.h2).pack(anchor="w")
        label(body, _("Utilisés pour cette connexion uniquement ; NetShift ne les enregistre pas."), Fonts.small,
              MUTED).pack(anchor="w", pady=(4, 10))
        label(body, _("Utilisateur"), Fonts.small, MUTED).pack(anchor="w")
        self.user = entry(body, _("DOMAINE\\utilisateur ou utilisateur@domaine"), width=380)
        self.user.pack(fill="x", pady=(2, 8))
        label(body, _("Mot de passe"), Fonts.small, MUTED).pack(anchor="w")
        self.pwd = entry(body, "", width=380, show="•")
        self.pwd.pack(fill="x", pady=(2, 0))
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", pady=(18, 0))
        button(row, _("Connecter"), self._ok, kind="success", width=110).pack(side="right")
        button(row, _("Annuler"), self.destroy, kind="ghost", width=90).pack(side="right", padx=(0, 8))
        for w in (self.user, self.pwd):
            w.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(60, self._focus)
        self.wait_window()

    def _focus(self):
        self.lift()
        self.focus_force()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.user.focus_set()

    def _ok(self):
        if self.user.get().strip():
            self.result = (self.user.get().strip(), self.pwd.get())
            self.destroy()
