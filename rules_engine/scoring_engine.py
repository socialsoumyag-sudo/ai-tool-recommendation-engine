"""
scoring_engine.py

Ranking a tool against weighted criteria is arithmetic, not intelligence.
This module makes ZERO API calls, by design -- the whole point of this
project is to stop over-trusting AI where plain logic is more reliable,
auditable, and free. If you can explain a ranking with a spreadsheet,
you shouldn't need an LLM to produce it.

The only places an LLM is invoked in this project are:
  - research_agent/refresh_agent.py: refreshing stale registry data
  - research_agent/explainer_agent.py: turning scores into plain language

Everything here is pure, deterministic, and unit-testable.
"""

from dataclasses import dataclass, field
from typing import Optional

from rules_engine.task_taxonomy import FACTORS
from rules_engine.tool_registry import ToolEntry, ToolRegistry


@dataclass
class ScoredTool:
    tool: str
    weighted_score: float
    factor_scores: dict
    last_verified: str
    is_stale: bool
    source_notes: str
    runner_up_gap: Optional[float] = None  # set by rank_tools for the #1 result
    vendor: str = "Independent"
    base_score: Optional[float] = None      # weighted_score before any platform bonus
    platform_bonus: float = 0.0             # points added because of existing-platform fit


@dataclass
class RankingResult:
    task_id: str
    weights: dict
    ranked_tools: list = field(default_factory=list)  # list[ScoredTool], best first
    stale_count: int = 0
    total_count: int = 0

    @property
    def winner(self) -> Optional[ScoredTool]:
        return self.ranked_tools[0] if self.ranked_tools else None

    @property
    def runner_up(self) -> Optional[ScoredTool]:
        return self.ranked_tools[1] if len(self.ranked_tools) > 1 else None


def normalize_weights(weights: dict) -> dict:
    """Normalize a raw weights dict (e.g. slider values 0-10) so they
    sum to 1.0. Missing factors default to 0 weight. Guards against
    div-by-zero by falling back to equal weighting if everything is 0.
    """
    clean = {f: max(0.0, float(weights.get(f, 0.0))) for f in FACTORS}
    total = sum(clean.values())
    if total <= 0:
        equal = 1.0 / len(FACTORS)
        return {f: equal for f in FACTORS}
    return {f: v / total for f, v in clean.items()}


def score_entry(entry: ToolEntry, normalized_weights: dict) -> float:
    """Pure weighted-average scoring for a single tool entry.
    Score is 0-10, same scale as the underlying factor scores.
    """
    total = 0.0
    for factor in FACTORS:
        factor_score = float(entry.scores.get(factor, 0))
        total += factor_score * normalized_weights.get(factor, 0.0)
    return round(total, 2)


def rank_tools(
    task_id: str,
    weights: dict,
    registry: ToolRegistry,
    staleness_days: int = 30,
) -> RankingResult:
    """Rank all known tools for a task against the given weights.
    Returns tools best-to-worst. This is the single entry point the
    rest of the app should call -- nothing else should need to reach
    into scoring math directly.
    """
    normalized = normalize_weights(weights)
    entries = registry.entries_for_task(task_id)

    scored = []
    stale_count = 0
    for entry in entries:
        stale = entry.is_stale(staleness_days)
        if stale:
            stale_count += 1
        base = score_entry(entry, normalized)
        scored.append(
            ScoredTool(
                tool=entry.tool,
                weighted_score=base,
                factor_scores=dict(entry.scores),
                last_verified=entry.last_verified,
                is_stale=stale,
                source_notes=entry.source_notes,
                vendor=entry.vendor,
                base_score=base,
                platform_bonus=0.0,
            )
        )

    scored.sort(key=lambda s: s.weighted_score, reverse=True)

    if len(scored) >= 2:
        scored[0].runner_up_gap = round(scored[0].weighted_score - scored[1].weighted_score, 2)

    return RankingResult(
        task_id=task_id,
        weights=normalized,
        ranked_tools=scored,
        stale_count=stale_count,
        total_count=len(scored),
    )


def dominant_factor(scored_tool: ScoredTool, normalized_weights: dict) -> str:
    """Identify which factor contributed most to a tool's weighted score.
    Used by the explainer to ground its narrative in an actual number,
    not a vibe.
    """
    contributions = {
        f: scored_tool.factor_scores.get(f, 0) * normalized_weights.get(f, 0)
        for f in FACTORS
    }
    return max(contributions, key=contributions.get)


def weakest_factor(scored_tool: ScoredTool) -> str:
    """Identify the tool's lowest raw factor score -- the honest
    'here's where it falls short' data point.
    """
    return min(scored_tool.factor_scores, key=scored_tool.factor_scores.get)


DEFAULT_PLATFORM_BONUS = 0.75  # points added, on the same 0-10 scale, for
                                 # tools matching an already-owned platform.
                                 # Kept explicit and visible (never folded
                                 # silently into the base score) so a reader
                                 # can always see raw fit vs. platform fit.


def apply_platform_context(
    result: RankingResult,
    existing_vendors: Optional[list] = None,
    allowed_vendors_only: bool = False,
    platform_bonus: float = DEFAULT_PLATFORM_BONUS,
) -> RankingResult:
    """Adjusts an already-computed RankingResult for real-world procurement
    context: existing licensing/compliance sunk cost, and optionally a hard
    filter to approved vendors only (for regulated environments).

    This never touches the underlying factor scores or base_score -- it
    only adds a labeled, visible platform_bonus on top, and re-sorts.
    Nothing here calls an LLM; it's the same class of pure arithmetic as
    the rest of this module.
    """
    existing_vendors = existing_vendors or []
    tools = list(result.ranked_tools)

    if allowed_vendors_only and existing_vendors:
        tools = [t for t in tools if t.vendor in existing_vendors]

    for t in tools:
        if t.vendor in existing_vendors:
            t.platform_bonus = platform_bonus
            t.weighted_score = round(min(10.0, t.base_score + platform_bonus), 2)
        else:
            t.platform_bonus = 0.0
            t.weighted_score = t.base_score

    tools.sort(key=lambda s: s.weighted_score, reverse=True)
    if len(tools) >= 2:
        tools[0].runner_up_gap = round(tools[0].weighted_score - tools[1].weighted_score, 2)
    elif len(tools) == 1:
        tools[0].runner_up_gap = None

    return RankingResult(
        task_id=result.task_id,
        weights=result.weights,
        ranked_tools=tools,
        stale_count=sum(1 for t in tools if t.is_stale),
        total_count=len(tools),
    )
