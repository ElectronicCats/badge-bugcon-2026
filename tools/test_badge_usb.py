#!/usr/bin/env python3
"""
test_badge_usb.py — Pruebas de tools/badge_usb.py sin badge: la respuesta de
PWR tal como la escribe usb_protocol.cpp y restore_vmin() con el tty
ya desconectado.

Uso (requiere pyserial, que badge_usb.py importa):
  python3 -m unittest tools/test_badge_usb.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import badge_usb  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
