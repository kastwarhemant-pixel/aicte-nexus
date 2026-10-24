"""Auth, RBAC, reopen workflow, audit integrity, backup, migration and injection tests. Run: python tests/test_security_rbac.py"""
import datetime as dt
import os
import shutil
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp()
os.environ["NEXUS_DB_PATH"] = os.path.join(TMP, "sec.db")
os.environ["NEXUS_DEMO_MODE"] = "1"

import accounts as ac  # noqa: E402
import database as db  # noqa: E402
import intelligence as intel  # noqa: E402

PASS = []


def check(name, cond):
    assert cond, "FAILED: " + name
    PASS.append(name)
    print("PASS", name)


def login(username, pw=ac.DEMO_PASSWORD):
    ok, u, _ = ac.authenticate(username, pw)
    assert ok, username
    return u


db.init_db(); ac.seed_users(); intel.refresh_suggestions("System")

# ---------------- passwords
h = ac.hash_password("Str0ng!Pass")
check("scrypt hash verifies and is salted", ac.verify_password("Str0ng!Pass", h) and h != ac.hash_password("Str0ng!Pass")
      and h.startswith("scrypt$") and "Str0ng" not in h)
check("wrong password / garbage hash rejected", not ac.verify_password("nope", h) and not ac.verify_password("x", "junk"))
check("weak passwords rejected", all(ac.password_problems(p) for p in ("short1!", "alllowercase1!", "NoDigits!!", "NoSpecial11", "aaaaaaaa", "password123")))
check("strong password accepted", not ac.password_problems("Gr8!Passphrase", "bob", "bob@x.example"))
raw = sqlite3.connect(db.DB_PATH).execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
check("database stores only hashes", ac.DEMO_PASSWORD not in raw and raw.startswith("scrypt$"))

# ---------------- registration, email verification, lockout
ok, msg, code = ac.register_user("new.officer", "New Officer", "new@aicte-nexus.example", "Gr8!Passphrase", "Legal Cell")
check("registration returns a demo verification code", ok and code and len(code) == 6)
check("unverified user cannot sign in", not ac.authenticate("new.officer", "Gr8!Passphrase")[0])
check("wrong code rejected", not ac.verify_email("new.officer", "000000" if code != "000000" else "111111")[0])
check("correct code verifies", ac.verify_email("new.officer", code)[0])
u = login("new.officer", "Gr8!Passphrase")
check("self-registered user is a Bureau Officer only", u["role"] == "Bureau Officer" and u["bureau"] == "Legal Cell")
check("duplicate username/email blocked", not ac.register_user("NEW.officer", "X Y", "z@x.example", "Gr8!Passphrase", "Legal Cell")[0])
check("registration function has no role parameter", "role" not in ac.register_user.__code__.co_varnames[:ac.register_user.__code__.co_argcount])
for _ in range(5):
    ac.authenticate("approval.rohit", "wrong-Pass1!")
ok, _, msg = ac.authenticate("approval.rohit", ac.DEMO_PASSWORD)
check("account locks after 5 failures (even with right password)", not ok and "Too many" in msg)
db.set_current_user(login("admin"))
check("admin can unlock", ac.unlock_user([r for r in ac.list_users().itertuples() if r.username == "approval.rohit"][0].user_id)[0])
db.set_current_user(None)
check("unlocked user can sign in", ac.authenticate("approval.rohit", ac.DEMO_PASSWORD)[0])
check("login error does not reveal whether user exists",
      ac.authenticate("ghost.user", "x")[2] == ac.authenticate("admin", "x")[2])

# ---------------- sessions
user = login("senior.anita")
tok = ac.create_session(user["user_id"])
check("session validates", ac.validate_session(tok)["username"] == "senior.anita")
tokhash = sqlite3.connect(db.DB_PATH).execute("SELECT token_hash FROM sessions").fetchall()
check("only token hashes are stored", all(tok != r[0] for r in tokhash))
with db.get_conn() as conn:
    conn.execute("UPDATE sessions SET expires_at=?", ((dt.datetime.now() - dt.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),))
check("idle-expired session rejected", ac.validate_session(tok) is None)
tok2 = ac.create_session(user["user_id"]); ac.end_session(tok2, user)
check("logout revokes the session", ac.validate_session(tok2) is None)
check("forged token rejected", ac.validate_session("A" * 43) is None)

