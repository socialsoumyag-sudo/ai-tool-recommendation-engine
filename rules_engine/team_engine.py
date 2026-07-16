"""
team_engine.py

Handles the scenario a single-role ranking can't: a cross-functional team
where buying one tool per person per task isn't realistic. A company
usually wants to know one of three things:

  1. Best-of-breed  -- if cost/sprawl didn't matter, what's the best tool
                        per task? (the upper bound on quality)
  2. Single suite    -- if we standardize on ONE tool for everyone, which
                         one, and how much quality do we actually give up?
  3. Complementary pair -- if we allow exactly TWO tools, which pairing
                            recovers the most lost quality, and who uses
                            which tool for what?

All three are still pure arithmetic over already-computed weighted scores
-- no LLM call is needed to compare sums. This keeps faith with the
project's core rule: ranking and portfolio math are deterministic, full
stop. An optional LLM call may narrate the result (see
research_agent/explainer_agent.py's explain_with_llm equivalent for team
reports), but it never decides the recommendation itself.
"""

from dataclasses import dataclass, field
from typing import Optional

from rules_engine.scoring_engine import (
    ScoredTool,
    rank_tools,
    apply_platform_context,
    DEFAULT_PLATFORM_BONUS,
)
from rules_engine.tool_registry import ToolRegistry


@dataclass
class RoleTask:
    """One line item in a team request: a role doing a task with their
    own priority weights and an importance multiplier (e.g. a task done
    daily by 8 people should outweigh one done monthly by 1 person).
    """
    role_label: str
    task_id: str
    task_label: str
    weights: dict
    importance: float = 1.0


@dataclass
class TaskCoverage:
    task_id: str
    task_label: str
    role_label: str
    importance: float
    best_of_breed: Optional[ScoredTool]
    chosen_tool_score: Optional[float] = None       # for single-suite report
    pair_assignment_tool: Optional[str] = None        # for pair report
    pair_assignment_score: Optional[float] = None


@dataclass
class SuiteRecommendation:
    tools: list                     # list[str], 1 or 2 tool names
    total_weighted_score: float     # sum(score * importance) across tasks
    coverage_pct: float             # vs best-of-breed upper bound
    task_breakdown: list            # list[TaskCoverage]


@dataclass
class TeamAnalysis:
    role_tasks: list                          # list[RoleTask]
    best_of_breed_total: float
    best_of_breed_breakdown: list             # list[TaskCoverage]
    single_suite: Optional[SuiteRecommendation]
    complementary_pair: Optional[SuiteRecommendation]
    existing_vendors: list
    allowed_vendors_only: bool


def _ranked_for_role_task(
    rt: RoleTask,
    registry: ToolRegistry,
    existing_vendors: list,
    allowed_vendors_only: bool,
):
    base = rank_tools(task_id=rt.task_id, weights=rt.weights, registry=registry)
    return apply_platform_context(
        base,
        existing_vendors=existing_vendors,
        allowed_vendors_only=allowed_vendors_only,
    )


