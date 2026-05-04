"""
Gmail Sync — authenticate with Google, scan inbox + sent mail,
run LLM extraction, and ingest results into SQLite.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from db.database import get_connection, get_email_ids_in_db, init_db
from services import gmail_service, llm_service
from services.gmail_service import APPLICATION_QUERY, ATS_QUERY, RECRUITER_QUERY, SENT_QUERY
from services.llm_service import get_active_provider, get_all_providers_status
from services.sync_logic import ingest_normalized_message

load_dotenv(ROOT / ".env")
init_db()

st.set_page_config(page_title="Gmail Sync — Job Tracker AI", layout="wide")
st.title("📧 Gmail Sync")

st.markdown(
    "Scan your Gmail inbox and sent folder for job-related emails. "
    "With **LLM extraction** enabled, each email is classified and an application "
    "record is created or updated automatically."
)

# ── Status indicators ──────────────────────────────────────────────────────────
col_status1, col_status2 = st.columns(2)
with col_status1:
    has_gmail = gmail_service.is_authenticated()
    st.markdown(
        f"Gmail: {'✅ Connected' if has_gmail else '❌ Not connected'}"
    )
with col_status2:
    has_key = llm_service.api_key_configured()
    if has_key:
        st.markdown(f"LLM: ✅ {get_active_provider()}")
    else:
        st.markdown("LLM: ❌ No provider configured")
        for p in get_all_providers_status():
            if not p["configured"]:
                st.caption(f"  Set `{p['env_var']}` for {p['provider']}")

st.divider()

# ── Controls ───────────────────────────────────────────────────────────────────
col_a, col_b = st.columns(2)
with col_a:
    use_llm = st.toggle(
        "Enable LLM extraction",
        value=has_key,
        disabled=not has_key,
        help="Classifies each email and creates application records automatically.",
    )
    if not has_key:
        st.caption("Set OPENAI_API_KEY in .env to enable extraction.")

with col_b:
    max_per_query = st.number_input(
        "Max emails per query",
        min_value=10, max_value=500, value=100, step=10,
        help="Lower = faster scan. Raise to catch older emails.",
    )

# ── Auth button ────────────────────────────────────────────────────────────────
if st.button("🔑 Connect / test Gmail", type="secondary"):
    try:
        svc = gmail_service.build_gmail_service()
        profile = svc.users().getProfile(userId="me").execute()
        st.success(f"✅ Authenticated as **{profile.get('emailAddress')}**")
        st.rerun()
    except FileNotFoundError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.exception(exc)

st.divider()


# ── Core sync helper ───────────────────────────────────────────────────────────

def run_sync(
    query: str,
    direction: str,
    label_ids: list[str] | None = None,
    max_results: int = 100,
) -> tuple[int, int, int]:
    """
    Fetch messages matching query, run LLM extraction if enabled,
    and persist results. Returns (fetched, skipped, total_ids).
    """
    conn = get_connection()
    try:
        known = get_email_ids_in_db(conn)
        svc   = gmail_service.build_gmail_service()
        mids  = list(gmail_service.iter_message_ids(svc, query, label_ids=label_ids, max_results=max_results))

        fetched = skipped = failed = 0
        total   = max(len(mids), 1)
        prog    = st.progress(0.0, text=f"Found {len(mids)} message IDs…")

        for i, mid in enumerate(mids):
            frac = min((i + 1) / total, 1.0)

            if mid in known:
                skipped += 1
                prog.progress(frac)
                continue

            try:
                raw  = gmail_service.fetch_message(svc, mid)
                norm = gmail_service.normalize_message(raw, direction)
            except Exception as exc:
                failed += 1
                st.warning(f"Fetch error ({mid}): {exc}")
                prog.progress(frac)
                continue

            subj = (norm.get("subject") or "(no subject)")[:70]
            prog.progress(frac, text=f"[{i+1}/{len(mids)}] {subj}")

            extracted = None
            if use_llm:
                try:
                    extracted = llm_service.extract_email_struct(
                        subject   = norm.get("subject") or "",
                        body      = norm.get("body")    or "",
                        direction = direction,
                        snippet   = norm.get("snippet") or "",
                    )
                except Exception as exc:
                    extracted = {
                        "email_type":     "needs_review",
                        "is_job_related": False,
                        "confidence":     0.0,
                        "reason":         str(exc),
                    }

            try:
                ingest_normalized_message(conn, normalized=norm, extracted=extracted)
                conn.commit()
                known.add(mid)
                fetched += 1
            except Exception as exc:
                failed += 1
                st.error(f"DB error for '{subj}': {exc}")

            prog.progress(frac)

        prog.progress(1.0, text="✅ Done")
        if failed:
            st.warning(f"{failed} message(s) could not be processed.")
        return fetched, skipped, len(mids)

    finally:
        conn.close()


# ── Scan buttons ───────────────────────────────────────────────────────────────
st.subheader("Scans")

b1, b2, b3, b4 = st.columns(4)
run_full     = b1.button("📥 Scan last 3 months\n(confirmations + ATS)",  type="primary",    use_container_width=True)
run_new      = b2.button("🔄 Scan new emails\n(skip known IDs)",          use_container_width=True)
run_sent     = b3.button("📤 Scan sent outreach\n(cold emails + referrals)", use_container_width=True)
run_recruiter= b4.button("📨 Scan recruiter\nreplies",                    use_container_width=True)

if run_full:
    if not gmail_service.is_authenticated() and not has_gmail:
        st.warning("Connect Gmail first using the button above.")
    else:
        try:
            totals = [0, 0, 0]
            with st.spinner("Scanning application confirmations…"):
                a, s, t = run_sync(APPLICATION_QUERY, "inbound", max_results=int(max_per_query))
                totals[0] += a; totals[1] += s; totals[2] += t
            with st.spinner("Scanning ATS domains…"):
                a, s, t = run_sync(ATS_QUERY, "inbound", max_results=int(max_per_query))
                totals[0] += a; totals[1] += s; totals[2] += t
            st.success(
                f"✅ Imported **{totals[0]}** new · skipped **{totals[1]}** duplicates · "
                f"**{totals[2]}** total IDs scanned."
            )
        except FileNotFoundError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.exception(exc)

if run_new:
    try:
        totals = [0, 0, 0]
        for label, q in [("confirmations", APPLICATION_QUERY), ("ATS", ATS_QUERY)]:
            with st.spinner(f"Scanning {label}…"):
                a, s, t = run_sync(q, "inbound", max_results=int(max_per_query))
                totals[0] += a; totals[1] += s; totals[2] += t
        st.success(
            f"✅ New: **{totals[0]}** · skipped: **{totals[1]}** · scanned: **{totals[2]}**."
        )
    except FileNotFoundError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.exception(exc)

if run_sent:
    try:
        with st.spinner("Scanning Sent folder…"):
            nf, ns, nt = run_sync(SENT_QUERY, "outbound", label_ids=["SENT"], max_results=int(max_per_query))
        st.success(f"✅ Imported **{nf}** · skipped **{ns}** · scanned **{nt}**.")
    except FileNotFoundError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.exception(exc)

if run_recruiter:
    try:
        with st.spinner("Scanning for recruiter replies…"):
            nf, ns, nt = run_sync(RECRUITER_QUERY, "inbound", max_results=int(max_per_query))
        st.success(f"✅ Imported **{nf}** · skipped **{ns}** · scanned **{nt}**.")
    except FileNotFoundError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.exception(exc)

st.divider()

# ── Needs-review queue ─────────────────────────────────────────────────────────
with st.expander("🔍 Review uncertain / needs-review emails"):
    if st.button("Load uncertain emails"):
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT e.email_date, e.classification, e.sender, e.subject, e.snippet,
                       a.gmail_thread_link
                FROM emails e
                LEFT JOIN applications a ON e.application_id = a.id
                WHERE e.classification IN ('needs_review','not_job_related') OR e.classification IS NULL
                ORDER BY e.email_date DESC LIMIT 200
                """
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            st.info("No uncertain emails — all messages were confidently classified.")
        else:
            st.markdown(f"**{len(rows)} uncertain email(s):**")
            for date_s, cls, sender, subject, snippet, link in rows:
                with st.expander(f"[{cls}] {subject or '(no subject)'} — {(date_s or '')[:10]}"):
                    st.markdown(f"**From:** {sender}")
                    st.markdown(f"**Snippet:** {snippet}")
                    if link:
                        st.markdown(f"[Open in Gmail ↗]({link})")

st.divider()
st.markdown(
    "**Setup note:** Save your OAuth 2.0 client JSON from Google Cloud Console as "
    "`Secrets/credentials.json`, or set `GMAIL_CREDENTIALS_PATH` in `.env`. "
    "Enable both the **Gmail API** and **Drive API** in the same Google Cloud project."
)
