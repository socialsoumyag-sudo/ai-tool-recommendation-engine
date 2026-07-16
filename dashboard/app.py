"""
dashboard/app.py

Streamlit UI for AI Tool Recommendation Engine.

Two modes:
  - Individual: one role, one task, your priority weights (original flow).
  - Team & Portfolio: a cross-functional team, multiple roles/tasks, with
    a best-of-breed vs single-suite vs complementary-pair tradeoff --
    the realistic procurement question companies actually have.

Both modes share the same rule: the ranking and consolidation math make
ZERO API calls. The only optional LLM call is the plain-language
narrative layered on top, with a deterministic fallback either way.
"""

import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rules_engine.task_taxonomy import FACTORS, list_professions
from rules_engine.tool_registry import ToolRegistry
from rules_engine.team_engine import RoleTask
from advisor.report_generator import generate_report
from advisor.team_report_generator import generate_team_report


st.set_page_config(page_title="AI Tool Recommendation Engine", page_icon="🎯", layout="wide")

FACTOR_LABELS = {
    "accuracy": "Accuracy / Quality",
    "cost": "Cost (10 = cheapest)",
    "speed": "Speed",
    "privacy": "Privacy / Enterprise Readiness",
    "ecosystem": "Ecosystem / Integrations",
    "context": "Context Window / Memory",
    "ease": "Ease of Use",
}


