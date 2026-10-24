"""Complaint Management: register, tracking, details, updates, reopen requests, new complaint, export."""
import datetime as dt

import streamlit as st

import auth
import database as db
import intelligence as intel
import ui

user = auth.require()
ui.page_header("Complaint Management",
               "Register, track and update complaints. Every change is recorded in the audit trail.")
actor = db.default_actor()
can = lambda perm: db.has_perm(perm, user)  # noqa: E731
all_df = db.list_complaints()
pending_n = len(db.list_reopen_requests("Pending"))
tab_reg, tab_new, tab_track, tab_reopen = st.tabs(
    ["Complaint register", "New complaint", "Track a complaint", f"Reopen requests ({pending_n} pending)"])

# ------------------------------------------------------------------ register + details
with tab_reg:
    with st.expander("Search and filters", expanded=True):
        r1 = st.columns([2, 1, 1])
        search = r1[0].text_input("Search ID, title, description or institution", key="cm_search")
        statuses = r1[1].multiselect("Status", db.STATUSES, key="cm_status")
        if user["role"] == "Bureau Officer":
            r1[2].markdown(f"**Bureau / cell**  \n{user['bureau']} (your bureau)")
            bureaus = []
        else:
            bureaus = r1[2].multiselect("Bureau / cell", db.BUREAUS, key="cm_bureau")
        r2 = st.columns(3)
        cats = r2[0].multiselect("Category", db.CATEGORIES, key="cm_cat")
        prios = r2[1].multiselect("Priority", db.PRIORITIES, key="cm_prio")
        states = r2[2].multiselect("State", sorted(all_df["state"].unique()) if not all_df.empty else [], key="cm_state")
        r3 = st.columns([2, 1, 1])
        lo = all_df["date_received"].min().date() if not all_df.empty else db.today()
        hi = max(all_df["date_received"].max().date(), db.today()) if not all_df.empty else db.today()
        with r3[0]:
            d_from, d_to = ui.date_range_filter("Date received", lo, hi, "cm_dates")
        only_over = r3[1].checkbox("Overdue only", key="cm_over")
        mine = r3[2].checkbox("Assigned to me", key="cm_mine", help="Cases where you are the assigned officer.")
    df = db.list_complaints({"search": search, "statuses": statuses, "bureaus": bureaus, "categories": cats,
                             "priorities": prios, "states": states, "date_from": d_from, "date_to": d_to,
                             "only_overdue": only_over,
                             "officers": [user["full_name"]] if mine else None})
    st.caption(f"{len(df)} of {len(all_df)} complaints · overdue = open and past due date "
               f"(grace period {db.get_settings()['overdue_grace_days']} day(s))")
    if df.empty:
        ui.empty_state("No complaints match these filters.", "Clear a filter or create a new complaint.")
    else:
        ui.show_table(ui.complaint_table_df(df))
        ui.export_button("Export filtered complaints to CSV", db.to_csv_bytes(df.drop(columns=["is_open"])),
                         "aicte_nexus_complaints.csv", "text/csv", key="cm_export", what="Filtered complaint register")

        st.markdown("### Complaint details")
        ids = df["complaint_id"].tolist()
        titles = dict(zip(df["complaint_id"], df["title"]))
        cid = st.selectbox("Open a complaint", ids, format_func=lambda i: f"{i} — {titles[i][:70]}", key="cm_sel")
        row = df[df["complaint_id"] == cid].iloc[0]
        c = db.get_complaint(cid)
        over = (f" {ui.badge(f'Overdue {int(row.days_overdue)} d', ui.DANGER)}" if row.is_overdue else "")
        n_reopen = c["reopen_count"]
        reopened = (" " + ui.badge(f"Reopened {n_reopen}×", ui.PURPLE)) if n_reopen else ""
        st.markdown(f"""<div class="nx-card"><h4>{ui.e(cid)} · {ui.e(c['title'])}</h4>
{ui.status_badge(c['status'])}{ui.priority_badge(c['priority'])}{over}{reopened}
<p class="nx-muted" style="margin:.6rem 0 0">{ui.e(c['institution_name'])} ({ui.e(c['institution_id'])}) · {ui.e(c['state'])}</p></div>""",
                    unsafe_allow_html=True)
        ui.status_stepper(c["status"])
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
            st.caption("No related complaints recorded. Officer-verified links from Cross-Bureau Intelligence appear here.")
        for r in refs:
            st.markdown(f"- {r} · manually referenced")
        for r in confirmed.itertuples():
            other = r.complaint_b if r.complaint_a == cid else r.complaint_a
            st.markdown(f"- {other} · verified related by {r.reviewed_by} (heuristic score {r.similarity_score:.2f})")

        t_time, t_notes, t_status, t_assign, t_due, t_res, t_ref, t_reopen, t_sim = st.tabs(
            ["Timeline", "Notes", "Update status", "Officer and priority", "Due date", "Resolution notes",
             "Add reference", "Reopen", "Similar cases"])
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
            is_done = c["status"] in db.TERMINAL_STATUSES
            options = [s for s in db.STATUSES if (s in db.TERMINAL_STATUSES) == is_done]
            if not can("complaint.close"):
                options = [s for s in options if s != "Closed"] or [c["status"]]
            if c["status"] not in options:
                options = [c["status"]] + options
            if is_done:
                st.info("This complaint is Resolved/Closed. To work on it again, use the **Reopen** tab.")
            if user["role"] == "Bureau Officer":
                st.caption("Bureau officers can set statuses up to Resolved. Closing a case is a senior-officer decision.")
            with st.form(f"status_{cid}"):
                new = st.selectbox("New status", options, index=options.index(c["status"]), key=f"ns_{cid}")
                cmt = st.text_input("Comment (saved in the audit trail)", max_chars=300, key=f"nsc_{cid}")
                rn = st.text_area("Resolution notes (required for Resolved or Closed)", value="",
                                  max_chars=3000, key=f"nsr_{cid}")
                if st.form_submit_button("Update status", type="primary"):
                    ui.result(*db.update_status(cid, new, cmt, rn, actor))
        with t_assign:
            a1, a2 = st.columns(2)
            if can("complaint.reassign"):
                with a1.form(f"assign_{cid}"):
                    officers = db.list_officers()
                    pick = st.selectbox("Assign to", officers, index=officers.index(c["assigned_officer"]), key=f"ao_{cid}")
                    other = st.text_input("…or enter a different officer name", max_chars=80, key=f"aoo_{cid}")
                    why = st.text_input("Reason", max_chars=300, key=f"aor_{cid}")
                    if st.form_submit_button("Reassign officer"):
                        ui.result(*db.assign_officer(cid, other.strip() or pick, why, actor))
            else:
                a1.info("Officer assignment is handled by Senior Officers and Admins.")
            if can("complaint.priority"):
                with a2.form(f"prio_{cid}"):
                    np_ = st.selectbox("Priority", db.PRIORITIES, index=db.PRIORITIES.index(c["priority"]), key=f"pp_{cid}")
                    why = st.text_input("Reason", max_chars=300, key=f"ppr_{cid}")
                    if st.form_submit_button("Change priority"):
                        ui.result(*db.change_priority(cid, np_, why, actor))
            else:
                a2.info("Priority changes are handled by Senior Officers and Admins.")
        with t_due:
            if can("complaint.due"):
                with st.form(f"due_{cid}"):
                    nd = st.date_input("New due date", value=db.parse_date(c["due_date"]),
                                       min_value=db.parse_date(c["date_received"]), key=f"dd_{cid}")
                    why = st.text_input("Reason for change", max_chars=300, key=f"ddr_{cid}")
                    if st.form_submit_button("Update due date"):
                        ui.result(*db.update_due_date(cid, nd, why, actor))
            else:
                st.info("Due-date changes are handled by Senior Officers and Admins.")
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
        with t_reopen:
            reqs = db.list_reopen_requests(complaint_id=cid)
            if not reqs.empty:
                ui.html_table(reqs, [("request_id", "#", "text"), ("requested_by", "Requested by", "text"),
                                     ("reason", "Reason", "text"), ("status", "Decision", "review"),
                                     ("decided_by", "Decided by", "text"), ("decision_note", "Note", "text")])
            if c["status"] not in db.TERMINAL_STATUSES:
                st.caption("Only Resolved or Closed complaints can be reopened.")
            elif not reqs.empty and (reqs["status"] == "Pending").any():
                st.info("A reopen request is already waiting for a senior officer's decision.")
            else:
                with st.form(f"reopen_{cid}"):
                    why = st.text_area("Why should this complaint be reopened? *", max_chars=1000, key=f"rr_{cid}",
                                       help="New evidence, repeat violation, incomplete resolution…")
                    b1, b2 = st.columns(2)
                    ask = b1.form_submit_button("Submit reopen request", type="primary")
                    direct = b2.form_submit_button("Reopen now (senior officers)", disabled=not can("complaint.reopen_decide"))
                if ask:
                    ui.result(*db.request_reopen(cid, why, actor))
                if direct:
                    ui.result(*db.reopen_now(cid, why, actor))
        with t_sim:
            st.caption("Textually similar complaints across all institutions and bureaus (TF-IDF). Suggestions only.")
            sim = intel.similar_cases(cid)
            if sim.empty:
                st.caption("No similar complaints found.")
            else:
                sim = sim.assign(same_institution=sim["same_institution"].map({True: "Same institution", False: "Other"}))
                ui.html_table(sim, [("complaint_id", "ID", "text"), ("institution_name", "Institution", "text"),
                                    ("bureau", "Bureau", "text"), ("title", "Title", "text"),
                                    ("status", "Status", "status"), ("similarity", "Similarity", "text"),
                                    ("shared_terms", "Shared terms", "text"), ("same_institution", "Scope", "text")])

