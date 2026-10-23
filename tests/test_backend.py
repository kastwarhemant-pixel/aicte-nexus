"""Backend tests (no Streamlit needed). Run:  python tests/test_backend.py   (or pytest)."""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp()
os.environ["NEXUS_DB_PATH"] = os.path.join(TMP, "test.db")

import sqlite3  # noqa: E402

import database as db  # noqa: E402
import intelligence as intel  # noqa: E402

db.init_db()
PASSED = []


def check(name, cond):
    assert cond, f"FAILED: {name}"
    PASSED.append(name)
    print("PASS", name)


# --- seed ---
c = db.table_counts()
check("seed: >=25 institutions", c["institutions"] >= 25)
check("seed: >=60 complaints", c["complaints"] >= 60)
df = db.list_complaints()
check("seed: multiple states/bureaus/statuses/priorities",
      df.state.nunique() >= 8 and df.bureau.nunique() == 6 and df.status.nunique() == 6 and df.priority.nunique() == 4)
check("seed: overdue cases exist", int(df.is_overdue.sum()) > 5)
before = db.table_counts()
db.init_db()
check("init_db does not reseed/destroy existing data", db.table_counts()["complaints"] == before["complaints"])

# --- institutions ---
check("institution search by name", len(db.list_institutions("satpura")) == 1)
check("institution search by id", len(db.list_institutions("INS-DEMO-025")) == 1)
check("institution search with % is literal (no wildcard abuse)", len(db.list_institutions("%")) == 0)
check("institution filter by state", (db.list_institutions(states=["Madhya Pradesh"]).state == "Madhya Pradesh").all())
ok, _ = db.add_institution(dict(institution_id="INS-NEW-001", name="Test College", state="Goa", district="Panaji",
                                institution_type="Polytechnic", approval_ref="AICTE/DEMO/1", contact_email="a@b.example"))
check("add institution", ok)
ok, msg = db.add_institution(dict(institution_id="INS-NEW-001", name="Dup", state="Goa", district="x",
                                  institution_type="Polytechnic", approval_ref="r", contact_email="a@b.example"))
check("duplicate institution ID rejected", (not ok) and "already exists" in msg)
ok, _ = db.add_institution(dict(institution_id="x", name="", state="Goa", district="", institution_type="Polytechnic",
                                approval_ref="", contact_email="bad"))
check("invalid institution rejected", not ok)
ok, _ = db.update_institution("INS-NEW-001", dict(name="Test College Renamed", state="Goa", district="Panaji",
                                                  institution_type="Polytechnic", approval_ref="AICTE/DEMO/1",
                                                  contact_email="a@b.example"))
check("edit institution", ok and db.get_institution("INS-NEW-001")["name"] == "Test College Renamed")
check("institution edit audited", len(db.list_audit(action_types=["INSTITUTION_UPDATED"], entity_id="INS-NEW-001")) == 1)

# --- complaints ---
base = dict(institution_id="INS-NEW-001", title="Test title", description="Test description", bureau="Finance Bureau",
            category="Financial Irregularities", priority="High", assigned_officer="Rohit Verma",
            date_received=db.today(), due_date=db.today())
ok, msg, cid = db.create_complaint(base)
check("create complaint", ok and cid.startswith("CMP-"))
ok2, msg2, cid2 = db.create_complaint({**base, "title": "Second"})
check("complaint IDs are unique", ok2 and cid2 != cid)
check("required title enforced", not db.create_complaint({**base, "title": "  "})[0])
check("required description enforced", not db.create_complaint({**base, "description": ""})[0])
check("invalid due date rejected", not db.create_complaint({**base, "due_date": "not-a-date"})[0])
check("due date before received rejected", not db.create_complaint({**base, "due_date": db.today() - __import__("datetime").timedelta(days=2)})[0])
check("unknown institution rejected", not db.create_complaint({**base, "institution_id": "NOPE"})[0])
check("SQL-injection-like text stored literally",
      db.create_complaint({**base, "title": "x'); DROP TABLE complaints;--"})[0] and db.count_complaints() > 60)
check("creation audited", len(db.list_audit(action_types=["COMPLAINT_CREATED"], entity_id=cid)) == 1)

