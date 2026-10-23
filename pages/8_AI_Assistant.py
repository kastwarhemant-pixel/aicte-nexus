
"""NEXUS AI Assistant — Groq-powered conversational complaint intelligence."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pandas as pd
import streamlit as st

import database as db
import intelligence as intel
import ui


# ---------------------------------------------------------
# PAGE SETUP
# ---------------------------------------------------------

ui.page_header(
    "NEXUS AI Assistant",
    "AI-powered operational intelligence for complaint management, "
    "institution insights and risk review.",
)

st.markdown(
    """
    <div class="nx-hero">
        <span class="nx-pill">NEXUS COPILOT · GROQ AI</span>
        <h1>Your data. Your questions. Clear answers.</h1>
        <p>Ask questions naturally. Explore complaint trends, overdue cases,
        institutional workload and risk indicators through one AI assistant.</p>
        <div class="nx-hero-grid">
            <div class="nx-hero-cell">
                <b>AI-powered</b>
                <span>Groq-hosted Llama model for conversational responses.</span>
            </div>
            <div class="nx-hero-cell">
                <b>Data grounded</b>
                <span>Operational metrics come from the local database.</span>
            </div>
            <div class="nx-hero-cell">
                <b>Human controlled</b>
                <span>AI suggestions never modify records automatically.</span>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# API CONFIGURATION
# ---------------------------------------------------------

def get_groq_key():
    """Read the API key without displaying it in the UI."""
    key = os.environ.get("GROQ_API_KEY", "").strip()

    if key:
        return key

    try:
        return str(st.secrets.get("GROQ_API_KEY", "")).strip()
    except Exception:
        return ""


def get_groq_model():
    model = os.environ.get(
        "GROQ_MODEL", "llama-3.3-70b-versatile"
    ).strip()

    try:
        return str(st.secrets.get("GROQ_MODEL", model)).strip()
    except Exception:
        return model


GROQ_API_KEY = get_groq_key()
GROQ_MODEL = get_groq_model()

if GROQ_API_KEY:
    st.success("Groq AI is configured. The assistant can use the Llama model.")
else:
    st.warning(
        "Groq API key is not configured. The assistant is running in "
        "offline analysis mode. Set GROQ_API_KEY in your terminal or "
        "Streamlit secrets to enable AI responses."
    )


# ---------------------------------------------------------
# LOAD DATABASE
# ---------------------------------------------------------

try:
    all_df = db.list_complaints()
    settings = db.get_settings()
except Exception as exc:
    st.error("Unable to load the NEXUS database.")
    st.code(str(exc))
    st.stop()

if all_df is None or all_df.empty:
    st.info(
        "No complaint records found. Add records or restore the synthetic "
        "demo data from Settings."
    )
    st.stop()

all_df = all_df.copy()

required = [
    "complaint_id",
    "institution_name",
    "bureau",
    "priority",
    "status",
    "is_open",
    "is_overdue",
]

missing = [column for column in required if column not in all_df.columns]

if missing:
    st.error("The database is missing required columns.")
    st.write(", ".join(missing))
    st.stop()


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def safe_bool_series(series):
    """Normalize database boolean columns safely."""
    return series.fillna(False).astype(bool)


def existing_columns(frame, candidates):
    return [col for col in candidates if col in frame.columns]


def result_table(frame, columns=None, limit=25):
    if frame is None or frame.empty:
        return pd.DataFrame()

    output = frame.copy()

    if columns:
        available = existing_columns(output, columns)
        if available:
            output = output[available]

    return output.head(limit).reset_index(drop=True)


def high_priority_cases(frame):
    priorities = frame["priority"].fillna("").astype(str).str.lower()
    return frame[priorities.isin(["high", "critical"])].copy()


