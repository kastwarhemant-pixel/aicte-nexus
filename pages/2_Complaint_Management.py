"""Complaint Management: register, details view, updates, timeline, new complaint, export."""
import datetime as dt

import streamlit as st

import database as db
import ui

ui.page_header("Complaint Management",
               "Search, review and update complaints. Every change is recorded in the audit trail.")
actor = db.default_actor()
all_df = db.list_complaints()
tab_reg, tab_new = st.tabs(["Complaint register", "New complaint"])

with tab_reg:
    with st.expander("Search and filters", expanded=True):
        r1 = st.columns([2, 1, 1])
        search = r1[0].text_input("Search ID, title, description or institution", key="cm_search")
        statuses = r1[1].multiselect("Status", db.STATUSES, key="cm_status")
        bureaus = r1[2].multiselect("Bureau / cell", db.BUREAUS, key="cm_bureau")
        r2 = st.columns(3)
        cats = r2[0].multiselect("Category", db.CATEGORIES, key="cm_cat")
        prios = r2[1].multiselect("Priority", db.PRIORITIES, key="cm_prio")
        states = r2[2].multiselect("State", sorted(all_df["state"].unique()) if not all_df.empty else [], key="cm_state")
        r3 = st.columns([2, 1])
        lo = all_df["date_received"].min().date() if not all_df.empty else db.today()
        hi = max(all_df["date_received"].max().date(), db.today()) if not all_df.empty else db.today()
        with r3[0]:
            d_from, d_to = ui.date_range_filter("Date received", lo, hi, "cm_dates")
        only_over = r3[1].checkbox("Overdue only", key="cm_over")
    df = db.list_complaints({"search": search, "statuses": statuses, "bureaus": bureaus, "categories": cats,
                             "priorities": prios, "states": states, "date_from": d_from, "date_to": d_to,
                             "only_overdue": only_over})
    st.caption(f"{len(df)} of {len(all_df)} complaints · overdue = open and past due date "
               f"(grace period {db.get_settings()['overdue_grace_days']} day(s))")
    if df.empty:
        ui.empty_state("No complaints match these filters.", "Clear a filter or create a new complaint.")
    else:
        view = ui.complaint_table_df(df)
        ui.show_table(view)
        st.download_button("Export filtered complaints to CSV", db.to_csv_bytes(df.drop(columns=["is_open"])),
                           "aicte_nexus_complaints.csv", "text/csv", key="cm_export")

        st.markdown("### Complaint details")
        ids = df["complaint_id"].tolist()
        titles = dict(zip(df["complaint_id"], df["title"]))
        cid = st.selectbox("Open a complaint", ids, format_func=lambda i: f"{i} — {titles[i][:70]}", key="cm_sel")
        row = df[df["complaint_id"] == cid].iloc[0]
        c = db.get_complaint(cid)
        over = (f" {ui.badge(f'Overdue {int(row.days_overdue)} d', ui.DANGER)}" if row.is_overdue else "")
        st.markdown(f"""<div class="nx-card"><h4>{ui.e(cid)} · {ui.e(c['title'])}</h4>
{ui.status_badge(c['status'])}{ui.priority_badge(c['priority'])}{over}
<p class="nx-muted" style="margin:.6rem 0 0">{ui.e(c['institution_name'])} ({ui.e(c['institution_id'])}) · {ui.e(c['state'])}</p></div>""",
                    unsafe_allow_html=True)
        g = st.columns(4)
        g[0].markdown(f"**Bureau / cell**  \n{c['bureau']}")
        g[1].markdown(f"**Category**  \n{c['category']}")
        g[2].markdown(f"**Assigned officer**  \n{c['assigned_officer']}  \n<span class='nx-muted'>reassigned {c['reassign_count']}×</span>",
                      unsafe_allow_html=True)
        g[3].markdown(f"**Due date**  \n{ui.fmt_date(c['due_date'])}")
        g2 = st.columns(4)
        g2[0].markdown(f"**Received**  \n{ui.fmt_date(c['date_received'])}")
        g2[1].markdown(f"**Last updated**  \n{ui.fmt_date(c['last_updated'])}")
        g2[2].markdown(f"**Resolved on**  \n{ui.fmt_date(c['resolved_date'])}")
        g2[3].markdown(f"**Days overdue**  \n{int(row.days_overdue)}")
        st.markdown("**Description**")
        st.markdown(f'<div class="nx-card">{ui.e(c["description"])}</div>', unsafe_allow_html=True)
        if c["resolution_notes"]:
            st.markdown("**Resolution notes**")
            st.markdown(f'<div class="nx-card">{ui.e(c["resolution_notes"])}</div>', unsafe_allow_html=True)

        refs = [r for r in c["related_refs"].split(",") if r]
        confirmed = db.list_relationships(review_statuses=["Related"], complaint_ids=[cid])
        st.markdown("**Related complaints**")
        if not refs and confirmed.empty:
            st.caption("No related complaints recorded. Officer-confirmed links from Cross-Bureau Intelligence appear here.")
        for r in refs:
            st.markdown(f"- {r} · manually referenced")
        for r in confirmed.itertuples():
            other = r.complaint_b if r.complaint_a == cid else r.complaint_a
            st.markdown(f"- {other} · confirmed related by {r.reviewed_by} (heuristic score {r.similarity_score:.2f})")

        t_time, t_notes, t_status, t_assign, t_due, t_res, t_ref = st.tabs(
            ["Timeline", "Notes", "Update status", "Officer and priority", "Due date", "Resolution notes",
             "Add reference"])
        with t_time:
            ui.timeline(db.get_timeline(cid))
        with t_notes:
            notes = db.list_notes(cid)
            if notes.empty:
                st.caption("No notes yet.")
            for n in notes.itertuples():
                st.markdown(f'<div class="nx-card"><span class="nx-muted">{ui.e(n.note_type)} · {ui.e(n.author)} · {ui.e(n.created_at)}</span><br>{ui.e(n.note)}</div>',
                            unsafe_allow_html=True)
            with st.form(f"note_{cid}", clear_on_submit=True):
                text = st.text_area("Add internal note", max_chars=3000, key=f"note_text_{cid}")
                if st.form_submit_button("Add note"):
                    ui.result(*db.add_note(cid, text, "Internal Note", actor))
        with t_status:
            with st.form(f"status_{cid}"):
                new = st.selectbox("New status", db.STATUSES, index=db.STATUSES.index(c["status"]), key=f"ns_{cid}")
                cmt = st.text_input("Comment (saved in the audit trail)", max_chars=300, key=f"nsc_{cid}")
                rn = st.text_area("Resolution notes (required for Resolved or Closed)", value="",
                                  max_chars=3000, key=f"nsr_{cid}")
                if st.form_submit_button("Update status", type="primary"):
                    ui.result(*db.update_status(cid, new, cmt, rn, actor))
        with t_assign:
            a1, a2 = st.columns(2)
            with a1.form(f"assign_{cid}"):
                officers = db.list_officers()
                pick = st.selectbox("Assign to", officers, index=officers.index(c["assigned_officer"]), key=f"ao_{cid}")
                other = st.text_input("…or enter a different officer name", max_chars=80, key=f"aoo_{cid}")
                why = st.text_input("Reason", max_chars=300, key=f"aor_{cid}")
                if st.form_submit_button("Reassign officer"):
                    ui.result(*db.assign_officer(cid, other.strip() or pick, why, actor))
            with a2.form(f"prio_{cid}"):
                np_ = st.selectbox("Priority", db.PRIORITIES, index=db.PRIORITIES.index(c["priority"]), key=f"pp_{cid}")
                why = st.text_input("Reason", max_chars=300, key=f"ppr_{cid}")
                if st.form_submit_button("Change priority"):
                    ui.result(*db.change_priority(cid, np_, why, actor))
        with t_due:
            with st.form(f"due_{cid}"):
                nd = st.date_input("New due date", value=db.parse_date(c["due_date"]),
                                   min_value=db.parse_date(c["date_received"]), key=f"dd_{cid}")
                why = st.text_input("Reason for change", max_chars=300, key=f"ddr_{cid}")
                if st.form_submit_button("Update due date"):
                    ui.result(*db.update_due_date(cid, nd, why, actor))
        with t_res:
            st.caption("Saving replaces the current notes; the previous text stays preserved in the audit event.")
            with st.form(f"res_{cid}"):
                txt = st.text_area("Resolution notes", value=c["resolution_notes"], max_chars=3000, key=f"rs_{cid}")
                if st.form_submit_button("Save resolution notes"):
                    ui.result(*db.save_resolution_notes(cid, txt, actor))
        with t_ref:
            with st.form(f"ref_{cid}"):
                options = [i for i in all_df["complaint_id"] if i != cid]
                other = st.selectbox("Related complaint", options, key=f"rf_{cid}")
                if st.form_submit_button("Add reference"):
                    ui.result(*db.add_related_reference(cid, other, actor))

