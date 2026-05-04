"""
Email ingestion pipeline.

Takes a normalized message dict + LLM extraction dict and writes
the appropriate rows to `emails` and `applications`.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from db import database as db
from services.followup_service import (
    STATUS_FROM_EMAIL_TYPE,
    SOURCE_FROM_EMAIL_TYPE,
    compute_followup_due_date,
    parse_iso_date,
)
from services.gmail_service import gmail_thread_url


def _safe_str(val: Any) -> Optional[str]:
    return str(val).strip() or None if val else None


def apply_extraction_to_application(
    conn,
    *,
    thread_id:  Optional[str],
    email_date: Optional[str],
    extracted:  dict[str, Any],
) -> int:
    """
    Upsert an `applications` row from LLM extraction output.
    Creates a new row if thread_id is new; patches an existing row otherwise.
    Returns the application id.
    """
    email_type    = _safe_str(extracted.get("email_type")) or "needs_review"
    company       = _safe_str(extracted.get("company"))
    role_title    = _safe_str(extracted.get("role_title"))
    contact_name  = _safe_str(extracted.get("contact_name"))
    contact_email = _safe_str(extracted.get("contact_email"))
    status        = _safe_str(extracted.get("status")) or STATUS_FROM_EMAIL_TYPE.get(email_type, "Needs Review")
    source_type   = SOURCE_FROM_EMAIL_TYPE.get(email_type, "Other")

    applied_raw = extracted.get("applied_date") or extracted.get("last_interaction_date")
    anchor = parse_iso_date(applied_raw) or parse_iso_date(email_date) or date.today()

    follow_due = compute_followup_due_date(email_type, anchor)
    follow_due_s = follow_due.isoformat() if follow_due else None
    followup_status = "open" if extracted.get("followup_needed") else "none"

    try:
        ai_confidence = float(extracted["confidence"]) if "confidence" in extracted else None
    except (TypeError, ValueError):
        ai_confidence = None

    thread_link = gmail_thread_url(thread_id) if thread_id else None

    # ── Update path ────────────────────────────────────────────────────────────
    existing = thread_id and db.get_application_by_thread(conn, thread_id)
    if existing:
        patch: dict[str, Any] = {"status": status, "followup_status": followup_status}
        if company:          patch["company"]           = company
        if role_title:       patch["role_title"]        = role_title
        if source_type:      patch["source_type"]       = source_type
        if contact_name:     patch["contact_name"]      = contact_name
        if contact_email:    patch["contact_email"]     = contact_email
        if applied_raw:      patch["applied_date"]      = applied_raw[:10] if isinstance(applied_raw, str) else None
        if email_date:       patch["last_email_date"]   = email_date
        if follow_due_s:     patch["followup_due_date"] = follow_due_s
        if thread_id:        patch["gmail_thread_id"]   = thread_id
        if thread_link:      patch["gmail_thread_link"] = thread_link
        if ai_confidence is not None: patch["ai_confidence"] = ai_confidence
        db.update_application(conn, int(existing["id"]), patch)
        return int(existing["id"])

    # ── Insert path ────────────────────────────────────────────────────────────
    return db.insert_application(
        conn,
        company           = company,
        role_title        = role_title,
        source_type       = source_type,
        status            = status,
        applied_date      = applied_raw[:10] if isinstance(applied_raw, str) else None,
        last_email_date   = email_date,
        followup_due_date = follow_due_s,
        followup_status   = followup_status,
        contact_name      = contact_name,
        contact_email     = contact_email,
        gmail_thread_id   = thread_id,
        gmail_thread_link = thread_link,
        ai_confidence     = ai_confidence,
    )


def ingest_normalized_message(
    conn,
    *,
    normalized: dict[str, Any],
    extracted:  Optional[dict[str, Any]],
) -> tuple[int, Optional[int]]:
    """
    Save one email + optionally create/update its application.
    Returns (email_row_id, application_id).
    """
    ext            = extracted or {}
    classification = _safe_str(ext.get("email_type")) or "needs_review"
    company        = _safe_str(ext.get("company"))
    role_title     = _safe_str(ext.get("role_title"))
    thread_id      = normalized.get("gmail_thread_id")

    # Skip application creation for non-job emails or when LLM wasn't run
    skip_app = (
        extracted is None
        or ext.get("is_job_related") is False
        or classification == "not_job_related"
    )

    app_id: Optional[int] = None
    if not skip_app:
        app_id = apply_extraction_to_application(
            conn,
            thread_id  = thread_id,
            email_date = normalized.get("email_date"),
            extracted  = ext,
        )

    email_id = db.upsert_email(
        conn,
        gmail_message_id = normalized["gmail_message_id"],
        gmail_thread_id  = thread_id,
        direction        = normalized["direction"],
        sender           = normalized.get("sender"),
        recipients       = normalized.get("recipients"),
        subject          = normalized.get("subject"),
        email_date       = normalized.get("email_date"),
        snippet          = normalized.get("snippet"),
        classification   = classification,
        company          = company,
        role_title       = role_title,
        extracted_json   = ext or None,
        application_id   = app_id,
    )
    return email_id, app_id