def local_analysis(question):
    """
    Produce a verified local answer and supporting table.
    This function never executes user-provided SQL.
    """
    q = question.lower().strip()
    df = all_df.copy()

    df["is_open"] = safe_bool_series(df["is_open"])
    df["is_overdue"] = safe_bool_series(df["is_overdue"])

    open_cases = df[df["is_open"]].copy()
    overdue_cases = df[df["is_open"] & df["is_overdue"]].copy()
    high_cases = high_priority_cases(open_cases)

    if "resolved_date" in df.columns:
        resolved = df[
            (~df["is_open"]) & df["resolved_date"].notna()
        ].copy()
    else:
        resolved = df[~df["is_open"]].copy()

    # Overdue complaints
    if any(term in q for term in [
        "overdue", "past due", "late complaint", "late case",
        "sla breach", "delayed", "delay",
    ]):
        if overdue_cases.empty:
            return (
                "There are no overdue open complaints in the current dataset.",
                pd.DataFrame(),
            )

        if "days_overdue" in overdue_cases.columns:
            overdue_cases["days_overdue"] = pd.to_numeric(
                overdue_cases["days_overdue"], errors="coerce"
            ).fillna(0)
            overdue_cases = overdue_cases.sort_values(
                "days_overdue", ascending=False
            )

        critical_count = int(
            (
                overdue_cases["priority"].fillna("")
                .astype(str).str.lower() == "critical"
            ).sum()
        )

        return (
            f"There are **{len(overdue_cases)} overdue open complaints**. "
            f"**{critical_count}** are Critical priority. Review their due "
            "dates and assigned officers before deciding on escalation.",
            result_table(overdue_cases, [
                "complaint_id", "institution_name", "bureau", "priority",
                "status", "assigned_officer", "due_date", "days_overdue",
            ]),
        )

    # High/Critical complaints
    if any(term in q for term in [
        "critical", "high priority", "high-priority", "urgent",
        "high risk cases", "priority cases",
    ]):
        if high_cases.empty:
            return (
                "There are no open High or Critical priority complaints.",
                pd.DataFrame(),
            )

        return (
            f"There are **{len(high_cases)} open High/Critical complaints**. "
            "These cases may need prompt review by the responsible officers. "
            "No automatic escalation has been performed.",
            result_table(high_cases, [
                "complaint_id", "institution_name", "bureau", "priority",
                "status", "assigned_officer", "due_date", "days_overdue",
            ]),
        )

    # Bureau workload
    if any(term in q for term in [
        "bureau", "department", "cell workload", "team workload",
        "which team",
    ]):
        grouped = df.groupby("bureau", dropna=False).agg(
            Total=("complaint_id", "count"),
            Open=("is_open", "sum"),
            Overdue=("is_overdue", "sum"),
        ).reset_index().sort_values("Total", ascending=False)

        if grouped.empty:
            return "No bureau workload data is available.", grouped

        top = grouped.iloc[0]

        return (
            f"**{top['bureau']}** has the highest complaint volume with "
            f"**{int(top['Total'])} complaints**, **{int(top['Open'])} open** "
            f"and **{int(top['Overdue'])} overdue**. See the table for "
            "the workload comparison.",
            grouped,
        )

    # Resolution performance
    if any(term in q for term in [
        "resolution", "resolved", "closed", "on time",
        "performance", "average time",
    ]):
        answer = (
            f"There are **{len(resolved)} resolved/closed complaints** "
            "with a recorded resolution date. "
        )

        if "resolution_days" in resolved.columns:
            times = pd.to_numeric(
                resolved["resolution_days"], errors="coerce"
            ).dropna()

            if not times.empty:
                answer += (
                    f"Average resolution time is **{times.mean():.1f} days**. "
                )
            else:
                answer += "Average resolution time is unavailable. "
        else:
            answer += "Average resolution time is unavailable. "

        if "resolved_on_time" in resolved.columns and not resolved.empty:
            on_time = safe_bool_series(resolved["resolved_on_time"]).sum()
            rate = 100 * on_time / len(resolved)
            answer += f"**{rate:.0f}%** were resolved on time."

        return (
            answer,
            result_table(resolved, [
                "complaint_id", "institution_name", "bureau", "status",
                "date_received", "resolved_date", "resolution_days",
                "resolved_on_time",
            ]),
        )

    # Institution lookup or ranking
    if any(term in q for term in [
        "institution", "college", "university", "top institution",
        "most complaints",
    ]):
        group_cols = ["institution_name"]

        if "institution_id" in df.columns:
            group_cols.insert(0, "institution_id")

        if "state" in df.columns:
            group_cols.append("state")

        grouped = df.groupby(group_cols, dropna=False).agg(
            Total=("complaint_id", "count"),
            Open=("is_open", "sum"),
            Overdue=("is_overdue", "sum"),
        ).reset_index().sort_values(
            ["Total", "Overdue"], ascending=[False, False]
        )

        stop_words = {
            "institution", "institutions", "college", "university",
            "complaint", "complaints", "find", "search", "about",
            "details", "show", "give", "tell", "records", "please",
            "which", "what", "with", "from", "most", "have",
        }

        if any(term in q for term in ["find", "search", "details", "about"]):
            terms = [
                word.strip(".,?!:;")
                for word in q.split()
                if len(word.strip(".,?!:;")) > 3
                and word.strip(".,?!:;") not in stop_words
            ]

            if terms:
                matches = df[
                    df["institution_name"].fillna("").astype(str).apply(
                        lambda name: any(term in name.lower() for term in terms)
                    )
                ]

                if not matches.empty:
                    return (
                        f"Found **{matches['institution_name'].nunique()} "
                        f"matching institution(s)** and "
                        f"**{len(matches)} complaint records**.",
                        result_table(matches, [
                            "complaint_id", "institution_name", "bureau",
                            "title", "priority", "status", "is_overdue",
                            "assigned_officer",
                        ]),
                    )

        if grouped.empty:
            return "No institution data is available.", grouped

        top = grouped.iloc[0]
        return (
            f"**{top['institution_name']}** has the highest complaint "
            f"volume in the current dataset: **{int(top['Total'])} total**, "
            f"**{int(top['Open'])} open** and "
            f"**{int(top['Overdue'])} overdue**.",
            grouped.head(20),
        )

    # Risk analysis
    if any(term in q for term in [
        "risk", "risk flags", "risk score", "inactive",
        "reassigned", "awaiting information", "awaiting info",
    ]):
        try:
            risks = intel.compute_risk(df, settings)
        except Exception as exc:
            return (
                "Risk analysis failed. Check the intelligence module and "
                "risk settings.",
                pd.DataFrame({"Error": [str(exc)]}),
            )

        if risks is None or risks.empty:
            return (
                "The configured rules did not flag any complaints "
                "for risk review.",
                pd.DataFrame(),
            )

        return (
            f"The configured rules flagged **{len(risks)} complaints** "
            "for review. These scores are heuristic indicators, not "
            "validated probabilities. Suggested actions are advisory.",
            result_table(risks, [
                "complaint_id", "institution_name", "bureau", "priority",
                "status", "risk_score", "risk_flags", "recommended_action",
            ]),
        )

    # General summary
    institution_count = (
        df["institution_id"].nunique()
        if "institution_id" in df.columns
        else df["institution_name"].nunique()
    )

    summary = (
        f"Loaded database: **{len(df)} complaints** across "
        f"**{institution_count} institutions** and "
        f"**{df['bureau'].nunique()} bureaus**.\n\n"
        f"- Open cases: **{len(open_cases)}**\n"
        f"- Overdue open cases: **{len(overdue_cases)}**\n"
        f"- Resolved cases with resolution dates: **{len(resolved)}**\n"
        f"- Open High/Critical cases: **{len(high_cases)}**"
    )

    distribution = (
        df["status"].value_counts()
        .rename_axis("Status")
        .reset_index(name="Complaints")
    )

    return summary, distribution


