#!/usr/bin/env python3
"""
test_badge_link.py — Pruebas de tools/badge_link.py sin badge: búsqueda por
VID:PID con comports() simulado, traducción de errores de apertura y del
firmware, saludo y reintento de los comandos repetibles.

Uso (requiere pyserial):
  python3 -m unittest tools/test_badge_link.py -v
"""
import errno
import os
import sys
import unittest
from collections import namedtuple
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import badge_link  # noqa: E402
import badge_usb  # noqa: E402
from test_badge_usb import INFO_REPLY, FakePort  # noqa: E402

Port = namedtuple("Port", "device vid pid serial_number")
BADGE = Port("/dev/ttyACM1", 0x303A, 0x1001, "7C:4F:AD:3A:FD:E0")
OTHER = Port("/dev/ttyUSB0", 0x10C4, 0xEA60, "0001")


def comports(*ports):
    return mock.patch.object(badge_link.list_ports, "comports",
                             return_value=list(ports))


def info_ok(line):
    return b"OK BB26 1.0.0 no=42 panel=200x200 album=25/400 slots=4 " \
           b"current=1 used=1010\r\n" if line == "INFO" else b"OK\r\n"


def badge_on(port):
    """connect() sobre un FakePort, sin esperas."""
    return (mock.patch.object(badge_usb.serial, "Serial", return_value=port),
            mock.patch.object(badge_usb.time, "sleep"))


class FindBadge(unittest.TestCase):
    def test_none(self):
        with comports(OTHER):
            with self.assertRaisesRegex(badge_link.BadgeConnectionError,
                                        "No encuentro tu Badge.*SW1"):
                badge_link.find_badge()

    def test_empty_list(self):
        with comports():
            with self.assertRaises(badge_link.BadgeConnectionError):
                badge_link.find_badge()

    def test_one_among_others(self):
        with comports(OTHER, BADGE):
            self.assertEqual(badge_link.find_badge(), "/dev/ttyACM1")

    def test_two_lists_both(self):
        two = BADGE._replace(device="/dev/ttyACM2", serial_number="AA:BB")
        with comports(BADGE, two):
            with self.assertRaises(badge_link.BadgeConnectionError) as cm:
                badge_link.find_badge()
        self.assertIn("/dev/ttyACM1", str(cm.exception))
        self.assertIn("AA:BB", str(cm.exception))
        self.assertIn("-p", str(cm.exception))

    def test_explicit_port_wins(self):
        with comports() as m:
            self.assertEqual(badge_link.find_badge("COM7"), "COM7")
        m.assert_not_called()


class OpenErrors(unittest.TestCase):
    def connect_failing(self, exc):
        with mock.patch.object(badge_usb.serial, "Serial", side_effect=exc):
            with self.assertRaises(badge_link.BadgeConnectionError) as cm:
                badge_link.connect("/dev/ttyACM9")
        return str(cm.exception)

    def test_missing(self):
        msg = self.connect_failing(
            badge_usb.serial.SerialException(errno.ENOENT, "could not open"))
        self.assertIn("No encuentro /dev/ttyACM9", msg)

    def test_permission(self):
        msg = self.connect_failing(
            badge_usb.serial.SerialException(errno.EACCES, "could not open"))
        self.assertIn("dialout", msg)

    def test_busy_exclusive_lock(self):
        msg = self.connect_failing(badge_usb.serial.SerialException(
            errno.EAGAIN, "Could not exclusively lock port"))
        self.assertIn("ocupado", msg)

    def test_busy_on_windows(self):
        exc = badge_usb.serial.SerialException(
            "could not open port 'COM3': PermissionError(13, 'Access is "
            "denied.', None, 5)")
        with mock.patch.object(badge_link.sys, "platform", "win32"):
            self.assertIn("ocupado", self.connect_failing(exc))

    def test_permission_is_not_busy_on_linux(self):
        exc = badge_usb.serial.SerialException(
            "could not open port: Permission denied")
        with mock.patch.object(badge_link.sys, "platform", "linux"):
            self.assertIn("dialout", self.connect_failing(exc))


