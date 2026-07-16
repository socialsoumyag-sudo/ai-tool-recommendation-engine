"""
task_taxonomy.py

Defines the default task checklist per profession, and the weighting
factors a user can tune. This is deliberately plain data, not a database,
so it's trivial to extend with new professions/tasks without touching
any scoring logic.
"""

from dataclasses import dataclass, field
from typing import Optional


# The factors every tool is scored against, 1-10 scale.
# Kept small and orthogonal on purpose -- more factors doesn't mean
# better decisions, it means more noise in a weighted average.
FACTORS = [
    "accuracy",   # quality/reliability of output for the task
    "cost",       # inverse of $ burden (10 = cheap, 1 = expensive)
    "speed",      # latency / turnaround
    "privacy",    # data handling, enterprise/compliance readiness
    "ecosystem",  # integrations, plugins, workflow fit
    "context",    # context window, memory, ability to hold long tasks
    "ease",       # learning curve, UX friction
]

DEFAULT_WEIGHTS = {factor: 1.0 for factor in FACTORS}


@dataclass
class Task:
    id: str
    label: str
    description: str = ""


@dataclass
class Profession:
    id: str
    label: str
    tasks: list = field(default_factory=list)


PROFESSIONS = {
    "product_manager": Profession(
        id="product_manager",
        label="Product / Program Manager",
        tasks=[
            Task("prd_writing", "PRD / spec writing",
                 "Drafting structured product requirement docs from loose notes"),
            Task("roadmap_synthesis", "Roadmap synthesis",
                 "Reconciling conflicting stakeholder inputs into one roadmap narrative"),
            Task("exec_comms", "Stakeholder / exec comms",
                 "Turning status updates into crisp exec-ready summaries"),
            Task("data_analysis", "Data analysis on messy spreadsheets",
                 "Cleaning and extracting insight from unstructured tabular data"),
            Task("meeting_notes", "Meeting notes to action items",
                 "Converting transcripts/notes into tracked action items"),
            Task("competitive_research", "Competitive research",
                 "Scanning and synthesizing competitor positioning"),
            Task("technical_review", "Technical spec sanity-check",
                 "Reviewing engineering specs for gaps a non-engineer can catch"),
        ],
    ),
    "business_analyst": Profession(
        id="business_analyst",
        label="Business Analyst",
        tasks=[
            Task("requirements_gathering", "Requirements gathering",
                 "Structuring stakeholder interviews into formal requirements"),
            Task("process_mapping", "Process mapping",
                 "Documenting as-is / to-be workflows"),
            Task("data_analysis", "Data analysis & reporting",
                 "Building analysis from raw exports"),
            Task("sql_query_help", "SQL / query drafting",
                 "Writing and debugging data queries"),
            Task("stakeholder_docs", "Stakeholder documentation",
                 "Producing BRDs, FSDs, and similar formal docs"),
        ],
    ),
    "software_engineer": Profession(
        id="software_engineer",
        label="Software Development Engineer",
        tasks=[
            Task("code_generation", "Code generation",
                 "Writing new code from a spec or description"),
            Task("code_review", "Code review / debugging",
                 "Finding bugs and reviewing pull requests"),
            Task("test_writing", "Test writing",
                 "Generating unit/integration tests"),
            Task("architecture_design", "Architecture design",
                 "Reasoning about system design tradeoffs"),
            Task("documentation", "Technical documentation",
                 "Writing docs from code or vice versa"),
        ],
    ),
    "marketing_vp": Profession(
        id="marketing_vp",
        label="VP / Head of Marketing",
        tasks=[
            Task("campaign_strategy", "Campaign strategy",
                 "Drafting go-to-market and campaign strategy docs"),
            Task("content_generation", "Content generation at scale",
                 "Producing on-brand copy across channels"),
            Task("market_research", "Market & audience research",
                 "Synthesizing market data into positioning insight"),
            Task("performance_analysis", "Performance / analytics review",
                 "Interpreting campaign performance data"),
            Task("brand_voice_consistency", "Brand voice consistency",
                 "Maintaining consistent tone across long-form and short-form content"),
        ],
    ),
}


def get_profession(profession_id: str) -> Optional[Profession]:
    return PROFESSIONS.get(profession_id)


def list_professions():
    return list(PROFESSIONS.values())


def get_task(profession_id: str, task_id: str) -> Optional[Task]:
    profession = get_profession(profession_id)
    if not profession:
        return None
    for task in profession.tasks:
        if task.id == task_id:
            return task
    return None
