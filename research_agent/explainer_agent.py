"""
explainer_agent.py

Exactly ONE LLM call. Its only job: take numbers that scoring_engine.py
already computed and explain them in plain language -- including WHY
the runner-up lost, not just why the winner won. It never re-scores,
never re-ranks, and never invents a number that isn't already in the
RankingResult it's given.

If this call fails or the API key is missing, the app should still work
using explain_without_llm() as a graceful, fully deterministic fallback --
consistent with this project's stance that the ranking itself never
depends on AI being available.
"""

import os
from anthropic import Anthropic

from rules_engine.scoring_engine import RankingResult, dominant_factor, weakest_factor
from rules_engine.task_taxonomy import FACTORS


def _client() -> Anthropic:
    return Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def explain_without_llm(result: RankingResult) -> str:
    """Deterministic fallback narrative -- no API key required.
    Less fluent than the LLM version, but fully honest and always available.
    """
    winner = result.winner
    if not winner:
        return "No tools found for this task yet. Try refreshing the registry."

    lines = [
        f"Top pick: {winner.tool} (score {winner.weighted_score}/10)."
    ]
    top_factor = dominant_factor(winner, result.weights)
    weak_factor = weakest_factor(winner)
    lines.append(
        f"Its biggest contributor was {top_factor} "
        f"({winner.factor_scores.get(top_factor)}/10); "
        f"its weakest factor was {weak_factor} "
        f"({winner.factor_scores.get(weak_factor)}/10)."
    )

    runner_up = result.runner_up
    if runner_up:
        lines.append(
            f"Runner-up: {runner_up.tool} (score {runner_up.weighted_score}/10, "
            f"{winner.runner_up_gap} points behind). "
            f"It fell short mainly on {dominant_factor(winner, result.weights)} "
            f"relative weighting."
        )

    if winner.is_stale:
        lines.append(
            f"Note: this data was last verified {winner.last_verified} and "
            f"may be stale -- consider refreshing before relying on it."
        )

    return "\n".join(lines)


def explain_with_llm(result: RankingResult, task_label: str, model: str = "claude-sonnet-4-6") -> str:
    """LLM-generated explanation. Grounded strictly in the numbers already
    computed by scoring_engine -- the prompt hands over the actual scores
    and forbids introducing new claims or re-ranking.
    """
    if not result.ranked_tools:
        return explain_without_llm(result)

    top_n = result.ranked_tools[:3]
    scores_block = "\n".join(
        f"- {t.tool}: weighted score {t.weighted_score}/10, "
        f"factor scores {t.factor_scores}, "
        f"last verified {t.last_verified}"
        for t in top_n
    )

    system_prompt = (
        "You explain pre-computed AI-tool rankings in plain, confident "
        "language for a busy professional. You are NOT allowed to change, "
        "re-rank, or invent any score -- only explain the numbers you are "
        "given. Always state clearly why the runner-up lost, using the "
        "actual factor scores, not vague language. Keep it under 120 words. "
        "No preamble, no restating the task."
    )

    user_prompt = (
        f"Task: {task_label}\n\n"
        f"Ranked tools (best first):\n{scores_block}\n\n"
        "Explain the winner's edge and specifically why the runner-up "
        "fell short, citing the actual factor scores."
    )

    try:
        client = _client()
        response = client.messages.create(
            model=model,
            max_tokens=300,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text_blocks = [b.text for b in response.content if b.type == "text"]
        explanation = "\n".join(text_blocks).strip()
        return explanation if explanation else explain_without_llm(result)
    except Exception:
        # Never let an API hiccup break the report -- fall back to the
        # deterministic explanation, which is always available.
        return explain_without_llm(result)