# ------------------------------------------------------------------ new complaint
with tab_new:
    inst_opts = db.institution_options()
    officers = db.list_officers()
    st.caption("Fields marked * are required. The complaint ID is generated automatically and is unique "
               "(format CMP-YYYY-NNNN).")
    if user["role"] == "Bureau Officer":
        st.info(f"You can register complaints for your own bureau: **{user['bureau']}**.")
    with st.form("new_complaint"):
        n1 = st.columns(2)
        iid = n1[0].selectbox("Institution *", [i for i, _ in inst_opts], format_func=ui.inst_label(inst_opts))
        title = n1[1].text_input("Complaint title *", max_chars=200)
        desc = st.text_area("Complaint description *", max_chars=5000, height=140)
        n2 = st.columns(3)
        bureau_opts = [user["bureau"]] if user["role"] == "Bureau Officer" else db.BUREAUS
        bureau = n2[0].selectbox("Bureau / cell *", bureau_opts)
        cat = n2[1].selectbox("Category *", db.CATEGORIES)
        prio = n2[2].selectbox("Priority *", db.PRIORITIES, index=2)
        n3 = st.columns(3)
        officer = n3[0].selectbox("Assigned officer *", officers,
                                  index=officers.index(user["full_name"]) if user["full_name"] in officers else 0)
        received = n3[1].date_input("Date received *", value=db.today(), max_value=db.today())
        due = n3[2].date_input("Due date *", value=db.today() + dt.timedelta(days=db.SLA_DAYS["Medium"]))
        refs = st.multiselect("Related complaints (optional)", all_df["complaint_id"].tolist() if not all_df.empty else [])
        ok_submit = st.form_submit_button("Create complaint", type="primary")
    if ok_submit:
        ok, msg, new_id = db.create_complaint({
            "institution_id": iid, "title": title, "description": desc, "bureau": bureau, "category": cat,
            "priority": prio, "assigned_officer": officer, "date_received": received, "due_date": due,
            "related_refs": refs}, actor)
        if ok:
            intel.refresh_suggestions("System", log=False)  # let the new complaint be matched across bureaus
            msg += f" Track it with ID {new_id}."
        ui.result(ok, msg)

