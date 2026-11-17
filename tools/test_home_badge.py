#!/usr/bin/env python3
"""
test_home_badge.py — Con un badge conectado: HOME n / HOME OFF (imagen de
inicio). INFO lo refleja, sobrevive a un reinicio, y un slot vacío o inexistente
responde error. Se omite sin badge. No toca las imágenes de los slots; deja el
inicio como estaba.

Uso (en Linux, después de pyserial el navegador necesita VMIN=1: badge_usb ya
lo restaura al cerrar):
  python3 -m unittest tools/test_home_badge.py -v
"""
import glob
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import badge_usb  # noqa: E402

PORTS = glob.glob("/dev/serial/by-id/usb-Espressif_*")
REBOOT_WAIT_S = 5


@unittest.skipUnless(PORTS, "sin badge conectado")
class HomeTest(unittest.TestCase):
    def setUp(self):
        self.badge = badge_usb.Badge(PORTS[0])
        self.addCleanup(self.close)
        info = self.badge.info()
        if info["home"] is None:
            self.skipTest("el firmware no reporta home")
        self.original = info["home"]
        self.used = [i for i, u in enumerate(info["used"]) if u == "1"]
        self.empty = [i for i, u in enumerate(info["used"]) if u == "0"]
        if not self.used:
            self.skipTest("hace falta un slot con imagen")

    def close(self):
        try:
            if self.original >= 0:
                self.badge.expect_ok(f"HOME {self.original}")
            else:
                self.badge.expect_ok("HOME OFF")
        finally:
            self.badge.close()

    def reboot(self):
        # DTR a 0 con el puerto abierto deja DTR=0/RTS=1 = reset (PCB)
        p = self.badge.port
        p.dtr = False
        p.rts = True
        time.sleep(0.1)
        p.rts = False
        self.badge.close()
        time.sleep(REBOOT_WAIT_S)
        self.badge = badge_usb.Badge(PORTS[0])

    def test_home_roundtrip(self):
        n = self.used[0]
        self.badge.expect_ok(f"HOME {n}")
        self.assertEqual(self.badge.info()["home"], n)
        self.reboot()
        self.assertEqual(self.badge.info()["home"], n, "no sobrevivió al reinicio")
        self.badge.expect_ok("HOME OFF")
        self.assertEqual(self.badge.info()["home"], -1)

    def test_errors(self):
        self.assertEqual(self.badge.command("HOME 9"), "ERR badslot")
        if not self.empty:
            self.skipTest("no hay slot vacío para probar ERR empty")
        self.assertEqual(self.badge.command(f"HOME {self.empty[0]}"), "ERR empty")
        self.assertEqual(self.badge.info()["home"], self.original, "el error cambió el inicio")


if __name__ == "__main__":
    unittest.main()
