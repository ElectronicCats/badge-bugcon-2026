#!/usr/bin/env python3
"""
test_badge_upload.py — Pruebas de tools/badge_upload.py sin badge: protección
del espacio, validaciones, verificación con READ, vista previa y que ningún
camino mande un payload de otro tamaño.

Uso (requiere pyserial):
  python3 -m unittest tools/test_badge_upload.py -v
"""
import argparse
import contextlib
import os
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import badge_image  # noqa: E402
import badge_link  # noqa: E402
import badge_upload  # noqa: E402
from test_badge_usb import INFO_REPLY, make_badge  # noqa: E402

try:
    from PIL import Image
except ImportError:
    Image = None

IMAGE = bytes(range(256)) * 19 + bytes(136)  # 5000 B
assert len(IMAGE) == 5000


class FakeConsole:
    def __init__(self):
        self.lines = []

    def print(self, message, **kw):
        self.lines.append(message)

    @contextlib.contextmanager
    def status(self, message):
        yield

    def text(self):
        return "\n".join(self.lines)


class Run(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "a.bin").write_bytes(IMAGE)
        self.console = FakeConsole()

    def args(self, **kw):
        parser = argparse.ArgumentParser()
        badge_upload.add_options(parser)
        ns = parser.parse_args([])
        ns.port, ns.slot, ns.file = None, 0, str(self.dir / "a.bin")
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns

    def go(self, args, kind="upload", info=INFO_REPLY, read=None, confirm=None,
           upld="OK"):
        """run() sobre un badge falso; -> (código, puerto, mensajes de error)."""
        stored = []

        def reply(line):
            if line == "INFO":
                return (info + "\n").encode()
            if line.startswith("UPLD"):
                stored.append(IMAGE)
                return (upld + "\n").encode()
            if line.startswith("READ"):
                data = read(len(stored)) if read else self.last_payload(holder["port"])
                return b"OK %d\n" % len(data) + data
            return b"OK\n"

        holder = {}
        badge, port = make_badge(reply)
        holder["port"] = port
        err = mock.patch("sys.stderr", new=type("E", (), {
            "lines": [], "write": lambda s, t: s.lines.append(t),
            "flush": lambda s: None})())
        with err as e:
            code = badge_upload.run(args, kind, connect=lambda p: badge,
                                    console=self.console, confirm=confirm or (lambda q: True))
        return code, port, "".join(e.lines)

    @staticmethod
    def last_payload(port):
        sent = Run.payloads(port, "UPLD")
        return sent[-1] if sent else IMAGE

    @staticmethod
    def payloads(port, verb):
        """Payloads escritos tras cada línea `verb`."""
        w = port.written
        return [w[i + 1] for i, d in enumerate(w) if d.startswith(verb.encode() + b" ")
                or d == verb.encode() + b"\n"]

    def test_upload_verifies_and_reports(self):
        code, port, _ = self.go(self.args(slot=0))
        self.assertEqual(code, 0)
        self.assertEqual(self.payloads(port, "UPLD"), [IMAGE])
        self.assertIn(b"READ 0\n", port.written)
        self.assertIn("espacio 0", self.console.text())
        self.assertTrue(port.closed)

    def test_slot_out_of_range_sends_nothing(self):
        for slot in (-1, 4):
            code, port, err = self.go(self.args(slot=slot))
            self.assertEqual(code, 2)
            self.assertIn("4 espacios", err)
            self.assertEqual(self.payloads(port, "UPLD"), [])

    def test_occupied_slot_asks_first(self):
        asked = []
        code, port, _ = self.go(self.args(slot=0),  # used=1010: el 0 está ocupado
                                confirm=lambda q: asked.append(q) or False)
        self.assertEqual(code, 1)
        self.assertIn("espacio 0 ya tiene una imagen", asked[0])
        self.assertEqual(self.payloads(port, "UPLD"), [])

    def test_occupied_slot_replaced_when_confirmed_or_si(self):
        for kw, confirm in (({}, lambda q: True), ({"si": True}, lambda q: 1 / 0)):
            code, port, _ = self.go(self.args(slot=0, **kw), confirm=confirm)
            self.assertEqual(code, 0)
            self.assertEqual(len(self.payloads(port, "UPLD")), 1)

    def test_free_slot_does_not_ask(self):
        code, _, _ = self.go(self.args(slot=1), confirm=lambda q: 1 / 0)
        self.assertEqual(code, 0)

    def test_default_confirm_without_terminal(self):
        with mock.patch.object(badge_upload.sys.stdin, "isatty", return_value=False):
            with self.assertRaisesRegex(badge_image.ImageError, "--si"):
                badge_upload._confirm("¿Reemplazarla?")

    def test_mismatch_retries_once_then_fails(self):
        wrong = b"\xff" + IMAGE[1:]
        code, port, _ = self.go(self.args(slot=1),
                                read=lambda n: wrong if n == 1 else IMAGE)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.payloads(port, "UPLD")), 2)
        code, port, err = self.go(self.args(slot=1), read=lambda n: wrong)
        self.assertEqual(code, 1)
        self.assertIn("distinta", err)
        self.assertEqual(len(self.payloads(port, "UPLD")), 2)

    def test_slow_reply_warns(self):
        _, _, _ = self.go(self.args(slot=1), upld="OK slow=2100")
        self.assertIn("tardó en refrescar", self.console.text())

    def test_other_panel_refused(self):
        code, port, err = self.go(self.args(slot=1),
                                  info=INFO_REPLY.replace("200x200", "128x64"))
        self.assertEqual(code, 2)
        self.assertEqual(self.payloads(port, "UPLD"), [])

    def test_avatar_sends_96x96_without_read(self):
        (self.dir / "av.bin").write_bytes(bytes(1152))
        code, port, _ = self.go(self.args(file=str(self.dir / "av.bin")), "avatar")
        self.assertEqual(code, 0)
        self.assertEqual(self.payloads(port, "AVTR"), [bytes(1152)])
        self.assertNotIn(b"READ", b"".join(port.written))
        self.assertIn("no se pudo verificar", self.console.text())

    def test_wrong_size_never_reaches_the_port(self):
        (self.dir / "bad.bin").write_bytes(bytes(4999))
        connected = []
        with mock.patch("sys.stderr"):
            code = badge_upload.run(self.args(file=str(self.dir / "bad.bin")),
                                    "upload", connect=lambda p: connected.append(p),
                                    console=self.console)
        self.assertEqual((code, connected), (2, []))
        with self.assertRaises(badge_image.ImageError):
            badge_upload._check_size(bytes(4999), 200, 200)

    def test_solo_vista_does_not_open_the_port(self):
        out = self.dir / "v.png"
        code = badge_upload.run(self.args(solo_vista=True, vista=str(out)), "upload",
                                connect=lambda p: 1 / 0, console=self.console)
        self.assertEqual(code, 0)
        data = out.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(int.from_bytes(data[16:20], "big"), 400)  # 200 x2

    def test_preview_ink_where_bit_is_zero(self):
        # 0 = negro en el badge: solo el píxel (0, 0) lleva tinta
        out = self.dir / "p.png"
        badge_upload.save_preview(b"\x7f" + b"\xff" * 7, 8, 8, str(out), scale=1)
        data = out.read_bytes()
        size = int.from_bytes(data[33:37], "big")  # tras la firma y el IHDR
        raw = zlib.decompress(data[41:41 + size])
        pixels = [raw[1 + y * 9 + x] for y in range(8) for x in range(8)]
        self.assertEqual(pixels, [0] + [255] * 63)
    def test_connection_error_exit_code(self):
        def fail(port):
            raise badge_link.BadgeConnectionError("No encuentro tu Badge.")
        with mock.patch("sys.stderr"):
            code = badge_upload.run(self.args(), "upload", connect=fail,
                                    console=self.console)
        self.assertEqual(code, 3)

    @unittest.skipIf(Image is None, "falta Pillow")
    def test_converted_photo_is_exactly_5000_bytes(self):
        Image.new("RGB", (640, 480), "gray").save(self.dir / "f.jpg")
        code, port, _ = self.go(self.args(slot=1, file=str(self.dir / "f.jpg")))
        self.assertEqual(code, 0)
        self.assertEqual({len(p) for p in self.payloads(port, "UPLD")}, {5000})
        self.assertIn("Convirtiendo f.jpg (640×480) → 200×200, contener", self.console.text())


if __name__ == "__main__":
    unittest.main()
