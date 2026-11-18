#!/usr/bin/env python3
"""
verify_album.py — Verifica la exportación ALBM de un badge, fuera de
línea y con K_master (no hay servidor): la firma de mi
estampa y, por cada estampa del álbum, su firma y el token del intercambio.

  K_A = HMAC-SHA256(K_master, MAC_A || A.no)   (tools/identity.py)
  sig de la estampa de A con K_A; token de A hacia B (el que exporta) con el
  nonce que B guardó.

Formato (services/usb_protocol.h): cabecera de 80 B ("ALBM", formato 1,
provisioned, MAC del que exporta, count, reservado, su estampa firmada) y
count entradas de 80 B (estampa 64, token 8, orden u16, nonce u32, reservado
2), little endian.

Para derivar K_A hace falta la MAC de cada badge: la tiene la tabla de la
provisión. Aquí se pasa con --mac NO=MAC (repetible) o --macs CSV
(no,mac por renglón). Un maestro de villa (901..910) y su repuesto
comparten dorsal con otra MAC: para esos dorsales se prueban todas las MAC
del CSV. Sin --master se usa DEV_MASTER si el badge no está
provisionado. El par virtual Eco del DevKit (#999) y las estampas de prueba
de la consola (`album add|fill|stress`) firman con la MAC del propio badge:
--self-mac la usa para todo dorsal sin MAC.

Especiales: las de tipo reto o especial las genera el propio badge
(services/specials) y las firma con su clave, sin token (no hay intercambio):
se verifican con la clave del que exporta. Solo cuentan en su álbum. Una
firma OK prueba que las pegó ese badge, no que su dueño las ganó: puede leer
su K_dev del flash. Los premios de N3 se validan con la flag,
no con la estampa.

Gira de villas: "villas: n/10 verificadas" cuenta las estampas de maestros
(901..910) con firma y token válidos. La especial "Gira de villas" la pega el
badge con solo ver los dorsales (un firmware modificado los falsifica), así
que solo es válida con las 10 verificadas; si no, "sin respaldo (n/10)" y no
cuenta.

Una estampa repetida en la exportación (mismo tipo y número que una anterior)
no cuenta: el badge las deduplica, así que una repetida es una exportación
alterada (cuentan los tokens únicos).

Exportación local: "Guardar álbum (.json)" del configurador y `badge_usb.py album
-o x.json` la guardan como .json; acepta el .bin y el .json. El .json lleva la
exportación completa en base64 ("albm") y un resumen legible; lo único que
cuenta es "albm" y un resumen que no coincide con ella se rechaza:
  {"format": "bb26-album", "version": 1, "badge_no": 42,
   "mac": "F4:12:FA:52:03:F8", "provisioned": false, "count": 1,
   "fw": "0.1.0", "exported_at": "2026-10-08T19:00:00Z", "albm": "<base64>"}
La versión 2 (firmware con ALAV) agrega los avatares que el badge recibió por IR:
"avatar_count": n y "avatars": {"<dorsal>": "<base64 de 512 B>"} (64x64, 1 bpp,
filas completas, MSB primero, 1 = blanco), un dorsal de asistente que está en
"albm". Los avatares no entran en la verificación (sin firma: solo CRC al leerlos
del badge) y la salida de este programa es la misma con la v1 y la v2.

QR del álbum (vista rápida web): con --qr verifica el texto que
codifica la pantalla QR del badge (lo que leerá web/album):
  <cfg::album::QR_URL><dorsal>/<bitmap>/<tag>
bitmap = 50 B (dorsal n en el bit n-1, MSB primero) y tag =
identity.album_tag() en base32 de RFC 4648 sin relleno. Solo prueba que el
bitmap salió de ese badge (no lleva tokens). El destino del QR aún no tiene hosting.

Uso:
  ./tools/verify_album.py album.bin --mac 999=F4:12:FA:52:03:F8
  ./tools/verify_album.py album_42.json --self-mac -v
  ./tools/verify_album.py --qr HTTPS://BUGCON.MX/A/42/... --mac 42=F4:12:FA:52:03:F8
  ./tools/verify_album.py -p /dev/ttyACM0 --self-mac -v
  ./tools/verify_album.py -p /dev/ttyACM0 --macs provision.csv --master HEX -v

Sale con 0 solo si todo se verificó; con 1 si algo no es válido o no se
pudo verificar (sin MAC, sin token, repetida, la propia, especial con
firma inválida).
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
JSON_FORMAT = "bb26-album"  # .json de la exportación local
JSON_VERSIONS = (1, 2)  # la 2 trae "avatars"
AVATARS_MAGIC = b"ALAV"  # exportación ALAV, formato 1 (services/usb_protocol.h)
AVATAR_BYTES = 512  # cfg::ir::AVATAR_BYTES: 64x64, 1 bpp
ATTENDEE = 0  # card::ATTENDEE
ATTENDEES = 400  # cfg::album::ATTENDEES
SPECIAL = 2  # card::SPECIAL
MASTER_FIRST = 901  # cfg::villa::MASTER_FIRST: maestro de la villa v = 901 + v
VILLAS = 10  # card::TEAM_COUNT
VILLA_TOUR = 30  # Número de la especial "Gira de villas" (services/specials)
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


def parse_avatars(data):
    """Exportación ALAV -> {dorsal: imagen de 512 B}. Un registro con crc 0 no
    es un avatar (el badge lo dio por dañado) y se omite."""
    if len(data) < 7 or data[:5] != AVATARS_MAGIC + b"\x01":
        raise ValueError("no es una exportación ALAV de formato 1")
    count = int.from_bytes(data[5:7], "little")
    record = 4 + AVATAR_BYTES
    if len(data) != 7 + count * record:
        raise ValueError(f"ALAV mide {len(data)} B; con {count} avatares "
                         f"serían {7 + count * record}")
    out = {}
    for i in range(count):
        no, crc = struct.unpack_from("<HH", data, 7 + i * record)
        if crc:
            out[no] = data[11 + i * record:7 + (i + 1) * record]
    return out


def to_json(data, fw=None, exported_at=None, avatars=None):
    """Exportación ALBM -> .json de la exportación local (bb26-album). Con
    `avatars` (ALAV, crudo) es la versión 2; sin él, la 1 de siempre."""
    header, entries = parse_album(data)
    doc = {
        "format": JSON_FORMAT, "version": 1, "badge_no": header["no"],
        "mac": header["mac"].hex(":").upper(),
        "provisioned": header["provisioned"], "count": header["count"],
        "fw": fw, "exported_at": exported_at,
        "albm": base64.b64encode(data).decode()}
    if avatars is not None:
        # Solo los de asistentes del álbum, como el configurador y la página
        mine = {e["no"] for e in entries if e["type"] == ATTENDEE}
        found = {no: img for no, img in parse_avatars(avatars).items()
                 if no in mine}
        doc["version"] = 2
        doc["avatar_count"] = len(found)
        doc["avatars"] = {str(no): base64.b64encode(img).decode()
                          for no, img in sorted(found.items())}
    return json.dumps(doc, indent=1)


def load_avatars(doc):
    """.json (bytes o dict ya leído) -> {dorsal: imagen}; vacío en la v1. Lanza
    ValueError si algún avatar no cuadra (largo, base64 o dorsal sin estampa)."""
    if isinstance(doc, (bytes, bytearray)):
        doc = json.loads(doc)
    raw = doc.get("avatars")
    if doc.get("version") == 1 or raw is None:
        return {}
    header, entries = parse_album(base64.b64decode(doc["albm"], validate=True))
    mine = {e["no"] for e in entries if e["type"] == ATTENDEE}
    out = {}
    for key, text in raw.items():
        try:
            no, img = int(key), base64.b64decode(text, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError(f"avatar {key!r} inválido") from None
        if len(img) != AVATAR_BYTES or no not in mine:
            raise ValueError(f"avatar {key!r}: largo o dorsal que no cuadra")
        out[no] = img
    if doc.get("avatar_count") != len(out):
        raise ValueError("avatar_count no coincide con avatars")
    return out


def load_export(data):
    """Contenido de un .bin o un .json (bb26-album) -> exportación ALBM cruda."""
    if not data.lstrip().startswith(b"{"):
        return data
    try:
        doc = json.loads(data)
        if doc.get("format") != JSON_FORMAT or \
                doc.get("version") not in JSON_VERSIONS:
            raise ValueError(f"no es un .json {JSON_FORMAT} versión "
                             f"{' o '.join(map(str, JSON_VERSIONS))}")
        raw = base64.b64decode(doc["albm"], validate=True)
        header, _ = parse_album(raw)
        summary = (doc["badge_no"], doc["mac"].upper(), doc["provisioned"],
                   doc["count"])
        load_avatars(doc)  # un avatar mal formado invalida el archivo
    except (KeyError, TypeError, AttributeError, binascii.Error) as e:
        raise ValueError(f".json de álbum inválido: {e!r}") from None
    if summary != (header["no"], header["mac"].hex(":").upper(),
                   header["provisioned"], header["count"]):
        raise ValueError("el resumen del .json no coincide con su exportación")
    return raw


def is_master(no):
    return MASTER_FIRST <= no < MASTER_FIRST + VILLAS


def attendee_key(master, no, candidates, card):
    """Clave de `no` con la primera MAC cuya firma cuadra (o la primera)."""
    keys = [identity.derive_key(master, mac, no) for mac in candidates]
    return next((k for k in keys if identity.verify_card(k, card)), keys[0])


def verify(header, entries, master, macs, default_mac=None):
    """Agrega a cada entrada `status`; devuelve el estado de mi estampa.
    macs = {dorsal: [MAC, ...]}."""
    me = header["no"]
    my_key = identity.derive_key(master, header["mac"], me)
    mine = "OK" if identity.verify_card(my_key, header["card"]) else "INVÁLIDA"
    seen = set()
    for e in entries:
        candidates = macs.get(e["no"]) or ([default_mac] if default_mac
                                           else [])
        ident = (e["type"], e["no"])
        if ident in seen:
            e["status"] = "repetida (ya contada)"
        elif e["type"] == ATTENDEE and e["no"] == me:
            # El badge no pega la suya; con su K_dev cualquiera fabrica una.
            e["status"] = "es la del que exporta (no cuenta)"
        elif e["type"] != ATTENDEE:
            # La generó y la firmó el badge que exporta.
            sig = identity.verify_card(my_key, e["card"])
            e["status"] = f"especial, {'firma OK' if sig else 'firma INVÁLIDA'}"
        elif not candidates:
            e["status"] = "sin MAC: no se puede derivar su clave"
        else:
            key = attendee_key(master, e["no"], candidates, e["card"])
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
        e["ok"] = e["status"] in ("firma OK, token OK", "especial, firma OK")
    villas = villa_count(entries)
    for e in entries:
        if e["ok"] and (e["type"], e["no"]) == (SPECIAL, VILLA_TOUR) \
                and villas < VILLAS:
            e["status"] += f", sin respaldo ({villas}/{VILLAS})"
            e["ok"] = False
    return mine


def villa_count(entries):
    """Villas con la estampa de su maestro verificada (tras verify())."""
    return sum(e["ok"] and e["type"] == ATTENDEE and is_master(e["no"])
               for e in entries)


def read_macs(args):
    """{dorsal: [MAC, ...]}: la última de cada dorsal; todas las de un
    maestro (el repuesto tiene el mismo dorsal y otra MAC)."""
    macs = {}

    def add(no, mac):
        mac = identity.parse_mac(mac)
        if not is_master(no):
            macs[no] = [mac]
        elif mac not in macs.setdefault(no, []):
            macs[no].append(mac)

    if args.macs:
        with open(args.macs, newline="") as f:
            for row in csv.reader(f):
                if row and row[0].strip().isdigit():
                    add(int(row[0]), row[1].strip())
    for item in args.mac:
        no, _, mac = item.partition("=")
        add(int(no), mac)
    return macs


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("file", nargs="?",
                        help="exportación ALBM (.bin o .json bb26-album)")
    parser.add_argument("-p", "--port", help="leer ALBM del badge")
    parser.add_argument("--qr", help="texto del QR del álbum")
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
    macs.setdefault(header["no"], [header["mac"]])

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
    print(f"villas: {villa_count(entries)}/{VILLAS} verificadas")
    return 0 if mine == "OK" and valid == len(entries) else 1


def main_qr(parser, args):
    try:
        no = parse_qr(args.qr)[0]
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    candidates = read_macs(args).get(no)
    if not candidates:
        parser.error(f"falta la MAC de #{no} (--mac {no}=MAC o --macs)")
    results = [verify_qr(args.qr, args.master or identity.DEV_MASTER, mac)
               for mac in candidates]
    no, numbers, ok = next((r for r in results if r[2]), results[0])
    print(f"#{no}: {len(numbers)}/{ATTENDEES} estampas, tag "
          f"{'OK' if ok else 'INVÁLIDO'}")
    if args.verbose:
        print("  " + " ".join(map(str, numbers)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
