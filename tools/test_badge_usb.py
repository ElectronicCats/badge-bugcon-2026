#!/usr/bin/env python3
"""
test_badge_usb.py — Pruebas de tools/badge_usb.py sin badge: la respuesta de
PWR (F4.7) tal como la escribe usb_protocol.cpp.

Uso (requiere pyserial, que badge_usb.py importa):
  python3 -m unittest tools/test_badge_usb.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import badge_usb  # noqa: E402

REPLY = ("OK estado=USB ACTIVO=30000 REPOSO=1200 SUENO=95000 USB=4000 "
         "ligero=12 dormido=900 profundo=1 completos=3 parciales=7 ir=5 "
         "apps=home:120000,menu:2500,penalty:0")


class ParsePower(unittest.TestCase):
    def test_reply(self):
        power = badge_usb.parse_power(REPLY)
        self.assertEqual(power["estado"], "USB")
        self.assertEqual(power["SUENO"], 95000)
        self.assertEqual(power["parciales"], 7)
        self.assertEqual(power["ir"], 5)
        self.assertEqual(list(power["apps"].items()),
                         [("home", 120000), ("menu", 2500), ("penalty", 0)])

    def test_error(self):
        with self.assertRaises(badge_usb.ProtocolError):
            badge_usb.parse_power("ERR badcmd")


if __name__ == "__main__":
    unittest.main()