check("same status rejected", not db.update_status(cid, "Submitted")[0])
check("resolving requires notes", not db.update_status(cid, "Resolved")[0])
ok, _ = db.update_status(cid, "Under Review", comment="start")
check("status change", ok and db.get_complaint(cid)["status"] == "Under Review")
a = db.list_audit(action_types=["STATUS_CHANGED"], entity_id=cid)
check("status change audited with prev/new", len(a) == 1 and a.iloc[0].previous_value == "Submitted" and a.iloc[0].new_value == "Under Review")
ok, _ = db.update_status(cid, "Resolved", resolution_notes="Fixed after inspection")
c1 = db.get_complaint(cid)
check("resolve with notes sets resolved_date", ok and c1["resolved_date"] == str(db.today()) and c1["resolution_notes"])
ok, _ = db.update_status(cid, "In Progress")
check("reopen clears resolved_date", ok and db.get_complaint(cid)["resolved_date"] is None)
check("priority change + audit", db.change_priority(cid, "Critical", "escalated")[0]
      and len(db.list_audit(action_types=["PRIORITY_CHANGED"], entity_id=cid)) == 1)
check("officer reassignment counted + audit", db.assign_officer(cid, "Priya Nair", "load")[0]
      and db.get_complaint(cid)["reassign_count"] == 1 and len(db.list_audit(action_types=["OFFICER_ASSIGNED"], entity_id=cid)) == 1)
check("same officer rejected", not db.assign_officer(cid, "Priya Nair")[0])
check("note added + audited", db.add_note(cid, "Called the registrar")[0] and len(db.list_notes(cid)) == 1
      and len(db.list_audit(action_types=["NOTE_ADDED"], entity_id=cid)) == 1)
check("empty note rejected", not db.add_note(cid, "  ")[0])
db.save_resolution_notes(cid, "v1 notes")
db.save_resolution_notes(cid, "v2 notes")
r = db.list_audit(action_types=["RESOLUTION_UPDATED"], entity_id=cid)
check("resolution overwrite preserves previous text in audit", "v1 notes" in set(r.previous_value.dropna()))
check("due date update + validation", db.update_due_date(cid, db.today() + __import__("datetime").timedelta(days=9))[0]
      and not db.update_due_date(cid, "2001-01-01")[0])
check("related reference both ways", db.add_related_reference(cid, cid2)[0]
      and cid in db.get_complaint(cid2)["related_refs"] and not db.add_related_reference(cid, cid2)[0])
tl = db.get_timeline(cid)
check("timeline has events", len(tl) >= 6)

# --- overdue ---
import datetime as dt  # noqa: E402
ok, _, oid = db.create_complaint({**base, "date_received": db.today() - dt.timedelta(days=30),
                                  "due_date": db.today() - dt.timedelta(days=10)})
row = db.list_complaints({"search": oid}).iloc[0]
check("overdue calculated: open + past due = 10 days", bool(row.is_overdue) and int(row.days_overdue) == 10)
with sqlite3.connect(db.DB_PATH) as cx:
    cx.execute("UPDATE complaints SET status='Closed', resolution_notes='x' WHERE complaint_id=?", (oid,))
row = db.list_complaints({"search": oid}).iloc[0]
check("closed complaints are never overdue", not bool(row.is_overdue))
db.update_settings({"overdue_grace_days": 15})
row = db.list_complaints({"search": cid2}).iloc[0]
check("settings change is audited", len(db.list_audit(action_types=["SETTINGS_CHANGED"])) == 1)
db.update_settings({"overdue_grace_days": 0})
check("invalid settings rejected", not db.update_settings({"match_min_score": 0.9, "match_medium_score": 0.4})[0]
      and not db.update_settings({"inactivity_days": -3})[0])

# --- filters ---
f = db.list_complaints({"statuses": ["Closed"], "bureaus": ["Finance Bureau"]})
check("complaint filters combine", (f.status == "Closed").all() and (f.bureau == "Finance Bureau").all())
check("search filter", len(db.list_complaints({"search": "laboratory"})) > 0)
check("date filter", len(db.list_complaints({"date_from": db.today(), "date_to": db.today()})) >= 3)

# --- cross-bureau matching ---
res = intel.refresh_suggestions("tester")
check("matching produces suggestions", res["candidates"] > 5 and db.count_relationships() > 5)
rel = db.list_relationships()
check("no duplicate pairs", len(rel) == len({(a, b) for a, b in zip(rel.complaint_a, rel.complaint_b)}))
check("pairs are same institution + different bureau", (rel.bureau_a != rel.bureau_b).all())
check("every suggestion has reasons and a label", rel.reasons.str.len().gt(10).all() and rel.confidence.isin(["High", "Medium", "Low"]).all())
check("High and Medium confidence bands reachable", set(rel.confidence) >= {"High", "Medium"})
n1 = db.count_relationships()
intel.refresh_suggestions("tester")
check("refresh is idempotent (no duplicates)", db.count_relationships() == n1)
top = rel.iloc[0]
ok, _ = db.review_relationship(int(top.relationship_id), "Related", "Same fee problem", "tester")
check("review: mark related", ok)
before_status = (db.get_complaint(top.complaint_a)["status"], db.get_complaint(top.complaint_b)["status"])
check("review does not change complaints", before_status == (top.status_a, top.status_b))
check("review audited", len(db.list_audit(action_types=["RELATIONSHIP_REVIEWED"],
                                         entity_id=f"{top.complaint_a}|{top.complaint_b}")) == 1)
