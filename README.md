# Job Tracker AI

A personal Streamlit dashboard that connects Gmail, Google Drive, an LLM, and SQLite to automate and organize your job search.

## Features

| Page | What it does |
|---|---|
| **Dashboard** | KPI metrics, status/timeline charts, filterable master table with clickable Gmail & Drive links |
| **Gmail Sync** | OAuth scan of inbox + sent mail (last 90 days); LLM classifies every email and auto-creates application records |
| **Applications** | Add / edit / delete records manually; follow-up dates auto-computed |
| **Follow-up Center** | Overdue alerts, per-row mark-done buttons, AI-drafted follow-up emails |
| **Resume Library** | Connect a Drive folder; keyword-match resumes to roles; bulk-link blank records |
| **AI Chatbot** | Natural-language Q&A over the database — works offline (pattern matching) or with full LLM |

## Quick start

### 1. Clone & install

```bash
git clone <repo>
cd job-tracker-ai
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `OPENAI_API_KEY` — your OpenAI key (`gpt-4o-mini` is the default model)
- Google credential paths (see step 3)
- `RESUME_DRIVE_FOLDER_ID` — optional, for Resume Library

### 3. Set up Google OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create or select a project
2. **APIs & Services → Library** → enable **Gmail API** and **Drive API**
3. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Desktop app**
   - Download the JSON file
4. Create a `Secrets/` folder in the project root and save the file as `Secrets/credentials.json`
5. Add `http://localhost` to the **Authorised redirect URIs** if prompted

### 4. Run

```bash
streamlit run app.py
```

### 5. First-time Gmail auth

Go to **Gmail Sync** → click **Connect / test Gmail**. A browser window opens for one-time OAuth consent. The token is saved to `Secrets/gmail_token.json` for all future runs.

### 6. Scan & extract

Click **Scan last 3 months** with **LLM extraction enabled**. Application records are created automatically from classified emails.

---

## Project structure

```
job-tracker-ai/
├── app.py                    # Home page + quick-start guide
├── requirements.txt
├── .env                      # Your secrets (gitignored)
├── .env.example              # Template
│
├── db/
│   ├── schema.sql            # SQLite schema (3 tables)
│   └── database.py           # All CRUD operations
│
├── services/
│   ├── llm_service.py        # OpenAI: email extraction, draft, chatbot
│   ├── gmail_service.py      # Gmail OAuth + message fetching
│   ├── drive_service.py      # Drive OAuth + PDF listing
│   ├── followup_service.py   # Business-day arithmetic + follow-up rules
│   ├── sync_logic.py         # Email ingestion pipeline
│   └── chatbot_service.py    # Pattern matching + LLM Q&A
│
├── pages/
│   ├── 1_Dashboard.py
│   ├── 2_Gmail_Sync.py
│   ├── 3_Applications.py
│   ├── 4_Followups.py
│   ├── 5_Resume_Library.py
│   └── 6_AI_Chatbot.py
│
├── data/
│   └── job_tracker.db        # SQLite database (gitignored)
│
└── Secrets/
    ├── credentials.json      # Google OAuth client (gitignored)
    ├── gmail_token.json      # Gmail token (gitignored)
    └── drive_token.json      # Drive token (gitignored)
```

## Database schema

Three tables: `applications`, `emails`, `followups`.

**applications** — one row per company/role combination, linked to a Gmail thread.
Key fields: `company`, `role_title`, `status`, `applied_date`, `followup_due_date`, `resume_drive_link`, `gmail_thread_link`, `ai_confidence`.

**emails** — one row per Gmail message, linked back to an application.
Key fields: `gmail_message_id` (unique), `direction` (inbound/outbound), `classification`, `extracted_json`.

**followups** — optional granular follow-up tasks per application.

## Follow-up rules

| Status | Follow-up due |
|---|---|
| Applied (application confirmation) | 10 business days |
| Cold Email Sent | 5 business days |
| Referral Request Sent | 5 business days |
| Recruiter Reply | 4 business days |
| Interview | 1 business day (thank-you within 24–48 h) |

## Resume matching keywords

| Resume file fragment | Matched roles |
|---|---|
| `soc_analyst` | SOC, security operations center |
| `grc_analyst` | GRC, governance, compliance, risk |
| `cloud_security` | cloud, AWS, Azure, GCP, DevSecOps |
| `product_security` | product security, AppSec, application security |
| `cybersecurity_analyst_general` | analyst, cybersecurity, infosec, security engineer |

## Privacy

- Gmail access is **read-only** (`gmail.readonly` scope).
- Drive access is **read-only** (`drive.readonly` scope).
- All data stays in `data/job_tracker.db` on your local machine.
- LLM calls send only the email subject, snippet, and body (up to 12 000 characters) you choose to process.
