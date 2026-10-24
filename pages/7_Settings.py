"""Settings: thresholds, demo user label, data reset, and the production-readiness checklist."""
import pandas as pd
import streamlit as st

import auth
import database as db
import intelligence as intel
import ui

user = auth.require("settings.write")

ui.page_header("Settings", "Configurable demo thresholds, demo data reset, and production-readiness guidance.")
s = db.get_settings()
t1, t2, t3, t4 = st.tabs(["Thresholds", "Data & backups", "Production readiness", "About this demo"])

with t1:
    st.caption("Changes are saved to the local database and recorded in the audit trail.")
    with st.form("settings_form"):
        vals = {}
        cols = st.columns(2)
        for n, (key, (label, typ, lo, hi, helptext)) in enumerate(db.SETTING_META.items()):
            with cols[n % 2]:
                if typ is int:
                    vals[key] = st.number_input(label, min_value=lo, max_value=hi, value=int(s[key]), step=1,
                                                help=helptext, key=f"set_{key}")
                elif typ is float:
                    vals[key] = st.number_input(label, min_value=float(lo), max_value=float(hi),
                                                value=float(s[key]), step=0.05, format="%.2f",
                                                help=helptext, key=f"set_{key}")
                else:
                    vals[key] = st.text_input(label, value=s[key], max_chars=hi, help=helptext, key=f"set_{key}")
        saved = st.form_submit_button("Save settings", type="primary")
    if saved:
        ok, msg = db.update_settings(vals, db.default_actor())
        if ok:
            intel.refresh_suggestions(db.default_actor())  # re-score pending suggestions with new thresholds
        ui.result(ok, msg)

with t2:
    st.markdown("#### Current database contents")
    counts = db.table_counts()
    ui.html_table(pd.DataFrame({"Table": list(counts), "Rows": list(counts.values())}),
                  [("Table", "Table", "text"), ("Rows", "Rows", "text")])
    st.markdown("#### Reset synthetic demo data")
    ui.banner("This <b>deletes all institutions, complaints, notes, relationship reviews and audit history</b>, including "
              "anything you created, and re-seeds fresh synthetic data. Settings are kept.", "warn")
    sure = st.checkbox("I understand that all current data will be permanently replaced", key="reset_ack")
    word = st.text_input("Type RESET to confirm", key="reset_word")
    if st.button("Reset demo data", disabled=not (sure and word.strip() == "RESET"), key="reset_btn"):
        with st.spinner("Re-seeding…"):
            ok, msg = db.reset_demo_data(confirm=True, actor=db.default_actor())
            if ok:
                intel.refresh_suggestions("System")
        for k in ("reset_ack", "reset_word"):
            st.session_state.pop(k, None)
        ui.result(ok, msg)

with t2:
    st.markdown("#### Database backups")
    st.caption("Online, consistent copies (SQLite backup API). The last 10 are kept in the backups folder next to the database.")
    if st.button("Create backup now", key="bk_now"):
        ui.result(*db.backup_database(db.default_actor()))
    bks = db.list_backups()
    if bks:
        ui.html_table(pd.DataFrame(bks), [("file", "File", "text"), ("created", "Created", "text"), ("size_kb", "Size (KB)", "text")])
    else:
        st.caption("No backups yet.")

with t3:
    st.markdown("""
This prototype is **not** production software. Before any real deployment the following are required:

| Area | Needed for production |
|---|---|
| Authentication | The app has its own login (scrypt hashes, lockout, email verification, server-side sessions). Production should use the organisation's identity provider (SSO + multi-factor) and a real mail service. |
| Authorisation | Admin / Senior / Bureau roles are enforced in the data layer. Production needs review against the organisation's actual access policy. |
| Encryption | TLS in transit; encryption at rest for the database and backups; managed secrets. |
| Data protection | Review of personal data in complaints, retention rules, and consent/legal basis. |
| Backups and recovery | Automated backups, tested restores, and a managed database (not a local SQLite file). |
| Logging and audit | Tamper-evident, centrally stored audit logs with restricted access and alerting. |
| Security testing | Threat modelling, dependency scanning, penetration testing and an independent review. |
| Compliance | Verification against applicable government security and data-protection requirements. **This demo makes no compliance claims.** |
| Model validation | Evaluate the matching method against real labelled cases before relying on it; keep officers in the loop. |
""")

with t4:
    st.markdown(f"""
- **Synthetic data:** all institutions, complaints, officers and approval references are fictional demonstration records.
  Institution names are invented and do not represent real verified entities. No AICTE system is accessed.
- **Database file:** `{db.DB_PATH}`
- **Audit:** append-only and hash-chained (tamper-evident), but still a local file.
- **Matching:** explainable heuristic prototype, offline, officer review required.
""")
