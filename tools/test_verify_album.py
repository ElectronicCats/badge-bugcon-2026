#!/usr/bin/env python3
"""
test_verify_album.py — Pruebas de tools/verify_album.py sin badge:
arma exportaciones ALBM con tools/identity.py y comprueba que se acepten las
buenas y se rechacen las alteradas, fuera de línea con K_master: firma
inválida, estampa firmada con la clave de otro badge, token falsificado o de
otro receptor, nonce cambiado, repetidas, la propia, otra K_master y
exportaciones truncadas. Incluye el álbum lleno (400 + especiales) y el
texto del QR del álbum.

Uso (biblioteca estándar):
  python3 -m unittest tools/test_verify_album.py -v
  ./tools/test_verify_album.py
"""
import base64
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import identity  # noqa: E402
import verify_album as va  # noqa: E402

MASTER = bytes(range(32))
MY_NO = 42
MY_MAC = bytes.fromhex("F412FA5203F8")
MY_KEY = identity.derive_key(MASTER, MY_MAC, MY_NO)
CAPACITY = 480  # cfg::album::CAPACITY
ATTENDEE, SPECIAL = 0, 2
GOLD = 2


def mac_of(no):
    return bytes([0x02, 0, 0, 0]) + struct.pack(">H", no)


def card(no, key=None, type_=ATTENDEE, rarity=0, nick=None):
    """Estampa v1 de 64 B; firmada con `key` (sin key, sig en ceros)."""
    nick = (nick or f"Prueba {no}").encode()[:16].ljust(16, b"\0")
    body = struct.pack("<BBH16sBB4sBB20s", 1, type_, no, nick, no % 8, 0,
                       bytes([10, 20, 30, 40]), rarity, 0, b"\0" * 20)
    assert len(body) == identity.SIGNED_BYTES
    sig = identity.card_sig(key, body) if key else b"\0" * 16
    return body + sig


def key_of(no, master=MASTER, mac=None):
    return identity.derive_key(master, mac or mac_of(no), no)


def entry(no, order, nonce=None, master=MASTER):
    """Entrada de un intercambio legítimo de `no` hacia mí."""
    key = key_of(no, master)
    nonce = no * 0x9E3779B9 & 0xFFFFFFFF if nonce is None else nonce
    return {"card": card(no, key), "token": identity.token(key, no, MY_NO, nonce),
            "order": order, "nonce": nonce}


def export(entries, provisioned=True, master=MASTER, mine=None):
    mine = mine or card(MY_NO, identity.derive_key(master, MY_MAC, MY_NO))
    out = va.HEADER.pack(b"ALBM", va.FORMAT, provisioned, MY_MAC,
                         len(entries), b"\0\0", mine)
    for e in entries:
        out += va.ENTRY.pack(e["card"], e["token"], e["order"], e["nonce"],
                             b"\0\0")
    return out


def check(data, master=MASTER, macs=None):
    """-> (estado de mi estampa, [status de cada entrada], [ok])."""
    header, entries = va.parse_album(data)
    if macs is None:
        macs = {e["no"]: [mac_of(e["no"])] for e in entries}
    mine = va.verify(header, entries, master, macs)
    return mine, [e["status"] for e in entries], [e["ok"] for e in entries]


