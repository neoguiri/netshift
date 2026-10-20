"""Garde-fou : les captures de la documentation ne doivent montrer QUE la fenêtre de NetShift.

Chaque image doit avoir exactement la couleur de la barre latérale sur son bord gauche et la couleur de
fond sur son bord droit, sur toute la hauteur. Une autre fenêtre (éditeur, navigateur…) qui se serait
retrouvée sur la capture casse ces bandes et fait échouer ce test, localement comme en CI.
"""
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")

SHOTS = sorted((Path(__file__).resolve().parent.parent / "docs" / "screenshots").rglob("*.png"))
# (barre latérale, fond) — doivent correspondre à SIDEBAR et BG dans netshift/ui.py
THEMES = {"dark": ((0x12, 0x16, 0x1D), (0x0E, 0x11, 0x16)), "light": ((0xE8, 0xEB, 0xF1), (0xF3, 0xF5, 0xF9))}


def test_screenshots_exist():
    assert SHOTS, "aucune capture dans docs/screenshots"


@pytest.mark.parametrize("path", SHOTS, ids=lambda p: p.name)
def test_screenshot_shows_only_the_app(path):
    theme = "dark" if path.stem.endswith("-dark") else "light"
    sidebar, bg = THEMES[theme]
    im = Image.open(path).convert("RGB")
    w, h = im.size
    for y in range(4, h - 4, max(1, h // 60)):
        assert im.getpixel((3, y)) == sidebar, f"{path.name}: bord gauche inattendu en y={y}"
        assert im.getpixel((w - 3, y)) == bg, f"{path.name}: bord droit inattendu en y={y}"
