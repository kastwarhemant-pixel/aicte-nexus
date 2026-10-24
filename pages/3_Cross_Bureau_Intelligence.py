"""Cross-Bureau Intelligence: explainable suggestions that an officer must review."""
import streamlit as st

import auth
import database as db
import intelligence as intel
import ui

user = auth.require()
can_review = db.has_perm("relationship.review", user)

ui.page_header("Cross-Bureau Intelligence",
               "Suggested links between complaints about the same institution handled by different bureaus.")
ui.banner("<b>Explainable prototype, not a production-validated AI model.</b> Scores are heuristic similarity "
          "indicators, not probabilities. Nothing is merged or closed automatically: a Senior Officer or Admin must "
          "verify each relationship (human verification). Runs fully offline.", "warn")
if user["role"] == "Bureau Officer":
    ui.banner(f"You see suggestions that involve at least one complaint of your bureau ({ui.e(user['bureau'])}). "
              "Verification is done by Senior Officers.", "info")
actor = db.default_actor()
settings = db.get_settings()

top = st.columns([1, 3])
if db.has_perm("relationship.refresh", user) and top[0].button("Refresh suggestions", type="primary", key="ci_refresh"):
    with st.spinner("Comparing complaints across bureaus…"):
        res = intel.refresh_suggestions(actor)
    ui.flash("success", f"Matching complete: {res['candidates']} candidate pair(s), {res['new']} new. "
                        "Existing review decisions were not changed.")
    st.rerun()
top[1].caption(f"Gate: same institution and different bureaus · minimum score {settings['match_min_score']} · "
               f"Medium ≥ {settings['match_medium_score']} · High ≥ {settings['match_high_score']} (demo thresholds, editable in Settings)")
ui.show_flash()

allrel = db.list_relationships()
k = st.columns(4)
with k[0]: ui.kpi("Suggestions", len(allrel), "stored pairs", ui.BLUE)
with k[1]: ui.kpi("Pending review", int((allrel["review_status"] == "Pending").sum()) if len(allrel) else 0, "need an officer", ui.WARNING)
with k[2]: ui.kpi("Confirmed related", int((allrel["review_status"] == "Related").sum()) if len(allrel) else 0, "officer decision", ui.SUCCESS)
with k[3]: ui.kpi("Dismissed", int((allrel["review_status"] == "Dismissed").sum()) if len(allrel) else 0, "officer decision", "#64748B")
st.write("")

with st.expander("Institutions with open complaints in several bureaus"):
    cdf = db.list_complaints({"only_open": True})
    if cdf.empty:
        ui.empty_state("No open complaints.")
    else:
        g = (cdf.groupby(["institution_id", "institution_name"])
             .agg(bureaus=("bureau", "nunique"), open_complaints=("complaint_id", "count"))
             .reset_index())
        g = g[g["bureaus"] > 1].sort_values(["bureaus", "open_complaints"], ascending=False)
        ui.html_table(g, [("institution_id", "ID", "text"), ("institution_name", "Institution", "text"),
                          ("bureaus", "Bureaus", "text"), ("open_complaints", "Open complaints", "text")],
                      "No institution has open complaints in more than one bureau.")

with st.expander("How the score works"):
    st.markdown(f"""
A pair is considered only when both complaints belong to the **same institution** and sit in **different bureaus**,
and share at least one meaningful keyword. The heuristic score (0 to 1) is a weighted sum:

- **{intel.W_TEXT:.2f} × text similarity**: TF-IDF cosine on title + description (title counts double), scaled so a cosine of {intel.TEXT_SATURATION} counts as 1.0
- **{intel.W_KEYWORD:.2f} × keyword overlap**: shared meaningful terms relative to all terms used
- **{intel.W_DATE:.2f} × date proximity**: full credit when received together, none beyond the window ({settings['match_date_window_days']} days)
- **{intel.W_CATEGORY:.2f} × same category**

Confidence labels (High / Medium / Low) are fixed score bands for triage. They are **not** statistical probabilities
and have not been validated against real cases.""")

