"""Shared Streamlit UI helpers: Blue & White theme (light + dark), animation, badges, KPI cards, tables, filters.

Theming approach
- The app is configured as a *light* Streamlit theme (.streamlit/config.toml). The dark theme is applied by CSS
  variables + overrides for Streamlit's own widgets, so one toggle switches everything: cards, tables, charts, forms.
- Tables are rendered as themed HTML (not st.dataframe, whose canvas ignores CSS) so they follow the toggle.
- Plotly figures read the active theme in style_fig().
"""
from __future__ import annotations

import datetime as dt
import html

import pandas as pd
import streamlit as st

import accounts
import database as db
import intelligence as intel

# ---------------------------------------------------------------------------
# PALETTE
# ---------------------------------------------------------------------------
BLUE, CYAN = "#2563EB", "#0EA5E9"
SUCCESS, WARNING, DANGER = "#16A34A", "#D97706", "#DC2626"
PURPLE = "#6D5BD0"
FONT = "Inter, 'Segoe UI', system-ui, -apple-system, sans-serif"

THEMES = {
    "light": dict(
        scheme="light", bg="#F3F7FF", bg2="#E6EFFE", card="#FFFFFF", card2="#F6F9FF", border="#CDDFFA",
        border2="#A8C5F0", text="#0E2748", muted="#566F93", input="#FFFFFF", thead="#E8F1FF", hover="#F1F7FF",
        shadow="0 6px 22px rgba(37,99,235,.10)", shadow2="0 12px 30px rgba(37,99,235,.18)",
        grid="#DDE8F8", plot="plotly_white", header="rgba(243,247,255,.85)",
        glow="rgba(37,99,235,.35)"),
    "dark": dict(
        scheme="dark", bg="#071226", bg2="#0A1B3A", card="#0F2042", card2="#13294F", border="#1F3D73",
        border2="#2D56A1", text="#E8F0FF", muted="#93AACC", input="#0B1B38", thead="#15305F", hover="#152F5C",
        shadow="0 8px 26px rgba(0,0,0,.38)", shadow2="0 14px 34px rgba(0,0,0,.5)",
        grid="#1B3562", plot="plotly_dark", header="rgba(7,18,38,.85)",
        glow="rgba(59,130,246,.55)"),
}

STATUS_COLORS = {
    "Submitted": "#64748B", "Under Review": "#2563EB", "In Progress": "#0891B2",
    "Awaiting Information": "#D97706", "Resolved": "#16A34A", "Closed": "#475569",
}
PRIORITY_COLORS = {"Critical": "#DC2626", "High": "#EA580C", "Medium": "#CA8A04", "Low": "#0D9488"}
CONFIDENCE_COLORS = {"High": "#2563EB", "Medium": "#0891B2", "Low": "#64748B"}
REVIEW_COLORS = {"Pending": "#D97706", "Related": "#16A34A", "Dismissed": "#64748B"}
ROLE_COLORS = {"Admin": "#7C3AED", "Senior Officer": "#2563EB", "Bureau Officer": "#0891B2"}
BUREAU_PALETTE = ["#2563EB", "#0EA5E9", "#6D5BD0", "#F59E0B", "#16A34A", "#EC4899"]
MUTED = THEMES["light"]["muted"]

STATUS_EMOJI = {"Submitted": "⚪", "Under Review": "🔵", "In Progress": "🟣", "Awaiting Information": "🟠",
                "Resolved": "🟢", "Closed": "⚫"}
PRIORITY_EMOJI = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}


def _h(text: str) -> str:
    """Strip indentation and blank lines so Markdown never turns HTML into a code block."""
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


# ---------------------------------------------------------------------------
# THEME STATE
# ---------------------------------------------------------------------------
def theme() -> str:
    return "dark" if st.session_state.get("theme") == "dark" else "light"


def theme_toggle(label: str = "🌙  Dark mode"):
    """Light/Dark switch. The choice is remembered for the signed-in user."""
    st.session_state["_theme_tgl"] = theme() == "dark"

    def _changed():
        st.session_state["theme"] = "dark" if st.session_state.get("_theme_tgl") else "light"
        u = db.current_user() or st.session_state.get("user")
        if u:
            try:
                accounts.set_theme(u["user_id"], st.session_state["theme"])
            except Exception:
                pass

    st.toggle(label, key="_theme_tgl", on_change=_changed,
              help="Switch between the Light and Dark Blue & White themes.")


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
def build_css(mode: str = "light") -> str:
    t = THEMES[mode]
    dark = mode == "dark"
    css = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root {{
  color-scheme: {t['scheme']};
  --nx-bg:{t['bg']}; --nx-bg2:{t['bg2']}; --nx-card:{t['card']}; --nx-card2:{t['card2']};
  --nx-border:{t['border']}; --nx-border2:{t['border2']}; --nx-text:{t['text']}; --nx-muted:{t['muted']};
  --nx-input:{t['input']}; --nx-thead:{t['thead']}; --nx-hover:{t['hover']};
  --nx-shadow:{t['shadow']}; --nx-shadow2:{t['shadow2']}; --nx-glow:{t['glow']};
  --nx-primary:#2563EB; --nx-primary-d:#1D4ED8; --nx-bright:#3B82F6; --nx-sky:#0EA5E9;
  --nx-side-from:#0B2C74; --nx-side-to:#06194A;
}}
html, body, [class*="css"], .stApp {{ font-family:{FONT}; }}
.stApp {{
  background:
    radial-gradient(ellipse at 85% -10%, {'#12346F' if dark else '#DCE9FF'} 0%, transparent 42%),
    radial-gradient(ellipse at 0% 60%, {'#0B2150' if dark else '#EAF2FF'} 0%, transparent 36%),
    var(--nx-bg);
  color: var(--nx-text);
}}
[data-testid="stHeader"] {{ background:{t['header']}; backdrop-filter:blur(14px); border-bottom:1px solid var(--nx-border); }}
.block-container {{ padding-top:2rem; padding-bottom:3rem; max-width:1600px; }}

