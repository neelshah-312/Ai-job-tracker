"""
Dashboard — KPI metrics, charts, and master application table.
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

from db.database import get_connection, get_stats, init_db, iter_applications

load_dotenv(ROOT / ".env")
init_db()

st.set_page_config(page_title="Dashboard — Job Tracker AI", layout="wide")
st.title("📊 Dashboard")

conn = get_connection()
try:
    stats = get_stats(conn)
    apps  = iter_applications(conn)
finally:
    conn.close()

# ── KPI row ───────────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
c1.metric("Total",           stats["total"])
c2.metric("Cold emails",     stats["cold_emails"])
c3.metric("Referrals",       stats["referrals"])
c4.metric("Interviews",      stats["interviews"])
c5.metric("Rejections",      stats["rejections"])
c6.metric("Offers",          stats["offers"])
c7.metric("Due today",       stats["due_today"])
c8.metric("Overdue",         stats["overdue"],
          delta=f"{stats['no_resume']} no resume", delta_color="off")

st.divider()

# ── Charts ────────────────────────────────────────────────────────────────────
if stats["total"] > 0:
    try:
        import plotly.express as px

        ch1, ch2 = st.columns(2)

        with ch1:
            st.subheader("Status breakdown")
            if stats["by_status"]:
                df_s = pd.DataFrame(stats["by_status"], columns=["Status", "Count"])
                STATUS_COLORS = {
                    "Applied":                  "#3b82f6",
                    "Cold Email Sent":           "#8b5cf6",
                    "Referral Request Sent":     "#a855f7",
                    "Recruiter Reply":           "#06b6d4",
                    "Interview":                 "#10b981",
                    "Rejected":                  "#ef4444",
                    "Offer":                     "#f59e0b",
                    "Ghosted":                   "#6b7280",
                    "Needs Review":              "#f97316",
                }
                fig = px.pie(
                    df_s, values="Count", names="Status",
                    color="Status", color_discrete_map=STATUS_COLORS,
                    hole=0.4,
                )
                fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=300)
                st.plotly_chart(fig, use_container_width=True)

        with ch2:
            st.subheader("Applications over time")
            if stats["timeline"]:
                df_t = pd.DataFrame(stats["timeline"], columns=["Date", "Count"])
                df_t["Date"] = pd.to_datetime(df_t["Date"], errors="coerce")
                df_t = df_t.dropna(subset=["Date"]).sort_values("Date")
                fig2 = px.bar(
                    df_t, x="Date", y="Count",
                    labels={"Date": "Applied date", "Count": "Applications"},
                    color_discrete_sequence=["#3b82f6"],
                )
                fig2.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=300)
                st.plotly_chart(fig2, use_container_width=True)

    except ImportError:
        st.caption("Install `plotly` for charts: `pip install plotly`")

    st.divider()

# ── Master table ──────────────────────────────────────────────────────────────
st.subheader("All applications")

if not apps:
    st.info(
        "No applications yet. Go to **Gmail Sync** to import emails automatically, "
        "or **Applications** to add records manually."
    )
else:
    STATUS_EMOJI = {
        "Applied":              "🔵",
        "Cold Email Sent":      "🟣",
        "Referral Request Sent":"🟣",
        "Recruiter Reply":      "🔷",
        "Interview":            "🟢",
        "Rejected":             "🔴",
        "Offer":                "🟡",
        "Ghosted":              "⚫",
        "Needs Review":         "🟠",
    }
    today_s = date.today().isoformat()

    # ── Filter controls ──
    with st.expander("🔍 Filters", expanded=False):
        f1, f2, f3, f4 = st.columns(4)
        all_statuses = sorted({a.get("status") or "" for a in apps if a.get("status")})
        all_sources  = sorted({a.get("source_type") or "" for a in apps if a.get("source_type")})
        flt_status  = f1.multiselect("Status",  all_statuses)
        flt_source  = f2.multiselect("Source",  all_sources)
        flt_company = f3.text_input("Company contains")
        flt_role    = f4.text_input("Role contains")

    rows = []
    for a in apps:
        status = a.get("status") or ""
        due    = (a.get("followup_due_date") or "")[:10]
        overdue = bool(due and due < today_s)

        # Apply filters
        if flt_status  and status not in flt_status:                       continue
        if flt_source  and (a.get("source_type") or "") not in flt_source: continue
        if flt_company and flt_company.lower() not in (a.get("company") or "").lower(): continue
        if flt_role    and flt_role.lower()    not in (a.get("role_title") or "").lower(): continue

        rows.append({
            "Status":        f"{STATUS_EMOJI.get(status, '⚪')} {status}",
            "Company":       a.get("company") or "",
            "Role":          a.get("role_title") or "",
            "Source":        a.get("source_type") or "",
            "Applied":       (a.get("applied_date") or "")[:10],
            "Last contact":  (a.get("last_email_date") or "")[:10],
            "Follow-up due": f"{'🔴 ' if overdue else ''}{due}",
            "Resume":        a.get("resume_drive_link") or "",
            "Gmail thread":  a.get("gmail_thread_link") or "",
            "Job URL":       a.get("job_url") or "",
        })

    if not rows:
        st.warning("No applications match the current filters.")
    else:
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Resume":       st.column_config.LinkColumn("Resume",       display_text="📄 View"),
                "Gmail thread": st.column_config.LinkColumn("Gmail thread", display_text="✉ Open"),
                "Job URL":      st.column_config.LinkColumn("Job URL",      display_text="🔗 Link"),
            },
        )
        st.caption(f"Showing **{len(rows)}** of **{len(apps)}** applications.")

st.divider()
st.caption(
    "Tip: Gmail thread links open the conversation in-browser. "
    "Use **Resume Library** to bulk-link Drive PDFs."
)
