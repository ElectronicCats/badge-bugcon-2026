#!/usr/bin/env python3
"""
badge_usb.py — Cliente del protocolo USB del badge (el mismo contrato
que el e-ink-Keychain; detalle en firmware/badge_bugcon_2026/src/services/
usb_protocol.h): sirve para probar el firmware sin el configurador web y como
base de provision.py.

Las imágenes van en el formato del badge: 1 bpp, filas completas, MSB primero,
1 = blanco, del tamaño `panel` que reporta INFO. Se leen y se escriben como
PBM binario (P4, 1 = negro: se invierte) o como .bin crudo.

El avatar (AVTR) va en el mismo formato, de AVATAR_W x AVATAR_H.

Requiere pyserial; para las tablas y los colores, Rich (requirements.txt).
Uso:
  ./tools/badge_usb.py info                       # dorsal, álbum y espacios
  ./tools/badge_usb.py time                       # reloj con la hora de la PC
  ./tools/badge_usb.py nick "Ñandú 10"
  ./tools/badge_usb.py card --team 2 --pos 4 --stats 60,40,70,30 --handle @yo
  ./tools/badge_usb.py avatar cara.png            # 96x96, se convierte sola
  ./tools/badge_usb.py upload 0 mi_foto.png       # Marco, se convierte sola
  ./tools/badge_usb.py show 0
  ./tools/badge_usb.py read 0 -o slot0.pbm
  ./tools/badge_usb.py album -o album.json        # copia del álbum
  ./tools/badge_usb.py flag bandera{secreta}      # entrega la flag de un reto
  ./tools/badge_usb.py led rojo                   # notificador (apagar lo apaga)
  ./tools/badge_usb.py clr
  ./tools/badge_usb.py pwr                        # energía (desarrollo)
  ./tools/badge_usb.py dbg                        # consola de desarrollo
  ./tools/badge_usb.py tokens 1200 3400 500000 20000 9000000 2000000
                       # tokens de IA: entrada salida caché_lect
                       # caché_escr total_7d meta (0 = sin meta);
                       # --nombre "Claude Code" elige la página
  ./tools/badge_usb.py campeon                    # estampa de campeón
  ./tools/badge_usb.py -p /dev/ttyACM1 raw "INFO"  # desarrollo
"""
import argparse
import re
import struct
import sys
import time

import serial

OPEN_WAIT_S = 0.3  # El badge descarta lo que llega en los primeros 200 ms
REPLY_TIMEOUT_S = 15  # Como el configurador del keychain
AVATAR_W = AVATAR_H = 96  # cfg::card::AVATAR_WIDTH/HEIGHT
AVATAR_BYTES = (AVATAR_W + 7) // 8 * AVATAR_H
# Bytes 0..47 de la estampa v1 (card::Card): version, type, badge_no,
# nickname, team, position, stats, rarity, flags, handle. Lo que lleva CARD.
CARD_FIELDS = struct.Struct("<BBH16sBB4sBB20s")
ALBUM_HEADER_BYTES = 80  # Cabecera de ALBM; mi estampa va en 16..80
INFO_RE = re.compile(
    r"^OK BB26 (?P<fw>\S+) no=(?P<no>\d+) panel=(?P<w>\d+)x(?P<h>\d+) "
    r"album=(?P<album>\d+)/(?P<total>\d+) slots=(?P<slots>\d+) "
    r"current=(?P<current>-?\d+) used=(?P<used>[01]+)$"
)
# Tablas del README: villas (team), posiciones (pos) y colores del notificador.
VILLAS = {
    0: "Hardware", 1: "RF", 2: "Rookie", 3: "OT", 4: "Payments",
    5: "BugBounty", 6: "WoSec", 7: "APT",
    8: "Nación Hacker", 9: "Live Hacking",
}
POSICIONES = {
    0: "Portero", 1: "Defensa", 2: "Medio", 3: "Delantero", 4: "Pentester",
}
LED_NAMES = {
    "rojo": "ff0000", "verde": "00ff00", "azul": "0000ff",
    "amarillo": "ffff00", "blanco": "ffffff", "apagar": "000000",
}
DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
MESES = ("ene", "feb", "mar", "abr", "may", "jun",
         "jul", "ago", "sep", "oct", "nov", "dic")