def inject_theme():
    css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "theme.css")
    with open(css_path, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

    st.markdown(
        """
        <div class="hero-wrap">
            <p class="hero-title">🎯 AI Tool Recommendation Engine</p>
            <p class="hero-subtitle">
                Stop guessing which AI tool to use. Get a decision, not a listicle —
                with the runner-up's exact tradeoff shown, not hidden. Built for
                individuals and for the messier real-world question: what should
                a cross-functional team actually standardize on.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def load_registry() -> ToolRegistry:
    return ToolRegistry()


def render_radar(scored_tools_with_labels, top_n: int = 3):
    fig = go.Figure()
    for label, factor_scores in scored_tools_with_labels[:top_n]:
        values = [factor_scores.get(f, 0) for f in FACTORS]
        values.append(values[0])
        labels = [FACTOR_LABELS[f] for f in FACTORS] + [FACTOR_LABELS[FACTORS[0]]]
        fig.add_trace(go.Scatterpolar(r=values, theta=labels, fill="toself", name=label, opacity=0.6))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 10])),
        showlegend=True, height=430, margin=dict(l=30, r=30, t=30, b=30),
        font=dict(family="Inter, sans-serif"),
    )
    return fig


def platform_multiselect(registry: ToolRegistry, key_prefix: str):
    vendors = registry.known_vendors()
    existing = st.multiselect(
        "Platforms your company already uses (optional)",
        options=vendors,
        key=f"{key_prefix}_vendors",
        help="Tools from these vendors get a visible, explicit fit bonus "
             "(licensing already sunk, compliance already vetted).",
    )
    only_approved = st.checkbox(
        "Only consider these platforms (hard filter, for regulated environments)",
        key=f"{key_prefix}_approved_only",
    )
    return existing, only_approved


# =========================================================================
# INDIVIDUAL MODE
# =========================================================================

def render_individual_mode(registry: ToolRegistry):
    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.markdown('<p class="section-label">1 · Your profession</p>', unsafe_allow_html=True)
        professions = list_professions()
        profession_labels = [p.label for p in professions]
        selected_label = st.selectbox("Profession", profession_labels, label_visibility="collapsed")
        profession = next(p for p in professions if p.label == selected_label)

        st.markdown('<p class="section-label">2 · Task</p>', unsafe_allow_html=True)
        task_labels = [t.label for t in profession.tasks]
        selected_task_label = st.selectbox("Task", task_labels, label_visibility="collapsed")
        task = next(t for t in profession.tasks if t.label == selected_task_label)
        if task.description:
            st.caption(task.description)

        st.markdown('<p class="section-label">3 · What matters to you</p>', unsafe_allow_html=True)
        weights = {}
        for factor in FACTORS:
            weights[factor] = st.slider(FACTOR_LABELS[factor], 0, 10, 5, key=f"ind_w_{factor}")

        st.markdown('<p class="section-label">4 · Company context (optional)</p>', unsafe_allow_html=True)
        existing_vendors, only_approved = platform_multiselect(registry, "ind")

        use_llm = st.checkbox(
            "Generate plain-language explanation (uses 1 API call)",
            value=bool(os.environ.get("ANTHROPIC_API_KEY")),
            key="ind_use_llm",
        )
        run = st.button("Get my recommendation", type="primary", use_container_width=True, key="ind_run")

    with col_right:
        if not run:
            st.info("Pick a profession, task, and your priorities on the left, then hit **Get my recommendation**.")
            return

        report = generate_report(
            task_id=task.id, task_label=task.label, weights=weights,
            registry=registry, use_llm_explanation=use_llm,
        )

        if report.ranking.total_count == 0:
            st.warning(f"No tool data yet for '{task.label}'. Try another task.")
            return

        # apply platform context on top of the individual ranking
        from rules_engine.scoring_engine import apply_platform_context
        adjusted = apply_platform_context(
            report.ranking, existing_vendors=existing_vendors, allowed_vendors_only=only_approved,
        )

        winner = adjusted.winner
        if winner is None:
            st.warning("No tools remain after applying your approved-vendor filter.")
            return

        st.markdown(f'<p class="section-label">Top pick</p>', unsafe_allow_html=True)
        badges = f'<span class="badge badge-vendor">{winner.vendor}</span>'
        if winner.platform_bonus > 0:
            badges += f'<span class="badge badge-bonus">+{winner.platform_bonus} existing-platform bonus</span>'
        badges += (
            f'<span class="badge badge-fresh">fresh</span>' if not winner.is_stale
            else f'<span class="badge badge-stale">stale · {winner.last_verified}</span>'
        )
        st.markdown(badges, unsafe_allow_html=True)
        st.markdown(f'<div class="big-score">{winner.tool}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="score-caption">Weighted fit score: {winner.weighted_score}/10'
            + (f' &nbsp;·&nbsp; +{winner.runner_up_gap} over runner-up' if winner.runner_up_gap else '')
            + '</div>', unsafe_allow_html=True,
        )

        st.plotly_chart(
            render_radar([(t.tool, t.factor_scores) for t in adjusted.ranked_tools]),
            use_container_width=True,
        )

        st.markdown('<p class="section-label">Why</p>', unsafe_allow_html=True)
        st.write(report.narrative)
        if not report.used_llm_explanation:
            st.caption("(Deterministic explanation — no API key used.)")

        st.markdown('<p class="section-label">Full ranking</p>', unsafe_allow_html=True)
        rows = []
        for i, t in enumerate(adjusted.ranked_tools, start=1):
            rows.append({
                "Rank": i, "Tool": t.tool, "Vendor": t.vendor,
                "Score": t.weighted_score,
                "Platform Bonus": f"+{t.platform_bonus}" if t.platform_bonus else "—",
                "Data Status": ("stale" if t.is_stale else "fresh") + f" ({t.last_verified})",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption(f"📅 {report.freshness_summary()}")


# =========================================================================
# TEAM & PORTFOLIO MODE
# =========================================================================

def _init_team_state():
    if "team_rows" not in st.session_state:
        st.session_state.team_rows = []


def render_team_mode(registry: ToolRegistry):
    _init_team_state()

    st.markdown('<p class="section-label">Build your team</p>', unsafe_allow_html=True)
    st.caption(
        "Add one row per role + task. Weights below apply uniformly across "
        "all rows — set them for whatever your team collectively values most."
    )

    professions = list_professions()

    # Profession lives OUTSIDE the form on purpose. Streamlit forms only
    # rerun on submit -- so a Task dropdown whose options depend on the
    # Profession selection would show stale options until submit if both
    # lived inside the same form. Keeping Profession outside means picking
    # it triggers an immediate rerun, and the Task list below is always
    # correct before you ever open that dropdown.
    prof_label = st.selectbox(
        "Profession", [p.label for p in professions], key="team_add_profession",
    )
    profession = next(p for p in professions if p.label == prof_label)

    with st.form("add_row_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 1.6, 1])
        with c1:
            task_label = st.selectbox("Task", [t.label for t in profession.tasks])
            task = next(t for t in profession.tasks if t.label == task_label)
        with c2:
            role_name = st.text_input("Role label (optional)", value="", placeholder=prof_label)
        with c3:
            importance = st.slider("Importance", 1, 5, 1, help="e.g. done daily by many people = higher")
        add = st.form_submit_button("+ Add to team", use_container_width=True)
        if add:
            st.session_state.team_rows.append({
                "role_label": role_name.strip() or prof_label,
                "task_id": task.id,
                "task_label": task.label,
                "importance": float(importance),
            })

    if st.session_state.team_rows:
        st.markdown('<p class="section-label">Current team</p>', unsafe_allow_html=True)
        df = pd.DataFrame(st.session_state.team_rows)
        df_display = df.rename(columns={
            "role_label": "Role", "task_label": "Task", "importance": "Importance",
        })[["Role", "Task", "Importance"]]
        st.dataframe(df_display, hide_index=True, use_container_width=True)

        remove_idx = st.selectbox(
            "Remove a row (optional)",
            options=["—"] + [f"{i}: {r['role_label']} / {r['task_label']}" for i, r in enumerate(st.session_state.team_rows)],
        )
        if remove_idx != "—":
            idx = int(remove_idx.split(":")[0])
            if st.button("Remove selected row"):
                st.session_state.team_rows.pop(idx)
                st.rerun()
    else:
        st.info("No rows yet — add at least two to see a meaningful consolidation analysis.")

    st.markdown('<p class="section-label">Shared priority weights</p>', unsafe_allow_html=True)
    weight_cols = st.columns(len(FACTORS))
    weights = {}
    for col, factor in zip(weight_cols, FACTORS):
        with col:
            weights[factor] = st.slider(FACTOR_LABELS[factor].split(" ")[0], 0, 10, 5, key=f"team_w_{factor}")

    st.markdown('<p class="section-label">Company context (optional)</p>', unsafe_allow_html=True)
    existing_vendors, only_approved = platform_multiselect(registry, "team")

    use_llm = st.checkbox(
        "Generate plain-language procurement narrative (uses 1 API call)",
        value=bool(os.environ.get("ANTHROPIC_API_KEY")),
        key="team_use_llm",
    )

    analyze = st.button(
        "Analyze team", type="primary", use_container_width=True,
        disabled=len(st.session_state.team_rows) == 0,
    )

    if not analyze:
        return

    role_tasks = [
        RoleTask(
            role_label=r["role_label"], task_id=r["task_id"], task_label=r["task_label"],
            weights=weights, importance=r["importance"],
        )
        for r in st.session_state.team_rows
    ]

    report = generate_team_report(
        role_tasks=role_tasks, registry=registry,
        existing_vendors=existing_vendors, allowed_vendors_only=only_approved,
        use_llm_explanation=use_llm,
    )
    analysis = report.analysis

    st.markdown('<hr class="thin-divider">', unsafe_allow_html=True)
    st.markdown('<p class="section-label">The tradeoff</p>', unsafe_allow_html=True)

    bcol1, bcol2, bcol3 = st.columns(3)
    with bcol1:
        st.markdown('<div class="fit-card">', unsafe_allow_html=True)
        st.markdown("**Best-of-breed**")
        st.markdown(f'<div class="big-score">{analysis.best_of_breed_total}</div>', unsafe_allow_html=True)
        st.caption("100% quality · one tool per task · highest procurement complexity")
        st.markdown('</div>', unsafe_allow_html=True)

    with bcol2:
        st.markdown('<div class="fit-card-highlight">', unsafe_allow_html=True)
        st.markdown("**Single suite (1 tool)**")
        if analysis.single_suite:
            s = analysis.single_suite
            st.markdown(f'<div class="big-score">{s.tools[0]}</div>', unsafe_allow_html=True)
            st.caption(f"{s.coverage_pct}% of best-of-breed quality · simplest procurement")
        st.markdown('</div>', unsafe_allow_html=True)

    with bcol3:
        st.markdown('<div class="fit-card">', unsafe_allow_html=True)
        st.markdown("**Complementary pair (2 tools)**")
        if analysis.complementary_pair:
            p = analysis.complementary_pair
            st.markdown(f'<div class="big-score" style="font-size:1.5rem;">{p.tools[0]} + {p.tools[1]}</div>', unsafe_allow_html=True)
            st.caption(f"{p.coverage_pct}% of best-of-breed quality · two licenses to manage")
        st.markdown('</div>', unsafe_allow_html=True)

    # Comparison bar chart
    bar_labels, bar_values = ["Best-of-breed"], [analysis.best_of_breed_total]
    if analysis.single_suite:
        bar_labels.append(f"Single suite\n({analysis.single_suite.tools[0]})")
        bar_values.append(analysis.single_suite.total_weighted_score)
    if analysis.complementary_pair:
        bar_labels.append(f"Pair\n({'+'.join(analysis.complementary_pair.tools)})")
        bar_values.append(analysis.complementary_pair.total_weighted_score)

    fig = go.Figure(go.Bar(x=bar_labels, y=bar_values, marker_color=["#16344A", "#2C5F7C", "#5C7A8C"]))
    fig.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20), font=dict(family="Inter, sans-serif"))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown('<p class="section-label">Why</p>', unsafe_allow_html=True)
    st.write(report.narrative)
    if not report.used_llm_explanation:
        st.caption("(Deterministic explanation — no API key used.)")

    if analysis.complementary_pair:
        st.markdown('<p class="section-label">Who uses what (complementary-pair assignment)</p>', unsafe_allow_html=True)
        rows = []
        for tc in analysis.complementary_pair.task_breakdown:
            rows.append({
                "Role": tc.role_label, "Task": tc.task_label,
                "Assigned Tool": tc.pair_assignment_tool,
                "Score": tc.pair_assignment_score,
                "Best-of-breed alternative": tc.best_of_breed.tool if tc.best_of_breed else "—",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


# =========================================================================
# MAIN
# =========================================================================

def main():
    inject_theme()
    registry = load_registry()

    with st.expander("Why the ranking never needs an API key", expanded=False):
        st.markdown(
            "Ranking and consolidation math are arithmetic, not intelligence — "
            "so scoring, platform-fit bonuses, and the best-of-breed / "
            "single-suite / complementary-pair analysis all run on plain "
            "deterministic logic, zero LLM calls. An LLM is only used, "
            "optionally, to turn the numbers into a plain-language narrative, "
            "and to refresh stale tool data via web research on a schedule."
        )

    mode = st.radio(
        "Mode", ["Individual", "Team & Portfolio"], horizontal=True, label_visibility="collapsed",
    )
    st.markdown('<hr class="thin-divider">', unsafe_allow_html=True)

    if mode == "Individual":
        render_individual_mode(registry)
    else:
        render_team_mode(registry)


if __name__ == "__main__":
    main()
