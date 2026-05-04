"""
SQLite database layer for Job Tracker AI.

All public functions accept an open sqlite3.Connection so callers control
transaction boundaries.  Use get_connection() to open one, and always
close it in a try/finally block.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "job_tracker.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# ── Valid column names (guards against SQL injection in update_application) ──

APPLICATION_COLUMNS = {
    "company", "role_title", "job_location", "job_url", "source_type", "status",
    "applied_date", "last_email_date", "followup_due_date", "followup_status",
    "contact_name", "contact_email", "resume_drive_link", "gmail_thread_id",
    "gmail_thread_link", "ai_confidence", "notes", "created_at", "updated_at",
}

ORDER_CLAUSES = {
    "default":      "followup_due_date IS NULL, followup_due_date ASC, company COLLATE NOCASE ASC",
    "created_desc": "datetime(created_at) DESC",
    "company":      "company COLLATE NOCASE ASC",
    "followup_due": "followup_due_date IS NULL, followup_due_date ASC",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    return {k: row[k] for k in row.keys()} if row else None


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    """Open a new connection.  Caller is responsible for closing it."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db() -> None:
    """Create tables if they don't exist.  Safe to call multiple times."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


# ── Applications ──────────────────────────────────────────────────────────────

def insert_application(
    conn: sqlite3.Connection,
    *,
    company:           Optional[str] = None,
    role_title:        Optional[str] = None,
    job_location:      Optional[str] = None,
    job_url:           Optional[str] = None,
    source_type:       Optional[str] = None,
    status:            Optional[str] = None,
    applied_date:      Optional[str] = None,
    last_email_date:   Optional[str] = None,
    followup_due_date: Optional[str] = None,
    followup_status:   Optional[str] = None,
    contact_name:      Optional[str] = None,
    contact_email:     Optional[str] = None,
    resume_drive_link: Optional[str] = None,
    gmail_thread_id:   Optional[str] = None,
    gmail_thread_link: Optional[str] = None,
    ai_confidence:     Optional[float] = None,
    notes:             Optional[str] = None,
) -> int:
    now = _now()
    cur = conn.execute(
        """
        INSERT INTO applications (
            company, role_title, job_location, job_url, source_type, status,
            applied_date, last_email_date, followup_due_date, followup_status,
            contact_name, contact_email, resume_drive_link,
            gmail_thread_id, gmail_thread_link, ai_confidence, notes,
            created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            company, role_title, job_location, job_url, source_type, status,
            applied_date, last_email_date, followup_due_date, followup_status,
            contact_name, contact_email, resume_drive_link,
            gmail_thread_id, gmail_thread_link, ai_confidence, notes,
            now, now,
        ),
    )
    return int(cur.lastrowid)


def update_application(
    conn: sqlite3.Connection,
    application_id: int,
    fields: dict[str, Any],
) -> None:
    if not fields:
        return
    bad = sorted(set(fields) - APPLICATION_COLUMNS)
    if bad:
        raise ValueError(f"Unknown application column(s): {', '.join(bad)}")
    payload = {**fields, "updated_at": _now()}
    cols = ", ".join(f"{k} = ?" for k in payload)
    conn.execute(
        f"UPDATE applications SET {cols} WHERE id = ?",
        [*payload.values(), application_id],
    )


def get_application_by_id(
    conn: sqlite3.Connection, application_id: int
) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM applications WHERE id = ? LIMIT 1", (application_id,)
    ).fetchone()
    return _row(row)


def get_application_by_thread(
    conn: sqlite3.Connection, gmail_thread_id: str
) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM applications WHERE gmail_thread_id = ? LIMIT 1",
        (gmail_thread_id,),
    ).fetchone()
    return _row(row)


def delete_application(conn: sqlite3.Connection, application_id: int) -> None:
    conn.execute("DELETE FROM emails    WHERE application_id = ?", (application_id,))
    conn.execute("DELETE FROM followups WHERE application_id = ?", (application_id,))
    conn.execute("DELETE FROM applications WHERE id = ?",          (application_id,))


