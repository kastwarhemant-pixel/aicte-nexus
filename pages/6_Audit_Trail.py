"""Audit trail viewer. Read-only: the application offers no way to edit or delete audit events."""
import datetime as dt

import streamlit as st

import auth
import database as db
import ui

user = auth.require()

ui.page_header("Audit Trail", "Chronological record of changes, decisions and settings updates.")
ui.banner("<b>Append-only, hash-chained log.</b> Database triggers block edits and deletes, and every event carries a "
          "SHA-256 hash of the previous one, so tampering is detectable. A local SQLite file is still <b>not a certified "
          "production audit system</b>. Resetting demo data clears the history.", "warn")
if user["role"] == "Bureau Officer":
    ui.banner("Showing your own actions and events on your bureau's complaints.", "info")
if db.has_perm("audit.verify", user):
    if st.button("Verify audit-log integrity", key="au_verify"):
        v = db.verify_audit_chain()
        if v["ok"]:
            st.success(f"Chain intact: {v['checked']} hashed events verified"
                       + (f" ({v['legacy_unchained']} older events pre-date hashing)." if v["legacy_unchained"] else "."))
        else:
            st.error(f"Tampering detected: the chain breaks at event #{v['first_bad_event']}.")

c = st.columns(3)
with c[0]:
    d_from, d_to = ui.date_range_filter("Date range", db.today() - dt.timedelta(days=400),
                                        db.today(), "au_dates")
actions = c[1].multiselect("Action type", db.audit_action_types(), key="au_actions")
etypes = c[2].multiselect("Entity type", ["Complaint", "Institution", "Relationship", "Setting", "System", "User", "Export"], key="au_etypes")
c2 = st.columns(2)
eid = c2[0].text_input("Entity ID contains", placeholder="e.g. CMP-2026-0012", key="au_eid")
text = c2[1].text_input("Details or actor contains", key="au_text")
df = db.list_audit(d_from, d_to, actions, etypes, eid, text, limit=3000)
st.caption(f"{len(df)} event(s) shown (newest first, max 3000)")
if df.empty:
    ui.empty_state("No audit events match these filters.")
else:
    view = df.rename(columns={"event_id": "Event ID", "ts": "Timestamp", "action_type": "Action",
                              "entity_type": "Entity type", "entity_id": "Entity ID",
                              "previous_value": "Previous value", "new_value": "New value",
                              "actor": "Actor", "details": "Details"})
    ui.show_table(view)
    ui.export_button("Export audit events to CSV", db.to_csv_bytes(view), "aicte_nexus_audit_trail.csv",
                     "text/csv", key="au_export", what="Audit trail")