def analyze_team(
    role_tasks: list,
    registry: ToolRegistry,
    existing_vendors: Optional[list] = None,
    allowed_vendors_only: bool = False,
) -> TeamAnalysis:
    """The main entry point. Give it a list of RoleTask line items covering
    a whole team, and it returns best-of-breed, single-suite, and
    complementary-pair recommendations -- all pure arithmetic.
    """
    existing_vendors = existing_vendors or []

    # Step 1: rank every task independently (this reuses the exact same
    # deterministic engine as individual mode -- no new scoring logic).
    per_task_rankings = {}
    for rt in role_tasks:
        per_task_rankings[id(rt)] = _ranked_for_role_task(
            rt, registry, existing_vendors, allowed_vendors_only
        )

    # Step 2: best-of-breed upper bound.
    best_of_breed_breakdown = []
    best_of_breed_total = 0.0
    for rt in role_tasks:
        ranking = per_task_rankings[id(rt)]
        winner = ranking.winner
        contribution = (winner.weighted_score * rt.importance) if winner else 0.0
        best_of_breed_total += contribution
        best_of_breed_breakdown.append(TaskCoverage(
            task_id=rt.task_id, task_label=rt.task_label, role_label=rt.role_label,
            importance=rt.importance, best_of_breed=winner,
        ))
    best_of_breed_total = round(best_of_breed_total, 2)

    # Step 3: build a per-(tool) score lookup across every requested task,
    # defaulting to 0 if that tool has no data for a given task.
    all_tools = set()
    for rt in role_tasks:
        for st in per_task_rankings[id(rt)].ranked_tools:
            all_tools.add(st.tool)

    def score_of(tool_name: str, rt: RoleTask) -> float:
        for st in per_task_rankings[id(rt)].ranked_tools:
            if st.tool == tool_name:
                return st.weighted_score
        return 0.0

    # Step 4: single-suite -- the one tool maximizing total weighted
    # coverage across the whole team.
    single_suite = None
    if all_tools:
        totals = {}
        for tool in all_tools:
            total = sum(score_of(tool, rt) * rt.importance for rt in role_tasks)
            totals[tool] = round(total, 2)
        best_single = max(totals, key=totals.get)

        breakdown = []
        for rt in role_tasks:
            s = score_of(best_single, rt)
            breakdown.append(TaskCoverage(
                task_id=rt.task_id, task_label=rt.task_label, role_label=rt.role_label,
                importance=rt.importance,
                best_of_breed=per_task_rankings[id(rt)].winner,
                chosen_tool_score=s,
            ))

        coverage_pct = (
            round(100 * totals[best_single] / best_of_breed_total, 1)
            if best_of_breed_total > 0 else 0.0
        )
        single_suite = SuiteRecommendation(
            tools=[best_single],
            total_weighted_score=totals[best_single],
            coverage_pct=coverage_pct,
            task_breakdown=breakdown,
        )

    # Step 5: complementary pair -- brute-force over all tool pairs
    # (registry is small enough that this is cheap and exact, not a
    # heuristic approximation).
    complementary_pair = None
    if len(all_tools) >= 2:
        tool_list = sorted(all_tools)
        best_pair = None
        best_pair_total = -1.0

        for i in range(len(tool_list)):
            for j in range(i + 1, len(tool_list)):
                tool_a, tool_b = tool_list[i], tool_list[j]
                total = 0.0
                for rt in role_tasks:
                    score_a = score_of(tool_a, rt)
                    score_b = score_of(tool_b, rt)
                    total += max(score_a, score_b) * rt.importance
                if total > best_pair_total:
                    best_pair_total = total
                    best_pair = (tool_a, tool_b)

        if best_pair:
            breakdown = []
            for rt in role_tasks:
                score_a = score_of(best_pair[0], rt)
                score_b = score_of(best_pair[1], rt)
                winner_tool = best_pair[0] if score_a >= score_b else best_pair[1]
                winner_score = max(score_a, score_b)
                breakdown.append(TaskCoverage(
                    task_id=rt.task_id, task_label=rt.task_label, role_label=rt.role_label,
                    importance=rt.importance,
                    best_of_breed=per_task_rankings[id(rt)].winner,
                    pair_assignment_tool=winner_tool,
                    pair_assignment_score=winner_score,
                ))

            coverage_pct = (
                round(100 * best_pair_total / best_of_breed_total, 1)
                if best_of_breed_total > 0 else 0.0
            )
            complementary_pair = SuiteRecommendation(
                tools=list(best_pair),
                total_weighted_score=round(best_pair_total, 2),
                coverage_pct=coverage_pct,
                task_breakdown=breakdown,
            )

    return TeamAnalysis(
        role_tasks=role_tasks,
        best_of_breed_total=best_of_breed_total,
        best_of_breed_breakdown=best_of_breed_breakdown,
        single_suite=single_suite,
        complementary_pair=complementary_pair,
        existing_vendors=existing_vendors,
        allowed_vendors_only=allowed_vendors_only,
    )


def team_narrative_without_llm(analysis: TeamAnalysis) -> str:
    """Deterministic, no-API-key narrative for the team report -- same
    fallback pattern as explainer_agent.explain_without_llm.
    """
    lines = []
    n_roles = len({rt.role_label for rt in analysis.role_tasks})
    n_tasks = len(analysis.role_tasks)
    lines.append(
        f"Analyzed {n_tasks} task(s) across {n_roles} role(s). "
        f"Best-of-breed upper bound: {analysis.best_of_breed_total}/pt scale."
    )

    if analysis.single_suite:
        s = analysis.single_suite
        lines.append(
            f"Standardizing on {s.tools[0]} alone covers {s.coverage_pct}% "
            f"of best-of-breed quality across the whole team."
        )

    if analysis.complementary_pair:
        p = analysis.complementary_pair
        lines.append(
            f"Allowing exactly two tools ({p.tools[0]} + {p.tools[1]}) "
            f"recovers {p.coverage_pct}% of best-of-breed quality -- "
            f"{'a meaningful step up from the single-suite option' if analysis.single_suite and p.coverage_pct > analysis.single_suite.coverage_pct + 3 else 'a marginal improvement over standardizing on one tool'}."
        )

    if analysis.existing_vendors:
        lines.append(
            f"Existing-platform bonus (+{DEFAULT_PLATFORM_BONUS} pts) was applied "
            f"to tools from: {', '.join(analysis.existing_vendors)}."
        )
    if analysis.allowed_vendors_only:
        lines.append("Only approved vendors were considered (hard filter applied).")

    return "\n".join(lines)
