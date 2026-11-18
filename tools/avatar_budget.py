#!/usr/bin/env python3
"""Cuánto tarda un avatar en viajar por IR (BugBeam) con distintas codificaciones.

Pasa cada imagen por el mismo flujo que el configurador con sus ajustes por
omisión (recorte cuadrado centrado, gris Rec. 709, Floyd-Steinberg o umbral 128;
1 = blanco), y mide a 96, 64 y 48 px (64 y 48 se reducen desde el 96×96 de 1 bpp
que tiene el badge emisor: promedio por área y otro Floyd-Steinberg):

  - % de unos de la imagen,
  - bytes con PackBits y con zlib (zlib solo como cota de un LZ pequeño),
  - tiempo en el aire de un sentido armando las tramas reales de BugBeam
    (cabecera, payload, CRC-16) más TX_GAP_MS por trama, sin y con polaridad por
    trama (cada trozo va tal cual o invertido, el que tenga menos unos).

Uso: avatar_budget.py [imagen o carpeta ...] [-v]
Sin argumentos usa las fotos de cuenta del sistema y los logos de las villas.
"""
import argparse
import statistics
import sys
import zlib
from pathlib import Path

from PIL import Image

# cfg::ir (badge_config.h) e ir_frame.h
LEADER_US = 2400 + 1200
MARK_US = 350
ZERO_US, ONE_US = 400, 1100
MAX_PAYLOAD = 96
TX_GAP_MS = 20
AVDATA_TYPE = 12
HEAD = bytes([0xA5, 0x5A, 0x3C, 0xC3])  # sid, rid: 50 % de unos
CHUNK = MAX_PAYLOAD - len(HEAD) - 3     # - idx - ack(2) = 89 B
FIXED_S = 1.45 + 1.0                    # estampa + HELLO alineado (estimado)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES = [Path("/usr/share/pixmaps/faces"), ROOT / "firmware/art/villas"]


def crc16(data, crc=0xFFFF):
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def frame_us(payload, seq=0):
    body = bytes([1 << 4 | AVDATA_TYPE, seq & 0xFF, len(payload)]) + payload
    crc = crc16(body)
    raw = body + bytes([crc >> 8, crc & 0xFF])
    ones = sum(bin(b).count("1") for b in raw)
    zeros = 8 * len(raw) - ones
    return LEADER_US + ones * (MARK_US + ONE_US) + zeros * (MARK_US + ZERO_US) + MARK_US


def ones_of(data):
    return sum(bin(b).count("1") for b in data)


def one_way_s(data, polarity):
    """Segundos de un sentido: tramas AVDATA con `data` partido en trozos."""
    total_us = 0
    chunks = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)]
    for i, c in enumerate(chunks):
        idx = i
        if polarity and 2 * ones_of(c) > 8 * len(c):
            c = bytes(b ^ 0xFF for b in c)
            idx |= 0x40
        ack = (1 << i) - 1  # el otro confirma lo que llevaba
        total_us += frame_us(HEAD + bytes([idx, ack >> 8, ack & 0xFF]) + c, i)
    return total_us / 1e6 + len(chunks) * TX_GAP_MS / 1000, len(chunks)


def packbits(data):
    out, i, n = bytearray(), 0, len(data)
    while i < n:
        j = i
        while j + 1 < n and data[j + 1] == data[i] and j - i < 127:
            j += 1
        if j > i:  # corrida de 2..128
            out += bytes([257 - (j - i + 1), data[i]])
            i = j + 1
            continue
        j = i
        while j < n and j - i < 128 and not (j + 1 < n and data[j + 1] == data[j]):
            j += 1
        j = max(j, i + 1)
        out += bytes([j - i - 1]) + data[i:j]
        i = j
    return bytes(out)


def unpackbits(data):
    out, i = bytearray(), 0
    while i < len(data):
        h = data[i]
        if h < 128:
            out += data[i + 1:i + 2 + h]
            i += 2 + h
        elif h > 128:
            out += data[i + 1:i + 2] * (257 - h)
            i += 2
        else:
            i += 1
    return bytes(out)


def to_bits(path, mode, side=96):
    img = Image.open(path)
    img = img.convert("RGBA")
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))  # lo transparente queda blanco
    img = Image.alpha_composite(bg, img).convert("RGB")
    s = min(img.size)
    x0, y0 = (img.width - s) // 2, (img.height - s) // 2
    img = img.crop((x0, y0, x0 + s, y0 + s)).resize((side, side), Image.LANCZOS)
    g = [0.2126 * r + 0.7152 * gg + 0.0722 * b for r, gg, b in zip(*[iter(img.tobytes())] * 3)]
    return [1 if v >= 128 else 0 for v in g] if mode == "umbral" else fs(g, side)


def fs(g, side):
    """Floyd-Steinberg 7/16 3/16 5/16 1/16 a 128, como el configurador."""
    bits = [0] * (side * side)
    for y in range(side):
        for x in range(side):
            i = y * side + x
            on = 1 if g[i] >= 128 else 0
            bits[i] = on
            err = g[i] - (255 if on else 0)
            if x + 1 < side:
                g[i + 1] += err * 7 / 16
            if y + 1 < side:
                if x > 0:
                    g[i + side - 1] += err * 3 / 16
                g[i + side] += err * 5 / 16
                if x + 1 < side:
                    g[i + side + 1] += err / 16
    return bits


