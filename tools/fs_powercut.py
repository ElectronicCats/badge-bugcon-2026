#!/usr/bin/env python3
"""
fs_powercut.py — Reinicia el badge en momentos aleatorios mientras escribe y
verifica que el almacenamiento sobreviva (criterio de F2: 200 cortes sin
corrupción).

Cada ciclo: `fs check` (el registro de prueba está completo y su seq no
retrocede), `fs stress` y, tras una espera aleatoria, un reinicio por la línea
RTS del USB (como hace esptool). Solo prueba LittleFS: NVS no sobrevivió a
esta prueba (sesión 8) y queda para datos que se escriben una vez.

Limitación: el reinicio corta al ESP32-S3 pero no al flash, así que una
operación de escritura o borrado ya iniciada termina. Para cortes reales,
desconectar el USB (o SW1 con pilas) durante `fs stress` y correr `fs check`.

Con --album prueba el alta en el álbum (F5.8) en lugar del registro de
prueba: `album clear` + `album fill <base>` (un álbum grande: cada alta
reescribe ~24-38 KB en 0.5-0.8 s) y en cada ciclo `album stress`, que agrega
estampas una a una e imprime "saved=<n>" tras cada guardado completo. Tras el
corte, `album check` debe pasar (el álbum cargó, cada entrada es la esperada,
sin repetidas) y el álbum debe tener al menos las n estampas del último
"saved=" que llegó: un alta confirmada no se pierde. Al acercarse a la
capacidad vuelve a empezar desde <base>.

Si el host deshabilita el puerto USB por tantos reinicios ("disabled by hub
(EMI?)" en dmesg), reconectar el badge y seguir con --resume: el primer ciclo
verifica el registro que dejó el último corte en lugar de borrarlo.

Requiere pyserial. Uso:
  ./tools/fs_powercut.py                  # 200 ciclos en /dev/ttyACM0
  ./tools/fs_powercut.py -n 20 -p /dev/ttyACM1
  ./tools/fs_powercut.py -n 176 --resume  # tras reconectar
  ./tools/fs_powercut.py --album -n 200   # cortes durante el alta (F5.8)
"""
import argparse
import random
import re
import sys
import time

import serial

BOOT_WAIT_S = 0.6  # La consola descarta lo que llega en los primeros 200 ms
PORT_TIMEOUT_S = 30
RESET_PAUSE_S = 1.5  # Entre reinicios: da tiempo al host de enumerar


def open_port(name):
    deadline = time.time() + PORT_TIMEOUT_S
    while True:
        try:
            port = serial.Serial(name, 115200, timeout=0.1)
            break
        except serial.SerialException:
            if time.time() > deadline:
                sys.exit(f"{name} no apareció en {PORT_TIMEOUT_S} s: reconecta "
                         "el badge y sigue con --resume")
            time.sleep(0.2)
    time.sleep(BOOT_WAIT_S)
    port.reset_input_buffer()
    return port


def command(port, text, until, timeout=10):
    port.write((text + "\n").encode())
    out = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        out += port.read(1024)
        if until.encode() in out:
            time.sleep(0.05)
            out += port.read(1024)
            break
    return out.decode(errors="replace")


def reset(port):
    port.dtr = False
    port.rts = True
    time.sleep(0.1)
    port.rts = False
    port.close()
    time.sleep(RESET_PAUSE_S)  # El USB CDC se vuelve a enumerar


def album_check(port):
    """-> (count, cap, salida) de `album check`, o None si falló."""
    out = command(port, "album check", "RESULT album")
    match = re.search(r"RESULT album PASS .*count=(\d+) cap=(\d+)", out)
    if not match:
        print(out.strip())
        return None
    return int(match.group(1)), int(match.group(2)), out


def album_refill(port, base):
    out = command(port, "album clear", "OK")
    out += command(port, f"album fill {base}", "added=", timeout=30)
    match = re.search(r"OK added=\d+ full=\d+ count=(\d+)", out)
    if not match:
        sys.exit(f"no se pudo llenar el álbum:\n{out}")
    return int(match.group(1))


