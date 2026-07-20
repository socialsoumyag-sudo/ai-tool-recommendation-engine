# AI Tool Recommendation Engine

**Stop guessing which AI tool to use. Get a decision, not a listicle — with the runner-up's exact tradeoff shown, not hidden.**

Most "best AI tools" content is a static ranked list that's stale in six weeks and never tells you *why* the #2 tool lost. This tries to do the opposite: a live, re-weightable ranking that shows its math, dates its data, and is honest when the popular tool isn't actually the best fit.

---

## The problem

Working professionals default to whatever AI tool their company already pays for, or whatever's trending on LinkedIn this week — not necessarily the one that's actually best for the task in front of them. Meanwhile the tools themselves are moving fast enough that any static comparison is out of date before it's finished being written.

This came out of noticing the same pattern that motivated my two earlier projects: the actual answer people need is usually a structured comparison against *their own* priorities, not a generic "top 10" that assumes everyone weighs cost, privacy, and quality the same way.

## The core idea — and the deliberate irony

A tool that ranks AI tools would be a little absurd if it burned an LLM call just to do arithmetic. So this one doesn't:

- **The ranking itself makes zero API calls.** Weighted scoring across factors is math, not intelligence — `rules_engine/scoring_engine.py` is pure, deterministic, and fully unit-tested. You can audit exactly why a tool won using nothing but the JSON registry and a calculator.
- **The plain-language explanation is exactly one optional LLM call**, and it's not allowed to re-rank or invent a score — it's handed the already-computed numbers and told to explain them, with a deterministic fallback if no API key is set.
- **Refreshing tool data is a separate, scheduled job**, not something that happens on every page load — `research_agent/refresh_agent.py` uses live web search to re-verify only entries older than 30 days, and writes back an explicit `last_verified` date so nothing pretends to be more current than it is.

