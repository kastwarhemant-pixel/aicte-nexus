# Deploying AICTE NEXUS reliably

The app keeps everything in one SQLite file (WAL mode). It only survives restarts if that file sits on **persistent storage**.

## Option A — Docker (recommended)
```bash
cp .env.example .env      # edit values
docker compose up -d --build
```
Open http://localhost:8501. Data lives in the `nexus-data` volume (`/data/nexus.db`, backups in `/data/backups`).

## Option B — Render / Railway / Fly.io
Deploy the Dockerfile, attach a **persistent disk/volume mounted at `/data`**, set the variables from `.env.example`.
Health check path: `/_stcore/health`. Use HTTPS (the platform terminates TLS).

## Option C — Streamlit Community Cloud (demo only)
Works for a live demo, but its filesystem is **ephemeral**: the database is re-created (and re-seeded) when the app restarts. Put
`NEXUS_DEMO_MODE=1` in *Secrets/Environment*. Do not store real data there.

## Before real use
* `NEXUS_DEMO_MODE=0`, strong `NEXUS_ADMIN_PASSWORD`, SMTP configured, `NEXUS_ALLOWED_EMAIL_DOMAINS` set.
* Back up: Settings → *Data & backups* → **Create backup now** (or copy `/data/nexus.db` while idle). Restore = stop app, replace `nexus.db` with a backup file.
* For many concurrent users, move from SQLite to a managed database (PostgreSQL) — the data layer is in `database.py` only.
