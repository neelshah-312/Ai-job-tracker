"""
LLM service — multi-provider with automatic fallback.

Provider priority (first configured wins; falls back on quota/auth errors):
  1. OpenAI   (OPENAI_API_KEY)
  2. Groq     (GROQ_API_KEY)    — OpenAI-compatible, very fast free tier
  3. Gemini   (GEMINI_API_KEY)  — OpenAI-compatible endpoint

Set LLM_PROVIDER=openai|groq|gemini to pin a specific provider (no fallback).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

try:
    from openai import OpenAI, RateLimitError, AuthenticationError
except ImportError:
    OpenAI = None  # type: ignore
    RateLimitError = Exception  # type: ignore
    AuthenticationError = Exception  # type: ignore

# ── Prompts ────────────────────────────────────────────────────────────────────

EXTRACTION_SYSTEM = """You classify and extract structured job-search data from email text.
Return ONLY valid JSON matching this shape exactly (no markdown fences, no extra keys):

{
  "is_job_related": true,
  "email_type": "application_confirmation",
  "company": "Acme Corp",
  "role_title": "SOC Analyst Intern",
  "status": "Applied",
  "contact_name": null,
  "contact_email": "recruiting@acme.com",
  "applied_date": "2026-05-01",
  "last_interaction_date": "2026-05-01",
  "followup_needed": true,
  "confidence": 0.91,
  "reason": "Email confirms receipt of job application."
}

email_type must be one of:
  application_confirmation | cold_email | referral_request | recruiter_reply
  interview_invite | rejection | offer | not_job_related | needs_review

status must be one of:
  Applied | Cold Email Sent | Referral Request Sent | Recruiter Reply
  Interview | Rejected | Offer | Ghosted | Needs Review

