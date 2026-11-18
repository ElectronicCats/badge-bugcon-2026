#!/usr/bin/env python3
"""
ir_len_sweep.py — Mide qué parte de las tramas BugBeam llega entre dos badges
según su largo, en la postura en que estén (distancia, ángulo). En cada
sentido, uno manda n tramas PING de B bytes (`irtx`) y el otro las cuenta
(`irrx`). Imprime una línea JSON por largo y sentido: tramas recibidas,
correctas, con CRC malo, perdidas (por el seq) y otras (formas rotas, como una
marca perdida).

Uso (con el venv del proyecto):
  ./tools/ir_len_sweep.py ACM0 ACM1 --label "puntas, 25 cm" -n 100
  ./tools/ir_len_sweep.py ACM0 ACM1 -l 16,48,96 --one-way

Los puertos son los de /dev/ttyACMn o /dev/serial/by-id/…. Con `--one-way`
solo se mide del primero al segundo.
"""
import argparse
import json
import re
import time

import serial

RESULT = re.compile(
    r"tramas=(\d+) beam=(\d+) crc=(\d+) perdidas=(\d+) otras=(\d+) glitches=(\d+)"
)


def open_console(path):
    s = serial.Serial(path, 115200, timeout=0.1)
    time.sleep(0.5)
    s.write(b"DBG\r\n")  # La consola de pruebas no contesta hasta recibirlo
    time.sleep(1)
    s.reset_input_buffer()
    return s


def read_until(s, seconds, pattern):
    end, out = time.time() + seconds, ""
    while time.time() < end:
        data = s.read(4096)
        if data:
            out += data.decode(errors="replace")
            if re.search(pattern, out):
                break
    return out


def measure(tx, rx, length, n, label, name):
    # Una trama de 96 B dura ≈ 0.9 s en el aire y irtx deja 0.25 s entre tramas.
    seconds = int(n * (0.3 + 0.0095 * length + 0.1)) + 8
    rx.reset_input_buffer()
    tx.reset_input_buffer()
    rx.write(f"irrx {seconds}\r\n".encode())
    time.sleep(0.5)
    tx.write(f"irtx {n} {length}\r\n".encode())
    out = read_until(rx, seconds + 10, r"RESULT irrx")
    read_until(tx, 2, r"RESULT irtx")
    row = {"label": label, "dir": name, "bytes": length, "sent": n}
    m = RESULT.search(out)
    if m:
        keys = ("rx", "ok", "crc", "lost", "other", "glitches")
        row.update(zip(keys, map(int, m.groups())))
    else:
        row["error"] = out[-200:]
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("first")
    ap.add_argument("second")
    ap.add_argument("-n", type=int, default=60, help="tramas por largo")
    ap.add_argument("-l", "--lengths", default="16,32,48,64,80,96")
    ap.add_argument("--label", default="")
    ap.add_argument("--one-way", action="store_true")
    args = ap.parse_args()

    a, b = open_console(args.first), open_console(args.second)
    legs = [(a, b, "1>2")] + ([] if args.one_way else [(b, a, "2>1")])
    for tx, rx, name in legs:
        for length in map(int, args.lengths.split(",")):
            print(json.dumps(measure(tx, rx, length, args.n, args.label, name)),
                  flush=True)


if __name__ == "__main__":
    main()
