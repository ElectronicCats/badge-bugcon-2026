#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prueba en vivo del receptor SDR (services/sdr/sdr_rx) por la consola.

Necesita un badge o DevKit con USB.
Uso: python3 tools/sdr/sdr_rx_live.py [/dev/serial/by-id/...]
Revisa la exclusión con el AP, 300 ráfagas en los canales 1-13 a 80/40/16
MS/s, la ganancia forzada, el espectro de un canal y el heap en ciclos on/off.
"""
import serial, time, sys, re
import numpy as np
P = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
s = serial.Serial(P, 115200, timeout=0.2)
time.sleep(2.5); s.reset_input_buffer()

def cmd(line, until=("OK", "ERR", "CAP ", "SDR ", "PWR", "WIFI "), timeout=8, lines=False):
    s.write((line + "\r\n").encode()); out = []; t = time.time(); buf = b""
    while time.time() - t < timeout:
        buf += s.read(4096)
        while b"\n" in buf:
            l, buf = buf.split(b"\n", 1); l = l.decode(errors="replace").strip()
            if not l: continue
            out.append(l)
            if any(l.startswith(u) for u in until) and not (lines and not l.startswith(("OK", "ERR"))):
                return out
    return out

fails = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, info); cond or fails.append(name)

r = cmd("sdr"); print(r[-1] if r else "(sin respuesta)")
if not r or not r[-1].startswith("SDR"):
    sys.exit("el firmware no trae el receptor (¿firmware viejo?)")
check("cap while off", cmd("sdr cap")[-1].startswith("ERR"))
cmd("wifi on", timeout=10)
check("sdr refused with AP", cmd("sdr on")[-1].startswith("ERR"))
cmd("wifi off")
check("sdr on", cmd("sdr on", timeout=10)[-1] == "OK")
check("dump without burst", cmd("sdr dump")[-1].startswith("ERR"))
check("AP refused with sdr", cmd("wifi on", timeout=10)[-1].startswith("ERR"))
r = cmd("sdr"); print(r[-1])
r = cmd("pwr", until=("OK", "ERR", "PWR", "POWER", "power")); print(" | ".join(r))
for rate in (80, 40, 16):
    l = cmd(f"sdr cap 16380 {rate}")[-1]; print(l)
    check(f"cap 16380 @{rate}", l.startswith("CAP"))
check("bad rate", cmd("sdr cap 100 20")[-1].startswith("ERR"))
check("too many", cmd("sdr cap 16381")[-1].startswith("ERR"))
check("bad freq", cmd("sdr freq 2413")[-1].startswith("ERR"))
ok = 0; us = {}
for k in range(300):
    ch = 1 + k % 13; rate = (80, 40, 16)[k % 3]
    cmd(f"sdr freq {2407 + 5*ch}")
    l = cmd(f"sdr cap 16380 {rate}")[-1]
    if l.startswith("CAP"):
        ok += 1; us.setdefault(rate, []).append(int(re.search(r"us=(\d+)", l).group(1)))
print("after 300:", cmd("sdr")[-1])
check("300 bursts", ok == 300, f"{ok}/300 " + " ".join(f"{r}:{min(v)}-{max(v)}us" for r, v in us.items()))
cmd("sdr freq 2437")
for g in ("20", "60", "auto"):
    cmd(f"sdr gain {g}"); l = cmd("sdr cap 4096")[-1]; print("gain", g, l)
# Spectrum: strongest of 20 bursts
best = None
for _ in range(20):
    l = cmd("sdr cap 4096")[-1]
    m = re.search(r"rms=([\d.]+)", l)
    if m and (best is None or float(m.group(1)) > best[0]):
        r = cmd("sdr raw", lines=True, timeout=15)
        iq = np.array([[int(x) for x in v.split()[:2]] for v in r if re.match(r"^-?\d+ -?\d+ \d+$", v)])
        best = (float(m.group(1)), iq)
iq = best[1]; z = (iq[:, 0] - iq[:, 0].mean()) + 1j * (iq[:, 1] - iq[:, 1].mean())
P = np.abs(np.fft.fftshift(np.fft.fft(z * np.hanning(len(z))))) ** 2
f = np.fft.fftshift(np.fft.fftfreq(len(z), 1 / 80.0))
inb = 10*np.log10(P[np.abs(f) < 9].mean()); outb = 10*np.log10(P[np.abs(f) > 15].mean())
check("spectrum in-band > out-of-band", inb - outb > 10, f"n={len(z)} rms={best[0]} in-out={inb-outb:.1f} dB")
print("after raw:", cmd("sdr")[-1])
import zlib
for n, rate in ((16380, 80), (4096, 40), (1000, 16)):
    cmd(f"sdr cap {n} {rate}")
    r = cmd("sdr dump", until=("OK", "ERR"), timeout=15)
    h = re.match(r"DUMP mhz=2437 n=(\d+) msps=(\d+) crc=([0-9a-f]{8})$", r[0]) if r else None
    # Cada palabra va en hex como número; la memoria la guarda little-endian
    raw = b"".join(bytes.fromhex(w)[::-1] for l in r[1:-1] for w in re.findall(r"[0-9a-f]{8}", l))
    check(f"dump {n}@{rate}", bool(h) and r[-1] == "OK" and int(h[1]) == n and int(h[2]) == rate
          and len(raw) == 4 * n and zlib.crc32(raw) == int(h[3], 16), r[0] if r else "")
check("sdr off", cmd("sdr off")[-1] == "OK")
check("dump after off", cmd("sdr dump")[-1].startswith("ERR"))
r = cmd("sdr"); print(r[-1]); heap1 = int(re.search(r"heap=(\d+)", r[-1]).group(1))
check("AP after sdr", cmd("wifi on", timeout=10)[-1] == "OK"); cmd("wifi off")
# El primer `wifi on` deja lwIP y el loop de eventos creados: se compara
# contra el heap tras el primer ciclo, no contra el del arranque.
for i in range(3):
    cmd("sdr on", timeout=10); on = cmd("sdr")[-1]; cmd("sdr cap 16380"); cmd("sdr off")
    off = cmd("sdr")[-1]; print("cycle", i, on, "|", off)
    heap = int(re.search(r"heap=(\d+)", off).group(1))
    check(f"no leak cycle {i}", abs(heap - heap1) < 1024, f"{heap1} -> {heap}")
r = cmd("ui", until=("UI",)); check("ui", r and r[-1].startswith("UI"), r[-1] if r else "")
print("FAILS:", fails)
sys.exit(1 if fails else 0)
