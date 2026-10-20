"""Persistance : presets, paramètres et historique (fichiers JSON dans data/)."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Fichiers embarqués (icône) : dossier temporaire de PyInstaller en mode exe, sinon le dépôt."""
    return Path(getattr(sys, "_MEIPASS", app_dir()))


def is_installed(base: Path | None = None) -> bool:
    """Vrai si NetShift a été installé (installeur Inno Setup) plutôt que lancé en version portable."""
    base = base or app_dir()
    return (base / "unins000.exe").exists()


def user_data_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "NetShift"


def data_dir() -> Path:
    """Version installée : %APPDATA%\\NetShift (conservé lors des mises à jour et désinstallations).
    Version portable : dossier data\\ à côté de l'application (repli sur %APPDATA% si non inscriptible)."""
    if not is_installed():
        d = app_dir() / "data"
        try:
            d.mkdir(exist_ok=True)
            probe = d / ".write_test"
            probe.write_text("ok")
            probe.unlink()
            return d
        except OSError:
            pass
    d = user_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


EMPTY_CONFIG = {
    "mode": "static", "ip": "", "mask": "255.255.255.0", "gateway": "",
    "dns_mode": "static", "dns1": "", "dns2": "", "extra_ips": [],
}

DEFAULT_PRESETS = [
    {"name": "DHCP automatique", "description": "IP et DNS fournis par le serveur DHCP",
     "config": {**EMPTY_CONFIG, "mode": "dhcp", "mask": "", "dns_mode": "auto"}},
    {"name": "Box 192.168.1.x", "description": "Exemple : réseau domestique classique",
     "config": {**EMPTY_CONFIG, "ip": "192.168.1.50", "gateway": "192.168.1.1", "dns1": "192.168.1.1", "dns2": "1.1.1.1"}},
    {"name": "Lien direct 10.0.0.x", "description": "Exemple : câble direct vers un équipement, sans passerelle",
     "config": {**EMPTY_CONFIG, "ip": "10.0.0.10", "mask": "255.255.255.0"}},
]

PUBLIC_DNS = {
    "Cloudflare": ("1.1.1.1", "1.0.0.1"),
    "Google": ("8.8.8.8", "8.8.4.4"),
    "Quad9": ("9.9.9.9", "149.112.112.112"),
    "OpenDNS": ("208.67.222.222", "208.67.220.220"),
}


def normalize_config(cfg: dict) -> dict:
    out = {**EMPTY_CONFIG, **(cfg or {})}
    out["extra_ips"] = [x for x in (out.get("extra_ips") or []) if str(x).strip()]
    return out


def summarize(cfg: dict) -> str:
    cfg = normalize_config(cfg)
    if cfg["mode"] == "dhcp":
        s = "DHCP"
        if cfg["dns_mode"] == "static" and cfg["dns1"]:
            s += f" · DNS {cfg['dns1']}"
        return s
    try:
        from .netbackend import parse_mask
        pfx = f"/{parse_mask(cfg['mask'])}"
    except Exception:
        pfx = ""
    s = f"{cfg['ip'] or '?'}{pfx}"
    if cfg["gateway"]:
        s += f" · GW {cfg['gateway']}"
    if cfg["extra_ips"]:
        s += f" · +{len(cfg['extra_ips'])} IP"
    return s


class _JsonFile:
    def __init__(self, path: Path, default):
        self.path = path
        self.default = default

    def load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self.default() if callable(self.default) else self.default

    def save(self, data):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)


class PresetStore:
    def __init__(self, directory: Path):
        first_run = not (directory / "presets.json").exists()
        self._file = _JsonFile(directory / "presets.json", lambda: {"presets": []})
        self.presets: list[dict] = [self._fix(p) for p in self._file.load().get("presets", [])]
        if first_run:
            self.presets = [self._fix(dict(p)) for p in DEFAULT_PRESETS]
            self.save()

    @staticmethod
    def _fix(p: dict) -> dict:
        p.setdefault("id", uuid.uuid4().hex[:12])
        p.setdefault("name", "Sans nom")
        p.setdefault("description", "")
        p["config"] = normalize_config(p.get("config"))
        return p

    def save(self):
        self._file.save({"version": 1, "presets": self.presets})

    def get(self, pid: str) -> dict | None:
        return next((p for p in self.presets if p["id"] == pid), None)

    def by_name(self, name: str) -> dict | None:
        return next((p for p in self.presets if p["name"] == name), None)

    def unique_name(self, base: str) -> str:
        names = {p["name"] for p in self.presets}
        if base not in names:
            return base
        i = 2
        while f"{base} ({i})" in names:
            i += 1
        return f"{base} ({i})"

    def add(self, name: str, config: dict, description: str = "") -> dict:
        p = self._fix({"name": self.unique_name(name.strip() or "Nouveau preset"), "description": description,
                       "config": dict(config)})
        p["id"] = uuid.uuid4().hex[:12]
        self.presets.append(p)
        self.save()
        return p

    def update(self, pid: str, **fields):
        p = self.get(pid)
        if p:
            p.update(fields)
            self._fix(p)
            self.save()

    def delete(self, pid: str):
        self.presets = [p for p in self.presets if p["id"] != pid]
        self.save()

    def move(self, pid: str, delta: int):
        idx = next((i for i, p in enumerate(self.presets) if p["id"] == pid), None)
        if idx is None:
            return
        j = max(0, min(len(self.presets) - 1, idx + delta))
        self.presets.insert(j, self.presets.pop(idx))
        self.save()

    def export(self, path: str):
        Path(path).write_text(json.dumps({"version": 1, "presets": self.presets}, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    def import_file(self, path: str) -> int:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        items = data.get("presets", data) if isinstance(data, dict) else data
        n = 0
        for p in items:
            if isinstance(p, dict) and "config" in p:
                self.add(p.get("name", "Importé"), p["config"], p.get("description", ""))
                n += 1
        return n


class Settings:
    def __init__(self, directory: Path):
        self._file = _JsonFile(directory / "settings.json", dict)
        self.data: dict = {"theme": "dark", "show_virtual": True, "auto_refresh": True, **self._file.load()}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self._file.save(self.data)


class History:
    """Historique des configurations appliquées, avec l'état précédent pour pouvoir revenir en arrière."""

    MAX = 50

    def __init__(self, directory: Path):
        self._file = _JsonFile(directory / "history.json", lambda: {"entries": []})
        self.entries: list[dict] = self._file.load().get("entries", [])

    def add(self, adapter_name: str, adapter_desc: str, before: dict, after: dict, label: str, ok: bool):
        self.entries.insert(0, {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"), "adapter": adapter_name, "adapter_desc": adapter_desc,
            "before": before, "after": after, "label": label, "ok": ok,
        })
        del self.entries[self.MAX:]
        self._file.save({"entries": self.entries})

    def last_for(self, adapter_desc: str) -> dict | None:
        return next((e for e in self.entries if e["adapter_desc"] == adapter_desc), None)

    def clear(self):
        self.entries = []
        self._file.save({"entries": self.entries})
