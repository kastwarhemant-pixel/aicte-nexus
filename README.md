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

## Features
| Module | What it does |
|---|---|
| Overview | Hero summary, 6 KPIs, status / priority / resolution / bureau / trend charts, critical, overdue, recent and activity lists. Filters: date, bureau, state, institution, status, priority. |
| Institution Directory | Search (name/ID), state and type filters, details with full complaint history and charts, add (validated, duplicate IDs blocked), edit, CSV export. |
| Complaint Management | Search + 7 filters, details view, timeline, create, status update, officer reassignment, priority change, due date change, notes, resolution notes, manual references, overdue highlighting, CSV export. |
| Cross-Bureau Intelligence | Explainable pair suggestions with reasons, score, confidence label and review status. Officers mark **Related**, **Dismissed** or reset to pending. Nothing is merged or closed automatically. |
| Risk Monitoring | Overdue / inactive / Critical / reassigned / awaiting-information flags with **recommended** next actions (never automatic). Thresholds configurable. |
| Analytics & Reports | Counts by bureau, state, category, status, month, institution; avg resolution time, on-time %, overdue %; 5 CSV exports honouring filters. |
| Audit Trail | Append-only event log with date / action / entity filters and CSV export. |
| Settings | Thresholds, demo user label, demo-data reset (checkbox + typed `RESET`), production-readiness checklist. |
| NEXUS AI Assistant | Database-grounded natural-language questions for complaint summary, overdue cases, bureau workload, institution volume, resolution performance and risk flags; result tables can be exported to CSV. Offline-safe intent mode works without an API key; optional Groq phrasing is available via `GROQ_API_KEY`. |

## Architecture
```
app.py                 entry point: page config, theme, st.navigation
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
`audit_logs` (append-only via triggers) · `application_settings`. Primary and foreign keys, CHECK constraints, unique
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
python tests/test_backend.py      # 73 checks: database, validation, audit, matching, risk, CSV, persistence, reset
python tests/ui_smoke_stub.py     # 37 checks: runs every page script against a STUB of Streamlit/Plotly
```
The stub test catches wiring and data errors but is **not** a browser test; verify visually with real Streamlit.

## Limitations
- No authentication or roles; the "demo user" is only an audit label.
- Local SQLite file, single-user; audit log is not tamper-proof (anyone with file access can alter it).
- Matching is a lightweight lexical heuristic: it can miss paraphrases and over-match shared boilerplate.
- Seeded due dates, statuses and thresholds are illustrative. CSV exports neutralise spreadsheet formulas.
- Visual layout has not been checked in a real browser in the build environment (see test notes).

## Future improvements
SSO and role-based, bureau-scoped access · managed database · hash-chained audit log · semantic embeddings
validated on labelled cases · notifications and SLA escalation workflows · document attachments · API integration.

## Production security considerations
Authentication (SSO + MFA), server-enforced authorisation, TLS and encryption at rest, secrets management, personal-data
review and retention, automated backups and restores, centralised tamper-evident logging, threat modelling,
dependency scanning and penetration testing, and a formal compliance review. **This prototype makes no compliance
claims.** The same checklist appears in Settings → Production readiness.
#   a i c t e - n e x u s  
 