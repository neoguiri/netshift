"""Cohérence des traductions : toutes les chaînes _() du code ont une traduction, avec les mêmes marqueurs."""
import ast
import string
from collections import Counter
from pathlib import Path

import pytest

from netshift import i18n
from netshift.locales import en

PKG = Path(__file__).resolve().parent.parent / "netshift"


def source_keys() -> dict[str, str]:
    keys = {}
    for path in sorted(PKG.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    keys.setdefault(a.value, f"{path.name}:{node.lineno}")
    return keys


def fields(text: str) -> Counter:
    return Counter((name, spec, conv) for _lit, name, spec, conv in string.Formatter().parse(text) if name is not None)


KEYS = source_keys()


def test_every_string_is_translated():
    missing = {k: where for k, where in KEYS.items() if k not in en.CATALOG}
    assert not missing, f"{len(missing)} chaîne(s) sans traduction anglaise : {missing}"


def test_no_orphan_translation():
    orphans = [k for k in en.CATALOG if k not in KEYS]
    assert not orphans, f"Traductions inutilisées (à supprimer de locales/en.py) : {orphans}"


@pytest.mark.parametrize("key", sorted(k for k in KEYS if k in en.CATALOG))
def test_placeholders_match(key):
    value = en.CATALOG[key]
    assert fields(key) == fields(value), f"Marqueurs différents : {key!r} → {value!r}"
    assert value.count("\n") == key.count("\n") or key.startswith("Termes combinés"), "Nombre de lignes différent"
    assert value.startswith("\n") == key.startswith("\n") and value.endswith("\n") == key.endswith("\n")


def test_switch_language():
    try:
        i18n.set_language("en")
        assert i18n._("Prêt") == "Ready"
        assert i18n._("{0} carte(s) réseau détectée(s)", 3) == "3 network adapter(s) found"
        assert i18n._("texte inconnu") == "texte inconnu"
        i18n.set_language("xx")
        assert i18n.language() == "en"
    finally:
        i18n.set_language("fr")
    assert i18n._("Prêt") == "Prêt"
    assert i18n._("Erreur : {0}", "x") == "Erreur : x"
