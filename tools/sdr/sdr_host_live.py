#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prueba en vivo de la sesión del visor (services/sdr/sdr_host) por el CDC.

Necesita un badge o DevKit con USB.
Uso: python3 tools/sdr/sdr_host_live.py [puerto] [--idle]
Abre la sesión con `sdr host`, habla el protocolo de ráfagas como el visor
(identidad, ganancia, ráfagas con CRC a 80/40/16 MS/s, RXRUN, espectro), la
cierra con RELEASE y comprueba que la consola y usb_protocol siguen sin reset.
--idle espera además el minuto de silencio que cierra una sesión abandonada.
"""
import re, struct, sys, time, zlib
import serial

args = [a for a in sys.argv[1:] if not a.startswith("--")]
P = args[0] if args else "/dev/ttyACM0"
s = serial.Serial(P, 115200, timeout=0.2)  # Sin tocar DTR/RTS: no reinicia
time.sleep(0.5); s.reset_input_buffer()
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

def exact(n, timeout=10):
    out = b""; t = time.time()
    while len(out) < n and time.time() - t < timeout:
        out += s.read(n - len(out))
    return out

def ask(cmd, timeout=5):
    s.write((cmd + "\n").encode()); return line(timeout)

def console(cmd, prefix, timeout=5):
    s.write((cmd + "\r\n").encode()); t = time.time()
    while time.time() - t < timeout:
        l = line(timeout)
        if l.startswith(prefix): return l
    return ""

# Una sesión vieja se cierra con RELEASE; luego el receptor encendido por la consola
s.write(b"RELEASE\n"); time.sleep(0.5); s.reset_input_buffer()
check("consola antes", console("sdr", "SDR ").startswith("SDR"), "")
console("sdr off", "OK")
check("host sin receptor lo enciende", console("sdr host", "OK host", 10) == "OK host")

sync = ask("SYNC 1792629170881")
check("SYNC devuelve el nonce", sync == "SYNC 1792629170881", sync)
info = ask("INFO")
check("INFO identifica S3SDR", "S3SDR 6 burst" in info, info)
check("CAPS", len(ask("CAPS")) > 0)
check("RANGE?", len(ask("RANGE?")) > 0)
check("FREQ 2437", ask("FREQ 2437") == "OK")
check("FREQ fuera de rango", ask("FREQ 5000").startswith("ERR"))
check("GAIN MANUAL 40", ask("GAIN MANUAL 40") == "OK")
check("GAIN?", "40" in ask("GAIN?"))
check("GAIN 99", ask("GAIN MANUAL 99").startswith("ERR"))
check("GAIN HARDWARE", ask("GAIN HARDWARE") == "OK")
check("comando desconocido", ask("NOPE").startswith("ERR"))
check("línea larga", ask("X" * 200).startswith("ERR"))

def burst(cmd, bits, n):
    s.write((cmd + "\n").encode()); h = line()
    m = re.match(r"^DATA (\d+) ([0-9a-fA-F]{1,8}) (\d+)$", h)
    if not m or int(m.group(1)) != n: return False, h
    data = exact(n * bits // 8)
    return zlib.crc32(data) == int(m.group(2), 16) and len(data) == n * bits // 8, h

for name, rate in (("80", 0), ("40", 1), ("16", 6)):
    for fmt, bits in (("CAP20", 20), ("CAP16", 16)):
        bad = 0
        for ch in (2412, 2437, 2462):
            ask("FREQ %d" % ch)
            for _ in range(10):
                ok, h = burst("%s 16380 %d" % (fmt, rate), bits, 16380)
                bad += not ok
        check("%s a %s MS/s: 30 ráfagas con CRC" % (fmt, name), bad == 0, "malas=%d" % bad)

check("CAP20 con tasa inválida", ask("CAP20 4096 3").startswith("ERR"))
check("CAP20 con muestras de menos", ask("CAP20 10 0").startswith("ERR"))

# RXRUN: 5 ráfagas de corrido y END
s.write(b"RXRUN 4096 0 5 20\n"); good = 0
for _ in range(5):
    h = line(); m = re.match(r"^DATA (\d+) ([0-9a-fA-F]{1,8}) (\d+)$", h)
    if m:
        data = exact(4096 * 20 // 8); good += zlib.crc32(data) == int(m.group(2), 16)
check("RXRUN 5 ráfagas con CRC", good == 5 and line() == "END", "buenas=%d" % good)
s.write(b"RXRUN 4096 0 1000 20\n"); line(); exact(4096 * 20 // 8)
s.write(b"\n"); time.sleep(0.5)  # Una línea vacía corta el flujo
while s.read(65536): pass
check("RXRUN cortado por el cliente", ask("INFO").startswith("S3SDR"))

# Espectro en chip: SPC1 hasta que el cliente corta
check("SPECINFO?", len(ask("SPECINFO?")) > 0)
s.write(b"SPEC 0 1 1 0 1 1024\n"); h = line(); print("   SPEC ->", h)
frames = 0; t = time.time()
while time.time() - t < 3:
    if s.read(4096): frames += 1
s.write(b"\n"); time.sleep(0.5)
tail = s.read(65536)
check("SPEC transmite y se corta", frames > 3 and b"SPECEND" in tail, "lecturas=%d" % frames)
s.reset_input_buffer()

if "--idle" in sys.argv:
    t = time.time()
    while console("sdr", "SDR ", 3) == "" and time.time() - t < 80: pass
    check("cierre por silencio", 58 < time.time() - t < 75, "%.0f s" % (time.time() - t))
else:
    check("RELEASE", ask("RELEASE") == "OK")
    time.sleep(0.5); s.reset_input_buffer()

st = console("sdr", "SDR ")
check("consola vuelve sin reset (host=0, receptor apagado: lo encendió la sesión)",
      "host=0" in st and "on=0" in st, st)
check("usb_protocol vuelve", console("INFO", "OK BB26").startswith("OK BB26"))
print(st)
# Con el receptor ya encendido por la consola, la sesión no lo apaga
check("sdr on", console("sdr on", "OK", 10) == "OK")
check("host con el receptor encendido", console("sdr host", "OK host") == "OK host")
check("RELEASE otra vez", ask("RELEASE") == "OK"); time.sleep(0.5); s.reset_input_buffer()
check("el receptor sigue encendido", "on=1" in console("sdr", "SDR ") and
      console("sdr cap 4096", "CAP ").startswith("CAP "))
console("sdr off", "OK")
print("\n%d fallas" % len(fails)); sys.exit(1 if fails else 0)
