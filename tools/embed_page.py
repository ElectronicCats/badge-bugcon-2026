#!/usr/bin/env python3
"""
embed_page.py — Comprime con gzip la página del Wi-Fi del badge y la escribe
como arreglo de C (patrón html_data.h del keychain; F6.11/F6.12, RNF-08).
El resultado se guarda en el repo, así compilar no necesita Python. La salida
es reproducible (mtime = 0): el mismo HTML da el mismo .h.

Uso (desde la raíz del repo):
  ./tools/embed_page.py web/phone/index.html \
      firmware/badge_bugcon_2026/src/services/wifi_page.h
"""
import gzip
import sys


def to_header(html: bytes, source: str) -> str:
    data = gzip.compress(html, compresslevel=9, mtime=0)
    rows = (
        "    " + ", ".join(f"0x{b:02x}" for b in data[i : i + 12]) + ","
        for i in range(0, len(data), 12)
    )
    return (
        f"// Generado por tools/embed_page.py desde {source}: no editar.\n"
        f"// {len(html)} B de HTML -> {len(data)} B con gzip.\n"
        "#pragma once\n\n#include <stdint.h>\n\nnamespace wifi_page {\n"
        "const uint8_t GZ[] = {\n" + "\n".join(rows) + "\n};\n"
        "} // namespace wifi_page\n"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[1], "rb") as f:
        html = f.read()
    header = to_header(html, sys.argv[1])
    with open(sys.argv[2], "w") as f:
        f.write(header)
    body = header.split("GZ[] = {\n", 1)[1].split("\n};")[0]
    data = bytes(int(b, 16) for b in body.replace(",", " ").split())
    assert gzip.decompress(data) == html  # El arreglo escrito es la página
    print(header.splitlines()[1][3:])
