"""SQLite persistence layer for AICTE NEXUS (prototype, synthetic data only).

All SQL is parameterised. Every state-changing function writes an audit event
in the same transaction as the change itself.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import random
import re
import sqlite3
import threading
from contextlib import contextmanager

import pandas as pd

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("NEXUS_DB_PATH") or os.path.join(APP_DIR, "data", "nexus.db")

# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #
BUREAUS = ["Approval Bureau", "Grievance Cell", "Regulation Bureau", "Finance Bureau",
           "Examination/Quality Cell", "Legal Cell"]
CATEGORIES = ["Approval and Accreditation", "Student Grievance", "Faculty Issues",
              "Financial Irregularities", "Infrastructure Compliance",
              "Regulatory Non-Compliance", "Documentation Issues"]
STATUSES = ["Submitted", "Under Review", "In Progress", "Awaiting Information",
            "Resolved", "Closed"]
PRIORITIES = ["Critical", "High", "Medium", "Low"]
TERMINAL_STATUSES = ("Resolved", "Closed")
ACTIVE_STATUSES = tuple(s for s in STATUSES if s not in TERMINAL_STATUSES)
INSTITUTION_TYPES = ["Engineering College", "Management Institute", "Pharmacy College",
                     "Architecture College", "Polytechnic", "University Department"]
STATES = ["Andhra Pradesh", "Assam", "Bihar", "Chhattisgarh", "Delhi", "Goa", "Gujarat",
          "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
          "Madhya Pradesh", "Maharashtra", "Odisha", "Punjab", "Rajasthan",
          "Tamil Nadu", "Telangana", "Uttar Pradesh", "Uttarakhand", "West Bengal"]
SLA_DAYS = {"Critical": 7, "High": 14, "Medium": 30, "Low": 45}
OFFICERS = ["Anita Deshmukh", "Rohit Verma", "Priya Nair", "Imran Qureshi", "Suresh Iyer",
            "Kavita Joshi", "Manoj Pillai", "Neha Banerjee", "Arvind Chauhan", "Lakshmi Reddy"]

ROLES = ["Admin", "Senior Officer", "Bureau Officer"]
_ALL = ("Admin", "Senior Officer", "Bureau Officer")
_SENIOR = ("Admin", "Senior Officer")
# permission -> (roles allowed, human description used in "not permitted" messages)
PERMISSIONS = {
    "complaint.create":         (_ALL, "register complaints"),
    "complaint.update":         (_ALL, "update complaints"),
    "complaint.close":          (_SENIOR, "close complaints (Resolved is available to bureau officers)"),
    "complaint.reassign":       (_SENIOR, "reassign officers"),
    "complaint.priority":       (_SENIOR, "change complaint priority"),
    "complaint.due":            (_SENIOR, "change due dates"),
    "complaint.reopen_request": (_ALL, "request a reopen"),
    "complaint.reopen_decide":  (_SENIOR, "approve or reject reopen requests"),
    "relationship.review":      (_SENIOR, "verify cross-bureau suggestions"),
    "relationship.refresh":     (_SENIOR, "refresh cross-bureau suggestions"),
    "institution.write":        (_SENIOR, "add or edit institutions"),
    "settings.write":           (("Admin",), "change system settings"),
    "users.manage":             (("Admin",), "manage users"),
    "data.reset":               (("Admin",), "reset demo data"),
    "backup.create":            (("Admin",), "create database backups"),
    "audit.verify":             (_SENIOR, "verify audit-log integrity"),
}

DEFAULT_SETTINGS = {
    "due_soon_days": "3",
    "overdue_grace_days": "0", "inactivity_days": "14", "awaiting_info_days": "10",
    "reassignment_threshold": "2", "match_min_score": "0.30", "match_medium_score": "0.45",
    "match_high_score": "0.65", "match_date_window_days": "90", "demo_user": "Demo Officer",
}
# key: (label, type, min, max, help)
SETTING_META = {
    "due_soon_days": ("Deadline alert window (days)", int, 1, 30,
                      "Open cases due within this many days raise a deadline alert."),
    "overdue_grace_days": ("Overdue grace period (days)", int, 0, 30,
                           "Days past the due date tolerated before a case counts as overdue."),
    "inactivity_days": ("Inactivity threshold (days)", int, 1, 180,
                        "Open cases with no update for this many days are flagged inactive."),
    "awaiting_info_days": ("Awaiting-information threshold (days)", int, 1, 180,
                           "Cases waiting on information for this long are flagged."),
    "reassignment_threshold": ("Reassignment threshold (count)", int, 1, 20,
                               "Cases reassigned at least this many times are flagged."),
    "match_min_score": ("Minimum suggestion score", float, 0.05, 0.95,
                        "Cross-bureau pairs below this heuristic score are not suggested."),
    "match_medium_score": ("Medium confidence score", float, 0.05, 0.95,
                           "Score at or above which a suggestion is labelled Medium."),
    "match_high_score": ("High confidence score", float, 0.05, 0.99,
                         "Score at or above which a suggestion is labelled High."),
    "match_date_window_days": ("Date proximity window (days)", int, 7, 365,
                               "Complaints received further apart than this earn no date-proximity credit."),
    "demo_user": ("Demo user name", str, 2, 60,
                  "Label recorded as the actor in the audit trail. This is NOT authentication."),
}

_Q = lambda vals: ",".join("?" * len(vals))  # noqa: E731  placeholder list helper


def _sql_list(values):
    return ",".join("'%s'" % v for v in values)


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS institutions (
    institution_id   TEXT PRIMARY KEY,
    name             TEXT NOT NULL CHECK (length(trim(name)) > 0),
    state            TEXT NOT NULL,
    district         TEXT NOT NULL,
    institution_type TEXT NOT NULL,
    approval_ref     TEXT NOT NULL,
    contact_email    TEXT NOT NULL,
    is_synthetic     INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS complaints (
    complaint_id      TEXT PRIMARY KEY,
    institution_id    TEXT NOT NULL REFERENCES institutions(institution_id) ON UPDATE CASCADE,
    title             TEXT NOT NULL CHECK (length(trim(title)) > 0),
    description       TEXT NOT NULL CHECK (length(trim(description)) > 0),
    bureau            TEXT NOT NULL CHECK (bureau IN ({_sql_list(BUREAUS)})),
    category          TEXT NOT NULL CHECK (category IN ({_sql_list(CATEGORIES)})),
    priority          TEXT NOT NULL CHECK (priority IN ({_sql_list(PRIORITIES)})),
    status            TEXT NOT NULL CHECK (status IN ({_sql_list(STATUSES)})),
    assigned_officer  TEXT NOT NULL CHECK (length(trim(assigned_officer)) > 0),
    date_received     TEXT NOT NULL,
    last_updated      TEXT NOT NULL,
    due_date          TEXT NOT NULL,
    status_changed_at TEXT NOT NULL,
    resolved_date     TEXT,
    resolution_notes  TEXT NOT NULL DEFAULT '',
    related_refs      TEXT NOT NULL DEFAULT '',
    reassign_count    INTEGER NOT NULL DEFAULT 0,
    is_synthetic      INTEGER NOT NULL DEFAULT 1,
    submitted_by      TEXT NOT NULL DEFAULT '',
    reopen_count      INTEGER NOT NULL DEFAULT 0,
    CHECK (due_date >= date_received)
);
CREATE TABLE IF NOT EXISTS complaint_notes (
    note_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id TEXT NOT NULL REFERENCES complaints(complaint_id),
    note_type    TEXT NOT NULL,
    note         TEXT NOT NULL CHECK (length(trim(note)) > 0),
    author       TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS complaint_relationships (
    relationship_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_a      TEXT NOT NULL REFERENCES complaints(complaint_id),
    complaint_b      TEXT NOT NULL REFERENCES complaints(complaint_id),
    institution_id   TEXT NOT NULL REFERENCES institutions(institution_id),
    similarity_score REAL NOT NULL,
    confidence       TEXT NOT NULL CHECK (confidence IN ('High','Medium','Low')),
    reasons          TEXT NOT NULL,
    review_status    TEXT NOT NULL DEFAULT 'Pending'
                     CHECK (review_status IN ('Pending','Related','Dismissed')),
    reviewed_by      TEXT,
    reviewed_at      TEXT,
    review_comment   TEXT,
    created_at       TEXT NOT NULL,
    UNIQUE (complaint_a, complaint_b),
    CHECK (complaint_a < complaint_b)
);
CREATE TABLE IF NOT EXISTS audit_logs (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    action_type    TEXT NOT NULL,
    entity_type    TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    previous_value TEXT,
    new_value      TEXT,
    actor          TEXT NOT NULL,
    details        TEXT,
    prev_hash      TEXT,
    row_hash       TEXT
);
CREATE TABLE IF NOT EXISTS application_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    user_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(username) BETWEEN 3 AND 32),
    email               TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name           TEXT NOT NULL CHECK (length(trim(full_name)) > 1),
    password_hash       TEXT NOT NULL,
    role                TEXT NOT NULL CHECK (role IN ({_sql_list(ROLES)})),
    bureau              TEXT CHECK (bureau IS NULL OR bureau IN ({_sql_list(BUREAUS)})),
    email_verified      INTEGER NOT NULL DEFAULT 0,
    verify_hash         TEXT,
    verify_expires      TEXT,
    verify_attempts     INTEGER NOT NULL DEFAULT 0,
    is_active           INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    failed_attempts     INTEGER NOT NULL DEFAULT 0,
    locked_until        TEXT,
    theme               TEXT NOT NULL DEFAULT 'light' CHECK (theme IN ('light','dark')),
    created_at          TEXT NOT NULL,
    last_login          TEXT,
    CHECK (role <> 'Bureau Officer' OR bureau IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reopen_requests (
    request_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id   TEXT NOT NULL REFERENCES complaints(complaint_id),
    requested_by   TEXT NOT NULL,
    requested_by_id INTEGER,
    reason         TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    status         TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending','Approved','Rejected')),
    decided_by     TEXT,
    decided_at     TEXT,
    decision_note  TEXT,
    created_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reopen_one_pending ON reopen_requests(complaint_id) WHERE status = 'Pending';
CREATE INDEX IF NOT EXISTS idx_sessions_user       ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_complaints_inst     ON complaints(institution_id);
CREATE INDEX IF NOT EXISTS idx_complaints_status   ON complaints(status);
CREATE INDEX IF NOT EXISTS idx_complaints_bureau   ON complaints(bureau);
CREATE INDEX IF NOT EXISTS idx_complaints_due      ON complaints(due_date);
CREATE INDEX IF NOT EXISTS idx_complaints_received ON complaints(date_received);
CREATE INDEX IF NOT EXISTS idx_notes_complaint     ON complaint_notes(complaint_id);
CREATE INDEX IF NOT EXISTS idx_rel_inst            ON complaint_relationships(institution_id);
CREATE INDEX IF NOT EXISTS idx_rel_status          ON complaint_relationships(review_status);
CREATE INDEX IF NOT EXISTS idx_audit_ts            ON audit_logs(ts);
CREATE INDEX IF NOT EXISTS idx_audit_entity        ON audit_logs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_action        ON audit_logs(action_type);
CREATE TRIGGER IF NOT EXISTS trg_audit_no_update BEFORE UPDATE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_audit_no_delete BEFORE DELETE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END;
"""

# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def today() -> dt.date:
    return dt.date.today()


def now_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _clean(value) -> str:
    s = "" if value is None else str(value)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s).strip()


def _like(term: str) -> str:
    t = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{t}%"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Current user context + role-based access control
# --------------------------------------------------------------------------- #
# The Streamlit layer sets the signed-in user at the start of every script run. Every data-layer function
# below enforces permissions and bureau scope from this context, so a missing UI check cannot bypass RBAC.
# With NO user set the caller is treated as trusted system code (seeding, tests, background jobs).
_ctx = threading.local()


def set_current_user(user: dict | None):
    _ctx.user = user


def current_user() -> dict | None:
    return getattr(_ctx, "user", None)


@contextmanager
def trusted():
    """Run system-level code (e.g. re-scoring suggestions over all bureaus) without the caller's scope."""
    prev = current_user()
    set_current_user(None)
    try:
        yield
    finally:
        set_current_user(prev)


def user_label(user: dict | None = None) -> str:
    u = user or current_user()
    return f"{u['full_name']} ({u['role']})" if u else ""


def has_perm(perm: str, user: dict | None = None) -> bool:
    u = user if user is not None else current_user()
    if u is None:
        return True  # trusted system context
    return u["role"] in PERMISSIONS[perm][0]


def _guard(perm: str, bureau: str | None = None) -> str | None:
    """Return an error message when the current user may not do this, else None."""
    u = current_user()
    if u is None:
        return None
    if u["role"] not in PERMISSIONS[perm][0]:
        return f"Your role ({u['role']}) is not permitted to {PERMISSIONS[perm][1]}."
    if bureau is not None and u["role"] == "Bureau Officer" and u.get("bureau") != bureau:
        return f"This complaint belongs to the {bureau}. Bureau officers can only act on their own bureau's cases."
    return None


def _scope_bureaus(requested):
    """Bureau officers only ever see their own bureau, whatever filters were requested."""
    u = current_user()
    if u and u["role"] == "Bureau Officer":
        mine = u.get("bureau")
        if requested:
            return [b for b in requested if b == mine] or ["\x00none"]
        return [mine]
    return requested


def _complaint_visible(conn, cid) -> bool:
    u = current_user()
    if not u or u["role"] != "Bureau Officer":
        return True
    r = conn.execute("SELECT bureau FROM complaints WHERE complaint_id=?", (cid,)).fetchone()
    return bool(r) and r["bureau"] == u.get("bureau")


