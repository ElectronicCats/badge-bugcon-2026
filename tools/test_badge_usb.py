#!/usr/bin/env python3
"""
test_badge_usb.py — Pruebas de tools/badge_usb.py sin badge: la respuesta de
PWR tal como la escribe usb_protocol.cpp, restore_vmin() con el tty
ya desconectado y la API que importa provision.py (Badge con un puerto
falso, ProtocolError, card_fields, read_pbm/write_pbm, local_epoch). Si una
de estas pruebas cambia, cambió el contrato con provision.py.

Uso (requiere pyserial, que badge_usb.py importa):
  python3 -m unittest tools/test_badge_usb.py -v
"""
import inspect
import itertools
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import badge_usb  # noqa: E402

INFO_REPLY = ("OK BB26 1.0.0 no=42 panel=200x200 album=25/400 slots=4 "
              "current=1 used=1010")


class FakePort:
    """Puerto serie falso: cada línea escrita (terminada en \\n) dispara
    reply(línea) -> bytes, que quedan por leer. read() vuelve vacío si no hay
    nada, como pyserial al vencer su timeout."""

    def __init__(self, reply=None):
        self.reply = reply or (lambda line: b"")
        self.rx = bytearray()
        self.written = []
        self.resets = 0
        self.closed = False

    def read(self, n=1):
        data = bytes(self.rx[:n])
        del self.rx[:n]
        return data

    def write(self, data):
        self.written.append(bytes(data))
        if data.endswith(b"\n"):  # los payloads de las pruebas no terminan en \n
            self.rx += self.reply(data.decode(errors="replace").rstrip("\n"))

    def reset_input_buffer(self):
        self.resets += 1
        self.rx.clear()

    def close(self):
        self.closed = True


def make_badge(reply=None):
    """Badge sobre un FakePort, sin abrir ningún tty ni esperar 0.3 s."""
    port = FakePort(reply)
    with mock.patch.object(badge_usb.serial, "Serial", return_value=port), \
            mock.patch.object(badge_usb.time, "sleep"):
        badge = badge_usb.Badge("/dev/fake")
    return badge, port

REPLY = ("OK estado=USB ACTIVO=30000 REPOSO=1200 SUENO=95000 USB=4000 "
         "ligero=12 dormido=900 profundo=1 completos=3 parciales=7 "
         "completo_ms=1522 completo_max_ms=1530 parcial_ms=641 "
         "parcial_max_ms=650 epd_timeouts=0 ir=5 "
         "apps=home:120000,menu:2500,penalty:0")


class ParsePower(unittest.TestCase):
    def test_reply(self):
        power = badge_usb.parse_power(REPLY)
        self.assertEqual(power["estado"], "USB")
        self.assertEqual(power["SUENO"], 95000)
        self.assertEqual(power["parciales"], 7)
        self.assertEqual(power["parcial_max_ms"], 650)
        self.assertEqual(power["ir"], 5)
        self.assertEqual(list(power["apps"].items()),
                         [("home", 120000), ("menu", 2500), ("penalty", 0)])

    def test_error(self):
        with self.assertRaises(badge_usb.ProtocolError):
            badge_usb.parse_power("ERR badcmd")


class RestoreVmin(unittest.TestCase):
    def test_gone(self):
        # Badge desconectado: tcgetattr lanza termios.error (EIO), que no es
        # OSError; aquí, con un pipe, ENOTTY. close() no debe caerse.
        read, write = os.pipe()
        try:
            badge_usb.restore_vmin(type("Port", (), {"fd": read})())
        finally:
            os.close(read)
            os.close(write)


class PublicApi(unittest.TestCase):
    """Firmas que provision.py da por hechas (la mutación manual de H0: si
    cambia una, esta clase falla)."""

    def sig(self, fn):
        return str(inspect.signature(fn))

    def test_badge_signatures(self):
        B = badge_usb.Badge
        self.assertEqual(self.sig(B.__init__), "(self, port)")
        self.assertEqual(self.sig(B.close), "(self)")
        self.assertEqual(self.sig(B.read_line),
                         f"(self, timeout={badge_usb.REPLY_TIMEOUT_S})")
        self.assertEqual(self.sig(B.read_reply),
                         f"(self, timeout={badge_usb.REPLY_TIMEOUT_S})")
        self.assertEqual(self.sig(B.command), "(self, line, payload=None)")
        self.assertEqual(self.sig(B.expect_ok), "(self, line, payload=None)")
        self.assertEqual(self.sig(B.info), "(self)")
        self.assertEqual(self.sig(B.upload), "(self, slot, image)")
        self.assertEqual(self.sig(B.read), "(self, slot)")
        self.assertEqual(self.sig(B.album), "(self)")
        self.assertEqual(self.sig(B.power), "(self)")
        self.assertEqual(self.sig(B.my_card), "(self)")

    def test_module_signatures(self):
        self.assertEqual(self.sig(badge_usb.restore_vmin), "(port)")
        self.assertEqual(self.sig(badge_usb.parse_power), "(reply)")
        self.assertEqual(self.sig(badge_usb.local_epoch), "(now=None)")
        self.assertEqual(
            self.sig(badge_usb.card_fields),
            "(card, nick=None, team=None, pos=None, stats=None, handle=None)")
        self.assertTrue(issubclass(badge_usb.ProtocolError, Exception))


