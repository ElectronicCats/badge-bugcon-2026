#!/usr/bin/env python3
"""
badge_image.py — Imagen cualquiera -> bytes en el formato del badge.

Formato: 1 bpp, filas completas, MSB primero, 1 = blanco, de ancho x alto
píxeles ((ancho + 7) // 8 * alto bytes). Sirve igual para el Marco (el
tamaño de INFO panel) y para el avatar (96 x 96).

  load_for_badge(ruta, w, h)  .bin/.pbm del tamaño exacto pasan tal cual
                              (sin Pillow); lo demás se convierte
  prepare_image(ruta, w, h)   convierte con Pillow: gira por EXIF, aplana la
                              transparencia sobre blanco, ajusta al tamaño,
                              autoniveles al 1 %, tramado, empaqueta

No importa pyserial ni abre ningún puerto. Pillow se importa solo al
convertir, así que el camino sin conversión no lo necesita.
"""
import re
from pathlib import Path

FITS = ("contener", "cubrir")
DITHERS = ("fs", "umbral")
# P4, ancho y alto (con comentarios entre campos) y un solo espacio antes de los datos
PBM_HEADER = re.compile(rb"P4(?:\s|#[^\n]*\n)+(\d+)(?:\s|#[^\n]*\n)+(\d+)\s")


class ImageError(ValueError):
    """Mensaje en español, listo para mostrar a la persona."""


def expected_bytes(w, h):
    return (w + 7) // 8 * h


def read_raw(path, w, h):
    """.bin o .pbm (P4) que ya miden w x h -> bytes con 1 = blanco."""
    path = Path(path)
    data = path.read_bytes()
    ext = path.suffix.lower()
    if ext == ".bin":
        bits = data
    elif ext == ".pbm":
        m = PBM_HEADER.match(data)
        if not m:
            raise ImageError(f"{path.name}: solo PBM binario (P4)")
        if (int(m[1]), int(m[2])) != (w, h):
            raise ImageError(
                f"{path.name} mide {int(m[1])}x{int(m[2])}; "
                f"el badge espera {w}x{h}")
        bits = bytes(b ^ 0xFF for b in data[m.end():])  # PBM: 1 = negro
    else:
        raise ImageError(f"{path.name}: no sé leer '{ext}' sin convertir")
    want = expected_bytes(w, h)
    if len(bits) != want:
        raise ImageError(
            f"{path.name} mide {len(bits)} B; el badge espera {want} B ({w}x{h})")
    return bits


def prepare_image(path, width, height, fit="contener", dither="fs",
                  threshold=128, invert=False, enlarge=False):
    """Convierte la imagen de `path` a width x height, 1 bpp, 1 = blanco."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ImageError(
            "Para convertir imágenes falta Pillow: "
            "pip install -r tools/requirements.txt "
            "(o usa un .pbm/.bin que ya mida el tamaño exacto)") from None
    if fit not in FITS:
        raise ImageError(f"ajuste '{fit}' desconocido; usa {' o '.join(FITS)}")
    if dither not in DITHERS:
        raise ImageError(f"tramado '{dither}' desconocido; usa {' o '.join(DITHERS)}")
    if not 0 <= threshold <= 255:
        raise ImageError("el umbral va de 0 a 255")

    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise ImageError(f"{Path(path).name}: no pude leer la imagen ({e})") from e
    flat = Image.new("RGBA", im.size, "white")  # la transparencia queda blanca
    flat.alpha_composite(im)
    img = flat.convert("L")

    resample = Image.Resampling.LANCZOS
    inside = img.width <= width and img.height <= height
    covers = img.width >= width and img.height >= height
    if fit == "cubrir" and (enlarge or covers):
        img = ImageOps.fit(img, (width, height), resample)
    elif enlarge or not inside:  # una imagen más chica que el destino no se amplía
        img = ImageOps.contain(img, (width, height), resample)
    img = ImageOps.autocontrast(img, cutoff=1)  # como el configurador web

    canvas = Image.new("L", (width, height), 255)
    canvas.paste(img, ((width - img.width) // 2, (height - img.height) // 2))
    if invert:
        canvas = ImageOps.invert(canvas)
    if dither == "umbral":
        canvas = canvas.point(lambda p: 255 if p >= threshold else 0)
    bw = canvas.convert("1", dither=Image.Dither.FLOYDSTEINBERG
                        if dither == "fs" else Image.Dither.NONE)
    return bw.tobytes()  # en modo "1" de Pillow, 1 = blanco, igual que el badge


def load_for_badge(path, width, height, **options):
    """Bytes del badge para cualquier archivo de imagen; `options` va a prepare_image."""
    ext = Path(path).suffix.lower()
    if ext == ".bin":
        return read_raw(path, width, height)
    if ext == ".pbm":
        try:
            return read_raw(path, width, height)
        except ImageError:
            pass  # otro tamaño: se convierte como cualquier imagen
    return prepare_image(path, width, height, **options)
