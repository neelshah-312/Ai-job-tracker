"""
Resume Library — connect a Google Drive folder, auto-match resumes to roles,
and bulk-link blank records.
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

from db import database as db
from services import drive_service

load_dotenv(ROOT / ".env")
db.init_db()

st.set_page_config(page_title="Resume Library — Job Tracker AI", layout="wide")
st.title("📄 Resume Library")

st.markdown(
    "Connect your **Google Drive folder** of PDF resumes. "
    "The matcher maps role keywords → the best-fit resume and can bulk-link blank records.\n\n"
    "**Recommended file naming:**\n"
    "```\n"
    "Resume_SOC_Analyst.pdf\n"
    "Resume_GRC_Analyst.pdf\n"
    "Resume_Cloud_Security.pdf\n"
    "Resume_Product_Security.pdf\n"
    "Resume_Cybersecurity_Analyst_General.pdf\n"
    "```\n"
    "Any file whose lowercase name contains the fragment will match."
)

st.divider()

# ── Folder input ───────────────────────────────────────────────────────────────
env_folder = os.getenv("RESUME_DRIVE_FOLDER_ID", "")
folder = st.text_input(
    "Google Drive folder ID",
    value=st.session_state.get("drive_folder", env_folder),
    placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
    help="Found in the Drive URL: drive.google.com/drive/folders/**<FOLDER_ID>**",
)
if folder:
    st.session_state["drive_folder"] = folder

col_auth, col_list = st.columns(2)

with col_auth:
    if st.button("🔑 Connect Drive", type="secondary"):
        try:
            svc = drive_service.build_drive_service()
            # Quick auth check
            svc.files().list(pageSize=1, fields="files(id)").execute()
            st.success("✅ Drive connected.")
        except Exception as exc:
            st.error(str(exc))

with col_list:
    if st.button("📂 List resumes in folder", type="primary", disabled=not folder.strip()):
        try:
            svc   = drive_service.build_drive_service()
            files = drive_service.list_pdf_files_in_folder(svc, folder.strip())
            st.session_state["drive_files"] = files
            if not files:
                st.warning(
                    "No PDF files found. Check the folder ID and that the folder "
                    "is shared with your OAuth account."
                )
            else:
                st.success(f"✅ Found **{len(files)}** PDF file(s).")
        except Exception as exc:
            st.error(str(exc))

# ── File listing ───────────────────────────────────────────────────────────────
files = st.session_state.get("drive_files", [])

if files:
    st.subheader("Files in folder")
    for f in files:
        name = f.get("name") or "unnamed"
        link = f.get("webViewLink") or ""
        st.markdown(f"- [{name}]({link})" if link else f"- {name}")

    name_to_link: dict[str, str] = {
        f["name"].lower(): (f.get("webViewLink") or "")
        for f in files
    }

    st.divider()

    # ── Auto-link section ──────────────────────────────────────────────────────
    st.subheader("Auto-link resumes to applications")
    st.caption(
        "Preview shows the best resume match per role. "
        "'Apply' only fills blank `resume_drive_link` fields."
    )

    if st.button("🔍 Preview matches"):
        conn = db.get_connection()
        try:
            apps = conn.execute(
                "SELECT id, company, role_title, resume_drive_link FROM applications ORDER BY company"
            ).fetchall()
        finally:
            conn.close()

        preview = [
            {
                "id":        a[0],
                "company":   a[1] or "?",
                "role":      a[2] or "?",
                "current":   a[3] or "",
                "suggested": drive_service.match_resume_for_role(a[2], name_to_link) or "",
            }
            for a in apps
        ]
        st.session_state["resume_preview"] = preview

    preview = st.session_state.get("resume_preview")
    if preview:
        matched   = [r for r in preview if r["suggested"]]
        unmatched = [r for r in preview if not r["suggested"]]
        to_link   = [r for r in matched if not r["current"]]

        st.markdown(
            f"**{len(matched)}** matched · **{len(to_link)}** would be newly linked · "
            f"**{len(unmatched)}** unmatched"
        )

        ICONS = {
            (True,  False): "✅",  # matched, no current → will link
            (True,  True):  "🔄",  # matched, already has one → show suggestion
            (False, False): "❌",  # no match
            (False, True):  "🔒",  # no match but has existing link
        }
        for r in preview:
            has_match   = bool(r["suggested"])
            has_current = bool(r["current"])
            icon = ICONS.get((has_match, has_current), "❓")
            st.markdown(
                f"{icon} **#{r['id']} {r['company']}** · {r['role']}  \n"
                f"&nbsp;&nbsp;Current: `{r['current'] or 'none'}` → "
                f"Suggested: `{r['suggested'] or 'no match'}`"
            )

        if to_link:
            if st.button(
                f"🔗 Apply suggestions ({len(to_link)} blank record(s))",
                type="primary",
            ):
                conn = db.get_connection()
                try:
                    updated = 0
                    for r in to_link:
                        db.update_application(
                            conn, int(r["id"]),
                            {"resume_drive_link": r["suggested"]},
                        )
                        updated += 1
                    conn.commit()
                finally:
                    conn.close()
                st.success(f"✅ Linked **{updated}** records.")
                del st.session_state["resume_preview"]
                st.rerun()
        else:
            st.info(
                "All matched roles already have a resume link. "
                "Use **Applications** to override individual records."
            )

st.divider()
st.caption(
    "Manual overrides: paste any HTTPS Google Drive link into **Applications → Resume link**. "
    "Set `RESUME_DRIVE_FOLDER_ID` in `.env` to pre-fill the folder ID on every page load."
)