# ---------------------------------------------------------
# GROQ API
# ---------------------------------------------------------

def ask_groq(question, verified_answer, result_df):
    """
    Send a question and limited context to Groq.
    No SQL is generated or executed. The API key is never shown.
    """
    context = {
        "local_analysis": verified_answer,
        "result_preview": (
            result_df.head(10).fillna("").astype(str).to_dict("records")
            if result_df is not None and not result_df.empty
            else []
        ),
        "dataset_summary": {
            "total_complaints": int(len(all_df)),
            "institutions": int(all_df["institution_name"].nunique()),
            "bureaus": int(all_df["bureau"].nunique()),
        },
    }

    system_prompt = """
You are NEXUS Copilot, an AI assistant inside a complaint-management
prototype using synthetic demonstration data.

Rules:
1. Answer the user's question clearly and naturally.
2. Treat the supplied local analysis and records as the source of truth
   for project-specific metrics.
3. Never invent complaint IDs, statistics, institutions, officers, or actions.
4. If the supplied context does not contain a requested fact, say it is
   unavailable rather than guessing.
5. You may explain general concepts, but distinguish them from facts in
   the NEXUS database.
6. Recommendations are advisory. Never claim that you changed records,
   assigned officers, closed cases, or escalated complaints.
7. Risk scores are heuristic indicators, not validated probabilities.
8. The project uses synthetic demo data, not verified official records.
Use concise Markdown in your response.
""".strip()

    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.2,
        "max_tokens": 900,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\n"
                    "Verified local context:\n"
                    + json.dumps(context, ensure_ascii=False)
                ),
            },
        ],
    }

    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        answer = data["choices"][0]["message"]["content"].strip()

        if not answer:
            raise ValueError("Groq returned an empty response.")

        return answer, None

    except urllib.error.HTTPError as exc:
        try:
            details = exc.read().decode("utf-8", errors="replace")
            parsed = json.loads(details)
            message = parsed.get("error", {}).get("message", details)
        except Exception:
            message = f"HTTP {exc.code}"

        return None, f"Groq API error ({exc.code}): {message}"

    except (urllib.error.URLError, TimeoutError) as exc:
        return None, f"Could not connect to Groq: {exc}"

    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
        return None, f"Could not read the Groq response: {exc}"


# ---------------------------------------------------------
# CHAT HANDLER
# ---------------------------------------------------------