class BadgeOpen(unittest.TestCase):
    def test_open_in_exclusive_mode_and_flush(self):
        port = FakePort()
        with mock.patch.object(badge_usb.serial, "Serial",
                               return_value=port) as ctor, \
                mock.patch.object(badge_usb.time, "sleep") as sleep:
            badge_usb.Badge("/dev/ttyACM9")
        ctor.assert_called_once_with("/dev/ttyACM9", 115200, timeout=0.1,
                                     exclusive=True)
        sleep.assert_called_once_with(badge_usb.OPEN_WAIT_S)
        self.assertEqual(port.resets, 1)

    def test_close_closes_port(self):
        badge, port = make_badge()
        badge.close()  # el puerto falso no tiene fd: restore_vmin no se cae
        self.assertTrue(port.closed)


class ReadReply(unittest.TestCase):
    def test_read_line_strips_cr_and_decodes(self):
        badge, port = make_badge()
        port.rx += "OK ñ\r\n".encode()
        self.assertEqual(badge.read_line(1), "OK ñ")

    def test_read_line_invalid_utf8_is_replaced(self):
        badge, port = make_badge()
        port.rx += b"OK \xff\n"
        self.assertEqual(badge.read_line(1), "OK �")

    def test_read_line_timeout(self):
        badge, _ = make_badge()
        with self.assertRaises(badge_usb.ProtocolError) as ctx:
            badge.read_line(0.05)
        self.assertEqual(str(ctx.exception), "timeout")

    def test_read_reply_skips_logs(self):
        badge, port = make_badge()
        port.rx += b"[I] boot\nCOMANDO raro\nOK 1\nOK 2\n"
        self.assertEqual(badge.read_reply(1), "OK 1")

    def test_read_reply_returns_err(self):
        badge, port = make_badge()
        port.rx += b"log\nERR badslot\n"
        self.assertEqual(badge.read_reply(1), "ERR badslot")

    def test_read_reply_timeout_without_reply(self):
        badge, port = make_badge()
        port.rx += b"solo un log\n"
        with self.assertRaises(badge_usb.ProtocolError):
            badge.read_reply(0.05)


class Commands(unittest.TestCase):
    def test_command_clears_input_writes_line_then_payload(self):
        badge, port = make_badge(lambda line: b"OK\n")
        port.rx += b"OK viejo\n"  # basura anterior: no debe leerse
        self.assertEqual(badge.command("UPLD 2", b"\x01\x02"), "OK")
        self.assertEqual(port.written, [b"UPLD 2\n", b"\x01\x02"])

    def test_command_without_payload_writes_once(self):
        badge, port = make_badge(lambda line: b"OK\n")
        badge.command("CLR")
        self.assertEqual(port.written, [b"CLR\n"])

    def test_expect_ok_returns_reply(self):
        badge, _ = make_badge(lambda line: b"log\nOK 7\n")
        self.assertEqual(badge.expect_ok("TIME 1"), "OK 7")

    def test_expect_ok_raises_protocol_error_with_the_err_line(self):
        badge, _ = make_badge(lambda line: b"ERR badslot\n")
        with self.assertRaises(badge_usb.ProtocolError) as ctx:
            badge.expect_ok("SHOW 9")
        self.assertEqual(str(ctx.exception), "ERR badslot")

    def test_info(self):
        badge, _ = make_badge(lambda line: (INFO_REPLY + "\n").encode())
        self.assertEqual(badge.info(), {
            "fw": "1.0.0", "no": 42, "w": 200, "h": 200, "album": 25,
            "total": 400, "slots": 4, "current": 1, "used": "1010",
            "home": None})

    def test_info_home(self):
        # El firmware con imagen de inicio la reporta al final de INFO
        badge, _ = make_badge(lambda line: (INFO_REPLY + " home=2\n").encode())
        self.assertEqual(badge.info()["home"], 2)
        badge, _ = make_badge(lambda line: (INFO_REPLY + " home=-1\n").encode())
        self.assertEqual(badge.info()["home"], -1)

    def test_info_current_can_be_negative(self):
        badge, _ = make_badge(lambda line: (
            INFO_REPLY.replace("current=1", "current=-1") + "\n").encode())
        self.assertEqual(badge.info()["current"], -1)

    def test_info_unexpected(self):
        badge, _ = make_badge(lambda line: b"OK otra cosa\n")
        with self.assertRaises(badge_usb.ProtocolError):
            badge.info()

    def test_upload(self):
        badge, port = make_badge(lambda line: b"OK\n")
        image = bytes(5000)
        self.assertEqual(badge.upload(1, image), "OK")
        self.assertEqual(port.written, [b"UPLD 1\n", image])

    def test_power(self):
        badge, _ = make_badge(lambda line: (REPLY + "\n").encode())
        self.assertEqual(badge.power()["estado"], "USB")


