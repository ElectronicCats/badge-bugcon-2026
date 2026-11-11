#!/usr/bin/env python3
"""
badge_link.py — Conexión común a un Badge para las herramientas de la PC:
lo encuentra en cualquier sistema operativo, comprueba que es un Badge, traduce
los errores del sistema y del firmware a mensajes con una sugerencia y
reintenta una vez los comandos que se pueden repetir.

Solo usa la clase Badge de badge_usb.py; no depende de Rich ni de Pillow.
Los mensajes son texto plano: la presentación es asunto de cada script.

  find_badge(port=None)  -> ruta del puerto (None = buscarlo por VID:PID)
  connect(port=None)     -> Badge ya saludado; quien lo pide lo cierra
  call(badge, línea, payload=None)  -> respuesta OK, con un reintento
  explain(error)         -> texto en español de un ProtocolError

Códigos de salida que usan las herramientas:
  0 bien · 1 el Badge rechazó el comando (ERR) · 2 uso · 3 conexión
"""
import errno
import sys
import time

import serial
from serial.tools import list_ports

import badge_usb

# La clase de error del protocolo: quien ejecuta badge_usb.py como script tiene
# una copia distinta en __main__, así que captura la de badge_link.
ProtocolError = badge_usb.ProtocolError

VID, PID = 0x303A, 0x1001  # USB Serial/JTAG del ESP32-S3
GREET_TIMEOUT_S = 3  # INFO de saludo; la respuesta normal tarda milisegundos
PAYLOAD_WAIT_S = 3.5  # Más que PAYLOAD_TIMEOUT_MS (3 s): el badge ya soltó el payload
# Comandos que se pueden repetir sin efectos dobles. FLAG no está: se pide
# a mano.
IDEMPOTENT = frozenset(
    "INFO TIME SHOW READ ALBM LED CLR PWR UPLD AVTR CARD NICK".split())

EXIT_OK, EXIT_REJECTED, EXIT_USAGE, EXIT_CONNECTION = 0, 1, 2, 3

CHECKLIST = (
    "Revisa que el Badge esté encendido con el interruptor SW1, que el cable "
    "sea de datos (no solo de carga) y que el configurador web esté cerrado.")
ASLEEP = ("El Badge no contesta: puede estar dormido. Presiona un botón y "
          "vuelve a intentar.")

ERR_MESSAGES = {
    "badcmd": "El Badge no entiende ese comando.",
    "badslot": "Ese espacio del Marco no existe. Mira cuáles hay con `info`.",
    "empty": "Ese espacio del Marco está vacío.",
    "timeout": "El Badge no recibió los datos completos. Intenta de nuevo.",
    "flash": "El Badge no pudo guardarlo en su memoria. Intenta de nuevo.",
    "badnick": "Apodo no válido: no puede quedar vacío.",
    "badver": "El Badge no reconoce esa versión de estampa. Actualiza las "
              "herramientas.",
    "badteam": "Villa no válida: va de -1 (ninguna) a 10.",
    "badpos": "Posición no válida: va de -1 (ninguna) a 4.",
    "badstats": "Estadísticas no válidas: cada una va de 0 a 99 y la suma no "
                "puede pasar de 200.",
    "badhandle": "Handle no válido: hasta 20 bytes.",
    "badtime": "Hora no válida: el reloj de la PC está antes de 2025.",
    "badcolor": "Color no válido: usa seis dígitos hex, como ff0000.",
    "badtokens": "Los datos de Tokens no son válidos.",
    "full": "El Badge ya no tiene espacio para eso. En Tokens: presiona "
            "RESET en el Badge y vuelve a correr el programa.",
    "wrong": "La flag no es correcta. Revísala e intenta de nuevo.",
    "locked": "Primero tienes que superar la etapa anterior.",
}


class BadgeConnectionError(Exception):
    """No se pudo hablar con un Badge; el texto ya dice qué hacer."""


def explain(error):
    """Texto en español de un ProtocolError (o de su mensaje)."""
    text = str(error)
    if text == "timeout":
        return ASLEEP
    if text.startswith("ERR "):
        code = text[4:].split(None, 1)[0] if text[4:].strip() else ""
        return ERR_MESSAGES.get(code, f"El Badge rechazó el comando: {text}")
    return text


def find_badge(port=None):
    """Ruta del puerto del Badge. `port` explícito manda sobre la búsqueda."""
    if port:
        return port
    found = [p for p in list_ports.comports() if (p.vid, p.pid) == (VID, PID)]
    if not found:
        raise BadgeConnectionError("No encuentro tu Badge. " + CHECKLIST)
    if len(found) > 1:
        lines = "\n".join(
            f"  {p.device}  (serie {p.serial_number})" for p in found)
        raise BadgeConnectionError(
            "Hay más de un Badge conectado; elige uno con -p:\n" + lines)
    return found[0].device


def _open_error(port, exc):
    """Mensaje para una falla de apertura, según el sistema."""
    text = str(exc)
    windows = sys.platform.startswith("win")
    code = getattr(exc, "errno", None)
    if code == errno.ENOENT or "FileNotFoundError" in text:
        return f"No encuentro {port}. ¿Está conectado el Badge? " + CHECKLIST
    if code in (errno.EAGAIN, errno.EBUSY) or "exclusively lock" in text or (
            windows and ("Access is denied" in text or code == errno.EACCES)):
        return (f"{port} está ocupado por otro programa. Cierra el "
                "configurador web y los programas que usen el Badge (como "
                "ai_tokens.py) y vuelve a intentar.")
    if code == errno.EACCES or "Permission denied" in text:
        return (f"No tienes permiso para usar {port}. En Linux agrega tu "
                "usuario al grupo dialout (sudo usermod -aG dialout $USER) y "
                "vuelve a iniciar sesión.")
    return f"No pude abrir {port}: {text}"


def greet(badge):
    """INFO de saludo con timeout corto; levanta si no contesta un Badge."""
    badge.port.reset_input_buffer()
    badge.port.write(b"INFO\n")
    try:
        reply = badge.read_reply(GREET_TIMEOUT_S)
    except badge_usb.ProtocolError:
        raise BadgeConnectionError(
            ASLEEP + " Si el Badge está despierto, ese puerto no es el suyo."
        ) from None
    if not reply.startswith("OK BB26"):
        raise BadgeConnectionError("Ese puerto no es un Badge BugCON 2026.")


def connect(port=None):
    """Busca, abre y saluda al Badge. Quien lo recibe llama a close()."""
    path = find_badge(port)
    try:
        badge = badge_usb.Badge(path)
    except (serial.SerialException, OSError) as exc:
        raise BadgeConnectionError(_open_error(path, exc)) from exc
    try:
        greet(badge)
    except BaseException:
        badge.close()  # deja el tty en VMIN=1
        raise
    return badge


def call(badge, line, payload=None):
    """expect_ok con un reintento si el comando se puede repetir y venció el
    tiempo. Antes de repetir espera a que el Badge suelte el payload a medias,
    vacía la entrada y vuelve a saludar."""
    verb = line.split(None, 1)[0]
    try:
        return badge.expect_ok(line, payload)
    except badge_usb.ProtocolError as exc:
        if str(exc) not in ("timeout", "ERR timeout") or verb not in IDEMPOTENT:
            raise
        if str(exc) == "timeout":  # silencio: ERR timeout ya soltó el payload
            time.sleep(PAYLOAD_WAIT_S)
        greet(badge)
    try:
        return badge.expect_ok(line, payload)
    except badge_usb.ProtocolError as exc:
        if str(exc) == "timeout":
            raise BadgeConnectionError(ASLEEP) from None
        raise
