"""Executive overview: KPIs, charts and attention lists. Everything derives from the database."""
import pandas as pd
import plotly.express as px
import streamlit as st

import auth
import database as db
import intelligence as intel
import ui

user = auth.require()
all_df = db.list_complaints()
settings = db.get_settings()
pending = db.count_relationships("Pending")
open_all = all_df[all_df["is_open"]] if not all_df.empty else all_df
n_over = int(all_df["is_overdue"].sum()) if not all_df.empty else 0
n_crit = int((open_all["priority"] == "Critical").sum()) if not all_df.empty else 0

st.markdown(f"""
<div class="nx-hero">
  <span class="nx-pill">Prototype Demonstration — Synthetic Data</span>
  <h1>One Institution. Multiple Bureaus. One Unified View.</h1>
  <p>AICTE NEXUS brings institution-related complaints from every bureau and cell into a single dashboard,
  so officers can see the whole picture of an institution instead of a single file at a time.</p>
  <div class="nx-hero-grid">
    <div class="nx-hero-cell"><b>Why cross-bureau monitoring matters</b>
      <span>A fee complaint in Finance, a laboratory complaint in Regulation and a document issue in Approval may
      describe the same institution problem. Today each bureau sees only its own piece.</span></div>
    <div class="nx-hero-cell"><b>Needs attention now</b>
      <span><b style="display:inline;color:#EF4444">{n_over}</b> overdue ·
      <b style="display:inline;color:#EF4444">{n_crit}</b> critical open ·
      <b style="display:inline;color:#F59E0B">{pending}</b> cross-bureau suggestions awaiting officer review.</span></div>
    <div class="nx-hero-cell"><b>How officers track a case</b>
      <span>Find the institution, open its complaint history, update status or assignment, review linked cases,
      and see every change recorded in the audit trail.</span></div>
  </div>
</div>""", unsafe_allow_html=True)
ui.show_flash()
ui.alert_strip(intel.compute_alerts(all_df, settings, user["full_name"]))

with st.expander("Guided demo: scenarios you can run from the interface"):
    st.markdown("""
0. **Sign in** with different demo accounts (Admin, Senior Officer, a Bureau Officer) to see role-based access; try the 🌙 Dark mode switch.
1. **Institution Directory** → search an institution with complaints in several bureaus (e.g. *Satpura*, *Utkal*, *Narmada*).
2. Open **Institution details** to see its complete complaint history across bureaus.
3. **Cross-Bureau Intelligence** → open a High-confidence suggestion and read why the two complaints were matched.
4. Click **Mark as Related** or **Dismiss** (nothing is merged or closed automatically).
5. **Complaint Management** → select a complaint and update its status (resolution notes are required to resolve).
6. **Audit Trail** → filter by the complaint ID and see the status change and relationship decision recorded.
7. **Analytics & Reports** → apply filters and download the CSV exports.
""")

ui.banner("Filters apply to every KPI, chart and table below. All numbers are computed from the database"
          + (f" and limited to your bureau ({ui.e(user['bureau'])})." if user['role'] == 'Bureau Officer' else "."))
f = ui.global_filters("ov", all_df)
df = db.list_complaints(f)
if df.empty:
    ui.empty_state("No complaints match the current filters.", "Widen the date range or clear some filters.")
    st.stop()

opn = df[df["is_open"]]
k = st.columns(6)
with k[0]: ui.kpi("Total complaints", len(df), "in current filter", ui.BLUE)
with k[1]: ui.kpi("Open complaints", len(opn), "not yet resolved or closed", ui.CYAN)
with k[2]: ui.kpi("Resolved complaints", int((~df["is_open"]).sum()),
                  f"{int((df['status'] == 'Resolved').sum())} resolved · {int((df['status'] == 'Closed').sum())} closed", ui.SUCCESS)
with k[3]: ui.kpi("Overdue complaints", int(df["is_overdue"].sum()), "open and past due date", ui.DANGER)
with k[4]: ui.kpi("Institutions covered", df["institution_id"].nunique(), "with complaints in filter", "#8B5CF6")
with k[5]: ui.kpi("High-priority cases", int(opn["priority"].isin(["Critical", "High"]).sum()),
                  "open Critical or High", ui.WARNING)
st.write("")

c1, c2, c3 = st.columns(3)
with c1:
    s = df["status"].value_counts().reindex(db.STATUSES).dropna().reset_index()
    s.columns = ["Status", "Complaints"]
    fig = px.pie(s, names="Status", values="Complaints", hole=0.58, color="Status", color_discrete_map=ui.STATUS_COLORS)
    ui.show_plot(ui.style_fig(fig, 320, "Status distribution"), key="ov_status")
