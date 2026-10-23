"""UI smoke test using a STUB of Streamlit and Plotly (neither needs to be installed).

It executes every page script end to end against a real temporary SQLite database, with scripted widget values
and button clicks, to catch NameErrors, bad DataFrame operations and broken wiring. It is NOT a visual test and
does not prove the pages render correctly in a real browser. Run:  python tests/ui_smoke_stub.py
"""
import os
import runpy
import sys
import tempfile
import types
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["NEXUS_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "ui.db")


class Rerun(Exception): pass
class Stop(Exception): pass


class SS(dict):
    __getattr__ = dict.get
    def __setattr__(self, k, v): self[k] = v


class Ctx:
    def __init__(self, st): self._st = st
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __getattr__(self, n): return getattr(self._st, n)


class FakeSt(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.reset()

    def reset(self):
        self.session_state = SS(); self.inputs = {}; self.clicks = set()
        self.errors, self.successes, self.dataframes, self.downloads, self.html = [], [], [], [], []

    def _in(self, label, key, default):
        for k in (key, label):
            if k is not None and k in self.inputs:
                return self.inputs[k]
        return default

    # layout
    def columns(self, spec, **kw): return [Ctx(self) for _ in range(spec if isinstance(spec, int) else len(spec))]
    def tabs(self, labels): return [Ctx(self) for _ in labels]
    def expander(self, *a, **k): return Ctx(self)
    def form(self, *a, **k): return Ctx(self)
    def spinner(self, *a, **k): return Ctx(self)
    @property
    def sidebar(self): return Ctx(self)
    # text
    def markdown(self, body, **k): self.html.append(str(body))
    def error(self, m, **k): self.errors.append(m)
    def success(self, m, **k): self.successes.append(m)
    # inputs
    def text_input(self, label, value="", key=None, **k): return self._in(label, key, value)
    def text_area(self, label, value="", key=None, **k): return self._in(label, key, value)
    def number_input(self, label, value=0, key=None, **k): return self._in(label, key, value)
    def checkbox(self, label, value=False, key=None, **k): return self._in(label, key, value)
    def date_input(self, label, value=None, key=None, **k): return self._in(label, key, value)
    def selectbox(self, label, options, index=0, format_func=str, key=None, **k):
        options = list(options)
        [format_func(o) for o in options]
        return self._in(label, key, options[index] if options else None)
    def multiselect(self, label, options, default=None, format_func=str, key=None, **k):
        [format_func(o) for o in options]
        return self._in(label, key, default or [])
    def button(self, label, key=None, disabled=False, **k):
        return (not disabled) and (label in self.clicks or key in self.clicks)
    form_submit_button = button
    def download_button(self, label, data, file_name=None, *a, **k):
        self.downloads.append((label, file_name, data)); return False
    # data
    def dataframe(self, df, *a, **k): self.dataframes.append(df)
    def plotly_chart(self, fig, *a, **k): pass
    # control
    def rerun(self): raise Rerun()
    def stop(self): raise Stop()
    def set_page_config(self, **k): pass
    def Page(self, *a, **k): return types.SimpleNamespace(args=a)
    def navigation(self, pages, **k): return types.SimpleNamespace(run=lambda: None, pages=pages)
    def __getattr__(self, n): return lambda *a, **k: None


st = FakeSt()
sys.modules["streamlit"] = st
for mod in ("plotly", "plotly.express", "plotly.graph_objects"):
    sys.modules[mod] = MagicMock()

import database as db  # noqa: E402
import intelligence as intel  # noqa: E402
import ui  # noqa: E402

PAGES = {n: os.path.join(ROOT, "pages", n) for n in sorted(os.listdir(os.path.join(ROOT, "pages"))) if n.endswith(".py")}
PASS = []


def run(path):
    try:
        runpy.run_path(path, run_name="__main__")
        return None
    except Rerun:
        return "rerun"
    except Stop:
        return "stop"


def check(name, cond):
    assert cond, "FAILED: " + name
    PASS.append(name); print("PASS", name)


db.init_db()
ui.bootstrap()
check("app.py runs", run(os.path.join(ROOT, "app.py")) is None)
for n, p in PAGES.items():
    st.reset()
    out = run(p)
    check(f"page loads: {n}", out in (None, "stop") and not st.errors)
st.reset()
check("overview exports no unescaped script tags", all("<script" not in h.lower() for h in st.html))

# Scenario 1: institution search
st.reset(); st.inputs = {"dir_search": "satpura"}
run(PAGES["1_Institution_Directory.py"])
check("scenario 1: directory search returns the institution", len(st.dataframes[0]) == 1)
check("scenario 1: directory CSV export offered", any(d[1] == "aicte_nexus_institutions.csv" for d in st.downloads))

# add institution via form
st.reset(); st.inputs = {"Institution ID *": "INS-UI-001", "Institution name *": "UI Test College",
                         "District *": "Indore", "AICTE approval reference *": "AICTE/DEMO/9",
                         "Contact email *": "x@y.example"}; st.clicks = {"Add institution"}
check("add-institution form saves (rerun)", run(PAGES["1_Institution_Directory.py"]) == "rerun")
check("added institution exists", db.get_institution("INS-UI-001") is not None)
st.reset(); st.inputs = {"Institution ID *": "INS-UI-001", "Institution name *": "Dup", "District *": "x",
                         "AICTE approval reference *": "r", "Contact email *": "x@y.example"}; st.clicks = {"Add institution"}
run(PAGES["1_Institution_Directory.py"])
check("duplicate institution shows an error", any("already exists" in e for e in st.errors))

# Scenario: create complaint
n0 = db.count_complaints()
st.reset(); st.inputs = {"Complaint title *": "UI smoke complaint", "Complaint description *": "Created from UI test"}
st.clicks = {"Create complaint"}
check("new-complaint form saves (rerun)", run(PAGES["2_Complaint_Management.py"]) == "rerun")
check("complaint count +1", db.count_complaints() == n0 + 1)
new_id = db.list_complaints({"search": "UI smoke complaint"}).iloc[0].complaint_id
st.reset(); st.clicks = {"Create complaint"}
run(PAGES["2_Complaint_Management.py"])
check("empty required fields show an error and save nothing", st.errors and db.count_complaints() == n0 + 1)

# Scenario 5: status update through the UI
st.reset(); st.inputs = {"cm_sel": new_id, f"ns_{new_id}": "Under Review", f"nsc_{new_id}": "ui test"}
st.clicks = {"Update status"}
check("status form saves (rerun)", run(PAGES["2_Complaint_Management.py"]) == "rerun")
check("status changed in DB", db.get_complaint(new_id)["status"] == "Under Review")
st.reset(); st.inputs = {"cm_sel": new_id, f"ns_{new_id}": "Resolved"}; st.clicks = {"Update status"}
run(PAGES["2_Complaint_Management.py"])
check("resolving without notes shows an error", any("Resolution notes" in e for e in st.errors))
st.reset(); st.inputs = {"cm_sel": new_id, f"note_text_{new_id}": "A note from the UI"}; st.clicks = {"Add note"}
check("note form saves (rerun)", run(PAGES["2_Complaint_Management.py"]) == "rerun")

# Scenario 3/4: review a suggestion
rid = int(db.list_relationships(review_statuses=["Pending"]).iloc[0].relationship_id)
st.reset(); st.clicks = {f"ci_rel_{rid}"}
check("Mark as Related button saves (rerun)", run(PAGES["3_Cross_Bureau_Intelligence.py"]) == "rerun")
check("relationship marked Related", db.list_relationships(review_statuses=["Related"]).relationship_id.eq(rid).any())
rid2 = int(db.list_relationships(review_statuses=["Pending"]).iloc[0].relationship_id)
st.reset(); st.clicks = {f"ci_dis_{rid2}"}
check("Dismiss button saves (rerun)", run(PAGES["3_Cross_Bureau_Intelligence.py"]) == "rerun")
st.reset(); st.clicks = {"Refresh suggestions"}
check("Refresh suggestions button works (rerun)", run(PAGES["3_Cross_Bureau_Intelligence.py"]) == "rerun")

# Scenario 6: audit trail shows the change
st.reset(); st.inputs = {"au_eid": new_id}
run(PAGES["6_Audit_Trail.py"])
check("audit page lists the status change", "STATUS_CHANGED" in set(st.dataframes[0]["Action"]))
st.reset(); st.inputs = {"au_actions": ["RELATIONSHIP_REVIEWED"]}
run(PAGES["6_Audit_Trail.py"])
check("audit page lists relationship reviews", len(st.dataframes[0]) >= 2)

# Scenario 7: exports
st.reset(); run(PAGES["5_Analytics_Reports.py"])
check("analytics offers 5 non-empty CSV exports", len(st.downloads) == 5 and all(len(d[2]) > 20 for d in st.downloads))
st.reset(); st.inputs = {"an_bureau": ["Finance Bureau"]}; run(PAGES["5_Analytics_Reports.py"])
all_rows = db.to_csv_bytes(db.list_complaints()).count(b"\n")
fin_rows = [d for d in st.downloads if d[1] == "complaints.csv"][0][2].count(b"\n")
check("analytics filters change the exported data", fin_rows < all_rows)
st.reset(); st.inputs = {"ov_bureau": ["Finance Bureau"]}; run(PAGES["0_Overview.py"])
check("overview filter bureau runs", not st.errors)

# Risk page + settings
st.reset(); run(PAGES["4_Risk_Monitoring.py"]); check("risk export offered", any(d[1] == "aicte_nexus_risk_cases.csv" for d in st.downloads))
st.reset(); st.inputs = {"set_inactivity_days": 30}; st.clicks = {"Save settings"}
check("settings save (rerun)", run(PAGES["7_Settings.py"]) == "rerun" and db.get_settings()["inactivity_days"] == "30")

# Reset requires confirmation
cnt = db.count_complaints()
st.reset(); st.clicks = {"Reset demo data"}; run(PAGES["7_Settings.py"])
check("reset button inert without confirmation", db.count_complaints() == cnt)
st.reset(); st.inputs = {"reset_ack": True, "reset_word": "nope"}; st.clicks = {"Reset demo data"}; run(PAGES["7_Settings.py"])
check("reset button inert with wrong confirmation word", db.count_complaints() == cnt)
st.reset(); st.inputs = {"reset_ack": True, "reset_word": "RESET"}; st.clicks = {"Reset demo data"}
check("reset with confirmation runs (rerun)", run(PAGES["7_Settings.py"]) == "rerun")
check("user-created data gone, demo data restored", db.get_complaint(new_id) is None and db.count_complaints() >= 60)
print(f"\nALL {len(PASS)} UI-STUB CHECKS PASSED")
