#!/usr/bin/env python3
"""
provision.py — Línea de producción: flashea un badge,
le asigna su dorsal y su K_dev, corre la QA (app qa) y lo registra en
el CSV (MAC ↔ dorsal ↔ resultado).

Pasos, con un badge conectado por USB:
  1. Lee la MAC con esptool.
  2. Dorsal: el que ya tenga esa MAC en el CSV o el menor libre de 1..400
     (--no lo fija; --villa V da MASTER_FIRST + V). Se reserva en el CSV
     antes de seguir. El dorsal de un maestro lo comparte su repuesto (otra
     MAC); verify_album.py prueba todas.
  3. Graba el merged.bin hasta el final de la app (sin el relleno 0xFF: los
     8 MB completos tardan ~90 s) y borra la partición littlefs, así que el
     badge arranca en blanco: sin identidad (NVS), álbum, estampa ni récords.
     Con --vestidor DIR, en la misma pasada graba DIR/vestidor-NNN.bin (NNN =
     el dorsal) en la partición vestidor: los datos del reto N3 y el tiro de
     este badge (tools/challenges/generate.py, privado).
  4. Ya arrancado: K_dev = HMAC-SHA256(K_master, MAC || dorsal) se escribe
     con `id prov` (identity::provision(), el blob de NVS) y `id` confirma
     dorsal, id de la clave y MAC.
  5. `QA` y espera `RESULT qa PASS|FAIL …`; el operador sigue las
     instrucciones que se imprimen. Necesita el badge dorado (`QA GOLD`).
  6. Con --villa V (maestro de villa): con PASS, `CARD` deja en su estampa
     team = V, el nombre de la villa como nickname y de handle su pedazo del
     reto de villas (villa_shares[V] de DIR/secrets.json; --villa exige
     --vestidor DIR y sin secrets.json falla antes de grabar).
  7. Con PASS reinicia el badge (arranca en el gafete, sin la QA ni su hold
     de energía); con FAIL deja el FAIL en la pantalla para apartarlo. Los
     botones de la QA no dan "Debut" (services/specials).

CSV (un renglón por intento, se agrega; lo lee `verify_album.py --macs`):
  no,mac,fecha,puerto,resultado,segundos,detalle
  resultado = ASIGNADO (la reserva del paso 2), PASS, FAIL o ERROR; detalle =
  la línea final de la QA o el error. Vale el último renglón de cada MAC.
Varios puertos: una instancia por puerto con el mismo CSV (se bloquea al
escribirlo).

Uso (pyserial; esptool del core de Arduino o del PATH):
  ./tools/provision.py -p /dev/ttyACM0 --master HEX --vestidor DIR
  ./tools/provision.py -p /dev/ttyACM1 --master HEX --no 17 --no-flash
  ./tools/provision.py --master HEX --vestidor DIR --villa 3   # OT Village
  # DevKit con el puente IO18 -> IO17, que es probado y dorado a la vez:
  ./tools/provision.py --master HEX --before "ir carrier 0" --before "QA GOLD"
Sale con 0 solo con QA PASS.
"""
import argparse
import csv
import datetime
import fcntl
import glob
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time

import serial

import badge_usb
import identity

TOOLS = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BIN = os.path.join(TOOLS, "..", "firmware", "build",
                           "badge_bugcon_2026.ino.merged.bin")
ATTENDEES = 400  # cfg::album::ATTENDEES: dorsales con hueco en el álbum
MASTER_FIRST = 901  # cfg::villa::MASTER_FIRST: maestro de la villa v
# Nickname de cada maestro, en el orden de TEAMS[] (services/card.cpp); el
# nickname tiene 16 B de UTF-8 y "Live Hacking Villa" no cabe.
VILLA_NICKS = ["Hardware", "RF Village MX", "Rookie Village",
               "OT Village CDMX", "PaySec LATAM", "BugBounty", "WoSEC México",
               "APT", "Nación Hacker", "Live Hacking"]
