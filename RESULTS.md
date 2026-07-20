# Results Summary

A quick-scan summary of what this pipeline actually produced, for anyone
reviewing this submission without wanting to dig through logs first. Full
detail lives in `README.md` (setup/architecture) and `architecture.pdf`
(scale/design decisions).

## Data collected (single trial run)

| Vertical | Count | Notes |
|---|---|---|
| Startups | 1,000 | Y Combinator dataset, prioritized by known/`top_company` status for stronger downstream entity resolution |
| Products | 1,000 | Product Hunt API; ~32% have an inferred pricing model from text heuristics, with an LLM backfill pass for the rest |
| Research Papers | 1,000 | Arxiv + Hugging Face + GitHub; ~13% have a live-tracked GitHub star count |
| News | 2–5 per run | Strictly 24h-fresh, AI-relevance filtered — low count is correct behavior, not a bug (see README) |
| Jobs | 2–5 per run | Strictly 24h-fresh, across 5 companies on 3 different ATS platforms | 
| Entity mappings logged | 2,000 | Every Startup/Product name resolution attempt, matched or not, is logged for auditability |

## What makes this more than "scrape 4000 rows"

- **Every record traces to a real, fetchable source URL.** No field is
  ever filled with a guess presented as fact — unclear fields are `null`,
  not invented.
- **Two real production incidents were hit, diagnosed, and fixed during
  this build**, not just anticipated in theory: a 429 that was actually a
  missing-User-Agent bot-detection issue (not a true rate limit), and a
  planned data source (Papers with Code) that turned out to be fully
  discontinued mid-project. Both are documented in `docs/anti_bot_strategy.md`
  and `architecture.pdf` with the actual fix, not a hypothetical one.
- **A real false-positive bug was found and fixed in entity resolution**:
  the initial fuzzy-matching scorer incorrectly matched unrelated names
  (e.g. "Deepika Sharma" → "Pika") due to substring-containment scoring.
  Fixed by switching scorers and adding length guards — verified against
  all 27 real false positives found in live data, now locked in as a
  regression test.
- **92 automated tests** (`tests/`, run via `pytest`) cover every module,
  including regression tests for both bugs above so they can't silently
  reappear.
- **Cross-phase integration, not siloed phases**: the Phase III LLM
  extraction chain is applied twice — once to news full-text (summary/
  entities/sentiment) and once to backfill Product pricing models the
  keyword heuristic couldn't classify, with the LLM's answer validated
  against the exact allowed enum values before being trusted.

## Honest limitations

- News/Jobs counts are intentionally small on any single run — the
  assignment asks for strictly 24-hour-fresh content, and most sources
  don't publish AI-specific news or post new AI roles every single hour.
  Running the pipeline on a schedule (e.g. hourly via a cron/scheduled
  task) would accumulate meaningfully more over a day; a single manual run
  only sees whatever's fresh at that instant.
- The entity resolution seed list (51 companies) is intentionally the
  small mock database the assignment asks for, not a comprehensive company
  database — most of the 2,000 real names it's checked against won't be in
  it, and are honestly left unresolved rather than force-matched.
- GitHub star coverage on papers (~13%) reflects that most very recently
  submitted papers haven't had a public code repo linked yet, not a gap in
  the lookup logic itself (verified: Hugging Face's Papers API and a
  regex fallback both run correctly; there's often just nothing to find).