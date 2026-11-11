#!/usr/bin/env python3
"""
test_badge_cli.py — Pruebas de PC de la CLI de badge_usb.py (sin badge): las
validaciones de la estampa y del notificador, la flag y los mensajes de cada
comando. Si una validación se afloja, estas pruebas fallan.

Uso (requiere pyserial y rich):
  python3 -m unittest tools/test_badge_cli.py -v
"""
import argparse
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import badge_usb  # noqa: E402
from test_badge_usb import INFO_REPLY, REPLY, make_badge  # noqa: E402

CARD64 = badge_usb.CARD_FIELDS.pack(
    1, 0, 42, b"Viejo", 3, 2, bytes([10, 20, 30, 40]), 1, 0, b"@viejo") + bytes(16)
ALBUM = bytes(16) + CARD64 + bytes(80)  # cabecera + una estampa
SLOT = bytes(range(256)) * 19 + bytes(136)  # 5000 B

DEFAULTS = dict(
    cmd=None, crudo=False, text=None, nick=None, team=None, pos=None,
    stats=None, handle=None, rgb=None, n=None, nombre=None, slot=None,
    output=None, line=None, file=None, vista=None, solo_vista=False,
    ajuste="contener", tramado="fs", umbral=128, invertir=False,
    ampliar=False, si=False, port=None)


def reply(line):
    if line == "INFO":
        return (INFO_REPLY + "\n").encode()
    if line == "ALBM":
        return b"OK %d\n" % len(ALBUM) + ALBUM
    if line == "PWR":
        return (REPLY + "\n").encode()
    if line.startswith("READ"):
        return b"OK %d\n" % len(SLOT) + SLOT
    return b"OK\n"


def console():
    from rich.console import Console

    return Console(file=io.StringIO(), force_terminal=False, width=100)


def args(**kw):
    values = dict(DEFAULTS)
    values.update(kw)
    return argparse.Namespace(**values)


def run(badge, **kw):
    """_run_command sobre un badge falso; -> (código, texto del console)."""
    out = console()
    code = badge_usb._run_command(badge, args(**kw), out)
    return code, out.file.getvalue()


class Stats(unittest.TestCase):
    def test_sum_200_is_valid(self):
        self.assertEqual(badge_usb.validate_stats([50, 50, 50, 50]), [50] * 4)

    def test_sum_201_says_by_how_much(self):
        with self.assertRaisesRegex(ValueError, "201.*pasas por 1"):
            badge_usb.validate_stats([50, 50, 50, 51])

    def test_over_99(self):
        with self.assertRaisesRegex(ValueError, "0 a 99"):
            badge_usb.validate_stats([100, 0, 0, 0])

    def test_not_four(self):
        with self.assertRaisesRegex(ValueError, "4 números"):
            badge_usb.validate_stats([1, 2, 3])


class TeamAndPos(unittest.TestCase):
    def test_valid_range(self):
        self.assertEqual(badge_usb.validate_team(-1), -1)
        self.assertEqual(badge_usb.validate_team(10), 10)
        self.assertEqual(badge_usb.validate_pos(-1), -1)
        self.assertEqual(badge_usb.validate_pos(4), 4)

    def test_out_of_range(self):
        with self.assertRaisesRegex(ValueError, "villa"):
            badge_usb.validate_team(11)
        with self.assertRaisesRegex(ValueError, "posición"):
            badge_usb.validate_pos(5)


class StickerText(unittest.TestCase):
    def test_eight_n_tildes_is_16_bytes(self):
        self.assertEqual(len(badge_usb.validate_sticker_text("ñ" * 8, 16, "apodo")),
                         16)

    def test_nine_n_tildes_is_too_long(self):
        with self.assertRaisesRegex(ValueError, "cuentan doble"):
            badge_usb.validate_sticker_text("ñ" * 9, 16, "apodo")

    def test_control_characters_rejected(self):
        with self.assertRaisesRegex(ValueError, "control"):
            badge_usb.validate_sticker_text("a\nb", 16, "apodo")


class LedColor(unittest.TestCase):
    def test_names(self):
        self.assertEqual(badge_usb.validate_led("rojo"), "ff0000")
        self.assertEqual(badge_usb.validate_led("apagar"), "000000")

    def test_hex_with_and_without_hash(self):
        self.assertEqual(badge_usb.validate_led("ff0000"), "ff0000")
        self.assertEqual(badge_usb.validate_led("#00FF00"), "00ff00")

    def test_invalid(self):
        for bad in ("ff00", "zzzzzz", "#ff0000ff"):
            with self.assertRaisesRegex(ValueError, "no es un color"):
                badge_usb.validate_led(bad)