CSV_FIELDS = ["no", "mac", "fecha", "puerto", "resultado", "segundos",
              "detalle"]
PARTITION_TABLE = 0x8000  # Tabla de particiones dentro del merged.bin
SECTOR = 0x1000
BOOT_TIMEOUT_S = 30
QA_TIMEOUT_S = 300  # Cada paso de la QA tiene su tiempo límite en el badge
ID_RE = re.compile(r"^ID prov=(\d) no=(\d+) key=([0-9A-F]{8}) "
                   r"mac=([0-9A-F:]{17}) ")


class Failure(Exception):
    pass


# --- Imagen -----------------------------------------------------------------
def partition(image, label):
    """(offset, tamaño) de la partición `label` de la tabla del merged.bin."""
    for at in range(PARTITION_TABLE, PARTITION_TABLE + 0xC00, 32):
        magic, _, _, offset, size, name = struct.unpack_from("<HBBII16s",
                                                             image, at)
        if magic != 0x50AA:
            break
        if name.rstrip(b"\0").decode() == label:
            return offset, size
    raise Failure(f"el merged.bin no tiene la partición {label}")


def trim(image):
    """El merged.bin sin el 0xFF final, en sectores completos."""
    data = image.rstrip(b"\xff")
    return data + b"\xff" * (-len(data) % SECTOR)


# --- CSV --------------------------------------------------------------------
def assign(rows, mac, wanted=None):
    """Dorsal para `mac`: `wanted`, el que ya tiene o el menor libre."""
    rows = [r for r in rows if r["no"].isdigit()]
    owner = {int(r["no"]): r["mac"] for r in rows}
    current = next((int(r["no"]) for r in reversed(rows) if r["mac"] == mac),
                   None)
    no = wanted or current or next(
        (n for n in range(1, ATTENDEES + 1) if n not in owner), None)
    if no is None:
        raise Failure(f"no quedan dorsales libres en 1..{ATTENDEES}")
    if not 1 <= no <= 0xFFFF:
        raise Failure(f"dorsal {no} fuera de 1..65535")
    if owner.get(no, mac) != mac and not is_master(no):
        raise Failure(f"el dorsal {no} ya es de {owner[no]}")
    return no


def is_master(no):
    return MASTER_FIRST <= no < MASTER_FIRST + len(VILLA_NICKS)


def log(path, row, pick=None):
    """Agrega `row` al CSV con el archivo bloqueado; con `pick`, el dorsal
    sale de pick(renglones) dentro del mismo bloqueo (dos puertos no toman
    el mismo)."""
    # ponytail: fcntl = solo Linux/macOS; en Windows, una instancia por CSV.
    with open(path, "a+", newline="") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        if pick:
            row["no"] = pick(list(csv.DictReader(f)))
        f.seek(0, os.SEEK_END)
        writer = csv.DictWriter(f, CSV_FIELDS)
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow(row)
    return row["no"]


# --- esptool ----------------------------------------------------------------
def find_esptool():
    """El del core de Arduino (el de arduino-cli upload) o el del PATH."""
    core = sorted(glob.glob(os.path.expanduser(
        "~/.arduino15/packages/esp32/tools/esptool_py/*/esptool")))
    found = core[-1] if core else shutil.which("esptool")
    if not found:
        raise SystemExit("no se encontró esptool (usa --esptool)")
    return found


# Comandos con guion bajo: los acepta esptool 4 y (obsoletos) esptool 5.
def esptool(args, *command):
    cmd = [args.esptool, "--chip", "esp32s3", "-p", args.port, "-b",
           "921600", *command]
    run = subprocess.run(cmd, capture_output=True, text=True)
    if run.returncode != 0:
        lines = (run.stdout + run.stderr).strip().splitlines() or ["?"]
        raise Failure(f"esptool: {lines[-1]}")
    return run.stdout


def read_mac(args):
    m = re.search(r"MAC:\s+([0-9a-f:]{17})", esptool(args, "read_mac"))
    if not m:
        raise Failure("esptool no dio la MAC")
    return m.group(1).upper()


