"""
refresh_agent.py

Refreshes STALE registry entries only (see ToolEntry.is_stale). This is
the one place in the project that does real research -- everything else
is either pure math (scoring_engine) or a single grounded explanation
call (explainer_agent). Kept isolated so it can be run on a schedule
(cron / GitHub Action) independent of the interactive app.

Each refreshed entry still requires a human-legible source_notes string
-- the model is instructed to justify its scores in one sentence, not
just emit numbers, so a reader can sanity-check the reasoning.
"""

import json
import os
from datetime import date

from anthropic import Anthropic

from rules_engine.task_taxonomy import FACTORS
from rules_engine.tool_registry import ToolEntry, ToolRegistry


def _client() -> Anthropic:
    return Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


SYSTEM_PROMPT = f"""You are a careful, skeptical AI-tools researcher.
Given a tool name and a task, use web search to find CURRENT, verifiable
information about how well that tool performs the task today.

Score the tool 1-10 on each of these factors: {", ".join(FACTORS)}.
Note: 'cost' and 'speed' must be inverted so 10 = cheap/fast (NOT 10 = expensive).

Respond with ONLY a JSON object, no other text, in this exact shape:
{{
  "scores": {{"accuracy": 0, "cost": 0, "speed": 0, "privacy": 0, "ecosystem": 0, "context": 0, "ease": 0}},
  "source_notes": "one sentence justification, plain language, no citations pasted verbatim"
}}

Be honest about mediocrity -- do not inflate scores. If you cannot find
reliable current information, score conservatively (5s) and say so in
source_notes."""


def refresh_entry(tool: str, task_id: str, model: str = "claude-sonnet-4-6") -> ToolEntry:
    """Runs ONE research-backed LLM call (with web search) for a single
    (tool, task) pair and returns a freshly-dated ToolEntry.
    """
    client = _client()
    response = client.messages.create(
        model=model,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[
            {
                "role": "user",
                "content": f"Tool: {tool}\nTask: {task_id}\n\nResearch and score this pairing.",
            }
        ],
    )

    text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    raw_text = "\n".join(text_blocks).strip()

    # Defensive parsing -- strip code fences if the model added them
    # despite instructions, rather than crashing the refresh job.
    cleaned = raw_text.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(cleaned)
        scores = {f: int(parsed["scores"].get(f, 5)) for f in FACTORS}
        notes = parsed.get("source_notes", "No notes provided.")
    except (json.JSONDecodeError, KeyError, TypeError):
        # Fail loudly in logs, but don't crash the whole refresh batch --
        # skip this entry rather than writing garbage data.
        raise ValueError(
            f"Could not parse refresh response for {tool}/{task_id}: {raw_text[:200]}"
        )

    return ToolEntry(
        tool=tool,
        task=task_id,
        scores=scores,
        last_verified=date.today().isoformat(),
        source_notes=notes,
    )


def refresh_stale_entries(
    registry: ToolRegistry,
    staleness_days: int = 30,
    max_refreshes: int = 20,
) -> dict:
    """Scans the registry for stale entries and refreshes them in place.
    Returns a summary dict: {"refreshed": [...], "failed": [...]}.
    Caps refreshes per run (max_refreshes) to keep API spend predictable --
    this is a batch job, not an unbounded loop.
    """
    stale = [e for e in registry.all_entries() if e.is_stale(staleness_days)]
    stale = stale[:max_refreshes]

    refreshed, failed = [], []
    for entry in stale:
        try:
            new_entry = refresh_entry(entry.tool, entry.task)
            registry.upsert_entry(new_entry)
            refreshed.append(f"{entry.tool}/{entry.task}")
        except Exception as exc:
            failed.append(f"{entry.tool}/{entry.task}: {exc}")

    if refreshed:
        registry.save()

    return {"refreshed": refreshed, "failed": failed, "skipped_count": max(0, len(
        [e for e in registry.all_entries() if e.is_stale(staleness_days)]
    ))}