Same philosophy as [ai-readiness-advisor](https://github.com/socialsoumyag-sudo/ai-readiness-advisor): judgment over enthusiasm. More AI is not automatically the answer, including inside a tool about AI.

## What it does

**Individual mode:**
1. **Pick your profession and task** — 10 professions ship with a default task checklist (`rules_engine/task_taxonomy.py`): Product/Program Manager, Business Analyst, Software Development Engineer, VP/Head of Marketing, Data Scientist/ML Engineer, HR Business Partner, Sales/Account Executive, Finance Analyst (FP&A), Customer Support Lead, and Legal Counsel/Paralegal. Easy to extend further.
2. **Set your weights** — seven factors (accuracy, cost, speed, privacy, ecosystem, context window, ease of use), tunable per person because a solo builder and an enterprise compliance team should never get the same ranking for the same task.
3. **Get a ranked, dated, sourced result** — a radar chart across the top 3 tools, a full ranked table, and a narrative that explains not just why the winner won, but *specifically what number* cost the runner-up first place.

**Team & Portfolio mode** — the realistic version of this question. A single-role ranking is easy; the actual decision a company faces is cross-functional: PM + BA + SDE + Marketing all need different things, and buying a different tool per person per task isn't realistic procurement. This mode answers three questions at once, side by side:
- **Best-of-breed** — the upper bound: best tool per task, ignoring consolidation
- **Single suite** — the one tool that covers the whole team best, with an honest "you give up X% quality" number
- **Complementary pair** — the two-tool combination (brute-force exact, not heuristic) that recovers the most lost quality — usually the realistic answer

**Company context (both modes)** — tell it which platforms you already own (Google, Microsoft, Anthropic, OpenAI, etc.) and matching tools get a small, *explicitly visible* fit bonus reflecting sunk licensing and pre-vetted compliance — never folded silently into the base score. A hard "approved vendors only" filter is also available for regulated environments.

Pre-generated examples are included at `data/sample_output.json` (individual mode) and `data/sample_team_output.json` (team mode) so you can see real output without needing an API key first.

## Architecture

```
Profession + Task + Weights ──► rules_engine/scoring_engine.py   (NO LLM call)
                                 weighted-average scoring, pure math
                                          │
                                          ▼
                                 rules_engine/tool_registry.py
                                 (JSON-backed capability data, dated + vendor-tagged per entry)
                                          │
                          ┌───────────────┼────────────────────────────┐
                          ▼               ▼                            ▼
        research_agent/refresh_agent.py   apply_platform_context()     rules_engine/team_engine.py
        (scheduled job, web search,       (NO LLM call — explicit,     (NO LLM call — best-of-breed
         re-verifies stale entries only)   visible existing-platform    vs single-suite vs
                          │                bonus + approved-vendor      complementary-pair, exact
                          │                hard filter)                 brute-force over tool pairs)
                          │                        │                            │
                          │                        ▼                            ▼
                          │           advisor/report_generator.py   advisor/team_report_generator.py
                          │                        │                            │
                          │                        └──────────┬─────────────────┘
                          │                                   ▼
                          │                    research_agent/explainer_agent.py
                          │                    (ONE optional LLM call, grounded
                          │                     strictly in already-computed scores)
                          └───────────────────────────────────┬
                                                                ▼
                                           dashboard/app.py (Streamlit, themed)
                                Individual mode: radar + ranked table + narrative
                                Team mode: best-of-breed / single-suite / pair tradeoff + bar chart
```

## Quickstart

```bash
git clone <this-repo>
cd ai-tool-recommendation-engine
pip install -r requirements.txt
cp .env.example .env   # only needed for the LLM explanation + refresh job

streamlit run dashboard/app.py
```

The profession/task picker, weight sliders, radar chart, and ranked table all work **with no API key** — try those first. Uncheck "Generate plain-language explanation" in the sidebar to run the entire session with zero API calls.

```bash
# Run all tests (no API key needed — 29 tests total, deterministic logic only)
python tests/test_scoring_engine.py
python tests/test_team_engine.py

# Refresh stale registry entries via live web research (needs ANTHROPIC_API_KEY)
python -c "from rules_engine.tool_registry import ToolRegistry; from research_agent.refresh_agent import refresh_stale_entries; print(refresh_stale_entries(ToolRegistry()))"
```

## Why this is more than a wrapper

- **Grounded, not vibes-based**: every score in the registry carries a one-sentence `source_notes` justification and a `last_verified` date — nothing is asserted without a traceable, dated reason.
- **The explanation can't lie about the math**: `explainer_agent.py` is explicitly instructed not to re-rank or introduce new claims — it explains the `RankingResult` object it's handed, nothing else. A malformed or missing API response falls back to a deterministic explanation, never a broken page.
- **Freshness is a first-class citizen, not an afterthought**: every report displays "N of M entries verified in the last 30 days" and flags stale entries individually, rather than presenting all data with equal (false) confidence.
- **Tested where testing is meaningful**: `tests/test_scoring_engine.py` covers weight normalization, scoring math, ranking order, and edge cases (all-zero weights, missing scores, malformed dates) — deterministic logic only, no assertions on non-deterministic LLM text.
- **Fails loudly, not silently**: `refresh_agent.py` raises on unparseable model output rather than silently writing garbage scores into the registry.

## Scope — what this does *not* do (yet)

- The seed registry (`data/tool_registry.json`) now covers 106 entries across 10 professions and ~35 tasks — a real foundation, still not an exhaustive market map. A few domain-specific tools (Textio, Salesforce Einstein Copilot, Intercom Fin, Harvey) are included alongside the generalist tools for realism.
- Tool capability scores are directional judgment calls with stated reasoning, not benchmarked lab results — treat the ranking as a structured starting point for a decision, not a certification.
- The refresh job is designed to be run on a schedule (cron / GitHub Action) — it does not run automatically on every dashboard load, by design, to keep API spend predictable.
- No persistence of past reports or user accounts yet — each session is a one-off, not a tracked history (a natural v2 addition).
- Team mode applies one shared set of priority weights across every role/task in the team, by design, to keep the UI usable — a natural v2 is per-row weight overrides for teams where roles genuinely disagree on priorities.
- The complementary-pair search is brute-force over all tool pairs — fine at the current registry size, but would need a smarter search (or a cap) if the tool catalog grows into the hundreds.
- The existing-platform bonus is a single flat constant (`DEFAULT_PLATFORM_BONUS`) applied uniformly — a real procurement decision would also weigh actual negotiated contract value, which varies per company and isn't modeled here.

## Tech stack

Python · Anthropic API (Claude, incl. web search tool) · Streamlit · Plotly · pandas · pytest/unittest

## Background

Built by [Soumya Ghatak](https://linkedin.com/in/soumyaghatakiimb) — Senior Program/Product Manager, IIM Bangalore MBA, PMP®. Third in a series of shipped agentic tools, following the same judgment-over-enthusiasm philosophy as [stakeholder-sentiment-analyzer](https://github.com/socialsoumyag-sudo/stakeholder-sentiment-analyzer) and [ai-readiness-advisor](https://github.com/socialsoumyag-sudo/ai-readiness-advisor) — applied here to the everyday decision of which AI tool actually fits the task in front of you.
