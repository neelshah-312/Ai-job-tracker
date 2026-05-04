"""
Follow-up Center — overdue alerts, mark-done buttons, and AI draft generator.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from db import database as db
from services.followup_service import (
    email_type_for_status,
    parse_iso_date,
    suggest_followup_action,
)

load_dotenv(ROOT / ".env")
db.init_db()

st.set_page_config(page_title="Follow-up Center — Job Tracker AI", layout="wide")
st.title("⏰ Follow-up Center")

today   = date.today()
today_s = today.isoformat()

# ── Load all non-terminal applications ────────────────────────────────────────
conn = db.get_connection()
try:
    all_apps = db.iter_applications(conn)
finally:
    conn.close()

TERMINAL = {"Rejected", "Offer"}

rows = []
for a in all_apps:
    if a.get("status") in TERMINAL:
        continue
    last_dt = parse_iso_date(a.get("last_email_date")) or parse_iso_date(a.get("applied_date"))
    kind    = email_type_for_status(a.get("status") or "Applied")
    due     = (a.get("followup_due_date") or "")[:10]
    rows.append({
        "id":             a["id"],
        "company":        a.get("company")    or "—",
        "role":           a.get("role_title") or "—",
        "status":         a.get("status")     or "—",
        "last_action":    last_dt.isoformat() if last_dt else "—",
        "days_since":     (today - last_dt).days if last_dt else None,
        "followup_due":   due,
        "overdue":        bool(due and due < today_s),
        "followup_status":a.get("followup_status") or "",
        "suggested":      suggest_followup_action(kind, a.get("status") or ""),
    })

overdue_rows  = [r for r in rows if r["overdue"] and r["followup_status"] != "done"]
pending_rows  = [r for r in rows if not r["overdue"] and r["followup_status"] != "done"]
done_rows     = [r for r in rows if r["followup_status"] == "done"]


# ── Overdue alert block ────────────────────────────────────────────────────────
if overdue_rows:
    st.error(f"🔴 {len(overdue_rows)} overdue follow-up(s) need attention")
    for item in overdue_rows:
        with st.container(border=True):
            left, right = st.columns([5, 1])
            with left:
                st.markdown(
                    f"**{item['company']}** · _{item['role']}_ · `{item['status']}`  \n"
                    f"Due: **{item['followup_due']}** · Last contact: {item['last_action']}  \n"
                    f"💡 {item['suggested']}"
                )
            with right:
                if st.button("✅ Done", key=f"od_{item['id']}", use_container_width=True):
                    c = db.get_connection()
                    try:
                        db.update_application(c, item["id"], {"followup_status": "done"})
                        c.commit()
                    finally:
                        c.close()
                    st.rerun()
    st.divider()


# ── Upcoming follow-ups table ──────────────────────────────────────────────────
st.subheader("📋 Active follow-ups")

if not rows:
    st.info("Nothing to chase — all applications are at a terminal status (Rejected / Offer).")
elif not pending_rows and not overdue_rows:
    st.success("All follow-ups are marked done. ✅")
else:
    display = [
        {
            "Company":        r["company"],
            "Role":           r["role"],
            "Status":         r["status"],
            "Last action":    r["last_action"],
            "Days since":     r["days_since"],
            "Follow-up due":  r["followup_due"],
            "Suggested":      r["suggested"],
        }
        for r in pending_rows
    ]
    if display:
        df = pd.DataFrame(display).sort_values("Follow-up due", na_position="last")
        st.dataframe(df, hide_index=True, use_container_width=True)

    if pending_rows:
        with st.expander("Mark individual follow-ups done"):
            for item in pending_rows:
                col_l, col_r = st.columns([6, 1])
                col_l.markdown(
                    f"**#{item['id']}** {item['company']} · {item['role']} "
                    f"· due **{item['followup_due']}**"
                )
                if col_r.button("Done", key=f"pnd_{item['id']}", use_container_width=True):
                    c = db.get_connection()
                    try:
                        db.update_application(c, item["id"], {"followup_status": "done"})
                        c.commit()
                    finally:
                        c.close()
                    st.rerun()

st.divider()

# ── Draft generator ────────────────────────────────────────────────────────────
st.subheader("✍️ Generate follow-up draft")

active = overdue_rows + pending_rows
if not active:
    st.caption("No active follow-ups to draft for.")
else:
    pick_map = {f"#{r['id']} {r['company']} · {r['role']}": r["id"] for r in active}
    pick     = st.selectbox("Select application", list(pick_map.keys()))
    aid      = pick_map[pick]

    conn = db.get_connection()
    try:
        app_row  = db.get_application_by_id(conn, aid)
        email_rows = db.list_emails_for_application(conn, aid)
    finally:
        conn.close()

    if app_row:
        snippets = [f"Subject: {e['subject']}\nSnippet: {e['snippet']}" for e in email_rows[:5]]
        context  = ((app_row.get("notes") or "") + "\n\n" + "\n".join(snippets)).strip()

        draft_key = f"draft_{aid}"

        col_gen, col_clr = st.columns([2, 1])
        gen_clicked = col_gen.button("🤖 Generate draft", type="primary")
        if draft_key in st.session_state and col_clr.button("🗑️ Clear"):
            del st.session_state[draft_key]
            st.rerun()

        if gen_clicked:
            from services import llm_service
            if not llm_service.api_key_configured():
                st.error("OPENAI_API_KEY is not set. Add it to your .env file.")
            else:
                with st.spinner("Drafting email…"):
                    try:
                        draft = llm_service.draft_followup_email(
                            company       = app_row.get("company")    or "the team",
                            role_title    = app_row.get("role_title") or "the role",
                            status        = app_row.get("status")     or "Applied",
                            prior_context = context,
                        )
                        st.session_state[draft_key] = draft
                    except Exception as exc:
                        st.error(str(exc))

        if draft_key in st.session_state:
            st.text_area("Email draft", st.session_state[draft_key], height=260)
            st.code(st.session_state[draft_key], language=None)
            st.caption("☝️ Use the copy icon (top-right of code block) to copy to clipboard.")

st.divider()

# ── Completed ──────────────────────────────────────────────────────────────────
if done_rows:
    with st.expander(f"Completed follow-ups ({len(done_rows)})"):
        for r in done_rows:
            st.markdown(f"- ~~**{r['company']}** · {r['role']}~~ ✓")
