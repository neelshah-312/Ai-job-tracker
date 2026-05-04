import os
import unittest
from datetime import datetime, timezone

from services import gmail_service as gs


class GmailServiceTests(unittest.TestCase):
    def test_credential_paths_from_environment(self):
        old_cred = os.environ.get("GMAIL_CREDENTIALS_PATH")
        old_token = os.environ.get("GMAIL_TOKEN_PATH")
        try:
            os.environ["GMAIL_CREDENTIALS_PATH"] = "Secrets/credentials.json"
            os.environ["GMAIL_TOKEN_PATH"] = "Secrets/token.json"
            cred, token = gs.credential_paths()
            self.assertEqual(cred.as_posix(), "Secrets/credentials.json")
            self.assertEqual(token.as_posix(), "Secrets/token.json")
        finally:
            if old_cred is None:
                os.environ.pop("GMAIL_CREDENTIALS_PATH", None)
            else:
                os.environ["GMAIL_CREDENTIALS_PATH"] = old_cred
            if old_token is None:
                os.environ.pop("GMAIL_TOKEN_PATH", None)
            else:
                os.environ["GMAIL_TOKEN_PATH"] = old_token

    def test_message_date_iso_falls_back_to_internal_date(self):
        internal_ms = "1714656000000"
        msg = {"payload": {"headers": []}, "internalDate": internal_ms}
        iso = gs.message_date_iso(msg)
        self.assertIsNotNone(iso)
        expected = datetime.fromtimestamp(int(internal_ms) / 1000, tz=timezone.utc).isoformat()
        self.assertEqual(iso, expected)

    def test_normalize_message_extracts_headers(self):
        msg = {
            "id": "m1",
            "threadId": "t1",
            "snippet": "snippet text",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Hello"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "To", "value": "to@example.com"},
                    {"name": "Cc", "value": "cc@example.com"},
                    {"name": "Date", "value": "Mon, 04 May 2026 10:00:00 +0000"},
                ],
                "body": {"data": ""},
            },
        }
        norm = gs.normalize_message(msg, "inbound")
        self.assertEqual(norm["gmail_message_id"], "m1")
        self.assertEqual(norm["gmail_thread_id"], "t1")
        self.assertEqual(norm["direction"], "inbound")
        self.assertEqual(norm["subject"], "Hello")
        self.assertIn("to@example.com", norm["recipients"])
        self.assertIn("cc@example.com", norm["recipients"])

    def test_thread_url(self):
        self.assertEqual(gs.gmail_thread_url("abc"), "https://mail.google.com/mail/u/0/#inbox/abc")


if __name__ == "__main__":
    unittest.main()
