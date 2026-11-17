#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prueba en vivo de la apertura de la sesión del visor sin consola.

Necesita un badge o DevKit con USB.
Uso: python3 tools/sdr/sdr_viewer_live.py [puerto]
1. Auto-arranque: el primer `SYNC <nonce>` nada más abrir el puerto (dentro de
   la ventana de guarda de usb_protocol) abre la sesión y se contesta; luego
   otro SYNC fuera de la guarda. RELEASE devuelve la consola y usb_protocol.
2. App SDR: se llega por teclas (Menú > Herramientas > SDR), mantener A abre
   la sesión y RELEASE la cierra sin salir de la app.
"""
import sys, time
import serial

P = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM1"
s = serial.Serial(P, 115200, timeout=0.2)  # Sin tocar DTR/RTS: no reinicia
fails = []

def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, info); cond or fails.append(name)

def line(timeout=5):
    out = b""; t = time.time()
    while time.time() - t < timeout:
        c = s.read(1)
        if c == b"\n":
            if out.strip(): return out.decode(errors="replace").strip()
            out = b""
        elif c: out += c
    return out.decode(errors="replace").strip()

# Los logs del badge y el eco del arranque llegan por el mismo puerto: se busca
# la línea que empieza con `prefix`, no la primera.
def console(cmd, prefix, timeout=5, end="\r\n"):
    s.write((cmd + end).encode()); t = time.time()
    while time.time() - t < timeout:
        l = line(timeout)
        if l.startswith(prefix): return l
    return ""

def ask(cmd, prefix, timeout=5):
    return console(cmd, prefix, timeout, "\n")

def ui():
    return console("ui", "UI ")

# 1. SYNC nada más abrir el puerto, como el visor (sin esperar la guarda).
sync = ask("SYNC 1792629170881", "SYNC ")
check("SYNC en la guarda abre la sesión", sync == "SYNC 1792629170881", sync)
check("INFO identifica S3SDR", ask("INFO", "S3SDR 6 burst") != "")
check("RELEASE", ask("RELEASE", "OK") == "OK")
time.sleep(0.5); s.reset_input_buffer()
st = console("sdr", "SDR ")
check("consola de vuelta, receptor apagado", "on=0 host=0" in st, st)
check("usb_protocol de vuelta", console("INFO", "OK BB26") != "")

# SYNC fuera de la guarda (puerto ya abierto).
check("SYNC tras la guarda abre la sesión", ask("SYNC 7", "SYNC ") == "SYNC 7")
check("RELEASE", ask("RELEASE", "OK") == "OK")
time.sleep(0.5); s.reset_input_buffer()

# 2. La app: gafete > A (menú) > Herramientas > SDR. El menú y la rueda de
# Herramientas recuerdan dónde quedaron: se deduce la posición con `ui`.
MENU = ["card", "album", "ir", "games", "escritorio", "challenges", "settings",
        "agenda", "about"]
def key(k, ms=0):
    console("key %s %d" % (k, ms) if ms else "key " + k, "OK"); time.sleep(0.4)
def top():
    return ui().split()[1].split("=")[1].split(">")[-1]
key("b", 1500); time.sleep(1)  # Al gafete
key("a"); key("a")              # Menú y la entrada que estaba seleccionada
idx = MENU.index(top()) if top() in MENU else -1
key("b")
for _ in range((MENU.index("escritorio") - idx) % len(MENU)):
    key("right")
key("a")
for _ in range(5):              # Rueda de 5 vistas: A solo abre la app en SDR
    key("a"); time.sleep(0.4)
    if top() == "sdr": break
    key("right")
u = ui()
check("app sdr abierta", "sdr" in u.split()[1], u)
st = console("sdr", "SDR ")
check("receptor encendido por la app", "on=1 host=0" in st, st)
key("a", 1500)  # Mantener A: abre el visor
time.sleep(0.5)  # La ráfaga del A corto y su log
check("mantener A abre la sesión", ask("INFO", "S3SDR 6 burst") != "")
check("RELEASE", ask("RELEASE", "OK") == "OK")
time.sleep(0.5); s.reset_input_buffer()
st = console("sdr", "SDR ")
check("receptor sigue (lo encendió la app)", "on=1 host=0" in st, st)
key("b"); time.sleep(0.5)
u = ui()
check("B sale a Herramientas", "sdr" not in u.split()[1], u)
st = console("sdr", "SDR ")
check("receptor apagado al salir", "on=0" in st, st)
key("b", 1500)

print("\nFALLAS:", fails if fails else "ninguna")
sys.exit(1 if fails else 0)
