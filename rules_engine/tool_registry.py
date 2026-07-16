"""
tool_registry.py

Loads and queries the tool capability registry (data/tool_registry.json).
This module has NO opinions about ranking -- it just answers "what data
do we have for tool X on task Y". Scoring/ranking logic lives entirely
in scoring_engine.py, kept separate on purpose so each piece is testable
in isolation.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

_REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "tool_registry.json",
)


@dataclass
class ToolEntry:
    tool: str
    task: str
    scores: dict
    last_verified: str
    source_notes: str
    vendor: str = "Independent"

    def days_since_verified(self) -> int:
        try:
            verified_date = datetime.strptime(self.last_verified, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return 9999
        return (datetime.now(timezone.utc) - verified_date).days

    def is_stale(self, staleness_days: int = 30) -> bool:
        return self.days_since_verified() > staleness_days


class ToolRegistry:
    def __init__(self, path: str = _REGISTRY_PATH):
        self.path = path
        self._entries: list[ToolEntry] = []
        self._load()

    def _load(self):
        with open(self.path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self._entries = [
            ToolEntry(
                tool=e["tool"],
                task=e["task"],
                scores=e["scores"],
                last_verified=e["last_verified"],
                source_notes=e.get("source_notes", ""),
                vendor=e.get("vendor", "Independent"),
            )
            for e in raw.get("entries", [])
        ]

    def entries_for_task(self, task_id: str) -> list[ToolEntry]:
        return [e for e in self._entries if e.task == task_id]

    def all_entries(self) -> list[ToolEntry]:
        return list(self._entries)

    def upsert_entry(self, entry: ToolEntry):
        """Replace an existing (tool, task) entry or append a new one.
        Used by refresh_agent to write back freshly researched data.
        """
        for i, existing in enumerate(self._entries):
            if existing.tool == entry.tool and existing.task == entry.task:
                self._entries[i] = entry
                return
        self._entries.append(entry)

    def save(self, path: Optional[str] = None):
        target = path or self.path
        payload = {
            "_meta": {
                "schema_version": 1,
                "note": (
                    "Scores are 1-10 per factor, per (tool, task) pair. "
                    "'cost' and 'speed' are already inverted so that 10 = "
                    "cheap/fast, consistent with the other factors where "
                    "higher is always better."
                ),
            },
            "entries": [
                {
                    "tool": e.tool,
                    "task": e.task,
                    "scores": e.scores,
                    "last_verified": e.last_verified,
                    "source_notes": e.source_notes,
                    "vendor": e.vendor,
                }
                for e in self._entries
            ],
        }
        with open(target, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def known_tools_for_task(self, task_id: str) -> list[str]:
        return sorted({e.tool for e in self.entries_for_task(task_id)})

    def vendor_for_tool(self, tool_name: str) -> str:
        """Looks up a tool's vendor from any entry mentioning it. Tools are
        assumed to have one consistent vendor across all their task entries.
        """
        for e in self._entries:
            if e.tool == tool_name:
                return e.vendor
        return "Independent"

    def known_vendors(self) -> list[str]:
        return sorted({e.vendor for e in self._entries})