class ProtocolError(Exception):
    pass


def parse_power(reply):
    """Respuesta de PWR -> dict: estado (texto), contadores (int) y apps
    ({nombre: ms}, en el orden de APPS[])."""
    if not reply.startswith("OK "):
        raise ProtocolError(reply)
    fields = dict(field.split("=", 1) for field in reply[3:].split())
    apps = fields.pop("apps", "")
    power = {k: v if k == "estado" else int(v) for k, v in fields.items()}
    power["apps"] = {
        name: int(ms)
        for name, ms in (app.split(":") for app in apps.split(",") if app)
    }
    return power


def restore_vmin(port):
    """Deja el tty con VMIN=1 (el valor de fábrica) antes de cerrarlo.

    pyserial lo pone en 0 y el kernel lo guarda para el siguiente que abra
    ese ttyACMn, aunque se desconecte el cable. Chrome/Brave en Linux no fijan
    VMIN: con 0, su read() vuelve vacío, lo toman por "device has been lost"
    y el configurador nunca recibe respuesta."""
    try:
        import termios
    except ImportError:
        return  # Windows no tiene termios ni el problema
    try:
        attrs = termios.tcgetattr(port.fd)
        attrs[6][termios.VMIN] = 1
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(port.fd, termios.TCSANOW, attrs)
    except (termios.error, AttributeError, OSError):
        pass  # Badge desconectado (EIO): ya no hay tty que arreglar


class Badge:
    def __init__(self, port):
        # En exclusiva: dos programas en el mismo tty se roban las respuestas
        # (ai_tokens.py se queda con el puerto abierto)
        self.port = serial.Serial(port, 115200, timeout=0.1, exclusive=True)
        time.sleep(OPEN_WAIT_S)
        self.port.reset_input_buffer()

    def close(self):
        restore_vmin(self.port)
        self.port.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def read_line(self, timeout=REPLY_TIMEOUT_S):
        deadline = time.time() + timeout
        line = b""
        while time.time() < deadline:
            c = self.port.read(1)
            if c == b"\n":
                return line.rstrip(b"\r").decode(errors="replace")
            line += c
        raise ProtocolError("timeout")

    def read_reply(self, timeout=REPLY_TIMEOUT_S):
        """Primera línea OK/ERR; las demás son logs del firmware."""
        deadline = time.time() + timeout
        while True:
            line = self.read_line(max(0.01, deadline - time.time()))
            if line.startswith("OK") or line.startswith("ERR"):
                return line

    def command(self, line, payload=None):
        self.port.reset_input_buffer()
        self.port.write((line + "\n").encode())
        if payload is not None:
            self.port.write(payload)
        return self.read_reply()

    def expect_ok(self, line, payload=None):
        reply = self.command(line, payload)
        if not reply.startswith("OK"):
            raise ProtocolError(reply)
        return reply

    def info(self):
        reply = self.expect_ok("INFO")
        m = INFO_RE.match(reply)
        if not m:
            raise ProtocolError(f"INFO inesperado: {reply}")
        info = m.groupdict()
        for key in ("no", "w", "h", "album", "total", "slots", "current"):
            info[key] = int(info[key])
        return info

    def upload(self, slot, image):
        return self.expect_ok(f"UPLD {slot}", image)

    def read(self, slot):
        reply = self.expect_ok(f"READ {slot}")
        size = int(reply.split()[1])
        data = self.port.read(size)
        deadline = time.time() + 5
        while len(data) < size and time.time() < deadline:
            data += self.port.read(size - len(data))
        if len(data) != size:
            raise ProtocolError(f"READ: llegaron {len(data)} de {size} B")
        return data

    def album(self):
        """Exportación de ALBM: cabecera + entradas (tools/verify_album.py)."""
        reply = self.expect_ok("ALBM")
        size = int(reply.split()[1])
        data = b""
        deadline = time.time() + 5
        while len(data) < size and time.time() < deadline:
            data += self.port.read(size - len(data))
        if len(data) != size:
            raise ProtocolError(f"ALBM: llegaron {len(data)} de {size} B")
        return data

    def power(self):
        return parse_power(self.expect_ok("PWR"))

    def my_card(self):
        """Mi estampa firmada (64 B), de la cabecera de ALBM."""
        return self.album()[16:ALBUM_HEADER_BYTES]


