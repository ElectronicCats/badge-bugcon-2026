#!/usr/bin/env python3
"""
test_ai_tokens.py — Pruebas de tools/ai_tokens.py sin badge ni red:
transcripts de ejemplo (duplicados, renglón roto, sin usage, subagente,
medianoche local, archivo viejo), una base de opencode de ejemplo, una
respuesta guardada de la API de uso y el lazo de main() con un badge falso
(reinicio y desconexión).

Uso (requiere pyserial, que badge_usb.py importa):
  python3 -m unittest tools/test_ai_tokens.py -v
"""
import argparse
import contextlib
import datetime
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_tokens  # noqa: E402
import serial  # noqa: E402

TODAY = datetime.date(2026, 10, 19)
NOW = 1792454400  # 2026-10-19 18:00 en CST+6, para la fecha de modificación


def reply(msg, req, ts, inp, out, cr, cw, model="claude-opus-5-5", **extra):
    return json.dumps({
        "type": "assistant", "requestId": req, "timestamp": ts,
        "message": {"id": msg, "model": model,
                    "content": [{"type": "text", "text": "secreto"}],
                    "usage": {"input_tokens": inp, "output_tokens": out,
                              "cache_read_input_tokens": cr,
                              "cache_creation_input_tokens": cw,
                              "service_tier": "standard"}},
        **extra})


# Sesión principal: la respuesta A sale en 3 renglones (el primero con la
# salida a medio contar), luego basura que se ignora, y dos respuestas a los
# lados de la medianoche local (CST+6: 06:00Z = 00:00 local).
MAIN = [
    reply("msg_A", "req_A", "2026-10-19T15:00:00.000Z", 2, 8, 1000, 300),
    reply("msg_A", "req_A", "2026-10-19T15:00:02.000Z", 2, 229, 1000, 300),
    reply("msg_A", "req_A", "2026-10-19T15:00:02.100Z", 2, 229, 1000, 300),
    '{"type": "assistant", "message": {"id": "msg_roto", "usage": {',
    json.dumps({"type": "user", "timestamp": "2026-10-19T15:00:00Z",
                "message": {"role": "user", "content": "hola usage"}}),
    json.dumps({"type": "assistant", "requestId": "req_X",
                "timestamp": "2026-10-19T15:01:00Z",
                "message": {"id": "msg_X", "content": "sin usage"}}),
    json.dumps(["usage"]),
    reply("msg_neg", "req_neg", "2026-10-19T15:02:00Z", -1, 5, 0, 0),
    reply("msg_ayer", "req_ayer", "2026-10-19T05:59:59.000Z", 10, 20, 30, 40),
    reply("msg_hoy", "req_hoy", "2026-10-19T06:00:01.000Z", 1, 2, 3, 4),
    reply("msg_viejo", "req_viejo", "2026-10-12T12:00:00Z", 7, 7, 7, 7),
]
SUBAGENT = [reply("msg_S", "req_S", "2026-10-19T16:00:00Z", 5, 50, 500, 5000,
                  model="claude-haiku-5-5", isSidechain=True)]
OLD_FILE = [reply("msg_O", "req_O", "2026-10-19T16:00:00Z", 9, 9, 9, 9)]

# Respuesta guardada de usage_report/messages (bucket_width=1h): una cubeta
# de ayer local (05:00Z), dos de hoy, y una sin resultados.
API_PAGES = [
    {"data": [
        {"starting_at": "2026-10-19T05:00:00Z", "ending_at": "2026-10-19T06:00:00Z",
         "results": [{"uncached_input_tokens": 100, "output_tokens": 200,
                      "cache_read_input_tokens": 300,
                      "cache_creation": {"ephemeral_1h_input_tokens": 40,
                                         "ephemeral_5m_input_tokens": 0},
                      "model": "claude-opus-5-5",
                      "server_tool_use": {"web_search_requests": 0}}]},
        {"starting_at": "2026-10-19T06:00:00Z", "ending_at": "2026-10-19T07:00:00Z",
         "results": []},
     ], "has_more": True, "next_page": "page_2"},
    {"data": [
        {"starting_at": "2026-10-19T15:00:00Z", "ending_at": "2026-10-19T16:00:00Z",
         "results": [{"uncached_input_tokens": 1, "output_tokens": 2,
                      "cache_read_input_tokens": 3,
                      "cache_creation": {"ephemeral_1h_input_tokens": 4,
                                         "ephemeral_5m_input_tokens": 5},
                      "model": "claude-opus-5-5"},
                     {"uncached_input_tokens": 10, "output_tokens": 20,
                      "cache_read_input_tokens": 30,
                      "cache_creation": {"ephemeral_1h_input_tokens": 0,
                                         "ephemeral_5m_input_tokens": 40},
                      "model": "claude-haiku-5-5"}]},
     ], "has_more": False, "next_page": None},
]


