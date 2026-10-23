"""Institution Directory: search, details with complaint history, add, edit, export."""
import plotly.express as px
import streamlit as st

import database as db
import ui

ui.page_header("Institution Directory",
               "Search institutions, review their complaint history across bureaus, and manage records.")
inst_all = db.list_institutions()
tab_dir, tab_detail, tab_add, tab_edit = st.tabs(["Directory", "Institution details", "Add institution",
                                                  "Edit institution"])

with tab_dir:
    c = st.columns([2, 1, 1])
    search = c[0].text_input("Search by institution name or ID", key="dir_search", placeholder="e.g. Satpura or INS-DEMO-025")
    states = c[1].multiselect("State", sorted(inst_all["state"].unique()), key="dir_states")
    types = c[2].multiselect("Institution type", db.INSTITUTION_TYPES, key="dir_types")
    df = db.list_institutions(search, states, types)
    st.caption(f"{len(df)} of {len(inst_all)} institutions · generated records are synthetic demonstration data")
    if df.empty:
        ui.empty_state("No institutions match your search.", "Try a different name, ID or clear the filters.")
    else:
        view = df.rename(columns={
            "institution_id": "ID", "name": "Institution", "state": "State", "district": "District",
            "institution_type": "Type", "approval_ref": "Approval ref (synthetic)",
            "contact_email": "Contact (synthetic)", "total_complaints": "Total",
            "open_complaints": "Open", "resolved_complaints": "Resolved",
            "last_complaint_date": "Last complaint"})
        view["Data"] = view.pop("is_synthetic").map({1: "Synthetic", 0: "User-added"})
        ui.show_table(view)
        st.download_button("Export institutions to CSV", db.to_csv_bytes(view), "aicte_nexus_institutions.csv",
                           "text/csv", key="dir_export")

with tab_detail:
    if inst_all.empty:
        ui.empty_state("No institutions yet.", "Add one in the next tab.")
    else:
        names = dict(zip(inst_all["institution_id"], inst_all["name"]))
        sel = st.selectbox("Select institution", list(names), format_func=lambda i: f"{names[i]} ({i})",
                           key="dir_detail_sel")
        inst = db.get_institution(sel)
        hist = db.list_complaints({"institution_ids": [sel]})
        tag = "Synthetic demonstration record" if inst["is_synthetic"] else "User-added record"
        st.markdown(f"""<div class="nx-card"><h4>{ui.e(inst['name'])}</h4>
<span class="nx-muted">{ui.e(inst['institution_type'])} · {ui.e(inst['district'])}, {ui.e(inst['state'])}<br>
Approval ref: {ui.e(inst['approval_ref'])} · Contact: {ui.e(inst['contact_email'])} · <i>{tag}</i></span></div>""",
                    unsafe_allow_html=True)
        k = st.columns(4)
        with k[0]: ui.kpi("Total complaints", len(hist), "", ui.BLUE)
        with k[1]: ui.kpi("Open", int(hist["is_open"].sum()) if len(hist) else 0, "", ui.CYAN)
        with k[2]: ui.kpi("Resolved / closed", int((~hist["is_open"]).sum()) if len(hist) else 0, "", ui.SUCCESS)
        with k[3]: ui.kpi("Bureaus involved", hist["bureau"].nunique() if len(hist) else 0, "", "#8B5CF6")
        if hist.empty:
            ui.empty_state("No complaints recorded for this institution.")
        else:
            nb = hist[hist["is_open"]]["bureau"].nunique()
            if nb > 1:
                ui.banner(f"<b>{nb} bureaus</b> currently hold open complaints for this institution. "
                          "Check the Cross-Bureau Intelligence page for suggested relationships.", "warn")
            g1, g2 = st.columns(2)
            with g1:
                s = hist["status"].value_counts().reindex(db.STATUSES).dropna().reset_index()
                s.columns = ["Status", "Complaints"]
                fig = px.bar(s, x="Status", y="Complaints", color="Status", color_discrete_map=ui.STATUS_COLORS)
                fig.update_layout(showlegend=False)
                ui.show_plot(ui.style_fig(fig, 280, "Status distribution"), key="dir_status_chart")
            with g2:
                b = hist["bureau"].value_counts().reset_index()
                b.columns = ["Bureau", "Complaints"]
                fig = px.bar(b, y="Bureau", x="Complaints", orientation="h", color_discrete_sequence=[ui.CYAN])
                ui.show_plot(ui.style_fig(fig, 280, "Bureau distribution"), key="dir_bureau_chart")
            st.markdown("#### Complete complaint history")
            hv = ui.complaint_table_df(hist)
            ui.show_table(hv)
            st.download_button("Export this history to CSV", db.to_csv_bytes(hv),
                               f"{sel}_complaint_history.csv", "text/csv", key="dir_hist_export")
        rel = db.list_relationships(institution_id=sel)
        if not rel.empty:
            st.markdown("#### Cross-bureau relationship suggestions")
            ui.html_table(rel, [("complaint_a", "Complaint A", "text"), ("bureau_a", "Bureau A", "text"),
                                ("complaint_b", "Complaint B", "text"), ("bureau_b", "Bureau B", "text"),
                                ("similarity_score", "Score", "text"), ("confidence", "Confidence", "confidence"),
                                ("review_status", "Review", "review")])

