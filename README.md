# AICTE NEXUS
**Unified Institutional Complaint Intelligence & Tracking Platform** · SIH 2026 · Smart Automation

> *One Institution. Multiple Bureaus. One Unified View.*
>
> **Prototype Demonstration — Synthetic Data.** Every institution, complaint, officer and approval
> reference is fictional. No AICTE system or real database is accessed.

## Problem statement
*Integrated Dashboard for Monitoring and Tracking Institution-Related Complaint Cases Across AICTE Bureaus/Cells.*
Complaints about one institution reach different bureaus (Approval, Grievance, Regulation, Finance, Examination/Quality,
Legal). Each bureau sees only its own file, so related issues stay invisible and overdue cases are hard to spot.

## Proposed solution
One dashboard where authorised officials can monitor and update complaints across bureaus, see everything about an
institution in one place, get explainable suggestions about cases that may be related, and see every change recorded.

## What's new in this version (upgrade checklist 1–13)
| # | Item | Where |
|---|---|---|
| 1 | Blue & White UI: deep-blue sidebar, bright-blue selected item, white cards, light-blue borders, filled KPI boxes, soft shadows | `ui.py` (CSS) |
| 2 | Light / Dark toggle (sidebar and login page); cards, tables, charts, forms, tabs and dropdowns follow it; remembered per user | `ui.py` |
| 3 | Premium intro (glowing logo, title reveal, loading bar), post-login "Welcome" transition, page fade-ins | `ui.py` |
| 4 | Login, registration, email-verification code, scrypt password hashing, lockout, forced password change, server-side sessions with idle + absolute timeout | `accounts.py`, `auth.py` |
| 5 | Roles: **Admin**, **Senior Officer**, **Bureau Officer** (bureau-scoped). Enforced in the data layer, not just the UI | `database.py` (`PERMISSIONS`) |
| 6 | Unique complaint IDs, tracking page with progress stepper, officer assignment, resolution, **reopen requests** with approval | `pages/2_…` |
| 7 | SQLite in WAL mode, schema migration for old databases, online backups, Docker + persistent volume | `database.py`, `Dockerfile`, `DEPLOY.md` |
| 8 | Same-institution cross-bureau matching + "similar cases" lookup anywhere, similarity score, **human verification** by Senior/Admin | `intelligence.py` |
| 9 | Overdue, Critical/High, **due-soon** deadline alerts (strip on pages, sidebar counts, login toast) | `intelligence.py` |
| 10 | Analytics with all filters, trend charts, CSV exports **and PDF summary report** | `pages/5_…`, `reports.py` |
| 11 | Audit trail: every user action, login/logout, exports, status history; **SHA-256 hash chain** with an integrity check | `database.py` |
| 12 | NEXUS AI: complaint summaries, relevant similar cases, **privacy mode** (local by default; redaction before any external call) | `pages/8_…` |
| 13 | 200+ automated checks, error-safe forms, responsive CSS, synthetic demo data with demo accounts, `DEMO_SCRIPT.md` | `tests/` |

## Roles
| Action | Admin | Senior Officer | Bureau Officer |
|---|---|---|---|
| See complaints | all | all | own bureau only |
| Register / update status / notes | ✅ | ✅ | own bureau (up to *Resolved*) |
| Close, reassign, change priority/due date | ✅ | ✅ | — |
| Request reopen | ✅ | ✅ | ✅ |
| Approve/reject reopen (not your own) | ✅ | ✅ | — |
| Verify cross-bureau suggestions | ✅ | ✅ | view only |
| Add/edit institutions | ✅ | ✅ | — |
| Settings, backups, demo reset, user management | ✅ | — | — |

## Demo accounts (when `NEXUS_DEMO_MODE=1`, the default)
All use password `Nexus@2026`: `admin`, `senior.anita`, `approval.rohit`, `grievance.priya`, `regulation.imran`, `finance.suresh`, `quality.kavita`, `legal.manoj`.
In demo mode the email-verification code is shown on screen; set `NEXUS_SMTP_*` to email it. Full list of settings: `.env.example`.

## Modules
| Module | What it does |
|---|---|
| Command Center | Alert strip, hero summary, 6 KPIs, status / priority / resolution / bureau / trend charts, critical, overdue, recent and activity lists. |
| Institution Directory | Search, details with full complaint history, add / edit (Senior+), CSV export. |
| Complaint Management | Register with filters, details, timeline, notes, status, officer/priority/due date, resolution notes, references, **Reopen**, **Similar cases**, **Track a complaint**, **Reopen requests queue**. |
| Cross-Bureau Intelligence | Explainable pair suggestions with reasons and score; Senior/Admin verify (Related / Dismissed). Nothing is merged or closed automatically. |
| Risk Monitoring | Overdue / due-soon / inactive / Critical / reassigned / awaiting-information flags with recommended next actions. |
| Analytics & Reports | Charts, KPIs, 5 CSV exports and a PDF summary honouring the filters. |
| Audit Trail | Append-only, hash-chained log; integrity check; CSV export (exports are themselves logged). |
| Settings (Admin) | Thresholds, backups, demo-data reset, production checklist. |
| User Management (Admin) | Create users, change role/bureau, deactivate, unlock, issue temporary passwords. |
| My Account | Profile, what your role may do, change password. |
| NEXUS AI Assistant | Database-grounded answers, complaint summaries with similar cases, optional redacted Groq phrasing (opt-in). |