def vestidor(folder, no, image):
    """(offset, ruta) de la imagen del vestidor del dorsal `no`."""
    path = os.path.join(folder, f"vestidor-{no:03d}.bin")
    if not os.path.isfile(path):
        raise Failure(f"no existe {path}")
    offset, size = partition(image, "vestidor")
    if os.path.getsize(path) > size:
        raise Failure(f"{path} no cabe en la partición vestidor ({size} B)")
    return offset, path


def flash(args, image_path, littlefs, vest=None):
    """Graba la imagen (y el vestidor: offset, ruta) y borra littlefs."""
    extra = [hex(vest[0]), vest[1]] if vest else []
    esptool(args, "--after", "no_reset", "write_flash", "0x0", image_path,
            *extra)
    esptool(args, "erase_region", hex(littlefs[0]), hex(littlefs[1]))


# --- Badge ------------------------------------------------------------------
def connect(port):
    """Espera a que el badge recién reiniciado conteste INFO."""
    deadline = time.time() + BOOT_TIMEOUT_S
    while True:
        try:
            badge = badge_usb.Badge(port)
        except (serial.SerialException, OSError):
            if time.time() > deadline:
                raise Failure(f"{port} no apareció tras el reinicio")
            time.sleep(0.5)
            continue
        try:  # Un puerto abierto antes de re-enumerar no contesta: reintenta
            badge.port.write(b"INFO\n")
            if badge.read_reply(2).startswith("OK BB26"):
                return badge
        except (badge_usb.ProtocolError, serial.SerialException, OSError):
            pass
        badge.close()
        if time.time() > deadline:
            raise Failure("el badge no contesta INFO")


def ask(badge, line, prefix, timeout=5):
    """Comando de consola que contesta una línea que empieza con prefix."""
    badge.port.reset_input_buffer()
    badge.port.write((line + "\n").encode())
    deadline = time.time() + timeout
    while True:
        reply = badge.read_line(max(0.01, deadline - time.time()))
        if reply.startswith(prefix) or reply.startswith("ERR"):
            return reply


def provision(badge, no, key, mac):
    badge.expect_ok(f"id prov {no} {key.hex()}")
    reply = ask(badge, "id", "ID ")
    m = ID_RE.match(reply)
    got = m and (m.group(1), int(m.group(2)), m.group(3), m.group(4))
    want = ("1", no, identity.key_id(key), mac)
    if got != want:
        raise Failure(f"`id` no coincide: {reply}")


def villa_share(folder, villa):
    """Pedazo (20 hex) del reto de villas de la villa `villa`."""
    path = os.path.join(folder, "secrets.json")
    try:
        with open(path) as f:
            share = json.load(f)["villa_shares"][villa]
    except (OSError, ValueError, KeyError, IndexError) as e:
        raise Failure(f"{path}: sin el pedazo de la villa {villa} ({e})")
    if not re.fullmatch(r"[0-9a-f]{20}", share):
        raise Failure(f"{path}: pedazo de la villa {villa} inválido: "
                      f"{share!r}")
    return share


def set_villa(badge, villa, handle):
    """Estampa del maestro: su villa, el nombre de la villa de nickname y su
    pedazo del reto de villas de handle."""
    payload = badge_usb.card_fields(badge.my_card(), nick=VILLA_NICKS[villa],
                                    team=villa, handle=handle)
    badge.expect_ok("CARD", payload)


def run_qa(badge, show=print):
    """Corre la QA y regresa su línea final; show() recibe cada línea de
    instrucciones (QA …) y de resultados (RESULT …)."""
    # Sin expect_ok: `QA` imprime las primeras instrucciones antes de su OK.
    badge.port.reset_input_buffer()
    badge.port.write(b"QA\n")
    deadline = time.time() + QA_TIMEOUT_S
    while True:
        line = badge.read_line(max(0.01, deadline - time.time()))
        if line.startswith("ERR"):
            raise Failure(f"QA: {line}")
        if line.startswith("QA ") or line.startswith("RESULT"):
            show(line)
        if line.startswith("RESULT qa "):
            return line