# ---------------- RBAC
admin, senior = login("admin"), login("senior.anita")
fin, legal = login("finance.suresh"), login("legal.manoj")
db.set_current_user(None)
total = len(db.list_complaints())
db.set_current_user(fin)
mine = db.list_complaints()
check("bureau officer sees only own bureau", 0 < len(mine) < total and set(mine.bureau) == {"Finance Bureau"})
check("bureau filter cannot widen scope", db.list_complaints({"bureaus": ["Legal Cell"]}).empty)
db.set_current_user(None)
foreign = db.list_complaints({"bureaus": ["Legal Cell"]}).iloc[0].complaint_id
fin_case = db.list_complaints({"bureaus": ["Finance Bureau"], "only_open": True}).iloc[0].complaint_id
db.set_current_user(fin)
check("bureau officer cannot open other bureau's complaint", db.get_complaint(foreign) is None)
check("…nor its notes/timeline", db.list_notes(foreign).empty and db.get_timeline(foreign).empty)
check("…nor update/add note on it", not db.update_status(foreign, "In Progress")[0] and not db.add_note(foreign, "hi")[0])
check("bureau officer cannot reassign / change priority / due date",
      not db.assign_officer(fin_case, "Priya Nair")[0] and not db.change_priority(fin_case, "Low")[0]
      and not db.update_due_date(fin_case, dt.date.today() + dt.timedelta(days=90))[0])
check("bureau officer cannot close, add institution, verify, reset, change settings",
      not db.update_status(fin_case, "Closed", resolution_notes="x")[0]
      and not db.add_institution({"institution_id": "INS-X-1"})[0]
      and not db.review_relationship(1, "Related")[0] and not db.reset_demo_data(True)[0]
      and not db.update_settings({"inactivity_days": 20})[0] and not db.backup_database()[0])
ok, _ = db.add_note(fin_case, "Own-bureau note")
check("bureau officer can note own bureau case and audit shows their name", ok and
      db.list_audit(action_types=["NOTE_ADDED"], entity_id=fin_case).iloc[0].actor == "Suresh Iyer (Bureau Officer)")
ok, _, _ = db.create_complaint({"institution_id": "INS-DEMO-001", "title": "t", "description": "d", "bureau": "Legal Cell",
                                "category": db.CATEGORIES[0], "priority": "Low", "assigned_officer": "Suresh Iyer",
                                "date_received": dt.date.today(), "due_date": dt.date.today() + dt.timedelta(days=9)})
check("bureau officer cannot create a complaint in another bureau", not ok)
ok, msg, new_id = db.create_complaint({"institution_id": "INS-DEMO-001", "title": "Own bureau", "description": "d",
                                       "bureau": "Finance Bureau", "category": db.CATEGORIES[3], "priority": "Low",
                                       "assigned_officer": "Suresh Iyer", "date_received": dt.date.today(),
                                       "due_date": dt.date.today() + dt.timedelta(days=9)})
check("…but can create in own bureau; submitted_by recorded", ok and db.get_complaint(new_id)["submitted_by"].startswith("Suresh Iyer"))
rel = db.list_relationships()
check("relationships limited to pairs touching own bureau",
      rel.empty or ((rel.bureau_a == "Finance Bureau") | (rel.bureau_b == "Finance Bureau")).all())
aud = db.list_audit(limit=5000)
db.set_current_user(None)
check("audit for bureau officer is scoped to own actions + own bureau", 0 < len(aud) < len(db.list_audit(limit=5000)))
db.set_current_user(fin)

# ---------------- reopen workflow
db.set_current_user(fin)
opens = list(db.list_complaints({"only_open": True}).complaint_id[:2])
for i in opens:
    assert db.update_status(i, "Resolved", "done", "Resolved after verification")[0]
cid, cid2 = opens
check("reopen needs a real reason", not db.request_reopen(cid, "short")[0])
check("bureau officer can request reopen", db.request_reopen(cid, "Institution resumed the violation after closure")[0])
check("duplicate pending request blocked", not db.request_reopen(cid, "Another reason that is long enough")[0])
rid = int(db.list_reopen_requests(complaint_id=cid).iloc[0].request_id)
check("bureau officer cannot decide", not db.decide_reopen(rid, True)[0])
db.set_current_user(senior)
check("reject needs a note", not db.decide_reopen(rid, False, "")[0])
ok, _ = db.decide_reopen(rid, True, "Evidence accepted")
c = db.get_complaint(cid)
check("senior approves: complaint Under Review, resolved date cleared, reopen counted, due date reset",
      ok and c["status"] == "Under Review" and c["resolved_date"] is None and c["reopen_count"] >= 1
      and db.parse_date(c["due_date"]) >= dt.date.today())
check("reopen events audited", {"REOPEN_REQUESTED", "REOPEN_APPROVED"} <= set(db.get_timeline(cid).action_type))
check("cannot decide twice", not db.decide_reopen(rid, True)[0])
db.set_current_user(senior)
check("senior cannot decide own request", db.request_reopen(cid2, "Senior raising a long enough reason")[0]
      and not db.decide_reopen(int(db.list_reopen_requests(complaint_id=cid2).iloc[0].request_id), True)[0])
db.set_current_user(admin)
check("admin can approve it", db.decide_reopen(int(db.list_reopen_requests(complaint_id=cid2).iloc[0].request_id), True)[0])

