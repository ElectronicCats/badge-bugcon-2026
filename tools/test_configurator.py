#!/usr/bin/env python3
"""
test_configurator.py — El configurador web (web/configurator/index.html),
el álbum web (web/album/index.html) y la página del teléfono
(web/phone/index.html) usan el mismo catálogo y los mismos límites que
el firmware: el índice de la selección y de la posición viaja en la estampa, y
CARD rechaza lo que no cumpla cfg::card. La página del teléfono embebida en el
firmware (wifi_page.h) es la del repo, y el .zip del configurador
(tools/package_web.py) abre sin servidor. Sin badge ni navegador (biblioteca
estándar).

Uso: python3 -m unittest tools/test_configurator.py
"""
import gzip
import io
import posixpath
import re
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import embed_gfx  # noqa: E402
import package_web  # noqa: E402
from embed_page import from_header  # noqa: E402

SRC = ROOT / "firmware/badge_bugcon_2026/src"
PAGES = {name: (ROOT / f"web/{name}/index.html").read_text(encoding="utf-8")
         for name in ("configurator", "album", "phone")}
# El firmware vive en otro repositorio: sin él se omiten las comparaciones.
HAS_FW = SRC.is_dir()
needs_fw = unittest.skipUnless(HAS_FW, "requiere firmware/ (repo del firmware)")


def fw(path):
    return (SRC / path).read_text(encoding="utf-8") if HAS_FW else ""


CARD_CPP = fw("services/card.cpp")
CARD_H = fw("services/card.h")
CONFIG = fw("config/badge_config.h")


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
    @needs_fw
    def test_catalogs(self):
        for page, html in PAGES.items():
            for name in ("TEAMS", "POSITIONS", "RARITIES", "STATS"):
                if page == "phone" and name == "RARITIES":
                    continue  # el teléfono no muestra la rareza
                with self.subTest(page=page, name=name):
                    self.assertEqual(strings(html, name), strings(CARD_CPP, name))

    @needs_fw
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
                if page == "phone" and web in ("AVATAR_W", "AVATAR_H"):
                    continue  # avatar solo por USB
                with self.subTest(page=page, name=web):
                    self.assertEqual(number(html, web), number(source, fw))
        self.assertEqual(number(PAGES["album"], "ATTENDEES"),
                         number(CONFIG, "ATTENDEES"))
        self.assertEqual(number(PAGES["album"], "MASTER_FIRST"),
                         number(CONFIG, "MASTER_FIRST"))

    def test_privacy_notice(self):
        # El aviso de privacidad va en las tres páginas y en el LEEME del .zip.
        leeme = (ROOT / "web/LEEME.txt").read_text(encoding="utf-8")
        for page, text in [*PAGES.items(), ("LEEME", leeme)]:
            text = " ".join(text.split()).lower()  # sin saltos de línea
            for phrase in ["privacidad",
                           "no hay servidor ni almacenamiento central",
                           "infrarrojo", "handle", "publiques", "borrar datos"]:
                with self.subTest(page=page, phrase=phrase):
                    self.assertIn(phrase, text)

    def test_stats_glossary(self):
        # Glosario de la Copa (games/cup.h) junto a las barras de stats.
        for page in ["configurator", "phone"]:
            text = " ".join(PAGES[page].split())
            for phrase in ['id="glossary"', "<dt>Ataque</dt>", "<dt>Defensa</dt>",
                           "<dt>Hack · control</dt>", "<dt>Suerte</dt>", "99 como 149"]:
                with self.subTest(page=page, phrase=phrase):
                    self.assertIn(phrase, text)


class TabsTest(unittest.TestCase):
    def test_default_tab_is_template(self):
        # Al abrir la página la pestaña activa es la plantilla; "Pantalla
        # completa" existe pero no está seleccionada.
        html = PAGES["configurator"]
        self.assertIn('role="tablist"', html)
        tabs = dict(re.findall(
            r'<button role="tab"[^>]*data-target="(\w+)"[^>]*'
            r'aria-selected="(\w+)"', html))
        self.assertEqual(tabs, {"avatar": "true", "slot": "false"})


class PhonePageTest(unittest.TestCase):
    @needs_fw
    def test_embedded_page_is_current(self):
        header = fw("services/wifi_page.h")
        self.assertEqual(gzip.decompress(from_header(header)).decode("utf-8"),
                         PAGES["phone"], "corre tools/embed_page.py")

    @needs_fw
    def test_badge_gfx_is_current(self):
        # Fuentes, escudos y textos del gafete iguales a los del firmware
        self.assertEqual(embed_gfx.current(PAGES["configurator"]),
                         embed_gfx.block(), "corre tools/embed_gfx.py")

    def test_no_external_resources(self):
        # Sin Internet en el AP: todo va en el HTML o se pide al badge.
        self.assertIsNone(re.search(r"https?:|//[\w.-]+\.\w|src=|href=",
                                    PAGES["phone"]))


class PackageTest(unittest.TestCase):
    """El .zip de package_web.py abre desde file:// sin servidor ni red."""

    def test_package(self):
        data = package_web.build("v9.9.9")
        self.assertEqual(data, package_web.build("v9.9.9"))  # reproducible
        z = zipfile.ZipFile(io.BytesIO(data))
        names = set(z.namelist())
        folder = package_web.FOLDER
        self.assertEqual(names, {f"{folder}/{n}" for n in package_web.FILES})
        self.assertIn("Versión: v9.9.9", z.read(f"{folder}/LEEME.txt").decode())
        self.assertIn("GPL-3.0", z.read(f"{folder}/LEEME.txt").decode())
        self.assertIn("GNU GENERAL PUBLIC LICENSE",
                      z.read(f"{folder}/LICENSE.txt").decode())
        for name in names - {f"{folder}/LEEME.txt", f"{folder}/LICENSE.txt"}:
            html = z.read(name).decode("utf-8")
            with self.subTest(page=name):
                self.assertEqual(html, PAGES[name.split("/")[1]])
                self.assertIsNone(re.search(r"https?:|//[\w.-]+\.\w", html))
                for href in re.findall(r'(?:href|src)="([^"]+)"', html):
                    target = posixpath.normpath(posixpath.join(
                        posixpath.dirname(name), href))
                    self.assertIn(target, names, href)


if __name__ == "__main__":
    unittest.main()