def text_field(text, size, name):
    """Texto UTF-8 de la estampa; struct lo cortaría a media letra."""
    data = text.encode()
    if len(data) > size:
        raise ValueError(f"el {name} mide {len(data)} B de UTF-8; caben {size}")
    return data


def card_fields(card,nick=None, team=None, pos=None, stats=None, handle=None):
    """Payload de CARD: los 48 B de `card` con los campos que se cambian."""
    f = list(CARD_FIELDS.unpack(card[: CARD_FIELDS.size]))
    if nick is not None:
        f[3] = text_field(nick, 16, "nickname")
    if team is not None:
        f[4] = team & 0xFF  # -1 = ninguna (0xFF)
    if pos is not None:
        f[5] = pos & 0xFF
    if stats is not None:
        if len(stats) != 4 or not all(0 <= v <= 255 for v in stats):
            raise ValueError("las stats son 4 valores (ATK,DEF,HAX,SUERTE)")
        f[6] = bytes(stats)
    if handle is not None:
        f[9] = text_field(handle, 20, "handle")
    return CARD_FIELDS.pack(*f)  # struct rellena los textos con NUL


def read_pbm(path):
    """PBM binario (P4) -> (ancho, alto, bytes con 1 = blanco)."""
    data = open(path, "rb").read()
    tokens = []
    pos = 0
    while len(tokens) < 3:
        while data[pos : pos + 1].isspace():
            pos += 1
        if data[pos : pos + 1] == b"#":
            pos = data.index(b"\n", pos)
            continue
        start = pos
        while not data[pos : pos + 1].isspace():
            pos += 1
        tokens.append(data[start:pos])
    if tokens[0] != b"P4":
        raise ValueError(f"{path}: solo PBM binario (P4)")
    w, h = int(tokens[1]), int(tokens[2])
    bits = data[pos + 1 : pos + 1 + (w + 7) // 8 * h]
    return w, h, bytes(b ^ 0xFF for b in bits)


def write_pbm(path, w, h, image):
    with open(path, "wb") as f:
        f.write(f"P4\n{w} {h}\n".encode())
        f.write(bytes(b ^ 0xFF for b in image))


def load_image(path, info):
    if path.endswith(".pbm"):
        w, h, image = read_pbm(path)
        if (w, h) != (info["w"], info["h"]):
            raise ValueError(
                f"{path} mide {w}x{h}; el badge espera {info['w']}x{info['h']}"
            )
        return image
    return open(path, "rb").read()


def local_epoch(now=None):
    """Segundos desde 1970 en hora local, lo que espera TIME."""
    now = time.time() if now is None else now
    return int(now) + time.localtime(now).tm_gmtoff


def validate_stats(stats):
    """Las 4 estadísticas: cada una 0-99 y la suma no pasa de 200."""
    if len(stats) != 4:
        raise ValueError("las estadísticas son 4 números separados por comas: "
                         "ataque, defensa, hack y suerte")
    for value in stats:
        if not 0 <= value <= 99:
            raise ValueError(f"cada estadística va de 0 a 99; {value} no sirve")
    total = sum(stats)
    if total > 200:
        raise ValueError(f"las estadísticas suman {total}; el máximo es 200 "
                         f"(te pasas por {total - 200})")
    return stats


def validate_team(team):
    if team != -1 and team not in VILLAS:
        raise ValueError(f"la villa va de -1 (ninguna) a {len(VILLAS) - 1}; {team} no existe")
    return team


def validate_pos(pos):
    if pos != -1 and pos not in POSICIONES:
        raise ValueError(f"la posición va de -1 (ninguna) a 4; {pos} no existe")
    return pos


def validate_sticker_text(text, size, name):
    """Texto de la estampa: hasta `size` B de UTF-8 y sin caracteres de control."""
    for char in text:
        if ord(char) < 32 or ord(char) == 127:
            raise ValueError(f"el {name} no puede llevar caracteres de control "
                             "(saltos de línea, tabulaciones…)")
    data = text.encode()
    if len(data) > size:
        raise ValueError(f"el {name} mide {len(data)} B de UTF-8 y caben {size}; "
                         "la ñ y las letras con acento cuentan doble")
    return data


def validate_led(color):
    """Color del notificador: nombre del README o hex (con o sin #) -> rrggbb."""
    text = color.strip().lower()
    if text.startswith("#"):
        text = text[1:]
    if text in LED_NAMES:
        return LED_NAMES[text]
    if len(text) != 6 or any(c not in "0123456789abcdef" for c in text):
        raise ValueError(f"'{color}' no es un color: escribe seis dígitos hex "
                         f"(como ff0000) o un nombre: {', '.join(LED_NAMES)}")
    return text


def validate_flag(text):
    """La flag de un reto: no vacía, sin espacios en las orillas ni controles."""
    if not text or text.strip() != text:
        raise ValueError("la flag no puede ir vacía ni llevar espacios al "
                         "principio o al final")
    for char in text:
        if ord(char) < 32 or ord(char) == 127:
            raise ValueError("la flag no puede llevar caracteres de control "
                             "(saltos de línea, tabulaciones…)")
    return text


def _bar(album, total, width=16):
    if total <= 0:
        return ""
    filled = min(width, round(album * width / total))
    return "█" * filled + "░" * (width - filled)


def _slots_text(info):
    return " · ".join(f"{i} {'ocupado' if bit == '1' else 'libre'}"
                      for i, bit in enumerate(info["used"]))


def _villa_name(team):
    return "Sin villa" if team == 0xFF else VILLAS.get(team, f"villa {team}")


def _pos_name(pos):
    return "Sin posición" if pos == 0xFF else POSICIONES.get(pos, f"posición {pos}")


def _sticker_summary(card):
    """Líneas (dato, valor) de la estampa, para contar qué quedó."""
    f = CARD_FIELDS.unpack(card[: CARD_FIELDS.size])
    nick = f[3].rstrip(b"\0").decode(errors="replace")
    handle = f[9].rstrip(b"\0").decode(errors="replace")
    return [
        ("Apodo", nick or "(vacío)"),
        ("Villa", _villa_name(f[4])),
        ("Posición", _pos_name(f[5])),
        ("Estadísticas", "/".join(str(b) for b in f[6])),
        ("Handle", handle or "(sin handle)"),
    ]


def _print_info(console, info):
    from rich import box
    from rich.table import Table

    table = Table(box=box.SIMPLE_HEAD, show_header=False, padding=(0, 1))
    table.add_column("Dato", style="bold")
    table.add_column("Valor")
    table.add_row("Dorsal", str(info["no"]))
    table.add_row("Álbum", f"{info['album']}/{info['total']}  "
                           f"{_bar(info['album'], info['total'])}")
    table.add_row("Marco", _slots_text(info))
    table.add_row("Versión", info["fw"])
    console.print(table)


def _console():
    """Console de Rich para los mensajes (stderr); None si falta Rich."""
    try:
        from rich.console import Console
    except ImportError:
        return None
    return Console(stderr=True, highlight=False)


def _run_command(badge, args, console):
    """Un comando sobre un Badge ya conectado; -> código de salida."""
    import badge_link

    def say(message):
        console.print(message, markup=False)

    _validate_args(args)  # idempotente: main() ya lo corrió antes de abrir el puerto
    if args.cmd == "info":
        info = badge.info()
        if args.crudo:
            for key, value in info.items():
                print(f"{key}={value}")
        else:
            _print_info(console, info)
        return badge_link.EXIT_OK
    if args.cmd == "show":
        badge_link.call(badge, f"SHOW {args.slot}")
        say(f"Mostrando el espacio {args.slot} en la pantalla.")
        return badge_link.EXIT_OK
    if args.cmd == "read":
        info = badge.info()
        image = badge.read(args.slot)
        if args.output.endswith(".pbm"):
            write_pbm(args.output, info["w"], info["h"], image)
        else:
            with open(args.output, "wb") as f:
                f.write(image)
        say(f"Guardados {len(image)} B del espacio {args.slot} en {args.output}.")
        return badge_link.EXIT_OK
    if args.cmd == "clr":
        badge_link.call(badge, "CLR")
        say("Pantalla en blanco. Las imágenes guardadas no se borraron.")
        return badge_link.EXIT_OK
    if args.cmd == "dbg":
        say(badge_link.call(badge, "DBG"))
        return badge_link.EXIT_OK
    if args.cmd == "raw":
        say(badge.command(args.line))
        return badge_link.EXIT_OK
    if args.cmd == "nick":
        badge_link.call(badge, f"NICK {args.text}")
        say(f"Apodo puesto: {args.text}")
        return badge_link.EXIT_OK
    if args.cmd == "card":
        payload = card_fields(badge.my_card(), args.nick, args.team,
                              args.pos, args.stats, args.handle)
        badge_link.call(badge, "CARD", payload)
        say("Estampa actualizada:")
        for label, value in _sticker_summary(payload):
            say(f"  {label}: {value}")
        return badge_link.EXIT_OK
    if args.cmd == "pwr":
        for key, value in badge.power().items():
            print(f"{key}={value}")
        return badge_link.EXIT_OK
    if args.cmd == "time":
        epoch = local_epoch()
        badge_link.call(badge, f"TIME {epoch}")
        t = time.localtime(epoch)
        say(f"Hora puesta: {DIAS[t.tm_wday]} {t.tm_mday} "
            f"{MESES[t.tm_mon - 1]} {t.tm_hour:02d}:{t.tm_min:02d}.")
        say("El Badge no permite leer la hora de vuelta; revisa la barra de "
            "arriba.")
        return badge_link.EXIT_OK
    if args.cmd == "led":
        color = validate_led(args.rgb)
        badge_link.call(badge, f"LED {color}")
        say(f"Luces en #{color}.")
        return badge_link.EXIT_OK
    if args.cmd == "tokens":
        name = f" {args.nombre}" if args.nombre else ""
        badge_link.call(badge, "TOKENS " + " ".join(map(str, args.n)) + name)
        say("Tokens enviados a la vista del Badge.")
        return badge_link.EXIT_OK
    if args.cmd == "campeon":
        say(badge_link.call(badge, "CAMPEON"))
        return badge_link.EXIT_OK
    if args.cmd == "flag":
        text = validate_flag(args.text)
        reply = badge_link.call(badge, f"FLAG {text}")
        parts = reply.split()
        stage = parts[1] if len(parts) > 1 else "?"
        say(f"¡Correcta! Superaste la etapa {stage} y ganaste su estampa.")
        return badge_link.EXIT_OK
    if args.cmd == "album":
        say("Aviso: este archivo tiene apodos y handles de otras personas. "
            "Guárdalo con cuidado y no lo publiques.")
        data = badge.album()
        if args.output.endswith(".json"):  # el de "Guardar .json" (bb26-album)
            import datetime

            import verify_album

            now = datetime.datetime.now(datetime.timezone.utc)
            with open(args.output, "w") as f:
                f.write(verify_album.to_json(
                    data, badge.info()["fw"],
                    now.isoformat(timespec="seconds").replace("+00:00", "Z")))
        else:
            with open(args.output, "wb") as f:
                f.write(data)
        count = (len(data) - ALBUM_HEADER_BYTES) // 80
        say(f"OK {len(data)} B, {count} estampas -> {args.output}")
        return badge_link.EXIT_OK
    raise ValueError(f"comando desconocido: {args.cmd}")


def _validate_args(args):
    """Revisa en la PC lo que el Badge rechazaría, antes de abrir el puerto."""
    if args.cmd == "nick":
        validate_sticker_text(args.text, 16, "apodo")
    elif args.cmd == "card":
        if args.team is not None:
            validate_team(args.team)
        if args.pos is not None:
            validate_pos(args.pos)
        if args.stats is not None:
            validate_stats(args.stats)
        if args.nick is not None:
            validate_sticker_text(args.nick, 16, "apodo")
        if args.handle is not None:
            validate_sticker_text(args.handle, 20, "handle")
    elif args.cmd == "led":
        validate_led(args.rgb)
    elif args.cmd == "flag":
        validate_flag(args.text)


def _parser():
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n")[1],
        epilog="Códigos de salida: 0 bien · 1 el Badge rechazó el comando · "
               "2 uso · 3 conexión.")
    parser.add_argument("-p", "--port", default=None,
                        help="puerto del Badge (si no, se busca solo)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    info = sub.add_parser("info", help="dorsal, álbum y espacios del Marco")
    info.add_argument("--crudo", action="store_true",
                      help="clave=valor, como antes")
    up = sub.add_parser("upload", help="guarda una imagen en el Marco")
    up.add_argument("slot", type=int)
    up.add_argument("file", help="cualquier imagen; se convierte al tamaño del Marco")
    sub.add_parser("show", help="muestra un espacio en la pantalla").add_argument(
        "slot", type=int)
    rd = sub.add_parser("read", help="guarda una copia de un espacio")
    rd.add_argument("slot", type=int)
    rd.add_argument("-o", "--output", required=True, help=".pbm o .bin")
    sub.add_parser("clr", help="pantalla en blanco (desarrollo)")
    sub.add_parser("dbg", help="consola de desarrollo")
    sub.add_parser("raw", help="manda una línea tal cual (desarrollo)").add_argument(
        "line")
    sub.add_parser("nick", help="cambia tu apodo").add_argument("text")
    cd = sub.add_parser("card", help="cambia solo los campos indicados")
    cd.add_argument("--nick")
    cd.add_argument("--team", type=int, help=f"-1 = ninguna (0 a {len(VILLAS) - 1})")
    cd.add_argument("--pos", type=int, help="-1 = ninguna (0 a 4)")
    cd.add_argument("--stats", type=lambda s: [int(v) for v in s.split(",")],
                    help="ataque,defensa,hack,suerte (0-99, suma <= 200)")
    cd.add_argument("--handle", help="hasta 20 bytes de UTF-8")
    av = sub.add_parser("avatar", help="pon tu imagen (96x96)")
    av.add_argument("file", help="cualquier imagen; se convierte a 96x96")
    al = sub.add_parser("album", help="guarda una copia de tu álbum")
    al.add_argument("-o", "--output", required=True, help=".bin o .json")
    sub.add_parser("pwr", help="energía (desarrollo)")
    sub.add_parser("time", help="fija el reloj con la hora local de la PC")
    sub.add_parser("led", help="color de las luces (nombre o hex)").add_argument(
        "rgb")
    tk = sub.add_parser("tokens", help="tokens de IA (desarrollo)")
    tk.add_argument("n", nargs=6, type=int,
                    help="entrada salida caché_lect caché_escr total_7d meta")
    tk.add_argument("--nombre", help="página (herramienta o modelo; Total)")
    sub.add_parser("campeon", help="estampa de campeón (desarrollo)")
    sub.add_parser("flag", help="entrega la flag de un reto").add_argument("text")

    import badge_upload  # opciones de conversión y vista previa

    badge_upload.add_options(up)
    badge_upload.add_options(av, slot=False)
    return parser


def main():
    args = _parser().parse_args()

    import badge_link

    if args.cmd in ("upload", "avatar"):
        import badge_upload

        return badge_upload.run(args, args.cmd)

    console = _console()
    if console is None:
        print("Falta Rich: pip install -r tools/requirements.txt", file=sys.stderr)
        return badge_link.EXIT_USAGE

    try:
        _validate_args(args)
    except ValueError as e:
        console.print(f"error: {e}", style="bold red", markup=False)
        return badge_link.EXIT_USAGE

    try:
        badge = badge_link.connect(args.port)
    except badge_link.BadgeConnectionError as e:
        console.print(f"error: {e}", style="bold red", markup=False)
        return badge_link.EXIT_CONNECTION

    try:
        return _run_command(badge, args, console)
    except badge_link.ProtocolError as e:
        console.print(f"error: {badge_link.explain(e)}", style="bold red",
                      markup=False)
        return badge_link.EXIT_REJECTED
    except ValueError as e:
        console.print(f"error: {e}", style="bold red", markup=False)
        return badge_link.EXIT_USAGE
    except OSError as e:  # no se pudo escribir el archivo de -o
        console.print(f"error: no pude guardar el archivo: {e.strerror}: "
                      f"{e.filename}", style="bold red", markup=False)
        return badge_link.EXIT_USAGE
    finally:
        badge.close()


if __name__ == "__main__":
    sys.exit(main())
