"""AICTE NEXUS — secure, role-based institutional complaint intelligence platform (entry point)."""

import streamlit as st

import auth
import database as db
import ui

st.set_page_config(
    page_title="AICTE NEXUS | Intelligence Command Center",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "**AICTE NEXUS**\n\nUnified institutional complaint intelligence, cross-bureau case "
                         "matching and risk monitoring.\n\nPrototype demonstration using synthetic data only."},
)

# Theme must be known before any CSS is injected (the toggle stores it in session_state).
st.session_state.setdefault("theme", "light")
ui.bootstrap()                       # database, demo accounts, theme CSS
ui.intro_once()                      # premium AICTE NEXUS intro (once per browser session)

user = auth.authenticate_session()   # validates the server-side session on every run

if user is None:
    # Signed out: only the login page exists; the sidebar is hidden and no other page can be reached.
    st.markdown("<style>[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl']{display:none}</style>",
                unsafe_allow_html=True)
    login_page = st.Page(auth.login_screen, title="Sign in", icon="🔐", default=True, url_path="login")
    try:
        nav = st.navigation([login_page], position="hidden")
    except TypeError:  # older Streamlit without position=
        nav = st.navigation([login_page])
    nav.run()
    st.stop()

if user.get("must_change_password"):
    auth.password_change_screen(user)
    st.stop()

# ----- signed in -----
ui.entry_splash(user["full_name"])
alerts = auth.alerts_for(user)
if not st.session_state.get("_toasted"):
    st.session_state["_toasted"] = True
    if alerts["overdue"] or alerts["due_soon"]:
        st.toast(f"{alerts['overdue']} overdue · {alerts['due_soon']} due soon in your scope", icon="⏰")

P = st.Page
workspace = [
    P("pages/0_Overview.py", title="Command Center", icon="📊", default=True),
    P("pages/1_Institution_Directory.py", title="Institution Directory", icon="🏛️"),
    P("pages/2_Complaint_Management.py", title="Complaint Management", icon="📁"),
]
intelligence = [
    P("pages/3_Cross_Bureau_Intelligence.py", title="Cross-Bureau Intelligence", icon="🔗"),
    P("pages/4_Risk_Monitoring.py", title="Risk Monitoring", icon="🛡️"),
    P("pages/5_Analytics_Reports.py", title="Analytics & Reports", icon="📈"),
    P("pages/8_AI_Assistant.py", title="NEXUS AI Assistant", icon="🤖"),
]
governance = [P("pages/6_Audit_Trail.py", title="Audit Trail", icon="🧾")]
if db.has_perm("settings.write", user):
    governance.append(P("pages/7_Settings.py", title="Settings", icon="⚙️"))
if db.has_perm("users.manage", user):
    governance.append(P("pages/9_User_Management.py", title="User Management", icon="👥"))
governance.append(P("pages/10_My_Account.py", title="My Account", icon="🔑"))

navigation = st.navigation({"Workspace": workspace, "Intelligence": intelligence, "Governance": governance})

auth.sidebar_account(alerts)
ui.sidebar_footer()
navigation.run()
