#!/usr/bin/env python3
"""
package_web.py — Empaqueta el configurador USB local (web/configurator), el
álbum web (web/album), sus instrucciones (web/LEEME.txt) y la licencia
(LICENSE, como LICENSE.txt) en un .zip para descargar, descomprimir y abrir
con file://, sin servidor (F6.15, D-06, D-16).
Las páginas conservan su carpeta para que el enlace relativo "Ver el álbum"
(../album/index.html) funcione. La salida es reproducible (fechas fijas): los
mismos archivos y la misma versión dan el mismo .zip.

Uso (desde la raíz del repo):
  ./tools/package_web.py dist/bugcon26-configurador.zip [versión]
"""
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDER = "bugcon26-configurador"
FILES = ("LEEME.txt", "LICENSE.txt", "configurator/index.html",
         "album/index.html")


def build(version: str = "desarrollo") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in FILES:
            # La GPL-3.0 pide entregar su texto junto con el código.
            source = ROOT / ("LICENSE" if name == "LICENSE.txt" else f"web/{name}")
            data = source.read_bytes()
            if name == "LEEME.txt":
                data = data.replace(b"{version}", version.encode("utf-8"))
            info = zipfile.ZipInfo(f"{FOLDER}/{name}", (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data, compresslevel=9)
    return buf.getvalue()


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    data = build(*sys.argv[2:])
    out.write_bytes(data)
    print(f"{out}: {len(data)} B")
