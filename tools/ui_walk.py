#!/usr/bin/env python3
"""
ui_walk.py — Recorre las pantallas del badge con `key` y guarda una captura
de cada una (`ui shot`): la línea base visual para detectar
regresiones. Antes de cada pantalla regresa al gafete con B sostenido.

Sin --only empieza con un RESET (RTS) y captura el arranque: bienvenida y
lo que sigue ("Presiona cualquier botón" solo en badges sin Debut). Con
--debut sigue el primer contacto (A3–A5): un botón, el aviso y su cierre.

Requiere pyserial. Uso:
  ./tools/ui_walk.py -p /dev/ttyACM3 -o /tmp/ui_base
  ./tools/ui_walk.py -p /dev/ttyACM3 -o /tmp/x --only menu,album
"""
import argparse
import os
import sys
import time

import serial

from badge_usb import restore_vmin
from ui_shot import command, parse_shot, write_png, OPEN_WAIT_S

# Casillas del menú 3×3 (0..8, ←→ avanzan de a uno y dan la vuelta; A entra):
# Mi Estampa, Álbum, Infrarrojo / Juegos, Herramientas, Retos / Ajustes,
# Agenda, Acerca de. El menú recuerda la casilla elegida (tras un reset es 0).
MENU = [("estampa", ""), ("album", ""), ("infrarrojo", ""), ("juegos", ""),
        ("herramientas", ""), ("retos", ""), ("ajustes", ""), ("agenda", ""),
        ("acerca_de", "")]
# (nombre, casilla del menú o botones sueltos)
SCREENS = [("gafete", None), ("luces", "right"), ("menu", -1)] + [
    (name, i) for i, (name, _) in enumerate(MENU)
] + [("estampa_editar", "estampa")]
TAP_WAIT_S = 0.35  # Entre botones
SETTLE_S = 1.8  # Tras el último: el cuadro sale cuando termina el refresco


def route(sel, target):
    """Botones para ir de la casilla `sel` a `target` por el camino corto."""
    delta = (target - sel) % 9
    return ["right"] * delta if delta <= 4 else ["left"] * (9 - delta)


def press(port, step):
    if step.endswith("!"):
        reply = command(port, f"key {step[:-1]} 900")
    else:
        reply = command(port, f"key {step}")
    if "OK" not in reply:
        sys.exit(f"key {step}: {reply.strip()}")


def shot(port, path, scale):
    width, height, rows = parse_shot(command(port, "ui shot"))
    write_png(path, width, height, rows, scale)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("-p", "--port", default="/dev/ttyACM0")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--only", default="", help="nombres separados por coma")
    parser.add_argument("--debut", action="store_true",
                        help="badge sin Debut: captura el primer contacto")
    parser.add_argument("--scale", type=int, default=2)
    args = parser.parse_args()
    only = set(filter(None, args.only.split(",")))
    os.makedirs(args.output, exist_ok=True)

    port = serial.Serial(args.port, 115200, timeout=0.1)
    time.sleep(OPEN_WAIT_S)
    if not only:  # Arranque: la bienvenida y lo que sigue
        port.dtr = False  # Sin esto el pulso de RTS no reinicia
        port.rts = True
        time.sleep(0.1)
        port.rts = False
        start = time.time()
        for i, at in enumerate((0.8, 1.6, 2.6, 3.6, 5.0)):
            time.sleep(max(0, start + at - time.time()))
            shot(port, f"{args.output}/arranque_{i + 1}.png", args.scale)
    if args.debut:
        for name in ("debut_aviso", "debut_luces"):
            press(port, "a")
            time.sleep(SETTLE_S)
            shot(port, f"{args.output}/{name}.png", args.scale)
    sel = 0
    for i, (name, what) in enumerate(SCREENS):
        if only and name not in only:
            continue
        press(port, "b!")
        time.sleep(SETTLE_S)
        if what is None:
            keys = []
        elif isinstance(what, str) and what != "estampa":
            keys = [what]
        else:  # Menú: casilla (-1 = solo abrirlo); "estampa" = Editar
            target = sel if what == -1 else 0 if what == "estampa" else what
            keys = ["a"] + route(sel, target) + (
                [] if what == -1 else ["a"] + (["a"] if what == "estampa" else []))
            sel = target
        for key in keys:
            press(port, key)
            time.sleep(TAP_WAIT_S)
        time.sleep(SETTLE_S)
        path = f"{args.output}/{i:02d}_{name}.png"
        shot(port, path, args.scale)
        print(path)
    press(port, "b!")
    restore_vmin(port)
    port.close()


if __name__ == "__main__":
    main()
