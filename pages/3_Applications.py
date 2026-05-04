"""
Applications — add, edit, and delete job application records manually.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from db import database as db
from services.followup_service import (
    compute_followup_due_date,
    email_type_for_status,
    parse_iso_date,
)
from services.gmail_service import gmail_thread_url

load_dotenv(ROOT / ".env")
db.init_db()

st.set_page_config(page_title="Applications — Job Tracker AI", layout="wide")
st.title("📋 Applications")

STATUSES = [
    "Applied", "Cold Email Sent", "Referral Request Sent",
    "Recruiter Reply", "Interview", "Rejected", "Offer", "Ghosted", "Needs Review",
]
SOURCES = ["Direct", "ATS", "Cold Email", "Referral", "LinkedIn", "Recruiter", "Other"]


# ── Add ────────────────────────────────────────────────────────────────────────
st.subheader("➕ Add application")

with st.form("add_app", clear_on_submit=True):
    r1c1, r1c2, r1c3 = st.columns(3)
    company  = r1c1.text_input("Company *")
    role     = r1c2.text_input("Role title")
    location = r1c3.text_input("Location")

    r2c1, r2c2 = st.columns(2)
    job_url     = r2c1.text_input("Job URL")
    source_type = r2c2.selectbox("Source", SOURCES)

    r3c1, r3c2 = st.columns(2)
    status  = r3c1.selectbox("Status", STATUSES)
    applied = r3c2.text_input("Applied date (YYYY-MM-DD)")

    r4c1, r4c2 = st.columns(2)
    contact_name  = r4c1.text_input("Contact name")
    contact_email = r4c2.text_input("Contact email")

    thread_id = st.text_input(
        "Gmail thread ID (optional)",
        help="Copy from the Gmail URL: mail.google.com/mail/u/0/#inbox/<THREAD_ID>",
    )
    resume = st.text_input("Resume Drive link (optional)")
    notes  = st.text_area("Notes")

    submit = st.form_submit_button("💾 Save application", type="primary")

    if submit:
        if not company.strip():
            st.error("Company name is required.")
        else:
            anchor = parse_iso_date(applied.strip() or None)
            if applied.strip() and anchor is None:
                st.error("Applied date must be YYYY-MM-DD (e.g. 2026-05-01).")
            else:
                et  = email_type_for_status(status)
                due = compute_followup_due_date(et, anchor) if anchor else None
                lnk = gmail_thread_url(thread_id.strip()) if thread_id.strip() else None

                conn = db.get_connection()
                try:
                    aid = db.insert_application(
                        conn,
                        company           = company.strip(),
                        role_title        = role.strip()    or None,
                        job_location      = location.strip() or None,
                        job_url           = job_url.strip() or None,
                        source_type       = source_type,
                        status            = status,
                        applied_date      = applied.strip()[:10] or None,
                        followup_due_date = due.isoformat() if due else None,
                        followup_status   = "open",
                        contact_name      = contact_name.strip()  or None,
                        contact_email     = contact_email.strip() or None,
                        resume_drive_link = resume.strip() or None,
                        gmail_thread_id   = thread_id.strip() or None,
                        gmail_thread_link = lnk,
                        notes             = notes.strip() or None,
                    )
                    conn.commit()
                    st.success(f"✅ Saved as application **#{aid}**.")
                except Exception as exc:
                    st.error(f"Save failed: {exc}")
                finally:
                    conn.close()

st.divider()

# ── Edit / Delete ──────────────────────────────────────────────────────────────
st.subheader("✏️ Edit / delete")

conn = db.get_connection()
try:
    all_apps = conn.execute(
        "SELECT id, company, role_title, status FROM applications ORDER BY datetime(created_at) DESC"
    ).fetchall()
finally:
    conn.close()

if not all_apps:
    st.caption("No applications yet — add one above or run Gmail Sync.")
else:
    label_map = {
        f"#{r[0]} — {r[1] or '?'} · {r[2] or 'unknown role'} [{r[3]}]": r[0]
        for r in all_apps
    }
    selected_label = st.selectbox("Select application", list(label_map.keys()))
    sel_id = label_map[selected_label]

    conn = db.get_connection()
    try:
        row = db.get_application_by_id(conn, sel_id)
    finally:
        conn.close()

    if row:
        with st.form("edit_app"):
            e1, e2, e3 = st.columns(3)
            e_company  = e1.text_input("Company",   value=row["company"]      or "")
            e_role     = e2.text_input("Role title", value=row["role_title"]   or "")
            e_location = e3.text_input("Location",   value=row["job_location"] or "")

            u1, u2 = st.columns(2)
            e_url    = u1.text_input("Job URL", value=row["job_url"] or "")
            e_source = u2.selectbox(
                "Source", SOURCES,
                index=SOURCES.index(row["source_type"]) if row["source_type"] in SOURCES else 0,
            )

            s1, s2 = st.columns(2)
            e_status  = s1.selectbox(
                "Status", STATUSES,
                index=STATUSES.index(row["status"]) if row["status"] in STATUSES else 0,
            )
            e_applied = s2.text_input("Applied date", value=(row["applied_date"] or "")[:10])

            t1, t2 = st.columns(2)
            e_contact_name  = t1.text_input("Contact name",  value=row["contact_name"]  or "")
            e_contact_email = t2.text_input("Contact email", value=row["contact_email"] or "")

            e_thread = st.text_input("Gmail thread ID", value=row["gmail_thread_id"] or "")
            e_resume = st.text_input("Resume link",     value=row["resume_drive_link"] or "")
            e_notes  = st.text_area("Notes",            value=row["notes"] or "")

            anchor = parse_iso_date(e_applied.strip() or None)
            if anchor:
                et2 = email_type_for_status(e_status)
                due2 = compute_followup_due_date(et2, anchor)
                due2_iso = due2.isoformat() if due2 else ""
                st.caption(f"Follow-up due (auto): **{due2_iso or 'N/A'}**")
            else:
                due2_iso = ""

            btn_save, btn_del, _ = st.columns([1, 1, 4])
            do_save   = btn_save.form_submit_button("💾 Update", type="primary")
            do_delete = btn_del.form_submit_button("🗑️ Delete")

            if do_save:
                lnk2 = gmail_thread_url(e_thread.strip()) if e_thread.strip() else None
                conn = db.get_connection()
                try:
                    db.update_application(
                        conn, sel_id,
                        {
                            "company":           e_company.strip()       or None,
                            "role_title":        e_role.strip()          or None,
                            "job_location":      e_location.strip()      or None,
                            "job_url":           e_url.strip()           or None,
                            "source_type":       e_source,
                            "status":            e_status,
                            "applied_date":      e_applied.strip()[:10]  or None,
                            "followup_due_date": due2_iso                or None,
                            "contact_name":      e_contact_name.strip()  or None,
                            "contact_email":     e_contact_email.strip() or None,
                            "resume_drive_link": e_resume.strip()        or None,
                            "gmail_thread_id":   e_thread.strip()        or None,
                            "gmail_thread_link": lnk2,
                            "notes":             e_notes.strip()         or None,
                        },
                    )
                    conn.commit()
                    st.success("✅ Updated.")
                except Exception as exc:
                    st.error(f"Update failed: {exc}")
                finally:
                    conn.close()

            if do_delete:
                conn = db.get_connection()
                try:
                    db.delete_application(conn, sel_id)
                    conn.commit()
                finally:
                    conn.close()
                st.warning("🗑️ Application deleted.")
                st.rerun()