def reduce(bits, side):
    """Lo que haría el emisor: promedio por área del 96×96 de 1 bpp y otro tramado.
    (Reducir por mayoría, como card_face::drawAvatar, borra los grises del tramado.)"""
    im = Image.new("L", (96, 96))
    im.frombytes(bytes(255 * b for b in bits))
    return fs(list(im.resize((side, side), Image.BOX).tobytes()), side)


def pack(bits, side):
    row = (side + 7) >> 3
    out = bytearray(row * side)
    for i, b in enumerate(bits):
        if b:
            y, x = divmod(i, side)
            out[y * row + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(out)


def measure(data):
    pb, zl = packbits(data), zlib.compress(data, 9)[2:-4]  # deflate crudo
    assert unpackbits(pb) == data
    row = {"ones": 100 * ones_of(data) / (8 * len(data)), "pb_b": len(pb), "zl_b": len(zl)}
    for key, payload, pol in (("raw", data, False), ("pol", data, True),
                              ("pb", pb, True), ("zl", zl, True)):
        row[key], row[key + "_n"] = one_way_s(payload, pol)
    return row


def images(args):
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    for p in map(Path, args or DEFAULT_SOURCES):
        if p.is_dir():
            files = sorted(f for f in p.rglob("*") if f.suffix.lower() in exts)
            if p.name == "villas":  # el 24 px es el mismo logo
                files = [f for f in files if f.stem.endswith("_96")]
            yield from files
        else:
            yield p


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(q * (len(xs) - 1)))]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("-v", action="store_true", help="una línea por imagen")
    a = ap.parse_args()

    # comprobaciones: el tiempo de §3.1 y PackBits de ida y vuelta
    full = lambda v: (LEADER_US + 8 * (MAX_PAYLOAD + 5) * (MARK_US + v) + MARK_US) / 1e6
    assert abs(full(ZERO_US) - 0.61) < 0.01 and abs(full(ONE_US) - 1.18) < 0.01
    for t in (b"", b"\x00" * 300, bytes(range(256)), b"\xff\x00" * 70 + b"\x11" * 129):
        assert unpackbits(packbits(t)) == t

    files = list(images(a.paths))
    if not files:
        sys.exit("sin imágenes")
    res = {}  # (modo, lado) -> [fila]
    for f in files:
        for mode in ("fs", "umbral"):
            b96 = to_bits(f, mode)
            for side in (96, 64, 48):
                bits = b96 if side == 96 else reduce(b96, side)
                r = measure(pack(bits, side))
                r["name"] = f.name
                res.setdefault((mode, side), []).append(r)
                if a.v:
                    print(f"{mode:6} {side:2} {f.name:32} unos={r['ones']:5.1f}% "
                          f"pb={r['pb_b']:4} zl={r['zl_b']:4} raw={r['raw']:5.2f}s "
                          f"pol={r['pol']:5.2f}s pb={r['pb']:5.2f}s zl={r['zl']:5.2f}s")

    print(f"{len(files)} imágenes. Segundos de UN sentido (tramas AVDATA + {TX_GAP_MS} ms por trama),"
          " sin pérdidas. p50 / p95 / máx.\n")
    for (mode, side), rows in sorted(res.items(), key=lambda kv: (kv[0][0], -kv[0][1])):
        raw_b = len(pack([0] * side * side, side))
        print(f"### {'Floyd-Steinberg' if mode == 'fs' else 'Umbral 128'} — {side}×{side} ({raw_b} B)\n")
        print("| Medida | p50 | p95 | máx |\n|---|---|---|---|")
        for key, label in (("ones", "% de unos"), ("pb_b", "Bytes PackBits"), ("zl_b", "Bytes zlib"),
                           ("raw", "s crudo"), ("pol", "s crudo + polaridad"),
                           ("pb", "s PackBits + polaridad"), ("zl", "s zlib + polaridad")):
            xs = [r[key] for r in rows]
            fmt = "{:.0f}" if key.endswith("_b") else "{:.1f}" if key == "ones" else "{:.2f}"
            print(f"| {label} | " + " | ".join(fmt.format(v) for v in
                  (statistics.median(xs), pct(xs, 0.95), max(xs))) + " |")
        for key in ("pol", "pb", "zl"):
            p95 = pct([r[key] for r in rows], 0.95)
            worst = max(rows, key=lambda r: r[key])
            print(f"\n- {key}: ida y vuelta p95 = {2 * p95:.1f} s; con estampa y HELLO ≈ "
                  f"{2 * p95 + FIXED_S:.1f} s; con 15 % de pérdida ≈ {2 * p95 / 0.85 + FIXED_S:.1f} s"
                  f" (peor: {worst['name']}, {worst[key + '_n']} tramas)")
        print()


if __name__ == "__main__":
    main()