def _read(sql: str, params=()) -> pd.DataFrame:
    conn = _connect()
    try:
        return pd.read_sql_query(sql, conn, params=list(params))
    finally:
        conn.close()


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """CSV export with spreadsheet-formula neutralisation (CSV injection guard)."""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
        elif not pd.api.types.is_numeric_dtype(out[col]) and not pd.api.types.is_bool_dtype(out[col]):
            out[col] = out[col].map(
                lambda v: "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v)
    return out.to_csv(index=False).encode("utf-8-sig")


# --------------------------------------------------------------------------- #
# Audit + settings
# --------------------------------------------------------------------------- #
def _actor(conn) -> str:
    u = current_user()
    if u:
        return user_label(u)
    row = conn.execute("SELECT value FROM application_settings WHERE key='demo_user'").fetchone()
    return row["value"] if row else "Demo Officer"


_AUDIT_FIELDS = ("ts", "action_type", "entity_type", "entity_id", "previous_value", "new_value", "actor", "details")


def _audit_hash(prev_hash: str, row: dict) -> str:
    payload = json.dumps([prev_hash or ""] + [("" if row[k] is None else str(row[k])) for k in _AUDIT_FIELDS],
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def log_audit(conn, action, entity_type, entity_id, prev=None, new=None, details="",
              actor=None, ts=None):
    """Append an audit event. Each event is hash-chained to the previous one (tamper evidence)."""
    u = current_user()
    who = user_label(u) if (u and not str(actor or "").startswith("System")) else (actor or _actor(conn))
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    last = conn.execute("SELECT row_hash FROM audit_logs WHERE row_hash IS NOT NULL "
                        "ORDER BY event_id DESC LIMIT 1").fetchone()
    prev_hash = last["row_hash"] if last else ""
    row = dict(ts=ts or now_str(), action_type=action, entity_type=entity_type, entity_id=str(entity_id),
               previous_value=None if prev is None else str(prev), new_value=None if new is None else str(new),
               actor=who, details=details or "")
    conn.execute(
        "INSERT INTO audit_logs(ts,action_type,entity_type,entity_id,previous_value,new_value,actor,details,"
        "prev_hash,row_hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (row["ts"], action, entity_type, row["entity_id"], row["previous_value"], row["new_value"],
         who, row["details"], prev_hash, _audit_hash(prev_hash, row)))


def verify_audit_chain() -> dict:
    """Recompute the hash chain. Rows written before hash-chaining existed (NULL hash) are skipped."""
    with get_conn() as conn:
        rows = conn.execute("SELECT event_id, " + ",".join(_AUDIT_FIELDS) + ", prev_hash, row_hash "
                            "FROM audit_logs WHERE row_hash IS NOT NULL ORDER BY event_id").fetchall()
        legacy = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE row_hash IS NULL").fetchone()[0]
    prev, bad = "", None
    for r in rows:
        d = dict(r)
        if d["prev_hash"] != prev or _audit_hash(prev, d) != d["row_hash"]:
            bad = d["event_id"]
            break
        prev = d["row_hash"]
    return {"ok": bad is None, "checked": len(rows), "first_bad_event": bad, "legacy_unchained": legacy}


def get_settings() -> dict:
    out = dict(DEFAULT_SETTINGS)
    with get_conn() as conn:
        for r in conn.execute("SELECT key,value FROM application_settings"):
            out[r["key"]] = r["value"]
    return out


def default_actor() -> str:
    """Audit label of whoever is acting: the signed-in user, else the configured demo label."""
    if current_user():
        return user_label()
    return get_settings().get("demo_user", "Demo Officer")


def _validate_setting(key, raw):
    label, typ, lo, hi, _ = SETTING_META[key]
    try:
        if typ is str:
            v = _clean(raw)
            if not (lo <= len(v) <= hi):
                return False, f"{label} must be {lo}-{hi} characters."
            return True, v
        v = typ(raw)
    except (TypeError, ValueError):
        return False, f"{label} must be a number."
    if not (lo <= v <= hi):
        return False, f"{label} must be between {lo} and {hi}."
    return True, v


def update_settings(new_values: dict, actor=None):
    denied = _guard("settings.write")
    if denied:
        return False, denied
    current = get_settings()
    cleaned = {}
    for key, raw in new_values.items():
        if key not in SETTING_META:
            return False, f"Unknown setting: {key}"
        ok, v = _validate_setting(key, raw)
        if not ok:
            return False, v
        cleaned[key] = v
    merged = {**current, **{k: str(v) for k, v in cleaned.items()}}
    mn, md, hi = (float(merged[k]) for k in ("match_min_score", "match_medium_score", "match_high_score"))
    if not (mn <= md < hi):
        return False, "Scores must satisfy: minimum <= medium < high."
    changed = [k for k, v in cleaned.items() if str(v) != str(current.get(k))]
    if not changed:
        return False, "No settings were changed."
    with get_conn() as conn:
        who = actor or _actor(conn)
        for k in changed:
            conn.execute("INSERT INTO application_settings(key,value,updated_at) VALUES(?,?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                         (k, str(cleaned[k]), now_str()))
            log_audit(conn, "SETTINGS_CHANGED", "Setting", k, current.get(k), cleaned[k],
                      "Setting updated from Settings page", who)
    return True, f"Saved {len(changed)} setting(s)."


# --------------------------------------------------------------------------- #
# Institutions
# --------------------------------------------------------------------------- #
_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{3,23}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def list_institutions(search="", states=None, types=None) -> pd.DataFrame:
    sql = """
    SELECT i.institution_id, i.name, i.state, i.district, i.institution_type, i.approval_ref,
           i.contact_email, i.is_synthetic,
           COALESCE(c.total,0) AS total_complaints, COALESCE(c.open_c,0) AS open_complaints,
           COALESCE(c.resolved_c,0) AS resolved_complaints, c.last_date AS last_complaint_date
    FROM institutions i LEFT JOIN (
        SELECT institution_id, COUNT(*) AS total,
               SUM(CASE WHEN status IN ('Resolved','Closed') THEN 0 ELSE 1 END) AS open_c,
               SUM(CASE WHEN status IN ('Resolved','Closed') THEN 1 ELSE 0 END) AS resolved_c,
               MAX(date_received) AS last_date
        FROM complaints GROUP BY institution_id) c ON c.institution_id = i.institution_id
    WHERE 1=1"""
    params = []
    if search and search.strip():
        sql += " AND (LOWER(i.name) LIKE ? ESCAPE '\\' OR LOWER(i.institution_id) LIKE ? ESCAPE '\\')"
        params += [_like(search.strip())] * 2
    if states:
        sql += f" AND i.state IN ({_Q(states)})"
        params += list(states)
    if types:
        sql += f" AND i.institution_type IN ({_Q(types)})"
        params += list(types)
    return _read(sql + " ORDER BY i.name", params)


def institution_options() -> list:
    with get_conn() as conn:
        return [(r["institution_id"], r["name"]) for r in
                conn.execute("SELECT institution_id,name FROM institutions ORDER BY name")]


def get_institution(iid):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM institutions WHERE institution_id=?", (iid,)).fetchone()
        return dict(r) if r else None


def _validate_institution(d, creating):
    errs = []
    iid = _clean(d.get("institution_id")).upper()
    if creating and not _ID_RE.match(iid):
        errs.append("Institution ID must be 4-24 characters: capital letters, digits and hyphens (e.g. INS-NEW-001).")
    for f, label in (("name", "Institution name"), ("district", "District"),
                     ("approval_ref", "AICTE approval reference"), ("contact_email", "Contact email")):
        if not _clean(d.get(f)):
            errs.append(f"{label} is required.")
    if _clean(d.get("state")) not in STATES:
        errs.append("Select a valid state.")
    if _clean(d.get("institution_type")) not in INSTITUTION_TYPES:
        errs.append("Select a valid institution type.")
    email = _clean(d.get("contact_email"))
    if email and not _EMAIL_RE.match(email):
        errs.append("Contact email is not a valid email address.")
    if len(_clean(d.get("name"))) > 200:
        errs.append("Institution name is too long (max 200).")
    return errs, iid


def add_institution(d: dict, actor=None):
    denied = _guard("institution.write")
    if denied:
        return False, denied
    errs, iid = _validate_institution(d, True)
    if errs:
        return False, " ".join(errs)
    try:
        with get_conn() as conn:
            if conn.execute("SELECT 1 FROM institutions WHERE institution_id=?", (iid,)).fetchone():
                return False, f"Institution ID {iid} already exists. Choose a different ID."
            ts = now_str()
            conn.execute("INSERT INTO institutions VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (iid, _clean(d["name"]), _clean(d["state"]), _clean(d["district"]),
                          _clean(d["institution_type"]), _clean(d["approval_ref"]),
                          _clean(d["contact_email"]), 0, ts, ts))
            log_audit(conn, "INSTITUTION_CREATED", "Institution", iid, None, _clean(d["name"]),
                      "New institution record added by user", actor)
    except sqlite3.IntegrityError as e:
        return False, f"Could not save institution: {e}"
    return True, f"Institution {iid} added."


_INST_FIELDS = ("name", "state", "district", "institution_type", "approval_ref", "contact_email")


def update_institution(iid: str, d: dict, actor=None):
    denied = _guard("institution.write")
    if denied:
        return False, denied
    errs, _ = _validate_institution({**d, "institution_id": iid}, False)
    if errs:
        return False, " ".join(errs)
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM institutions WHERE institution_id=?", (iid,)).fetchone()
        if not cur:
            return False, "Institution not found."
        changes = {f: _clean(d[f]) for f in _INST_FIELDS if _clean(d.get(f)) != cur[f]}
        if not changes:
            return False, "No changes to save."
        sets = ", ".join(f"{f}=?" for f in changes)
        conn.execute(f"UPDATE institutions SET {sets}, updated_at=? WHERE institution_id=?",
                     (*changes.values(), now_str(), iid))
        for f, v in changes.items():
            log_audit(conn, "INSTITUTION_UPDATED", "Institution", iid, cur[f], v, f"Field changed: {f}", actor)
    return True, f"Updated {len(changes)} field(s) on {iid}."


# --------------------------------------------------------------------------- #
# Complaints: read
# --------------------------------------------------------------------------- #
def enrich(df: pd.DataFrame, settings: dict | None = None, ref_date=None) -> pd.DataFrame:
    """Add derived columns: is_open, days_overdue, is_overdue, days_inactive, resolution_days..."""
    s = settings or get_settings()
    ref = pd.Timestamp(ref_date or today())
    df = df.copy()
    for c in ("date_received", "due_date", "last_updated", "resolved_date", "status_changed_at"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["is_open"] = ~df["status"].isin(TERMINAL_STATUSES)
    raw = (ref - df["due_date"]).dt.days.fillna(0).clip(lower=0).astype(int)
    df["days_overdue"] = raw.where(df["is_open"], 0)
    df["is_overdue"] = df["is_open"] & (df["days_overdue"] > int(s["overdue_grace_days"]))
    df["days_to_due"] = (df["due_date"] - ref).dt.days.fillna(0).astype(int)
    df["days_inactive"] = (ref - df["last_updated"]).dt.days.fillna(0).astype(int)
    df["days_in_status"] = (ref - df["status_changed_at"]).dt.days.fillna(0).astype(int)
    df["resolution_days"] = (df["resolved_date"] - df["date_received"]).dt.days
    df["resolved_on_time"] = df["resolved_date"].notna() & (df["resolved_date"] <= df["due_date"])
    return df


def list_complaints(filters: dict | None = None) -> pd.DataFrame:
    f = filters or {}
    sql = ("SELECT c.*, i.name AS institution_name, i.state AS state, i.district AS district "
           "FROM complaints c JOIN institutions i ON i.institution_id = c.institution_id WHERE 1=1")
    params = []
    if f.get("search") and f["search"].strip():
        like = _like(f["search"].strip())
        sql += (" AND (LOWER(c.complaint_id) LIKE ? ESCAPE '\\' OR LOWER(c.title) LIKE ? ESCAPE '\\'"
                " OR LOWER(c.description) LIKE ? ESCAPE '\\' OR LOWER(i.name) LIKE ? ESCAPE '\\')")
        params += [like] * 4
    for key, col in (("statuses", "c.status"), ("bureaus", "c.bureau"), ("categories", "c.category"),
                     ("priorities", "c.priority"), ("states", "i.state"),
                     ("institution_ids", "c.institution_id"), ("officers", "c.assigned_officer")):
        vals = _scope_bureaus(f.get(key)) if key == "bureaus" else f.get(key)
        if vals:
            sql += f" AND {col} IN ({_Q(vals)})"
            params += list(vals)
    if f.get("date_from"):
        sql += " AND c.date_received >= ?"
        params.append(str(f["date_from"]))
    if f.get("date_to"):
        sql += " AND c.date_received <= ?"
        params.append(str(f["date_to"]))
    df = enrich(_read(sql + " ORDER BY c.date_received DESC, c.complaint_id DESC", params))
    if f.get("only_open"):
        df = df[df["is_open"]]
    if f.get("only_overdue"):
        df = df[df["is_overdue"]]
    return df.reset_index(drop=True)


def get_complaint(cid):
    with get_conn() as conn:
        if not _complaint_visible(conn, cid):
            return None
        r = conn.execute("SELECT c.*, i.name AS institution_name, i.state AS state FROM complaints c "
                         "JOIN institutions i ON i.institution_id=c.institution_id WHERE complaint_id=?",
                         (cid,)).fetchone()
        return dict(r) if r else None


def _visible(cid) -> bool:
    with get_conn() as conn:
        return _complaint_visible(conn, cid)


def list_notes(cid) -> pd.DataFrame:
    if not _visible(cid):
        return pd.DataFrame(columns=["note_id", "note_type", "note", "author", "created_at"])
    return _read("SELECT note_id, note_type, note, author, created_at FROM complaint_notes "
                 "WHERE complaint_id=? ORDER BY note_id DESC", [cid])


def get_timeline(cid) -> pd.DataFrame:
    if not _visible(cid):
        return pd.DataFrame(columns=["event_id", "ts", "action_type", "entity_type", "entity_id",
                                     "previous_value", "new_value", "actor", "details"])
    return _read("SELECT event_id, ts, action_type, entity_type, entity_id, previous_value, new_value, actor, details "
                 "FROM audit_logs WHERE (entity_type='Complaint' AND entity_id=?) "
                 "OR (entity_type='Relationship' AND (entity_id LIKE ? ESCAPE '\\' OR entity_id LIKE ? ESCAPE '\\')) "
                 "ORDER BY ts DESC, event_id DESC",
                 [cid, f"{cid}|%", f"%|{cid}"])


def list_officers() -> list:
    with get_conn() as conn:
        extra = [r[0] for r in conn.execute("SELECT DISTINCT assigned_officer FROM complaints")]
    return sorted(set(OFFICERS) | set(extra))


def count_complaints() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]


# --------------------------------------------------------------------------- #
# Complaints: write
# --------------------------------------------------------------------------- #
def _next_complaint_id(conn) -> str:
    nums = [int(r[0].rsplit("-", 1)[-1]) for r in
            conn.execute("SELECT complaint_id FROM complaints WHERE complaint_id LIKE 'CMP-%'")
            if r[0].rsplit("-", 1)[-1].isdigit()]
    return f"CMP-{today().year}-{(max(nums) + 1 if nums else 1):04d}"


def create_complaint(d: dict, actor=None):
    """Returns (ok, message, complaint_id | None)."""
    errs = []
    title, desc = _clean(d.get("title")), _clean(d.get("description"))
    officer, iid = _clean(d.get("assigned_officer")), _clean(d.get("institution_id"))
    if not iid:
        errs.append("Institution is required.")
    if not title:
        errs.append("Title is required.")
    elif len(title) > 200:
        errs.append("Title must be 200 characters or fewer.")
    if not desc:
        errs.append("Description is required.")
    elif len(desc) > 5000:
        errs.append("Description must be 5000 characters or fewer.")
    if not (2 <= len(officer) <= 80):
        errs.append("Assigned officer is required (2-80 characters).")
    for key, allowed, label in (("bureau", BUREAUS, "Bureau"), ("category", CATEGORIES, "Category"),
                                ("priority", PRIORITIES, "Priority")):
        if _clean(d.get(key)) not in allowed:
            errs.append(f"Select a valid {label.lower()}.")
    received, due = parse_date(d.get("date_received")), parse_date(d.get("due_date"))
    if not received:
        errs.append("Date received is not a valid date.")
    elif received > today():
        errs.append("Date received cannot be in the future.")
    if not due:
        errs.append("Due date is not a valid date.")
    elif received and due < received:
        errs.append("Due date cannot be earlier than the date received.")
    refs = [r for r in dict.fromkeys(_clean(x) for x in (d.get("related_refs") or [])) if r]
    if errs:
        return False, " ".join(errs), None
    denied = _guard("complaint.create", _clean(d.get("bureau")))
    if denied:
        return False, denied, None
    try:
        with get_conn() as conn:
            if not conn.execute("SELECT 1 FROM institutions WHERE institution_id=?", (iid,)).fetchone():
                return False, "Selected institution does not exist.", None
            for r in refs:
                if not conn.execute("SELECT 1 FROM complaints WHERE complaint_id=?", (r,)).fetchone():
                    return False, f"Related complaint {r} does not exist.", None
            cid = _next_complaint_id(conn)
            day = str(today())
            conn.execute(
                "INSERT INTO complaints(complaint_id,institution_id,title,description,bureau,category,priority,"
                "status,assigned_officer,date_received,last_updated,due_date,status_changed_at,resolved_date,"
                "resolution_notes,related_refs,reassign_count,is_synthetic,submitted_by,reopen_count) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,'',?,0,0,?,0)",
                (cid, iid, title, desc, d["bureau"], d["category"], d["priority"], "Submitted", officer,
                 str(received), day, str(due), day, ",".join(refs), _actor(conn)))
            log_audit(conn, "COMPLAINT_CREATED", "Complaint", cid, None, "Submitted",
                      f"{title} | {d['bureau']} | {d['priority']} | officer {officer}", actor)
    except sqlite3.IntegrityError as e:
        return False, f"Could not save complaint: {e}", None
    return True, f"Complaint {cid} created.", cid


def _fetch(conn, cid):
    return conn.execute("SELECT * FROM complaints WHERE complaint_id=?", (cid,)).fetchone()


def update_status(cid, new_status, comment="", resolution_notes="", actor=None):
    if new_status not in STATUSES:
        return False, "Select a valid status."
    with get_conn() as conn:
        c = _fetch(conn, cid)
        if not c:
            return False, "Complaint not found."
        denied = _guard("complaint.update", c["bureau"]) or (
            _guard("complaint.close") if new_status == "Closed" else None)
        if denied:
            return False, denied
        if c["status"] == new_status:
            return False, f"Complaint is already '{new_status}'."
        if c["status"] in TERMINAL_STATUSES and new_status not in TERMINAL_STATUSES:
            return False, ("A resolved or closed complaint cannot be moved back directly. "
                           "Submit a reopen request so a senior officer can approve it.")
        res_new = _clean(resolution_notes)
        res_final = res_new or c["resolution_notes"]
        if new_status in TERMINAL_STATUSES and not res_final:
            return False, "Resolution notes are required before marking a complaint Resolved or Closed."
        day = str(today())
        resolved = day if new_status in TERMINAL_STATUSES else None
        if new_status in TERMINAL_STATUSES and c["resolved_date"]:
            resolved = c["resolved_date"]
        conn.execute("UPDATE complaints SET status=?, last_updated=?, status_changed_at=?, resolved_date=?, "
                     "resolution_notes=? WHERE complaint_id=?",
                     (new_status, day, day, resolved, res_final, cid))
        if res_new and res_new != c["resolution_notes"]:
            log_audit(conn, "RESOLUTION_UPDATED", "Complaint", cid, c["resolution_notes"], res_new,
                      "Recorded together with status change", actor)
        log_audit(conn, "STATUS_CHANGED", "Complaint", cid, c["status"], new_status,
                  _clean(comment) or "Status updated", actor)
    return True, f"Status changed from {c['status']} to {new_status}."


def change_priority(cid, new_priority, reason="", actor=None):
    if new_priority not in PRIORITIES:
        return False, "Select a valid priority."
    with get_conn() as conn:
        c = _fetch(conn, cid)
        if not c:
            return False, "Complaint not found."
        denied = _guard("complaint.priority", c["bureau"])
        if denied:
            return False, denied
        if c["priority"] == new_priority:
            return False, f"Priority is already {new_priority}."
        conn.execute("UPDATE complaints SET priority=?, last_updated=? WHERE complaint_id=?",
                     (new_priority, str(today()), cid))
        log_audit(conn, "PRIORITY_CHANGED", "Complaint", cid, c["priority"], new_priority,
                  _clean(reason) or "Priority changed", actor)
    return True, f"Priority changed from {c['priority']} to {new_priority}."


def assign_officer(cid, officer, reason="", actor=None):
    officer = _clean(officer)
    if not (2 <= len(officer) <= 80):
        return False, "Officer name is required (2-80 characters)."
    with get_conn() as conn:
        c = _fetch(conn, cid)
        if not c:
            return False, "Complaint not found."
        denied = _guard("complaint.reassign", c["bureau"])
        if denied:
            return False, denied
        if c["assigned_officer"] == officer:
            return False, f"{officer} is already the assigned officer."
        conn.execute("UPDATE complaints SET assigned_officer=?, reassign_count=reassign_count+1, last_updated=? "
                     "WHERE complaint_id=?", (officer, str(today()), cid))
        log_audit(conn, "OFFICER_ASSIGNED", "Complaint", cid, c["assigned_officer"], officer,
                  _clean(reason) or "Officer reassigned", actor)
    return True, f"Assigned to {officer}."


def update_due_date(cid, new_due, reason="", actor=None):
    due = parse_date(new_due)
    if not due:
        return False, "Due date is not a valid date."
    with get_conn() as conn:
        c = _fetch(conn, cid)
        if not c:
            return False, "Complaint not found."
        denied = _guard("complaint.due", c["bureau"])
        if denied:
            return False, denied
        if due < parse_date(c["date_received"]):
            return False, "Due date cannot be earlier than the date received."
        if str(due) == c["due_date"]:
            return False, "Due date is unchanged."
        conn.execute("UPDATE complaints SET due_date=?, last_updated=? WHERE complaint_id=?",
                     (str(due), str(today()), cid))
        log_audit(conn, "DUE_DATE_CHANGED", "Complaint", cid, c["due_date"], str(due),
                  _clean(reason) or "Due date changed", actor)
    return True, f"Due date set to {due}."


def add_note(cid, text, note_type="Internal Note", actor=None):
    text = _clean(text)
    if not text:
        return False, "Note text cannot be empty."
    if len(text) > 3000:
        return False, "Note must be 3000 characters or fewer."
    with get_conn() as conn:
        cc = _fetch(conn, cid)
        if not cc:
            return False, "Complaint not found."
        denied = _guard("complaint.update", cc["bureau"])
        if denied:
            return False, denied
        who = actor or _actor(conn)
        conn.execute("INSERT INTO complaint_notes(complaint_id,note_type,note,author,created_at) VALUES(?,?,?,?,?)",
                     (cid, note_type, text, who, now_str()))
        conn.execute("UPDATE complaints SET last_updated=? WHERE complaint_id=?", (str(today()), cid))
        log_audit(conn, "NOTE_ADDED", "Complaint", cid, None, note_type, text[:160], who)
    return True, "Note added."


def save_resolution_notes(cid, text, actor=None):
    text = _clean(text)
    if not text:
        return False, "Resolution notes cannot be empty."
    if len(text) > 3000:
        return False, "Resolution notes must be 3000 characters or fewer."
    with get_conn() as conn:
        c = _fetch(conn, cid)
        if not c:
            return False, "Complaint not found."
        denied = _guard("complaint.update", c["bureau"])
        if denied:
            return False, denied
        if c["resolution_notes"] == text:
            return False, "Resolution notes are unchanged."
        conn.execute("UPDATE complaints SET resolution_notes=?, last_updated=? WHERE complaint_id=?",
                     (text, str(today()), cid))
        log_audit(conn, "RESOLUTION_UPDATED", "Complaint", cid, c["resolution_notes"], text,
                  "Resolution notes updated (previous text preserved in this event)", actor)
    return True, "Resolution notes saved."


def add_related_reference(cid, other, actor=None):
    other = _clean(other)
    if not other or other == cid:
        return False, "Choose a different complaint to reference."
    with get_conn() as conn:
        a, b = _fetch(conn, cid), _fetch(conn, other)
        if not a:
            return False, "Complaint not found."
        if not b:
            return False, f"Complaint {other} does not exist."
        denied = _guard("complaint.update", a["bureau"])
        if denied:
            return False, denied
        for x, y in ((a, other), (b, cid)):
            refs = [r for r in x["related_refs"].split(",") if r]
            if y in refs:
                if x is a:
                    return False, f"{other} is already referenced."
                continue
            conn.execute("UPDATE complaints SET related_refs=?, last_updated=? WHERE complaint_id=?",
                         (",".join(refs + [y]), str(today()), x["complaint_id"]))
        log_audit(conn, "RELATED_REFERENCE_ADDED", "Complaint", cid, None, other,
                  "Manual reference recorded on both complaints", actor)
    return True, f"Reference to {other} added."


# --------------------------------------------------------------------------- #
# Reopen requests
# --------------------------------------------------------------------------- #
def request_reopen(cid, reason, actor=None):
    """Any role may ask for a Resolved/Closed complaint to be reopened; a senior officer decides."""
    reason = _clean(reason)
    if not (10 <= len(reason) <= 1000):
        return False, "Give a reason of 10-1000 characters explaining why the complaint should be reopened."
    try:
        with get_conn() as conn:
            c = _fetch(conn, cid)
            if not c:
                return False, "Complaint not found."
            denied = _guard("complaint.reopen_request", c["bureau"])
            if denied:
                return False, denied
            if c["status"] not in TERMINAL_STATUSES:
                return False, "Only Resolved or Closed complaints can be reopened."
            u = current_user()
            who = _actor(conn)
            cur = conn.execute("INSERT INTO reopen_requests(complaint_id,requested_by,requested_by_id,reason,created_at)"
                               " VALUES(?,?,?,?,?)", (cid, who, u["user_id"] if u else None, reason, now_str()))
            log_audit(conn, "REOPEN_REQUESTED", "Complaint", cid, c["status"], "Reopen requested",
                      f"Request #{cur.lastrowid}: {reason[:200]}", actor)
    except sqlite3.IntegrityError:
        return False, "A reopen request for this complaint is already waiting for a decision."
    return True, "Reopen request submitted. A senior officer will review it."


def list_reopen_requests(status=None, complaint_id=None) -> pd.DataFrame:
    sql = ("SELECT r.request_id, r.complaint_id, c.title, c.bureau, c.priority, c.status AS complaint_status, "
           "i.name AS institution_name, r.requested_by, r.reason, r.status, r.decided_by, r.decided_at, "
           "r.decision_note, r.created_at, r.requested_by_id FROM reopen_requests r "
           "JOIN complaints c ON c.complaint_id=r.complaint_id "
           "JOIN institutions i ON i.institution_id=c.institution_id WHERE 1=1")
    params = []
    scoped = _scope_bureaus(None)
    if scoped:
        sql += f" AND c.bureau IN ({_Q(scoped)})"
        params += list(scoped)
    if status:
        sql += f" AND r.status IN ({_Q(status if isinstance(status, (list, tuple)) else [status])})"
        params += list(status if isinstance(status, (list, tuple)) else [status])
    if complaint_id:
        sql += " AND r.complaint_id=?"
        params.append(complaint_id)
    return _read(sql + " ORDER BY (r.status='Pending') DESC, r.request_id DESC", params)


def _apply_reopen(conn, c, detail, actor):
    day = str(today())
    new_due = str(max(parse_date(c["due_date"]), today() + dt.timedelta(days=SLA_DAYS[c["priority"]])))
    conn.execute("UPDATE complaints SET status='Under Review', resolved_date=NULL, status_changed_at=?, "
                 "last_updated=?, reopen_count=reopen_count+1, due_date=? WHERE complaint_id=?",
                 (day, day, new_due, c["complaint_id"]))
    log_audit(conn, "STATUS_CHANGED", "Complaint", c["complaint_id"], c["status"], "Under Review", detail, actor)
    if new_due != c["due_date"]:
        log_audit(conn, "DUE_DATE_CHANGED", "Complaint", c["complaint_id"], c["due_date"], new_due,
                  "Due date reset on reopen (priority SLA)", actor)


def decide_reopen(request_id, approve: bool, note="", actor=None):
    note = _clean(note)
    denied = _guard("complaint.reopen_decide")
    if denied:
        return False, denied
    if not approve and len(note) < 5:
        return False, "Give a short reason (at least 5 characters) when rejecting a reopen request."
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM reopen_requests WHERE request_id=?", (request_id,)).fetchone()
        if not r:
            return False, "Reopen request not found."
        if r["status"] != "Pending":
            return False, f"This request was already {r['status'].lower()}."
        u = current_user()
        if u and r["requested_by_id"] == u["user_id"]:
            return False, "You cannot decide a reopen request that you raised yourself."
        c = _fetch(conn, r["complaint_id"])
        if approve and c["status"] not in TERMINAL_STATUSES:
            return False, "The complaint is no longer Resolved or Closed."
        who = _actor(conn)
        verdict = "Approved" if approve else "Rejected"
        conn.execute("UPDATE reopen_requests SET status=?, decided_by=?, decided_at=?, decision_note=? "
                     "WHERE request_id=?", (verdict, who, now_str(), note, request_id))
        log_audit(conn, "REOPEN_APPROVED" if approve else "REOPEN_REJECTED", "Complaint", r["complaint_id"],
                  "Pending", verdict, f"Request #{request_id}: {note or 'no comment'}", actor)
        if approve:
            _apply_reopen(conn, c, f"Reopened via request #{request_id}", actor)
    return True, (f"Request #{request_id} approved: {r['complaint_id']} is back Under Review."
                  if approve else f"Request #{request_id} rejected.")


def reopen_now(cid, reason, actor=None):
    """Senior officers/admins may reopen directly; this is recorded as one explicit, audited event."""
    reason = _clean(reason)
    denied = _guard("complaint.reopen_decide")
    if denied:
        return False, denied
    if not (10 <= len(reason) <= 1000):
        return False, "Give a reason of 10-1000 characters."
    with get_conn() as conn:
        c = _fetch(conn, cid)
        if not c:
            return False, "Complaint not found."
        if c["status"] not in TERMINAL_STATUSES:
            return False, "Only Resolved or Closed complaints can be reopened."
        if conn.execute("SELECT 1 FROM reopen_requests WHERE complaint_id=? AND status='Pending'", (cid,)).fetchone():
            return False, "A reopen request is already pending; decide it instead."
        who = _actor(conn)
        u = current_user()
        conn.execute("INSERT INTO reopen_requests(complaint_id,requested_by,requested_by_id,reason,status,decided_by,"
                     "decided_at,decision_note,created_at) VALUES(?,?,?,?,'Approved',?,?,?,?)",
                     (cid, who, u["user_id"] if u else None, reason, who, now_str(), "Direct reopen", now_str()))
        log_audit(conn, "REOPEN_APPROVED", "Complaint", cid, c["status"], "Approved", f"Direct reopen: {reason[:200]}", actor)
        _apply_reopen(conn, c, "Reopened directly by a senior officer", actor)
    return True, f"{cid} reopened and set to Under Review."


# --------------------------------------------------------------------------- #
# Relationships (cross-bureau suggestions)
# --------------------------------------------------------------------------- #
def upsert_suggestions(rows: list) -> int:
    """Insert new suggestions; refresh score/reasons of still-pending ones; never touch reviewed ones."""
    n_new = 0
    with get_conn() as conn:
        for r in rows:
            a, b = sorted((r["complaint_a"], r["complaint_b"]))
            exists = conn.execute("SELECT 1 FROM complaint_relationships WHERE complaint_a=? AND complaint_b=?",
                                  (a, b)).fetchone()
            conn.execute(
                "INSERT INTO complaint_relationships(complaint_a,complaint_b,institution_id,similarity_score,"
                "confidence,reasons,created_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(complaint_a,complaint_b) DO UPDATE SET similarity_score=excluded.similarity_score,"
                "confidence=excluded.confidence, reasons=excluded.reasons WHERE review_status='Pending'",
                (a, b, r["institution_id"], float(r["score"]), r["confidence"], r["reasons"], now_str()))
            n_new += 0 if exists else 1
    return n_new


def count_relationships(status=None) -> int:
    with get_conn() as conn:
        if status:
            return conn.execute("SELECT COUNT(*) FROM complaint_relationships WHERE review_status=?",
                                (status,)).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM complaint_relationships").fetchone()[0]


def list_relationships(confidences=None, review_statuses=None, active_only=False, institution_id=None,
                       min_score=None, complaint_ids=None) -> pd.DataFrame:
    sql = """
    SELECT r.relationship_id, r.complaint_a, r.complaint_b, r.institution_id, i.name AS institution_name,
           a.bureau AS bureau_a, b.bureau AS bureau_b, a.title AS title_a, b.title AS title_b,
           a.description AS desc_a, b.description AS desc_b, a.status AS status_a, b.status AS status_b,
           a.priority AS priority_a, b.priority AS priority_b, a.date_received AS received_a,
           b.date_received AS received_b, a.category AS category_a, b.category AS category_b,
           r.similarity_score, r.confidence, r.reasons, r.review_status, r.reviewed_by, r.reviewed_at,
           r.review_comment
    FROM complaint_relationships r
    JOIN complaints a ON a.complaint_id=r.complaint_a JOIN complaints b ON b.complaint_id=r.complaint_b
    JOIN institutions i ON i.institution_id=r.institution_id WHERE 1=1"""
    params = []
    scoped = _scope_bureaus(None)
    if scoped:  # bureau officers see only pairs in which one of the complaints belongs to their bureau
        sql += f" AND (a.bureau IN ({_Q(scoped)}) OR b.bureau IN ({_Q(scoped)}))"
        params += list(scoped) + list(scoped)
    if confidences:
        sql += f" AND r.confidence IN ({_Q(confidences)})"
        params += list(confidences)
    if review_statuses:
        sql += f" AND r.review_status IN ({_Q(review_statuses)})"
        params += list(review_statuses)
    if active_only:
        sql += " AND a.status NOT IN ('Resolved','Closed') AND b.status NOT IN ('Resolved','Closed')"
    if institution_id:
        sql += " AND r.institution_id=?"
        params.append(institution_id)
    if min_score is not None:
        sql += " AND r.similarity_score >= ?"
        params.append(float(min_score))
    if complaint_ids is not None:
        ids = list(complaint_ids)
        if not ids:
            return _read(sql + " AND 1=0", params)
        sql += f" AND (r.complaint_a IN ({_Q(ids)}) OR r.complaint_b IN ({_Q(ids)}))"
        params += ids + ids
    return _read(sql + " ORDER BY r.similarity_score DESC, r.relationship_id", params)


def review_relationship(rid: int, decision: str, comment="", actor=None):
    denied = _guard("relationship.review")
    if denied:
        return False, denied
    if decision not in ("Related", "Dismissed", "Pending"):
        return False, "Decision must be Related, Dismissed or Pending."
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM complaint_relationships WHERE relationship_id=?", (rid,)).fetchone()
        if not r:
            return False, "Suggestion not found."
        if r["review_status"] == decision:
            return False, f"Suggestion is already marked {decision}."
        who = actor or _actor(conn)
        conn.execute("UPDATE complaint_relationships SET review_status=?, reviewed_by=?, reviewed_at=?, "
                     "review_comment=? WHERE relationship_id=?",
                     (decision, None if decision == "Pending" else who,
                      None if decision == "Pending" else now_str(), _clean(comment), rid))
        log_audit(conn, "RELATIONSHIP_REVIEWED", "Relationship", f"{r['complaint_a']}|{r['complaint_b']}",
                  r["review_status"], decision, _clean(comment) or "No comment", who)
    return True, f"Suggestion marked {decision}. No complaint was merged or closed."


# --------------------------------------------------------------------------- #
# Audit queries
# --------------------------------------------------------------------------- #
def list_audit(date_from=None, date_to=None, action_types=None, entity_types=None, entity_id="",
               search="", limit=3000) -> pd.DataFrame:
    sql = ("SELECT event_id, ts, action_type, entity_type, entity_id, previous_value, new_value, actor, details "
           "FROM audit_logs WHERE 1=1")
    params = []
    u = current_user()
    if u and u["role"] == "Bureau Officer":  # own actions + events on own bureau's complaints only
        sql += (" AND (actor=? OR (entity_type='Complaint' AND entity_id IN "
                "(SELECT complaint_id FROM complaints WHERE bureau=?)))")
        params += [user_label(u), u.get("bureau")]
    if date_from:
        sql += " AND ts >= ?"
        params.append(f"{date_from} 00:00:00")
    if date_to:
        sql += " AND ts <= ?"
        params.append(f"{date_to} 23:59:59")
    if action_types:
        sql += f" AND action_type IN ({_Q(action_types)})"
        params += list(action_types)
    if entity_types:
        sql += f" AND entity_type IN ({_Q(entity_types)})"
        params += list(entity_types)
    if entity_id and entity_id.strip():
        sql += " AND LOWER(entity_id) LIKE ? ESCAPE '\\'"
        params.append(_like(entity_id.strip()))
    if search and search.strip():
        sql += " AND (LOWER(details) LIKE ? ESCAPE '\\' OR LOWER(actor) LIKE ? ESCAPE '\\')"
        params += [_like(search.strip())] * 2
    return _read(sql + " ORDER BY ts DESC, event_id DESC LIMIT ?", params + [int(limit)])


def audit_action_types() -> list:
    with get_conn() as conn:
        return [r[0] for r in conn.execute("SELECT DISTINCT action_type FROM audit_logs ORDER BY 1")]


def table_counts() -> dict:
    with get_conn() as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
                ("institutions", "complaints", "complaint_notes", "complaint_relationships",
                 "reopen_requests", "audit_logs", "users", "application_settings")}


