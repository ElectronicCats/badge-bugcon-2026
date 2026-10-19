#!/usr/bin/env python3
"""
ai_tokens.py — Tokens de IA de hoy para la vista Tokens del modo
Escritorio del badge (F11.11, D-24). La PC cuenta y el badge solo muestra: al
conectarse manda `TIME` y luego un `TOKENS <entrada> <salida> <caché_lect>
<caché_escr> <total_7d> <meta> <nombre>` (firmware/README.md, protocolo USB)
por página: una por herramienta y, si usó más de un modelo en 7 días, una
por modelo (↑/↓ en el badge, hasta MAX_PAGES). Cada página se manda cada
`--cada` s si cambió, y todas cada KEEPALIVE_S aunque no cambien para que el
badge no diga "Sin actualizar". La meta vale para cada página.

Fuentes (`--fuente`, varias separadas por comas):
  claude-code  (por omisión) los transcripts locales de Claude Code,
               ~/.claude/projects/**/*.jsonl (o $CLAUDE_CONFIG_DIR/projects),
               subagentes incluidos. De cada renglón solo se leen `usage`,
               `model`, `timestamp`, `message.id` y `requestId`: las
               conversaciones no salen de la PC. El formato no es una API
               documentada (R-24).
  opencode     la base local de opencode ≥ 2.0,
               ~/.local/share/opencode/opencode.db (o $XDG_DATA_HOME), en
               solo lectura y solo la tabla de mensajes. Cuenta cualquier
               modelo que use opencode, no solo Claude.
  api          la API de uso de la organización (Admin API), con la clave de
               administrador en la variable de entorno ANTHROPIC_ADMIN_KEY.
               La clave nunca se imprime ni va al badge. Cuenta a toda la
               organización y llega con ~5 min de retraso; se consulta como
               mucho una vez por minuto.

Copilot y Antigravity no guardan cifras de tokens legibles en la PC (Copilot
solo los límites del modelo; Antigravity, protobuf sin esquema publicado).

No combine `api` con `claude-code` si Claude Code usa una clave de esa misma
organización: serían las mismas respuestas en dos páginas. El día es el local
de la PC (el mismo que `TIME`). Si el badge se reinicia, se le reenvía todo.
Requiere pyserial. Uso:
  ./tools/ai_tokens.py                        # se queda corriendo
  ./tools/ai_tokens.py --meta 5M --cada 30
  ./tools/ai_tokens.py --una-vez              # imprime, manda y sale
  ./tools/ai_tokens.py --fuente claude-code,opencode
  ANTHROPIC_ADMIN_KEY=... ./tools/ai_tokens.py --fuente api
"""
import argparse
import datetime
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

import serial

from badge_usb import Badge, ProtocolError, local_epoch

DAYS = 7  # total_7d = hoy + los 6 días anteriores
FILE_DAYS = 8  # Transcripts tocados en este lapso (fecha de modificación)
KEEPALIVE_S = 300  # < cfg::desk::TOKENS_STALE_MIN (10 min) del badge
BOOT_BANNER = b"ESP-ROM:"  # Primera línea del ROM del ESP32-S3 al arrancar
BOOT_S = 3  # El badge tira lo que llega mientras arranca
MAX_PAGES = 8  # cfg::desk::TOKENS_PAGES
NAME_MAX = 27  # cfg::desk::TOKENS_NAME_MAX, en bytes de UTF-8
# Campos de message.usage en los transcripts, en el orden de TOKENS
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
                "cache_creation_input_tokens")
API_URL = "https://api.anthropic.com/v1/organizations/usage_report/messages"
API_KEY_ENV = "ANTHROPIC_ADMIN_KEY"
API_MIN_S = 60  # La documentación pide sondear como mucho 1 vez por minuto
SUFFIXES = {"k": 1000, "m": 1000000}
# Fuente -> nombre de su página en el badge
SOURCES = {"claude-code": "Claude Code", "opencode": "opencode",
           "api": "API org"}


def parse_count(text):
    """Meta de `--meta`: `5M`, `800k`, `1.5M` o un entero."""
    mult = SUFFIXES.get(text[-1:].lower(), 1)
    try:
        value = Decimal(text[:-1] if mult > 1 else text) * mult
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"meta inválida: {text}")
    if value < 0 or value != int(value):
        raise argparse.ArgumentTypeError(f"meta inválida: {text}")
    return int(value)


