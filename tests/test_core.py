#!/usr/bin/env python3
"""Smoke tests for callsign validation, storage, APRS parse (no network)."""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aprs_messenger.aprs_is import AprsIsClient, parse_aprs_message_line  # noqa: E402
from aprs_messenger.callsign import (  # noqa: E402
    aprs_addressee,
    is_valid_callsign,
    normalize_callsign,
)
from aprs_messenger.chat import split_aprs_message  # noqa: E402
from aprs_messenger.storage import Storage  # noqa: E402


class SplitMessageTests(unittest.TestCase):
    def test_short_unchanged(self):
        self.assertEqual(split_aprs_message("hello"), ["hello"])

    def test_splits_long(self):
        parts = split_aprs_message("a" * 68)
        self.assertEqual([len(p) for p in parts], [67, 1])


class CallsignTests(unittest.TestCase):
    def test_valid(self):
        for c in ("W1AW", "G0ABC", "VK2XYZ", "2E0ABC", "N0CALL", "ja1yxx"):
            self.assertTrue(is_valid_callsign(c), c)

    def test_invalid(self):
        for c in ("", "ABC", "123", "TOOLONGCALLX", "N0"):
            self.assertFalse(is_valid_callsign(c), c)

    def test_addressee(self):
        self.assertEqual(len(aprs_addressee("W1AW")), 9)
        self.assertTrue(aprs_addressee("W1AW").startswith("W1AW"))


class ParseTests(unittest.TestCase):
    def test_message(self):
        line = "N0CALL>APRS,TCPIP*::W1AW     :Hello world{42"
        m = parse_aprs_message_line(line)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.from_call, "N0CALL")
        self.assertEqual(m.to_call, "W1AW")
        self.assertEqual(m.body, "Hello world")
        self.assertEqual(m.msg_id, "42")
        self.assertFalse(m.is_ack)

    def test_ack(self):
        line = "W1AW>APRS,TCPIP*::N0CALL   :ack42"
        m = parse_aprs_message_line(line)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertTrue(m.is_ack)
        self.assertEqual(m.msg_id, "42")
        self.assertEqual(m.to_call, "N0CALL")

    def test_braces_in_body_not_msgid(self):
        """Curly braces in the text must not be stripped as a message id."""
        line = "X>APRS,TCPIP*::N0CALL   :code {foo} bar"
        m = parse_aprs_message_line(line)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.body, "code {foo} bar")
        self.assertEqual(m.msg_id, "")
        self.assertFalse(m.is_ack)

    def test_trailing_msgid_still_parsed(self):
        line = "X>APRS,TCPIP*::N0CALL   :hi there{AB12"
        m = parse_aprs_message_line(line)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.body, "hi there")
        self.assertEqual(m.msg_id, "AB12")

    def test_brace_then_real_msgid(self):
        """Text may contain '{' and still end with a valid {msgid."""
        line = "X>APRS,TCPIP*::N0CALL   :use {n} times{03"
        m = parse_aprs_message_line(line)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.body, "use {n} times")
        self.assertEqual(m.msg_id, "03")

    def test_invalid_trailing_brace_kept_in_body(self):
        """Trailing { with non-alnum or empty is not a msg id."""
        line = "X>APRS,TCPIP*::N0CALL   :oops{!!"
        m = parse_aprs_message_line(line)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.body, "oops{!!")
        self.assertEqual(m.msg_id, "")