# --------------------------------------------------------------------------- #
# Initialisation, seeding, reset
# --------------------------------------------------------------------------- #
def _add_column(conn, table, column, ddl):
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _migrate(conn):
    """Bring a database created by an older version up to the current schema without losing data."""
    _add_column(conn, "complaints", "submitted_by", "submitted_by TEXT NOT NULL DEFAULT ''")
    _add_column(conn, "complaints", "reopen_count", "reopen_count INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "audit_logs", "prev_hash", "prev_hash TEXT")
    _add_column(conn, "audit_logs", "row_hash", "row_hash TEXT")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")      # readers never block the writer; survives restarts
        conn.execute("PRAGMA synchronous = NORMAL")
    finally:
        conn.close()
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.executescript(SCHEMA)  # indexes that depend on migrated columns
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO application_settings(key,value,updated_at) VALUES(?,?,?)",
                         (k, v, now_str()))
        if conn.execute("SELECT COUNT(*) FROM institutions").fetchone()[0] == 0:
            seed_demo_data(conn)


def reset_demo_data(confirm: bool = False, actor=None):
    """Destroys all institutions/complaints/notes/relationships/audit history and reseeds. Needs confirm=True.
    User accounts and sessions are kept."""
    denied = _guard("data.reset")
    if denied:
        return False, denied
    if confirm is not True:
        return False, "Reset not confirmed."
    with get_conn() as conn:
        who = actor or _actor(conn)
        for t in ("reopen_requests", "complaint_relationships", "complaint_notes", "complaints",
                  "institutions", "audit_logs"):
            conn.execute(f"DROP TABLE IF EXISTS {t}")
        conn.executescript(SCHEMA)
        seed_demo_data(conn)
        log_audit(conn, "DEMO_DATA_RESET", "System", "database", None, "reseeded",
                  "All data and audit history replaced with fresh synthetic demo data", who)
    return True, "Demo data was reset and re-seeded."


