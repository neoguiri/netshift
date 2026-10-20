"""Traductions de l'interface. Le français est la langue source ; les autres langues sont des catalogues
{texte français: traduction} dans netshift/locales/.

La langue est fixée au démarrage (avant l'import des autres modules), dans cet ordre :
variable d'environnement NETSHIFT_LANG, réglage « lang » de settings.json, langue de Windows.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

LANGUAGES = {"fr": "Français", "en": "English"}
_lang = "fr"
_catalog: dict[str, str] = {}


def _(text: str, *args, **kwargs) -> str:
    """Traduit `text` puis le formate avec str.format(*args, **kwargs) s'il y a des arguments."""
    out = _catalog.get(text, text)
    return out.format(*args, **kwargs) if (args or kwargs) else out


def language() -> str:
    return _lang


def set_language(lang: str):
    global _lang, _catalog
    _lang = lang if lang in LANGUAGES else "en"
    if _lang == "fr":
        _catalog = {}
    else:
        from importlib import import_module
        _catalog = import_module(f".locales.{_lang}", __package__).CATALOG


def _settings_candidates() -> list[Path]:
    """Mêmes emplacements que store.data_dir(), sans importer store (qui utilise déjà _)."""
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parent.parent
    appdata = Path(os.environ.get("APPDATA", Path.home())) / "NetShift" / "settings.json"
    if (base / "unins000.exe").exists():
        return [appdata]
    return [base / "data" / "settings.json", appdata]


def _windows_language() -> str:
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "fr" if (lang_id & 0x3FF) == 0x0C else "en"   # LANG_FRENCH
    except Exception:
        return "en"


def detect() -> str:
    env = os.environ.get("NETSHIFT_LANG", "").lower()
    if env in LANGUAGES:
        return env
    for path in _settings_candidates():
        try:
            lang = json.loads(path.read_text(encoding="utf-8")).get("lang")
            if lang in LANGUAGES:
                return lang
        except (OSError, ValueError):
            continue
    return _windows_language()


set_language(detect())
