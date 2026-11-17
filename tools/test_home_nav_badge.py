#!/usr/bin/env python3
"""
test_home_nav_badge.py — Con un badge conectado: ←/→ en el gafete pasan entre
la plantilla y los slots llenos, y ↑/↓ abren Luces.

Llena y vacía slots (UPLD y `fs rm slotN.bin` de la consola), presiona
botones con `key` y revisa en cada paso el `home` de INFO y la pantalla
(`ui shot`): con un slot, el cuerpo es su imagen píxel a píxel; con la
plantilla, ninguna; el pie dice a la izquierda qué se ve solo si hay slots
llenos. Casos: todos vacíos, solo el slot 2, huecos (0 y 3), un slot que se
llena y otro que se vacía mientras se navega. Al terminar deja los slots y el
inicio como estaban. Se omite sin badge. Tarda ~2 min (refrescos completos).

Uso (en Linux, después de pyserial el navegador necesita VMIN=1: badge_usb ya
lo restaura al cerrar):
  python3 -m unittest tools/test_home_nav_badge.py -v
"""
import glob
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import badge_usb  # noqa: E402
from ui_shot import command as console, parse_shot  # noqa: E402

PORTS = glob.glob("/dev/serial/by-id/usb-Espressif_*")
T = -1  # La plantilla, como `home` de INFO
BAR = 14  # cfg::ui::BAR_HEIGHT: franja arriba y pie abajo
LABEL_W = 76  # A la izquierda de "A: menú" en el panel de 200
REFRESH_S = 3.0  # Refresco completo (~1.5 s) y el cuadro de después


