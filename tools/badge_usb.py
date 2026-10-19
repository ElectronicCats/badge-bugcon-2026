#!/usr/bin/env python3
"""
badge_usb.py — Cliente del protocolo USB del badge (F2.9, el mismo contrato
que el e-ink-Keychain; detalle en firmware/badge_bugcon_2026/src/services/
usb_protocol.h): sirve para probar el firmware sin el configurador web y como
base de provision.py (F12.4).

Las imágenes van en el formato del badge: 1 bpp, filas completas, MSB primero,
1 = blanco, del tamaño `panel` que reporta INFO. Se leen y se escriben como
PBM binario (P4, 1 = negro: se invierte) o como .bin crudo.

El avatar (AVTR, F5.7) va en el mismo formato, de AVATAR_W x AVATAR_H.

Requiere pyserial. Uso:
  ./tools/badge_usb.py info
  ./tools/badge_usb.py upload 0 gafete.pbm      # guarda el slot 0 y lo muestra
  ./tools/badge_usb.py show 0
  ./tools/badge_usb.py read 0 -o slot0.pbm
  ./tools/badge_usb.py clr
  ./tools/badge_usb.py dbg
  ./tools/badge_usb.py nick "Ñandú 10"
  ./tools/badge_usb.py card --team 2 --pos 4 --stats 60,40,70,30 --handle @yo
  ./tools/badge_usb.py avatar cara.pbm           # 96x96
  ./tools/badge_usb.py album -o album.bin        # luego tools/verify_album.py
  ./tools/badge_usb.py album -o album_42.json    # el .json de "Guardar .json"
  ./tools/badge_usb.py pwr                       # energía (F4.7)
  ./tools/badge_usb.py time                      # reloj con la hora de la PC
  ./tools/badge_usb.py led ff0000                # notificador (000000 apaga)
  ./tools/badge_usb.py -p /dev/ttyACM1 raw "INFO"
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
# Bytes 0..47 de la estampa v1 (card::Card, §3.2): version, type, badge_no,
# nickname, team, position, stats, rarity, flags, handle. Lo que lleva CARD.
CARD_FIELDS = struct.Struct("<BBH16sBB4sBB20s")
ALBUM_HEADER_BYTES = 80  # Cabecera de ALBM; mi estampa va en 16..80
INFO_RE = re.compile(
    r"^OK BB26 (?P<fw>\S+) no=(?P<no>\d+) panel=(?P<w>\d+)x(?P<h>\d+) "
    r"album=(?P<album>\d+)/(?P<total>\d+) slots=(?P<slots>\d+) "
    r"current=(?P<current>-?\d+) used=(?P<used>[01]+)$"
)


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
    y el configurador nunca recibe respuesta (F6.7)."""
    try:
        import termios
        attrs = termios.tcgetattr(port.fd)
        attrs[6][termios.VMIN] = 1
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(port.fd, termios.TCSANOW, attrs)
    except (ImportError, AttributeError, OSError):
        pass  # Windows no tiene termios ni el problema


class Badge:
    def __init__(self, port):
        self.port = serial.Serial(port, 115200, timeout=0.1)
        time.sleep(OPEN_WAIT_S)
        self.port.reset_input_buffer()

    def close(self):
        restore_vmin(self.port)
        self.port.close()

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
    """Segundos desde 1970 en hora local, lo que espera TIME (F11.1)."""
    now = time.time() if now is None else now
    return int(now) + time.localtime(now).tm_gmtoff


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("-p", "--port", default="/dev/ttyACM0")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    up = sub.add_parser("upload")
    up.add_argument("slot", type=int)
    up.add_argument("file", help=".pbm (P4) o .bin crudo")
    sub.add_parser("show").add_argument("slot", type=int)
    rd = sub.add_parser("read")
    rd.add_argument("slot", type=int)
    rd.add_argument("-o", "--output", required=True, help=".pbm o .bin")
    sub.add_parser("clr")
    sub.add_parser("dbg")
    sub.add_parser("raw").add_argument("line")
    sub.add_parser("nick").add_argument("text")
    cd = sub.add_parser("card", help="cambia solo los campos indicados")
    cd.add_argument("--nick")
    cd.add_argument("--team", type=int, help="-1 = ninguna")
    cd.add_argument("--pos", type=int, help="-1 = ninguna")
    cd.add_argument("--stats", type=lambda s: [int(v) for v in s.split(",")],
                    help="ATK,DEF,HAX,SUERTE")
    cd.add_argument("--handle")
    sub.add_parser("avatar").add_argument("file", help=".pbm (P4) o .bin")
    sub.add_parser("album").add_argument("-o", "--output", required=True)
    sub.add_parser("pwr")
    sub.add_parser("time", help="fija el reloj con la hora local de la PC")
    sub.add_parser("led").add_argument("rgb", help="rrggbb en hex; 000000 apaga")
    args = parser.parse_args()

    badge = Badge(args.port)
    try:
        if args.cmd == "info":
            for key, value in badge.info().items():
                print(f"{key}={value}")
        elif args.cmd == "upload":
            image = load_image(args.file, badge.info())
            print(badge.upload(args.slot, image))
        elif args.cmd == "show":
            print(badge.expect_ok(f"SHOW {args.slot}"))
        elif args.cmd == "read":
            info = badge.info()
            image = badge.read(args.slot)
            if args.output.endswith(".pbm"):
                write_pbm(args.output, info["w"], info["h"], image)
            else:
                open(args.output, "wb").write(image)
            print(f"OK {len(image)} B -> {args.output}")
        elif args.cmd == "clr":
            print(badge.expect_ok("CLR"))
        elif args.cmd == "dbg":
            print(badge.expect_ok("DBG"))
        elif args.cmd == "raw":
            print(badge.command(args.line))
        elif args.cmd == "nick":
            print(badge.expect_ok(f"NICK {args.text}"))
        elif args.cmd == "card":
            fields = card_fields(badge.my_card(), args.nick, args.team,
                                 args.pos, args.stats, args.handle)
            print(badge.expect_ok("CARD", fields))
        elif args.cmd == "avatar":
            image = load_image(args.file, {"w": AVATAR_W, "h": AVATAR_H})
            if len(image) != AVATAR_BYTES:
                raise ValueError(f"el avatar mide {AVATAR_BYTES} B")
            print(badge.expect_ok("AVTR", image))
        elif args.cmd == "pwr":
            for key, value in badge.power().items():
                print(f"{key}={value}")
        elif args.cmd == "time":
            print(badge.expect_ok(f"TIME {local_epoch()}"))
        elif args.cmd == "led":
            print(badge.expect_ok(f"LED {args.rgb}"))
        elif args.cmd == "album":
            data = badge.album()
            if args.output.endswith(".json"):  # el de "Guardar .json" (bb26-album)
                import datetime

                import verify_album

                now = datetime.datetime.now(datetime.timezone.utc)
                open(args.output, "w").write(verify_album.to_json(
                    data, badge.info()["fw"],
                    now.isoformat(timespec="seconds").replace("+00:00", "Z")))
            else:
                open(args.output, "wb").write(data)
            count = (len(data) - ALBUM_HEADER_BYTES) // 80
            print(f"OK {len(data)} B, {count} estampas -> {args.output}")
    except (ProtocolError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        badge.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
