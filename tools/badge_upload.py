#!/usr/bin/env python3
"""
badge_upload.py — Enviar una imagen al Marco (upload) o al avatar (avatar):
convierte cualquier imagen común, guarda una vista previa, pregunta antes de
reemplazar un espacio ocupado y comprueba con READ que el Badge guardó lo
mismo que se envió.

  add_options(parser, slot=True)  opciones de conversión y de vista previa
  run(args, kind)                 "upload" | "avatar" completo -> código de salida

Rich solo se importa al presentar mensajes; ni este módulo ni badge_usb.py lo
necesitan para importarse. Pillow, solo al convertir (badge_image).
"""
import sys
from pathlib import Path

import badge_image
import badge_link
import badge_usb
from badge_image import ImageError

PANEL_W = PANEL_H = 200  # INFO panel; --solo-vista no abre el puerto
DITHER_NAMES = {"fs": "Floyd-Steinberg", "umbral": "umbral"}


def add_options(parser, slot=True):
    parser.add_argument("--ajuste", choices=badge_image.FITS, default="contener",
                        help="contener: se ve entera; cubrir: llena y recorta")
    parser.add_argument("--tramado", choices=badge_image.DITHERS, default="fs")
    parser.add_argument("--umbral", type=int, default=128,
                        help="0-255, con --tramado umbral")
    parser.add_argument("--invertir", action="store_true")
    parser.add_argument("--ampliar", action="store_true",
                        help="amplía una imagen más chica que la pantalla")
    parser.add_argument("--vista", metavar="PNG",
                        help="guarda cómo se verá (ampliada x2)")
    parser.add_argument("--solo-vista", action="store_true",
                        help="convierte y guarda la vista, sin abrir el Badge")
    if slot:
        parser.add_argument("--si", action="store_true",
                            help="reemplaza un espacio ocupado sin preguntar")


def save_preview(bits, w, h, path, scale=2):
    """PNG en blanco y negro de una imagen del badge (1 = blanco)."""
    import ui_shot  # write_png; importa pyserial, que los scripts ya requieren

    stride = (w + 7) // 8
    rows = [[1 - (bits[y * stride + x // 8] >> (7 - x % 8) & 1) for x in range(w)]
            for y in range(h)]  # write_png espera 1 = tinta
    ui_shot.write_png(path, w, h, rows, scale)


def _size_note(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return f" ({im.width}×{im.height})"
    except Exception:  # noqa: BLE001 — solo adorno; prepare_image da el error real
        return ""


def convert(args, w, h, say):
    path = Path(args.file)
    if path.suffix.lower() not in (".bin", ".pbm"):
        say(f"Convirtiendo {path.name}{_size_note(path)} → {w}×{h}, "
            f"{args.ajuste}, {DITHER_NAMES[args.tramado]}")
    return badge_image.load_for_badge(
        path, w, h, fit=args.ajuste, dither=args.tramado,
        threshold=args.umbral, invert=args.invertir, enlarge=args.ampliar)


def _check_size(bits, w, h):
    # Nunca sale al puerto un payload de otro tamaño (el badge quedaría esperando)
    if len(bits) != badge_image.expected_bytes(w, h):
        raise ImageError(f"la imagen mide {len(bits)} B; para {w}x{h} deben ser "
                         f"{badge_image.expected_bytes(w, h)} B")


def upload_verified(badge, slot, bits, w, h):
    """UPLD + READ y comparación; un reintento si no coincide. -> respuesta OK."""
    _check_size(bits, w, h)
    for _ in range(2):
        reply = badge_link.call(badge, f"UPLD {slot}", bits)
        if badge.read(slot) == bits:
            return reply
    raise badge_usb.ProtocolError(
        "El Badge guardó una imagen distinta a la que envié. Intenta de nuevo.")


def send_avatar(badge, bits):
    _check_size(bits, badge_usb.AVATAR_W, badge_usb.AVATAR_H)
    return badge_link.call(badge, "AVTR", bits)  # el avatar no tiene lectura


def _confirm(question):
    if not sys.stdin.isatty():
        raise ImageError(f"{question} Usa --si para reemplazarla sin preguntar.")
    from rich.prompt import Confirm
    return Confirm.ask(question, default=False)


def _console():
    try:
        from rich.console import Console
    except ImportError:
        raise ImageError("Falta Rich: pip install -r tools/requirements.txt") from None
    return Console(stderr=True, highlight=False)


def run(args, kind, connect=badge_link.connect, console=None, confirm=_confirm):
    """upload / avatar de punta a punta. 0 bien · 1 rechazado · 2 uso · 3 conexión."""
    avatar = kind == "avatar"
    w, h = (badge_usb.AVATAR_W, badge_usb.AVATAR_H) if avatar else (PANEL_W, PANEL_H)
    badge = None
    try:
        console = console or _console()

        def say(message):
            console.print(message, markup=False)

        bits = convert(args, w, h, say)  # antes de abrir el puerto
        out = args.vista or ("vista.png" if args.solo_vista else None)
        if out:
            save_preview(bits, w, h, out)
            say(f"Vista previa guardada en {out}")
        if args.solo_vista:
            return badge_link.EXIT_OK

        badge = connect(args.port)
        if avatar:
            with console.status("Enviando…"):
                reply = send_avatar(badge, bits)
            say("Avatar actualizado. El Badge no permite leerlo de vuelta, así "
                "que no se pudo verificar.")
        else:
            info = badge.info()
            if (info["w"], info["h"]) != (w, h):
                raise ImageError(f"la pantalla del Badge mide {info['w']}x{info['h']}, "
                                 f"no {w}x{h}; actualiza las herramientas")
            if not 0 <= args.slot < info["slots"]:
                raise ImageError(f"El Marco tiene {info['slots']} espacios "
                                 f"(0 a {info['slots'] - 1}); pediste el {args.slot}.")
            if info["used"][args.slot:args.slot + 1] == "1" and not args.si and not confirm(
                    f"El espacio {args.slot} ya tiene una imagen y no se puede "
                    "recuperar. ¿Reemplazarla?"):
                say("No se cambió nada.")
                return badge_link.EXIT_REJECTED
            with console.status("Enviando…"):
                reply = upload_verified(badge, args.slot, bits, w, h)
            say(f"Guardada en el espacio {args.slot} y en pantalla. Verificada.")
        if reply.startswith("OK slow="):
            say("Aviso: la pantalla tardó en refrescar; la imagen sí se guardó.")
        return badge_link.EXIT_OK
    except ImageError as e:
        print(f"error: {e}", file=sys.stderr)
        return badge_link.EXIT_USAGE
    except badge_link.BadgeConnectionError as e:
        print(f"error: {e}", file=sys.stderr)
        return badge_link.EXIT_CONNECTION
    except badge_usb.ProtocolError as e:
        print(f"error: {badge_link.explain(e)}", file=sys.stderr)
        return badge_link.EXIT_REJECTED
    finally:
        if badge:
            badge.close()