class VerifyAlbum(unittest.TestCase):
    def test_valid_album(self):
        mine, status, ok = check(export([entry(7, 1), entry(8, 2)]))
        self.assertEqual(mine, "OK")
        self.assertEqual(ok, [True, True])

    def test_tampered_field_invalidates_signature(self):
        e = entry(7, 1)
        c = bytearray(e["card"])
        c[26] = GOLD  # rarity: "me subí a oro" tras firmar
        e["card"] = bytes(c)
        _, status, ok = check(export([e]))
        self.assertEqual(status, ["firma INVÁLIDA, token OK"])
        self.assertFalse(ok[0])

    def test_tampered_signature_byte(self):
        e = entry(7, 1)
        c = bytearray(e["card"])
        c[63] ^= 0x01
        e["card"] = bytes(c)
        self.assertEqual(check(export([e]))[1], ["firma INVÁLIDA, token OK"])

    def test_unsigned_card(self):
        e = entry(7, 1)
        e["card"] = card(7)  # sig en ceros
        self.assertFalse(check(export([e]))[2][0])

    def test_card_signed_by_another_badge(self):
        # #9 se hace pasar por #7: firma y token con su propia clave.
        e = entry(7, 1)
        k9 = key_of(9)
        e["card"] = card(7, k9)
        e["token"] = identity.token(k9, 7, MY_NO, e["nonce"])
        self.assertEqual(check(export([e]))[1],
                         ["firma INVÁLIDA, token INVÁLIDO"])

    def test_forged_token(self):
        e = entry(7, 1)
        e["token"] = bytes(8 * [0x5A])
        self.assertEqual(check(export([e]))[1], ["firma OK, token INVÁLIDO"])

    def test_token_for_another_receiver(self):
        # Token legítimo de #7 hacia #43, pegado en la exportación de #42.
        e = entry(7, 1)
        e["token"] = identity.token(key_of(7), 7, 43, e["nonce"])
        self.assertEqual(check(export([e]))[1], ["firma OK, token INVÁLIDO"])

    def test_changed_nonce(self):
        e = entry(7, 1)
        e["nonce"] ^= 1
        self.assertEqual(check(export([e]))[1], ["firma OK, token INVÁLIDO"])

    def test_missing_token(self):
        e = entry(7, 1)
        e["token"] = b"\0" * 8
        self.assertEqual(check(export([e]))[1], ["firma OK, sin token"])

    def test_duplicate_counts_once(self):
        a = entry(7, 1)
        b = entry(7, 2, nonce=123)  # Otro intercambio legítimo con #7
        _, status, ok = check(export([a, b, entry(8, 3)]))
        self.assertEqual(ok, [True, False, True])
        self.assertEqual(status[1], "repetida (ya contada)")

    def test_special_and_attendee_with_same_number(self):
        special = {"card": card(7, MY_KEY, type_=SPECIAL, rarity=GOLD),
                   "token": b"\0" * 8, "order": 2, "nonce": 0}
        _, status, ok = check(export([entry(7, 1), special]))
        self.assertEqual(ok, [True, True])
        self.assertEqual(status[1], "especial, firma OK")

    def test_special_signed_by_another_badge(self):
        # La firma el badge que la ganó; copiada a otro álbum no sirve.
        # Sin firma o alterada, tampoco.
        tampered = bytearray(card(1, MY_KEY, type_=SPECIAL))
        tampered[26] = GOLD
        for c in (card(1, key_of(7), type_=SPECIAL), card(1, type_=SPECIAL),
                  bytes(tampered)):
            special = {"card": c, "token": b"\0" * 8, "order": 1, "nonce": 0}
            _, status, ok = check(export([special]))
            self.assertEqual((status, ok), (["especial, firma INVÁLIDA"],
                                            [False]))

    def test_own_card_does_not_count(self):
        # Con su K_dev cualquiera fabrica una "estampa suya hacia sí mismo".
        e = entry(MY_NO, 1)
        e["card"] = card(MY_NO, identity.derive_key(MASTER, MY_MAC, MY_NO))
        _, status, ok = check(export([e]), macs={MY_NO: [MY_MAC]})
        self.assertFalse(ok[0])
        self.assertIn("del que exporta", status[0])

    def test_without_mac(self):
        _, status, ok = check(export([entry(7, 1)]), macs={})
        self.assertFalse(ok[0])
        self.assertIn("sin MAC", status[0])

    def test_self_mac_for_devkit_test_cards(self):
        # Las estampas de prueba del DevKit firman con la MAC del propio badge.
        key = identity.derive_key(MASTER, MY_MAC, 7)
        e = {"card": card(7, key), "token": identity.token(key, 7, MY_NO, 5),
             "order": 1, "nonce": 5}
        header, entries = va.parse_album(export([e]))
        va.verify(header, entries, MASTER, {}, default_mac=header["mac"])
        self.assertTrue(entries[0]["ok"])
        header, entries = va.parse_album(export([e]))
        va.verify(header, entries, MASTER, {})
        self.assertIn("sin MAC", entries[0]["status"])

    def test_wrong_master(self):
        data = export([entry(7, 1)])
        mine, status, ok = check(data, master=identity.DEV_MASTER)
        self.assertEqual(mine, "INVÁLIDA")
        self.assertEqual(status, ["firma INVÁLIDA, token INVÁLIDO"])

    def test_my_card_tampered(self):
        mine = bytearray(card(MY_NO, identity.derive_key(MASTER, MY_MAC,
                                                         MY_NO)))
        mine[4] ^= 0x20
        self.assertEqual(check(export([], mine=bytes(mine)))[0], "INVÁLIDA")

    def test_malformed_exports(self):
        good = export([entry(7, 1), entry(8, 2)])
        for data in (good[:-1], good + b"\0", good[:79], b"ALBX" + good[4:],
                     good[:4] + b"\x02" + good[5:]):
            with self.assertRaises(ValueError):
                va.parse_album(data)

    def test_full_album(self):
        # 399 asistentes (sin mi dorsal) + 81 especiales = CAPACITY.
        entries = [entry(no, i + 1) for i, no in
                   enumerate(n for n in range(1, 401) if n != MY_NO)]
        for sid in range(1, CAPACITY - len(entries) + 1):
            entries.append({"card": card(sid, MY_KEY, type_=SPECIAL,
                                         rarity=GOLD),
                            "token": b"\0" * 8, "order": len(entries) + 1,
                            "nonce": 0})
        data = export(entries)
        self.assertEqual(len(data), 80 + CAPACITY * 80)
        mine, status, ok = check(data)
        self.assertEqual(mine, "OK")
        # La especial 30 ("Gira de villas") no tiene maestros que la respalden.
        self.assertEqual(sum(ok), CAPACITY - 1)
        self.assertEqual(sum(s == "especial, firma OK" for s in status), 80)
        self.assertIn("sin respaldo (0/10)", status[-81 + va.VILLA_TOUR - 1])

    def test_cli_exit_codes(self):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "verify_album.py")
        bad = entry(8, 2)
        bad["card"] = bad["card"][:26] + bytes([GOLD]) + bad["card"][27:]
        with tempfile.TemporaryDirectory() as tmp:
            def run(entries, *extra):
                path = os.path.join(tmp, "album.bin")
                with open(path, "wb") as f:
                    f.write(export(entries))
                macs = [f"--mac={e['card'][2] | e['card'][3] << 8}="
                        f"{mac_of(e['card'][2] | e['card'][3] << 8).hex()}"
                        for e in entries]
                return subprocess.run(
                    [sys.executable, script, path, "--master", MASTER.hex(),
                     *macs, *extra], capture_output=True, text=True)

            ok = run([entry(7, 1)])
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn("verificadas 1/1", ok.stdout)
            rejected = run([entry(7, 1), bad])
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("firma INVÁLIDA", rejected.stdout)
            self.assertIn("verificadas 1/2", rejected.stdout)
            # Provisionado sin --master: no adivina la maestra.
            path = os.path.join(tmp, "album.bin")
            no_master = subprocess.run([sys.executable, script, path],
                                       capture_output=True, text=True)
            self.assertNotEqual(no_master.returncode, 0)
            self.assertIn("--master", no_master.stderr)