with tab_add:
    st.caption("New institutions are stored as user-added (non-synthetic) records.")
    with st.form("add_inst_form", clear_on_submit=False):
        a1, a2 = st.columns(2)
        iid = a1.text_input("Institution ID *", placeholder="INS-NEW-001", max_chars=24)
        name = a2.text_input("Institution name *", max_chars=200)
        a3, a4, a5 = st.columns(3)
        state = a3.selectbox("State *", db.STATES)
        district = a4.text_input("District *", max_chars=80)
        itype = a5.selectbox("Institution type *", db.INSTITUTION_TYPES)
        a6, a7 = st.columns(2)
        ref = a6.text_input("AICTE approval reference *", placeholder="AICTE/DEMO/2026/0001", max_chars=60)
        email = a7.text_input("Contact email *", placeholder="registrar@example.edu", max_chars=120)
        submitted = st.form_submit_button("Add institution", type="primary")
    if submitted:
        ok, msg = db.add_institution({"institution_id": iid, "name": name, "state": state, "district": district,
                                      "institution_type": itype, "approval_ref": ref, "contact_email": email},
                                     db.default_actor())
        ui.result(ok, msg)

with tab_edit:
    if inst_all.empty:
        ui.empty_state("No institutions to edit.")
    else:
        names = dict(zip(inst_all["institution_id"], inst_all["name"]))
        sel = st.selectbox("Institution to edit", list(names), format_func=lambda i: f"{names[i]} ({i})",
                           key="dir_edit_sel")
        cur = db.get_institution(sel)
        st.caption("The institution ID cannot be changed. Every change is recorded in the audit trail with its previous value.")
        with st.form(f"edit_inst_{sel}"):
            e1, e2 = st.columns(2)
            name = e1.text_input("Institution name *", value=cur["name"], max_chars=200, key=f"en_{sel}")
            district = e2.text_input("District *", value=cur["district"], max_chars=80, key=f"ed_{sel}")
            e3, e4 = st.columns(2)
            state = e3.selectbox("State *", db.STATES, index=db.STATES.index(cur["state"]) if cur["state"] in db.STATES else 0, key=f"es_{sel}")
            itype = e4.selectbox("Institution type *", db.INSTITUTION_TYPES,
                                 index=db.INSTITUTION_TYPES.index(cur["institution_type"]) if cur["institution_type"] in db.INSTITUTION_TYPES else 0,
                                 key=f"et_{sel}")
            e5, e6 = st.columns(2)
            ref = e5.text_input("AICTE approval reference *", value=cur["approval_ref"], key=f"er_{sel}")
            email = e6.text_input("Contact email *", value=cur["contact_email"], key=f"em_{sel}")
            saved = st.form_submit_button("Save changes", type="primary")
        if saved:
            ok, msg = db.update_institution(sel, {"name": name, "state": state, "district": district,
                                                  "institution_type": itype, "approval_ref": ref,
                                                  "contact_email": email}, db.default_actor())
            ui.result(ok, msg)
