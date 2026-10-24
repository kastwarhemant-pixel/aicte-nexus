"""User accounts, password hashing, email verification and server-side sessions.

No Streamlit imports here: everything is plain Python on top of ``database`` so it can be tested directly.

Security notes
- Passwords are hashed with scrypt (stdlib, memory-hard) using a random per-user salt; compared in constant time.
- Session tokens are random 256-bit values. Only their SHA-256 hash is stored, so a copied database cannot
  be used to hijack a live session. Sessions expire after idle time and after an absolute lifetime.
- After MAX_FAILED wrong passwords an account is locked for LOCK_MINUTES. Login errors never reveal whether
  the username exists.
- Self-registration can only create "Bureau Officer" accounts. Higher roles are granted by an Admin.
- Email verification uses a 6-digit one-time code (stored hashed, 30 minutes, 5 attempts). Mail is sent through
  SMTP when NEXUS_SMTP_HOST is configured; otherwise (demo mode) the code is returned so the UI can display it.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
import smtplib
import sqlite3
from email.message import EmailMessage

import database as db

MAX_FAILED = 5
LOCK_MINUTES = 15
IDLE_MINUTES = int(os.environ.get("NEXUS_SESSION_IDLE_MINUTES", "30"))
ABSOLUTE_HOURS = int(os.environ.get("NEXUS_SESSION_MAX_HOURS", "12"))
VERIFY_MINUTES = 30
VERIFY_MAX_ATTEMPTS = 5
DEMO_PASSWORD = "Nexus@2026"

_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,31}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_COMMON = {"password", "password1", "password123", "12345678", "123456789", "qwerty123", "admin123",
           "welcome123", "letmein123", "iloveyou1", "abc12345", "nexus@2026x"}
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1
_FMT = "%Y-%m-%d %H:%M:%S"


def demo_mode() -> bool:
    return os.environ.get("NEXUS_DEMO_MODE", "1").strip() not in ("0", "false", "no")


def _now() -> dt.datetime:
    return dt.datetime.now()


def _ts(t: dt.datetime) -> str:
    return t.strftime(_FMT)


def _parse(s):
    try:
        return dt.datetime.strptime(s, _FMT) if s else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt)}${b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, dk = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r),
                              p=int(p), dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def password_problems(password: str, username: str = "", email: str = "") -> list:
    """Return a list of human-readable problems; empty list means the password is acceptable."""
    pw, out = password or "", []
    if len(pw) < 8:
        out.append("at least 8 characters")
    if len(pw) > 128:
        out.append("at most 128 characters")
    if not re.search(r"[a-z]", pw):
        out.append("a lowercase letter")
    if not re.search(r"[A-Z]", pw):
        out.append("an uppercase letter")
    if not re.search(r"\d", pw):
        out.append("a digit")
    if not re.search(r"[^A-Za-z0-9]", pw):
        out.append("a special character")
    low = pw.lower()
    if low in _COMMON:
        out.append("something less common")
    if username and len(username) >= 3 and username.lower() in low:
        out.append("no part of your username")
    if email and email.split("@")[0].lower() in low and len(email.split("@")[0]) >= 4:
        out.append("no part of your email")
    return out


def _pw_error(problems: list) -> str:
    return "Password needs: " + ", ".join(problems) + "."


# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #
def smtp_configured() -> bool:
    return bool(os.environ.get("NEXUS_SMTP_HOST"))


def send_email(to: str, subject: str, body: str) -> bool:
    """Send through SMTP if configured. Returns True only when the message was handed to the server."""
    host = os.environ.get("NEXUS_SMTP_HOST")
    if not host:
        return False
    try:
        msg = EmailMessage()
        msg["From"] = os.environ.get("NEXUS_SMTP_FROM", "no-reply@aicte-nexus.example")
        msg["To"], msg["Subject"] = to, subject
        msg.set_content(body)
        with smtplib.SMTP(host, int(os.environ.get("NEXUS_SMTP_PORT", "587")), timeout=15) as smtp:
            smtp.starttls()
            user = os.environ.get("NEXUS_SMTP_USER")
            if user:
                smtp.login(user, os.environ.get("NEXUS_SMTP_PASSWORD", ""))
            smtp.send_message(msg)
        return True
    except Exception:
        return False


def _allowed_domain(email: str) -> bool:
    allowed = [d.strip().lower() for d in os.environ.get("NEXUS_ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()]
    return not allowed or email.split("@")[-1].lower() in allowed


def _code_hash(code: str, user_id: int) -> str:
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()


def _issue_code(conn, user_id: int, email: str, name: str):
    """Create a one-time code; returns (code_to_show_in_demo_or_None, emailed)."""
    code = f"{secrets.randbelow(10 ** 6):06d}"
    conn.execute("UPDATE users SET verify_hash=?, verify_expires=?, verify_attempts=0 WHERE user_id=?",
                 (_code_hash(code, user_id), _ts(_now() + dt.timedelta(minutes=VERIFY_MINUTES)), user_id))
    sent = send_email(email, "AICTE NEXUS - verify your email",
                      f"Hello {name},\n\nYour AICTE NEXUS verification code is {code}.\n"
                      f"It expires in {VERIFY_MINUTES} minutes. If you did not register, ignore this email.\n")
    return (None if sent else code), sent


# --------------------------------------------------------------------------- #
# Registration and verification
# --------------------------------------------------------------------------- #
def _audit(conn, action, entity, details="", actor="Anonymous", prev=None, new=None):
    db.log_audit(conn, action, "User", entity, prev, new, details, actor=actor)


def register_user(username, full_name, email, password, bureau):
    """Self-registration. Always creates an unverified Bureau Officer. Returns (ok, message, demo_code|None)."""
    username, full_name, email = db._clean(username), db._clean(full_name), db._clean(email).lower()
    errs = []
    if not _USERNAME_RE.match(username):
        errs.append("Username must be 3-32 characters, start with a letter, and use only letters, digits, . _ -")
    if not (2 <= len(full_name) <= 80):
        errs.append("Enter your full name (2-80 characters).")
    if not _EMAIL_RE.match(email) or len(email) > 120:
        errs.append("Enter a valid email address.")
    elif not _allowed_domain(email):
        errs.append("Registration is limited to approved email domains.")
    if bureau not in db.BUREAUS:
        errs.append("Select your bureau / cell.")
    bad = password_problems(password, username, email)
    if bad:
        errs.append(_pw_error(bad))
    if errs:
        return False, " ".join(errs), None
    try:
        with db.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO users(username,email,full_name,password_hash,role,bureau,email_verified,created_at) "
                "VALUES(?,?,?,?,?,?,0,?)",
                (username, email, full_name, hash_password(password), "Bureau Officer", bureau, db.now_str()))
            uid = cur.lastrowid
            code, sent = _issue_code(conn, uid, email, full_name)
            _audit(conn, "USER_REGISTERED", username, f"Self-registration as Bureau Officer ({bureau}); "
                   f"verification {'emailed' if sent else 'shown on screen (demo mode)'}", f"{full_name} (new)")
    except sqlite3.IntegrityError:
        return False, "That username or email is already registered.", None
    msg = ("Account created. A verification code was emailed to you." if sent
           else "Account created. Email is not configured on this server (demo mode), so your code is shown below.")
    return True, msg, code


def _find(conn, identifier):
    ident = db._clean(identifier)
    return conn.execute("SELECT * FROM users WHERE username=? OR email=?", (ident, ident.lower())).fetchone()


def resend_verification(identifier):
    with db.get_conn() as conn:
        u = _find(conn, identifier)
        if not u or u["email_verified"]:
            # same answer either way: do not reveal which accounts exist
            return True, "If that account exists and is unverified, a new code has been issued.", None
        code, sent = _issue_code(conn, u["user_id"], u["email"], u["full_name"])
        _audit(conn, "VERIFICATION_RESENT", u["username"], "New verification code issued", u["full_name"])
    return True, "If that account exists and is unverified, a new code has been issued.", code


def verify_email(identifier, code):
    code = db._clean(code)
    with db.get_conn() as conn:
        u = _find(conn, identifier)
        generic = "That code is not valid or has expired. Request a new one."
        if not u or u["email_verified"] or not u["verify_hash"]:
            return False, generic
        if u["verify_attempts"] >= VERIFY_MAX_ATTEMPTS:
            return False, "Too many attempts. Request a new code."
        exp = _parse(u["verify_expires"])
        ok = bool(exp and exp > _now()) and hmac.compare_digest(_code_hash(code, u["user_id"]), u["verify_hash"])
        if not ok:
            conn.execute("UPDATE users SET verify_attempts=verify_attempts+1 WHERE user_id=?", (u["user_id"],))
            return False, generic
        conn.execute("UPDATE users SET email_verified=1, verify_hash=NULL, verify_expires=NULL, verify_attempts=0 "
                     "WHERE user_id=?", (u["user_id"],))
        _audit(conn, "EMAIL_VERIFIED", u["username"], "Email address verified", u["full_name"])
    return True, "Email verified. You can sign in now."


# --------------------------------------------------------------------------- #
# Login, sessions
# --------------------------------------------------------------------------- #
_BAD = "Incorrect username or password."


def authenticate(identifier, password):
    """Returns (ok, user_dict | None, message). Handles lockout and audit."""
    ident = db._clean(identifier)
    with db.get_conn() as conn:
        u = _find(conn, ident)
        if not u:
            verify_password(password or "", hash_password("dummy"))  # equalise timing
            _audit(conn, "LOGIN_FAILED", ident[:40] or "-", "Unknown username", "Anonymous")
            return False, None, _BAD
        locked = _parse(u["locked_until"])
        if locked and locked > _now():
            mins = max(1, int((locked - _now()).total_seconds() // 60) + 1)
            _audit(conn, "LOGIN_BLOCKED", u["username"], "Attempt while account locked", u["full_name"])
            return False, None, f"Too many failed attempts. Try again in about {mins} minute(s)."
        if not verify_password(password or "", u["password_hash"]):
            n = u["failed_attempts"] + 1
            lock = _ts(_now() + dt.timedelta(minutes=LOCK_MINUTES)) if n >= MAX_FAILED else None
            conn.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE user_id=?",
                         (0 if lock else n, lock, u["user_id"]))
            _audit(conn, "ACCOUNT_LOCKED" if lock else "LOGIN_FAILED", u["username"],
                   f"Wrong password ({n}/{MAX_FAILED})", u["full_name"])
            return False, None, _BAD
        if not u["is_active"]:
            _audit(conn, "LOGIN_BLOCKED", u["username"], "Deactivated account", u["full_name"])
            return False, None, "This account has been deactivated. Contact an administrator."
        if not u["email_verified"]:
            return False, None, "Please verify your email first (use the Verify email tab)."
        conn.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login=? WHERE user_id=?",
                     (db.now_str(), u["user_id"]))
        _audit(conn, "LOGIN_SUCCESS", u["username"], f"Signed in as {u['role']}", u["full_name"])
        return True, _public(u), "Signed in."


def _public(row) -> dict:
    d = dict(row)
    for k in ("password_hash", "verify_hash", "verify_expires", "verify_attempts", "failed_attempts", "locked_until"):
        d.pop(k, None)
    return d


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    with db.get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ? OR revoked=1", (_ts(now - dt.timedelta(days=1)),))
        conn.execute("INSERT INTO sessions(token_hash,user_id,created_at,last_seen,expires_at) VALUES(?,?,?,?,?)",
                     (hashlib.sha256(token.encode()).hexdigest(), user_id, _ts(now), _ts(now),
                      _ts(now + dt.timedelta(minutes=IDLE_MINUTES))))
    return token


def validate_session(token):
    """Return the user dict for a live session (and slide the idle timeout), else None."""
    if not token:
        return None
    th, now = hashlib.sha256(str(token).encode()).hexdigest(), _now()
    with db.get_conn() as conn:
        s = conn.execute("SELECT * FROM sessions WHERE token_hash=?", (th,)).fetchone()
        if not s or s["revoked"]:
            return None
        created = _parse(s["created_at"])
        if (_parse(s["expires_at"]) or now) < now or (created and now - created > dt.timedelta(hours=ABSOLUTE_HOURS)):
            conn.execute("UPDATE sessions SET revoked=1 WHERE token_hash=?", (th,))
            return None
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (s["user_id"],)).fetchone()
        if not u or not u["is_active"]:
            return None
        conn.execute("UPDATE sessions SET last_seen=?, expires_at=? WHERE token_hash=?",
                     (_ts(now), _ts(now + dt.timedelta(minutes=IDLE_MINUTES)), th))
        return _public(u)


def end_session(token, user=None):
    if not token:
        return
    with db.get_conn() as conn:
        conn.execute("UPDATE sessions SET revoked=1 WHERE token_hash=?", (hashlib.sha256(str(token).encode()).hexdigest(),))
        if user:
            _audit(conn, "LOGOUT", user["username"], "Signed out", db.user_label(user))


def revoke_user_sessions(conn, user_id: int):
    conn.execute("UPDATE sessions SET revoked=1 WHERE user_id=?", (user_id,))


# --------------------------------------------------------------------------- #
# Account self-service
# --------------------------------------------------------------------------- #
def change_password(user_id: int, old: str, new: str, keep_token=None):
    with db.get_conn() as conn:
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not u or not verify_password(old or "", u["password_hash"]):
            return False, "Current password is incorrect."
        if old == new:
            return False, "Choose a new password that differs from the current one."
        bad = password_problems(new, u["username"], u["email"])
        if bad:
            return False, _pw_error(bad)
        conn.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE user_id=?",
                     (hash_password(new), user_id))
        revoke_user_sessions(conn, user_id)  # sign out everywhere else
        _audit(conn, "PASSWORD_CHANGED", u["username"], "User changed own password; all sessions revoked",
               db.user_label(_public(u)))
    return True, "Password changed. Please sign in again."


def set_theme(user_id: int, theme: str):
    if theme not in ("light", "dark"):
        return
    with db.get_conn() as conn:
        conn.execute("UPDATE users SET theme=? WHERE user_id=?", (theme, user_id))


# --------------------------------------------------------------------------- #
# Administration
# --------------------------------------------------------------------------- #
def list_users():
    return db._read("SELECT user_id, username, full_name, email, role, bureau, email_verified, is_active, "
                    "must_change_password, locked_until, created_at, last_login FROM users ORDER BY role, full_name")


def _admin_guard():
    return db._guard("users.manage")


def admin_create_user(username, full_name, email, role, bureau, password=None):
    """Admin creates a pre-verified account. Returns (ok, msg, temp_password|None)."""
    denied = _admin_guard()
    if denied:
        return False, denied, None
    username, full_name, email = db._clean(username), db._clean(full_name), db._clean(email).lower()
    errs = []
    if not _USERNAME_RE.match(username):
        errs.append("Username must be 3-32 characters, start with a letter, and use only letters, digits, . _ -")
    if not (2 <= len(full_name) <= 80):
        errs.append("Enter the full name.")
    if not _EMAIL_RE.match(email):
        errs.append("Enter a valid email address.")
    if role not in db.ROLES:
        errs.append("Select a valid role.")
    if role == "Bureau Officer" and bureau not in db.BUREAUS:
        errs.append("Bureau officers need a bureau.")
    if errs:
        return False, " ".join(errs), None
    temp = password or _temp_password()
    bad = password_problems(temp, username, email)
    if bad:
        return False, _pw_error(bad), None
    try:
        with db.get_conn() as conn:
            conn.execute("INSERT INTO users(username,email,full_name,password_hash,role,bureau,email_verified,"
                         "must_change_password,created_at) VALUES(?,?,?,?,?,?,1,1,?)",
                         (username, email, full_name, hash_password(temp), role,
                          bureau if role == "Bureau Officer" else None, db.now_str()))
            _audit(conn, "USER_CREATED", username, f"Created by admin as {role}"
                   + (f" ({bureau})" if role == "Bureau Officer" else ""), db.user_label(), None, role)
    except sqlite3.IntegrityError:
        return False, "That username or email already exists.", None
    return True, f"User {username} created. They must change the password at first sign-in.", temp


def _temp_password() -> str:
    return "Tmp-" + secrets.token_urlsafe(9) + "9a"


def _active_admins(conn, excluding=None) -> int:
    q = "SELECT COUNT(*) FROM users WHERE role='Admin' AND is_active=1" + (" AND user_id<>?" if excluding else "")
    return conn.execute(q, (excluding,) if excluding else ()).fetchone()[0]


def admin_update_user(user_id, role=None, bureau=None, is_active=None):
    denied = _admin_guard()
    if denied:
        return False, denied
    me = db.current_user()
    with db.get_conn() as conn:
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not u:
            return False, "User not found."
        new_role = role or u["role"]
        new_bureau = (bureau or u["bureau"]) if new_role == "Bureau Officer" else None
        new_active = u["is_active"] if is_active is None else int(bool(is_active))
        if new_role not in db.ROLES:
            return False, "Select a valid role."
        if new_role == "Bureau Officer" and new_bureau not in db.BUREAUS:
            return False, "Bureau officers need a bureau."
        if me and me["user_id"] == user_id and (new_role != u["role"] or not new_active):
            return False, "You cannot change your own role or deactivate yourself."
        if u["role"] == "Admin" and (new_role != "Admin" or not new_active) and _active_admins(conn, user_id) == 0:
            return False, "At least one active Admin must remain."
        changes = []
        if new_role != u["role"]:
            changes.append(("USER_ROLE_CHANGED", u["role"], new_role))
        if new_bureau != u["bureau"] and new_role == "Bureau Officer":
            changes.append(("USER_BUREAU_CHANGED", u["bureau"], new_bureau))
        if new_active != u["is_active"]:
            changes.append(("USER_ACTIVATED" if new_active else "USER_DEACTIVATED", u["is_active"], new_active))
        if not changes:
            return False, "No changes to save."
        conn.execute("UPDATE users SET role=?, bureau=?, is_active=? WHERE user_id=?",
                     (new_role, new_bureau, new_active, user_id))
        revoke_user_sessions(conn, user_id)  # permissions changed: force a fresh sign-in
        for action, a, b in changes:
            _audit(conn, action, u["username"], "Changed by admin; user's sessions revoked", db.user_label(), a, b)
    return True, f"Updated {u['username']}. Their active sessions were ended."


def admin_reset_password(user_id):
    denied = _admin_guard()
    if denied:
        return False, denied, None
    temp = _temp_password()
    with db.get_conn() as conn:
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not u:
            return False, "User not found.", None
        conn.execute("UPDATE users SET password_hash=?, must_change_password=1, failed_attempts=0, locked_until=NULL "
                     "WHERE user_id=?", (hash_password(temp), user_id))
        revoke_user_sessions(conn, user_id)
        _audit(conn, "PASSWORD_RESET_BY_ADMIN", u["username"], "Temporary password issued; change forced at next login",
               db.user_label())
    return True, f"Temporary password issued for {u['username']}.", temp


def force_change_password(user_id: int, new: str):
    """Used after an admin reset / first login: no old-password check (the user just proved the temp one)."""
    with db.get_conn() as conn:
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not u or not u["must_change_password"]:
            return False, "No password change is pending."
        bad = password_problems(new, u["username"], u["email"])
        if bad:
            return False, _pw_error(bad)
        if verify_password(new, u["password_hash"]):
            return False, "Choose a password different from the temporary one."
        conn.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE user_id=?",
                     (hash_password(new), user_id))
        _audit(conn, "PASSWORD_CHANGED", u["username"], "Password changed after reset/first login",
               db.user_label(_public(u)))
    return True, "Password updated."


def unlock_user(user_id):
    denied = _admin_guard()
    if denied:
        return False, denied
    with db.get_conn() as conn:
        u = conn.execute("SELECT username FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not u:
            return False, "User not found."
        conn.execute("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE user_id=?", (user_id,))
        _audit(conn, "ACCOUNT_UNLOCKED", u["username"], "Unlocked by admin", db.user_label())
    return True, f"{u['username']} unlocked."


# --------------------------------------------------------------------------- #
# Bootstrap / demo accounts
# --------------------------------------------------------------------------- #
DEMO_USERS = [
    ("admin", "System Administrator", "Admin", None),
    ("senior.anita", "Anita Deshmukh", "Senior Officer", None),
    ("approval.rohit", "Rohit Verma", "Bureau Officer", "Approval Bureau"),
    ("grievance.priya", "Priya Nair", "Bureau Officer", "Grievance Cell"),
    ("regulation.imran", "Imran Qureshi", "Bureau Officer", "Regulation Bureau"),
    ("finance.suresh", "Suresh Iyer", "Bureau Officer", "Finance Bureau"),
    ("quality.kavita", "Kavita Joshi", "Bureau Officer", "Examination/Quality Cell"),
    ("legal.manoj", "Manoj Pillai", "Bureau Officer", "Legal Cell"),
]


def seed_users():
    """Create accounts on a fresh database.

    Demo mode (default): the documented demo accounts, all with DEMO_PASSWORD.
    Production mode (NEXUS_DEMO_MODE=0): only 'admin', with NEXUS_ADMIN_PASSWORD or a random password printed once.
    """
    with db.get_conn() as conn:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return None
    if demo_mode():
        with db.get_conn() as conn:
            for username, name, role, bureau in DEMO_USERS:
                h = hash_password(DEMO_PASSWORD)  # fresh random salt per account
                conn.execute("INSERT INTO users(username,email,full_name,password_hash,role,bureau,email_verified,"
                             "created_at) VALUES(?,?,?,?,?,?,1,?)",
                             (username, f"{username}@aicte-nexus.example", name, h, role, bureau, db.now_str()))
            _audit(conn, "USERS_SEEDED", "demo", f"{len(DEMO_USERS)} synthetic demo accounts created", "System (seed)")
        return DEMO_PASSWORD
    pw = os.environ.get("NEXUS_ADMIN_PASSWORD") or ("Adm-" + secrets.token_urlsafe(12) + "7z")
    bad = password_problems(pw, "admin")
    if bad:
        raise RuntimeError("NEXUS_ADMIN_PASSWORD is too weak: " + _pw_error(bad))
    with db.get_conn() as conn:
        conn.execute("INSERT INTO users(username,email,full_name,password_hash,role,email_verified,created_at) "
                     "VALUES('admin',?,?,?,'Admin',1,?)",
                     (os.environ.get("NEXUS_ADMIN_EMAIL", "admin@aicte-nexus.example"), "System Administrator",
                      hash_password(pw), db.now_str()))
        _audit(conn, "USERS_SEEDED", "admin", "Initial administrator created", "System (seed)")
    if not os.environ.get("NEXUS_ADMIN_PASSWORD"):
        print(f"[AICTE NEXUS] Initial admin password (shown once): {pw}")
    return None
