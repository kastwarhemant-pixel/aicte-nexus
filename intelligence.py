"""Explainable cross-bureau complaint matching and risk monitoring.

EXPLAINABLE PROTOTYPE - not a production-validated model. Scores are heuristic
similarity indicators, NOT probabilities. Pure standard library + pandas; works offline.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from itertools import combinations

import pandas as pd

import database as db

# Heuristic score = weighted sum of four components, each in [0, 1].
W_TEXT, W_KEYWORD, W_DATE, W_CATEGORY = 0.55, 0.20, 0.15, 0.10
TEXT_SATURATION = 0.50   # a TF-IDF cosine at/above this earns the full text component

STOPWORDS = set("""a an and are as at be been being by for from has have had in into is it its of on or that the their
them they this those these to was were will with which who whom while about above after again against all also any
because before below between both but can could did do does doing down during each few further here how if more most
no nor not now off once only other our out over own same she should so some such than then there through under until
up very what when where why would you your""".split())
GENERIC_TERMS = set("""complaint complaints institution institutions student students report reports reported alleges
allege alleged allegation states state claims claim college institute during several current session requested
required prescribed stipulated""".split())


def tokenize(text: str) -> list:
    out = []
    for w in re.findall(r"[a-z]{3,}", (text or "").lower()):
        if w in STOPWORDS or w in GENERIC_TERMS:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def _doc_tokens(title: str, desc: str) -> list:
    return tokenize(title) * 2 + tokenize(desc)  # title words count double


def build_vectors(df: pd.DataFrame):
    """L2-normalised TF-IDF vectors (dict term->weight) for every complaint, corpus = all complaints."""
    docs = {r.complaint_id: _doc_tokens(r.title, r.description) for r in df.itertuples()}
    n = max(len(docs), 1)
    dfreq = Counter(t for toks in docs.values() for t in set(toks))
    vecs = {}
    for cid, toks in docs.items():
        tf = Counter(toks)
        v = {t: (1 + math.log(c)) * (math.log((1 + n) / (1 + dfreq[t])) + 1) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs[cid] = {t: x / norm for t, x in v.items()}
    return vecs, {cid: set(toks) for cid, toks in docs.items()}


def confidence_label(score: float, medium: float, high: float) -> str:
    return "High" if score >= high else "Medium" if score >= medium else "Low"


def score_pair(va, vb, ta, tb, ra, rb, cat_a, cat_b, window):
    cos = sum(w * vb[t] for t, w in va.items() if t in vb)
    shared = sorted((t for t in va if t in vb), key=lambda t: va[t] * vb[t], reverse=True)
    union = ta | tb
    jac = len(ta & tb) / len(union) if union else 0.0
    gap = abs((ra - rb).days)
    date_c = max(0.0, 1 - gap / window)
    cat_c = 1.0 if cat_a == cat_b else 0.0
    text_c = min(1.0, cos / TEXT_SATURATION)
    score = W_TEXT * text_c + W_KEYWORD * min(1.0, jac / 0.25) + W_DATE * date_c + W_CATEGORY * cat_c
    return score, cos, shared, gap, cat_c


def compute_candidates(df: pd.DataFrame, settings: dict) -> list:
    """Candidate pairs: same institution AND different bureaus AND at least one shared keyword."""
    if df.empty:
        return []
    mn, md, hi = (float(settings[k]) for k in ("match_min_score", "match_medium_score", "match_high_score"))
    window = int(settings["match_date_window_days"])
    vecs, toks = build_vectors(df)
    out = []
    for iid, grp in df.groupby("institution_id"):
        recs = list(grp.itertuples())
        for a, b in combinations(recs, 2):
            if a.bureau == b.bureau:
                continue
            a, b = sorted((a, b), key=lambda r: r.complaint_id)
            score, cos, shared, gap, same_cat = score_pair(
                vecs[a.complaint_id], vecs[b.complaint_id], toks[a.complaint_id], toks[b.complaint_id],
                a.date_received, b.date_received, a.category, b.category, window)
            if not shared or score < mn:
                continue
            reasons = [f"Same institution ({iid})",
                       f"Different bureaus: {a.bureau} and {b.bureau}",
                       f"Text similarity {cos:.2f} (TF-IDF cosine on title + description)",
                       "Shared keywords: " + ", ".join(shared[:6])]
            if same_cat:
                reasons.append(f"Same category: {a.category}")
            if gap <= window:
                reasons.append(f"Received {gap} day(s) apart (window {window} days)")
            out.append(dict(complaint_a=a.complaint_id, complaint_b=b.complaint_id, institution_id=iid,
                            score=round(score, 4), confidence=confidence_label(score, md, hi),
                            reasons=" | ".join(reasons)))
    return sorted(out, key=lambda r: r["score"], reverse=True)


def refresh_suggestions(actor=None, log=True) -> dict:
    """Recompute suggestions from the current database and store them. Never merges/closes anything."""
    settings = db.get_settings()
    cands = compute_candidates(db.list_complaints(), settings)
    new = db.upsert_suggestions(cands)
    if log:
        with db.get_conn() as conn:
            db.log_audit(conn, "SUGGESTIONS_REFRESHED", "Relationship", "all", None, len(cands),
                         f"{new} new suggestion(s); reviewed decisions untouched", actor or "System")
    return {"candidates": len(cands), "new": new}


# --------------------------------------------------------------------------- #
# Overdue and risk monitoring
# --------------------------------------------------------------------------- #
RISK_COLUMNS = ["complaint_id", "institution_name", "bureau", "assigned_officer", "priority", "status",
                "due_date", "days_overdue", "last_updated", "days_inactive", "risk_flags",
                "recommended_action", "risk_score"]


def compute_risk(df: pd.DataFrame, settings: dict) -> pd.DataFrame:
    """Flags open complaints against configurable thresholds. Recommendations only - nothing is automatic."""
    act = df[df["is_open"]].copy() if not df.empty else df.copy()
    if act.empty:
        return pd.DataFrame(columns=RISK_COLUMNS)
    inact, aw = int(settings["inactivity_days"]), int(settings["awaiting_info_days"])
    reas = int(settings["reassignment_threshold"])
    act["f_critical"] = act["priority"] == "Critical"
    act["f_high_overdue"] = (act["priority"] == "High") & act["is_overdue"]
    act["f_overdue"] = act["is_overdue"]
    act["f_inactive"] = act["days_inactive"] >= inact
    act["f_awaiting"] = (act["status"] == "Awaiting Information") & (act["days_in_status"] >= aw)
    act["f_reassigned"] = act["reassign_count"] >= reas
    act = act[act[["f_critical", "f_overdue", "f_inactive", "f_awaiting", "f_reassigned"]].any(axis=1)].copy()
    if act.empty:
        return pd.DataFrame(columns=RISK_COLUMNS)

    def flags(r):
        out = []
        if r.f_critical: out.append("Critical priority")
        if r.f_overdue: out.append(f"Overdue {r.days_overdue}d")
        if r.f_inactive: out.append(f"Inactive {r.days_inactive}d")
        if r.f_awaiting: out.append(f"Awaiting info {r.days_in_status}d")
        if r.f_reassigned: out.append(f"Reassigned {r.reassign_count}x")
        return ", ".join(out)

    def action(r):
        if r.f_critical:
            return "Immediate review by bureau head"
        if r.f_high_overdue:
            return "Urgent follow-up with assigned officer"
        if r.f_awaiting:
            return "Follow up with the responsible party for the pending information"
        if r.f_overdue:
            return "Escalate to supervisor or record a justified revised due date"
        if r.f_inactive:
            return "Request a status update from the assigned officer"
        return "Review ownership; confirm a single accountable officer"

    def points(r):
        p = {"Critical": 3, "High": 2, "Medium": 1, "Low": 0}[r.priority]
        p += (2 + (1 if r.days_overdue > 30 else 0)) if r.f_overdue else 0
        return p + int(r.f_inactive) + int(r.f_awaiting) + int(r.f_reassigned)

    act["risk_flags"] = act.apply(flags, axis=1)
    act["recommended_action"] = act.apply(action, axis=1)
    act["risk_score"] = act.apply(points, axis=1)
    return act.sort_values(["risk_score", "days_overdue"], ascending=False)[RISK_COLUMNS + [
        "f_critical", "f_overdue", "f_inactive", "f_awaiting", "f_reassigned"]].reset_index(drop=True)
