"""
report_generator.py

Thin orchestration layer: takes a user's task + weights, calls the
deterministic scoring engine, optionally calls the explainer agent,
and packages everything into a single Report the dashboard can render.

No business logic lives here -- this file should stay boring on purpose.
"""

from dataclasses import dataclass, field
from datetime import date

from rules_engine.scoring_engine import RankingResult, rank_tools
from rules_engine.tool_registry import ToolRegistry
from research_agent.explainer_agent import explain_with_llm, explain_without_llm


@dataclass
class Report:
    task_id: str
    task_label: str
    ranking: RankingResult
    narrative: str
    generated_on: str = field(default_factory=lambda: date.today().isoformat())
    used_llm_explanation: bool = False

    def freshness_summary(self) -> str:
        if self.ranking.total_count == 0:
            return "No data available for this task yet."
        fresh = self.ranking.total_count - self.ranking.stale_count
        return (
            f"{fresh} of {self.ranking.total_count} tool entries verified "
            f"within the last 30 days as of {self.generated_on}."
        )


def generate_report(
    task_id: str,
    task_label: str,
    weights: dict,
    registry: ToolRegistry,
    use_llm_explanation: bool = True,
) -> Report:
    ranking = rank_tools(task_id=task_id, weights=weights, registry=registry)

    if use_llm_explanation:
        narrative = explain_with_llm(ranking, task_label=task_label)
        used_llm = True
    else:
        narrative = explain_without_llm(ranking)
        used_llm = False

    return Report(
        task_id=task_id,
        task_label=task_label,
        ranking=ranking,
        narrative=narrative,
        used_llm_explanation=used_llm,
    )
