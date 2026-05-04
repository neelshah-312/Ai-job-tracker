import sqlite3
import unittest
from pathlib import Path

from db import database as db
from services.sync_logic import ingest_normalized_message


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema = (Path(__file__).resolve().parents[1] / "db" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()
    return conn


class DatabaseAndSyncTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()

    def tearDown(self):
        self.conn.close()

    def test_insert_and_update_application(self):
        app_id = db.insert_application(
            self.conn,
            company="Acme",
            role_title="Analyst",
            status="Applied",
            gmail_thread_id="thr-1",
        )
        db.update_application(self.conn, app_id, {"status": "Interview"})
        self.conn.commit()

        app = db.get_application_by_id(self.conn, app_id)
        self.assertIsNotNone(app)
        self.assertEqual(app["status"], "Interview")

    def test_upsert_email_and_needs_review_count(self):
        email_id = db.upsert_email(
            self.conn,
            gmail_message_id="m-1",
            gmail_thread_id="t-1",
            direction="inbound",
            sender="a@example.com",
            recipients="b@example.com",
            subject="subj",
            email_date="2026-05-01",
            snippet="snip",
            classification="needs_review",
            company=None,
            role_title=None,
            extracted_json={"foo": "bar"},
            application_id=None,
        )
        self.conn.commit()
        self.assertIsInstance(email_id, int)
        self.assertEqual(db.count_emails_uncertain(self.conn), 1)

    def test_ingest_creates_application_for_job_related_email(self):
        normalized = {
            "gmail_message_id": "m-2",
            "gmail_thread_id": "t-2",
            "direction": "inbound",
            "sender": "recruiter@example.com",
            "recipients": "me@example.com",
            "subject": "Application received",
            "email_date": "2026-05-04T10:00:00+00:00",
            "snippet": "thanks for applying",
        }
        extracted = {
            "email_type": "application_confirmation",
            "is_job_related": True,
            "company": "Contoso",
            "role_title": "SOC Analyst",
            "status": "Applied",
            "confidence": 0.8,
            "followup_needed": True,
            "applied_date": "2026-05-04",
        }
        email_id, app_id = ingest_normalized_message(self.conn, normalized=normalized, extracted=extracted)
        self.conn.commit()

        self.assertIsInstance(email_id, int)
        self.assertIsNotNone(app_id)
        app = db.get_application_by_id(self.conn, app_id)
        self.assertEqual(app["company"], "Contoso")
        self.assertEqual(app["role_title"], "SOC Analyst")

    def test_ingest_skips_application_for_not_job_related(self):
        normalized = {
            "gmail_message_id": "m-3",
            "gmail_thread_id": "t-3",
            "direction": "inbound",
            "sender": "newsletter@example.com",
            "recipients": "me@example.com",
            "subject": "Promo",
            "email_date": "2026-05-04",
            "snippet": "newsletter",
        }
        extracted = {
            "email_type": "not_job_related",
            "is_job_related": False,
        }
        _, app_id = ingest_normalized_message(self.conn, normalized=normalized, extracted=extracted)
        self.conn.commit()
        self.assertIsNone(app_id)


if __name__ == "__main__":
    unittest.main()
