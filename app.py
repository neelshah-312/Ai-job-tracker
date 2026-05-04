"""
Job Tracker AI — main entry point / home page.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from db.database import get_connection, get_stats, init_db

st.set_page_config(
    page_title="Job Tracker AI",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

st.title("💼 Job Tracker AI")
st.markdown(
    "**Your personal job-search command center** — Gmail scanning, AI extraction, "
    "follow-up reminders, and a chatbot, all backed by local SQLite."
)
st.divider()

conn = get_connection()
try:
    stats = get_stats(conn)
finally:
    conn.close()

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total applications", stats["total"])
c2.metric("Interviews",         stats["interviews"])
c3.metric("Offers",             stats["offers"])
c4.metric("Cold emails sent",   stats["cold_emails"])
c5.metric("Follow-ups due",     stats["due_today"],
          delta=f"{stats['overdue']} overdue", delta_color="inverse")
c6.metric("No resume linked",   stats["no_resume"])

st.divider()

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("### 📊 Dashboard")
    st.caption("KPIs, charts, and filterable master table with clickable links.")
    st.markdown("### 📧 Gmail Sync")
    st.caption("Scan 90 days of inbox + sent mail; AI auto-creates application records.")

with col2:
    st.markdown("### 📋 Applications")
    st.caption("Manually add, edit, or delete records. Follow-up dates auto-computed.")
    st.markdown("### ⏰ Follow-up Center")
    st.caption("Overdue alerts, mark-done buttons, and AI-drafted follow-up emails.")

with col3:
    st.markdown("### 📄 Resume Library")
    st.caption("Connect a Drive folder; auto-match resumes to roles by keyword.")
    st.markdown("### 🤖 AI Chatbot")
    st.caption("Ask anything about your pipeline. Works offline + LLM-enhanced.")

st.divider()

with st.expander("🚀 Quick start — first-time setup", expanded=(stats["total"] == 0)):
    st.markdown("""
**1. Add keys to `.env`**
```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
GMAIL_CREDENTIALS_PATH=Secrets/credentials.json
GMAIL_TOKEN_PATH=Secrets/gmail_token.json
RESUME_DRIVE_FOLDER_ID=<your-folder-id>
```

**2. Google OAuth** *(Gmail + Drive)*
- [Google Cloud Console](https://console.cloud.google.com/) → Enable Gmail API + Drive API
- Create OAuth 2.0 Desktop Client → Download JSON → save as `Secrets/credentials.json`

**3. Install & run**
```bash
pip install -r requirements.txt
streamlit run app.py
```

**4. Gmail Sync → "Connect / test Gmail"** — one-time browser auth. Then click **Scan last 3 months**.
""")

st.caption("All data stays local in `data/job_tracker.db`. Gmail access is read-only.")