def pattern(n, w, h):
    """Imagen distinta por slot: franjas de 4·(n+1) px, 1 = blanco."""
    row = (w + 7) // 8
    return bytes(0xFF if (y // (4 * (n + 1)) + x) % 2 else 0x00
                 for y in range(h) for x in range(row))


@unittest.skipUnless(PORTS, "sin badge conectado")
class HomeNavTest(unittest.TestCase):
    def setUp(self):
        self.badge = badge_usb.Badge(PORTS[0])
        info = self.badge.info()
        if info["home"] is None:
            self.badge.close()
            self.skipTest("el firmware no reporta home")
        self.w, self.h, self.count = info["w"], info["h"], info["slots"]
        self.original = info["home"]
        self.backup = {n: self.badge.read(n)
                       for n, u in enumerate(info["used"]) if u == "1"}
        self.images = [pattern(n, self.w, self.h) for n in range(self.count)]
        self.addCleanup(self.restore)
        self.key("b 1500")  # Al gafete

    def restore(self):
        try:
            for n in range(self.count):
                if n in self.backup:
                    self.badge.upload(n, self.backup[n])
                else:
                    self.rm(n)
            self.key("b 1500")  # UPLD abre el Marco encima
            self.badge.expect_ok(f"HOME {self.original}" if self.original >= 0
                                 else "HOME OFF")
            info = self.badge.info()
            used = "".join("1" if n in self.backup else "0"
                           for n in range(self.count))
            self.assertEqual((info["used"], info["home"]), (used, self.original))
        finally:
            self.badge.close()

    # --- Badge -----------------------------------------------------------------
    def key(self, name):
        reply = console(self.badge.port, f"key {name}")
        self.assertIn("OK", reply, f"key {name}")
        time.sleep(0.3)

    def rm(self, n):
        console(self.badge.port, f"fs rm slot{n}.bin")  # ERR si ya no estaba

    def stack(self):
        reply = console(self.badge.port, "ui", until="UI")
        return reply.split("pila=")[1].split()[0]

    def fill(self, full):
        """Deja llenos solo los slots de `full` y el gafete en la plantilla."""
        for n in range(self.count):
            if n in full:
                self.badge.upload(n, self.images[n])
            else:
                self.rm(n)
        self.key("b 1500")
        self.badge.expect_ok("HOME OFF")
        info = self.badge.info()
        self.assertEqual(info["used"], "".join(
            "1" if n in full else "0" for n in range(self.count)))
        time.sleep(REFRESH_S)

    def press(self, name):
        self.key(name)
        time.sleep(REFRESH_S)
        return self.badge.info()["home"]

    def shot(self):
        w, h, rows = parse_shot(console(self.badge.port, "ui shot"))
        self.assertEqual((w, h), (self.w, self.h))
        return rows

    # --- Pantalla -------------------------------------------------------------
    def body(self, rows):
        return [r for r in rows[BAR:self.h - BAR]]

    def slot_body(self, n):
        """El cuerpo de la imagen del slot n como lo da ui shot (1 = tinta)."""
        row = (self.w + 7) // 8
        img = self.images[n]
        return [[1 - ((img[y * row + x // 8] >> (7 - x % 8)) & 1)
                 for x in range(self.w)] for y in range(BAR, self.h - BAR)]

    def label(self, rows):
        return tuple(tuple(r[:LABEL_W]) for r in rows[self.h - BAR + 2:])

    def check(self, home, expected, full):
        """`home` de INFO y la pantalla corresponden a `expected`."""
        self.assertEqual(home, expected)
        rows = self.shot()
        body = self.body(rows)
        if expected == T:
            for n in full:
                self.assertNotEqual(body, self.slot_body(n),
                                    f"se ve el slot {n} y debía ser la plantilla")
        else:
            self.assertEqual(body, self.slot_body(expected),
                             f"no se ve el slot {expected}")
        label = self.label(rows)
        self.assertEqual(any(any(r) for r in label), bool(full),
                         "el pie solo dice qué se ve si hay slots llenos")
        return label

    def walk(self, full, steps):
        """Recorre `steps` [(botón, esperado)] y junta el rótulo de cada uno."""
        labels = {}
        for name, expected in steps:
            label = self.check(self.press(name), expected, full)
            labels.setdefault(expected, label)
            self.assertEqual(labels[expected], label,
                             f"rótulo distinto para {expected}")
        return labels

    # --- Casos ------------------------------------------------------------------
    def test_all_empty(self):
        self.fill(set())
        before = self.shot()
        self.check(T, T, set())
        for name in ("right", "left", "right"):
            self.check(self.press(name), T, set())
        self.assertEqual(self.shot(), before, "el gafete cambió sin slots")

    def test_only_slot_2(self):
        self.fill({2})
        labels = self.walk({2}, [("right", 2), ("right", T),
                                 ("left", 2), ("left", T)])
        self.assertNotEqual(labels[2], labels[T])

    def test_gaps(self):
        self.fill({0, 3})
        labels = self.walk({0, 3}, [("right", 0), ("right", 3), ("right", T),
                                    ("left", 3), ("left", 0), ("left", T)])
        self.assertEqual(len(set(labels.values())), 3, "un rótulo por elemento")

    def test_slot_changes_while_navigating(self):
        self.fill({0, 3})
        self.check(self.press("right"), 0, {0, 3})
        # La página sube una imagen al slot 1: abre el Marco; B regresa al
        # gafete, que sigue en el 0, y → ya pasa por el 1.
        self.badge.upload(1, self.images[1])
        self.assertEqual(self.stack().split(">")[-1], "frame")
        self.key("b")
        time.sleep(REFRESH_S)
        self.check(self.badge.info()["home"], 0, {0, 1, 3})
        self.check(self.press("right"), 1, {0, 1, 3})
        self.check(self.press("right"), 3, {0, 1, 3})
        # El slot en pantalla deja de estar lleno: al redibujar se ve la
        # plantilla (home.bin sigue en 3) y → sigue desde ahí.
        self.rm(3)
        self.key("a")  # Menú y de vuelta: el gafete se vuelve a dibujar
        self.key("b 1500")
        time.sleep(REFRESH_S)
        rows = self.shot()
        self.assertEqual(self.badge.info()["home"], 3)
        for n in (0, 1):
            self.assertNotEqual(self.body(rows), self.slot_body(n))
        self.assertTrue(any(any(r) for r in self.label(rows)))
        self.check(self.press("right"), 0, {0, 1})
        self.check(self.press("left"), T, {0, 1})

    def test_up_down_open_lights(self):
        self.fill({2})
        for name in ("up", "down"):
            self.key(name)
            self.assertEqual(self.stack().split(">")[-1], "luces", name)
            self.key("b 1500")
            self.assertEqual(self.stack(), "home")
        self.assertEqual(self.badge.info()["home"], T, "↑/↓ no cambian el inicio")


if __name__ == "__main__":
    unittest.main()