def local_day(timestamp):
    """`2026-10-19T05:59:59.000Z` (UTC) -> fecha local de la PC."""
    utc = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return utc.astimezone().date()


def is_count(value):
    return type(value) is int and value >= 0  # bool no es una cifra


def model_name(value):
    return value if isinstance(value, str) and value else "?"


def by_model():
    """{modelo: {día local: 4 cifras}}, lo que devuelve cada fuente."""
    return defaultdict(lambda: defaultdict(lambda: [0] * 4))


def add(days, day, counts):
    days[day] = [a + b for a, b in zip(days[day], counts)]


def projects_dir():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"
    return Path(base) / "projects"


def read_transcripts(root, now=None):
    """Respuestas de Claude Code ->
    {(message.id, requestId): [día, 4 cifras, modelo]}.

    Una respuesta sale en varios renglones con la misma llave (uno por bloque
    de contenido) y, a veces, el primero trae `output_tokens` a medio contar
    (8 contra 229 en transcripts reales): se cuenta una vez, con el máximo de
    cada campo. Lo que no se entiende se ignora (R-24)."""
    since = (time.time() if now is None else now) - FILE_DAYS * 86400
    responses = {}
    for path in Path(root).glob("**/*.jsonl"):
        try:
            if path.stat().st_mtime < since:
                continue
            lines = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue  # Se borró entre el glob y el open
        with lines:
            for line in lines:
                if '"usage"' not in line:  # Casi todos; ahorra json.loads
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") != "assistant":
                        continue
                    message = entry["message"]
                    usage = message["usage"]
                    key = (message["id"], entry.get("requestId"))
                    counts = [usage.get(f, 0) for f in USAGE_FIELDS]
                    day = local_day(entry["timestamp"])
                    model = model_name(message.get("model"))
                except (ValueError, TypeError, KeyError, AttributeError):
                    continue  # Renglón roto, sin usage o de otro formato
                if not isinstance(key[0], str) or not all(map(is_count, counts)):
                    continue
                old = responses.get(key)
                if old is None:
                    responses[key] = [day, counts, model]
                else:
                    old[1] = [max(a, b) for a, b in zip(old[1], counts)]
    return responses


def transcript_days(responses):
    models = by_model()
    for day, counts, model in responses.values():
        add(models[model], day, counts)
    return models


def api_pages(key, today, urlopen=urllib.request.urlopen):
    """Páginas de la API de uso desde la medianoche local de hace 6 días, en
    cubetas de 1 h para cortar el día en hora local (las de 1 d son UTC),
    separadas por modelo.
    ponytail: con un huso de media hora la cubeta de medianoche cae entera
    en un día; para eso harían falta cubetas de 1 min."""
    start = datetime.datetime.combine(today - datetime.timedelta(DAYS - 1),
                                      datetime.time()).astimezone()
    end = datetime.datetime.now(datetime.timezone.utc).replace(
        minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
    utc = "%Y-%m-%dT%H:%M:%SZ"
    params = {
        "starting_at": start.astimezone(datetime.timezone.utc).strftime(utc),
        "ending_at": end.strftime(utc),
        "bucket_width": "1h",
        "limit": DAYS * 24,  # El máximo para 1h
        "group_by[]": "model",
    }
    while True:
        request = urllib.request.Request(
            API_URL + "?" + urllib.parse.urlencode(params),
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "User-Agent": "bb26-claude-tokens/1"})
        with urlopen(request, timeout=30) as reply:
            page = json.load(reply)
        yield page
        if not page.get("has_more") or not page.get("next_page"):
            return
        params["page"] = page["next_page"]


def api_days(pages):
    """Respuestas de usage_report/messages -> {modelo: {día local: 4 cifras}}."""
    models = by_model()
    for page in pages:
        for bucket in page.get("data") or []:
            try:
                day = local_day(bucket["starting_at"])
            except (KeyError, TypeError, ValueError):
                continue
            for result in bucket.get("results") or []:
                cache = result.get("cache_creation") or {}
                counts = [result.get("uncached_input_tokens", 0),
                          result.get("output_tokens", 0),
                          result.get("cache_read_input_tokens", 0),
                          sum(v for v in cache.values() if is_count(v))]
                if all(map(is_count, counts)):
                    add(models[model_name(result.get("model"))], day, counts)
    return models