/* ---------- text ---------- */
:where(.stApp) :where(h1,h2,h3,h4,h5,h6) {{ letter-spacing:-.03em; }}
.stApp [data-testid="stHeading"] *, .stApp h1, .stApp h2, .stApp h3, .stApp h4 {{ color:var(--nx-text); }}
.stApp [data-testid="stMarkdownContainer"] :is(p, li, h1, h2, h3, h4, h5, h6, strong, em, td, th, span) {{ color:var(--nx-text); }}
[data-testid="stExpander"] summary *, [data-testid="stCheckbox"] label *, [data-testid="stToggle"] label * {{ color:var(--nx-text) !important; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {{ color:var(--nx-muted) !important; }}
[data-testid="stWidgetLabel"] *, label[data-baseweb="checkbox"] *, [data-testid="stRadio"] label * {{ color:var(--nx-text) !important; }}
h1 {{ font-weight:800; letter-spacing:-.045em; }}
h3 {{ margin-top:1.4rem; margin-bottom:.8rem; font-weight:700; }}
a {{ color:var(--nx-primary); }}
::selection {{ color:#fff; background:var(--nx-primary); }}
:focus-visible {{ outline:2px solid var(--nx-bright); outline-offset:2px; }}
hr {{ border-color:var(--nx-border); opacity:.8; }}

/* ---------- sidebar: deep blue in both themes ---------- */
[data-testid="stSidebar"] {{
  background:linear-gradient(185deg, var(--nx-side-from) 0%, var(--nx-side-to) 100%);
  border-right:1px solid #1d3f8f;
  box-shadow:6px 0 28px rgba(7,25,77,.25);
}}
[data-testid="stSidebar"] :where(p, span, label, li, div, small, h1, h2, h3, h4) {{ color:#DCE8FF; }}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {{ color:#9DB8E8 !important; }}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] *, [data-testid="stSidebar"] [data-testid="stToggle"] label *,
[data-testid="stSidebar"] label[data-baseweb="checkbox"] * {{ color:#DCE8FF !important; }}
[data-testid="stSidebar"] .stApp [data-testid="stMarkdownContainer"] p {{ color:#DCE8FF; }}
[data-testid="stSidebarNav"]::before {{
  content:"⬢  AICTE NEXUS"; display:block; padding:1.3rem 1.15rem .2rem; font-size:1.5rem; font-weight:800;
  letter-spacing:-.03em; color:#fff; text-shadow:0 0 18px rgba(96,165,250,.9), 0 0 34px rgba(59,130,246,.6);
  animation:nx-logo-pulse 3.2s ease-in-out infinite;
}}
[data-testid="stSidebarNav"]::after {{
  content:"UNIFIED COMPLAINT INTELLIGENCE"; display:block; padding:.1rem 1.25rem 1.2rem; font-size:.6rem;
  font-weight:700; letter-spacing:.14em; color:#8FB0EC;
}}
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNavLink"] {{
  margin:.15rem .6rem; border-radius:11px; transition:background .2s ease, transform .2s ease, box-shadow .2s ease;
}}
[data-testid="stSidebarNav"] a *, [data-testid="stSidebarNavLink"] * {{ color:#DCE8FF !important; }}
[data-testid="stSidebarNav"] a:hover, [data-testid="stSidebarNavLink"]:hover {{ background:rgba(96,165,250,.18); transform:translateX(3px); }}
[data-testid="stSidebarNav"] a[aria-current="page"], [data-testid="stSidebarNavLink"][aria-current="page"] {{
  background:linear-gradient(95deg,#2F80FF,#1D6BF0); box-shadow:0 6px 18px rgba(47,128,255,.45);
}}
[data-testid="stSidebarNav"] a[aria-current="page"] *, [data-testid="stSidebarNavLink"][aria-current="page"] * {{
  color:#fff !important; font-weight:700;
}}
[data-testid="stSidebar"] .stButton > button {{
  background:rgba(255,255,255,.10); color:#fff; border:1px solid rgba(255,255,255,.28);
}}
[data-testid="stSidebar"] .stButton > button:hover {{ background:rgba(255,255,255,.2); border-color:#fff; }}

/* ---------- page header / hero ---------- */
.nx-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; margin-bottom:1.5rem; flex-wrap:wrap; animation:nx-rise .5s ease both; }}
.nx-title {{
  font-size:clamp(1.6rem,3vw,2.3rem); font-weight:800; line-height:1.15; margin:0; letter-spacing:-.05em;
  background:linear-gradient(100deg, {'#E8F0FF 10%, #7FB0FF 70%, #5EC8F5' if dark else '#0B2C74 5%, #1D4ED8 60%, #0EA5E9'} 100%);
  -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent;
}}
.nx-sub {{ color:var(--nx-muted) !important; margin:.5rem 0 0; font-size:.95rem; line-height:1.7; max-width:75ch; }}
.nx-pill {{
  display:inline-block; padding:.35rem .8rem; border-radius:999px; font-size:.72rem; font-weight:700; letter-spacing:.03em;
  color:{'#9CC4FF' if dark else '#1D4ED8'} !important; background:{'rgba(59,130,246,.16)' if dark else '#E3EEFF'};
  border:1px solid var(--nx-border2);
}}
.nx-hero {{
  position:relative; overflow:hidden; border-radius:22px; padding:clamp(1.3rem,3vw,2.2rem); margin-bottom:1.5rem;
  background:radial-gradient(ellipse at 95% 0%, rgba(120,190,255,.45), transparent 45%),
             linear-gradient(125deg, #0B2C74 0%, #1D4ED8 55%, #2F86F6 100%);
  box-shadow:0 18px 50px rgba(29,78,216,.30); animation:nx-rise .55s ease both;
}}
.nx-hero::after {{ content:""; position:absolute; width:340px; height:340px; right:-90px; top:-120px; border-radius:50%;
  background:radial-gradient(circle, rgba(255,255,255,.22), transparent 65%); pointer-events:none; }}
.nx-hero h1 {{ color:#fff !important; font-size:clamp(1.7rem,3.5vw,2.6rem); line-height:1.13; margin:.8rem 0 .6rem; font-weight:800; letter-spacing:-.05em; }}
.nx-hero p {{ color:#DCEAFF !important; max-width:82ch; line-height:1.75; margin:0 0 1.4rem; }}
.nx-hero .nx-pill {{ background:rgba(255,255,255,.16); color:#fff !important; border-color:rgba(255,255,255,.4); }}
.nx-hero-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr)); gap:1rem; position:relative; z-index:1; }}
.nx-hero-cell {{ background:rgba(255,255,255,.12); backdrop-filter:blur(8px); border:1px solid rgba(255,255,255,.28);
  border-radius:15px; padding:1.05rem; transition:transform .2s ease, background .2s ease; }}
.nx-hero-cell:hover {{ transform:translateY(-3px); background:rgba(255,255,255,.2); }}
.nx-hero-cell b {{ color:#fff !important; display:block; margin-bottom:.5rem; font-size:.9rem; }}
.nx-hero-cell span {{ color:#E1EDFF !important; font-size:.85rem; line-height:1.7; }}

/* ---------- KPI: filled boxes ---------- */
.nx-kpi {{
  position:relative; overflow:hidden; height:100%; min-height:122px; border-radius:16px; padding:1.1rem 1.2rem;
  background:var(--accent); background:linear-gradient(135deg, color-mix(in srgb, var(--accent) 62%, #061a52) 0%, var(--accent) 100%);
  box-shadow:var(--nx-shadow); border:1px solid rgba(255,255,255,.18);
  transition:transform .22s ease, box-shadow .22s ease; animation:nx-rise .5s ease both;
}}
.nx-kpi::after {{ content:""; position:absolute; width:120px; height:120px; right:-40px; top:-55px; border-radius:50%; background:#fff; opacity:.14; }}
.nx-kpi:hover {{ transform:translateY(-4px); box-shadow:var(--nx-shadow2); }}
.nx-kpi-label {{ color:rgba(255,255,255,.92) !important; font-size:.8rem; font-weight:600; line-height:1.45; }}
.nx-kpi-value {{ color:#fff !important; font-size:clamp(1.65rem,2.3vw,2.15rem); font-weight:800; letter-spacing:-.04em; line-height:1.25; margin:.45rem 0; overflow-wrap:anywhere; text-shadow:0 1px 3px rgba(0,20,70,.3); }}
.nx-kpi-sub {{ color:rgba(255,255,255,.85) !important; font-size:.74rem; line-height:1.5; }}

/* ---------- cards, tables ---------- */
.nx-card {{ background:var(--nx-card); border:1px solid var(--nx-border); border-radius:16px; padding:1.1rem 1.25rem; margin-bottom:1rem; box-shadow:var(--nx-shadow); animation:nx-rise .45s ease both; }}
.nx-card h4 {{ margin:0 0 .5rem; font-size:1.02rem; font-weight:700; color:var(--nx-text); }}
.nx-muted {{ color:var(--nx-muted) !important; font-size:.85rem; line-height:1.7; }}
.nx-badge {{ display:inline-block; padding:.22rem .62rem; border-radius:999px; font-size:.72rem; font-weight:700; border:1px solid; white-space:nowrap; margin-right:.3rem; }}
.nx-banner {{ border-radius:12px; padding:.8rem 1rem; margin:.35rem 0 1.1rem; font-size:.9rem; line-height:1.65; border:1px solid; }}
.nx-banner.info {{ color:{'#BCD8FF' if dark else '#0B3A8F'} !important; background:{'rgba(59,130,246,.14)' if dark else '#E8F1FF'}; border-color:var(--nx-border2); }}
.nx-banner.warn {{ color:{'#FDE3A6' if dark else '#7A4B00'} !important; background:{'rgba(245,158,11,.14)' if dark else '#FFF6E0'}; border-color:{'rgba(245,158,11,.5)' if dark else '#F2CF85'}; }}
.nx-banner.danger {{ color:{'#FECACA' if dark else '#8E1B1B'} !important; background:{'rgba(220,38,38,.15)' if dark else '#FDECEC'}; border-color:{'rgba(220,38,38,.5)' if dark else '#F2B3B3'}; }}
.nx-banner b, .nx-banner span {{ color:inherit !important; }}
.nx-empty {{ text-align:center; padding:2.4rem 1rem; color:var(--nx-muted); border:1px dashed var(--nx-border2); border-radius:16px; background:var(--nx-card2); line-height:1.8; }}
.nx-tablewrap {{ overflow:auto; max-height:640px; border:1px solid var(--nx-border); border-radius:14px; background:var(--nx-card); box-shadow:var(--nx-shadow); animation:nx-rise .45s ease both; }}
table.nx-table {{ width:100%; border-collapse:collapse; font-size:.84rem; }}
table.nx-table th {{ position:sticky; top:0; z-index:1; text-align:left; color:var(--nx-muted); font-weight:700; padding:.8rem .9rem; border-bottom:1px solid var(--nx-border); background:var(--nx-thead); white-space:nowrap; }}
table.nx-table td {{ padding:.75rem .9rem; border-bottom:1px solid var(--nx-border); vertical-align:top; color:var(--nx-text); }}
table.nx-table tr:last-child td {{ border-bottom:none; }}
table.nx-table tr:hover td {{ background:var(--nx-hover); }}
.nx-over {{ color:#DC2626 !important; font-weight:800; }}
.nx-tl {{ border-left:2px solid var(--nx-border2); margin-left:.5rem; padding-left:1.2rem; }}
.nx-tl-item {{ position:relative; padding-bottom:1.1rem; }}
.nx-tl-item::before {{ content:""; position:absolute; left:-1.58rem; top:.35rem; width:.7rem; height:.7rem; border-radius:50%; background:var(--nx-bright); box-shadow:0 0 0 4px var(--nx-bg), 0 0 14px var(--nx-glow); }}
.nx-tl-title {{ font-weight:700; color:var(--nx-text); }}
.nx-tl-meta {{ color:var(--nx-muted); font-size:.78rem; margin:.2rem 0; }}

/* progress stepper (complaint tracking) */
.nx-steps {{ display:flex; gap:.4rem; align-items:center; flex-wrap:wrap; margin:.4rem 0 1rem; }}
.nx-step {{ flex:1 1 120px; text-align:center; padding:.55rem .4rem; border-radius:10px; font-size:.78rem; font-weight:700; background:var(--nx-card2); color:var(--nx-muted); border:1px solid var(--nx-border); }}
.nx-step.done {{ background:linear-gradient(135deg,#1D4ED8,#2F86F6); color:#fff; border-color:transparent; }}
.nx-step.now {{ background:#fff; color:#1D4ED8; border:2px solid #2563EB; box-shadow:0 0 0 4px var(--nx-glow); }}

/* alert strip */
.nx-alerts {{ display:flex; flex-wrap:wrap; gap:.6rem; margin:0 0 1.2rem; animation:nx-rise .45s ease both; }}
.nx-chip {{ display:inline-flex; align-items:center; gap:.5rem; padding:.5rem .9rem; border-radius:12px; font-size:.82rem; font-weight:700; border:1px solid; background:var(--nx-card); box-shadow:var(--nx-shadow); }}
.nx-chip b {{ font-size:1.05rem; }}
.nx-chip.red {{ color:{'#FCA5A5' if dark else '#B91C1C'} !important; border-color:{'rgba(248,113,113,.55)' if dark else '#F4B4B4'}; }}
.nx-chip.amber {{ color:{'#FCD34D' if dark else '#92520A'} !important; border-color:{'rgba(245,158,11,.55)' if dark else '#F1D08A'}; }}
.nx-chip.blue {{ color:{'#93C5FD' if dark else '#1D4ED8'} !important; border-color:var(--nx-border2); }}
.nx-chip b, .nx-chip span {{ color:inherit !important; }}

/* ---------- native widgets ---------- */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {{
  border-radius:10px; border:1px solid var(--nx-border2); background:var(--nx-card); color:var(--nx-text);
  font-weight:650; min-height:2.55rem; transition:transform .16s ease, border-color .16s ease, box-shadow .16s ease, background .16s ease;
}}
.stButton > button *, .stDownloadButton > button *, [data-testid="stFormSubmitButton"] > button * {{ color:inherit !important; }}
.stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stFormSubmitButton"] > button:hover {{
  border-color:var(--nx-primary); transform:translateY(-1px); box-shadow:0 6px 16px var(--nx-glow);
}}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
  color:#fff; background:linear-gradient(100deg,#1D4ED8,#2F86F6); border:1px solid #5B9BFF; box-shadow:0 6px 18px rgba(37,99,235,.35);
}}
.stButton > button[kind="primary"] *, [data-testid="stBaseButton-primaryFormSubmit"] * {{ color:#fff !important; }}
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"], [data-baseweb="select"] > div,
.stTextInput input, .stTextArea textarea, .stNumberInput input, .stDateInput input {{
  background-color:var(--nx-input) !important; color:var(--nx-text) !important; border-color:var(--nx-border2) !important; border-radius:10px;
}}
[data-baseweb="select"] *, [data-baseweb="input"] input, [data-baseweb="textarea"] textarea {{ color:var(--nx-text) !important; }}
input::placeholder, textarea::placeholder {{ color:var(--nx-muted) !important; opacity:.8; }}
[data-baseweb="tag"] {{ background:#2563EB !important; }}
[data-baseweb="tag"] * {{ color:#fff !important; }}
[data-baseweb="popover"] > div, [data-baseweb="menu"], ul[role="listbox"], [data-baseweb="calendar"] {{
  background:var(--nx-card) !important; color:var(--nx-text) !important; border:1px solid var(--nx-border2); border-radius:12px;
}}
[data-baseweb="popover"] li, [data-baseweb="menu"] li, [role="option"] {{ color:var(--nx-text) !important; background:transparent; }}
[data-baseweb="popover"] li:hover, [role="option"]:hover, [role="option"][aria-selected="true"] {{ background:var(--nx-hover) !important; }}
[data-baseweb="calendar"] * {{ color:var(--nx-text); }}
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ border-bottom:1px solid var(--nx-border); gap:.3rem; }}
[data-testid="stTabs"] button[role="tab"] {{ font-weight:650; padding-top:.7rem; padding-bottom:.7rem; }}
[data-testid="stTabs"] button[role="tab"] * {{ color:var(--nx-muted) !important; }}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] * {{ color:var(--nx-primary) !important; }}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background:var(--nx-primary) !important; }}
[data-testid="stExpander"] {{ background:var(--nx-card); border:1px solid var(--nx-border); border-radius:14px; overflow:hidden; box-shadow:var(--nx-shadow); }}
[data-testid="stExpander"] summary:hover {{ background:var(--nx-hover); }}
[data-testid="stMetric"] {{ background:var(--nx-card); border:1px solid var(--nx-border); border-radius:14px; padding:1rem; box-shadow:var(--nx-shadow); }}
[data-testid="stMetricLabel"] * {{ color:var(--nx-muted) !important; }}
[data-testid="stMetricValue"] * {{ color:var(--nx-text) !important; font-weight:800; }}
[data-testid="stPlotlyChart"] {{ background:var(--nx-card); border:1px solid var(--nx-border); border-radius:16px; padding:.5rem .6rem; box-shadow:var(--nx-shadow); animation:nx-rise .5s ease both; }}
[data-testid="stAlert"] {{ border-radius:12px; border:1px solid var(--nx-border2); }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-color:var(--nx-border) !important; }}
[data-testid="stCodeBlock"], pre, code {{ background:var(--nx-card2) !important; color:var(--nx-text) !important; }}
[data-testid="stToast"] {{ background:var(--nx-card); color:var(--nx-text); border:1px solid var(--nx-border2); }}
[data-testid="stNumberInput"] button {{ background:var(--nx-card2); color:var(--nx-text); }}
[data-testid="stForm"] {{ background:var(--nx-card2); border:1px solid var(--nx-border); border-radius:14px; }}

/* ---------- auth screen ---------- */
.nx-auth-brand {{
  position:relative; overflow:hidden; border-radius:24px; padding:2.4rem 2rem; min-height:520px; color:#fff;
  background:radial-gradient(ellipse at 90% 0%, rgba(130,195,255,.5), transparent 50%), linear-gradient(150deg,#0B2C74 0%,#1D4ED8 60%,#2F86F6 100%);
  box-shadow:0 22px 60px rgba(29,78,216,.35); animation:nx-rise .6s ease both;
}}
.nx-auth-brand h1 {{ color:#fff !important; font-size:2.3rem; margin:1.2rem 0 .5rem; letter-spacing:-.05em; }}
.nx-auth-brand p, .nx-auth-brand li, .nx-auth-brand span {{ color:#DCEAFF !important; line-height:1.75; }}
.nx-auth-brand ul {{ padding-left:1.1rem; margin-top:1.2rem; }}

/* ---------- logo ---------- */
.nx-logo-wrap {{ position:relative; width:96px; height:96px; display:flex; align-items:center; justify-content:center; }}
.nx-logo {{
  width:76px; height:84px; clip-path:polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%);
  background:linear-gradient(145deg,#60A5FA,#1D4ED8 70%); display:flex; align-items:center; justify-content:center;
  filter:drop-shadow(0 0 14px rgba(96,165,250,.95)); animation:nx-logo-pulse 2.6s ease-in-out infinite;
}}
.nx-logo span {{ color:#fff !important; font-size:2.1rem; font-weight:800; letter-spacing:-.04em; }}
.nx-logo-ring {{ position:absolute; inset:0; border-radius:50%; border:2px solid transparent; border-top-color:#93C5FD; border-right-color:rgba(147,197,253,.35); animation:nx-spin 2.4s linear infinite; }}

/* ---------- animation ---------- */
@keyframes nx-rise {{ from {{ opacity:0; transform:translateY(12px); }} to {{ opacity:1; transform:none; }} }}
@keyframes nx-spin {{ to {{ transform:rotate(360deg); }} }}
@keyframes nx-logo-pulse {{ 0%,100% {{ filter:drop-shadow(0 0 8px rgba(96,165,250,.7)); }} 50% {{ filter:drop-shadow(0 0 22px rgba(147,197,253,1)); }} }}
[data-testid="stSidebarNav"]::before {{ animation-name:nx-text-glow; }}
@keyframes nx-text-glow {{ 0%,100% {{ text-shadow:0 0 10px rgba(96,165,250,.7), 0 0 22px rgba(59,130,246,.4); }} 50% {{ text-shadow:0 0 20px rgba(147,197,253,1), 0 0 40px rgba(59,130,246,.8); }} }}
[data-testid="stMain"], section.main {{ animation:nx-page-in .35s ease both; }}
@keyframes nx-page-in {{ from {{ opacity:.0; }} to {{ opacity:1; }} }}

@media (max-width:800px) {{
  .block-container {{ padding:1.2rem 1rem 2rem; }}
  .nx-hero {{ border-radius:16px; padding:1.2rem; }}
  .nx-kpi {{ min-height:105px; }}
  .nx-auth-brand {{ min-height:auto; padding:1.6rem 1.3rem; }}
  .nx-tablewrap {{ max-height:480px; }}
  table.nx-table th, table.nx-table td {{ padding:.55rem .6rem; font-size:.78rem; }}
}}
@media (prefers-reduced-motion: reduce) {{ *, *::before, *::after {{ transition:none !important; animation:none !important; }} }}
"""
    if dark:
        css += """
/* ---------- dark-mode overrides for Streamlit's own light-base widgets ---------- */
[data-testid="stAlert"] { background:rgba(59,130,246,.14) !important; }
[data-testid="stAlert"] * { color:#DCE8FF !important; }
[data-testid="stAlert"]:has([data-testid="stAlertContentError"]) { background:rgba(220,38,38,.16) !important; border-color:rgba(248,113,113,.5); }
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) { background:rgba(245,158,11,.15) !important; border-color:rgba(245,158,11,.5); }
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) { background:rgba(34,197,94,.14) !important; border-color:rgba(74,222,128,.45); }
[data-testid="stToolbar"], [data-testid="stDecoration"] { filter:invert(.92) hue-rotate(180deg); }
::-webkit-scrollbar { width:10px; height:10px; } ::-webkit-scrollbar-thumb { background:#274a8c; border-radius:8px; } ::-webkit-scrollbar-track { background:#0A1B3A; }
[data-baseweb="checkbox"] > div:first-child { border-color:#4F78C4 !important; }
[data-testid="stSelectbox"] svg, [data-testid="stMultiSelect"] svg, [data-testid="stDateInput"] svg { fill:#9CC4FF; }
"""
    css += "\n</style>"
    return css


# ---------------------------------------------------------------------------
# INTRO / ENTRY ANIMATION
# ---------------------------------------------------------------------------
_INTRO_CSS = """
<style>
.nx-intro { position:fixed; inset:0; z-index:999999; display:flex; flex-direction:column; align-items:center; justify-content:center;
  background:radial-gradient(ellipse at 50% 38%, #123C93 0%, #07163F 55%, #030A20 100%); pointer-events:none;
  animation:nx-intro-out var(--dur,3.6s) ease forwards; }
.nx-intro .nx-logo-wrap { width:128px; height:128px; opacity:0; animation:nx-pop .9s cubic-bezier(.2,.9,.2,1) .15s forwards; }
.nx-intro .nx-logo { width:100px; height:112px; }
.nx-intro .nx-logo span { font-size:2.9rem; }
.nx-intro-kicker { margin-top:22px; color:#9CC4FF; font-size:12px; font-weight:700; letter-spacing:7px; opacity:0; animation:nx-fade .7s ease .7s forwards; }
.nx-intro-title { margin-top:12px; color:#fff; font-size:clamp(40px,8vw,84px); line-height:1.1; font-weight:800; letter-spacing:6px; opacity:0; transform:translateY(18px);
  text-shadow:0 0 38px rgba(96,165,250,.55); animation:nx-title .95s cubic-bezier(.2,.8,.2,1) .95s forwards; }
.nx-intro-title span { color:#60A5FA; text-shadow:0 0 28px rgba(96,165,250,.9); }
.nx-intro-line { width:0; height:2px; margin-top:22px; background:linear-gradient(90deg,transparent,#60A5FA,#fff,#60A5FA,transparent); box-shadow:0 0 18px #3B82F6; animation:nx-line 1s ease 1.5s forwards; }
.nx-intro-sub { margin-top:18px; color:#A9C4F2; font-size:11px; letter-spacing:4px; text-align:center; opacity:0; animation:nx-fade .7s ease 1.9s forwards; }
.nx-intro-bar { width:min(260px,60vw); height:3px; margin-top:34px; border-radius:3px; background:rgba(255,255,255,.14); overflow:hidden; }
.nx-intro-bar i { display:block; height:100%; width:0; background:linear-gradient(90deg,#3B82F6,#93C5FD); box-shadow:0 0 12px #60A5FA; animation:nx-bar var(--bar,2.6s) ease-in-out .5s forwards; }
@keyframes nx-pop { from { opacity:0; transform:scale(.55) rotate(-12deg); } to { opacity:1; transform:none; } }
@keyframes nx-fade { to { opacity:1; } }
@keyframes nx-title { to { opacity:1; transform:none; } }
@keyframes nx-line { to { width:min(340px,65vw); } }
@keyframes nx-bar { to { width:100%; } }
@keyframes nx-intro-out { 0%,76% { opacity:1; visibility:visible; } 100% { opacity:0; visibility:hidden; } }
@media (prefers-reduced-motion: reduce) { .nx-intro, .nx-intro * { animation-duration:.01ms !important; animation-delay:0ms !important; } }
</style>
"""


def intro_once():
    """Full-screen AICTE NEXUS intro: glowing logo, title reveal, loading bar. Plays once per browser session."""
    if st.session_state.get("_intro_done"):
        return
    st.session_state["_intro_done"] = True
    st.markdown(_h(_INTRO_CSS + """
    <div class="nx-intro" aria-hidden="true">
      <div class="nx-logo-wrap"><div class="nx-logo-ring"></div><div class="nx-logo"><span>N</span></div></div>
      <div class="nx-intro-kicker">AICTE PRESENTS</div>
      <div class="nx-intro-title">AICTE <span>NEXUS</span></div>
      <div class="nx-intro-line"></div>
      <div class="nx-intro-sub">UNIFIED INSTITUTIONAL COMPLAINT INTELLIGENCE</div>
      <div class="nx-intro-bar"><i></i></div>
    </div>"""), unsafe_allow_html=True)


def entry_splash(name: str):
    """Short 'entering the command center' transition shown once right after sign-in."""
    key = st.session_state.get("_session_token")
    if not key or st.session_state.get("_splash_for") == key:
        return
    st.session_state["_splash_for"] = key
    st.markdown(_h(_INTRO_CSS + f"""
    <style>.nx-intro.nx-entry {{ --dur:2.1s; --bar:1.5s; }}
    .nx-intro.nx-entry .nx-intro-title {{ animation-delay:.2s; font-size:clamp(28px,5vw,52px); letter-spacing:3px; }}
    .nx-intro.nx-entry .nx-logo-wrap {{ animation-delay:0s; }} .nx-intro.nx-entry .nx-intro-bar i {{ animation-delay:.2s; }}
    .nx-intro.nx-entry .nx-intro-sub {{ animation-delay:.6s; }}</style>
    <div class="nx-intro nx-entry" aria-hidden="true">
      <div class="nx-logo-wrap"><div class="nx-logo-ring"></div><div class="nx-logo"><span>N</span></div></div>
      <div class="nx-intro-title">Welcome, <span>{html.escape(name.split()[0])}</span></div>
      <div class="nx-intro-sub">OPENING YOUR COMMAND CENTER</div>
      <div class="nx-intro-bar"><i></i></div>
    </div>"""), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# STREAMLIT COMPATIBILITY
# ---------------------------------------------------------------------------
_STRETCH_MODE = None


def _stretch(fn, *args, **kwargs):
    """Call a Streamlit element full-width across old/new Streamlit versions."""
    global _STRETCH_MODE
    modes = ["old"] if _STRETCH_MODE == "old" else ["new", "old"]
    for mode in modes:
        extra = {"width": "stretch"} if mode == "new" else {"use_container_width": True}
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
    """Initialise the database (+ demo accounts, suggestions) and inject the active theme's CSS."""
    db.init_db()
    accounts.seed_users()
    if db.count_relationships() == 0 and db.count_complaints() > 0:
        intel.refresh_suggestions(actor="System", log=True)
    st.session_state["_tbl_n"] = 0
    st.markdown(build_css(theme()), unsafe_allow_html=True)


def sidebar_footer():
    with st.sidebar:
        st.markdown('<div class="nx-card" style="margin-top:1rem;background:rgba(255,255,255,.08);'
                    'border-color:rgba(255,255,255,.2);box-shadow:none">'
                    '<span class="nx-pill">Prototype · Synthetic data</span>'
                    '<p class="nx-muted" style="margin:.6rem 0 0;color:#B7CCF3 !important">'
                    'Demonstration build. All institutions, complaints and officers are fictional.</p></div>',
                    unsafe_allow_html=True)


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
    st.session_state["_flash"] = (kind, msg)


def show_flash():
    message = st.session_state.pop("_flash", None)
    if message:
        {"success": st.success, "error": st.error, "warning": st.warning}.get(message[0], st.info)(message[1])


def result(ok: bool, msg: str, rerun: bool = True):
    """Standard handling for an (ok, msg) result from the database layer."""
    if ok:
        flash("success", msg)
        if rerun:
            st.rerun()
    else:
        st.error(msg)


def page_header(title: str, subtitle: str):
    user = st.session_state.get("user")
    who = (f"{e(user['full_name'])} · {e(user['role'])}" + (f" · {e(user['bureau'])}" if user.get("bureau") else "")
           if user else "Prototype Demonstration — Synthetic Data")
    st.markdown(_h(f"""
    <div class="nx-head"><div><p class="nx-title">{e(title)}</p><p class="nx-sub">{e(subtitle)}</p></div>
    <span class="nx-pill">{who}</span></div>"""), unsafe_allow_html=True)
    show_flash()


def banner(text: str, kind: str = "info"):
    """Information / warning banner. ``text`` may contain trusted inline HTML such as <b>."""
    st.markdown(f'<div class="nx-banner {kind}">{text}</div>', unsafe_allow_html=True)


def empty_state(msg: str, hint: str = ""):
    st.markdown(_h(f'<div class="nx-empty"><b>{e(msg)}</b><br>{e(hint)}</div>'), unsafe_allow_html=True)


def badge(text, color) -> str:
    c = html.escape(str(color))
    return (f'<span class="nx-badge" style="color:{c};color:color-mix(in srgb,{c} 70%,var(--nx-text));'
            f'background:{c}22;border-color:{c}66">{e(text)}</span>')


def status_badge(status):
    return badge(status, STATUS_COLORS.get(status, "#64748B"))


def priority_badge(priority):
    return badge(priority, PRIORITY_COLORS.get(priority, "#64748B"))


def role_badge(role):
    return badge(role, ROLE_COLORS.get(role, "#64748B"))


def kpi(label: str, value, sub: str = "", accent: str = BLUE):
    """Filled KPI box."""
    st.markdown(_h(f"""
    <div class="nx-kpi" style="--accent:{html.escape(str(accent))}"><div class="nx-kpi-label">{e(label)}</div>
    <div class="nx-kpi-value">{e(value)}</div><div class="nx-kpi-sub">{e(sub)}</div></div>"""),
                unsafe_allow_html=True)


def fmt_date(value) -> str:
    if value is None:
        return "—"
    if not isinstance(value, str) and pd.isna(value):
        return "—"
    try:
        return pd.Timestamp(value).strftime("%d %b %Y")
    except Exception:
        return str(value)


def html_table(df: pd.DataFrame, spec: list, empty: str = "Nothing to show."):
    """Styled HTML table. spec = [(column, label, kind)]; kinds: text, status, priority, date, overdue,
    confidence, review."""
    if df is None or df.empty:
        empty_state(empty)
        return
    head = "".join(f"<th>{e(label)}</th>" for _, label, _ in spec)
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
                cell = badge(value, CONFIDENCE_COLORS.get(value, "#64748B"))
            elif kind == "review":
                cell = badge(value, REVIEW_COLORS.get(value, "#64748B"))
            elif kind == "date":
                cell = e(fmt_date(value))
            elif kind == "overdue":
                try:
                    days = int(value)
                except (TypeError, ValueError):
                    days = 0
                cell = f'<span class="nx-over">{days} d</span>' if days > 0 else "—"
            else:
                safe = e(value)
                cell = safe if len(safe) <= 90 else safe[:87] + "…"
            cells.append(f"<td>{cell}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    st.markdown(_h(f'<div class="nx-tablewrap"><table class="nx-table"><thead><tr>{head}</tr></thead>'
                   f'<tbody>{"".join(rows)}</tbody></table></div>'), unsafe_allow_html=True)


def _cell(v) -> str:
    if v is None or (not isinstance(v, (str, list, tuple)) and pd.isna(v)):
        return "—"
    if isinstance(v, (pd.Timestamp, dt.datetime)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    s = str(v)
    return s if len(s) <= 160 else s[:157] + "…"


def show_table(df: pd.DataFrame, page_size: int = 25, **_ignored):
    """Themed, paginated table for arbitrary DataFrames (replaces st.dataframe so it follows Light/Dark)."""
    if df is None or df.empty:
        empty_state("Nothing to show.")
        return
    n = st.session_state.get("_tbl_n", 0)
    st.session_state["_tbl_n"] = n + 1
    total = len(df)
    if total > page_size:
        c = st.columns([1, 1, 3])
        size = c[0].selectbox("Rows per page", [25, 50, 100, 250], index=0, key=f"_tbl_size_{n}")
        pages = max(1, -(-total // size))
        page = int(c[1].number_input("Page", min_value=1, max_value=pages, value=1, key=f"_tbl_page_{n}"))
        c[2].caption(f"Showing {min(total, (page - 1) * size + 1)}–{min(total, page * size)} of {total} rows")
        view = df.iloc[(page - 1) * size: page * size]
    else:
        view = df
    head = "".join(f"<th>{e(c)}</th>" for c in view.columns)
    body = "".join("<tr>" + "".join(f"<td>{e(_cell(v))}</td>" for v in row) + "</tr>"
                   for row in view.itertuples(index=False, name=None))
    st.markdown(_h(f'<div class="nx-tablewrap"><table class="nx-table"><thead><tr>{head}</tr></thead>'
                   f'<tbody>{body}</tbody></table></div>'), unsafe_allow_html=True)


def export_button(label, data, file_name, mime="text/csv", key=None, what=None):
    """Download button that records the export in the audit trail ("who downloaded what")."""
    def _log():
        try:
            with db.get_conn() as conn:
                db.log_audit(conn, "EXPORT_GENERATED", "Export", file_name, None, mime.split("/")[-1],
                             what or label, db.default_actor())
        except Exception:
            pass
    return st.download_button(label, data, file_name, mime, key=key, on_click=_log)


def show_plot(fig, key=None):
    """Display a full-width Plotly chart with a unique key."""
    key = key or "nexus_chart"
    st.session_state["_nexus_chart_instance"] = st.session_state.get("_nexus_chart_instance", 0) + 1
    _stretch(st.plotly_chart, fig, key=f"{key}_{st.session_state['_nexus_chart_instance']}")


def style_fig(fig, height=320, title=None):
    """Apply the active (light/dark) Blue & White theme to a Plotly figure."""
    t = THEMES[theme()]
    fig.update_layout(
        template=t["plot"], paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=t["text"], family=FONT), height=height, margin=dict(l=12, r=12, t=50, b=12),
        colorway=BUREAU_PALETTE, legend=dict(bgcolor="rgba(0,0,0,0)", title_text=""),
        title=dict(text=title, font=dict(size=15, color=t["text"]), x=0.02) if title else None)
    fig.update_xaxes(gridcolor=t["grid"], zerolinecolor=t["grid"], title_text=None, linecolor=t["grid"])
    fig.update_yaxes(gridcolor=t["grid"], zerolinecolor=t["grid"], title_text=None, linecolor=t["grid"])
    return fig


def complaint_table_df(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare a readable complaint table with status and priority markers."""
    cols = ["ID", "Institution", "Title", "Bureau", "Category", "Priority", "Status", "Officer", "Received", "Due",
            "Updated", "Days overdue"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame({
        "ID": df["complaint_id"], "Institution": df["institution_name"], "Title": df["title"],
        "Bureau": df["bureau"], "Category": df["category"],
        "Priority": df["priority"].map(lambda p: f"{PRIORITY_EMOJI.get(p, '')} {p}"),
        "Status": df["status"].map(lambda s: f"{STATUS_EMOJI.get(s, '')} {s}"),
        "Officer": df["assigned_officer"], "Received": df["date_received"].dt.strftime("%Y-%m-%d"),
        "Due": df["due_date"].dt.strftime("%Y-%m-%d"), "Updated": df["last_updated"].dt.strftime("%Y-%m-%d"),
        "Days overdue": df["days_overdue"]})


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
            change = f"{e(row.previous_value or '—')[:80]} → {e(row.new_value or '—')[:80]}"
        items.append(f'<div class="nx-tl-item"><div class="nx-tl-title">{e(title)}</div>'
                     f'<div class="nx-tl-meta">{e(row.ts)} · {e(row.actor)}</div><div>{change}</div>'
                     f'<div class="nx-muted">{e((row.details or "")[:240])}</div></div>')
    st.markdown(f'<div class="nx-tl">{"".join(items)}</div>', unsafe_allow_html=True)


def status_stepper(status: str):
    """Progress tracker: Submitted → Under Review → In Progress → Resolved / Closed."""
    flow = ["Submitted", "Under Review", "In Progress", "Resolved", "Closed"]
    labels = {"Awaiting Information": "Awaiting Information"}
    if status == "Awaiting Information":
        flow = ["Submitted", "Under Review", "Awaiting Information", "In Progress", "Resolved", "Closed"]
    idx = flow.index(status) if status in flow else 0
    parts = []
    for i, s in enumerate(flow):
        cls = "done" if i < idx else "now" if i == idx else ""
        parts.append(f'<div class="nx-step {cls}">{"✓ " if i < idx else ""}{e(labels.get(s, s))}</div>')
    st.markdown(f'<div class="nx-steps">{"".join(parts)}</div>', unsafe_allow_html=True)


def alert_strip(alerts: dict, show_mine: bool = True):
    """Compact deadline / overdue / critical alert chips."""
    chips = []
    if alerts["overdue"]:
        chips.append(f'<span class="nx-chip red">🔴 <b>{alerts["overdue"]}</b> overdue'
                     + (f' <span>({alerts["high_overdue"]} High/Critical)</span>' if alerts["high_overdue"] else "") + "</span>")
    if alerts["due_soon"]:
        chips.append(f'<span class="nx-chip amber">⏰ <b>{alerts["due_soon"]}</b> due soon</span>')
    if alerts["critical"]:
        chips.append(f'<span class="nx-chip red">🚨 <b>{alerts["critical"]}</b> Critical open</span>')
    if show_mine and (alerts["mine_overdue"] or alerts["mine_due_soon"]):
        chips.append(f'<span class="nx-chip blue">👤 Assigned to you: <b>{alerts["mine_overdue"]}</b> overdue · '
                     f'<b>{alerts["mine_due_soon"]}</b> due soon</span>')
    if not chips:
        chips.append('<span class="nx-chip blue">✅ No overdue, deadline or critical alerts in your scope</span>')
    st.markdown(f'<div class="nx-alerts">{"".join(chips)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# FILTERS
# ---------------------------------------------------------------------------
def date_range_filter(label: str, lo: dt.date, hi: dt.date, key: str):
    """Render a date-range selector."""
    if lo > hi:
        lo = hi
    value = st.date_input(label, value=(lo, hi), min_value=dt.date(2020, 1, 1), max_value=dt.date(2035, 12, 31), key=key)
    if isinstance(value, (tuple, list)):
        if len(value) == 2:
            return value[0], value[1]
        if len(value) == 1:
            return value[0], hi
        return lo, hi
    return value, value


def inst_label(options):
    names = dict(options)
    return lambda institution_id: f"{names.get(institution_id, institution_id)} ({institution_id})"


def global_filters(prefix: str, all_df: pd.DataFrame, show_status=True, show_institution=True, show_priority=True,
                   show_state=True) -> dict:
    """Standard filter bar. Returns a dictionary compatible with db.list_complaints()."""
    if not all_df.empty:
        lo = all_df["date_received"].min().date()
        hi = max(all_df["date_received"].max().date(), db.today())
    else:
        lo = hi = db.today()
    filters = {}
    with st.expander("Filters", expanded=True):
        columns = st.columns(3)
        with columns[0]:
            filters["date_from"], filters["date_to"] = date_range_filter("Date received", lo, hi, f"{prefix}_dates")
        user = st.session_state.get("user") or {}
        if user.get("role") == "Bureau Officer":
            columns[1].markdown(f"**Bureau / cell**  \n{user.get('bureau')} (your bureau)")
            filters["bureaus"] = []
        else:
            filters["bureaus"] = columns[1].multiselect("Bureau / cell", db.BUREAUS, key=f"{prefix}_bureau")
        if show_state:
            states = sorted(all_df["state"].unique()) if not all_df.empty else []
            filters["states"] = columns[2].multiselect("State", states, key=f"{prefix}_state")
        columns2 = st.columns(3)
        if show_institution:
            options = db.institution_options()
            filters["institution_ids"] = columns2[0].multiselect(
                "Institution", [i for i, _ in options], format_func=inst_label(options), key=f"{prefix}_inst")
        if show_status:
            filters["statuses"] = columns2[1].multiselect("Status", db.STATUSES, key=f"{prefix}_status")
        if show_priority:
            filters["priorities"] = columns2[2].multiselect("Priority", db.PRIORITIES, key=f"{prefix}_prio")
    return filters
