"""Icône dans la zone de notification : ouvrir NetShift, appliquer un preset en deux clics, état des cartes."""
from __future__ import annotations

from .i18n import _
from .store import resource_dir


class Tray:
    """Les clics arrivent dans le thread de pystray : toute action passe par app.ui() (thread de Tk)."""

    def __init__(self, app):
        self.app = app
        self.icon = None
        try:
            import pystray
            from PIL import Image
        except ImportError:   # dépendances optionnelles : l'app fonctionne sans
            return
        self._pystray = pystray
        image = Image.open(resource_dir() / "assets" / "netshift.png")
        self.icon = pystray.Icon("NetShift", image, "NetShift", menu=pystray.Menu(self._items))
        self.icon.run_detached()

    @property
    def available(self) -> bool:
        return self.icon is not None

    # ------------------------------------------------------------------ menu
    def _items(self):
        ps = self._pystray
        Item, Menu = ps.MenuItem, ps.Menu
        app = self.app
        adapters = list(app.adapters)
        presets = list(app.presets.presets)

        def apply(pid, guid):
            return lambda icon, item: app.ui(app.tray_apply, pid, guid)

        preset_items = []
        for p in presets:
            target = app.preset_adapter(p)
            if target:
                preset_items.append(Item(f"{p['name']}   → {target.name}", apply(p["id"], target.guid)))
            elif adapters:
                preset_items.append(Item(p["name"], Menu(*[Item(a.name, apply(p["id"], a.guid)) for a in adapters])))
        if not preset_items:
            preset_items = [Item(_("Aucun preset"), None, enabled=False)]

        card_items = []
        for a in adapters:
            ip = a.primary_ip
            state = (f"{ip.ip}/{ip.prefix}" if ip and a.up else _("désactivée") if a.disabled else _("déconnectée"))
            card_items.append(Item(f"{'●' if a.up else '○'}  {a.name} — {state}", None, enabled=False))
        if not card_items:
            card_items = [Item(_("Lecture en cours…"), None, enabled=False)]

        return (
            Item(_("Ouvrir NetShift"), lambda icon, item: app.ui(app.show_window), default=True),
            Menu.SEPARATOR,
            Item(_("Appliquer un preset"), Menu(*preset_items)),
            Item(_("Cartes réseau"), Menu(*card_items)),
            Menu.SEPARATOR,
            Item(_("Quitter"), lambda icon, item: app.ui(app.quit_app)),
        )

    # -------------------------------------------------------------- actions
    def notify(self, message: str, title: str = "NetShift"):
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
