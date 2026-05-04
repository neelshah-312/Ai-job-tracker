"""
Follow-up rules engine.

Calculates when to follow up based on email type and applies
US business-day (Mon–Fri) arithmetic.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

# ── Status mapping ─────────────────────────────────────────────────────────────

STATUS_FROM_EMAIL_TYPE: dict[str, str] = {
    "application_confirmation":  "Applied",
    "cold_email":                "Cold Email Sent",
    "referral_request":          "Referral Request Sent",
    "recruiter_reply":           "Recruiter Reply",
    "interview_invite":          "Interview",
    "rejection":                 "Rejected",
    "offer":                     "Offer",
    "not_job_related":           "Needs Review",
    "needs_review":              "Needs Review",
}

SOURCE_FROM_EMAIL_TYPE: dict[str, str] = {
    "application_confirmation":  "ATS",
    "cold_email":                "Cold Email",
    "referral_request":          "Referral",
    "recruiter_reply":           "Recruiter",
    "interview_invite":          "Recruiter",
    "rejection":                 "ATS",
    "offer":                     "Recruiter",
    "needs_review":              "Other",
    "not_job_related":           "Other",
}

# Business days until follow-up is due per email type
FOLLOWUP_DAYS: dict[str, int] = {
    "application_confirmation":  10,
    "cold_email":                 5,
    "referral_request":           5,
    "recruiter_reply":            4,
    "interview_invite":           1,   # thank-you within 24–48 h
}

# Status → email_type reverse mapping (for manual application entries)
_STATUS_TO_EMAIL_TYPE: dict[str, str] = {
    "applied":              "application_confirmation",
    "coldemailsent":        "cold_email",
    "referralrequestsent":  "referral_request",
    "recruiterreply":       "recruiter_reply",
    "interview":            "interview_invite",
    "rejected":             "rejection",
    "offer":                "offer",
    "ghosted":              "application_confirmation",
    "needsreview":          "needs_review",
}


# ── Date helpers ───────────────────────────────────────────────────────────────

def parse_iso_date(val: Optional[str]) -> Optional[date]:
    if not val:
        return None
    try:
        if "T" in val or " " in val:
            return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
        return date.fromisoformat(val[:10])
    except (ValueError, AttributeError):
        return None


def add_business_days(start: date, n: int) -> date:
    """Add n Mon–Fri business days to start (no holiday calendar)."""
    if n <= 0:
        return start
    d, remaining = start, n
    while remaining > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            remaining -= 1
    return d


def days_since(target: Optional[date], today: Optional[date] = None) -> Optional[int]:
    if target is None:
        return None
    return ((today or date.today()) - target).days


# ── Core logic ─────────────────────────────────────────────────────────────────

def followup_days_for(email_type: str) -> Optional[int]:
    return FOLLOWUP_DAYS.get(email_type)


def compute_followup_due_date(email_type: str, anchor: date) -> Optional[date]:
    n = followup_days_for(email_type)
    return add_business_days(anchor, n) if n is not None else None


def email_type_for_status(status: str) -> str:
    key = "".join((status or "").lower().split())
    return _STATUS_TO_EMAIL_TYPE.get(key, "application_confirmation")


def suggest_followup_action(email_type: str, status: str) -> str:
    actions = {
        "application_confirmation": "Send a concise status-check after ~10 business days.",
        "cold_email":               "Send a polite nudge referencing your prior outreach.",
        "referral_request":         "Circle back with your referrer after 5 business days.",
        "interview_invite":         "Send a thank-you email within 24–48 hours; reference specific points.",
        "recruiter_reply":          "Reply or follow up in 3–5 business days with a clear ask.",
        "rejection":                "No further follow-up unless you want to request feedback once.",
        "offer":                    "Coordinate offer details / negotiate; timeline-dependent.",
    }
    return actions.get(email_type, "Review thread and decide on next outreach step.")
