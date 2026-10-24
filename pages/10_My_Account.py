"""My Account: profile, role & permissions, change password."""
import pandas as pd
import streamlit as st

import accounts
import auth
import database as db
import ui

user = auth.require()
ui.page_header("My Account", "Your profile, what your role may do, and password management.")
st.markdown(f"""<div class="nx-card"><h4>{ui.e(user['full_name'])}</h4>{ui.role_badge(user['role'])}
<p class="nx-muted" style="margin:.6rem 0 0">@{ui.e(user['username'])} · {ui.e(user['email'])} ·
Scope: {ui.e(user.get('bureau') or 'All bureaus')} · Last sign-in: {ui.e(user.get('last_login') or '—')}</p></div>""",
            unsafe_allow_html=True)

st.markdown("#### What your role can do")
rows = [(label, "✅ Yes" if db.has_perm(perm, user) else "— No") for perm, (_, label) in db.PERMISSIONS.items()]
ui.html_table(pd.DataFrame(rows, columns=["Action", "Allowed"]), [("Action", "Action", "text"), ("Allowed", "Allowed", "text")])
if user["role"] == "Bureau Officer":
    st.caption("Bureau officers see and update only their own bureau's complaints.")

st.markdown("#### Change password")
with st.form("chg_pw"):
    old = st.text_input("Current password", type="password", max_chars=128)
    new = st.text_input("New password", type="password", max_chars=128)
    new2 = st.text_input("Confirm new password", type="password", max_chars=128)
    go = st.form_submit_button("Change password", type="primary")
if go:
    if new != new2:
        st.error("The two passwords do not match.")
    else:
        ok, msg = accounts.change_password(user["user_id"], old, new)
        if ok:
            st.success(msg + " Signing you out…")
            auth.sign_out()
        else:
            st.error(msg)