class LocalTime(unittest.TestCase):
    def setUp(self):
        self.tz = os.environ.get("TZ")
        os.environ["TZ"] = "CST+6"  # México centro, sin horario de verano
        time.tzset()

    def tearDown(self):
        if self.tz is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = self.tz
        time.tzset()


class Transcripts(LocalTime):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / "proj" / "sesion" / "subagents").mkdir(parents=True)
        files = {"proj/sesion.jsonl": MAIN,
                 "proj/sesion/subagents/agent-1.jsonl": SUBAGENT,
                 "proj/viejo.jsonl": OLD_FILE}
        for name, lines in files.items():
            (root / name).write_text("\n".join(lines) + "\n")
            os.utime(root / name, (NOW, NOW))
        old = NOW - (ai_tokens.FILE_DAYS + 1) * 86400
        os.utime(root / "proj/viejo.jsonl", (old, old))
        self.models = ai_tokens.transcript_days(
            ai_tokens.read_transcripts(root, now=NOW))

    def tearDown(self):
        self.dir.cleanup()
        super().tearDown()

    def test_today(self):
        # A una vez con la salida mayor + hoy después de medianoche + subagente
        opus = self.models["claude-opus-5-5"]
        self.assertEqual(opus[TODAY], [2 + 1, 229 + 2, 1000 + 3, 300 + 4])
        self.assertEqual(opus[TODAY - datetime.timedelta(1)], [10, 20, 30, 40])
        self.assertEqual(self.models["claude-haiku-5-5"][TODAY],
                         [5, 50, 500, 5000])
        # La herramienta y sus 2 modelos (el más usado primero); el
        # 2026-10-12 queda fuera de los 7 días (13..19)
        pages = ai_tokens.pages({"claude-code": self.models}, TODAY)
        self.assertEqual(pages, [
            ("Claude Code", [8, 281, 1503, 5304], 7096 + 100),
            ("Claude Code: haiku-5-5", [5, 50, 500, 5000], 5555),
            ("Claude Code: opus-5-5", [3, 231, 1003, 304], 1541 + 100)])
        self.assertEqual(
            ai_tokens.tokens_line(*pages[0][1:], 5000000, pages[0][0]),
            "TOKENS 8 281 1503 5304 7196 5000000 Claude Code")

    def test_ignored(self):
        days = {d for days in self.models.values() for d in days}
        self.assertEqual(days, {TODAY, TODAY - datetime.timedelta(1),
                                datetime.date(2026, 10, 12)})


class Api(LocalTime):
    def test_days(self):
        models = ai_tokens.api_days(API_PAGES)
        opus = models["claude-opus-5-5"]
        self.assertEqual(opus[TODAY - datetime.timedelta(1)],
                         [100, 200, 300, 40])
        self.assertEqual(opus[TODAY], [1, 2, 3, 9])
        self.assertEqual(models["claude-haiku-5-5"][TODAY], [10, 20, 30, 40])
        self.assertEqual(ai_tokens.pages({"api": models}, TODAY)[0],
                         ("API org", [11, 22, 33, 49], 115 + 640))

    def test_pages(self):
        requests = []

        def urlopen(request, timeout):
            requests.append(request)
            return io.BytesIO(json.dumps(API_PAGES[len(requests) - 1]).encode())

        pages = list(ai_tokens.api_pages("sk-prueba", TODAY, urlopen))
        self.assertEqual(pages, API_PAGES)
        self.assertEqual(requests[0].get_header("X-api-key"), "sk-prueba")
        self.assertIn("starting_at=2026-10-13T06%3A00%3A00Z",
                      requests[0].full_url)
        self.assertIn("bucket_width=1h", requests[0].full_url)
        self.assertIn("group_by%5B%5D=model", requests[0].full_url)
        self.assertNotIn("sk-prueba", requests[0].full_url)
        self.assertIn("page=page_2", requests[1].full_url)