def opencode_db():
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share"
    return Path(base) / "opencode" / "opencode.db"


def opencode_days(db, now=None):
    """Respuestas de opencode (≥ 2.0: SQLite) -> {modelo: {día: 4 cifras}}.

    La base también guarda cuentas y credenciales: solo se lee la tabla
    `session_message`, en solo lectura, y de cada respuesta solo `tokens`,
    `model.id` y `time.created` (ms). Una fila por respuesta (`id` es la
    llave), sin duplicados. La salida suma `reasoning`, que opencode cuenta
    aparte."""
    since_ms = int(((time.time() if now is None else now)
                    - FILE_DAYS * 86400) * 1000)
    db = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT data FROM session_message WHERE type = "
                          "'assistant' AND time_created >= ?", (since_ms,))
        models = by_model()
        for (data,) in rows:
            try:
                entry = json.loads(data)
                tokens = entry["tokens"]
                cache = tokens.get("cache") or {}
                counts = [tokens.get("input", 0),
                          tokens.get("output", 0) + tokens.get("reasoning", 0),
                          cache.get("read", 0), cache.get("write", 0)]
                day = datetime.datetime.fromtimestamp(
                    entry["time"]["created"] / 1000).date()
                model = model_name((entry.get("model") or {}).get("id"))
            except (ValueError, TypeError, KeyError, AttributeError,
                    OverflowError, OSError):
                continue
            if all(map(is_count, counts)):
                add(models[model], day, counts)
        return models
    finally:
        db.close()


def summary(days, today):
    """(cifras de hoy, total de los últimos DAYS días)."""
    week = sum(sum(days.get(today - datetime.timedelta(n), ()))
               for n in range(DAYS))
    return list(days.get(today, [0] * 4)), week


def page_name(tool, model):
    """`Claude Code: opus-5-5`; solo el modelo si no cabe en NAME_MAX."""
    model = "".join(c for c in model.removeprefix("claude-")
                    if c.isprintable()).strip() or "?"
    name = f"{tool}: {model}"
    if len(name.encode()) > NAME_MAX:
        name = model
    return name.encode()[:NAME_MAX].decode(errors="ignore").strip() or "?"


def pages(data, today):
    """{fuente: {modelo: días}} -> [(nombre, cifras de hoy, total 7d)].

    Una página por fuente con uso en 7 días (la suma de sus modelos) y,
    detrás, una por modelo si usó más de uno, del más usado al menos, hasta
    MAX_PAGES. Sin uso en ninguna, la primera fuente en 0."""
    tools = []
    for source, models in data.items():
        used = [(model, *summary(days, today)) for model, days in models.items()]
        used = sorted((m for m in used if m[2] > 0), key=lambda m: -m[2])
        if used:
            tools.append((SOURCES[source], used))
    if not tools:
        return [(SOURCES[next(iter(data))], [0] * 4, 0)]
    budget = MAX_PAGES - len(tools)
    out, names = [], set()
    for tool, used in tools:
        counts = [sum(m[1][i] for m in used) for i in range(4)]
        out.append((tool, counts, sum(m[2] for m in used)))
        names.add(tool)
        for model, counts, week in used if len(used) > 1 else ():
            name = page_name(tool, model)
            if budget > 0 and name not in names:
                out.append((name, counts, week))
                names.add(name)
                budget -= 1
    return out


def tokens_line(counts, week, goal, name):
    return "TOKENS " + " ".join(map(str, [*counts, week, goal, name]))


def parse_sources(text):
    """`--fuente claude-code,opencode` -> lista sin repetidos."""
    sources = list(dict.fromkeys(s.strip() for s in text.split(",")))
    bad = [s for s in sources if s not in SOURCES]
    if bad or not sources:
        raise argparse.ArgumentTypeError(
            f"fuente inválida: {','.join(bad) or text} "
            f"(opciones: {', '.join(SOURCES)})")
    return sources