class ClientFilterTests(unittest.TestCase):
    """ACKs/REJs/messages must be addressed to our station before callback."""

    def _collect(self, our_call: str, lines: list[str]):
        seen = []
        client = AprsIsClient(our_call, "0", on_message=seen.append)
        for line in lines:
            client._handle_line(line)
        return seen

    def test_send_message_while_disconnected_raises(self):
        client = AprsIsClient("N0CALL", "0")
        self.assertFalse(client.connected)
        with self.assertRaises(ConnectionError):
            client.send_message("W1AW", "hello")
        self.assertEqual(client._send_q.qsize(), 0)

    def test_send_message_while_connected_queues(self):
        client = AprsIsClient("N0CALL", "0")
        client._connected = True  # simulate post-login
        mid = client.send_message("W1AW", "hello")
        self.assertTrue(mid)
        self.assertEqual(client._send_q.qsize(), 1)

    def test_ack_to_us_accepted(self):
        lines = ["W1AW>APRS,TCPIP*::N0CALL   :ack42"]
        seen = self._collect("N0CALL", lines)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].is_ack)
        self.assertEqual(seen[0].msg_id, "42")

    def test_ack_to_other_station_dropped(self):
        """Foreign ACK (not addressed to us) must not reach the UI."""
        lines = ["W1AW>APRS,TCPIP*::K1ABC    :ack42"]
        seen = self._collect("N0CALL", lines)
        self.assertEqual(seen, [])

    def test_rej_to_us_accepted(self):
        lines = ["W1AW>APRS,TCPIP*::N0CALL   :rej7"]
        seen = self._collect("N0CALL", lines)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].is_rej)

    def test_message_to_other_dropped(self):
        lines = ["W1AW>APRS,TCPIP*::K1ABC    :Hello{01"]
        seen = self._collect("N0CALL", lines)
        self.assertEqual(seen, [])

    def test_ssid_tolerant_address(self):
        lines = ["W1AW>APRS,TCPIP*::N0CALL-7 :ack99"]
        seen = self._collect("N0CALL", lines)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].is_ack)


class StorageTests(unittest.TestCase):
    def test_contacts_and_messages(self):
        with tempfile.TemporaryDirectory() as td:
            s = Storage(Path(td) / "t.db")
            s.set_credentials("W1AW", "12345")
            self.assertTrue(s.is_configured())
            ct = s.add_contact("N0CALL", "Test Op")
            self.assertEqual(s.contact_count(), 1)
            s.add_message("N0CALL", "out", "Hi", msg_id="01", status="sent")
            n = s.update_message_status("01", "delivered", peer="N0CALL")
            self.assertEqual(n, 1)
            msgs = s.list_messages("N0CALL")
            self.assertEqual(msgs[0].status, "delivered")
            s.delete_contact(ct.id)
            self.assertEqual(s.contact_count(), 0)
            s.close()

    def test_ack_status_scoped_to_peer(self):
        """Same msg_id on two peers: ACK for one must not deliver the other."""
        with tempfile.TemporaryDirectory() as td:
            s = Storage(Path(td) / "t.db")
            s.add_message("N0AAA", "out", "to A", msg_id="01", status="sent")
            s.add_message("N0BBB", "out", "to B", msg_id="01", status="sent")
            n = s.update_message_status("01", "delivered", peer="N0AAA")
            self.assertEqual(n, 1)
            self.assertEqual(s.list_messages("N0AAA")[0].status, "delivered")
            self.assertEqual(s.list_messages("N0BBB")[0].status, "sent")
            # Already delivered: second update should not match pending/sent
            n2 = s.update_message_status("01", "delivered", peer="N0AAA")
            self.assertEqual(n2, 0)
            s.close()

    def test_concurrent_message_writes(self):
        """SQLite access from multiple threads must not corrupt the DB."""
        with tempfile.TemporaryDirectory() as td:
            s = Storage(Path(td) / "t.db")
            errors: list[BaseException] = []

            def writer(peer: str, n: int) -> None:
                try:
                    for i in range(n):
                        s.add_message(peer, "out", f"msg-{i}", msg_id=f"{i:02d}")
                        s.list_messages(peer)
                except BaseException as e:  # noqa: BLE001 — surface in main thread
                    errors.append(e)

            threads = [
                threading.Thread(target=writer, args=("N0AAA", 40)),
                threading.Thread(target=writer, args=("N0BBB", 40)),
                threading.Thread(target=writer, args=("N0CCC", 40)),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(s.list_messages("N0AAA")), 40)
            self.assertEqual(len(s.list_messages("N0BBB")), 40)
            self.assertEqual(len(s.list_messages("N0CCC")), 40)
            s.close()


if __name__ == "__main__":
    unittest.main()