def oc_row(msg, created_ms, inp, out, reasoning, read, write, kind="assistant",
           model="glm-5.3-flash-free"):
    data = {"time": {"created": created_ms}, "finish": "stop",
            "model": {"providerID": "opencode", "id": model},
            "tokens": {"input": inp, "output": out, "reasoning": reasoning,
                       "cache": {"read": read, "write": write}}}
    return (msg, "ses_1", kind, created_ms, json.dumps(data))


class Opencode(LocalTime):
    def test_days(self):
        ms = lambda iso: int(datetime.datetime.fromisoformat(iso).timestamp()
                             * 1000)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "opencode.db"
            db = sqlite3.connect(db_path)
            db.execute("CREATE TABLE session_message (id TEXT PRIMARY KEY, "
                       "session_id TEXT, type TEXT, seq INTEGER, "
                       "time_created INTEGER, data TEXT)")
            db.execute("CREATE TABLE credential (value TEXT)")
            db.execute("INSERT INTO credential VALUES ('secreto')")
            rows = [
                oc_row("m1", ms("2026-10-19T15:00:00+00:00"), 277, 502, 1, 26880, 0),
                oc_row("m2", ms("2026-10-19T06:00:01+00:00"), 3, 4, 5, 6, 7,
                       model="space-bunny-free"),
                oc_row("m3", ms("2026-10-19T05:59:59+00:00"), 1, 1, 1, 1, 1),
                oc_row("m4", ms("2026-10-19T15:00:00+00:00"), 9, 9, 9, 9, 9,
                       kind="user"),
                oc_row("m5", ms("2026-10-01T15:00:00+00:00"), 9, 9, 9, 9, 9),
                ("m6", "ses_1", "assistant", ms("2026-10-19T15:00:00+00:00"),
                 "{roto"),
                ("m7", "ses_1", "assistant", ms("2026-10-19T15:00:00+00:00"),
                 json.dumps({"time": {"created": 1}})),  # Sin tokens
            ]
            db.executemany("INSERT INTO session_message (id, session_id, "
                           "type, time_created, data) VALUES (?, ?, ?, ?, ?)",
                           rows)
            db.commit()
            db.close()
            models = ai_tokens.opencode_days(db_path, now=NOW)
        glm = models["glm-5.3-flash-free"]
        self.assertEqual(glm[TODAY], [277, 503, 26880, 0])
        self.assertEqual(glm[TODAY - datetime.timedelta(1)], [1, 2, 1, 1])
        self.assertEqual(set(glm), {TODAY, TODAY - datetime.timedelta(1)})
        self.assertEqual(dict(models["space-bunny-free"]), {TODAY: [3, 9, 6, 7]})
        # El nombre con la herramienta no cabe en 27 B: solo el modelo
        self.assertEqual(ai_tokens.pages({"opencode": models}, TODAY), [
            ("opencode", [280, 512, 26886, 7], 27660 + 5 + 25),
            ("glm-5.3-flash-free", [277, 503, 26880, 0], 27660 + 5),
            ("opencode: space-bunny-free", [3, 9, 6, 7], 25)])

    def test_sources(self):
        self.assertEqual(ai_tokens.parse_sources("claude-code,opencode"),
                         ["claude-code", "opencode"])
        self.assertEqual(ai_tokens.parse_sources("opencode, opencode"),
                         ["opencode"])
        for text in ("copilot", "claude-code,", ""):
            with self.assertRaises(argparse.ArgumentTypeError):
                ai_tokens.parse_sources(text)


