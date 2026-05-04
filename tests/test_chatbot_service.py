import sqlite3
import unittest
from pathlib import Path

from services.chatbot_service import answer_question


def seeded_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    schema = (Path(__file__).resolve().parents[1] / "db" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.execute(
        """
        INSERT INTO applications (
            company, role_title, status, followup_due_date, resume_drive_link, applied_date
        ) VALUES (?, ?, ?, date('now'), ?, ?)
        """,
        ("Contoso", "SOC Analyst", "Applied", "", "2026-05-01"),
    )
    conn.commit()
    return conn


class ChatbotServiceTests(unittest.TestCase):
    def test_answer_question_due_today_without_llm(self):
        conn = seeded_conn()
        try:
            answer = answer_question(conn, "what follow up today", use_llm=False)
            self.assertIn("Follow-ups due today", answer)
            self.assertIn("Contoso", answer)
        finally:
            conn.close()

    def test_answer_question_statistics_without_llm(self):
        conn = seeded_conn()
        try:
            answer = answer_question(conn, "show dashboard statistics", use_llm=False)
            self.assertIn("Totals", answer)
            self.assertIn("applications", answer)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
