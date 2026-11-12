#!/usr/bin/env python3
"""
embed_gfx.py — Copia al configurador web (web/configurator/index.html) lo que
el badge necesita para dibujar el gafete: las fuentes de src/gfx/fonts, los
escudos de 24 px de las villas (src/ui/icons.cpp, en el orden de
theme::teamLogo) y los nombres de card::teamName(). Con eso la plantilla
"Copa BugCon" es la pantalla del gafete píxel por píxel.

Reemplaza el bloque entre BEGIN/END badge_gfx de la página. Se corre después
de cambiar una fuente, un logo o el catálogo de villas:
  ./tools/embed_gfx.py
"""
import base64
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "firmware/badge_bugcon_2026/src"
PAGE = ROOT / "web/configurator/index.html"
# Las que usan home.cpp y card_face.cpp (theme::FONT, FONT_5X8, las de
# theme::fitFont y NICK_FONT).
FONTS = ("5x8", "6x12", "8x16b", "10x20b", "12x24b", "14x28b", "16x32b")
BEGIN = "// BEGIN badge_gfx"
END = "// END badge_gfx"


def b64(data):
    return base64.b64encode(bytes(data)).decode()


def hex_bytes(text):
    return [int(h, 16) for h in re.findall(r"0x([0-9A-Fa-f]{2})", text)]


def font(name):
    cpp = (SRC / f"gfx/fonts/font_{name}.cpp").read_text(encoding="utf-8")
    bitmap = hex_bytes(re.search(r"BITMAP\[\] = \{(.*?)\};", cpp, re.S).group(1))
    rows = re.findall(r"\{(-?\d+), (-?\d+), (-?\d+), (-?\d+), (-?\d+), (-?\d+)\}",
                      re.search(r"GLYPHS\[\] = \{(.*?)\n\};", cpp, re.S).group(1))
    first, last, line, ascent = re.search(
        r"Font FONT_\w+ = \{BITMAP, GLYPHS, (0x[0-9A-F]+), (0x[0-9A-F]+), (\d+), (\d+)\}",
        cpp).groups()
    first, last = int(first, 16), int(last, 16)
    assert len(rows) == last - first + 1, name
    glyphs = b"".join(struct.pack("<HBBbbB", *map(int, r)) for r in rows)
    return {"first": first, "lineHeight": int(line), "ascent": int(ascent),
            "glyphs": b64(glyphs), "bitmap": b64(bitmap)}


def shields():
    icons = (SRC / "ui/icons.cpp").read_text(encoding="utf-8")
    theme = (SRC / "ui/theme.cpp").read_text(encoding="utf-8")
    # Segundo renglón de LOGOS (los escudos); nullptr = esa villa sin logo
    row = re.search(r"LOGOS\[\]\[card::TEAM_COUNT\] = \{\s*\{.*?\},\s*\{(.*?)\}",
                    theme, re.S).group(1)
    out = []
    for name in (e.strip().lstrip("&") for e in row.split(",") if e.strip()):
        if name == "nullptr":
            out.append(None)
            continue
        w, h, ink, paper = re.search(
            r"Sprite " + name + r" = \{(\d+), (\d+), (\w+), (\w+)\}", icons).groups()
        assert paper == "nullptr", name + ": la vista previa solo dibuja la tinta"
        data = hex_bytes(re.search(ink + r"\[\] = \{(.*?)\};", icons, re.S).group(1))
        out.append({"w": int(w), "h": int(h), "ink": b64(data)})
    return out


def block():
    card = (SRC / "services/card.cpp").read_text(encoding="utf-8")
    config = (SRC / "config/badge_config.h").read_text(encoding="utf-8")
    teams = re.findall(r'"([^"]*)"',
                       re.search(r"TEAMS\[\] = \{(.*?)\};", card, re.S).group(1))
    home = (SRC / "apps/home.cpp").read_text(encoding="utf-8")
    text = lambda name: re.search(name + r' = "([^"]*)"', home).group(1)
    gfx = {
        "teams": teams,
        "masterFirst": int(re.search(r"MASTER_FIRST = (\d+)", config).group(1)),
        "barHeight": int(re.search(r"BAR_HEIGHT = (\d+)", config).group(1)),
        "event": text("EVENT"),
        "menuHint": text("MENU_HINT"),
        "masterHint": text("MASTER_HINT"),
        "shields": shields(),
        "fonts": {n: font(n) for n in FONTS},
    }
    body = ",\n".join(f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}"
                      for k, v in gfx.items())
    return (f"{BEGIN}: generado por tools/embed_gfx.py desde el firmware, no editar.\n"
            f"const BADGE_GFX = {{\n{body},\n}};\n{END}")


def current(html):
    """El bloque que tiene la página, o None."""
    m = re.search(re.escape(BEGIN) + r".*?" + re.escape(END), html, re.S)
    return m.group(0) if m else None


if __name__ == "__main__":
    html = PAGE.read_text(encoding="utf-8")
    old = current(html)
    if old is None:
        raise SystemExit(f"{PAGE}: falta el bloque {BEGIN} ... {END}")
    PAGE.write_text(html.replace(old, block()), encoding="utf-8")
    print(f"{PAGE.relative_to(ROOT)}: {len(block())} B de gráficos del badge")
