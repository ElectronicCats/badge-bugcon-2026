#!/usr/bin/env python3
"""
test_ui_shot.py — Pruebas de tools/ui_shot.py sin badge: espera de `command`,
validación de botones y el cierre del puerto (VMIN=1) en todos los caminos.

  python3 -m unittest tools/test_ui_shot.py -v
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import badge_link
import badge_usb
import ui_shot
from test_badge_link import BADGE, badge_on, comports
from test_badge_usb import FakePort

SHOT = b"OK ui\r\nSHOT 8 2\r\nff\r\n00\r\nOK\r\n"


def reply_for(**extra):
    def reply(line):
        if line in extra:
            return extra[line]
        if line == "INFO":
            return b"OK BB26 1.0.0 no=1 panel=200x200 album=0/400 slots=4 " \
                   b"current=0 used=0000\r\n"
        if line == "ui shot":
            return SHOT
        return b"OK\r\n"
    return reply


class Command(unittest.TestCase):
    def test_returns_on_until(self):
        port = FakePort(lambda line: b"log\r\nIRCOPA a=1\r\n")
        self.assertIn("IRCOPA", ui_shot.command(port, "ir", until="IRCOPA"))

    def test_err_ends_the_wait(self):
        port = FakePort(lambda line: b"ERR boton\r\n")
        self.assertIn("ERR boton", ui_shot.command(port, "key x"))

    def test_timeout_raises(self):
        port = FakePort()
        with mock.patch.object(ui_shot.time, "sleep"):
            with self.assertRaisesRegex(TimeoutError, "sin respuesta a 'ui"):
                ui_shot.command(port, "ui shot", timeout=0.05)


class Main(unittest.TestCase):
    def run_main(self, *argv, reply=None, connect_error=None):
        port = FakePort(reply or reply_for())
        serial_patch, sleep_patch = badge_on(port)
        vmin = mock.patch.object(badge_usb, "restore_vmin")
        err = io.StringIO()
        with serial_patch, sleep_patch, comports(BADGE), vmin as restore, \
                mock.patch.object(ui_shot.time, "sleep"), \
                mock.patch.object(sys, "argv", ["ui_shot.py", *argv]), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            code = ui_shot.main()
        return code, err.getvalue(), port, restore

    def test_happy_path_writes_png_and_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "c.png"
            code, _, port, restore = self.run_main("-o", str(out), "-k", "a b")
            self.assertEqual(code, 0)
            self.assertTrue(out.read_bytes().startswith(b"\x89PNG"))
        self.assertIn(b"key a\n", port.written)
        restore.assert_called_once()
        self.assertTrue(port.closed)

    def test_key_refused_restores(self):
        code, err, port, restore = self.run_main(
            "-k", "a", reply=reply_for(**{"key a": b"ERR ocupado\r\n"}))
        self.assertEqual(code, badge_link.EXIT_REJECTED)
        self.assertIn("key a: ERR ocupado", err)
        restore.assert_called_once()
        self.assertTrue(port.closed)

    def test_no_capture_restores(self):
        code, err, port, restore = self.run_main(
            reply=reply_for(**{"ui shot": b"OK\r\n"}))
        self.assertEqual(code, badge_link.EXIT_REJECTED)
        self.assertIn("no llegó la captura", err)
        restore.assert_called_once()

    def test_silence_restores(self):
        with mock.patch.object(ui_shot, "command", side_effect=TimeoutError(
                "sin respuesta a 'ui shot'")):
            code, err, port, restore = self.run_main()
        self.assertEqual(code, badge_link.EXIT_CONNECTION)
        restore.assert_called_once()

    def test_unknown_key_never_opens_the_port(self):
        with mock.patch.object(badge_link, "connect") as connect, \
                mock.patch.object(sys, "argv", ["ui_shot.py", "-k", "a x"]), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            with self.assertRaises(SystemExit) as cm:
                ui_shot.main()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("botón desconocido: x", err.getvalue())
        connect.assert_not_called()

    def test_no_badge_is_exit_3(self):
        err = io.StringIO()
        with comports(), mock.patch.object(sys, "argv", ["ui_shot.py"]), \
                contextlib.redirect_stderr(err):
            self.assertEqual(ui_shot.main(), badge_link.EXIT_CONNECTION)
        self.assertIn("No encuentro tu Badge", err.getvalue())


if __name__ == "__main__":
    unittest.main()
