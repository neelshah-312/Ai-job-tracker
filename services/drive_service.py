"""
Google Drive service — OAuth and resume file operations.

Re-uses the same OAuth client as Gmail but uses a separate token file
so both can be authenticated independently.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    from googleapiclient.discovery import build
    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False  # type: ignore

from services.gmail_service import _ensure_google, get_gmail_credentials  # shared auth helpers

ROOT = Path(__file__).resolve().parent.parent

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# ── Resume keyword → filename fragment mapping ─────────────────────────────────
# First matching rule wins.  Keys are checked against role_title.lower().

RESUME_RULES: list[tuple[list[str], str]] = [
    (["soc", "security operations center"],          "soc_analyst"),
    (["grc", "governance", "compliance", "risk"],    "grc_analyst"),
    (["cloud", "aws", "azure", "gcp", "devsecops"],  "cloud_security"),
    (["product security", "appsec", "application security"], "product_security"),
    (["analyst", "cybersecurity", "cyber security",
      "information security", "infosec", "security engineer"],
                                                     "cybersecurity_analyst_general"),
]


# ── Auth ───────────────────────────────────────────────────────────────────────

def _drive_token_path() -> Path:
    return Path(os.getenv("DRIVE_TOKEN_PATH", str(ROOT / "Secrets" / "drive_token.json")))


def get_drive_credentials():
    _ensure_google()
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    from services.gmail_service import _credential_paths
    cred_path, _ = _credential_paths()
    tok_path = _drive_token_path()

    creds = None
    if tok_path.exists():
        creds = Credentials.from_authorized_user_file(tok_path.as_posix(), DRIVE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not cred_path.exists():
                raise FileNotFoundError(
                    f"OAuth client file not found: {cred_path}\n"
                    "The same credentials.json used for Gmail works for Drive too."
                )
            flow = InstalledAppFlow.from_client_secrets_file(cred_path.as_posix(), DRIVE_SCOPES)
            creds = flow.run_local_server(port=0)
        tok_path.parent.mkdir(parents=True, exist_ok=True)
        tok_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def build_drive_service(creds=None):
    _ensure_google()
    return build("drive", "v3", credentials=creds or get_drive_credentials(), cache_discovery=False)


# ── File operations ────────────────────────────────────────────────────────────

def list_pdf_files_in_folder(service, folder_id: str) -> list[dict]:
    """Return list of {id, name, webViewLink} for PDFs in folder_id."""
    q = f"'{folder_id}' in parents and trashed = false and mimeType = 'application/pdf'"
    files: list[dict] = []
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                spaces="drive",
                fields="nextPageToken, files(id, name, webViewLink)",
                pageToken=page_token,
                pageSize=100,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files.extend(resp.get("files", []) or [])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def match_resume_for_role(
    role_title: Optional[str],
    name_to_link: dict[str, str],
) -> Optional[str]:
    """
    Return the webViewLink of the best-matching resume PDF.

    name_to_link: {lowercase_filename: webViewLink}
    Matching is done against substrings of the filename; first rule wins.
    """
    if not role_title or not name_to_link:
        return None

    role_lower = role_title.lower()

    for keywords, fragment in RESUME_RULES:
        if any(kw in role_lower for kw in keywords):
            for fname, link in name_to_link.items():
                if fragment in fname:
                    return link

    # Fallback: return the first PDF link if anything exists
    return next(iter(name_to_link.values()), None)
