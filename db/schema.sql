-- Job Application + Cold Email Tracker — SQLite schema

CREATE TABLE IF NOT EXISTS applications (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    company           TEXT,
    role_title        TEXT,
    job_location      TEXT,
    job_url           TEXT,
    source_type       TEXT,          -- Direct | ATS | Cold Email | Referral | LinkedIn | Recruiter | Other
    status            TEXT,          -- Applied | Cold Email Sent | Referral Request Sent | Recruiter Reply | Interview | Rejected | Offer | Ghosted | Needs Review
    applied_date      TEXT,          -- YYYY-MM-DD
    last_email_date   TEXT,          -- ISO datetime
    followup_due_date TEXT,          -- YYYY-MM-DD (computed from status + applied_date)
    followup_status   TEXT,          -- open | done | none
    contact_name      TEXT,
    contact_email     TEXT,
    resume_drive_link TEXT,          -- Google Drive webViewLink
    gmail_thread_id   TEXT,
    gmail_thread_link TEXT,          -- https://mail.google.com/...
    ai_confidence     REAL,          -- 0.0–1.0 from LLM extraction
    notes             TEXT,
    created_at        TEXT,          -- UTC ISO
    updated_at        TEXT           -- UTC ISO
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_app_thread
    ON applications(gmail_thread_id)
    WHERE gmail_thread_id IS NOT NULL AND gmail_thread_id != '';

CREATE INDEX IF NOT EXISTS idx_app_company   ON applications(company);
CREATE INDEX IF NOT EXISTS idx_app_status    ON applications(status);
CREATE INDEX IF NOT EXISTS idx_app_followup  ON applications(followup_due_date);
CREATE INDEX IF NOT EXISTS idx_app_created   ON applications(created_at);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS emails (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id  TEXT UNIQUE,
    gmail_thread_id   TEXT,
    direction         TEXT,          -- inbound | outbound
    sender            TEXT,
    recipients        TEXT,
    subject           TEXT,
    email_date        TEXT,          -- ISO datetime
    snippet           TEXT,
    classification    TEXT,          -- application_confirmation | cold_email | … | not_job_related | needs_review
    company           TEXT,
    role_title        TEXT,
    extracted_json    TEXT,          -- JSON blob from LLM
    application_id    INTEGER,
    FOREIGN KEY(application_id) REFERENCES applications(id)
);

CREATE INDEX IF NOT EXISTS idx_email_thread ON emails(gmail_thread_id);
CREATE INDEX IF NOT EXISTS idx_email_app    ON emails(application_id);
CREATE INDEX IF NOT EXISTS idx_email_class  ON emails(classification);

-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS followups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  INTEGER,
    followup_type   TEXT,           -- same as email_type
    due_date        TEXT,           -- YYYY-MM-DD
    status          TEXT,           -- open | done
    draft_text      TEXT,
    created_at      TEXT,
    completed_at    TEXT,
    FOREIGN KEY(application_id) REFERENCES applications(id)
);

CREATE INDEX IF NOT EXISTS idx_followup_due ON followups(due_date);
CREATE INDEX IF NOT EXISTS idx_followup_app ON followups(application_id);