def read_sources(sources, key):
    """{fuente: {modelo: días}}. Si una fuente falla, falla el ciclo entero:
    mejor no mandar nada que cifras a las que les falta una parte (R-24)."""
    data = {}
    for source in sources:
        if source == "api":
            data[source] = api_days(api_pages(key, datetime.date.today()))
        elif source == "opencode":
            data[source] = opencode_days(opencode_db())
        else:
            data[source] = transcript_days(read_transcripts(projects_dir()))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("-p", "--puerto", default="/dev/ttyACM0")
    parser.add_argument("--cada", type=int, default=30,
                        help="segundos entre lecturas (30; con api, ≥ 60)")
    parser.add_argument("--meta", type=parse_count, default=0,
                        help="presupuesto diario por página: 5M, 800k... "
                        "(0 = sin meta)")
    parser.add_argument("--una-vez", action="store_true",
                        help="manda una vez y sale")
    parser.add_argument("--fuente", type=parse_sources, default=["claude-code"],
                        help="claude-code (por omisión), opencode, api; "
                        "varias separadas por comas")
    args = parser.parse_args()

    key = None
    every = max(1, args.cada)
    if "api" in args.fuente:
        key = os.environ.get(API_KEY_ENV)
        if not key:
            print(f"error: falta la variable de entorno {API_KEY_ENV} "
                  "(clave de administrador)", file=sys.stderr)
            return 1
        every = max(every, API_MIN_S)

    badge = None
    sent = {}  # Página -> última línea que aceptó el badge en esta conexión
    sent_at = 0.0  # Último envío de todas las páginas

    def drop(error):
        nonlocal badge
        print(f"\nbadge: {error}", file=sys.stderr)
        if badge is not None:
            try:
                badge.close()
            except (serial.SerialException, OSError):
                pass
        badge = None
        sent.clear()  # Reconecta y reenvía todo en el siguiente ciclo

    try:
        while True:
            if badge is not None:
                try:  # Si se desconectó, read() lanza: suelta el tty
                    logs = badge.port.read(max(1, badge.port.in_waiting))
                except (serial.SerialException, OSError) as e:
                    drop(e)
                else:
                    # Un reset (RTS, botón) no reenumera el USB: solo se ve
                    # el arranque. Sus datos eran de RAM: TIME + TOKENS ya.
                    if BOOT_BANNER in logs:
                        print("badge: se reinició", file=sys.stderr)
                        sent.clear()
                        time.sleep(BOOT_S)
            try:
                current = pages(read_sources(args.fuente, key),
                                datetime.date.today())
            except urllib.error.HTTPError as e:
                current = None  # El cuerpo no lleva la clave; no se imprime
                print(f"api: HTTP {e.code} {e.reason}", file=sys.stderr)
            except (OSError, ValueError, sqlite3.Error) as e:  # Red, JSON, DB
                current = None
                print(f"{','.join(args.fuente)}: {e}", file=sys.stderr)
            if current is None:
                if args.una_vez:
                    return 1
            else:
                # El badge no borra páginas: las que ya no salen van en 0
                gone = [(n, [0] * 4, 0) for n in sent
                        if n not in {p[0] for p in current}]
                lines = [(name, counts, week,
                          tokens_line(counts, week, args.meta, name))
                         for name, counts, week in current + gone]
                due = time.time() - sent_at >= KEEPALIVE_S
                todo = [p for p in lines if due or sent.get(p[0]) != p[3]]
                try:
                    if todo and badge is None:
                        badge = Badge(args.puerto)
                    if todo and not sent:  # Al conectarse o tras un reinicio
                        badge.expect_ok(f"TIME {local_epoch()}")
                    for name, counts, week, line in todo:
                        print(f"{time.strftime('%H:%M:%S')} {name}: "
                              f"hoy={sum(counts)} entrada={counts[0]} "
                              f"salida={counts[1]} cache_lect={counts[2]} "
                              f"cache_escr={counts[3]} 7d={week} "
                              f"meta={args.meta}", end=" ", flush=True)
                        try:
                            print(badge.expect_ok(line))
                        except ProtocolError as e:
                            if str(e) != "ERR full":
                                raise
                            print(e)  # Sin lugar en el badge: no se reintenta
                        sent[name] = line
                    if todo and len(todo) == len(lines):
                        sent_at = time.time()
                except (serial.SerialException, ProtocolError, OSError) as e:
                    drop(e)
                    if args.una_vez:
                        return 1
            if args.una_vez:
                return 0
            time.sleep(every)
    except KeyboardInterrupt:
        return 0
    finally:
        if badge is not None:
            badge.close()


if __name__ == "__main__":
    sys.exit(main())