def run_album(args):
    """Cortes durante el alta del álbum; devuelve el código de salida."""
    port = open_port(args.port)
    confirmed = 0  # Estampas que el badge dijo haber guardado
    if not args.resume:
        confirmed = album_refill(port, args.base)
    saves = 0
    max_save_ms = 0
    for cycle in range(1, args.cycles + 1):
        checked = album_check(port)
        if checked is None:
            print(f"ciclo {cycle}: FALLO en album check")
            return 1
        count, cap, out = checked
        if count < confirmed:
            print(f"ciclo {cycle}: se perdió un alta confirmada "
                  f"({count} < {confirmed})\n{out.strip()}")
            return 1
        print(f"ciclo {cycle:3d}: count={count} (confirmadas {confirmed})",
              flush=True)
        confirmed = count
        if count >= cap - 5:
            confirmed = album_refill(port, args.base)
        command(port, "album stress", "OK guardando")
        deadline = time.time() + random.uniform(args.min_ms, args.max_ms) / 1000
        out = b""
        while time.time() < deadline:
            out += port.read(256)
        out += port.read(256)
        lines = re.findall(rb"saved=(\d+) #\d+ (\d+)ms", out)
        if lines:
            confirmed = max(confirmed, int(lines[-1][0]))
            saves += len(lines)
            max_save_ms = max(max_save_ms, *(int(ms) for _, ms in lines))
        if b"RESULT album" in out:
            print(f"ciclo {cycle}: stress terminó antes del corte\n"
                  f"{out.decode(errors='replace')}")
            return 1
        reset(port)
        port = open_port(args.port)

    checked = album_check(port)
    ok = checked is not None and checked[0] >= confirmed
    if checked is not None:
        print(checked[2].strip())
    print(f"{args.cycles} reinicios durante el alta ({saves} altas "
          f"confirmadas, peor guardado {max_save_ms} ms): "
          f"{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("-p", "--port", default="/dev/ttyACM0")
    parser.add_argument("-n", "--cycles", type=int, default=200)
    parser.add_argument("--min-ms", type=int, default=20)
    parser.add_argument("--max-ms", type=int, default=1500)
    parser.add_argument("--resume", action="store_true",
                        help="no borra el registro: el ciclo 1 lo verifica")
    parser.add_argument("--album", action="store_true",
                        help="cortes durante el alta del álbum (F5.8)")
    parser.add_argument("--base", type=int, default=300,
                        help="--album: dorsales 1..base al empezar (300)")
    args = parser.parse_args()
    if args.album:
        return run_album(args)

    port = open_port(args.port)
    if not args.resume:
        command(port, "fs clean", "OK")
    last_seq = 0
    for cycle in range(1, args.cycles + 1):
        if cycle > 1 or args.resume:
            out = command(port, "fs check", "RESULT fs")
            match = re.search(r"RESULT fs (PASS|FAIL) (.*)", out)
            seq = re.search(r"seq=(\d+)", out)
            if not match or match.group(1) != "PASS" or not seq:
                print(f"ciclo {cycle}: FALLO\n{out}")
                return 1
            if int(seq.group(1)) < last_seq:
                print(f"ciclo {cycle}: seq retrocedió ({seq.group(1)} < {last_seq})")
                return 1
            last_seq = int(seq.group(1))
            print(f"ciclo {cycle:3d}: {match.group(2).strip()}", flush=True)
        command(port, "fs stress", "OK guardando")
        time.sleep(random.uniform(args.min_ms, args.max_ms) / 1000)
        reset(port)
        port = open_port(args.port)

    out = command(port, "fs check", "RESULT fs")
    print(out.strip())
    command(port, "fs clean", "OK")
    ok = "RESULT fs PASS" in out
    print(f"{args.cycles} reinicios durante escrituras: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
