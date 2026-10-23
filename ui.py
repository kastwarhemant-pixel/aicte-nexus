"""Shared Streamlit UI helpers: theme CSS, badges, KPI cards, tables, filters."""
from __future__ import annotations

import datetime as dt
import html

import pandas as pd
import streamlit as st

import database as db
import intelligence as intel

BG, SIDEBAR, CARD = "#0B1020", "#11182B", "#151F35"
BLUE, CYAN = "#3B82F6", "#22D3EE"
SUCCESS, WARNING, DANGER = "#22C55E", "#F59E0B", "#EF4444"
TEXT, MUTED, BORDER = "#F8FAFC", "#94A3B8", "#24324F"
FONT = "Inter, 'Segoe UI', system-ui, -apple-system, sans-serif"

STATUS_COLORS = {
    "Submitted": "#94A3B8",
    "Under Review": BLUE,
    "In Progress": CYAN,
    "Awaiting Information": WARNING,
    "Resolved": SUCCESS,
    "Closed": "#64748B",
}

PRIORITY_COLORS = {
    "Critical": DANGER,
    "High": "#F97316",
    "Medium": "#EAB308",
    "Low": "#2DD4BF",
}

CONFIDENCE_COLORS = {"High": CYAN, "Medium": BLUE, "Low": "#94A3B8"}
REVIEW_COLORS = {"Pending": WARNING, "Related": SUCCESS, "Dismissed": "#64748B"}

BUREAU_PALETTE = [
    BLUE, CYAN, "#8B5CF6", "#F59E0B", "#22C55E", "#F472B6"
]

STATUS_EMOJI = {
    "Submitted": "⚪",
    "Under Review": "🔵",
    "In Progress": "🟣",
    "Awaiting Information": "🟠",
    "Resolved": "🟢",
    "Closed": "⚫",
}

PRIORITY_EMOJI = {
    "Critical": "🔴",
    "High": "🟠",
    "Medium": "🟡",
    "Low": "🟢",
}


# ---------------------------------------------------------------------------
# PREMIUM UI CSS
# ---------------------------------------------------------------------------

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {{
  color-scheme: dark;
  --nx-bg: {BG};
  --nx-sidebar: {SIDEBAR};
  --nx-card: {CARD};
  --nx-border: {BORDER};
  --nx-blue: {BLUE};
  --nx-cyan: {CYAN};
  --nx-text: {TEXT};
  --nx-muted: {MUTED};
}}

html, body, [class*="css"], .stApp {{
  font-family: {FONT};
}}