# ---------------- admin user management
db.set_current_user(admin)
ok, msg, temp = ac.admin_create_user("temp.user", "Temp User", "temp@aicte-nexus.example", "Bureau Officer", "Legal Cell")
check("admin creates user with temp password", ok and temp)
tu = login("temp.user", temp)
check("temp-password user must change it", tu["must_change_password"] == 1 and ac.force_change_password(tu["user_id"], "N3w!Passphrase")[0]
      and ac.authenticate("temp.user", "N3w!Passphrase")[0])
check("admin cannot deactivate/demote self", not ac.admin_update_user(admin["user_id"], is_active=False)[0]
      and not ac.admin_update_user(admin["user_id"], role="Senior Officer")[0])
db.set_current_user(fin)
check("non-admin cannot manage users", not ac.admin_create_user("x.y.z", "Xyz", "x@y.example", "Admin", None)[0]
      and not ac.admin_reset_password(1)[0])
db.set_current_user(admin)
uid = [r for r in ac.list_users().itertuples() if r.username == "temp.user"][0].user_id
t3 = ac.create_session(uid)
check("role change revokes sessions", ac.admin_update_user(int(uid), role="Senior Officer")[0] and ac.validate_session(t3) is None)
check("deactivated user cannot sign in", ac.admin_update_user(int(uid), is_active=False)[0] and not ac.authenticate("temp.user", "N3w!Passphrase")[0])

# ---------------- audit integrity
db.set_current_user(None)
v = db.verify_audit_chain()
check("audit chain intact", v["ok"] and v["checked"] > 100)
check("audit events cover logins and user admin",
      {"LOGIN_SUCCESS", "LOGIN_FAILED", "ACCOUNT_LOCKED", "USER_CREATED", "USER_ROLE_CHANGED", "LOGOUT"} <= set(db.audit_action_types()))
try:
    with db.get_conn() as conn:
        conn.execute("DELETE FROM audit_logs WHERE event_id=1")
    blocked = False
except sqlite3.DatabaseError:
    blocked = True
check("triggers still block audit deletes", blocked)
con = sqlite3.connect(db.DB_PATH)
con.execute("DROP TRIGGER trg_audit_no_update"); con.execute("UPDATE audit_logs SET details='tampered' WHERE event_id=(SELECT MAX(event_id)-3 FROM audit_logs)")
con.commit(); con.close()
v = db.verify_audit_chain()
check("tampering with a row is detected by the hash chain", not v["ok"] and v["first_bad_event"])

# ---------------- injection / XSS
db.init_db()
payload = "'; DROP TABLE complaints; --"
db.list_complaints({"search": payload}); db.list_institutions(payload); db.list_audit(search=payload, entity_id=payload)
check("SQL injection strings are inert", db.count_complaints() > 50)
check("login rejects injection and survives", not ac.authenticate("admin' OR '1'='1", "x' OR '1'='1")[0])

# ---------------- XSS escaping helper (ui needs a Streamlit stand-in)
from unittest.mock import MagicMock  # noqa: E402
sys.modules.setdefault("streamlit", MagicMock())
import ui  # noqa: E402
check("ui.e escapes script tags", "<script>" not in ui.e("<script>alert(1)</script>") and "&lt;script&gt;" in ui.e("<script>x</script>"))
check("badges escape their text", "<img" not in ui.badge('<img src=x onerror=1>', "#2563EB"))

# ---------------- backup + migration
db.set_current_user(admin)
ok, msg = db.backup_database()
check("admin backup creates a readable copy", ok and db.list_backups() and sqlite3.connect(os.path.join(db.BACKUP_DIR, db.list_backups()[0]["file"])).execute("SELECT COUNT(*) FROM complaints").fetchone()[0] > 50)
db.set_current_user(None)
old = os.path.join(TMP, "old.db"); shutil.copy(os.path.join(ROOT, "tests", "fixtures", "legacy_nexus.db"), old)
db.DB_PATH = old
db.init_db()
cols = {r[1] for r in sqlite3.connect(old).execute("PRAGMA table_info(complaints)")}
check("legacy database migrates in place without data loss", {"submitted_by", "reopen_count"} <= cols and db.count_complaints() == 76)
ac.seed_users()
check("legacy DB gets users and a working audit chain", len(ac.list_users()) >= 8 and db.verify_audit_chain()["ok"])

# ---------------- alerts
s_ = db.get_settings()
a = intel.compute_alerts(db.list_complaints(), s_, "Anita Deshmukh")
check("alerts count overdue, critical and due-soon", a["overdue"] > 0 and a["critical"] > 0 and a["due_soon"] >= 1 and len(a["items"]) > 0)
print(f"\nALL {len(PASS)} SECURITY/RBAC CHECKS PASSED")