# ------------------------------------------------------------------ tracking
with tab_track:
    st.caption("Look up any complaint by its unique ID to see where it stands, who owns it and what happened so far.")
    tid = st.text_input("Complaint ID", placeholder="e.g. CMP-2026-0012", key="trk_id", max_chars=24).strip().upper()
    if tid:
        tc = db.get_complaint(tid)
        if not tc:
            st.error("No complaint with that ID was found in your scope.")
        else:
            trow = db.list_complaints({"search": tid})
            trow = trow[trow["complaint_id"] == tid]
            od = int(trow.iloc[0].days_overdue) if len(trow) else 0
            left = (db.parse_date(tc["due_date"]) - db.today()).days
            if tc["status"] in db.TERMINAL_STATUSES:
                sla = f"Resolved on {ui.fmt_date(tc['resolved_date'])}"
            elif od:
                sla = f"⚠️ {od} day(s) past the due date"
            else:
                sla = f"{left} day(s) left until the due date"
            st.markdown(f"""<div class="nx-card"><h4>{ui.e(tid)} · {ui.e(tc['title'])}</h4>
{ui.status_badge(tc['status'])}{ui.priority_badge(tc['priority'])}
<p class="nx-muted" style="margin:.6rem 0 0">{ui.e(tc['institution_name'])} · {ui.e(tc['bureau'])} ·
Assigned to <b>{ui.e(tc['assigned_officer'])}</b> · Submitted by {ui.e(tc.get('submitted_by') or '—')} · <b>{ui.e(sla)}</b></p></div>""",
                        unsafe_allow_html=True)
            ui.status_stepper(tc["status"])
            st.markdown("**History**")
            ui.timeline(db.get_timeline(tid))