def villa_tour(order):
    return {"card": card(va.VILLA_TOUR, MY_KEY, type_=SPECIAL, rarity=GOLD),
            "token": b"\0" * 8, "order": order, "nonce": 0}


class Villas(unittest.TestCase):
    MASTERS = range(va.MASTER_FIRST, va.MASTER_FIRST + va.VILLAS)

    def test_ten_verified_back_the_special(self):
        entries = [entry(no, i + 1) for i, no in enumerate(self.MASTERS)]
        _, status, ok = check(export(entries + [villa_tour(11)]))
        self.assertTrue(all(ok), status)
        header, entries = va.parse_album(export(entries))
        va.verify(header, entries, MASTER,
                  {e["no"]: [mac_of(e["no"])] for e in entries})
        self.assertEqual(va.villa_count(entries), 10)

    def test_forged_master_leaves_special_unbacked(self):
        entries = [entry(no, i + 1) for i, no in enumerate(self.MASTERS)]
        # Un firmware modificado con dorsal 905 firma con otra clave.
        fake = identity.derive_key(MASTER, bytes(6), 905)
        entries[4]["card"] = card(905, fake)
        _, status, ok = check(export(entries + [villa_tour(11)]))
        self.assertEqual(ok.count(False), 2)
        self.assertEqual(status[-1], "especial, firma OK, sin respaldo (9/10)")

    def test_spare_master_with_another_mac(self):
        spare = bytes.fromhex("0A0000000385")
        key = identity.derive_key(MASTER, spare, 901)
        e = {"card": card(901, key), "token": identity.token(key, 901, MY_NO,
                                                            7),
             "order": 1, "nonce": 7}
        _, _, ok = check(export([e, entry(902, 2)]),
                         macs={901: [mac_of(901), spare],
                               902: [mac_of(902), spare]})
        self.assertEqual(ok, [True, True])
        _, status, ok = check(export([e]), macs={901: [mac_of(901)]})
        self.assertEqual(status, ["firma INVÁLIDA, token INVÁLIDO"])

    def test_read_macs_keeps_every_master_mac(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "provision.csv")
            with open(path, "w") as f:
                f.write("no,mac\n7,02:00:00:00:00:01\n7,02:00:00:00:00:02\n"
                        "901,02:00:00:00:00:03\n901,02:00:00:00:00:04\n"
                        "901,02:00:00:00:00:03\n")

            class Args:
                macs, mac = path, ["901=02:00:00:00:00:05"]
            macs = va.read_macs(Args)
        self.assertEqual([m[-1] for m in macs[7]], [2])
        self.assertEqual([m[-1] for m in macs[901]], [3, 4, 5])

    def test_cli_villas_line(self):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "verify_album.py")
        entries = [entry(no, i + 1) for i, no in enumerate(self.MASTERS)]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "album.bin")
            with open(path, "wb") as f:
                f.write(export(entries[:3] + [villa_tour(4)]))
            macs = [f"--mac={no}={mac_of(no).hex()}" for no in self.MASTERS]
            run = subprocess.run([sys.executable, script, path, "--master",
                                  MASTER.hex(), *macs],
                                 capture_output=True, text=True)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("villas: 3/10 verificadas", run.stdout)
        self.assertIn("sin respaldo (3/10)", run.stdout)