.stApp {{
  background:
    radial-gradient(ellipse at 80% -10%, #173568 0%, transparent 38%),
    radial-gradient(ellipse at 0% 45%, #101d39 0%, transparent 32%),
    {BG};
  color: {TEXT};
}}

[data-testid="stHeader"] {{
  background: rgba(11,16,32,.78);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid #24324F66;
}}

[data-testid="stToolbar"] {{
  right: 1rem;
}}

.block-container {{
  padding-top: 2rem;
  padding-bottom: 3rem;
  max-width: 1600px;
}}

[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, #111a30 0%, #0c1325 100%);
  border-right: 1px solid #2b3b5c;
}}

[data-testid="stSidebar"] > div:first-child {{
  padding-top: 1rem;
}}

[data-testid="stSidebarNav"] {{
  padding-top: .5rem;
}}

[data-testid="stSidebarNav"]::before {{
  content: "AICTE NEXUS";
  display: block;
  padding: 1.3rem 1.15rem .25rem;
  font-size: 1.55rem;
  font-weight: 800;
  letter-spacing: -.045em;
  background: linear-gradient(100deg, #60A5FA 5%, #22D3EE 55%, #A78BFA 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}}

[data-testid="stSidebarNav"]::after {{
  content: "INTELLIGENT INSTITUTIONAL GOVERNANCE";
  display: block;
  padding: .2rem 1.2rem 1.25rem;
  font-size: .62rem;
  font-weight: 700;
  letter-spacing: .09em;
  color: {MUTED};
}}

[data-testid="stSidebarNav"] a {{
  margin: .15rem .55rem;
  border-radius: 10px;
  transition: background .18s ease, color .18s ease;
}}

[data-testid="stSidebarNav"] a:hover {{
  background: #1e3152;
  color: #67e8f9;
}}

[data-testid="stSidebarNav"] a[aria-current="page"] {{
  background: linear-gradient(100deg, #1d4ed833, #22d3ee16);
  border: 1px solid #3b82f655;
  color: #67e8f9;
}}

[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{
  line-height: 1.65;
}}

h1, h2, h3, h4 {{
  color: {TEXT};
  letter-spacing: -.035em;
}}

h1 {{ font-weight: 800; letter-spacing: -.045em; }}
h2 {{ font-weight: 750; }}
h3 {{ margin-top: 1.5rem; margin-bottom: .8rem; font-weight: 700; }}

.nx-head {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  margin-bottom: 1.6rem;
  flex-wrap: wrap;
}}

.nx-title {{
  font-size: clamp(1.65rem, 3vw, 2.35rem);
  font-weight: 800;
  line-height: 1.15;
  margin: 0;
  letter-spacing: -.055em;
  background: linear-gradient(100deg, #f8fafc 20%, #93c5fd 72%, #67e8f9 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}}

.nx-sub {{
  color: #a8b8d0;
  margin: .55rem 0 0;
  font-size: .96rem;
  line-height: 1.7;
  max-width: 75ch;
}}

.nx-pill {{
  display: inline-block;
  padding: .35rem .75rem;
  border-radius: 999px;
  font-size: .72rem;
  font-weight: 700;
  letter-spacing: .035em;
  color: #67e8f9;
  background: #0891b220;
  border: 1px solid #22d3ee55;
  white-space: normal;
}}

.nx-hero {{
  position: relative;
  overflow: hidden;
  border: 1px solid #334a70;
  border-radius: 22px;
  padding: clamp(1.3rem, 3vw, 2.2rem);
  margin-bottom: 1.5rem;
  background:
    radial-gradient(ellipse at 95% 0%, #2563eb35, transparent 42%),
    radial-gradient(ellipse at 5% 100%, #0891b220, transparent 45%),
    linear-gradient(135deg, #172746 0%, #111b31 58%, #10283a 100%);
  box-shadow: 0 18px 60px #00000025, inset 0 1px 0 #ffffff08;
}}

.nx-hero h1 {{
  font-size: clamp(1.8rem, 3.6vw, 2.7rem);
  line-height: 1.13;
  margin: .85rem 0 .65rem;
  font-weight: 800;
  letter-spacing: -.055em;
}}

.nx-hero p {{
  color: #c4d2e5;
  max-width: 82ch;
  line-height: 1.75;
  margin: 0 0 1.5rem;
}}

.nx-hero-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));
  gap: 1rem;
}}

.nx-hero-cell {{
  background: #080f20a8;
  backdrop-filter: blur(10px);
  border: 1px solid #52658466;
  border-radius: 15px;
  padding: 1.1rem;
  transition: transform .2s ease, border-color .2s ease;
}}

.nx-hero-cell:hover {{
  transform: translateY(-3px);
  border-color: #22d3ee88;
}}

.nx-hero-cell b {{
  color: #67e8f9;
  display: block;
  margin-bottom: .55rem;
  font-size: .9rem;
}}

.nx-hero-cell span {{
  color: #c4d2e5;
  font-size: .85rem;
  line-height: 1.75;
}}

.nx-kpi {{
  position: relative;
  overflow: hidden;
  background: linear-gradient(145deg, #18243b 0%, #121b2f 100%);
  border: 1px solid #2c3d5c;
  border-left: 3px solid var(--accent);
  border-radius: 16px;
  padding: 1.15rem 1.2rem;
  min-height: 125px;
  height: 100%;
  box-shadow: 0 8px 25px #00000015, inset 0 1px 0 #ffffff06;
  transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease;
}}

.nx-kpi::after {{
  content: "";
  position: absolute;
  width: 100px;
  height: 100px;
  right: -45px;
  top: -50px;
  border-radius: 50%;
  background: var(--accent);
  opacity: .09;
  filter: blur(25px);
}}

.nx-kpi:hover {{
  transform: translateY(-4px);
  border-color: var(--accent);
  box-shadow: 0 12px 32px #00000030;
}}

.nx-kpi-label {{
  color: #a8b8d0;
  font-size: .82rem;
  font-weight: 600;
  line-height: 1.5;
}}

.nx-kpi-value {{
  font-size: clamp(1.65rem, 2.3vw, 2.15rem);
  font-weight: 800;
  letter-spacing: -.045em;
  line-height: 1.25;
  margin: .5rem 0;
  color: #f8fafc;
  overflow-wrap: anywhere;
}}

.nx-kpi-sub {{
  color: #8fa2bf;
  font-size: .74rem;
  line-height: 1.55;
}}

.nx-card {{
  background: linear-gradient(145deg, #18243b, #121a2c);
  border: 1px solid #2c3d5c;
  border-radius: 16px;
  padding: 1.15rem 1.25rem;
  margin-bottom: 1rem;
  box-shadow: 0 8px 25px #00000012;
}}

.nx-card h4 {{
  margin: 0 0 .55rem;
  font-size: 1.02rem;
  font-weight: 700;
}}

.nx-muted {{
  color: #94a8c5;
  font-size: .85rem;
  line-height: 1.7;
}}

.nx-badge {{
  display: inline-block;
  padding: .25rem .65rem;
  border-radius: 999px;
  font-size: .73rem;
  font-weight: 700;
  border: 1px solid;
  white-space: nowrap;
  margin-right: .3rem;
}}

.nx-banner {{
  border-radius: 12px;
  padding: .85rem 1rem;
  margin: .35rem 0 1.2rem;
  font-size: .9rem;
  line-height: 1.65;
  border: 1px solid;
}}

.nx-banner.info {{
  color: #bae6fd;
  background: #0891b21c;
  border-color: #22d3ee55;
}}

.nx-banner.warn {{
  color: #fde68a;
  background: #f59e0b16;
  border-color: #f59e0b55;
}}

.nx-empty {{
  text-align: center;
  padding: 2.5rem 1rem;
  color: #94a8c5;
  border: 1px dashed #354968;
  border-radius: 16px;
  background: #121b2b80;
  line-height: 1.8;
}}

.nx-tablewrap {{
  overflow-x: auto;
  border: 1px solid #2c3d5c;
  border-radius: 14px;
  background: #121b2e;
  box-shadow: 0 8px 24px #00000015;
}}

table.nx-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: .84rem;
}}

table.nx-table th {{
  text-align: left;
  color: #a9bbd5;
  font-weight: 700;
  padding: .9rem .95rem;
  border-bottom: 1px solid #334765;
  background: #1a2941;
  white-space: nowrap;
}}

table.nx-table td {{
  padding: .85rem .95rem;
  border-bottom: 1px solid #25344d;
  vertical-align: top;
  color: #dbe6f5;
}}

table.nx-table tr:last-child td {{
  border-bottom: none;
}}

table.nx-table tr:hover td {{
  background: #1d2d47;
}}

.nx-over {{
  color: #f87171;
  font-weight: 800;
}}

.nx-tl {{
  border-left: 2px solid #344967;
  margin-left: .5rem;
  padding-left: 1.2rem;
}}

.nx-tl-item {{
  position: relative;
  padding-bottom: 1.2rem;
}}

.nx-tl-item::before {{
  content: "";
  position: absolute;
  left: -1.58rem;
  top: .35rem;
  width: .7rem;
  height: .7rem;
  border-radius: 50%;
  background: #22d3ee;
  box-shadow: 0 0 0 4px #0b1020, 0 0 15px #22d3ee55;
}}

.nx-tl-title {{
  font-weight: 700;
  color: #e2e8f0;
}}

.nx-tl-meta {{
  color: #8fa2bf;
  font-size: .78rem;
  margin: .2rem 0;
}}

/* Plotly chart styling */
[data-testid="stPlotlyChart"] {{
  background: linear-gradient(145deg, #16223a, #111a2d);
  border: 1px solid #2c3d5c;
  border-radius: 16px;
  padding: .5rem .6rem;
  box-shadow: 0 8px 24px #00000015;
}}

.stButton > button,
.stDownloadButton > button,
[data-testid="stFormSubmitButton"] > button {{
  border-radius: 10px;
  border: 1px solid #354968;
  font-weight: 650;
  min-height: 2.55rem;
  transition: transform .16s ease, border-color .16s ease, background .16s ease;
}}

.stButton > button:hover,
.stDownloadButton > button:hover {{
  border-color: #22d3ee;
  transform: translateY(-1px);
}}

.stButton > button[kind="primary"],
[data-testid="stFormSubmitButton"] > button[kind="primary"] {{
  color: white;
  background: linear-gradient(100deg, #2563eb, #0891b2);
  border: 1px solid #60a5fa55;
  box-shadow: 0 5px 18px #2563eb25;
}}

.stTextInput input,
.stTextArea textarea,
.stNumberInput input {{
  background: #101a2d;
  border-color: #354968;
  border-radius: 10px;
}}

.stSelectbox [data-baseweb="select"],
.stMultiSelect [data-baseweb="select"] {{
  border-radius: 10px;
}}

[data-testid="stTabs"] button[role="tab"] {{
  font-weight: 650;
  padding-top: .7rem;
  padding-bottom: .7rem;
}}

[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
  color: #67e8f9;
}}

[data-testid="stExpander"] {{
  background: #121b2e;
  border: 1px solid #2c3d5c;
  border-radius: 14px;
  overflow: hidden;
}}

[data-testid="stMetric"] {{
  background: linear-gradient(145deg, #18243b, #121a2c);
  border: 1px solid #2c3d5c;
  border-radius: 14px;
  padding: 1rem;
}}

[data-testid="stMetricLabel"] {{
  color: #a8b8d0;
}}

[data-testid="stMetricValue"] {{
  color: #f8fafc;
  font-weight: 800;
}}

[data-testid="stDataFrame"],
[data-testid="stTable"] {{
  border: 1px solid #2c3d5c;
  border-radius: 12px;
  overflow: hidden;
}}

hr {{
  border-color: #2c3d5c;
  opacity: .7;
}}

a {{
  color: #67e8f9;
}}

::selection {{
  color: white;
  background: #2563eb;
}}

:focus-visible {{
  outline: 2px solid #22d3ee;
  outline-offset: 2px;
}}

@media (max-width: 800px) {{
  .block-container {{
    padding-top: 1.2rem;
    padding-left: 1rem;
    padding-right: 1rem;
  }}

  .nx-title {{
    font-size: 1.65rem;
  }}

  .nx-hero h1 {{
    font-size: 1.7rem;
  }}

  .nx-hero {{
    border-radius: 16px;
    padding: 1.2rem;
  }}

  .nx-kpi {{
    min-height: 110px;
  }}
}}

@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    transition: none !important;
    animation: none !important;
  }}
}}
</style>
"""

_STRETCH_MODE = None


# ---------------------------------------------------------------------------
# STREAMLIT COMPATIBILITY
# ---------------------------------------------------------------------------

def _stretch(fn, *args, **kwargs):
    """Call a Streamlit element full-width across old/new Streamlit versions."""
    global _STRETCH_MODE

    modes = ["old"] if _STRETCH_MODE == "old" else ["new", "old"]

    for mode in modes:
        extra = (
            {"width": "stretch"}
            if mode == "new"
            else {"use_container_width": True}
        )

        try:
            result = fn(*args, **kwargs, **extra)
            _STRETCH_MODE = mode
            return result
        except Exception:
            if mode == modes[-1]:
                raise


# ---------------------------------------------------------------------------
# INITIALIZATION
# ---------------------------------------------------------------------------

def bootstrap():
    """
    Initialize the database, refresh relationship suggestions if needed,
    and inject the shared CSS theme.
    """
    db.init_db()

    if db.count_relationships() == 0 and db.count_complaints() > 0:
        intel.refresh_suggestions(actor="System", log=True)

    st.markdown(CSS, unsafe_allow_html=True)


def sidebar_footer():
    actor = html.escape(db.default_actor())

    with st.sidebar:
        st.markdown(
            f"""
            <div class="nx-card" style="margin-top:1rem">
                <span class="nx-pill">Prototype Demonstration</span>
                <p class="nx-muted" style="margin:.6rem 0 0">
                    Synthetic data only. No authentication is implemented;
                    actions are recorded under the demo user label
                    <b>{actor}</b>.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# BUILDING BLOCKS
# ---------------------------------------------------------------------------

def e(v) -> str:
    """Safely escape values before inserting them into HTML."""
    if v is None:
        return ""

    if isinstance(v, float) and pd.isna(v):
        return ""

    return html.escape(str(v))


def flash(kind: str, msg: str):
    """Store a message to display after a rerun."""
    st.session_state["_flash"] = (kind, msg)


def show_flash():
    """Display a previously stored message once."""
    message = st.session_state.pop("_flash", None)

    if message:
        handlers = {
            "success": st.success,
            "error": st.error,
            "warning": st.warning,
        }

        handlers.get(message[0], st.info)(message[1])


def result(ok: bool, msg: str, rerun: bool = True):
    """Standard handling for an (ok, msg) result from the database layer."""
    if ok:
        flash("success", msg)

        if rerun:
            st.rerun()
    else:
        st.error(msg)


def page_header(title: str, subtitle: str):
    """Display a consistent page heading and subtitle."""
    st.markdown(
        f"""
        <div class="nx-head">
            <div>
                <p class="nx-title">{e(title)}</p>
                <p class="nx-sub">{e(subtitle)}</p>
            </div>
            <span class="nx-pill">
                Prototype Demonstration — Synthetic Data
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    show_flash()


def banner(text: str, kind: str = "info"):
    """Display an information or warning banner."""
    safe_text = e(text)

    st.markdown(
        f'<div class="nx-banner {kind}">{safe_text}</div>',
        unsafe_allow_html=True,
    )


def empty_state(msg: str, hint: str = ""):
    """Display a friendly empty-state message."""
    st.markdown(
        f"""
        <div class="nx-empty">
            <b>{e(msg)}</b><br>
            {e(hint)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def badge(text, color) -> str:
    """Return an HTML badge with a given color."""
    return (
        f'<span class="nx-badge" '
        f'style="color:{color};background:{color}22;'
        f'border-color:{color}66">'
        f'{e(text)}</span>'
    )


def status_badge(status):
    return badge(status, STATUS_COLORS.get(status, MUTED))


def priority_badge(priority):
    return badge(priority, PRIORITY_COLORS.get(priority, MUTED))


def kpi(label: str, value, sub: str = "", accent: str = BLUE):
    """Display a premium KPI card."""
    st.markdown(
        f"""
        <div class="nx-kpi" style="--accent:{accent}">
            <div class="nx-kpi-label">{e(label)}</div>
            <div class="nx-kpi-value">{e(value)}</div>
            <div class="nx-kpi-sub">{e(sub)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def fmt_date(value) -> str:
    """Format a date in a readable format."""
    if value is None:
        return "—"

    if not isinstance(value, str) and pd.isna(value):
        return "—"

    try:
        return pd.Timestamp(value).strftime("%d %b %Y")
    except Exception:
        return str(value)


def html_table(
    df: pd.DataFrame,
    spec: list,
    empty: str = "Nothing to show.",
):
    """
    Render a styled HTML table.

    spec format:
    [(column, label, kind), ...]

    Supported kinds:
    text, status, priority, date, overdue, confidence, review
    """
    if df is None or df.empty:
        empty_state(empty)
        return

    head = "".join(
        f"<th>{e(label)}</th>"
        for _, label, _ in spec
    )

    rows = []

    for _, row in df.iterrows():
        cells = []

        for column, _, kind in spec:
            value = row[column]

            if kind == "status":
                cell = status_badge(value)

            elif kind == "priority":
                cell = priority_badge(value)

            elif kind == "confidence":
                cell = badge(
                    value,
                    CONFIDENCE_COLORS.get(value, MUTED),
                )

            elif kind == "review":
                cell = badge(
                    value,
                    REVIEW_COLORS.get(value, MUTED),
                )

            elif kind == "date":
                cell = e(fmt_date(value))

            elif kind == "overdue":
                try:
                    days = int(value)
                except (TypeError, ValueError):
                    days = 0

                cell = (
                    f'<span class="nx-over">{days} d</span>'
                    if days > 0
                    else "—"
                )

            else:
                safe_value = e(value)
                cell = (
                    safe_value
                    if len(safe_value) <= 90
                    else safe_value[:87] + "…"
                )

            cells.append(f"<td>{cell}</td>")

        rows.append("<tr>" + "".join(cells) + "</tr>")

    st.markdown(
        f"""
        <div class="nx-tablewrap">
            <table class="nx-table">
                <thead><tr>{head}</tr></thead>
                <tbody>{"".join(rows)}</tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_table(df: pd.DataFrame, **kwargs):
    """Display a full-width Streamlit dataframe."""
    _stretch(
        st.dataframe,
        df,
        hide_index=True,
        **kwargs,
    )


def show_plot(fig, key=None):
    """Display a full-width Plotly chart with a unique key."""
    if key is None:
        key = "nexus_chart"

    if "_nexus_chart_instance" not in st.session_state:
        st.session_state["_nexus_chart_instance"] = 0

    st.session_state["_nexus_chart_instance"] += 1

    unique_key = (
        f"{key}_{st.session_state['_nexus_chart_instance']}"
    )

    _stretch(
        st.plotly_chart,
        fig,
        key=unique_key,
    )


def style_fig(fig, height=320, title=None):
    """Apply the shared dark theme to a Plotly figure."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            color=TEXT,
            family=FONT,
        ),
        height=height,
        margin=dict(l=12, r=12, t=50, b=12),
        colorway=BUREAU_PALETTE,
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            title_text="",
        ),
        title=(
            dict(
                text=title,
                font=dict(size=15),
                x=0.02,
            )
            if title
            else None
        ),
    )

    fig.update_xaxes(
        gridcolor="#1f2c4a",
        zerolinecolor="#1f2c4a",
        title_text=None,
    )

    fig.update_yaxes(
        gridcolor="#1f2c4a",
        zerolinecolor="#1f2c4a",
        title_text=None,
    )

    return fig


def complaint_table_df(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare a readable complaint table with status and priority markers."""
    if df.empty:
        return pd.DataFrame(
            columns=[
                "ID",
                "Institution",
                "Title",
                "Bureau",
                "Category",
                "Priority",
                "Status",
                "Officer",
                "Received",
                "Due",
                "Updated",
                "Days overdue",
            ]
        )

    return pd.DataFrame(
        {
            "ID": df["complaint_id"],
            "Institution": df["institution_name"],
            "Title": df["title"],
            "Bureau": df["bureau"],
            "Category": df["category"],
            "Priority": df["priority"].map(
                lambda p: f"{PRIORITY_EMOJI.get(p, '')} {p}"
            ),
            "Status": df["status"].map(
                lambda s: f"{STATUS_EMOJI.get(s, '')} {s}"
            ),
            "Officer": df["assigned_officer"],
            "Received": df["date_received"].dt.strftime("%Y-%m-%d"),
            "Due": df["due_date"].dt.strftime("%Y-%m-%d"),
            "Updated": df["last_updated"].dt.strftime("%Y-%m-%d"),
            "Days overdue": df["days_overdue"],
        }
    )


def timeline(df: pd.DataFrame):
    """Display audit events as a vertical timeline."""
    if df.empty:
        empty_state("No recorded events yet.")
        return

    items = []

    for row in df.itertuples():
        title = row.action_type.replace("_", " ").capitalize()
        change = ""

        if row.previous_value or row.new_value:
            change = (
                f"{e(row.previous_value or '—')[:80]} "
                f"→ {e(row.new_value or '—')[:80]}"
            )

        items.append(
            f'<div class="nx-tl-item">'
            f'<div class="nx-tl-title">{e(title)}</div>'
            f'<div class="nx-tl-meta">{e(row.ts)} · {e(row.actor)}</div>'
            f'<div>{change}</div>'
            f'<div class="nx-muted">{e((row.details or "")[:240])}</div>'
            f'</div>'
        )

    st.markdown(
        f'<div class="nx-tl">{"".join(items)}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# FILTERS
# ---------------------------------------------------------------------------

def date_range_filter(
    label: str,
    lo: dt.date,
    hi: dt.date,
    key: str,
):
    """Render a date-range selector."""
    if lo > hi:
        lo = hi

    value = st.date_input(
        label,
        value=(lo, hi),
        min_value=dt.date(2020, 1, 1),
        max_value=dt.date(2035, 12, 31),
        key=key,
    )

    if isinstance(value, (tuple, list)):
        if len(value) == 2:
            return value[0], value[1]

        if len(value) == 1:
            return value[0], hi

        return lo, hi

    return value, value


def inst_label(options):
    """Create a formatter for institution IDs."""
    names = dict(options)

    return lambda institution_id: (
        f"{names.get(institution_id, institution_id)} "
        f"({institution_id})"
    )


def global_filters(
    prefix: str,
    all_df: pd.DataFrame,
    show_status=True,
    show_institution=True,
    show_priority=True,
    show_state=True,
) -> dict:
    """
    Standard filter bar.

    Returns a dictionary compatible with db.list_complaints().
    """
    if not all_df.empty:
        lo = all_df["date_received"].min().date()
        hi = max(
            all_df["date_received"].max().date(),
            db.today(),
        )
    else:
        lo = db.today()
        hi = db.today()

    filters = {}

    with st.expander("Filters", expanded=True):
        columns = st.columns(3)

        with columns[0]:
            (
                filters["date_from"],
                filters["date_to"],
            ) = date_range_filter(
                "Date received",
                lo,
                hi,
                f"{prefix}_dates",
            )

        filters["bureaus"] = columns[1].multiselect(
            "Bureau / cell",
            db.BUREAUS,
            key=f"{prefix}_bureau",
        )

        if show_state:
            states = (
                sorted(all_df["state"].unique())
                if not all_df.empty
                else []
            )

            filters["states"] = columns[2].multiselect(
                "State",
                states,
                key=f"{prefix}_state",
            )

        columns2 = st.columns(3)

        if show_institution:
            options = db.institution_options()

            filters["institution_ids"] = columns2[0].multiselect(
                "Institution",
                [institution_id for institution_id, _ in options],
                format_func=inst_label(options),
                key=f"{prefix}_inst",
            )

        if show_status:
            filters["statuses"] = columns2[1].multiselect(
                "Status",
                db.STATUSES,
                key=f"{prefix}_status",
            )

        if show_priority:
            filters["priorities"] = columns2[2].multiselect(
                "Priority",
                db.PRIORITIES,
                key=f"{prefix}_prio",
            )

    return filters