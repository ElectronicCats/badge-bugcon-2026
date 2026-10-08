#!/usr/bin/env python3
"""
verify_album.py — Verifica la exportación ALBM de un badge (F5.7, §3.3 del
plan) como lo hará el backend (F6.4): la firma de mi estampa y, por cada
estampa del álbum, su firma y el token del intercambio.

  K_A = HMAC-SHA256(K_master, MAC_A || A.no)   (tools/identity.py)
  sig de la estampa de A con K_A; token de A hacia B (el que exporta) con el
  nonce que B guardó.

Formato (services/usb_protocol.h): cabecera de 80 B ("ALBM", formato 1,
provisioned, MAC del que exporta, count, reservado, su estampa firmada) y
count entradas de 80 B (estampa 64, token 8, orden u16, nonce u32, reservado
2), little endian.

Para derivar K_A hace falta la MAC de cada badge: la tiene la tabla de la
provisión (F12.4). Aquí se pasa con --mac NO=MAC (repetible) o --macs CSV
(no,mac por renglón). Sin --master se usa DEV_MASTER si el badge no está
provisionado. El par virtual Eco del DevKit (#999) y las estampas de prueba
de la consola (`album add|fill|stress`) firman con la MAC del propio badge:
--self-mac la usa para todo dorsal sin MAC.

Una estampa repetida en la exportación (mismo tipo y número que una anterior)
no cuenta: el badge las deduplica, así que una repetida es una exportación
alterada (el ranking cuenta tokens únicos, §3.3).

Sincronización (F6.2): el configurador sube (o guarda para subir después) la
exportación como .json; acepta el .bin y el .json. El .json lleva la
exportación completa en base64 ("albm") y un resumen legible; lo único que
cuenta es "albm" y un resumen que no coincide con ella se rechaza:
  {"format": "bb26-album", "version": 1, "badge_no": 42,
   "mac": "F4:12:FA:52:03:F8", "provisioned": false, "count": 1,
   "fw": "0.1.0", "exported_at": "2026-10-08T19:00:00Z", "albm": "<base64>"}

QR del álbum (F5.6, vista rápida web): con --qr verifica el texto que
codifica la pantalla QR del badge (lo que leerá web/album, F6.3):
  <cfg::album::QR_URL><dorsal>/<bitmap>/<tag>
bitmap = 50 B (dorsal n en el bit n-1, MSB primero) y tag =
identity.album_tag() en base32 de RFC 4648 sin relleno. Solo prueba que el
bitmap salió de ese badge; no cuenta para el ranking (no lleva tokens).

Uso:
  ./tools/verify_album.py album.bin --mac 999=F4:12:FA:52:03:F8
  ./tools/verify_album.py album_42.json --self-mac -v
  ./tools/verify_album.py --qr HTTPS://BUGCON.MX/A/42/... --mac 42=F4:12:FA:52:03:F8
  ./tools/verify_album.py -p /dev/ttyACM0 --self-mac -v
  ./tools/verify_album.py -p /dev/ttyACM0 --macs provision.csv --master HEX -v

Sale con 0 solo si todo se verificó; con 1 si algo no es válido o no se
pudo verificar (sin MAC, sin token, repetida, la propia, especiales de
F5.5).
"""
import argparse
import base64
import binascii
import csv
import hmac
import json
import struct
import sys

import identity

HEADER = struct.Struct("<4sBB6sH2s64s")
ENTRY = struct.Struct("<64s8sHI2s")
FORMAT = 1
JSON_FORMAT = "bb26-album"  # .json de la sincronización (F6.2)
ATTENDEE = 0  # card::ATTENDEE
ATTENDEES = 400  # cfg::album::ATTENDEES
BITMAP_BYTES = (ATTENDEES + 7) // 8


def _b32(text, length):
    data = base64.b32decode(text + "=" * (-len(text) % 8))
    if len(data) != length:
        raise ValueError(f"se esperaban {length} B y llegaron {len(data)}")
    return data