def reset(badge):
    badge.port.dtr = False  # DTR bajo con RTS alto reinicia el ESP32-S3
    badge.port.rts = True
    time.sleep(0.1)
    badge.port.rts = False


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("-p", "--port", default="/dev/ttyACM0")
    parser.add_argument("--master", type=bytes.fromhex, required=True,
                        help="K_master en hex")
    parser.add_argument("--csv", default="provision.csv")
    parser.add_argument("--bin", default=DEFAULT_BIN, help="merged.bin")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--no", type=int, help="fija el dorsal")
    which.add_argument("--villa", type=int,
                       choices=range(len(VILLA_NICKS)), metavar="V",
                       help="maestro de la villa V (0..9, orden de TEAMS[]): "
                       f"dorsal {MASTER_FIRST} + V")
    parser.add_argument("--no-flash", action="store_true",
                        help="no graba: solo provisión y QA")
    parser.add_argument("--before", action="append", default=[],
                        help="línea de consola antes de la QA (repetible)")
    parser.add_argument("--esptool", help="ruta de esptool")
    parser.add_argument("--vestidor", metavar="DIR",
                        help="imágenes vestidor-NNN.bin del reto N3")
    args = parser.parse_args()
    args.esptool = args.esptool or find_esptool()
    if args.villa is not None:
        args.no = MASTER_FIRST + args.villa
        if not args.vestidor:
            parser.error("--villa necesita --vestidor DIR (secrets.json)")
        try:
            share = villa_share(args.vestidor, args.villa)
        except Failure as e:
            parser.error(str(e))

    image = open(args.bin, "rb").read()
    littlefs = partition(image, "littlefs")
    start = time.time()
    row = {"no": "", "mac": "", "puerto": args.port}

    def record(result, detail=""):
        row.update(fecha=datetime.datetime.now().isoformat(timespec="seconds"),
                   resultado=result, segundos=f"{time.time() - start:.0f}",
                   detalle=detail)
        return log(args.csv, dict(row))

    badge = None
    try:
        row["mac"] = read_mac(args)
        row["no"] = log(args.csv, dict(row, fecha="", resultado="ASIGNADO",
                                       segundos="", detalle=""),
                        lambda rows: assign(rows, row["mac"], args.no))
        no = int(row["no"])
        print(f"MAC {row['mac']} -> dorsal {no}")
        vest = vestidor(args.vestidor, no, image) if args.vestidor else None
        if not args.no_flash:
            with tempfile.NamedTemporaryFile(suffix=".bin") as tmp:
                tmp.write(trim(image))
                tmp.flush()
                print(f"Grabando {os.path.basename(args.bin)}…")
                flash(args, tmp.name, littlefs, vest)
        elif vest:
            print(f"Grabando {os.path.basename(vest[1])}…")
            esptool(args, "write_flash", hex(vest[0]), vest[1])
        badge = connect(args.port)
        key = identity.derive_key(args.master, bytes.fromhex(
            row["mac"].replace(":", "")), no)
        provision(badge, no, key, row["mac"])
        print(f"Provisionado: dorsal {no}, clave {identity.key_id(key)}")
        for line in args.before:
            badge.expect_ok(line)
        result = run_qa(badge)
        passed = result.startswith("RESULT qa PASS")
        if passed and args.villa is not None:
            set_villa(badge, args.villa, share)
            print(f"Maestro de {VILLA_NICKS[args.villa]}")
        if passed:
            reset(badge)
        record("PASS" if passed else "FAIL", result)
        print(f"{'PASS' if passed else 'FAIL'} dorsal {no} "
              f"en {time.time() - start:.0f} s")
        return 0 if passed else 1
    except (Failure, badge_usb.ProtocolError, serial.SerialException,
            OSError) as e:
        if row["mac"]:
            record("ERROR", str(e))
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        if badge:
            badge.close()


if __name__ == "__main__":
    sys.exit(main())
