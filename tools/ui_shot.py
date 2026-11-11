#!/usr/bin/env python3
"""
ui_shot.py — Captura la pantalla de la UI del badge por la consola serie
(`ui shot`) y la guarda como PNG: tinta negra sobre blanco, como en la
e-paper. Es el último cuadro dibujado, que puede ir adelante del panel
mientras refresca.

Con --keys se presionan botones antes de capturar (`key <botón>`, el mismo
camino que un botón real), para llegar a una pantalla sin tocar el badge.

Requiere pyserial y Rich. Sin -p busca el badge solo. Códigos de salida:
0 bien · 1 el badge rechazó el botón o no mandó la captura · 2 uso ·
3 conexión. Uso:
  ./tools/ui_shot.py                              # captura.png
  ./tools/ui_shot.py -o menu.png --keys "a right" # abre el menú y avanza
  ./tools/ui_shot.py -p /dev/ttyACM1 --scale 2
"""
import argparse
import struct
import sys
import time
import zlib

OPEN_WAIT_S = 0.3  # La consola descarta lo que llega en los primeros 200 ms
KEY_WAIT_S = 0.3  # Entre botones: la app ya cambió su estado
# Tras el último botón: el cuadro nuevo se dibuja cuando termina el refresco
# en curso (parcial 0.64 s, completo 1.52 s en el DevKit).
SHOT_WAIT_S = 1.6
KEYS = ("up", "down", "left", "right", "a", "b")  # Botones de `key`


def command(port, text, until="OK", timeout=5):
    port.reset_input_buffer()
    port.write((text + "\n").encode())
    out = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        out += port.read(4096)
        # Un ERR también cierra la espera: el llamador lee el motivo
        if any(f"\n{w}".encode() in out or out.startswith(w.encode())
               for w in (until, "ERR")):
            break
    else:
        seen = out.decode(errors="replace").strip()
        raise TimeoutError(f"sin respuesta a '{text}'" +
                           (f": {seen[-200:]}" if seen else ""))
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
    parser.add_argument("-p", "--port",
                        help="por omisión, el badge que encuentre")
    parser.add_argument("-o", "--output", default="captura.png")
    parser.add_argument("-k", "--keys", default="",
                        help='botones antes de capturar, p. ej. "a right"')
    parser.add_argument("--scale", type=int, default=4)
    args = parser.parse_args()
    keys = args.keys.split()
    unknown = [k for k in keys if k not in KEYS]
    if unknown:
        parser.error(f"botón desconocido: {' '.join(unknown)} "
                     f"(usa {' '.join(KEYS)})")

    import badge_link
    console = badge_link.console()
    try:
        # Apertura normal, sin tocar DTR/RTS: fijarlos en bajo antes de abrir
        # reinicia el ESP32-S3. Al salir, el gestor deja el tty en VMIN=1.
        with badge_link.connect(args.port) as badge:
            port = badge.port
            for key in keys:
                reply = command(port, f"key {key}")
                if "OK" not in reply:
                    raise badge_link.ProtocolError(f"key {key}: {reply.strip()}")
                time.sleep(KEY_WAIT_S)
            if keys:
                time.sleep(SHOT_WAIT_S)
            try:
                width, height, rows = parse_shot(command(port, "ui shot"))
            except (StopIteration, ValueError, IndexError) as error:
                raise badge_link.ProtocolError(
                    f"no llegó la captura: {error or 'sin SHOT'}") from None
        write_png(args.output, width, height, rows, args.scale)
    except (badge_link.BadgeConnectionError, badge_link.ProtocolError,
            OSError) as error:
        return badge_link.report(console, error)
    print(f"{args.output}: {width}x{height}")
    return badge_link.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