# ------------------------------------------------------------------ reopen queue
with tab_reopen:
    st.caption("Resolved or Closed complaints can only return to work through a reopen request. "
               "A senior officer other than the requester decides; approval resets the due date from the priority SLA.")
    pend = db.list_reopen_requests("Pending")
    if pend.empty:
        ui.empty_state("No reopen requests are waiting.")
    for r in pend.itertuples():
        with st.expander(f"#{r.request_id} · {r.complaint_id} · {r.title} · requested by {r.requested_by}"):
            st.markdown(f"**Institution:** {r.institution_name} · **Bureau:** {r.bureau} · **Priority:** {r.priority}")
            st.markdown(f"**Reason given:** {r.reason}")
            if can("complaint.reopen_decide"):
                note = st.text_input("Decision note (required to reject)", key=f"rq_note_{r.request_id}", max_chars=300)
                b = st.columns(2)
                if b[0].button("Approve and reopen", type="primary", key=f"rq_ok_{r.request_id}"):
                    ui.result(*db.decide_reopen(r.request_id, True, note, actor))
                if b[1].button("Reject", key=f"rq_no_{r.request_id}"):
                    ui.result(*db.decide_reopen(r.request_id, False, note, actor))
            else:
                st.caption("Waiting for a Senior Officer or Admin to decide.")
    decided = db.list_reopen_requests(["Approved", "Rejected"])
    if not decided.empty:
        st.markdown("#### Decided requests")
        ui.html_table(decided.head(15), [("request_id", "#", "text"), ("complaint_id", "Complaint", "text"),
                                         ("requested_by", "Requested by", "text"), ("status", "Decision", "review"),
                                         ("decided_by", "Decided by", "text"), ("decision_note", "Note", "text")])
