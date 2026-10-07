#!/usr/bin/env python3
"""
ui_shot.py — Captura la pantalla de la UI del badge por la consola serie
(`ui shot`) y la guarda como PNG: tinta negra sobre blanco, como en la
e-paper, sin importar la pantalla real (en la OLED el framebuffer está
invertido y el firmware ya lo corrige).

Con --keys se presionan botones antes de capturar (`key <botón>`, el mismo
camino que un botón real), para llegar a una pantalla sin tocar el badge.

Requiere pyserial. Uso:
  ./tools/ui_shot.py                              # captura.png
  ./tools/ui_shot.py -o menu.png --keys "a right" # abre el menú y avanza
  ./tools/ui_shot.py -p /dev/ttyACM1 --scale 2
"""
import argparse
import struct
import sys
import time
import zlib

import serial

OPEN_WAIT_S = 0.3  # La consola descarta lo que llega en los primeros 200 ms
KEY_WAIT_S = 0.3  # Un cuadro en la OLED tarda ~41 ms; la e-paper, más


def command(port, text, until="OK", timeout=5):
    port.reset_input_buffer()
    port.write((text + "\n").encode())
    out = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        out += port.read(4096)
        if f"\n{until}".encode() in out or out.startswith(until.encode()):
            break
    return out.decode(errors="replace")


def parse_shot(text):
    lines = [l.strip() for l in text.splitlines()]
    start = next(i for i, l in enumerate(lines) if l.startswith("SHOT "))
    width, height = map(int, lines[start].split()[1:3])
    rows = []
    for line in lines[start + 1:start + 1 + height]:
        data = bytes.fromhex(line)
        rows.append([(data[x // 8] >> (7 - x % 8)) & 1 for x in range(width)])
    if len(rows) != height:
        raise ValueError(f"se esperaban {height} filas y llegaron {len(rows)}")
    return width, height, rows


def write_png(path, width, height, rows, scale):
    raw = b""
    for row in rows:
        line = bytes(0 if ink else 255 for ink in row for _ in range(scale))
        raw += (b"\x00" + line) * scale

    def chunk(kind, data):
        body = kind + data
        return (struct.pack(">I", len(data)) + body +
                struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width * scale, height * scale, 8, 0, 0,
                         0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) +
                chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("-p", "--port", default="/dev/ttyACM0")
    parser.add_argument("-o", "--output", default="captura.png")
    parser.add_argument("-k", "--keys", default="",
                        help='botones antes de capturar, p. ej. "a right"')
    parser.add_argument("--scale", type=int, default=4)
    args = parser.parse_args()

    # Apertura normal: fijar DTR/RTS en bajo antes de abrir reinicia el
    # ESP32-S3 (lo mismo que hace esptool).
    port = serial.Serial(args.port, 115200, timeout=0.1)
    time.sleep(OPEN_WAIT_S)
    for key in args.keys.split():
        reply = command(port, f"key {key}")
        if "OK" not in reply:
            sys.exit(f"key {key}: {reply.strip()}")
        time.sleep(KEY_WAIT_S)
    try:
        width, height, rows = parse_shot(command(port, "ui shot"))
    except (StopIteration, ValueError) as error:
        sys.exit(f"no llegó la captura: {error or 'sin SHOT'}")
    write_png(args.output, width, height, rows, args.scale)
    print(f"{args.output}: {width}x{height}")


if __name__ == "__main__":
    main()