class Flag(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(badge_usb.validate_flag("bandera{secreta}"),
                         "bandera{secreta}")

    def test_empty_and_edges(self):
        for bad in ("", " bandera", "bandera "):
            with self.assertRaisesRegex(ValueError, "vacía"):
                badge_usb.validate_flag(bad)

    def test_control_characters(self):
        with self.assertRaisesRegex(ValueError, "control"):
            badge_usb.validate_flag("bandera\nsecreta")


class Info(unittest.TestCase):
    def test_table_shows_dorsal_album_and_slots(self):
        badge, _ = make_badge(reply)
        code, text = run(badge, cmd="info")
        self.assertEqual(code, 0)
        for word in ("Dorsal", "42", "Álbum", "25/400", "Marco", "0 ocupado",
                     "1 libre", "Versión", "1.0.0"):
            self.assertIn(word, text)

    def test_crudo_prints_key_value_to_stdout(self):
        badge, _ = make_badge(reply)
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code, _ = run(badge, cmd="info", crudo=True)
        self.assertEqual(code, 0)
        self.assertIn("fw=1.0.0", out.getvalue())
        self.assertIn("no=42", out.getvalue())


class Time(unittest.TestCase):
    def test_shows_local_time_and_advice(self):
        badge, port = make_badge(reply)
        with mock.patch.object(badge_usb, "local_epoch", return_value=1_800_000_000):
            code, text = run(badge, cmd="time")
        self.assertEqual(code, 0)
        self.assertIn("Hora puesta:", text)
        self.assertIn("barra de arriba", text)
        self.assertIn(b"TIME 1800000000\n", port.written)


class NickAndCard(unittest.TestCase):
    def test_nick_sends_and_rejects_control(self):
        badge, port = make_badge(reply)
        code, text = run(badge, cmd="nick", text="Ñandú")
        self.assertEqual(code, 0)
        self.assertIn(b"NICK \xc3\x91and\xc3\xba\n", port.written)
        self.assertIn("Apodo puesto: Ñandú", text)

        badge, port = make_badge(reply)
        with self.assertRaisesRegex(ValueError, "control"):
            run(badge, cmd="nick", text="a\nb")
        self.assertEqual(port.written, [])

    def test_card_sends_and_summarizes(self):
        badge, port = make_badge(reply)
        code, text = run(badge, cmd="card", nick="Nuevo", team=2, pos=4,
                         stats=[60, 40, 70, 30], handle="@nuevo")
        self.assertEqual(code, 0)
        card = [w for w in port.written if w == b"CARD\n"]
        self.assertEqual(len(card), 1)
        self.assertIn("Apodo: Nuevo", text)
        self.assertIn("Villa: Rookie", text)
        self.assertIn("Posición: Pentester", text)
        self.assertIn("Estadísticas: 60/40/70/30", text)
        self.assertIn("Handle: @nuevo", text)

    def test_card_rejects_bad_stats_before_sending(self):
        badge, port = make_badge(reply)
        with self.assertRaisesRegex(ValueError, "pasas por 1"):
            run(badge, cmd="card", stats=[50, 50, 50, 51])
        self.assertNotIn(b"CARD\n", port.written)

    def test_card_rejects_bad_team_before_sending(self):
        badge, port = make_badge(reply)
        with self.assertRaisesRegex(ValueError, "villa"):
            run(badge, cmd="card", team=300)
        self.assertNotIn(b"CARD\n", port.written)


class LedAndFlag(unittest.TestCase):
    def test_led_name_is_sent_as_hex(self):
        badge, port = make_badge(reply)
        code, text = run(badge, cmd="led", rgb="rojo")
        self.assertEqual(code, 0)
        self.assertIn(b"LED ff0000\n", port.written)
        self.assertIn("Luces en #ff0000", text)

    def test_led_invalid_sends_nothing(self):
        badge, port = make_badge(reply)
        with self.assertRaisesRegex(ValueError, "no es un color"):
            run(badge, cmd="led", rgb="rrggbb")
        self.assertEqual(port.written, [])

    def test_flag_ok(self):
        badge, _ = make_badge(reply)
        code, text = run(badge, cmd="flag", text="bandera{x}")
        self.assertEqual(code, 0)
        self.assertIn("etapa", text)

    def test_flag_wrong_raises_protocol_error(self):
        badge, _ = make_badge(lambda line: b"ERR wrong\n")
        with self.assertRaises(badge_usb.ProtocolError):
            run(badge, cmd="flag", text="bandera{x}")

    def test_flag_rejects_control(self):
        badge, port = make_badge(reply)
        with self.assertRaisesRegex(ValueError, "control"):
            run(badge, cmd="flag", text="a\nb")
        self.assertEqual(port.written, [])


class AlbumAndRest(unittest.TestCase):
    def test_album_warns_and_counts(self):
        badge, _ = make_badge(reply)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "album.bin")
            code, text = run(badge, cmd="album", output=out)
            self.assertEqual(code, 0)
            self.assertEqual(open(out, "rb").read(), ALBUM)
        self.assertIn("apodos y handles", text)
        self.assertIn("1 estampas", text)

    def test_pwr_prints_key_value(self):
        badge, _ = make_badge(reply)
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            code, _ = run(badge, cmd="pwr")
        self.assertEqual(code, 0)
        self.assertIn("estado=USB", out.getvalue())

    def test_clr_and_tokens_report(self):
        badge, _ = make_badge(reply)
        code, text = run(badge, cmd="clr")
        self.assertEqual(code, 0)
        self.assertIn("blanco", text)

        badge, _ = make_badge(reply)
        code, text = run(badge, cmd="tokens", n=[1, 2, 3, 4, 5, 6], nombre=None)
        self.assertEqual(code, 0)
        self.assertIn("Tokens enviados", text)


class OutputFile(unittest.TestCase):
    def test_unwritable_output_is_a_one_line_error(self):
        badge, _ = make_badge(reply)
        out = console()
        with mock.patch.object(badge_usb, "_parser") as parser, \
                mock.patch("badge_link.connect", return_value=badge), \
                mock.patch("badge_usb._console", return_value=out):
            parser.return_value.parse_args.return_value = args(
                cmd="read", slot=0, output="/nonexistent-dir/x.bin")
            code = badge_usb.main()
        self.assertEqual(code, 2)
        self.assertIn("no pude guardar", out.file.getvalue())


class Help(unittest.TestCase):
    def test_lists_the_readme_commands(self):
        help_text = badge_usb._parser().format_help()
        for word in ("info", "time", "nick", "card", "avatar", "upload",
                     "album", "led", "flag"):
            self.assertIn(word, help_text)

    def test_documents_exit_codes(self):
        self.assertIn("Códigos de salida", badge_usb._parser().format_help())


if __name__ == "__main__":
    unittest.main()
