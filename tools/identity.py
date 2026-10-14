#!/usr/bin/env python3
"""
identity.py — Referencia de la identidad del badge (§3.3 del plan, F5.1): las
mismas cuentas que firmware/badge_bugcon_2026/src/services/identity.cpp. La
usan provision.py (F12.4) y verify_album.py (F5).

  K_dev = HMAC-SHA256(K_master, MAC(6) || badge_no(u16 LE))
  sig   = HMAC-SHA256(K_dev, estampa[0:48])[:16]
  tok   = HMAC-SHA256(K_A, "XCHG" || A.no || B.no || nonce_B (u32 LE))[:8]
  tag   = HMAC-SHA256(K_dev, "ALBQ" || badge_no || bitmap(50))[:8]  (QR, F5.6)
  flag  = SHA-256("BB26FLAG" || etapa (u8, desde 1) || flag UTF-8)  (retos, F9.1)

Sin provisionar, el badge usa DEV_MASTER (pública) como K_master:
verify_album.py, con la K_master real, rechaza lo que salga de un DevKit.

Uso (la clave sale de --key o se deriva con --mac y el dorsal; sin
--master se usa DEV_MASTER):
  ./tools/identity.py key --mac F4:12:FA:52:03:F8 --no 7 [--master HEX]
  ./tools/identity.py card <128 hex de 'id'> --mac F4:12:FA:52:03:F8
  ./tools/identity.py token --from 7 --to 999 --nonce 0x1234ABCD \\
      --tok 0011223344556677 --mac F4:12:FA:52:03:F8
  ./tools/identity.py flag 1 'BB26{...}'   # hash del vestidor (N3)
"""
import argparse
import hashlib
import hmac
import struct
import sys

DEV_MASTER = b"BugCon26 dev master (public)"
CARD_BYTES = 64
SIGNED_BYTES = 48


def _hmac(key, data):
    return hmac.new(key, data, hashlib.sha256).digest()


def derive_key(master, mac, badge_no):
    return _hmac(master, bytes(mac) + struct.pack("<H", badge_no))


def card_sig(key, card):
    return _hmac(key, card[:SIGNED_BYTES])[:16]


def token(key, sender, receiver, nonce):
    return _hmac(key, b"XCHG" + struct.pack("<HHI", sender, receiver, nonce))[:8]


def album_tag(key, badge_no, bitmap):
    """Tag del QR del álbum (identity::albumTag)."""
    return _hmac(key, b"ALBQ" + struct.pack("<H", badge_no) + bitmap)[:8]


def flag_hash(stage, flag):
    """Hash de verificación de la flag (challenge_engine::flagHash)."""
    return hashlib.sha256(b"BB26FLAG" + bytes([stage]) + flag.encode()).digest()


def verify_card(key, card):
    return hmac.compare_digest(card_sig(key, card), card[SIGNED_BYTES:CARD_BYTES])


def verify_token(key, sender, receiver, nonce, tok):
    return hmac.compare_digest(token(key, sender, receiver, nonce), tok)


def card_badge_no(card):
    return struct.unpack_from("<H", card, 2)[0]


def key_id(key):
    """Lo que muestra `id` en la consola (key=...)."""
    return hashlib.sha256(key).digest()[:4].hex().upper()


def parse_mac(text):
    mac = bytes.fromhex(text.replace(":", "").replace("-", ""))
    if len(mac) != 6:
        raise argparse.ArgumentTypeError("la MAC lleva 6 bytes")
    return mac


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("flag", help="hash de una flag para STAGES[]")
    p.add_argument("stage", type=int, choices=range(1, 256), metavar="etapa")
    p.add_argument("flag")
    for name in ("key", "card", "token"):
        p = sub.add_parser(name)
        p.add_argument("--key", type=bytes.fromhex, help="K_dev en hex")
        p.add_argument("--mac", type=parse_mac, help="MAC del badge que firma")
        p.add_argument("--master", type=bytes.fromhex,
                       help="K_master en hex (por omisión DEV_MASTER)")
        if name == "key":
            p.add_argument("--no", type=int, required=True)
        elif name == "card":
            p.add_argument("hex", help="estampa de 64 B en hex")
        else:
            p.add_argument("--from", dest="sender", type=int, required=True)
            p.add_argument("--to", dest="receiver", type=int, required=True)
            p.add_argument("--nonce", type=lambda s: int(s, 0), required=True)
            p.add_argument("--tok", type=bytes.fromhex, required=True)
    args = parser.parse_args()
    if args.cmd == "flag":
        h = flag_hash(args.stage, args.flag)
        print("{" + ", ".join(f"0x{b:02X}" for b in h) + "}")
        return 0

    card = bytes.fromhex(args.hex) if args.cmd == "card" else None
    if card is not None and len(card) != CARD_BYTES:
        parser.error("la estampa mide 64 B")
    no = {"key": lambda: args.no, "card": lambda: card_badge_no(card),
          "token": lambda: args.sender}[args.cmd]()
    key = args.key
    if key is None:
        if args.mac is None:
            parser.error("falta --key o --mac")
        key = derive_key(args.master or DEV_MASTER, args.mac, no)

    if args.cmd == "key":
        print(f"{key.hex().upper()}  (id {key_id(key)})")
        return 0
    if args.cmd == "card":
        ok = verify_card(key, card)
        print(f"#{no} sig {'OK' if ok else 'INVÁLIDA'}")
    else:
        ok = verify_token(key, args.sender, args.receiver, args.nonce, args.tok)
        print(f"#{args.sender} -> #{args.receiver} token "
              f"{'OK' if ok else 'INVÁLIDO'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
