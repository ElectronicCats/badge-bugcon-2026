#!/usr/bin/env python3
"""
test_configurator.py — El configurador web (web/configurator/index.html, F6.1)
y el álbum web (web/album/index.html, F6.3) usan el mismo catálogo y los
mismos límites que el firmware: el índice de la selección y de la posición
viaja en la estampa, y CARD rechaza lo que no cumpla cfg::card. Sin badge ni
navegador (biblioteca estándar).

Uso: python3 -m unittest tools/test_configurator.py
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "firmware/badge_bugcon_2026/src"
PAGES = {name: (ROOT / f"web/{name}/index.html").read_text(encoding="utf-8")
         for name in ("configurator", "album")}
CARD_CPP = (SRC / "services/card.cpp").read_text(encoding="utf-8")
CARD_H = (SRC / "services/card.h").read_text(encoding="utf-8")
CONFIG = (SRC / "config/badge_config.h").read_text(encoding="utf-8")


def strings(source, name):
    """Lista de textos de `name = [...]` (JS) o `name[] = {...}` (C++)."""
    m = re.search(name + r"(?:\[[^\]]*\])?\s*=\s*[\[{]([^\]}]*)[\]}]", source)
    if not m:
        raise AssertionError(f"no se encontró {name}")
    return re.findall(r'"([^"]*)"', m.group(1))


def number(source, name):
    m = re.search(name + r"\s*=\s*(\d+)", source)
    if not m:
        raise AssertionError(f"no se encontró {name}")
    return int(m.group(1))


class CatalogTest(unittest.TestCase):
    def test_catalogs(self):
        for page, html in PAGES.items():
            for name in ("TEAMS", "POSITIONS", "RARITIES", "STATS"):
                with self.subTest(page=page, name=name):
                    self.assertEqual(strings(html, name), strings(CARD_CPP, name))

    def test_limits(self):
        pairs = [("STAT_MAX", CONFIG, "STAT_MAX"),
                 ("STAT_BUDGET", CONFIG, "STAT_BUDGET"),
                 ("AVATAR_W", CONFIG, "AVATAR_WIDTH"),
                 ("AVATAR_H", CONFIG, "AVATAR_HEIGHT"),
                 ("NICK_BYTES", CARD_H, "NICK_BYTES"),
                 ("HANDLE_BYTES", CARD_H, "HANDLE_BYTES"),
                 ("CARD_VERSION", CARD_H, "VERSION")]
        for page, html in PAGES.items():
            for web, source, fw in pairs:
                if page == "album" and web in ("STAT_BUDGET", "CARD_VERSION",
                                               "AVATAR_W", "AVATAR_H"):
                    continue  # el álbum no edita estampas ni recibe avatares
                with self.subTest(page=page, name=web):
                    self.assertEqual(number(html, web), number(source, fw))
        self.assertEqual(number(PAGES["album"], "ATTENDEES"),
                         number(CONFIG, "ATTENDEES"))


if __name__ == "__main__":
    unittest.main()