with c2:
    p = df["priority"].value_counts().reindex(db.PRIORITIES).fillna(0).reset_index()
    p.columns = ["Priority", "Complaints"]
    fig = px.bar(p, x="Priority", y="Complaints", color="Priority", color_discrete_map=ui.PRIORITY_COLORS)
    fig.update_layout(showlegend=False)
    ui.show_plot(ui.style_fig(fig, 320, "Priority distribution"), key="ov_prio")
with c3:
    done = df[(~df["is_open"]) & df["resolved_date"].notna()]
    if done.empty:
        st.markdown("**Resolution performance**")
        ui.empty_state("No resolved complaints in this filter.")
    else:
        on = int(done["resolved_on_time"].sum())
        r = pd.DataFrame({"Outcome": ["On time", "Late"], "Complaints": [on, len(done) - on]})
        fig = px.pie(r, names="Outcome", values="Complaints", hole=0.58, color="Outcome",
                     color_discrete_map={"On time": ui.SUCCESS, "Late": ui.DANGER})
        ui.show_plot(ui.style_fig(fig, 320, f"Resolution performance · avg {done['resolution_days'].mean():.0f} days"),
                     key="ov_res")

c4, c5 = st.columns([1, 1.2])
with c4:
    b = df.groupby(["bureau", "is_open"]).size().reset_index(name="Complaints")
    b["State"] = b["is_open"].map({True: "Open", False: "Resolved / closed"})
    fig = px.bar(b, y="bureau", x="Complaints", color="State", orientation="h",
                 color_discrete_map={"Open": ui.CYAN, "Resolved / closed": "#475569"})
    fig.update_layout(yaxis=dict(categoryorder="total ascending"))
    ui.show_plot(ui.style_fig(fig, 340, "Bureau-wise workload"), key="ov_bureau")
with c5:
    rec = df.groupby(df["date_received"].dt.to_period("M").dt.to_timestamp()).size().rename("Received")
    res = df[df["resolved_date"].notna()]
    res = res.groupby(res["resolved_date"].dt.to_period("M").dt.to_timestamp()).size().rename("Resolved")
    trend = pd.concat([rec, res], axis=1).fillna(0).sort_index()
    trend.index.name = "Month"
    fig = px.line(trend.reset_index(), x="Month", y=["Received", "Resolved"], markers=True,
                  color_discrete_map={"Received": ui.BLUE, "Resolved": ui.SUCCESS})
    ui.show_plot(ui.style_fig(fig, 340, "Monthly complaint trend"), key="ov_trend")

st.markdown("### Critical cases requiring attention")
crit = opn[opn["priority"].isin(["Critical", "High"])].copy()
crit["_p"] = crit["priority"].map({"Critical": 0, "High": 1})
crit = crit.sort_values(["_p", "days_overdue"], ascending=[True, False]).head(8)
ui.html_table(crit, [("complaint_id", "ID", "text"), ("institution_name", "Institution", "text"),
                     ("bureau", "Bureau", "text"), ("priority", "Priority", "priority"),
                     ("status", "Status", "status"), ("assigned_officer", "Officer", "text"),
                     ("due_date", "Due", "date"), ("days_overdue", "Overdue", "overdue")],
              "No open Critical or High cases in this filter.")

left, right = st.columns(2)
with left:
    st.markdown("### Overdue cases")
    od = df[df["is_overdue"]].sort_values("days_overdue", ascending=False).head(8)
    ui.html_table(od, [("complaint_id", "ID", "text"), ("institution_name", "Institution", "text"),
                       ("priority", "Priority", "priority"), ("due_date", "Due", "date"),
                       ("days_overdue", "Overdue", "overdue")], "No overdue cases in this filter.")
with right:
    st.markdown("### Recently updated complaints")
    ru = df.sort_values(["last_updated", "complaint_id"], ascending=False).head(8)
    ui.html_table(ru, [("complaint_id", "ID", "text"), ("title", "Title", "text"),
                       ("status", "Status", "status"), ("last_updated", "Updated", "date")])

st.markdown("### Recent system activity")
act = db.list_audit(limit=8)
ui.html_table(act, [("ts", "Time", "text"), ("action_type", "Action", "text"), ("entity_id", "Entity", "text"),
                    ("actor", "Actor", "text"), ("details", "Details", "text")], "No activity recorded yet.")
st.caption("Activity feed shows the latest audit events across the whole system (not filtered).")