with tab_new:
    inst_opts = db.institution_options()
    officers = db.list_officers()
    st.caption("Fields marked * are required. The complaint ID is generated automatically and is unique.")
    with st.form("new_complaint"):
        n1 = st.columns(2)
        iid = n1[0].selectbox("Institution *", [i for i, _ in inst_opts], format_func=ui.inst_label(inst_opts))
        title = n1[1].text_input("Complaint title *", max_chars=200)
        desc = st.text_area("Complaint description *", max_chars=5000, height=140)
        n2 = st.columns(3)
        bureau = n2[0].selectbox("Bureau / cell *", db.BUREAUS)
        cat = n2[1].selectbox("Category *", db.CATEGORIES)
        prio = n2[2].selectbox("Priority *", db.PRIORITIES, index=2)
        n3 = st.columns(3)
        officer = n3[0].selectbox("Assigned officer *", officers)
        received = n3[1].date_input("Date received *", value=db.today(), max_value=db.today())
        due = n3[2].date_input("Due date *", value=db.today() + dt.timedelta(days=db.SLA_DAYS["Medium"]))
        refs = st.multiselect("Related complaints (optional)", all_df["complaint_id"].tolist() if not all_df.empty else [])
        ok_submit = st.form_submit_button("Create complaint", type="primary")
    if ok_submit:
        ok, msg, new_id = db.create_complaint({
            "institution_id": iid, "title": title, "description": desc, "bureau": bureau, "category": cat,
            "priority": prio, "assigned_officer": officer, "date_received": received, "due_date": due,
            "related_refs": refs}, actor)
        ui.result(ok, msg)
