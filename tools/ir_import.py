#!/usr/bin/env python3
"""
ir_import.py — Archivos `.ir` de Flipper Zero (qFlipper, la SD, las bases de
la comunidad) hacia y desde el control remoto del badge, por la consola USB.

  import: lee un `.ir`, mapea los nombres de botón conocidos a los 16 del
          badge (Power -> Encender, Vol_up -> Vol+, Mute -> Silencio...),
          valida cada señal y la manda a una marca propia nueva. Los botones
          que no caben (nombre libre, protocolo desconocido, portadora fuera
          de 10 kHz-1 MHz, más de 1024 tiempos...) se listan y no se cargan;
          los demás sí. Un crudo se repite a 38 kHz (la portadora de otra
          frecuencia no se guarda; el aviso sale en la lista).
  export: imprime una marca (`ir export <b>`) como `.ir`.

Requiere pyserial y Rich (venv del proyecto). Sin -p busca el badge solo.
Códigos de salida: 0 bien · 2 uso o archivo no válido · 3 conexión. Uso:
  ./tools/ir_import.py import TV.ir [--brand "Mi TV"] [-p /dev/ttyACM0]
  ./tools/ir_import.py import TV.ir --dry-run
  ./tools/ir_import.py export 12 -o mi_tv.ir
"""
import argparse
import re
import sys
import time
from pathlib import Path

import badge_link

BUTTONS = ["Encender", "Vol+", "Vol-", "Silencio", "Canal+", "Canal-",
           "Entrada", "Menú", "Arriba", "Abajo", "Izquierda", "Derecha",
           "OK", "Atrás", "Inicio", "Play/Pausa"]  # ir_remote::BUTTON_NAMES
# Nombre de Flipper (minúsculas, sin "_" ni espacios) -> índice del botón
ALIASES = {
    0: "power pwr onoff poweron poweroff standby",
    1: "volup vol+ volumeup volume+",
    2: "voldn voldown vol- volumedown volume-",
    3: "mute muting",
    4: "chnext chup ch+ channelup channel+ chan+",
    5: "chprev chdn chdown ch- channeldown channel- chan-",
    6: "input source tvinput avinput av",
    7: "menu",
    8: "up",
    9: "down",
    10: "left",
    11: "right",
    12: "ok enter select",
    13: "back return",
    14: "home",
    15: "play pause playpause",
}
BUTTON_OF = {a: k for k, names in ALIASES.items() for a in names.split()}
MAX_DURATIONS = 1024  # cfg::remote::MAX_DURATIONS
CARRIER_MIN, CARRIER_MAX = 10_000, 1_000_000  # cfg::ir::CARRIER_MIN/MAX_HZ
RAW_CARRIER = 38_000  # A la que sale un crudo
NAME_BYTES = 16  # ir_remote::NAME_BYTES
USER_BRANDS = 8  # cfg::remote::USER_BRANDS
CHUNK = 40  # Tiempos por línea `ir import data` (la consola corta en 320 B)


class IrError(Exception):
    pass


def button_of(name):
    """Índice del botón del badge para un nombre de Flipper, o None."""
    return BUTTON_OF.get(re.sub(r"[\s_]", "", name).lower())


def parse_ir(text):
    """Las señales de un `.ir`: [{'name', 'type', ...}] en su orden.

    Rechaza otro encabezado (un "IR library file" no es un remoto) y otra
    versión, como Flipper (WrongFileType / WrongFileVersion)."""
    fields = [tuple(s.strip() for s in line.split(":", 1))
              for line in text.splitlines()
              if line.strip() and not line.startswith("#") and ":" in line]
    if not fields or fields[0] != ("Filetype", "IR signals file"):
        raise IrError("no es un 'IR signals file'")
    if fields[1:2] != [("Version", "1")]:
        raise IrError("versión de archivo no soportada")
    signals = []
    for key, value in fields[2:]:
        if key == "name":
            signals.append({"name": value})
        elif signals:
            signals[-1][key] = value
    return signals


def hex_value(text):
    """'04 00 00 00' (bytes, el menos significativo primero) -> 4."""
    return int.from_bytes(bytes(int(b, 16) for b in text.split()), "little")


def plan(signals):
    """(órdenes, omitidos, avisos): `ir import ...` por botón del badge."""
    commands, skipped, notes, taken = [], [], [], {}
    for s in signals:
        name = s["name"]
        k = button_of(name)
        try:
            if k is None:
                raise IrError("el badge no tiene un botón con ese nombre")
            if k in taken:
                raise IrError(f"ya se cargó {taken[k]} como {BUTTONS[k]}")
            if s.get("type") == "parsed":
                cmd = [f"ir import parsed {{b}} {k} {s['protocol']} "
                       f"{hex_value(s['address'])} {hex_value(s['command'])}"]
            elif s.get("type") == "raw":
                cmd = raw_commands(k, s, notes)
            else:
                raise IrError("tipo de señal desconocido")
        except (IrError, KeyError, ValueError) as e:
            skipped.append((name, str(e) or f"falta {e}"))
            continue
        taken[k] = name
        commands.append((name, k, cmd))
    return commands, skipped, notes


