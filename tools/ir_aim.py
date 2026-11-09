#!/usr/bin/env python3
"""
ir_aim.py — Mide el intercambio de estampas entre dos badges por USB en una
postura (distancia, ángulo, cómo se sostienen): uno busca (`ir send`) y el
otro contesta con la recepción activa (`ir port 1`, o Infrarrojo › Recibir
a mano si no está conectado). Imprime aciertos al primer intento y la
duración de cada intercambio.

Uso (con el venv del proyecto):
  ./tools/ir_aim.py /dev/ttyACM0 /dev/ttyACM1 -n 50 --label "puntas, 20 cm"
  ./tools/ir_aim.py /dev/ttyACM0 -n 20   # el otro en Recibir, sin USB
"""
import argparse
import re
import statistics
import time

import serial

from ui_shot import command

STAT = re.compile(r"sesiones_ok=(\d+) fallidas=(\d+)")
LAST = re.compile(r"ultimo=(\w+) (\d+)ms")


def status(port):
    text = ""
    while not (STAT.search(text) and LAST.search(text)):  # Sin logs a medias
        text = command(port, "ir", until="IRCOPA")
    ok, failed = map(int, STAT.search(text).groups())
    result, ms = LAST.search(text).groups()
    return ok + failed, result, int(ms)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("sender")
    ap.add_argument("receiver", nargs="?", help="omitir si está en Recibir")
    ap.add_argument("-n", type=int, default=20, help="intercambios")
    ap.add_argument("--label", default="", help="postura, para el registro")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    tx = serial.Serial(args.sender, 115200, timeout=0.2)
    rx = args.receiver and serial.Serial(args.receiver, 115200, timeout=0.2)
    time.sleep(0.4)  # La consola descarta los primeros 200 ms
    times, failures = [], {}
    for i in range(args.n):
        if rx:
            command(rx, "ir port 1")
        before, _, _ = status(tx)
        command(tx, "ir send")
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            done, result, ms = status(tx)
            if done > before:
                break
            time.sleep(0.3)
        else:
            result, ms = "sin_respuesta", 0
        if result == "ok":
            times.append(ms)
        else:
            failures[result] = failures.get(result, 0) + 1
        print(f"{i + 1:3d} {result} {ms} ms", flush=True)
        time.sleep(1.0)  # LINGER_MS: los dos vuelven a escuchar
    if rx:
        command(rx, "ir port 0")
    ok = len(times)
    summary = f"{args.label}: ok={ok}/{args.n} ({100 * ok / args.n:.0f} %)"
    if times:
        summary += f" mediana={statistics.median(times):.0f} ms max={max(times)} ms"
    if failures:
        summary += " fallas=" + ",".join(f"{k}:{v}" for k, v in failures.items())
    print(summary)


if __name__ == "__main__":
    main()