# --------------------------------------------------------------------------- #
# Backups
# --------------------------------------------------------------------------- #
BACKUP_DIR = os.environ.get("NEXUS_BACKUP_DIR") or os.path.join(os.path.dirname(DB_PATH), "backups")
BACKUP_KEEP = 10


def backup_database(actor=None):
    """Consistent online copy using SQLite's backup API (safe while the app is running)."""
    denied = _guard("backup.create")
    if denied:
        return False, denied
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dest = os.path.join(BACKUP_DIR, f"nexus_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    src = _connect()
    try:
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    old = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("nexus_") and f.endswith(".db"))
    for f in old[:-BACKUP_KEEP]:
        os.remove(os.path.join(BACKUP_DIR, f))
    with get_conn() as conn:
        log_audit(conn, "BACKUP_CREATED", "System", "database", None, os.path.basename(dest),
                  f"Online backup written ({os.path.getsize(dest) // 1024} KB); last {BACKUP_KEEP} kept", actor)
    return True, f"Backup created: {os.path.basename(dest)}"


def list_backups() -> list:
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for f in sorted((f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")), reverse=True):
        path = os.path.join(BACKUP_DIR, f)
        out.append({"file": f, "size_kb": os.path.getsize(path) // 1024,
                    "created": dt.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")})
    return out


_INSTITUTIONS = [
    ("Aravalli Crest Institute of Engineering", "Rajasthan", "Udaipur", "Engineering College"),
    ("Narmada Valley Institute of Management", "Madhya Pradesh", "Jabalpur", "Management Institute"),
    ("Sahyadri Horizon College of Pharmacy", "Maharashtra", "Pune", "Pharmacy College"),
    ("Kaveri Delta Polytechnic", "Tamil Nadu", "Thanjavur", "Polytechnic"),
    ("Himalayan Pinnacle Institute of Technology", "Uttarakhand", "Dehradun", "Engineering College"),
    ("Brahmaputra Riverside College of Engineering", "Assam", "Guwahati", "Engineering College"),
    ("Deccan Meridian School of Architecture", "Telangana", "Hyderabad", "Architecture College"),
    ("Konkan Coastal Institute of Technology", "Maharashtra", "Ratnagiri", "Engineering College"),
    ("Malwa Plateau Institute of Technology", "Madhya Pradesh", "Indore", "Engineering College"),
    ("Thar Horizon Polytechnic", "Rajasthan", "Jodhpur", "Polytechnic"),
    ("Gangetic Plains Institute of Management", "Uttar Pradesh", "Varanasi", "Management Institute"),
    ("Vindhya Summit College of Engineering", "Madhya Pradesh", "Rewa", "Engineering College"),
    ("Sundarbans Delta Institute of Technology", "West Bengal", "Kolkata", "Engineering College"),
    ("Western Ghats College of Pharmacy", "Karnataka", "Mysuru", "Pharmacy College"),
    ("Coromandel Coast Department of Technology", "Andhra Pradesh", "Visakhapatnam", "University Department"),
    ("Five Rivers Institute of Engineering", "Punjab", "Ludhiana", "Engineering College"),
    ("Chambal Ravine Institute of Technology", "Madhya Pradesh", "Gwalior", "Engineering College"),
    ("Nilgiri Mist Institute of Management", "Tamil Nadu", "Coimbatore", "Management Institute"),
    ("Kutch Salt Flats College of Engineering", "Gujarat", "Bhuj", "Engineering College"),
    ("Utkal Heritage Institute of Technology", "Odisha", "Bhubaneswar", "Engineering College"),
    ("Malabar Spice Coast Polytechnic", "Kerala", "Kozhikode", "Polytechnic"),
    ("Bundelkhand Rock Institute of Technology", "Uttar Pradesh", "Jhansi", "Engineering College"),
    ("Shivalik Foothills School of Architecture", "Himachal Pradesh", "Shimla", "Architecture College"),
    ("Hooghly Mill Town Institute of Pharmacy", "West Bengal", "Howrah", "Pharmacy College"),
    ("Satpura Forest Institute of Management", "Madhya Pradesh", "Bhopal", "Management Institute"),
    ("Godavari Basin Institute of Engineering", "Telangana", "Warangal", "Engineering College"),
    ("Gandak Valley Institute of Technology", "Bihar", "Muzaffarpur", "Engineering College"),
    ("Tungabhadra Heritage College of Engineering", "Karnataka", "Hubballi", "Engineering College"),
    ("Plateau Ridge Polytechnic", "Jharkhand", "Ranchi", "Polytechnic"),
    ("Mahanadi Basin Institute of Technology", "Chhattisgarh", "Raipur", "Engineering College"),
]

_CATEGORY_BUREAUS = {
    "Approval and Accreditation": ["Approval Bureau", "Approval Bureau", "Examination/Quality Cell"],
    "Student Grievance": ["Grievance Cell"],
    "Faculty Issues": ["Regulation Bureau", "Grievance Cell"],
    "Financial Irregularities": ["Finance Bureau"],
    "Infrastructure Compliance": ["Regulation Bureau", "Examination/Quality Cell"],
    "Regulatory Non-Compliance": ["Regulation Bureau", "Legal Cell"],
    "Documentation Issues": ["Approval Bureau", "Regulation Bureau"],
}

_GENERIC = {
    "Approval and Accreditation": [
        ("Delay in processing of approval extension",
         "The institution reports that its application for extension of approval has remained pending beyond the stipulated period without a decision."),
        ("Admissions advertised before approval confirmation",
         "Complaint alleges that admissions for the coming session are being publicised before approval has been confirmed.")],
    "Student Grievance": [
        ("Hostel facilities not as promised at admission",
         "Students allege that hostel rooms, mess quality and drinking water differ from what was promised during admission counselling."),
        ("Delay in issuing transcripts and migration certificates",
         "Graduating students report repeated delays in receiving transcripts and migration certificates from the institution office."),
        ("Anti-ragging complaint not acted upon",
         "A student reports that an anti-ragging complaint was not acted upon by the institution committee in the stipulated time.")],
    "Faculty Issues": [
        ("Teaching staff appointed without prescribed qualifications",
         "Complaint states that several teaching staff were appointed without meeting the prescribed qualification requirements."),
        ("Pay scale and promotion benefits not implemented",
         "Members of staff allege that revised pay scales and promotion benefits have not been implemented.")],
    "Financial Irregularities": [
        ("Capitation demanded during counselling",
         "Parents allege that unofficial payments were demanded at the time of admission counselling."),
        ("Scholarship amounts not passed on to eligible students",
         "Eligible students report that scholarship amounts credited to the institution have not reached them.")],
    "Infrastructure Compliance": [
        ("Fire safety certificate expired for academic building",
         "Complaint states that the fire safety certificate for the main academic building has expired and no renewal is displayed."),
        ("Overcrowded classrooms and poor sanitation",
         "Students report overcrowded classrooms and inadequate sanitation facilities on campus.")],
    "Regulatory Non-Compliance": [
        ("Mandatory disclosures missing from website",
         "Required public disclosures about intake, courses and governance are not available on the institution website."),
        ("Admissions above sanctioned intake",
         "Allegation that the institution admitted students beyond the sanctioned intake for the current session.")],
    "Documentation Issues": [
        ("Annual report not submitted by deadline",
         "The institution has not submitted its annual report and compliance documents within the prescribed deadline."),
        ("Land document mismatch in approval application",
         "Land use documents submitted with the approval application show a mismatch in survey numbers.")],
}

# Each theme: three related complaints raised in three different bureaus.
_THEMES = [
    [("Finance Bureau", "Financial Irregularities", "Excess tuition fee collected without receipts",
      "Parents allege tuition fee was collected above the approved fee structure and receipts were not issued for hostel fee payments. Audit of the fee ledger requested."),
     ("Grievance Cell", "Student Grievance", "Fee refund withheld after admission cancellation",
      "Several students report that tuition fee refund was withheld after admission cancellation despite the approved refund policy. Fee receipts are disputed."),
     ("Legal Cell", "Regulatory Non-Compliance", "Approved fee structure directive not followed",
      "The institution has not complied with the directive to publish the approved tuition fee structure and refund policy.")],
    [("Regulation Bureau", "Infrastructure Compliance", "Laboratory facilities below prescribed norms",
      "Inspection feedback indicates computer and mechanical laboratory equipment is below prescribed norms; library and workshop space is inadequate."),
     ("Examination/Quality Cell", "Infrastructure Compliance", "Practical examinations held without functional laboratory",
      "Students report practical examinations conducted with non-functional laboratory equipment and insufficient workshop capacity."),
     ("Approval Bureau", "Documentation Issues", "Laboratory equipment inventory documents inconsistent",
      "Documents submitted for approval list a laboratory equipment inventory that does not match inspection findings on workshop and library facilities.")],
    [("Regulation Bureau", "Faculty Issues", "Faculty shortage against sanctioned intake",
      "Complaint states faculty strength is below the required student-faculty ratio for sanctioned intake; part-time faculty are shown as regular faculty."),
     ("Approval Bureau", "Documentation Issues", "Faculty records submitted for approval look inconsistent",
      "Faculty records and qualification documents submitted for approval renewal show duplicate entries; a faculty shortage is suspected."),
     ("Grievance Cell", "Faculty Issues", "Faculty salary unpaid for several months",
      "Faculty members report salary unpaid for several months and pressure to resign; faculty shortage is affecting classes.")],
    [("Approval Bureau", "Approval and Accreditation", "Decision on approval extension delayed",
      "The institution's approval extension application remains pending and admissions for the session are uncertain."),
     ("Legal Cell", "Regulatory Non-Compliance", "Admissions advertised without approval extension",
      "Admissions are advertised for the coming session although the approval extension has not been granted; students may be misled."),
     ("Examination/Quality Cell", "Approval and Accreditation", "Accreditation documents incomplete for quality review",
      "Accreditation documents for the quality review are incomplete and the approval extension status is unclear.")],
]

_RESOLUTIONS = [
    "Verified with the institution; corrective action plan accepted and compliance confirmed.",
    "Inspection report reviewed; institution rectified the issue and submitted compliance proof.",
    "Complaint partly substantiated; advisory issued to the institution.",
    "Matter closed after submission of satisfactory documents by the institution.",
]
_NOTES = [
    "Acknowledged and allotted to the concerned desk for examination.",
    "Clarification sought from the institution; reminder issued.",
    "Supporting documents reviewed; further verification pending.",
    "Discussed with the bureau head; follow-up scheduled.",
]


def _weighted(rnd, options, weights):
    return rnd.choices(options, weights=weights, k=1)[0]


def _make_complaint(rnd, t, inst_id, bureau, cat, title, desc, received, status):
    priority = _weighted(rnd, PRIORITIES, [13, 26, 40, 21])
    slack = rnd.choice([0, 5, 10]) if status in TERMINAL_STATUSES else rnd.choice([0, 10, 30, 45, 60, 90, 120])
    due = received + dt.timedelta(days=SLA_DAYS[priority] + slack)
    span = max(0, (t - received).days)
    resolved, notes = None, ""
    if status in TERMINAL_STATUSES:
        res_days = rnd.randint(2, max(3, min(max(span, 3), SLA_DAYS[priority] + 25)))
        resolved = min(received + dt.timedelta(days=res_days), t)
        last_updated = status_changed = resolved
        notes = rnd.choice(_RESOLUTIONS)
    else:
        if rnd.random() < (0.25 if status == "Awaiting Information" else 0.55):
            last_updated = max(received, t - dt.timedelta(days=rnd.randint(0, 9)))
        else:
            last_updated = received + dt.timedelta(days=rnd.randint(0, span))
        status_changed = received if status == "Submitted" else last_updated
    return dict(institution_id=inst_id, title=title, description=desc, bureau=bureau, category=cat,
                priority=priority, status=status, assigned_officer=rnd.choice(OFFICERS),
                date_received=received, last_updated=last_updated, due_date=due,
                status_changed_at=status_changed, resolved_date=resolved, resolution_notes=notes,
                reassign_count=_weighted(rnd, [0, 1, 2, 3, 4], [45, 30, 15, 7, 3]))


def seed_demo_data(conn):
    """Populate synthetic demo data. All entities are fictional."""
    rnd, t, stamp = random.Random(2026), today(), now_str()
    for n, (name, state, district, itype) in enumerate(_INSTITUTIONS, start=1):
        slug = re.sub(r"[^a-z]", "", name.lower())[:16]
        conn.execute("INSERT INTO institutions VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (f"INS-DEMO-{n:03d}", name, state, district, itype,
                      f"AICTE/DEMO/{2012 + (n * 3) % 12}/{n:04d}", f"registrar@{slug}.example.edu", 1, stamp, stamp))
    rows = []
    status_all, w_all = STATUSES, [10, 18, 25, 12, 20, 15]
    for k, idx in enumerate([2, 3, 6, 10, 13, 18, 20, 26]):  # clusters of 3 related cross-bureau complaints
        base = t - dt.timedelta(days=rnd.randint(25, 140))
        for bureau, cat, title, desc in _THEMES[k % len(_THEMES)]:
            status = _weighted(rnd, status_all, [12, 22, 28, 18, 12, 8])
            rows.append(_make_complaint(rnd, t, f"INS-DEMO-{idx:03d}", bureau, cat, title, desc,
                                        base + dt.timedelta(days=rnd.randint(0, 30)), status))
    for _ in range(52):
        cat = rnd.choice(CATEGORIES)
        title, desc = rnd.choice(_GENERIC[cat])
        status = _weighted(rnd, status_all, w_all)
        days_ago = rnd.randint(25, 300) if status in TERMINAL_STATUSES else int(rnd.triangular(1, 260, 45))
        rows.append(_make_complaint(rnd, t, f"INS-DEMO-{rnd.randint(1, len(_INSTITUTIONS)):03d}",
                                    rnd.choice(_CATEGORY_BUREAUS[cat]), cat, title, desc,
                                    t - dt.timedelta(days=days_ago), status))
    rows.sort(key=lambda r: r["date_received"])
    for n, r in enumerate(rows, start=1):
        cid = f"CMP-{t.year}-{n:04d}"
        conn.execute(
            "INSERT INTO complaints(complaint_id,institution_id,title,description,bureau,category,priority,status,"
            "assigned_officer,date_received,last_updated,due_date,status_changed_at,resolved_date,resolution_notes,"
            "related_refs,reassign_count,is_synthetic,submitted_by,reopen_count) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'',?,1,'System (seed)',0)",
            (cid, r["institution_id"], r["title"], r["description"], r["bureau"], r["category"], r["priority"],
             r["status"], r["assigned_officer"], str(r["date_received"]), str(r["last_updated"]),
             str(r["due_date"]), str(r["status_changed_at"]),
             None if r["resolved_date"] is None else str(r["resolved_date"]), r["resolution_notes"],
             r["reassign_count"]))
        log_audit(conn, "COMPLAINT_CREATED", "Complaint", cid, None, "Submitted",
                  f"{r['title']} | {r['bureau']} | {r['priority']}", "System (seed)",
                  f"{r['date_received']} 09:{rnd.randint(0, 59):02d}:00")
        if r["status"] != "Submitted":
            log_audit(conn, "STATUS_CHANGED", "Complaint", cid, "Submitted", r["status"],
                      "Seeded status", "System (seed)", f"{r['status_changed_at']} 11:15:00")
            if rnd.random() < 0.4:
                note = rnd.choice(_NOTES)
                conn.execute("INSERT INTO complaint_notes(complaint_id,note_type,note,author,created_at) "
                             "VALUES(?,?,?,?,?)", (cid, "Internal Note", note, r["assigned_officer"],
                                                   f"{r['status_changed_at']} 12:00:00"))
                log_audit(conn, "NOTE_ADDED", "Complaint", cid, None, "Internal Note", note,
                          r["assigned_officer"], f"{r['status_changed_at']} 12:00:00")
    _seed_reopen_requests(conn, rnd)
    _seed_deadline_cases(conn)


def _seed_reopen_requests(conn, rnd):
    """A few reopen requests so the workflow can be shown in the demo (2 pending, 1 rejected, 1 approved)."""
    done = [r["complaint_id"] for r in conn.execute(
        "SELECT complaint_id FROM complaints WHERE status IN ('Resolved','Closed') ORDER BY complaint_id")]
    active = [r["complaint_id"] for r in conn.execute(
        "SELECT complaint_id FROM complaints WHERE status IN ('In Progress','Under Review') ORDER BY complaint_id")]
    reasons = ["Institution has again stopped issuing fee receipts after the case was resolved.",
               "Complainant submitted fresh evidence that the corrective action was not implemented.",
               "Follow-up inspection found the reported deficiency still present.",
               "Resolution was recorded before the institution submitted the promised documents."]
    stamp = now_str()
    plan = [(done[0], "Pending"), (done[1], "Pending"), (done[2], "Rejected")] if len(done) >= 3 else []
    for n, (cid, status) in enumerate(plan):
        conn.execute("INSERT INTO reopen_requests(complaint_id,requested_by,reason,status,decided_by,decided_at,"
                     "decision_note,created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (cid, "Priya Nair (Bureau Officer)", reasons[n], status,
                      "Anita Deshmukh (Senior Officer)" if status != "Pending" else None,
                      stamp if status != "Pending" else None,
                      "Evidence already covered in the original resolution." if status != "Pending" else None, stamp))
        log_audit(conn, "REOPEN_REQUESTED", "Complaint", cid, "Resolved", "Reopen requested", reasons[n],
                  "System (seed)")
    if active:
        cid = active[0]
        conn.execute("UPDATE complaints SET reopen_count=1 WHERE complaint_id=?", (cid,))
        conn.execute("INSERT INTO reopen_requests(complaint_id,requested_by,reason,status,decided_by,decided_at,"
                     "decision_note,created_at) VALUES(?,?,?,'Approved',?,?,?,?)",
                     (cid, "Rohit Verma (Bureau Officer)", reasons[3], "Anita Deshmukh (Senior Officer)", stamp,
                      "Approved after document review.", stamp))
        log_audit(conn, "REOPEN_APPROVED", "Complaint", cid, "Pending", "Approved", "Seeded reopen history",
                  "System (seed)")


def _seed_deadline_cases(conn):
    """Make a few open complaints due within the next days so deadline alerts are visible in the demo."""
    t = today()
    rows = conn.execute("SELECT complaint_id, date_received FROM complaints WHERE status IN ('Under Review','In Progress','Submitted') "
                        "AND due_date >= ? ORDER BY complaint_id DESC LIMIT 12", (str(t),)).fetchall()
    for k, r in zip((0, 1, 2, 3), rows):
        due = t + dt.timedelta(days=k)
        if due >= parse_date(r["date_received"]):
            conn.execute("UPDATE complaints SET due_date=? WHERE complaint_id=?", (str(due), r["complaint_id"]))
