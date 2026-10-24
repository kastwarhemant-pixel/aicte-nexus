"""Analytics and reports generated from the current database and the active filters."""
import pandas as pd
import plotly.express as px
import streamlit as st

import auth
import database as db
import reports
import ui

user = auth.require()

ui.page_header("Analytics & Reports", "Metrics, charts and CSV exports computed from the live database and your filters.")
all_df = db.list_complaints()
if all_df.empty:
    ui.empty_state("No complaints in the database yet.")
    st.stop()
f = ui.global_filters("an", all_df)
df = db.list_complaints(f)
if df.empty:
    ui.empty_state("No complaints match the current filters.", "Widen the date range or clear the bureau/state filters.")
    st.stop()

opn = df[df["is_open"]]
done = df[(~df["is_open"]) & df["resolved_date"].notna()]
avg_res = float(done["resolution_days"].mean()) if len(done) else None
on_time = 100 * done["resolved_on_time"].mean() if len(done) else None
overdue_pct = 100 * df["is_overdue"].sum() / len(opn) if len(opn) else None
hp = int(opn["priority"].isin(["Critical", "High"]).sum())

k = st.columns(5)
with k[0]: ui.kpi("Complaints in scope", len(df), f"{len(opn)} open", ui.BLUE)
with k[1]: ui.kpi("Avg resolution time", f"{avg_res:.1f} d" if avg_res is not None else "n/a", f"{len(done)} resolved/closed", ui.CYAN)
with k[2]: ui.kpi("On-time resolution", f"{on_time:.0f}%" if on_time is not None else "n/a", "resolved on or before due date", ui.SUCCESS)
with k[3]: ui.kpi("Overdue share", f"{overdue_pct:.0f}%" if overdue_pct is not None else "n/a", "of open complaints", ui.DANGER)
with k[4]: ui.kpi("High-priority open", hp, "Critical or High", ui.WARNING)
st.write("")


def bar(series_col, title, key, horizontal=True, top=None):
    d = df[series_col].value_counts()
    if top: d = d.head(top)
    d = d.reset_index()
    d.columns = [title, "Complaints"]
    fig = (px.bar(d, y=title, x="Complaints", orientation="h", color_discrete_sequence=[ui.BLUE]) if horizontal
           else px.bar(d, x=title, y="Complaints", color_discrete_sequence=[ui.BLUE]))
    if horizontal: fig.update_layout(yaxis=dict(categoryorder="total ascending"))
    ui.show_plot(ui.style_fig(fig, 330, f"Complaints by {title.lower()}"), key=key)


c1, c2 = st.columns(2)
with c1: bar("bureau", "Bureau", "an_bureau")
with c2: bar("category", "Category", "an_cat")
c3, c4 = st.columns(2)
with c3: bar("state", "State", "an_state", top=12)
with c4:
    s = df["status"].value_counts().reindex(db.STATUSES).dropna().reset_index()
    s.columns = ["Status", "Complaints"]
    fig = px.pie(s, names="Status", values="Complaints", hole=0.55, color="Status", color_discrete_map=ui.STATUS_COLORS)
    ui.show_plot(ui.style_fig(fig, 330, "Complaint status distribution"), key="an_status")
c5, c6 = st.columns(2)
with c5:
    m = df.groupby(df["date_received"].dt.to_period("M").dt.to_timestamp()).size().reset_index(name="Complaints")
    m.columns = ["Month", "Complaints"]
    fig = px.area(m, x="Month", y="Complaints", color_discrete_sequence=[ui.CYAN])
    ui.show_plot(ui.style_fig(fig, 330, "Monthly complaint trend"), key="an_trend")
with c6:
    conc = df.groupby("institution_name").agg(Total=("complaint_id", "count"), Open=("is_open", "sum")).reset_index()
    conc = conc.sort_values("Total", ascending=False).head(10)
    fig = px.bar(conc, y="institution_name", x="Total", orientation="h", color_discrete_sequence=[ui.BLUE])
    fig.update_layout(yaxis=dict(categoryorder="total ascending"))
    ui.show_plot(ui.style_fig(fig, 330, "Institution-wise concentration (top 10)"), key="an_conc")

