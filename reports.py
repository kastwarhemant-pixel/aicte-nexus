"""PDF report generation (ReportLab). Falls back gracefully if ReportLab is not installed."""
from __future__ import annotations

import io

import pandas as pd

try:
    from reportlab.graphics.charts.barcharts import HorizontalBarChart
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    AVAILABLE = True
except ImportError:  # pragma: no cover
    AVAILABLE = False

NAVY, BLUE, LIGHT = "#0B2C74", "#2563EB", "#E8F1FF"


def _esc(v) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(rows, header, widths=None):
    data = [header] + [[_esc(c) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(LIGHT)]),
        ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#BBD0F5")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _bar(series: pd.Series, title: str, styles):
    if series.empty:
        return []
    d = Drawing(480, 22 + 18 * len(series))
    ch = HorizontalBarChart()
    ch.x, ch.y, ch.width, ch.height = 150, 6, 300, 14 * len(series) + 6
    ch.data = [list(series.values[::-1])]
    ch.categoryAxis.categoryNames = [str(i)[:28] for i in series.index[::-1]]
    ch.categoryAxis.labels.fontSize = 7
    ch.valueAxis.labels.fontSize = 7
    ch.valueAxis.valueMin = 0
    ch.bars[0].fillColor = colors.HexColor(BLUE)
    d.add(ch)
    return [Paragraph(f"<b>{_esc(title)}</b>", styles["Normal"]), d, Spacer(1, 6)]


def build_summary_pdf(df: pd.DataFrame, kpis: list, filters_text: str, generated_by: str, generated_on: str) -> bytes:
    """Executive summary: KPIs, distributions (with bar charts), top overdue cases. Returns PDF bytes."""
    if not AVAILABLE:
        raise RuntimeError("ReportLab is not installed (pip install reportlab).")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm, title="AICTE NEXUS Summary Report",
                            author=generated_by)
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=colors.HexColor(NAVY), alignment=0, fontSize=20)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=colors.HexColor(BLUE), fontSize=12, spaceBefore=8)
    small = ParagraphStyle("sm", parent=ss["Normal"], fontSize=8, textColor=colors.HexColor("#566F93"))
    story = [Paragraph("AICTE NEXUS — Complaint Summary Report", h1),
             Paragraph(f"Generated {_esc(generated_on)} by {_esc(generated_by)} · Prototype demonstration, synthetic data", small),
             Paragraph(f"Filters: {_esc(filters_text)}", small), Spacer(1, 8),
             _table([[v for _, v in kpis]], [k for k, _ in kpis]), Spacer(1, 6)]
    if df.empty:
        story.append(Paragraph("No complaints match the selected filters.", ss["Normal"]))
    else:
        for col, title in (("bureau", "Complaints by bureau"), ("status", "Complaints by status"),
                           ("priority", "Complaints by priority"), ("category", "Complaints by category")):
            story += [Paragraph(title, h2)] + _bar(df[col].value_counts(), title, ss)
        m = df.groupby(df["date_received"].dt.to_period("M")).size().tail(12)
        story += [Paragraph("Monthly trend (last 12 months)", h2),
                  _table([[str(i), int(v)] for i, v in m.items()], ["Month", "Complaints received"], [60 * mm, 50 * mm])]
        od = df[df["is_overdue"]].sort_values("days_overdue", ascending=False).head(15)
        story.append(Paragraph("Most overdue open cases", h2))
        if od.empty:
            story.append(Paragraph("No overdue cases.", ss["Normal"]))
        else:
            story.append(_table([[r.complaint_id, str(r.institution_name)[:34], r.bureau, r.priority, r.assigned_officer,
                                  r.due_date.strftime("%Y-%m-%d"), int(r.days_overdue)] for r in od.itertuples()],
                                ["ID", "Institution", "Bureau", "Priority", "Officer", "Due", "Days overdue"],
                                [28 * mm, 62 * mm, 42 * mm, 20 * mm, 38 * mm, 24 * mm, 24 * mm]))
    story += [Spacer(1, 10), Paragraph("Scores and recommendations are heuristic aids for officers; this prototype makes "
                                       "no compliance claims.", small)]
    doc.build(story)
    return buf.getvalue()