def parse_qr(text):
    """Texto del QR del álbum -> (dorsal, bitmap, tag, dorsales del bitmap)."""
    try:
        no, bits, tag = text.strip().rstrip("/").split("/")[-3:]
        if not no.isdigit():
            raise ValueError("dorsal no numérico")
        bitmap = _b32(bits, BITMAP_BYTES)
        tag = _b32(tag, 8)
    except ValueError as e:  # binascii.Error también
        raise ValueError(f"no es un QR del álbum: {e}") from None
    numbers = [n for n in range(1, ATTENDEES + 1)
               if bitmap[(n - 1) // 8] & (0x80 >> ((n - 1) % 8))]
    return int(no), bitmap, tag, numbers


def verify_qr(text, master, mac):
    """-> (dorsal, dorsales, tag válido)."""
    no, bitmap, tag, numbers = parse_qr(text)
    key = identity.derive_key(master, mac, no)
    ok = hmac.compare_digest(identity.album_tag(key, no, bitmap), tag)
    return no, numbers, ok


def parse_album(data):
    """-> (cabecera como dict, lista de entradas como dict)."""
    if len(data) < HEADER.size:
        raise ValueError("exportación incompleta")
    magic, fmt, prov, mac, count, _, mine = HEADER.unpack_from(data)
    if magic != b"ALBM" or fmt != FORMAT:
        raise ValueError(f"no es una exportación ALBM de formato {FORMAT}")
    if len(data) != HEADER.size + count * ENTRY.size:
        raise ValueError(f"mide {len(data)} B; con {count} estampas serían "
                         f"{HEADER.size + count * ENTRY.size}")
    header = {"provisioned": bool(prov), "mac": mac, "count": count,
              "card": mine, "no": identity.card_badge_no(mine)}
    entries = []
    for i in range(count):
        card, tok, order, nonce, _ = ENTRY.unpack_from(
            data, HEADER.size + i * ENTRY.size)
        entries.append({"card": card, "token": tok, "order": order,
                        "nonce": nonce, "type": card[1],
                        "no": identity.card_badge_no(card),
                        "nick": card[4:20].split(b"\0")[0].decode(
                            errors="replace")})
    return header, entries


def to_json(data, fw=None, exported_at=None):
    """Exportación ALBM -> .json de la sincronización (F6.2)."""
    header, _ = parse_album(data)
    return json.dumps({
        "format": JSON_FORMAT, "version": FORMAT, "badge_no": header["no"],
        "mac": header["mac"].hex(":").upper(),
        "provisioned": header["provisioned"], "count": header["count"],
        "fw": fw, "exported_at": exported_at,
        "albm": base64.b64encode(data).decode()}, indent=1)


def load_export(data):
    """Contenido de un .bin o un .json (F6.2) -> exportación ALBM cruda."""
    if not data.lstrip().startswith(b"{"):
        return data
    try:
        doc = json.loads(data)
        if doc.get("format") != JSON_FORMAT or doc.get("version") != FORMAT:
            raise ValueError(f"no es un .json {JSON_FORMAT} versión {FORMAT}")
        raw = base64.b64decode(doc["albm"], validate=True)
        header, _ = parse_album(raw)
        summary = (doc["badge_no"], doc["mac"].upper(), doc["provisioned"],
                   doc["count"])
    except (KeyError, TypeError, AttributeError, binascii.Error) as e:
        raise ValueError(f".json de sincronización inválido: {e!r}") from None
    if summary != (header["no"], header["mac"].hex(":").upper(),
                   header["provisioned"], header["count"]):
        raise ValueError("el resumen del .json no coincide con su exportación")
    return raw


def verify(header, entries, master, macs, default_mac=None):
    """Agrega a cada entrada `status`; devuelve el estado de mi estampa."""
    me = header["no"]
    my_key = identity.derive_key(master, header["mac"], me)
    mine = "OK" if identity.verify_card(my_key, header["card"]) else "INVÁLIDA"
    seen = set()
    for e in entries:
        mac = macs.get(e["no"], default_mac)
        ident = (e["type"], e["no"])
        if ident in seen:
            e["status"] = "repetida (ya contada)"
        elif e["type"] == ATTENDEE and e["no"] == me:
            # El badge no pega la suya; con su K_dev cualquiera fabrica una.
            e["status"] = "es la del que exporta (no cuenta)"
        elif e["type"] != ATTENDEE:
            e["status"] = "especial (sin verificar, F5.5)"
        elif mac is None:
            e["status"] = "sin MAC: no se puede derivar su clave"
        else:
            key = identity.derive_key(master, mac, e["no"])
            sig = identity.verify_card(key, e["card"])
            if not any(e["token"]):
                tok = "sin token"
            elif identity.verify_token(key, e["no"], me, e["nonce"],
                                       e["token"]):
                tok = "token OK"
            else:
                tok = "token INVÁLIDO"
            e["status"] = f"{'firma OK' if sig else 'firma INVÁLIDA'}, {tok}"
        seen.add(ident)
        e["ok"] = e["status"] == "firma OK, token OK"
    return mine


def read_macs(args):
    macs = {}
    if args.macs:
        with open(args.macs, newline="") as f:
            for row in csv.reader(f):
                if row and row[0].strip().isdigit():
                    macs[int(row[0])] = identity.parse_mac(row[1].strip())
    for item in args.mac:
        no, _, mac = item.partition("=")
        macs[int(no)] = identity.parse_mac(mac)
    return macs


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("file", nargs="?",
                        help="exportación ALBM (.bin o .json de F6.2)")
    parser.add_argument("-p", "--port", help="leer ALBM del badge")
    parser.add_argument("--qr", help="texto del QR del álbum (F5.6)")
    parser.add_argument("--master", type=bytes.fromhex,
                        help="K_master en hex (por omisión DEV_MASTER)")
    parser.add_argument("--mac", action="append", default=[],
                        metavar="NO=MAC")
    parser.add_argument("--macs", help="CSV no,mac de la provisión")
    parser.add_argument("--self-mac", action="store_true",
                        help="la MAC del que exporta para los dorsales sin "
                        "MAC (Eco y estampas de prueba del DevKit)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="una línea por estampa, también las válidas")
    args = parser.parse_args()
    if [args.file, args.port, args.qr].count(None) != 2:
        parser.error("indica un archivo, --port o --qr")
    if args.qr:
        return main_qr(parser, args)

    if args.port:
        import badge_usb

        badge = badge_usb.Badge(args.port)
        try:
            data = badge.album()
        finally:
            badge.close()
    else:
        data = open(args.file, "rb").read()

    try:
        header, entries = parse_album(load_export(data))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if header["provisioned"] and args.master is None:
        parser.error("el badge está provisionado: falta --master")
    master = args.master or identity.DEV_MASTER
    macs = read_macs(args)
    macs.setdefault(header["no"], header["mac"])

    mine = verify(header, entries, master, macs,
                  header["mac"] if args.self_mac else None)
    mac_text = header["mac"].hex(":").upper()
    print(f"#{header['no']} ({mac_text}, "
          f"{'provisionado' if header['provisioned'] else 'desarrollo'}): "
          f"mi estampa {mine}, {header['count']} estampas")
    for e in entries:
        if args.verbose or not e["ok"]:
            print(f"  [{e['order']:3}] tipo {e['type']} #{e['no']:<5} "
                  f"{e['nick']!r:20} {e['status']}")
    valid = sum(e["ok"] for e in entries)
    print(f"verificadas {valid}/{len(entries)}")
    return 0 if mine == "OK" and valid == len(entries) else 1


def main_qr(parser, args):
    try:
        no = parse_qr(args.qr)[0]
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    mac = read_macs(args).get(no)
    if mac is None:
        parser.error(f"falta la MAC de #{no} (--mac {no}=MAC o --macs)")
    no, numbers, ok = verify_qr(args.qr, args.master or identity.DEV_MASTER,
                                mac)
    print(f"#{no}: {len(numbers)}/{ATTENDEES} estampas, tag "
          f"{'OK' if ok else 'INVÁLIDO'}")
    if args.verbose:
        print("  " + " ".join(map(str, numbers)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
