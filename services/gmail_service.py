"""
Gmail API service — OAuth 2.0 authentication, message fetching, and normalisation.

Scopes: gmail.readonly only — the app never modifies email.
"""
from __future__ import annotations

import base64
import html
import os
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterator, Optional

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False  # type: ignore

ROOT = Path(__file__).resolve().parent.parent

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# ── Pre-built search queries ───────────────────────────────────────────────────

APPLICATION_QUERY = (
    'newer_than:90d ('
    '"thank you for applying" OR "application received" OR '
    '"we received your application" OR "your application" OR '
    '"application confirmation" OR "we have received"'
    ')'
)

ATS_QUERY = (
    "newer_than:90d ("
    "from:greenhouse.io OR from:lever.co OR from:workday.com OR "
    "from:ashbyhq.com OR from:taleo.net OR from:icims.com OR "
    "from:jobvite.com OR from:smartrecruiters.com OR from:bamboohr.com"
    ")"
)

SENT_QUERY = (
    'newer_than:90d in:sent ('
    '"interested in" OR "reaching out" OR "referral" OR '
    '"cybersecurity role" OR "security analyst" OR "open to connect" OR '
    '"cold email" OR "job opportunity" OR "application" OR "resume"'
    ')'
)

RECRUITER_QUERY = (
    'newer_than:90d ('
    '"interview" OR "next steps" OR "schedule a call" OR '
    '"hiring manager" OR "pleased to inform" OR "we would like" OR '
    '"move forward" OR "offer"'
    ')'
)


# ── Credential helpers ─────────────────────────────────────────────────────────

def _credential_paths() -> tuple[Path, Path]:
    cred = Path(os.getenv("GMAIL_CREDENTIALS_PATH", str(ROOT / "Secrets" / "credentials.json")))
    tok  = Path(os.getenv("GMAIL_TOKEN_PATH",        str(ROOT / "Secrets" / "gmail_token.json")))
    return cred, tok


def _ensure_google() -> None:
    if not _GOOGLE_AVAILABLE:
        raise RuntimeError(
            "Google API libraries not installed. "
            "Run: pip install google-api-python-client google-auth-oauthlib"
        )


def get_gmail_credentials() -> Any:
    _ensure_google()
    cred_path, tok_path = _credential_paths()

    creds = None
    if tok_path.exists():
        creds = Credentials.from_authorized_user_file(tok_path.as_posix(), GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not cred_path.exists():
                raise FileNotFoundError(
                    f"OAuth client file not found: {cred_path}\n"
                    "Download it from Google Cloud Console → APIs & Services → "
                    "Credentials → OAuth 2.0 Client IDs → Download JSON.\n"
                    "Save as Secrets/credentials.json or set GMAIL_CREDENTIALS_PATH in .env."
                )
            flow = InstalledAppFlow.from_client_secrets_file(cred_path.as_posix(), GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)

        tok_path.parent.mkdir(parents=True, exist_ok=True)
        tok_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def build_gmail_service(creds=None):
    _ensure_google()
    return build("gmail", "v1", credentials=creds or get_gmail_credentials(), cache_discovery=False)


def is_authenticated() -> bool:
    """True if a valid token exists (does not refresh)."""
    _, tok_path = _credential_paths()
    if not tok_path.exists():
        return False
    try:
        creds = Credentials.from_authorized_user_file(tok_path.as_posix(), GMAIL_SCOPES)
        return creds.valid or bool(creds.expired and creds.refresh_token)
    except Exception:
        return False


# ── Message decoding ───────────────────────────────────────────────────────────

def _decode_body(payload: dict) -> str:
    """Recursively extract plain-text body from a MIME payload."""
    data = payload.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data.encode("ascii")).decode("utf-8", errors="replace")

    parts = payload.get("parts") or []
    texts: list[str] = []
    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            texts.append(_decode_body(part))
        elif mime == "text/html":
            raw = _decode_body(part)
            texts.append(html.unescape(re.sub(r"<[^>]+>", " ", raw)))
        elif "parts" in part:
            texts.append(_decode_body(part))

    return "\n".join(t for t in texts if t.strip())


def _get_header(headers: list[dict], name: str) -> Optional[str]:
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value")
    return None


def _parse_date(msg: dict) -> Optional[str]:
    headers = msg.get("payload", {}).get("headers", []) or []
    for key in ("Date", "Received"):
        val = _get_header(headers, key)
        if val:
            try:
                from datetime import timezone
                dt = parsedate_to_datetime(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    # fallback: internalDate (milliseconds epoch)
    internal = int(msg.get("internalDate", "0") or "0")
    if internal:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(internal / 1000, tz=timezone.utc).isoformat()
    return None


# ── Iteration / fetching ───────────────────────────────────────────────────────

def iter_message_ids(
    service,
    query: str,
    label_ids: Optional[list[str]] = None,
    max_results: int = 500,
) -> Iterator[str]:
    """Yield Gmail message IDs matching query, paginated."""
    page_token = None
    fetched = 0
    while True:
        kwargs: dict[str, Any] = {
            "userId": "me",
            "q": query,
            "maxResults": min(100, max_results - fetched),
        }
        if label_ids:
            kwargs["labelIds"] = label_ids
        if page_token:
            kwargs["pageToken"] = page_token

        resp = service.users().messages().list(**kwargs).execute()
        for m in resp.get("messages", []) or []:
            yield m["id"]
            fetched += 1
            if fetched >= max_results:
                return

        page_token = resp.get("nextPageToken")
        if not page_token or fetched >= max_results:
            break


def fetch_message(service, message_id: str) -> dict[str, Any]:
    return service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()


def normalize_message(msg: dict, direction: str) -> dict[str, Any]:
    """Convert a raw Gmail API message dict into a clean, flat dict."""
    headers = msg.get("payload", {}).get("headers", []) or []
    subject    = _get_header(headers, "Subject") or ""
    sender     = _get_header(headers, "From")    or ""
    to         = _get_header(headers, "To")      or ""
    cc         = _get_header(headers, "Cc")      or ""
    recipients = ", ".join(x for x in (to, cc) if x)
    body       = _decode_body(msg.get("payload", {})).strip()
    snippet    = (msg.get("snippet") or "")[:500]
    thread_id  = msg.get("threadId") or ""

    return {
        "gmail_message_id": msg["id"],
        "gmail_thread_id":  thread_id,
        "direction":        direction,
        "sender":           sender,
        "recipients":       recipients,
        "subject":          subject,
        "email_date":       _parse_date(msg),
        "snippet":          snippet,
        "body":             body[:32_000],  # cap for LLM
        "gmail_thread_link": gmail_thread_url(thread_id),
    }


def gmail_thread_url(thread_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#inbox/{thread_id}" if thread_id else ""