f = st.columns([1.2, 1.2, 1.6, 1])
conf = f[0].multiselect("Confidence", ["High", "Medium", "Low"], default=["High", "Medium", "Low"], key="ci_conf")
stat = f[1].multiselect("Review status", ["Pending", "Related", "Dismissed"], default=["Pending"], key="ci_stat")
opts = db.institution_options()
inst = f[2].selectbox("Institution", [""] + [i for i, _ in opts],
                      format_func=lambda i: "All institutions" if i == "" else ui.inst_label(opts)(i), key="ci_inst")
active = f[3].checkbox("Active cases only", value=False, key="ci_active",
                       help="Hide pairs where either complaint is already Resolved or Closed.")
rel = db.list_relationships(conf, stat, active, inst or None)

tab_cards, tab_table = st.tabs(["Review suggestions", "Table and export"])
with tab_cards:
    if rel.empty:
        ui.empty_state("No suggestions match these filters.",
                       "Change the review status filter, or click Refresh suggestions.")
    else:
        limit = st.number_input("Show top", min_value=5, max_value=200, value=15, step=5, key="ci_limit")
        st.caption(f"Showing {min(int(limit), len(rel))} of {len(rel)} suggestions, highest score first.")
        for r in rel.head(int(limit)).itertuples():
            title = (f"{r.complaint_a} ↔ {r.complaint_b} · {r.institution_name} · "
                     f"score {r.similarity_score:.2f} · {r.confidence} · {r.review_status}")
            with st.expander(title):
                ca, cb = st.columns(2)
                for col, cid, bur, ttl, desc, stt, pr, rec in (
                        (ca, r.complaint_a, r.bureau_a, r.title_a, r.desc_a, r.status_a, r.priority_a, r.received_a),
                        (cb, r.complaint_b, r.bureau_b, r.title_b, r.desc_b, r.status_b, r.priority_b, r.received_b)):
                    col.markdown(f"""<div class="nx-card"><h4>{ui.e(cid)} · {ui.e(bur)}</h4>
{ui.status_badge(stt)}{ui.priority_badge(pr)}<p style="margin:.6rem 0 .2rem"><b>{ui.e(ttl)}</b></p>
<p class="nx-muted">Received {ui.fmt_date(rec)}<br>{ui.e(desc)}</p></div>""", unsafe_allow_html=True)
                st.markdown("**Why these were matched**")
                for reason in r.reasons.split(" | "):
                    st.markdown(f"- {reason}")
                if r.reviewed_by:
                    st.caption(f"Reviewed by {r.reviewed_by} on {r.reviewed_at}"
                               + (f" · comment: {r.review_comment}" if r.review_comment else ""))
                if not can_review:
                    st.caption("Only Senior Officers and Admins can verify suggestions.")
                    continue
                note = st.text_input("Reviewer comment (optional)", key=f"ci_cmt_{r.relationship_id}", max_chars=300)
                b = st.columns(3)
                if r.review_status != "Related" and b[0].button("Mark as Related", type="primary",
                                                                key=f"ci_rel_{r.relationship_id}"):
                    ui.result(*db.review_relationship(r.relationship_id, "Related", note, actor))
                if r.review_status != "Dismissed" and b[1].button("Dismiss", key=f"ci_dis_{r.relationship_id}"):
                    ui.result(*db.review_relationship(r.relationship_id, "Dismissed", note, actor))
                if r.review_status != "Pending" and b[2].button("Reset to pending", key=f"ci_pen_{r.relationship_id}"):
                    ui.result(*db.review_relationship(r.relationship_id, "Pending", note, actor))
with tab_table:
    if rel.empty:
        ui.empty_state("Nothing to show.")
    else:
        t = rel[["complaint_a", "complaint_b", "institution_name", "bureau_a", "bureau_b", "similarity_score",
                 "confidence", "reasons", "review_status", "reviewed_by", "reviewed_at"]].rename(columns={
            "complaint_a": "Complaint A", "complaint_b": "Complaint B", "institution_name": "Institution",
            "bureau_a": "Bureau A", "bureau_b": "Bureau B", "similarity_score": "Heuristic score",
            "confidence": "Confidence", "reasons": "Reasons", "review_status": "Review status",
            "reviewed_by": "Reviewed by", "reviewed_at": "Reviewed at"})
        ui.show_table(t)
        ui.export_button("Export suggestions to CSV", db.to_csv_bytes(t), "aicte_nexus_relationship_suggestions.csv",
                         "text/csv", key="ci_export", what="Relationship suggestions")