class Pages(unittest.TestCase):
    @staticmethod
    def used(*models):
        return {m: {TODAY: [1, 0, 0, 0]} for m in models}

    def test_one_model(self):
        # Un solo modelo: solo la página de la herramienta
        self.assertEqual(
            ai_tokens.pages({"claude-code": self.used("claude-opus-5-5")},
                                TODAY), [("Claude Code", [1, 0, 0, 0], 1)])

    def test_nothing(self):
        # Sin uso en 7 días: la primera fuente en 0 (el badge dice algo)
        self.assertEqual(ai_tokens.pages(
            {"opencode": {}, "claude-code": self.used()}, TODAY),
            [("opencode", [0, 0, 0, 0], 0)])

    def test_cap(self):
        # Las herramientas tienen lugar siempre; los modelos llenan el resto
        data = {"claude-code": self.used(*(f"m{i}" for i in range(9))),
                "opencode": self.used("a", "b")}
        pages = ai_tokens.pages(data, TODAY)
        self.assertEqual(len(pages), ai_tokens.MAX_PAGES)
        self.assertEqual([p[0] for p in pages][-1], "opencode")
        self.assertEqual(pages[0], ("Claude Code", [9, 0, 0, 0], 9))

    def test_name(self):
        self.assertEqual(ai_tokens.page_name("Claude Code", "claude-opus-5-5"),
                         "Claude Code: opus-5-5")
        name = ai_tokens.page_name("opencode", "ñ" * 40 + "\n")
        self.assertLessEqual(len(name.encode()), ai_tokens.NAME_MAX)
        self.assertEqual(name, "ñ" * 13)  # Sin cortar una letra a la mitad
        self.assertEqual(ai_tokens.page_name("opencode", " \t"),
                         "opencode: ?")


class Meta(unittest.TestCase):
    def test_parse(self):
        for text, value in (("5M", 5000000), ("800k", 800000),
                            ("1.5M", 1500000), ("0", 0), ("1200", 1200)):
            self.assertEqual(ai_tokens.parse_count(text), value)
        for text in ("abc", "-5", "1.5", "M", ""):
            with self.assertRaises(argparse.ArgumentTypeError):
                ai_tokens.parse_count(text)


class Main(unittest.TestCase):
    """El lazo de main() con un badge falso: conecta, ve el arranque del ROM
    (reset sin reenumerar), se desconecta y vuelve como ttyACM1."""

    def test_reconnect(self):
        log = []
        # Lo que lee cada ciclo del primer badge: nada, un reinicio, el cable
        reads = [b"", b"log\r\nESP-ROM:esp32s3-20210327\r\n",
                 serial.SerialException("desconectado")]

        class Port:
            in_waiting = 0

            def read(self, size):
                item = reads.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

        class FakeBadge:
            def __init__(self, port):
                self.name = port
                self.port = Port()
                log.append(("abre", port))

            def expect_ok(self, line):
                log.append((self.name, line))
                return "OK"

            def close(self):
                log.append(("cierra", self.name))

        cycles = []

        def sleep(seconds):
            if seconds == ai_tokens.BOOT_S:
                return
            cycles.append(seconds)
            if len(cycles) == 4:
                raise KeyboardInterrupt

        today = datetime.date.today()
        data = {"claude-code": {"claude-opus-5-5": {today: [1, 2, 3, 4]}}}
        # El enlace de udev antes (ttyACM0) y después de reconectarse (ttyACM1)
        first, second = "/dev/serial/by-id/acm0", "/dev/serial/by-id/acm1"
        with mock.patch.object(ai_tokens, "Badge", FakeBadge), \
                mock.patch.object(ai_tokens, "read_sources",
                                  return_value=data), \
                mock.patch.object(ai_tokens, "local_epoch", return_value=123), \
                mock.patch.object(ai_tokens.glob, "glob",
                                  side_effect=[[first], [second]]), \
                mock.patch.object(ai_tokens.time, "sleep", sleep), \
                mock.patch.object(sys, "argv", ["ai_tokens.py"]), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ai_tokens.main(), 0)

        line = "TOKENS 1 2 3 4 10 0 Claude Code"
        self.assertEqual(log, [
            ("abre", first), (first, "TIME 123"), (first, line),
            # Ciclo 2 sin cambios: nada. Ciclo 3: el reinicio lo reenvía todo
            (first, "TIME 123"), (first, line),
            # Ciclo 4: se desconectó; se vuelve a buscar el puerto
            ("cierra", first), ("abre", second), (second, "TIME 123"),
            (second, line), ("cierra", second)])
        self.assertEqual(cycles, [30] * 4)

    def test_find_port(self):
        with mock.patch.object(ai_tokens.glob, "glob", return_value=[]):
            self.assertEqual(ai_tokens.find_port(), "/dev/ttyACM0")
        with mock.patch.object(ai_tokens.glob, "glob",
                               return_value=["/dev/serial/by-id/b",
                                             "/dev/serial/by-id/a"]):
            self.assertEqual(ai_tokens.find_port(), "/dev/serial/by-id/a")


if __name__ == "__main__":
    unittest.main()