Rules:
- Dates: ISO YYYY-MM-DD when known, otherwise null.
- For outbound (sent by user): email_type is cold_email or referral_request.
- For inbound confirmations: application_confirmation.
- If truly ambiguous, use needs_review with lower confidence.
- If not job-related at all, is_job_related: false, email_type: not_job_related.
"""

CHATBOT_SYSTEM = """You are a job-search copilot with access ONLY to JSON data derived from a SQLite tracker.
Answer clearly and concisely. Use bullet lists when enumerating items.
Quote exact company names, statuses, and dates from the data.
If data is missing, tell the user what to sync next (Gmail, Drive).
Never make up companies or dates not in the provided context.
"""

# ── Provider registry ──────────────────────────────────────────────────────────

_PROVIDER_CONFIGS: dict[str, dict] = {
    "openai": {
        "env_key":   "OPENAI_API_KEY",
        "base_url":  None,  # use default
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-4o-mini",
        "label":     "OpenAI",
        "json_mode": True,
    },
    "groq": {
        "env_key":   "GROQ_API_KEY",
        "base_url":  "https://api.groq.com/openai/v1",
        "model_env": "GROQ_MODEL",
        "default_model": "llama-3.3-70b-versatile",
        "label":     "Groq",
        "json_mode": True,
    },
    "gemini": {
        "env_key":   "GEMINI_API_KEY",
        "base_url":  "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-2.0-flash",
        "label":     "Gemini",
        "json_mode": False,  # skip response_format for Gemini compatibility
    },
}

# Default fallback order
_DEFAULT_ORDER = ["openai", "groq", "gemini"]


def _get_ordered_providers() -> list[dict]:
    """Return configured providers in priority order."""
    pinned = os.getenv("LLM_PROVIDER", "").strip().lower()

    if pinned and pinned in _PROVIDER_CONFIGS:
        # Pinned: use only that provider, no fallback
        cfg = _PROVIDER_CONFIGS[pinned]
        key = os.getenv(cfg["env_key"])
        if not key:
            raise RuntimeError(
                f"LLM_PROVIDER is set to '{pinned}' but {cfg['env_key']} is not configured."
            )
        return [{**cfg, "api_key": key, "model": os.getenv(cfg["model_env"], cfg["default_model"])}]

    # Auto-detect: all configured providers in default order
    result = []
    for name in _DEFAULT_ORDER:
        cfg = _PROVIDER_CONFIGS[name]
        key = os.getenv(cfg["env_key"])
        if key:
            result.append({
                **cfg,
                "provider_id": name,
                "api_key":     key,
                "model":       os.getenv(cfg["model_env"], cfg["default_model"]),
            })
    return result


def _is_quota_error(exc: Exception) -> bool:
    """Return True if the exception indicates quota/auth exhaustion → try next provider."""
    msg = str(exc).lower()
    return any(k in msg for k in (
        "quota", "rate_limit", "rate limit", "ratelimit",
        "429", "401", "insufficient_quota", "exceeded",
        "invalid_api_key", "authentication",
    ))


def _make_client(provider: dict) -> "OpenAI":
    if OpenAI is None:
        raise RuntimeError("openai package not installed. Run: pip install openai")
    kwargs: dict[str, Any] = {"api_key": provider["api_key"]}
    if provider.get("base_url"):
        kwargs["base_url"] = provider["base_url"]
    return OpenAI(**kwargs)


# ── Core call with fallback ────────────────────────────────────────────────────

def _call(
    messages: list[dict],
    *,
    json_mode: bool = False,
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> tuple[str, str]:
    """
    Call LLM with automatic provider fallback.
    Returns (response_text, provider_label_used).
    Raises RuntimeError if all providers fail.
    """
    providers = _get_ordered_providers()
    if not providers:
        raise RuntimeError(
            "No LLM provider configured. Set at least one of: "
            "OPENAI_API_KEY, GROQ_API_KEY, or GEMINI_API_KEY in your .env file."
        )

    last_exc: Optional[Exception] = None

    for p in providers:
        try:
            client = _make_client(p)
            kwargs: dict[str, Any] = {
                "model":       p["model"],
                "temperature": temperature,
                "max_tokens":  max_tokens,
                "messages":    messages,
            }
            # Only add response_format if provider supports it AND caller wants JSON
            if json_mode and p.get("json_mode", True):
                kwargs["response_format"] = {"type": "json_object"}

            resp  = client.chat.completions.create(**kwargs, timeout=30)
            text  = resp.choices[0].message.content or ""
            return text, p["label"]

        except Exception as exc:
            if _is_quota_error(exc):
                last_exc = exc
                continue   # try next provider
            raise          # hard error — don't swallow

    raise RuntimeError(
        f"All LLM providers exhausted. Last error: {last_exc}\n"
        "Check your API keys and quotas."
    )


# ── JSON parser ────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        text = m.group(0)
    return json.loads(text)


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_email_struct(
    *,
    subject:   str,
    body:      str,
    direction: str,
    snippet:   str = "",
) -> dict[str, Any]:
    """Classify a single email and extract job-application metadata."""
    msgs = [
        {"role": "system", "content": EXTRACTION_SYSTEM},
        {"role": "user",   "content": (
            f"direction: {direction}\nsubject: {subject}\n"
            f"snippet: {snippet}\nbody:\n{body[:12_000]}"
        )},
    ]
    text, _ = _call(msgs, json_mode=True, temperature=0.1, max_tokens=512)
    try:
        return _parse_json(text)
    except json.JSONDecodeError:
        return {
            "is_job_related": False,
            "email_type":     "needs_review",
            "confidence":     0.0,
            "reason":         f"Non-JSON response: {text[:200]}",
        }


def draft_followup_email(
    *,
    company:       str,
    role_title:    str,
    status:        str,
    prior_context: str,
    tone:          str = "concise, professional, warm",
) -> str:
    """Generate a ready-to-send follow-up email."""
    msgs = [
        {
            "role": "system",
            "content": "You help job seekers write excellent, specific follow-up emails.",
        },
        {
            "role": "user",
            "content": (
                f"Draft a follow-up email. Tone: {tone}.\n"
                f"Company: {company}\nRole: {role_title}\nPipeline status: {status}\n"
                f"Context:\n{prior_context[:6_000]}\n\n"
                "Format:\nSubject: <subject>\n\n<body under 180 words>"
            ),
        },
    ]
    text, _ = _call(msgs, temperature=0.5, max_tokens=400)
    return text.strip()


def chat_with_context(
    system:  str,
    user:    str,
    history: Optional[list[dict]] = None,
) -> str:
    """Generic chat completion with optional conversation history."""
    msgs: list[dict] = [{"role": "system", "content": system}]
    if history:
        msgs.extend(history[-8:])
    msgs.append({"role": "user", "content": user})
    text, _ = _call(msgs, temperature=0.3, max_tokens=1500)
    return text.strip()


def get_active_provider() -> str:
    """Return a human-readable label of the first available provider."""
    try:
        providers = _get_ordered_providers()
        if not providers:
            return "None configured"
        return providers[0]["label"] + f" ({providers[0]['model']})"
    except Exception as exc:
        return f"Error: {exc}"


def get_all_providers_status() -> list[dict]:
    """Return status of all providers — useful for UI display."""
    results = []
    for name in _DEFAULT_ORDER:
        cfg = _PROVIDER_CONFIGS[name]
        key = os.getenv(cfg["env_key"])
        results.append({
            "provider": cfg["label"],
            "configured": bool(key),
            "model": os.getenv(cfg["model_env"], cfg["default_model"]) if key else "—",
            "env_var": cfg["env_key"],
        })
    return results


def api_key_configured() -> bool:
    """Return True if at least one provider has a key set."""
    return any(os.getenv(_PROVIDER_CONFIGS[p]["env_key"]) for p in _DEFAULT_ORDER)
