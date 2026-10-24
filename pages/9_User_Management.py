"""User management (Admin only): create users, change roles, deactivate, reset passwords, unlock."""
import pandas as pd
import streamlit as st

import accounts
import auth
import database as db
import ui

user = auth.require("users.manage")
ui.page_header("User Management", "Create accounts, assign roles and bureaus, and control access. Every change is audited.")

users = accounts.list_users()
k = st.columns(4)
with k[0]: ui.kpi("Users", len(users), "accounts", ui.BLUE)
with k[1]: ui.kpi("Admins / Senior", int(users["role"].isin(["Admin", "Senior Officer"]).sum()), "elevated roles", ui.PURPLE)
with k[2]: ui.kpi("Unverified email", int((users["email_verified"] == 0).sum()), "cannot sign in yet", ui.WARNING)
with k[3]: ui.kpi("Deactivated", int((users["is_active"] == 0).sum()), "blocked", ui.DANGER)
st.write("")

t_list, t_new, t_edit = st.tabs(["All users", "Create user", "Edit / reset"])
with t_list:
    view = users.assign(email_verified=users["email_verified"].map({1: "Yes", 0: "No"}),
                        is_active=users["is_active"].map({1: "Active", 0: "Deactivated"}),
                        must_change_password=users["must_change_password"].map({1: "Yes", 0: "No"}))
    view = view.rename(columns={"user_id": "ID", "username": "Username", "full_name": "Name", "email": "Email",
                                "role": "Role", "bureau": "Bureau", "email_verified": "Email verified",
                                "is_active": "State", "must_change_password": "Must change pw",
                                "locked_until": "Locked until", "created_at": "Created", "last_login": "Last sign-in"})
    ui.show_table(view)

with t_new:
    st.caption("Admin-created accounts are pre-verified and get a temporary password that must be changed at first sign-in.")
    with st.form("admin_new_user"):
        a = st.columns(2)
        nu = a[0].text_input("Username *", max_chars=32)
        nn = a[1].text_input("Full name *", max_chars=80)
        b = st.columns(3)
        ne = b[0].text_input("Email *", max_chars=120)
        nr = b[1].selectbox("Role *", db.ROLES, index=2)
        nb = b[2].selectbox("Bureau (Bureau Officers)", db.BUREAUS)
        go = st.form_submit_button("Create user", type="primary")
    if go:
        ok, msg, temp = accounts.admin_create_user(nu, nn, ne, nr, nb)
        if ok:
            st.success(msg)
            ui.banner(f"Temporary password (shown once): <b>{ui.e(temp)}</b>", "warn")
        else:
            st.error(msg)

with t_edit:
    if users.empty:
        st.stop()
    labels = {int(r.user_id): f"{r.full_name} (@{r.username}) · {r.role}" for r in users.itertuples()}
    uid = st.selectbox("User", list(labels), format_func=lambda i: labels[i], key="um_sel")
    row = users[users["user_id"] == uid].iloc[0]
    with st.form(f"um_edit_{uid}"):
        c = st.columns(3)
        role = c[0].selectbox("Role", db.ROLES, index=db.ROLES.index(row["role"]))
        bureau = c[1].selectbox("Bureau", db.BUREAUS,
                                index=db.BUREAUS.index(row["bureau"]) if row["bureau"] in db.BUREAUS else 0)
        active = c[2].checkbox("Account active", value=bool(row["is_active"]))
        save = st.form_submit_button("Save changes", type="primary")
    if save:
        ui.result(*accounts.admin_update_user(int(uid), role, bureau, active))
    b = st.columns(2)
    if b[0].button("Reset password", key=f"um_reset_{uid}"):
        ok, msg, temp = accounts.admin_reset_password(int(uid))
        if ok:
            st.success(msg)
            ui.banner(f"Temporary password (shown once): <b>{ui.e(temp)}</b>", "warn")
        else:
            st.error(msg)
    if b[1].button("Unlock account", key=f"um_unlock_{uid}"):
        ui.result(*accounts.unlock_user(int(uid)))
