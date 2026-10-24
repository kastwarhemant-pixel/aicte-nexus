"""Overdue and risk monitoring: flagged open complaints with recommended (never automatic) next actions."""
import plotly.express as px
import streamlit as st

import auth
import database as db
import intelligence as intel
import ui

user = auth.require()

ui.page_header("Risk Monitoring",
               "Open complaints that are overdue, inactive, high priority, repeatedly reassigned or waiting too long.")
settings = db.get_settings()
ui.banner("Recommendations are suggestions for officers only. No action is taken automatically. "
          "Thresholds are demo values and can be changed in Settings.")
st.caption(f"Thresholds · overdue grace {settings['overdue_grace_days']} d · inactive ≥ {settings['inactivity_days']} d · "
           f"awaiting information ≥ {settings['awaiting_info_days']} d · reassigned ≥ {settings['reassignment_threshold']}×")

df = db.list_complaints()
ui.alert_strip(intel.compute_alerts(df, settings, user["full_name"]))
risk = intel.compute_risk(df, settings)
if risk.empty:
    ui.empty_state("No complaints are currently flagged.", "Everything open is within the configured thresholds.")
    st.stop()

k = st.columns(6)
with k[5]: ui.kpi("Due soon", int(risk["f_due_soon"].sum()), f"within {settings['due_soon_days']} day(s)", ui.CYAN)
with k[0]: ui.kpi("Critical open", int(risk["f_critical"].sum()), "immediate review", ui.DANGER)
with k[1]: ui.kpi("Overdue", int(risk["f_overdue"].sum()), "past due date", "#F97316")
with k[2]: ui.kpi("Inactive", int(risk["f_inactive"].sum()), "no recent update", ui.WARNING)
with k[3]: ui.kpi("Awaiting info too long", int(risk["f_awaiting"].sum()), "follow up", ui.CYAN)
with k[4]: ui.kpi("Repeated reassignment", int(risk["f_reassigned"].sum()), "ownership review", "#8B5CF6")
st.write("")

c = st.columns(4)
flag = c[0].selectbox("Flag", ["All flagged", "Critical", "Overdue", "Inactive", "Due soon", "Awaiting information", "Reassigned"], key="rk_flag")
bureaus = c[1].multiselect("Bureau / cell", db.BUREAUS, key="rk_bureau")
prios = c[2].multiselect("Priority", db.PRIORITIES, key="rk_prio")
officers = c[3].multiselect("Officer", sorted(risk["assigned_officer"].unique()), key="rk_off")
col = {"Critical": "f_critical", "Overdue": "f_overdue", "Inactive": "f_inactive", "Due soon": "f_due_soon",
       "Awaiting information": "f_awaiting", "Reassigned": "f_reassigned"}.get(flag)
view = risk
if col: view = view[view[col]]
if bureaus: view = view[view["bureau"].isin(bureaus)]
if prios: view = view[view["priority"].isin(prios)]
if officers: view = view[view["assigned_officer"].isin(officers)]

if view.empty:
    ui.empty_state("No flagged complaints match these filters.")
else:
    st.markdown(f"### {len(view)} flagged complaint(s)")
    ui.html_table(view, [("complaint_id", "ID", "text"), ("institution_name", "Institution", "text"),
                         ("bureau", "Bureau", "text"), ("assigned_officer", "Officer", "text"),
                         ("priority", "Priority", "priority"), ("status", "Status", "status"),
                         ("due_date", "Due", "date"), ("days_overdue", "Days overdue", "overdue"), ("days_to_due", "Days to due", "text"),
                         ("last_updated", "Last updated", "date"), ("risk_flags", "Flags", "text"),
                         ("recommended_action", "Recommended next action", "text")])
    a = view["recommended_action"].value_counts().reset_index()
    a.columns = ["Recommended action", "Complaints"]
    fig = px.bar(a, y="Recommended action", x="Complaints", orientation="h", color_discrete_sequence=[ui.CYAN])
    fig.update_layout(yaxis=dict(categoryorder="total ascending"))
    ui.show_plot(ui.style_fig(fig, 280, "Recommended actions needed"), key="rk_actions")
    export = view[intel.RISK_COLUMNS].copy()
    ui.export_button("Export overdue and risk cases to CSV", db.to_csv_bytes(export),
                     "aicte_nexus_risk_cases.csv", "text/csv", key="rk_export", what="Risk cases")