def iter_applications(
    conn: sqlite3.Connection,
    order_by: str = "default",
) -> list[dict]:
    clause = ORDER_CLAUSES.get(order_by)
    if not clause:
        raise ValueError(f"Unknown order_by key: {order_by!r}")
    rows = conn.execute(
        f"SELECT * FROM applications ORDER BY {clause}"
    ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def get_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """All dashboard KPIs in one round-trip group."""
    c = conn.cursor()
    today = "date('now')"
    return {
        "total":       c.execute("SELECT COUNT(*) FROM applications").fetchone()[0],
        "cold_emails": c.execute("SELECT COUNT(*) FROM applications WHERE status='Cold Email Sent'").fetchone()[0],
        "referrals":   c.execute("SELECT COUNT(*) FROM applications WHERE status='Referral Request Sent'").fetchone()[0],
        "interviews":  c.execute("SELECT COUNT(*) FROM applications WHERE status='Interview'").fetchone()[0],
        "rejections":  c.execute("SELECT COUNT(*) FROM applications WHERE status='Rejected'").fetchone()[0],
        "offers":      c.execute("SELECT COUNT(*) FROM applications WHERE status='Offer'").fetchone()[0],
        "due_today":   c.execute(f"SELECT COUNT(*) FROM applications WHERE followup_due_date IS NOT NULL AND date(followup_due_date) = {today}").fetchone()[0],
        "overdue":     c.execute(f"SELECT COUNT(*) FROM applications WHERE followup_due_date IS NOT NULL AND date(followup_due_date) < {today}").fetchone()[0],
        "no_resume":   c.execute("SELECT COUNT(*) FROM applications WHERE resume_drive_link IS NULL OR resume_drive_link = ''").fetchone()[0],
        "by_status":   c.execute("SELECT status, COUNT(*) n FROM applications WHERE status IS NOT NULL GROUP BY status ORDER BY n DESC").fetchall(),
        "by_source":   c.execute("SELECT source_type, COUNT(*) n FROM applications WHERE source_type IS NOT NULL GROUP BY source_type ORDER BY n DESC").fetchall(),
        "timeline":    c.execute("SELECT applied_date, COUNT(*) n FROM applications WHERE applied_date IS NOT NULL GROUP BY applied_date ORDER BY applied_date ASC").fetchall(),
    }


# ── Emails ────────────────────────────────────────────────────────────────────

def upsert_email(
    conn: sqlite3.Connection,
    *,
    gmail_message_id: str,
    gmail_thread_id:  Optional[str],
    direction:        str,
    sender:           Optional[str],
    recipients:       Optional[str],
    subject:          Optional[str],
    email_date:       Optional[str],
    snippet:          Optional[str],
    classification:   Optional[str],
    company:          Optional[str],
    role_title:       Optional[str],
    extracted_json:   Optional[dict],
    application_id:   Optional[int],
) -> int:
    blob = json.dumps(extracted_json) if extracted_json else None
    conn.execute(
        """
        INSERT INTO emails (
            gmail_message_id, gmail_thread_id, direction, sender, recipients,
            subject, email_date, snippet, classification, company, role_title,
            extracted_json, application_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(gmail_message_id) DO UPDATE SET
            classification  = excluded.classification,
            company         = excluded.company,
            role_title      = excluded.role_title,
            extracted_json  = excluded.extracted_json,
            application_id  = excluded.application_id,
            snippet         = excluded.snippet
        """,
        (
            gmail_message_id, gmail_thread_id, direction, sender, recipients,
            subject, email_date, snippet, classification, company, role_title,
            blob, application_id,
        ),
    )
    row = conn.execute(
        "SELECT id FROM emails WHERE gmail_message_id = ?", (gmail_message_id,)
    ).fetchone()
    return int(row["id"])


def get_email_ids_in_db(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT gmail_message_id FROM emails").fetchall()
    return {r[0] for r in rows if r[0]}


def list_emails_needs_review(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM emails
        WHERE classification IN ('needs_review','not_job_related') OR classification IS NULL
        ORDER BY email_date DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def list_emails_for_application(conn: sqlite3.Connection, application_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM emails WHERE application_id = ? ORDER BY email_date DESC",
        (application_id,),
    ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


# ── Follow-ups ────────────────────────────────────────────────────────────────

def insert_followup(
    conn: sqlite3.Connection,
    *,
    application_id: int,
    followup_type:  str,
    due_date:       str,
    status:         str = "open",
    draft_text:     Optional[str] = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO followups (application_id, followup_type, due_date, status, draft_text, created_at)
        VALUES (?,?,?,?,?,?)
        """,
        (application_id, followup_type, due_date, status, draft_text, _now()),
    )
    return int(cur.lastrowid)


def complete_followup(conn: sqlite3.Connection, followup_id: int) -> None:
    conn.execute(
        "UPDATE followups SET status='done', completed_at=? WHERE id=?",
        (_now(), followup_id),
    )


def list_open_followups(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT f.*, a.company, a.role_title, a.status AS app_status
        FROM followups f
        JOIN applications a ON a.id = f.application_id
        WHERE f.status = 'open'
        ORDER BY f.due_date ASC
        """
    ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]
