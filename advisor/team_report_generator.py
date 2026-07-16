"""
team_report_generator.py

Same pattern as advisor/report_generator.py, but for the team/portfolio
scenario. Thin orchestration only -- all real logic lives in
rules_engine/team_engine.py.
"""

import os
from dataclasses import dataclass, field
from datetime import date

from anthropic import Anthropic

from rules_engine.team_engine import TeamAnalysis, analyze_team, team_narrative_without_llm
from rules_engine.tool_registry import ToolRegistry


@dataclass
class TeamReport:
    analysis: TeamAnalysis
    narrative: str
    generated_on: str = field(default_factory=lambda: date.today().isoformat())
    used_llm_explanation: bool = False


def _explain_team_with_llm(analysis: TeamAnalysis, model: str = "claude-sonnet-4-6") -> str:
    """One optional LLM call, strictly grounded in the already-computed
    TeamAnalysis numbers -- same non-negotiable rule as explainer_agent.py:
    explain the math, never re-decide it.
    """
    fallback = team_narrative_without_llm(analysis)
    try:
        client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

        summary_lines = [
            f"Best-of-breed total (upper bound): {analysis.best_of_breed_total}",
        ]
        if analysis.single_suite:
            summary_lines.append(
                f"Single-suite option: {analysis.single_suite.tools[0]} "
                f"at {analysis.single_suite.coverage_pct}% of best-of-breed."
            )
        if analysis.complementary_pair:
            p = analysis.complementary_pair
            summary_lines.append(
                f"Two-tool option: {p.tools[0]} + {p.tools[1]} "
                f"at {p.coverage_pct}% of best-of-breed."
            )
        if analysis.existing_vendors:
            summary_lines.append(f"Existing platforms factored in: {', '.join(analysis.existing_vendors)}.")

        system_prompt = (
            "You explain a pre-computed AI-tool procurement analysis for a "
            "cross-functional team, in plain language for a decision-maker "
            "comparing licensing options. You are NOT allowed to change any "
            "number or recommendation -- only explain the tradeoff already "
            "computed. Be direct about the cost-of-consolidation tradeoff. "
            "Under 130 words. No preamble."
        )
        user_prompt = "\n".join(summary_lines) + (
            "\n\nExplain this procurement tradeoff in plain language for a "
            "decision-maker choosing between one tool, two tools, or full "
            "best-of-breed sprawl."
        )

        response = client.messages.create(
            model=model, max_tokens=300, system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text_blocks = [b.text for b in response.content if b.type == "text"]
        explanation = "\n".join(text_blocks).strip()
        return explanation if explanation else fallback
    except Exception:
        return fallback


def generate_team_report(
    role_tasks: list,
    registry: ToolRegistry,
    existing_vendors: list = None,
    allowed_vendors_only: bool = False,
    use_llm_explanation: bool = True,
) -> TeamReport:
    analysis = analyze_team(
        role_tasks=role_tasks,
        registry=registry,
        existing_vendors=existing_vendors or [],
        allowed_vendors_only=allowed_vendors_only,
    )

    if use_llm_explanation:
        narrative = _explain_team_with_llm(analysis)
        used_llm = True
    else:
        narrative = team_narrative_without_llm(analysis)
        used_llm = False

    return TeamReport(analysis=analysis, narrative=narrative, used_llm_explanation=used_llm)