st.caption("Definitions: resolution time = resolved date − date received, for resolved/closed complaints · "
           "on-time = resolved on or before due date · overdue share = overdue open complaints ÷ open complaints.")

# ---------------- exports ---------------- #
st.markdown("### Exports (use the filters above)")
inst = db.list_institutions()
ic = df.groupby("institution_id").agg(complaints_in_scope=("complaint_id", "count"),
                                      open_in_scope=("is_open", "sum"),
                                      last_complaint=("date_received", "max")).reset_index()
inst_export = inst[["institution_id", "name", "state", "district", "institution_type"]].merge(ic, on="institution_id")
overdue_export = df[df["is_overdue"]][["complaint_id", "institution_name", "bureau", "assigned_officer", "priority",
                                       "status", "due_date", "days_overdue", "last_updated"]]
rel_export = db.list_relationships(complaint_ids=df["complaint_id"].tolist())
summary = pd.DataFrame([
    ("Complaints in scope", len(df)), ("Open complaints", len(opn)), ("Resolved/closed complaints", len(df) - len(opn)),
    ("Overdue complaints", int(df["is_overdue"].sum())),
    ("Overdue share of open (%)", None if overdue_pct is None else round(overdue_pct, 1)),
    ("Average resolution time (days)", None if avg_res is None else round(avg_res, 1)),
    ("On-time resolution (%)", None if on_time is None else round(on_time, 1)),
    ("High-priority open cases", hp), ("Institutions covered", df["institution_id"].nunique()),
    ("Date range", f"{f['date_from']} to {f['date_to']}"),
    ("Bureau filter", ", ".join(f["bureaus"]) or "All"), ("State filter", ", ".join(f.get("states", [])) or "All"),
    ("Generated on", db.now_str()), ("Data", "Synthetic demonstration data")], columns=["Metric", "Value"])
cols = st.columns(6)
with cols[0]: ui.export_button("Complaints CSV", db.to_csv_bytes(df.drop(columns=["is_open"])), "complaints.csv", "text/csv", key="an_x1", what="Complaints (filtered)")
with cols[1]: ui.export_button("Institutions CSV", db.to_csv_bytes(inst_export), "institutions.csv", "text/csv", key="an_x2", what="Institutions (filtered)")
with cols[2]: ui.export_button("Overdue CSV", db.to_csv_bytes(overdue_export), "overdue_cases.csv", "text/csv", key="an_x3", what="Overdue cases")
with cols[3]: ui.export_button("Suggestions CSV", db.to_csv_bytes(rel_export), "relationship_suggestions.csv", "text/csv", key="an_x4", what="Relationship suggestions")
with cols[4]: ui.export_button("Summary CSV", db.to_csv_bytes(summary), "summary_report.csv", "text/csv", key="an_x5", what="Summary metrics")
with cols[5]:
    if reports.AVAILABLE:
        kp = [("In scope", len(df)), ("Open", len(opn)), ("Avg resolution", f"{avg_res:.1f} d" if avg_res is not None else "n/a"),
              ("On-time", f"{on_time:.0f}%" if on_time is not None else "n/a"),
              ("Overdue share", f"{overdue_pct:.0f}%" if overdue_pct is not None else "n/a"), ("High-priority open", hp)]
        ftxt = (f"{f['date_from']} to {f['date_to']}; bureaus: {', '.join(f['bureaus']) or ('own bureau' if user['role'] == 'Bureau Officer' else 'all')}; "
                f"states: {', '.join(f.get('states', [])) or 'all'}")
        ui.export_button("Summary PDF", reports.build_summary_pdf(df, kp, ftxt, user["full_name"], db.now_str()),
                         "aicte_nexus_summary.pdf", "application/pdf", key="an_pdf", what="Summary PDF report")
    else:
        st.caption("PDF needs `pip install reportlab`.")
with st.expander("Preview summary report"):
    ui.show_table(summary)