## Architecture
```
app.py                 entry point: theme, intro, login gate, role-based st.navigation
accounts.py            users, scrypt hashing, verification codes, sessions (no Streamlit)
auth.py                login/registration screens, page guard, sidebar account
reports.py             PDF report builder (ReportLab)
ui.py                  CSS theme, badges, KPI cards, tables, filter bar
database.py            SQLite schema, seeding, validated writes, audit logging, queries
intelligence.py        TF-IDF matching (stdlib), risk rules
pages/0..8_*.py        one file per page, including NEXUS AI Assistant
tests/                 backend tests + Streamlit-stub UI smoke test
.streamlit/config.toml dark theme
```
Stack: Python 3.10+, Streamlit, Pandas, Plotly, SQLite, CSS/HTML. Matching uses only the standard library.
Navigation uses `st.navigation` so pages get clean titles (the Overview lives in `pages/0_Overview.py`).

## Database structure (SQLite, `data/nexus.db`, created on first run)
`institutions` · `complaints` · `complaint_notes` · `complaint_relationships` (unique ordered pair, review status) ·
`users` · `sessions` · `reopen_requests` · `audit_logs` (append-only via triggers, hash-chained) · `application_settings`. Primary and foreign keys, CHECK constraints, unique
constraints and indexes are defined in `database.py`; all SQL is parameterised.

## How cross-bureau matching works
A pair is a candidate only if both complaints belong to the **same institution**, sit in **different bureaus**, and
share at least one meaningful keyword. Heuristic score (0–1):

`0.55 × text similarity (TF-IDF cosine, title counted double, saturating at cosine 0.5)`
`+ 0.20 × keyword overlap + 0.15 × date proximity (90-day window) + 0.10 × same category`

Labels: **High** ≥ 0.65, **Medium** ≥ 0.45, **Low** ≥ 0.30 (editable demo thresholds, set by eye on the synthetic data).
Each suggestion lists its reasons (same institution, bureaus, cosine, shared keywords, category, date gap).
Scores are **not probabilities** and the method is **not validated**. Reviewed decisions survive re-runs; no complaint
is ever merged, closed or edited by the matcher.

## NEXUS AI Assistant
The assistant uses reviewed Python intent handlers against the local database; it does not execute arbitrary user SQL or mutate complaint records. Supported intents include complaint summary/status counts, overdue complaints, Critical/High cases, bureau workload, institution complaint volume, resolution performance and configured risk flags. It displays supporting result rows and allows CSV download.

Optional LLM phrasing can be enabled by setting `GROQ_API_KEY` in the environment. Optionally set `GROQ_MODEL` (defaults to `llama-3.3-70b-versatile`). In this mode, a verified answer and compact result preview are sent to Groq for phrasing; no database credentials or direct database access are shared. Do not use real sensitive data in this demo. Without the key, the assistant works in offline-safe mode.

## Install and run
```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```
The database is created and seeded automatically (30 institutions and 76 synthetic complaints across several states, bureaus, statuses and priorities)
on first start. Set `NEXUS_DB_PATH` to use a different database file.

## Reset the demo data
Settings → **Demo data** → tick the acknowledgement, type `RESET`, click **Reset demo data**. This deletes everything,
including user-created records and audit history, and re-seeds. Normal startup never deletes data.

## Hackathon demo workflow (all in the UI)
1. Institution Directory → search `Satpura`, `Utkal` or `Narmada` (institutions with several bureaus).
2. Institution details → full complaint history, bureau and status charts.
3. Cross-Bureau Intelligence → open a High suggestion, read the reasons.
4. Click **Mark as Related** or **Dismiss**.
5. Complaint Management → pick a complaint → Update status (Resolved needs resolution notes).
6. Audit Trail → filter by the complaint ID; the change and the review decision are there.
7. Analytics & Reports → set filters → download CSVs.

## Tests
```bash
python tests/test_backend.py        # 74 checks: database, validation, audit, matching, risk, CSV, persistence, reset
python tests/test_security_rbac.py  # 61 checks: hashing, lockout, sessions, RBAC matrix, reopen, audit tamper detection, migration, injection
python tests/ui_smoke_stub.py       # 67 checks: every page as Senior/Admin/Bureau officer against a STUB of Streamlit
```
The stub test catches wiring and data errors but is **not** a browser test; verify visually with real Streamlit.

## Limitations (honest list)
- The visual layer (light/dark CSS, animation) was written without a real browser in the build environment; the stub tests prove wiring, not looks. Check it once in Chrome and report any widget that looks off in Dark mode.
- A browser refresh starts a new Streamlit session, so users sign in again.
- SQLite, single server. Good for a demo/pilot; use PostgreSQL for many concurrent users.
- Email needs SMTP; without it, demo mode shows the code on screen (never use that in production).
- Matching is a lexical heuristic (can miss paraphrases); scores are not probabilities.
- No compliance claims. See *Production security considerations*.

## Future improvements
SSO + MFA · PostgreSQL · persistent "remember me" cookies · email/SMS alert delivery · semantic embeddings validated on labelled cases · document attachments · API integration.

## Production security considerations
Authentication (SSO + MFA), server-enforced authorisation, TLS and encryption at rest, secrets management, personal-data
review and retention, automated backups and restores, centralised tamper-evident logging, threat modelling,
dependency scanning and penetration testing, and a formal compliance review. **This prototype makes no compliance
claims.** The same checklist appears in Settings → Production readiness.
#   a i c t e - n e x u s 
 
 