def process_question(question):
    question = question.strip()
    if not question:
        return

    local_answer, result_df = local_analysis(question)
    final_answer = local_answer
    api_error = None

    if GROQ_API_KEY:
        ai_answer, api_error = ask_groq(
            question,
            local_answer,
            result_df,
        )

        if ai_answer:
            final_answer = ai_answer

    st.session_state.setdefault("nexus_ai_history", []).append({
        "question": question,
        "answer": final_answer,
        "local_answer": local_answer,
        "result": result_df.copy(),
        "api_error": api_error,
    })


# ---------------------------------------------------------
# DASHBOARD METRICS
# ---------------------------------------------------------

df_for_metrics = all_df.copy()
df_for_metrics["is_open"] = safe_bool_series(df_for_metrics["is_open"])
df_for_metrics["is_overdue"] = safe_bool_series(df_for_metrics["is_overdue"])

open_count = int(df_for_metrics["is_open"].sum())
overdue_count = int(
    (df_for_metrics["is_open"] & df_for_metrics["is_overdue"]).sum()
)
priority_count = len(high_priority_cases(
    df_for_metrics[df_for_metrics["is_open"]]
))

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Complaints", f"{len(all_df):,}")
m2.metric("Open Cases", f"{open_count:,}")
m3.metric("Overdue Cases", f"{overdue_count:,}")
m4.metric("High / Critical", f"{priority_count:,}")

st.divider()


# ---------------------------------------------------------
# QUESTION INPUT
# ---------------------------------------------------------

st.markdown("### Ask NEXUS")
st.caption(
    "Select a prompt below or type a question in your own words."
)

quick_questions = [
    "Give me an overall complaint summary",
    "Show overdue complaints",
    "Which bureau has the most complaints?",
    "Show open critical cases",
    "Explain current risk flags",
    "How is resolution performance?",
]

prompt_columns = st.columns(3)

for index, prompt in enumerate(quick_questions):
    with prompt_columns[index % 3]:
        if st.button(
            prompt,
            key=f"nexus_quick_{index}",
            use_container_width=True,
        ):
            process_question(prompt)
            st.rerun()

with st.form("nexus_ai_question_form", clear_on_submit=True):
    user_question = st.text_input(
        "Your question",
        placeholder=(
            "Example: Explain overdue complaints and suggest next steps"
        ),
    )
    submitted = st.form_submit_button(
        "Ask NEXUS  →",
        type="primary",
        use_container_width=True,
    )

if submitted and user_question.strip():
    process_question(user_question)
    st.rerun()


# ---------------------------------------------------------
# CHAT HISTORY AND RESULTS
# ---------------------------------------------------------

history = st.session_state.get("nexus_ai_history", [])

st.markdown("### Conversation")

if history:
    col1, col2 = st.columns([4, 1])

    with col1:
        st.caption(f"{len(history)} question(s) in this session")

    with col2:
        if st.button(
            "Clear chat",
            key="nexus_clear_chat",
            use_container_width=True,
        ):
            st.session_state["nexus_ai_history"] = []
            st.rerun()

    for number, item in enumerate(reversed(history[-10:]), start=1):
        with st.container(border=True):
            st.markdown("**You**")
            st.markdown(ui.e(item["question"]))

            st.markdown("**NEXUS Copilot**")
            st.markdown(item["answer"])

            if item.get("api_error"):
                st.warning(
                    "Groq could not answer this request. "
                    "The verified local analysis is shown instead."
                )
                with st.expander("Technical details"):
                    st.code(item["api_error"])

            result = item.get("result")

            if isinstance(result, pd.DataFrame) and not result.empty:
                st.dataframe(
                    result,
                    hide_index=True,
                    use_container_width=True,
                    key=f"nexus_result_{number}",
                )

                st.download_button(
                    "Download results as CSV",
                    data=result.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"nexus_ai_results_{number}.csv",
                    mime="text/csv",
                    key=f"nexus_csv_{number}",
                )
else:
    st.info(
        "Your conversation will appear here. Ask a question to get started."
    )


# ---------------------------------------------------------
# HELP AND TRANSPARENCY
# ---------------------------------------------------------

with st.expander("How NEXUS Copilot works"):
    st.markdown(
        """
        **When Groq is configured**
        - The question and a compact verified analysis are sent to Groq.
        - The Llama model explains the supplied results in natural language.
        - If the API fails, NEXUS falls back to its local analysis.

        **Security and limitations**
        - The API key is read from an environment variable or Streamlit secrets.
        - The assistant does not execute arbitrary SQL or modify database records.
        - A limited result preview may be sent to Groq when AI mode is enabled.
        - Use synthetic demo records for demonstrations.
        - Risk scores are heuristic indicators and recommendations require
          human review.
        """
    )