class ExportJson(unittest.TestCase):
    """El .json (bb26-album) que guarda el configurador con "Guardar álbum (.json)"."""

    def test_roundtrip(self):
        data = export([entry(7, 1), entry(8, 2)])
        doc = va.to_json(data, "0.1.0", "2026-11-20T18:00:00Z")
        self.assertEqual(va.load_export(doc.encode()), data)
        self.assertEqual(va.load_export(data), data)  # el .bin sigue igual
        d = json.loads(doc)
        self.assertEqual((d["badge_no"], d["count"], d["mac"]),
                         (MY_NO, 2, "F4:12:FA:52:03:F8"))

    def test_summary_must_match(self):
        doc = json.loads(va.to_json(export([entry(7, 1)])))
        for key, value in (("badge_no", 43), ("count", 2), ("provisioned",
                           False), ("mac", "02:00:00:00:00:07")):
            bad = dict(doc, **{key: value})
            with self.assertRaises(ValueError, msg=key):
                va.load_export(json.dumps(bad).encode())

    def test_malformed(self):
        doc = json.loads(va.to_json(export([entry(7, 1)])))
        raw = base64.b64decode(doc["albm"])
        for bad in (dict(doc, format="otro"), dict(doc, version=3),
                    dict(doc, albm=doc["albm"] + "!"),
                    dict(doc, albm=base64.b64encode(raw[:-1]).decode()),
                    {k: v for k, v in doc.items() if k != "albm"}, [], "x"):
            with self.assertRaises(ValueError, msg=repr(bad)[:60]):
                va.parse_album(va.load_export(json.dumps(bad).encode()))
        with self.assertRaises(ValueError):
            va.load_export(b"{no es json")

    @staticmethod
    def alav(records):
        """ALAV crudo: records = [(dorsal, crc, imagen)]."""
        out = b"ALAV\x01" + struct.pack("<H", len(records))
        for no, crc, img in records:
            out += struct.pack("<HH", no, crc) + img
        return out

    def test_avatars_v2(self):
        data = export([entry(7, 1), entry(8, 2)])
        a7, a8 = bytes([7]) * 512, bytes([8]) * 512
        # 9 no está en el álbum y 8 salió dañado (crc 0): no entran
        alav = self.alav([(7, 1, a7), (8, 0, a8), (9, 1, a8)])
        doc = va.to_json(data, "0.1.0", "x", avatars=alav)
        d = json.loads(doc)
        self.assertEqual((d["version"], d["avatar_count"]), (2, 1))
        self.assertEqual(list(d["avatars"]), ["7"])
        self.assertEqual(va.load_avatars(doc.encode()), {7: a7})
        self.assertEqual(va.load_export(doc.encode()), data)
        # sin ALAV (firmware viejo) sale la v1 de siempre, sin avatares
        v1 = json.loads(va.to_json(data))
        self.assertEqual((v1["version"], "avatars" in v1), (1, False))
        self.assertEqual(va.load_avatars(json.dumps(v1).encode()), {})

    def test_bad_avatars_rejected(self):
        data = export([entry(7, 1)])
        good = json.loads(va.to_json(
            data, avatars=self.alav([(7, 1, bytes(512))])))
        img = good["avatars"]["7"]
        for bad in (dict(good, avatars={"7": img[:-4]}),
                    dict(good, avatars={"7": "!" + img}),
                    dict(good, avatars={"8": img}),
                    dict(good, avatars={"x": img}),
                    dict(good, avatar_count=2)):
            with self.assertRaises(ValueError, msg=repr(bad)[:60]):
                va.load_export(json.dumps(bad).encode())
        with self.assertRaises(ValueError):
            va.parse_avatars(b"ALAV\x01\x01\x00")  # le falta el registro

    def test_cli_same_output_v1_v2(self):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "verify_album.py")
        data = export([entry(7, 1)])
        alav = self.alav([(7, 1, bytes(512))])
        outs = []
        with tempfile.TemporaryDirectory() as tmp:
            for name, avatars in (("v1", None), ("v2", alav)):
                path = os.path.join(tmp, name + ".json")
                with open(path, "w") as f:
                    f.write(va.to_json(data, avatars=avatars))
                r = subprocess.run([sys.executable, script, path, "--master",
                                    MASTER.hex(), f"--mac=7={mac_of(7).hex()}",
                                    "-v"], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                outs.append(r.stdout)
        self.assertEqual(outs[0], outs[1])

    def test_cli_accepts_json(self):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "verify_album.py")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "album_42.json")
            with open(path, "w") as f:
                f.write(va.to_json(export([entry(7, 1)])))
            r = subprocess.run([sys.executable, script, path, "--master",
                                MASTER.hex(), f"--mac=7={mac_of(7).hex()}"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("verificadas 1/1", r.stdout)


def qr_text(no, numbers, key):
    """Lo que arma album::qrText() en el badge."""
    bitmap = bytearray(va.BITMAP_BYTES)
    for n in numbers:
        bitmap[(n - 1) // 8] |= 0x80 >> ((n - 1) % 8)
    b32 = lambda b: base64.b32encode(bytes(b)).decode().rstrip("=")
    tag = identity.album_tag(key, no, bytes(bitmap))
    return f"HTTPS://BUGCON.MX/A/{no}/{b32(bitmap)}/{b32(tag)}"


class AlbumQr(unittest.TestCase):
    KEY = identity.derive_key(MASTER, MY_MAC, MY_NO)

    def test_valid(self):
        text = qr_text(MY_NO, [1, 7, MY_NO, 400], self.KEY)
        self.assertEqual(len(text), 20 + 2 + 1 + 80 + 1 + 13)
        self.assertTrue(set(text) <= set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                                         " $%*+-./:"))  # Alfanumérico del QR
        self.assertEqual(va.verify_qr(text, MASTER, MY_MAC),
                         (MY_NO, [1, 7, MY_NO, 400], True))

    def test_tampered_bitmap_or_number(self):
        text = qr_text(MY_NO, [7], self.KEY)
        forged = qr_text(MY_NO, [7, 8], self.KEY).rsplit("/", 1)[0]
        forged += "/" + text.rsplit("/", 1)[1]  # Tag del bitmap original
        self.assertFalse(va.verify_qr(forged, MASTER, MY_MAC)[2])
        other_no = text.replace(f"/{MY_NO}/", "/43/")
        self.assertFalse(va.verify_qr(other_no, MASTER, MY_MAC)[2])

    def test_wrong_master_or_mac(self):
        text = qr_text(MY_NO, [7], self.KEY)
        self.assertFalse(va.verify_qr(text, identity.DEV_MASTER, MY_MAC)[2])
        self.assertFalse(va.verify_qr(text, MASTER, mac_of(MY_NO))[2])

    def test_malformed(self):
        text = qr_text(MY_NO, [7], self.KEY)
        head, bits, tag = text.rsplit("/", 2)
        for bad in ("", "HTTPS://BUGCON.MX/A/", f"{head}/{bits}",
                    f"{head}/{bits[:-1]}/{tag}", f"{head}/{bits}/{tag}AA",
                    f"{head}/{bits}/{tag[:-1]}1",
                    text.replace(f"/{MY_NO}/", "/X/")):
            with self.assertRaises(ValueError, msg=bad):
                va.parse_qr(bad)

    def test_cli(self):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "verify_album.py")
        text = qr_text(MY_NO, [3, MY_NO], self.KEY)
        run = lambda *a: subprocess.run(
            [sys.executable, script, "--qr", *a, "--master", MASTER.hex()],
            capture_output=True, text=True)
        ok = run(text, "--mac", f"{MY_NO}={MY_MAC.hex(':')}")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertIn(f"#{MY_NO}: 2/400 estampas, tag OK", ok.stdout)
        bad = run(text, "--mac", f"{MY_NO}=02:00:00:00:00:01")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("tag INVÁLIDO", bad.stdout)
        self.assertNotEqual(run(text).returncode, 0)  # Sin MAC


if __name__ == "__main__":
    unittest.main()
