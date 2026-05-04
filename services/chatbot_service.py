"""
Chatbot service — answers natural-language questions about job applications.

Strategy:
1. Try fast pattern-matching (no API cost, works offline).
2. Fall back to LLM with JSON context if a key is set.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from typing import Any

from services import llm_service


# ── Database summary ───────────────────────────────────────────────────────────

def _sql_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    c = conn.cursor()
    today = "date('now')"

    stats = {
        "total":       c.execute("SELECT COUNT(*) FROM applications").fetchone()[0],
        "cold_emails": c.execute("SELECT COUNT(*) FROM applications WHERE status='Cold Email Sent'").fetchone()[0],
        "referrals":   c.execute("SELECT COUNT(*) FROM applications WHERE status='Referral Request Sent'").fetchone()[0],
        "interviews":  c.execute("SELECT COUNT(*) FROM applications WHERE status='Interview'").fetchone()[0],
        "rejections":  c.execute("SELECT COUNT(*) FROM applications WHERE status='Rejected'").fetchone()[0],
        "offers":      c.execute("SELECT COUNT(*) FROM applications WHERE status='Offer'").fetchone()[0],
        "no_resume":   c.execute("SELECT COUNT(*) FROM applications WHERE resume_drive_link IS NULL OR resume_drive_link = ''").fetchone()[0],
        "by_status":   dict(c.execute("SELECT status, COUNT(*) FROM applications GROUP BY status").fetchall()),
    }

    overdue = c.execute(
        f"""SELECT company, role_title, status, followup_due_date
            FROM applications
            WHERE followup_due_date IS NOT NULL AND date(followup_due_date) < {today}
            ORDER BY followup_due_date ASC LIMIT 25"""
    ).fetchall()

    due_today = c.execute(
        f"""SELECT company, role_title, status, followup_due_date
            FROM applications
            WHERE date(followup_due_date) = {today}
            ORDER BY company COLLATE NOCASE LIMIT 25"""
    ).fetchall()

    soc = c.execute(
        """SELECT company, role_title, status, applied_date
           FROM applications WHERE lower(role_title) LIKE '%soc%'
           ORDER BY applied_date DESC LIMIT 20"""
    ).fetchall()

    missing_resume = c.execute(
        """SELECT company, role_title, status
           FROM applications WHERE resume_drive_link IS NULL OR resume_drive_link = ''
           ORDER BY company COLLATE NOCASE LIMIT 20"""
    ).fetchall()

    return {
        "stats": stats,
        "followups_overdue":   overdue,
        "followups_due_today": due_today,
        "soc_roles":           soc,
        "missing_resume":      missing_resume,
    }


# ── Pattern-matched shortcuts (no LLM) ────────────────────────────────────────

def _pattern_answer(question: str, payload: dict[str, Any]) -> str | None:
    q  = question.lower()
    s  = payload["stats"]

    if any(k in q for k in ("follow-up today", "follow up today", "due today")):
        rows = payload["followups_due_today"]
        if not rows:
            return "Nothing is due for follow-up today."
        lines = [f"- **{r[0]}** — {r[1]} ({r[2]}) — due {r[3]}" for r in rows]
        return f"**{len(rows)} follow-up(s) due today:**\n" + "\n".join(lines)

    if "overdue" in q:
        rows = payload["followups_overdue"]
        if not rows:
            return "No overdue follow-ups. You're on top of it! ✅"
        lines = [f"- **{r[0]}** — {r[1]} ({r[2]}) — was due {r[3]}" for r in rows]
        return f"**{len(rows)} overdue follow-up(s):**\n" + "\n".join(lines)

    if "missing" in q and "resume" in q:
        rows = payload["missing_resume"]
        if not rows:
            return f"All {s['total']} applications have a resume linked. ✅"
        lines = [f"- **{r[0]}** — {r[1]} ({r[2]})" for r in rows]
        return f"**{len(rows)} application(s) missing a resume link:**\n" + "\n".join(lines)

    if "soc" in q and ("role" in q or "appli" in q):
        rows = payload["soc_roles"]
        if not rows:
            return "No SOC roles found in the tracker."
        lines = [f"- **{r[0]}** — {r[1]} — {r[2]} (applied {r[3]})" for r in rows]
        return "**SOC analyst applications:**\n" + "\n".join(lines)

    if any(k in q for k in ("statistic", "dashboard", "summary", "overview")):
        s_ = s
        return (
            f"**Tracker summary:**\n"
            f"- Total applications: **{s_['total']}**\n"
            f"- Cold emails: **{s_['cold_emails']}**\n"
            f"- Referrals: **{s_['referrals']}**\n"
            f"- Interviews: **{s_['interviews']}**\n"
            f"- Rejections: **{s_['rejections']}**\n"
            f"- Offers: **{s_['offers']}**\n"
            f"- Missing resume: **{s_['no_resume']}**"
        )

    if ("rate" in q or "replied" in q) and ("cold" in q or "email" in q):
        sent = s["cold_emails"] + s["referrals"]
        replied = s.get("by_status", {}).get("Recruiter Reply", 0)
        if not sent:
            return "No cold email or referral records yet. Sync Gmail or add manually."
        pct = 100.0 * replied / sent
        return (
            f"Approximate recruiter reply rate:\n"
            f"- Sent: **{sent}** (cold emails + referrals)\n"
            f"- Recruiter replies: **{replied}**\n"
            f"- Rate: **{pct:.1f}%**"
        )

    if "interview" in q and ("pipeline" in q or "all" in q or "show" in q):
        interviews = [
            (r[0], r[1], r[2], r[3]) for r in (
                # fetch inline
                []
            )
        ]
        count = s.get("by_status", {}).get("Interview", 0)
        return f"You have **{count}** application(s) at Interview status. Open the Dashboard to see details."

    return None


# ── Company-specific row lookup ────────────────────────────────────────────────

def _lookup_company(conn: sqlite3.Connection, question: str) -> str:
    m = re.search(r"for(?:\s+my)?\s+([\w&.\-\s]+?)\s+application", question.lower())
    if not m:
        return ""
    hint = m.group(1).strip()
    rows = conn.execute(
        """SELECT id, company, role_title, status, notes, gmail_thread_link, followup_due_date
           FROM applications WHERE lower(company) LIKE ?""",
        (f"%{hint}%",),
    ).fetchall()
    if not rows:
        return ""
    lines = [
        f"- #{r[0]} **{r[1]}** — {r[2]} — {r[3]} "
        f"(follow-up due: {r[6] or 'none'}) "
        f"[Gmail]({r[5]})" if r[5] else f"- #{r[0]} **{r[1]}** — {r[2]} — {r[3]}"
        for r in rows
    ]
    return "\nMatching rows:\n" + "\n".join(lines)


# ── Main entry point ───────────────────────────────────────────────────────────

def answer_question(
    conn: sqlite3.Connection,
    question: str,
    use_llm: bool = True,
    history: list[dict] | None = None,
) -> str:
    payload = _sql_summary(conn)

    # 1. Fast pattern match
    direct = _pattern_answer(question, payload)
    if direct:
        return direct

    # 2. No LLM available
    if not use_llm or not llm_service.api_key_configured():
        blob = json.dumps(payload["stats"], indent=2)
        return (
            "No built-in shortcut matched that question, and the LLM is not configured.\n\n"
            "Set `OPENAI_API_KEY` in your `.env` file for full natural-language answers.\n\n"
            f"_Available stats:_\n```json\n{blob}\n```"
        )

    # 3. LLM with full context
    extra = _lookup_company(conn, question)
    context_blob = json.dumps(payload, default=str, indent=2)[:14_000]
    user_msg = f"Question: {question}\n\nContext:\n{context_blob}{extra}"

    try:
        return llm_service.chat_with_context(
            system=llm_service.CHATBOT_SYSTEM,
            user=user_msg,
            history=history,
        )
    except Exception as exc:
        return (
            f"LLM call failed: {exc}\n\n"
            f"Stats snapshot:\n```json\n{json.dumps(payload['stats'], indent=2)}\n```"
        )
