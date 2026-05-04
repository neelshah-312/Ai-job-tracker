"""
AI Chatbot — natural-language Q&A over the job tracker database.

Works offline with pattern matching; full LLM answers with OPENAI_API_KEY.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from db.database import get_connection, init_db
from services.chatbot_service import answer_question
from services.llm_service import api_key_configured, get_all_providers_status, get_active_provider

load_dotenv(ROOT / ".env")
init_db()

st.set_page_config(page_title="AI Chatbot — Job Tracker AI", layout="wide")
st.title("🤖 AI Chatbot")

has_llm = api_key_configured()

# ── Provider status panel ──────────────────────────────────────────────────────
with st.expander("🔌 LLM provider status", expanded=not has_llm):
    providers = get_all_providers_status()
    for p in providers:
        icon = "✅" if p["configured"] else "❌"
        st.markdown(
            f"{icon} **{p['provider']}** — "
            f"{'model: `' + p['model'] + '`' if p['configured'] else f'set `{p[\"env_var\"]}` in .env'}"
        )
    if has_llm:
        st.caption(f"Active provider: **{get_active_provider()}** (falls back automatically on quota errors)")
    else:
        st.warning("No LLM provider configured. Set at least one API key in `.env`.")

st.markdown(
    "Ask anything about your job pipeline. "
    "**Heuristic answers work offline.** "
    f"{'Full LLM answers active — auto-fallback across providers.' if has_llm else '⚠️ Configure an API key above for full answers.'}"
)

# ── Sample questions ────────────────────────────────────────────────────────────
SAMPLES = [
    "What should I follow up on today?",
    "Which follow-ups are overdue?",
    "Show all SOC analyst roles I applied to.",
    "Which applications are missing a resume link?",
    "What is my recruiter reply rate from cold emails?",
    "Show my dashboard statistics.",
    "Which companies have not replied?",
    "Show my interview pipeline.",
]

with st.expander("💡 Sample questions (click to send)", expanded=False):
    cols = st.columns(2)
    for i, q in enumerate(SAMPLES):
        if cols[i % 2].button(q, key=f"sample_{i}", use_container_width=True):
            if "messages" not in st.session_state:
                st.session_state.messages = []
            st.session_state.messages.append({"role": "user", "content": q})
            st.rerun()

st.divider()

# ── Chat history ────────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "👋 I'm your job-search copilot, backed by your local tracker database.\n\n"
                "I can answer questions about applications, follow-ups, response rates, "
                "and can draft follow-up emails.\n\n"
                "**Try:** *What should I follow up on today?*"
            ),
        }
    ]

# Render history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Input ───────────────────────────────────────────────────────────────────────
conn = get_connection()
try:
    if prompt := st.chat_input("Ask the tracker…"):
        # Show user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Build conversation history for multi-turn context
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state.messages[:-1]
            if m["role"] in ("user", "assistant")
        ]

        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    reply = answer_question(
                        conn,
                        question = prompt,
                        use_llm  = has_llm,
                        history  = history[-8:],  # last 4 turns
                    )
                except Exception as exc:
                    reply = f"⚠️ Error: {exc}"
            st.markdown(reply)

        st.session_state.messages.append({"role": "assistant", "content": reply})
finally:
    conn.close()

# ── Controls ────────────────────────────────────────────────────────────────────
if len(st.session_state.messages) > 1:
    if st.button("🗑️ Clear conversation", type="secondary"):
        st.session_state.messages = []
        st.rerun()
