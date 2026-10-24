"""Streamlit glue for authentication: session check, login / registration screens, page guards, sidebar account."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import accounts
import database as db
import intelligence as intel
import ui

_KEEP_ON_LOGOUT = ("theme", "_intro_done", "_theme_tgl")


# --------------------------------------------------------------------------- #
# Session handling
# --------------------------------------------------------------------------- #
def authenticate_session():
    """Validate the server-side session on EVERY script run and set the data-layer user context."""
    token = st.session_state.get("_session_token")
    user = accounts.validate_session(token) if token else None
    if token and not user:
        st.session_state.pop("_session_token", None)
        ui.flash("warning", "Your session ended (timeout or sign-out elsewhere). Please sign in again.")
    st.session_state["user"] = user
    db.set_current_user(user)
    return user


def sign_in(user: dict):
    st.session_state["_session_token"] = accounts.create_session(user["user_id"])
    st.session_state["user"] = user
    st.session_state["theme"] = user.get("theme", "light")
    st.session_state.pop("_toasted", None)


def sign_out():
    token, user = st.session_state.get("_session_token"), st.session_state.get("user")
    accounts.end_session(token, user)
    for k in list(st.session_state.keys()):
        if k not in _KEEP_ON_LOGOUT:
            st.session_state.pop(k, None)
    db.set_current_user(None)
    st.rerun()


def require(permission: str | None = None):
    """First line of every page script. Defence in depth: refuses to render without a verified session."""
    user = db.current_user()
    if user is None:
        st.warning("Please sign in to continue.")
        st.stop()
    if permission and not db.has_perm(permission, user):
        label = db.PERMISSIONS[permission][1]
        ui.banner(f"<b>Access denied.</b> Your role ({ui.e(user['role'])}) is not permitted to {ui.e(label)}.", "danger")
        st.stop()
    return user


def me() -> dict:
    return db.current_user() or st.session_state.get("user") or {}


# --------------------------------------------------------------------------- #
# Screens
# --------------------------------------------------------------------------- #
def _brand_panel():
    st.markdown(ui._h("""
    <div class="nx-auth-brand">
      <div class="nx-logo-wrap"><div class="nx-logo-ring"></div><div class="nx-logo"><span>N</span></div></div>
      <h1>AICTE NEXUS</h1>
      <p>One institution. Multiple bureaus. One unified view.</p>
      <ul>
        <li>Secure, role-based access for Admin, Senior and Bureau officers</li>
        <li>Cross-bureau complaint intelligence with human verification</li>
        <li>Deadline alerts, risk monitoring and a tamper-evident audit trail</li>
      </ul>
      <p style="margin-top:2rem;font-size:.8rem;opacity:.85">Prototype demonstration — synthetic data only.</p>
    </div>"""), unsafe_allow_html=True)


def login_screen():
    """Sign in / Register / Verify email."""
    top = st.columns([5, 1.3])
    with top[1]:
        ui.theme_toggle()
    left, right = st.columns([1.05, 1], gap="large")
    with left:
        _brand_panel()
    with right:
        ui.show_flash()
        tab_in, tab_reg, tab_ver = st.tabs(["Sign in", "Register", "Verify email"])
        with tab_in:
            st.markdown("#### Welcome back")
            with st.form("login_form"):
                ident = st.text_input("Username or email", key="li_user", max_chars=120, autocomplete="username")
                pw = st.text_input("Password", type="password", key="li_pass", max_chars=128,
                                   autocomplete="current-password")
                go = st.form_submit_button("Sign in", type="primary")
            if go:
                if not ident.strip() or not pw:
                    st.error("Enter your username and password.")
                else:
                    ok, user, msg = accounts.authenticate(ident, pw)
                    if ok:
                        sign_in(user)
                        st.rerun()
                    else:
                        st.error(msg)
            st.caption(f"Sessions end after {accounts.IDLE_MINUTES} minutes without activity.")
            if accounts.demo_mode():
                with st.expander("Demo accounts (synthetic) — for the SIH demonstration"):
                    st.markdown(f"All demo accounts use the password **`{accounts.DEMO_PASSWORD}`**.")
                    ui.html_table(
                        pd.DataFrame(
                            [(u, n, r, b or "All bureaus") for u, n, r, b in accounts.DEMO_USERS],
                            columns=["Username", "Name", "Role", "Bureau"]),
                        [("Username", "Username", "text"), ("Name", "Name", "text"), ("Role", "Role", "text"),
                         ("Bureau", "Bureau", "text")])
                    st.caption("Set NEXUS_DEMO_MODE=0 to hide this panel and skip creating demo accounts "
                               "on a fresh database.")
        with tab_reg:
            st.markdown("#### Create an officer account")
            st.caption("New accounts are Bureau Officers. An Admin can grant a higher role afterwards. "
                       "You must verify your email before the first sign-in.")
            with st.form("register_form"):
                r1 = st.columns(2)
                rname = r1[0].text_input("Full name *", max_chars=80, key="rg_name")
                ruser = r1[1].text_input("Username *", max_chars=32, key="rg_user",
                                         help="3-32 characters; letters, digits, . _ -")
                remail = st.text_input("Official email *", max_chars=120, key="rg_email")
                rbureau = st.selectbox("Bureau / cell *", db.BUREAUS, key="rg_bureau")
                r2 = st.columns(2)
                rpw = r2[0].text_input("Password *", type="password", max_chars=128, key="rg_pw",
                                       help="8+ characters with upper & lower case, a digit and a symbol")
                rpw2 = r2[1].text_input("Confirm password *", type="password", max_chars=128, key="rg_pw2")
                reg = st.form_submit_button("Create account", type="primary")
            if reg:
                if rpw != rpw2:
                    st.error("The two passwords do not match.")
                else:
                    ok, msg, code = accounts.register_user(ruser, rname, remail, rpw, rbureau)
                    if ok:
                        st.session_state["_verify_id"] = ruser.strip()
                        st.success(msg + " Open the **Verify email** tab next.")
                        if code:
                            ui.banner(f"<b>Demo mode:</b> your verification code is <b>{code}</b> "
                                      "(valid for 30 minutes). In production it is sent by email only.", "info")
                    else:
                        st.error(msg)
        with tab_ver:
            st.markdown("#### Verify your email")
            with st.form("verify_form"):
                vid = st.text_input("Username or email", value=st.session_state.get("_verify_id", ""),
                                    max_chars=120, key="vf_id")
                vcode = st.text_input("6-digit code", max_chars=6, key="vf_code")
                vgo = st.form_submit_button("Verify", type="primary")
            if vgo:
                ok, msg = accounts.verify_email(vid, vcode)
                (st.success if ok else st.error)(msg)
            if st.button("Send a new code", key="vf_resend"):
                ok, msg, code = accounts.resend_verification(st.session_state.get("vf_id") or vid)
                st.info(msg)
                if code:
                    ui.banner(f"<b>Demo mode:</b> your new verification code is <b>{code}</b>.", "info")


def password_change_screen(user: dict):
    """Forced after an admin reset or first login with a temporary password."""
    st.markdown("### Set a new password")
    ui.banner("Your account uses a temporary password. Choose a new one to continue.", "warn")
    with st.form("force_pw_form"):
        a = st.text_input("New password", type="password", max_chars=128, key="fp_new")
        b = st.text_input("Confirm new password", type="password", max_chars=128, key="fp_new2")
        go = st.form_submit_button("Save password", type="primary")
    if go:
        if a != b:
            st.error("The two passwords do not match.")
        else:
            ok, msg = accounts.force_change_password(user["user_id"], a)
            if ok:
                st.session_state["user"] = dict(user, must_change_password=0)
                ui.flash("success", msg)
                st.rerun()
            else:
                st.error(msg)
    if st.button("Sign out", key="fp_out"):
        sign_out()


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
def sidebar_account(alerts: dict | None = None):
    user = me()
    if not user:
        return
    with st.sidebar:
        scope = user.get("bureau") or "All bureaus"
        st.markdown(ui._h(f"""
        <div class="nx-card" style="background:rgba(255,255,255,.10);border-color:rgba(255,255,255,.22);box-shadow:none;margin:.6rem 0">
        <div style="font-weight:800;font-size:1rem;color:#fff">{ui.e(user['full_name'])}</div>
        <div style="margin:.4rem 0">{ui.role_badge(user['role'])}</div>
        <div style="font-size:.78rem;color:#B7CCF3">{ui.e(scope)}</div>
        <div style="font-size:.7rem;color:#8FB0EC;margin-top:.3rem">@{ui.e(user['username'])}</div></div>"""),
                    unsafe_allow_html=True)
        if alerts:
            chips = []
            if alerts["overdue"]:
                chips.append(f"🔴 {alerts['overdue']} overdue")
            if alerts["due_soon"]:
                chips.append(f"⏰ {alerts['due_soon']} due soon")
            if alerts["critical"]:
                chips.append(f"🚨 {alerts['critical']} critical")
            if chips:
                st.caption("  ·  ".join(chips))
        ui.theme_toggle()
        if ui._stretch(st.button, "Sign out", key="sb_signout"):
            sign_out()


def alerts_for(user: dict) -> dict:
    """Alerts within the user's own scope (data layer applies the bureau scope)."""
    return intel.compute_alerts(db.list_complaints(), db.get_settings(), user.get("full_name"))