intel.refresh_suggestions("tester")
check("refresh keeps reviewed decision", db.list_relationships(review_statuses=["Related"]).shape[0] == 1)
second = db.list_relationships(review_statuses=["Pending"]).iloc[0]
check("dismiss", db.review_relationship(int(second.relationship_id), "Dismissed", "unrelated", "tester")[0])
check("same decision twice rejected", not db.review_relationship(int(second.relationship_id), "Dismissed")[0])
check("active-only filter excludes terminal complaints",
      all(s not in db.TERMINAL_STATUSES for s in db.list_relationships(active_only=True)[["status_a", "status_b"]].to_numpy().ravel()))
check("confirmed link visible in timeline", len(db.get_timeline(top.complaint_a)) >= 2)

# --- risk ---
settings = db.get_settings()
risk = intel.compute_risk(db.list_complaints(), settings)
check("risk table non-empty with recommendations", len(risk) > 5 and risk.recommended_action.str.len().gt(5).all())
check("risk never includes closed cases", risk.status.isin(db.ACTIVE_STATUSES).all())
check("critical -> immediate review", (risk[risk.f_critical].recommended_action == "Immediate review by bureau head").all())

# --- exports ---
csv = db.to_csv_bytes(db.list_complaints()).decode("utf-8-sig")
check("CSV export has header + rows", csv.splitlines()[0].startswith("complaint_id") and len(csv.splitlines()) > 60)
import pandas as pd  # noqa: E402
evil = db.to_csv_bytes(pd.DataFrame({"x": ["=cmd|' /C calc'!A0", "ok", "-5+1"]})).decode("utf-8-sig")
check("CSV formula injection neutralised", "'=cmd" in evil and "'-5+1" in evil)

# --- audit append-only ---
with sqlite3.connect(db.DB_PATH) as cx:
    try:
        cx.execute("UPDATE audit_logs SET actor='hacker'")
        upd = True
    except sqlite3.DatabaseError:
        upd = False
    try:
        cx.execute("DELETE FROM audit_logs")
        dele = True
    except sqlite3.DatabaseError:
        dele = False
check("audit_logs UPDATE blocked", not upd)
check("audit_logs DELETE blocked", not dele)
with sqlite3.connect(db.DB_PATH) as cx:
    cx.execute("PRAGMA foreign_keys=ON")
    try:
        cx.execute("INSERT INTO complaints(complaint_id,institution_id,title,description,bureau,category,priority,status,assigned_officer,date_received,last_updated,due_date,status_changed_at) VALUES('X','NOPE','t','d','Legal Cell','Faculty Issues','Low','Submitted','o','2026-01-01','2026-01-01','2026-02-01','2026-01-01')")
        fk = True
    except sqlite3.IntegrityError:
        fk = False
check("foreign keys enforced", not fk)

# --- persistence across processes ---
snap = db.table_counts()
out = subprocess.run([sys.executable, "-c",
                      "import database as db;db.init_db();c=db.table_counts();print(c['complaints'],c['audit_logs'],c['complaint_relationships'])"],
                     cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True).stdout.split()
check("data persists after restart (new process)", out == [str(snap["complaints"]), str(snap["audit_logs"]), str(snap["complaint_relationships"])])
check("user-created complaint still present after restart", db.get_complaint(cid) is not None)

# --- reset ---
check("reset refused without confirmation", db.reset_demo_data()[0] is False and db.reset_demo_data(confirm="yes")[0] is False)
check("data intact after refused reset", db.get_complaint(cid) is not None)
ok, _ = db.reset_demo_data(confirm=True, actor="tester")
check("confirmed reset reseeds", ok and db.get_complaint(cid) is None and db.count_complaints() >= 60)
check("reset leaves a single audit marker", len(db.list_audit(action_types=["DEMO_DATA_RESET"])) == 1)
print(f"\nALL {len(PASSED)} BACKEND CHECKS PASSED")
