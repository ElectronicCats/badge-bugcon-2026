#!/usr/bin/env python3
"""
test_badge_image.py — Pruebas de tools/badge_image.py sin badge. Las que
convierten imágenes se saltan si no hay Pillow.

Uso:
  python3 -m unittest tools/test_badge_image.py -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import badge_image  # noqa: E402
from badge_image import ImageError  # noqa: E402

try:
    from PIL import Image
except ImportError:
    Image = None

W = H = 200
ROW = W // 8


def white(data, x, y, w=W):
    """Bit (x, y) de la imagen del badge: True = blanco."""
    return bool(data[y * ((w + 7) // 8) + x // 8] >> (7 - x % 8) & 1)


class TmpDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def path(self, name):
        return str(self.dir / name)


class RawInput(TmpDir):
    def test_bin_exact_and_wrong_size(self):
        Path(self.path("a.bin")).write_bytes(b"\x55" * 5000)
        self.assertEqual(badge_image.read_raw(self.path("a.bin"), W, H), b"\x55" * 5000)
        Path(self.path("b.bin")).write_bytes(b"\x55" * 4999)
        with self.assertRaisesRegex(ImageError, "4999 B.*5000 B"):
            badge_image.read_raw(self.path("b.bin"), W, H)

    def test_unknown_extension(self):
        Path(self.path("README.md")).write_bytes(b"x" * 5000)
        with self.assertRaises(ImageError):
            badge_image.read_raw(self.path("README.md"), W, H)

    def test_pbm_inverts_and_ignores_extension_case(self):
        Path(self.path("a.PBM")).write_bytes(b"P4\n# nota\n8 2\n" + b"\x0f\xff")
        self.assertEqual(badge_image.read_raw(self.path("a.PBM"), 8, 2), b"\xf0\x00")

    def test_pbm_truncated_or_header_only(self):
        Path(self.path("t.pbm")).write_bytes(b"P4\n200 200\n" + b"\x00" * 100)
        with self.assertRaisesRegex(ImageError, "espera 5000 B"):
            badge_image.read_raw(self.path("t.pbm"), W, H)
        Path(self.path("h.pbm")).write_bytes(b"P4\n")  # no debe colgarse
        with self.assertRaises(ImageError):
            badge_image.read_raw(self.path("h.pbm"), W, H)

    def test_pbm_wrong_dimensions(self):
        Path(self.path("d.pbm")).write_bytes(b"P4\n8 1\n\x00")
        with self.assertRaisesRegex(ImageError, "8x1.*200x200"):
            badge_image.read_raw(self.path("d.pbm"), W, H)


@unittest.skipIf(Image is None, "falta Pillow")
class Convert(TmpDir):
    def save(self, name, img, **kw):
        img.save(self.path(name), **kw)
        return self.path(name)

    def test_always_exact_size_both_targets(self):
        p = self.save("a.png", Image.new("L", (300, 77), 0))
        self.assertEqual(len(badge_image.prepare_image(p, W, H)), 5000)
        self.assertEqual(len(badge_image.prepare_image(p, 96, 96)), 1152)

    def test_pixel_00_is_msb_of_byte_0_and_zero_means_black(self):
        img = Image.new("L", (W, H), 255)
        img.putpixel((0, 0), 0)
        p = self.save("a.png", img)
        for dither in ("fs", "umbral"):
            data = badge_image.prepare_image(p, W, H, dither=dither)
            self.assertEqual(data[0], 0x7F)
            self.assertEqual(data[1:], b"\xff" * 4999)

    def test_contener_bands_cubrir_fills(self):
        p = self.save("a.png", Image.new("L", (4000, 3000), 0))
        data = badge_image.prepare_image(p, W, H)  # 200x150 centrado
        self.assertEqual(data[:25 * ROW], b"\xff" * 25 * ROW)
        self.assertEqual(data[25 * ROW:175 * ROW], b"\x00" * 150 * ROW)
        self.assertEqual(data[175 * ROW:], b"\xff" * 25 * ROW)
        self.assertEqual(badge_image.prepare_image(p, W, H, fit="cubrir"),
                         b"\x00" * 5000)

    def test_small_image_centered_not_enlarged_unless_asked(self):
        p = self.save("a.png", Image.new("L", (50, 50), 0))
        data = badge_image.prepare_image(p, W, H)
        self.assertFalse(white(data, 75, 75))
        self.assertFalse(white(data, 124, 124))
        self.assertTrue(white(data, 74, 100))
        self.assertTrue(white(data, 125, 100))
        self.assertEqual(badge_image.prepare_image(p, W, H, enlarge=True),
                         b"\x00" * 5000)

    def test_exif_rotation_is_respected(self):
        img = Image.new("L", (100, 50), 255)
        img.paste(0, (0, 0, 50, 50))  # mitad izquierda negra
        exif = Image.Exif()
        exif[0x0112] = 6  # girar 90° a la derecha: la mitad negra queda arriba
        p = self.save("a.jpg", img, exif=exif, quality=95)
        data = badge_image.prepare_image(p, W, H)  # queda de 50x100, centrada
        self.assertFalse(white(data, 100, 60))
        self.assertTrue(white(data, 100, 140))

    def test_transparency_becomes_white(self):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        img.paste((0, 0, 0, 255), (0, 0, 100, 100))
        data = badge_image.prepare_image(self.save("a.png", img), W, H)
        self.assertFalse(white(data, 50, 50))
        self.assertTrue(white(data, 150, 150))

    def test_threshold_matches_configurator(self):
        # Bandas de 50 px con grises 0, 127, 128, 255 (>= umbral = blanco)
        img = Image.new("L", (W, H))
        for i, v in enumerate((0, 127, 128, 255)):
            img.paste(v, (50 * i, 0, 50 * i + 50, H))
        data = badge_image.prepare_image(self.save("a.png", img), W, H,
                                         dither="umbral", threshold=128)
        self.assertEqual([white(data, x, 10) for x in (25, 75, 125, 175)],
                         [False, False, True, True])

    def test_autolevels_stretch_a_low_contrast_photo(self):
        # Grises 130 y 200 (ambos pasan el umbral 128 sin autoniveles) y
        # unos pocos píxeles extremos que el recorte del 1 % debe ignorar
        img = Image.new("L", (W, H), 200)
        img.paste(130, (0, 0, 100, H))
        img.paste(0, (0, 199, 50, 200))
        img.paste(255, (150, 199, 200, 200))
        data = badge_image.prepare_image(self.save("a.png", img), W, H,
                                         dither="umbral", threshold=128)
        self.assertEqual([white(data, 50, 10), white(data, 150, 10)], [False, True])

    def test_invert(self):
        p = self.save("a.png", Image.new("L", (W, H), 0))
        self.assertEqual(badge_image.prepare_image(p, W, H, invert=True),
                         b"\xff" * 5000)

    def test_bad_inputs_are_image_errors(self):
        Path(self.path("a.png")).write_bytes(b"no soy una imagen")
        with self.assertRaisesRegex(ImageError, "no pude leer"):
            badge_image.prepare_image(self.path("a.png"), W, H)
        p = self.save("b.png", Image.new("L", (8, 8)))
        for kw in ({"fit": "x"}, {"dither": "x"}, {"threshold": 256}):
            with self.assertRaises(ImageError):
                badge_image.prepare_image(p, W, H, **kw)

    def test_load_for_badge_routes(self):
        raw = self.path("a.pbm")
        Path(raw).write_bytes(b"P4\n200 200\n" + b"\x00" * 5000)
        self.assertEqual(badge_image.load_for_badge(raw, W, H), b"\xff" * 5000)
        # PBM de otro tamaño: se convierte; .bin de otro tamaño: error
        Path(self.path("s.pbm")).write_bytes(b"P4\n8 8\n" + b"\x00" * 8)
        self.assertEqual(len(badge_image.load_for_badge(self.path("s.pbm"), W, H)), 5000)
        Path(self.path("x.bin")).write_bytes(b"\x00" * 10)
        with self.assertRaises(ImageError):
            badge_image.load_for_badge(self.path("x.bin"), W, H)


if __name__ == "__main__":
    unittest.main()