class Binary(unittest.TestCase):
    def test_read(self):
        badge, _ = make_badge(lambda line: b"OK 5\nhello")
        self.assertEqual(badge.read(0), b"hello")

    def test_read_short_payload(self):
        badge, _ = make_badge(lambda line: b"OK 5\nhel")
        # Reloj falso (1 s por consulta): los 5 s de espera no se esperan de
        # verdad. time.time es global, así que también lo usa read_reply.
        with mock.patch.object(badge_usb.time, "time",
                               side_effect=itertools.count()):
            with self.assertRaises(badge_usb.ProtocolError) as ctx:
                badge.read(0)
        self.assertIn("3 de 5", str(ctx.exception))

    def test_album_and_my_card(self):
        data = bytes(range(16)) + b"M" * 64 + b"E" * 80
        badge, _ = make_badge(
            lambda line: f"OK {len(data)}\n".encode() + data)
        self.assertEqual(badge.album(), data)
        badge, _ = make_badge(
            lambda line: f"OK {len(data)}\n".encode() + data)
        self.assertEqual(badge.my_card(), b"M" * 64)


class CardFields(unittest.TestCase):
    def card(self):
        return badge_usb.CARD_FIELDS.pack(
            1, 0, 42, b"Viejo", 3, 2, bytes([10, 20, 30, 40]), 1, 0,
            b"@viejo") + bytes(16)  # la estampa llega con más bytes: se ignoran

    def unpack(self, payload):
        return badge_usb.CARD_FIELDS.unpack(payload)

    def test_no_changes_keeps_everything(self):
        out = badge_usb.card_fields(self.card())
        self.assertEqual(len(out), 48)
        self.assertEqual(out, self.card()[:48])

    def test_changes_only_what_is_given(self):
        f = self.unpack(badge_usb.card_fields(
            self.card(), nick="Ñandú", team=-1, pos=4,
            stats=[1, 2, 3, 4], handle="@nuevo"))
        self.assertEqual(f[2], 42)  # badge_no intacto
        self.assertEqual(f[3].rstrip(b"\0"), "Ñandú".encode())
        self.assertEqual((f[4], f[5]), (0xFF, 4))  # -1 = 0xFF
        self.assertEqual(f[6], bytes([1, 2, 3, 4]))
        self.assertEqual(f[9].rstrip(b"\0"), b"@nuevo")

    def test_nick_limit_is_bytes_of_utf8(self):
        badge_usb.card_fields(self.card(), nick="ñ" * 8)  # 16 B: cabe
        with self.assertRaises(ValueError):
            badge_usb.card_fields(self.card(), nick="ñ" * 9)

    def test_handle_limit(self):
        badge_usb.card_fields(self.card(), handle="a" * 20)
        with self.assertRaises(ValueError):
            badge_usb.card_fields(self.card(), handle="a" * 21)

    def test_stats_must_be_four_bytes(self):
        for bad in ([1, 2, 3], [1, 2, 3, 4, 5], [0, 0, 0, 256], [0, 0, 0, -1]):
            with self.assertRaises(ValueError):
                badge_usb.card_fields(self.card(), stats=bad)


class Pbm(unittest.TestCase):
    def test_round_trip(self):
        image = bytes(range(256)) * 19 + bytes(136)  # 5000 B
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.pbm")
            badge_usb.write_pbm(path, 200, 200, image)
            self.assertEqual(badge_usb.read_pbm(path), (200, 200, image))

    def test_file_is_p4_with_inverted_bits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.pbm")
            badge_usb.write_pbm(path, 8, 2, b"\xff\x00")  # blanco, negro
            raw = pathlib.Path(path).read_bytes()
        self.assertEqual(raw, b"P4\n8 2\n\x00\xff")  # PBM: 1 = negro

    def test_reads_header_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.pbm")
            pathlib.Path(path).write_bytes(b"P4\n# GIMP\n8 1\n\x0f")
            self.assertEqual(badge_usb.read_pbm(path), (8, 1, b"\xf0"))

    def test_rejects_non_p4(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.pbm")
            pathlib.Path(path).write_bytes(b"P1\n8 1\n0 0 0 0 0 0 0 0\n")
            with self.assertRaises(ValueError):
                badge_usb.read_pbm(path)


class LocalEpoch(unittest.TestCase):
    def test_adds_utc_offset(self):
        if not hasattr(time, "tzset"):
            self.skipTest("sin time.tzset (Windows)")
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Etc/GMT+6"  # UTC-6, sin horario de verano
        time.tzset()
        try:
            self.assertEqual(badge_usb.local_epoch(1_000_000_000.9),
                             1_000_000_000 - 6 * 3600)
        finally:
            if old is None:
                del os.environ["TZ"]
            else:
                os.environ["TZ"] = old
            time.tzset()


if __name__ == "__main__":
    unittest.main()