def raw_commands(k, s, notes):
    hz = int(s["frequency"])
    if not CARRIER_MIN <= hz <= CARRIER_MAX:
        raise IrError(f"portadora fuera de rango ({hz} Hz)")
    t = [int(v) for v in s["data"].split()]
    if len(t) % 2 == 0:
        t.pop()  # Un espacio final no se nota; el badge pide marca al final
    if not t or any(v <= 0 for v in t) or any(v > 65535 for v in t[::2]):
        raise IrError("tiempos no válidos")
    if len(t) > MAX_DURATIONS:
        raise IrError(f"{len(t)} tiempos (el badge guarda {MAX_DURATIONS})")
    if hz != RAW_CARRIER:
        notes.append(f"{s['name']}: crudo a {hz} Hz, el badge lo envía "
                     f"a {RAW_CARRIER} Hz")
    t = [min(v, 65535) for v in t]
    return ([f"ir import raw {{b}} {k} {hz}"] +
            [f"ir import data {' '.join(map(str, t[i:i + CHUNK]))}"
             for i in range(0, len(t), CHUNK)] + ["ir import end"])


class Console:
    def __init__(self, port):
        # Conexión común: busca el badge, abre en exclusiva y lo saluda
        self.badge = badge_link.connect(port)
        self.port = self.badge.port

    def close(self):
        self.badge.close()  # También deja el tty en VMIN=1

    def run(self, line, until=("OK", "ERR"), timeout=5):
        """Las líneas de la respuesta hasta la que empieza con `until`."""
        self.port.reset_input_buffer()
        self.port.write((line + "\n").encode())
        out, buf, end = [], b"", time.time() + timeout
        while time.time() < end:
            buf += self.port.read(4096)
            *lines, buf = buf.split(b"\n")
            out += [l.decode(errors="replace").strip() for l in lines]
            if any(l.startswith(until) for l in out):
                return out
        raise TimeoutError(f"sin respuesta a '{line}'")


def check(lines, what=""):
    last = next(l for l in lines if l.startswith(("OK", "ERR")))
    if last.startswith("ERR"):
        raise IrError(f"{what}: {last}" if what else last)


def brand_name(text):
    """El nombre de la marca, o IrError si el badge no lo guardaría tal cual."""
    size = len(text.encode())
    if size > NAME_BYTES:
        raise IrError(f"el nombre de la marca '{text}' mide {size} bytes; el "
                      f"máximo es {NAME_BYTES} (sobran {size - NAME_BYTES}; "
                      "la ñ y los acentos cuentan doble). Usa --brand con un "
                      "nombre más corto")
    if not text.strip() or any(c < " " or c == "\x7f" for c in text):
        raise IrError("el nombre de la marca no puede estar vacío ni tener "
                      "caracteres de control")
    return text.strip()


def show(console, rows):
    """Tabla de resultados: (estado, señal, detalle)."""
    from rich.table import Table
    from rich.text import Text
    styles = {"cargado": "green", "listo": "green", "omitido": "yellow",
              "aviso": "cyan"}
    table = Table(show_header=True, header_style="bold")
    for column in ("Estado", "Señal", "Detalle"):
        table.add_column(column)
    for state, name, detail in rows:  # Text: el archivo puede traer corchetes
        table.add_row(Text(state, style=styles[state]), Text(name),
                      Text(detail))
    console.print(table)


def do_import(args, console):
    brand = brand_name(args.brand or Path(args.file).stem)
    text = Path(args.file).read_text(encoding="utf-8-sig")  # Con o sin BOM
    commands, skipped, notes = plan(parse_ir(text))
    rows = [("omitido", name, why) for name, why in skipped]
    rows += [("aviso", "", note) for note in notes]
    if args.dry_run:
        rows += [("listo", name, f"{BUTTONS[k]}: {len(cmd)} órdenes")
                 for name, k, cmd in commands]
        return show(console, rows)
    from rich.progress import track
    con = Console(args.port)
    try:
        lines = con.run(f"ir brand add {brand}")
        try:
            check(lines)
        except IrError:  # El badge no distingue el motivo
            raise IrError(f"el Badge no creó la marca '{brand}': el nombre ya "
                          f"existe o ya tienes {USER_BRANDS} marcas propias "
                          "(borra una desde el Badge)") from None
        found = next((re.match(r"BRAND (\d+)", l) for l in lines
                      if l.startswith("BRAND ")), None)
        if not found:
            raise IrError("el Badge no dijo qué número tiene la marca nueva")
        number = found.group(1)
        for name, k, cmd in track(commands, description="Cargando botones",
                                  console=console):
            try:
                for line in cmd:
                    check(con.run(line.replace("{b}", number)))
                rows.append(("cargado", name, BUTTONS[k]))
            except IrError as e:
                rows.append(("omitido", name, str(e)))
    finally:
        con.close()
    show(console, rows)
    console.print(f"Marca '{brand}' = {number}", markup=False)


def do_export(args, console):
    con = Console(args.port)
    try:
        lines = con.run(f"ir export {args.brand}")
    finally:
        con.close()
    if any(l.startswith("ERR") for l in lines):
        raise IrError("esa marca no existe")
    ir = [l for l in lines if re.match(
        r"#$|(Filetype|Version|name|type|protocol|address|command|frequency|"
        r"duty_cycle|data):", l)]
    text = "\n".join(ir) + "\n#\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-p", "--port", help="por omisión, el badge que encuentre")
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("file")
    imp.add_argument("--brand", help="nombre de la marca (≤ 16 B)")
    imp.add_argument("--dry-run", action="store_true")
    exp = sub.add_parser("export")
    exp.add_argument("brand", type=int)
    exp.add_argument("-o", "--output")
    args = ap.parse_args()
    console = badge_link.console()
    try:
        (do_import if args.cmd == "import" else do_export)(args, console)
    except (IrError, OSError, ValueError, badge_link.BadgeConnectionError,
            badge_link.ProtocolError) as e:  # ValueError: .ir que no es UTF-8
        return badge_link.report(console, e)
    return badge_link.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