class Connect(unittest.TestCase):
    def test_good_badge(self):
        port = FakePort(info_ok)
        serial_patch, sleep_patch = badge_on(port)
        with serial_patch, sleep_patch, comports(BADGE):
            badge = badge_link.connect()
        self.assertIsInstance(badge, badge_usb.Badge)
        self.assertFalse(port.closed)

    def test_not_a_badge_closes_port(self):
        port = FakePort(lambda line: b"OK hello\r\n")
        serial_patch, sleep_patch = badge_on(port)
        with serial_patch, sleep_patch:
            with self.assertRaisesRegex(badge_link.BadgeConnectionError,
                                        "no es un Badge BugCON 2026"):
                badge_link.connect("/dev/fake")
        self.assertTrue(port.closed)

    def test_silent_port_says_asleep(self):
        port = FakePort()
        serial_patch, sleep_patch = badge_on(port)
        with serial_patch, sleep_patch, \
                mock.patch.object(badge_link, "GREET_TIMEOUT_S", 0.05):
            with self.assertRaisesRegex(badge_link.BadgeConnectionError,
                                        "dormido"):
                badge_link.connect("/dev/fake")
        self.assertTrue(port.closed)


class Explain(unittest.TestCase):
    # Todos los ERR de usb_protocol.h
    CODES = ("badcmd badslot empty timeout flash badnick badver badteam "
             "badpos badstats badhandle badtime badcolor badtokens full "
             "wrong locked").split()

    def test_every_code_has_spanish_text(self):
        for code in self.CODES:
            text = badge_link.explain(badge_usb.ProtocolError(f"ERR {code}"))
            self.assertNotIn("ERR", text, code)
            self.assertNotEqual(text, "", code)
        self.assertEqual(set(self.CODES), set(badge_link.ERR_MESSAGES))

    def test_unknown_code_keeps_reply(self):
        self.assertIn("ERR nuevo", badge_link.explain("ERR nuevo algo"))

    def test_silent_timeout(self):
        self.assertEqual(badge_link.explain(badge_usb.ProtocolError("timeout")),
                         badge_link.ASLEEP)


class Call(unittest.TestCase):
    def setUp(self):
        sleep = mock.patch.object(badge_link.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)
        short = mock.patch.object(badge_link, "GREET_TIMEOUT_S", 0.05)
        short.start()
        self.addCleanup(short.stop)

    def badge(self):
        """Badge sobre un FakePort mudo; cada prueba simula read_reply."""
        port = FakePort()
        badge = badge_usb.Badge.__new__(badge_usb.Badge)
        badge.port = port
        return badge, port

    def test_idempotent_retried_once_after_silence(self):
        badge, port = self.badge()
        # La primera vez no contesta: se espera, se saluda y se repite
        with mock.patch.object(badge, "read_reply",
                               side_effect=[badge_usb.ProtocolError("timeout"),
                                            "OK BB26 x", "OK slow=10"]):
            self.assertEqual(badge_link.call(badge, "UPLD 0", b"\0"),
                             "OK slow=10")
        self.sleep.assert_called_with(badge_link.PAYLOAD_WAIT_S)
        sent = [w for w in port.written if w.startswith(b"UPLD")]
        self.assertEqual(len(sent), 2)

    def test_err_timeout_retries_without_waiting(self):
        badge, port = self.badge()
        with mock.patch.object(badge, "read_reply",
                               side_effect=["ERR timeout", "OK BB26 x", "OK"]):
            self.assertEqual(badge_link.call(badge, "AVTR", b"\0"), "OK")
        self.sleep.assert_not_called()

    def test_second_silence_says_asleep(self):
        badge, _ = self.badge()
        silent = badge_usb.ProtocolError("timeout")
        with mock.patch.object(badge, "read_reply",
                               side_effect=[silent, "OK BB26 x", silent]):
            with self.assertRaisesRegex(badge_link.BadgeConnectionError,
                                        "dormido"):
                badge_link.call(badge, "PWR")

    def test_flag_is_not_retried(self):
        badge, port = self.badge()
        with mock.patch.object(badge, "read_reply",
                               side_effect=badge_usb.ProtocolError("timeout")):
            with self.assertRaises(badge_usb.ProtocolError):
                badge_link.call(badge, "FLAG abc")
        self.assertEqual(len(port.written), 1)

    def test_other_errors_pass_through(self):
        badge, port = self.badge()
        with mock.patch.object(badge, "read_reply", return_value="ERR badslot"), \
                self.assertRaisesRegex(badge_usb.ProtocolError, "ERR badslot"):
            badge_link.call(badge, "SHOW 9")
        self.assertEqual(len(port.written), 1)

    def test_idempotent_set_matches_plan(self):
        self.assertEqual(
            badge_link.IDEMPOTENT,
            set("INFO TIME SHOW READ ALBM LED CLR PWR UPLD AVTR CARD "
                "NICK".split()))


if __name__ == "__main__":
    unittest.main()
