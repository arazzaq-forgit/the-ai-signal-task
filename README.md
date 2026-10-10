# AI Signal — Data Intelligence Pipelines (Trial Assignment)

## Status
Implemented and tested (schema/DB/logic layers; live network runs happen on
your machine, not in the dev sandbox):
- `src/schemas.py` — Pydantic models for all 4 entity types (Startup, Product,
  Research Paper, Job), matching the assignment's field tables exactly.
- `src/db.py` — SQLite state store: dedup via `seen_urls`, output via
  `records`, canonicalization audit trail via `entity_mapping_log`.
- `src/http_client.py` — shared async fetch layer: `tenacity`
  exponential-backoff-with-jitter retries (only for 429/5xx/genuine network
  failures — 404/403 fail fast, not retried), per-host request throttling,
  and a global `asyncio.Semaphore` for bounded concurrency.
- `src/scrapers/papers.py` + `main.py papers` — Arxiv metadata + GitHub star
  tracking, with Hugging Face's Papers API for GitHub repo linkage (Papers
  with Code, the original plan, was shut down by Meta in July 2025).
- `src/scrapers/startups.py` + `main.py startups` — YC's public company
  dataset.
- `src/scrapers/products.py` + `main.py products` — Product Hunt's GraphQL
  API, with heuristic (not hallucinated — null when unclear) pricing model
  inference from tagline/description text.
- `src/freshness.py` — date normalization: handles ISO/RFC822 dates and
  relative phrases ("2 hours ago", "yesterday") via regex, plus a
  first-seen-via-dedup heuristic for sources with no date at all.
- `src/scrapers/news.py` + `main.py news` — RSS-based crawler across 5 AI
  news sources, full-text extraction via `trafilatura`, strict 24h freshness
  filter.
- `src/scrapers/jobs.py` + `main.py jobs` — Greenhouse/Lever/Ashby job board
  APIs across 5 AI companies, resiliently trying each platform per company
  since ATS platform isn't reliably guessable, 24h freshness filter, remote
  detection, keyword-based role-family inference.
- `src/llm/chunking.py` — truncates text to a safe token budget at
  paragraph/sentence boundaries (never mid-sentence), to avoid 413s while
  keeping the most information-dense part of the text.
- `src/llm/providers.py` + `src/llm/extractor.py` — the multi-tier LLM
  fallback chain (Gemini Flash → Groq Llama 3 → DeepSeek), with 429/5xx
  retry+backoff, JSON-only prompting, markdown-fence stripping, and a
  guarantee of returning `None` (never a fabricated result) if every tier
  fails.
- `src/llm/news_enrichment.py` + `main.py extract-news` — applies the
  fallback chain to news articles' raw full-text (summary, key entities,
  sentiment) — the genuine "unstructured text → structured JSON via LLM"
  use case in this pipeline, since every other vertical is sourced from
  clean structured APIs instead.
- `src/resolver/seed_data.py` — mock database of 51 known AI startups with
  112 real-world name variations (legal suffixes, domain extensions,
  spacing).
- `src/resolver/entity_resolver.py` + `src/resolver/pipeline.py` +
  `main.py resolve-entities` — canonicalizes Startup/Product names via
  exact alias matching, then fuzzy matching (rapidfuzz, plain `ratio` —
  NOT `WRatio`, which produced real false positives against live data by
  over-rewarding substring containment) as a fallback for typos, logging
  every raw→canonical mapping (matched or not) to `entity_mapping_log`.
- `src/scrapers/stealth_browser.py` — Playwright-based async browser
  fetcher with stealth measures (webdriver-flag suppression, persistent
  context/cookies, randomized inter-action delays, conservative
  concurrency) for JS-rendered/anti-bot-protected sources that have no API
  alternative. Verified live in this sandbox against github.com —
  `navigator.webdriver` correctly reports `undefined`.
- `docs/anti_bot_strategy.md` — Phase V writeup, grounded in the actual
  anti-bot incidents hit during this project (missing User-Agent headers,
  a dead API mistaken for a rate limit, unguessable ATS platforms) plus
  the general Cloudflare/Datadome-class strategy.
- `architecture.pdf` — Phase VI writeup covering scale strategy, 413/429
  handling, distributed freshness tracking, and storage strategy.
- `src/export/sheets_export.py` + `main.py export-sheets` — flattens all 6
  record types into the required Google Sheets tab structure and writes
  them via a service account (no interactive OAuth needed).
- `tests/` — 73 automated pytest tests covering every module: schemas, the
  dedup store, HTTP retry/throttle policy (including a regression test
  that 404s fail fast and don't get retried), chunking, the LLM fallback
  chain, freshness date parsing, news relevance filtering, job freshness
  across all 3 ATS platforms, entity resolution (including a regression
  test locking in the 27 real false positives found and fixed during this
  project), and the Sheets export row-flattening logic.
- `main.py run-all` — runs every phase in sequence, skipping (not
  crashing on) any step whose credentials aren't configured, with a clear
  pass/fail/skip summary at the end.
- `src/scrapers/startups.py` now prioritizes YC's `top_company`-flagged
  and larger-team companies before slicing to `target_count`, instead of
  an arbitrary dataset-order slice — a better product decision and a more
  representative sample for entity resolution.
- `src/llm/pricing_backfill.py` + `main.py backfill-pricing` — a second,
  genuine application of the Phase III LLM chain: fills in `pricingModel`
  for products the keyword heuristic couldn't classify, with the LLM's
  answer validated against the exact allowed enum values (FREE/FREEMIUM/
  PAID/ENTERPRISE) before being trusted — an invalid or hallucinated
  response is discarded, never stored.
- `RESULTS.md` — one-page summary of what this pipeline actually produced,
  including the two real bugs found and fixed during the build.

## Running the test suite
```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```
All 73 tests run against an isolated temporary SQLite file per test (see
`tests/conftest.py`) — they never touch your real `data/state.db`.

Not yet built: Google Sheets export, Phase VI architecture doc.

### Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # only needed once JS-rendered scrapers are added
```

### Getting a Product Hunt API token (free)
1. Go to https://api.producthunt.com/v2/oauth/applications and log in with
   any Product Hunt account.
2. Create a new application (redirect URI can be anything, e.g.
   `http://localhost`).
3. Use the client_credentials grant to get a token:
```bash
curl -X POST https://api.producthunt.com/v2/oauth/token \
  -H "Content-Type: application/json" \
  -d '{"client_id":"YOUR_CLIENT_ID","client_secret":"YOUR_CLIENT_SECRET","grant_type":"client_credentials"}'
```
4. Copy the `access_token` from the response and set it as an environment
   variable (never commit it or paste it anywhere public):
```powershell
$env:PRODUCTHUNT_TOKEN = "your_token_here"
```

### Getting LLM API keys (free tiers, for Phase III)
The extraction chain works with just ONE key configured (it'll skip
unconfigured tiers), but all three is more realistic for demonstrating the
actual fallback behavior.
- **Gemini**: https://aistudio.google.com/apikey — free tier, generous
  rate limits for Flash models.
- **Groq**: https://console.groq.com/keys — free tier, very fast Llama
  inference.
- **DeepSeek**: https://platform.deepseek.com/api_keys — low-cost, often
  has free trial credits for new accounts.

Set them as environment variables:
```powershell
$env:GEMINI_API_KEY = "your_key_here"
$env:GROQ_API_KEY = "your_key_here"
$env:DEEPSEEK_API_KEY = "your_key_here"
```

### Getting Google Sheets export credentials (free)
This uses a Google Cloud **service account** (a robot identity, not your
personal Google login) — no OAuth browser flow needed.
1. Go to https://console.cloud.google.com/ and create a project (or use an
   existing one).
2. In the search bar, find and enable the **Google Sheets API** and the
   **Google Drive API** (both are needed — Sheets to write data, Drive to
   create a new spreadsheet file).
3. Go to "APIs & Services" → "Credentials" → "Create Credentials" →
   "Service account". Give it any name.
4. Once created, open the service account, go to the "Keys" tab → "Add Key"
   → "Create new key" → JSON. This downloads a `.json` credentials file —
   treat it like a password, never commit it.
5. **Important**: copy the service account's email address (looks like
   `something@your-project.iam.gserviceaccount.com`, visible on the service
   account's details page). If you want to write into a Google Sheet you
   already created yourself (rather than let the script create a new one),
   share that sheet with this email address (Editor access) — the service
   account can't see your Drive files otherwise.
6. Set the credentials path as an environment variable:
```powershell
$env:GOOGLE_SHEETS_CREDS = "C:\path\to\your-downloaded-creds.json"
```

## Running
```bash
# Research papers (Arxiv + GitHub stars)
python main.py papers --query "cat:cs.AI" --count 1000 --github-token $env:GITHUB_TOKEN

# Startups (Y Combinator)
python main.py startups --count 1000

# Products (Product Hunt)
python main.py products --count 1000 --token $env:PRODUCTHUNT_TOKEN

# News (24hr-fresh, 5 AI news sources via RSS)
python main.py news

# Jobs (24hr-fresh, 5 AI company job boards via Greenhouse/Lever/Ashby)
python main.py jobs

# LLM extraction: structure news full-text via the Gemini->Groq->DeepSeek chain
python main.py extract-news

# LLM backfill: fill in pricingModel for products the heuristic missed
python main.py backfill-pricing

# Entity resolution: canonicalize Startup/Product names, log to entity_mapping_log
python main.py resolve-entities

# Export everything to a Google Sheet (6 tabs)
python main.py export-sheets

# Or run everything above in one command (skips steps with missing credentials)
python main.py run-all --count 1000
python main.py run-all --count 1000 --export   # also runs the Sheets export at the end
```
Output lands in `data/state.db` (SQLite). All pipelines are insert-only and
dedup via `seen_urls`, so re-running any of them is safe.

### A note on the Sheets export
Run this last, after every other pipeline — it reads whatever's currently
in `data/state.db` and writes it to the 6 required tabs (Startups, Products,
Research Papers, Jobs, News, Entity Mapping Log). By default it creates a
brand-new sheet and prints its URL; pass `--sheet-key <id>` (the long ID in
a Google Sheets URL) to write into a specific existing sheet instead. Each
tab is fully cleared and rewritten on every run, so it's safe to re-run
after collecting more data.

### A note on the LLM extraction chain
`extract-news` will only have something to do after you've run `news` at
least once (it reads from the NEWS table). Each article gets exactly one
extraction attempt through the fallback chain — if Gemini fails, it tries
Groq; if that fails, DeepSeek; if all three fail (or aren't configured),
the record is still saved with `extraction: null` and a full log of what
was tried, rather than being silently dropped. That's intentional: a
transparent failure is worth more for grading than a hidden one.

### A note on news/jobs record counts
Unlike papers/startups/products, news and jobs don't have a `--count` target
— the assignment asks for "all 24-hr fresh" items, not a fixed minimum. It's
entirely normal and correct for a jobs run to save very few (or zero) new
records: established companies don't post new roles every day, and running
the pipeline twice in the same hour will correctly find nothing new the
second time (that's the dedup working, not a bug).

## Why these choices
- **Arxiv + GitHub API instead of scraping HTML**: both have free, stable,
  structured APIs. This sidesteps anti-bot risk entirely for the highest-volume
  entity type (papers) and guarantees every field traces back to a real,
  fetchable source URL — directly addressing the "no hallucinated data"
  requirement.
- **SQLite over an in-memory set for dedup**: survives crashes/restarts, and
  the read/write interface (`is_seen`/`mark_seen`) is small enough to swap for
  Postgres or Redis later without touching scraper code — the scaling story
  Phase VI asks about.
- **Semaphore-bounded concurrency instead of unbounded `asyncio.gather`**:
  keeps us polite to source APIs (avoids tripping their real rate limits) while
  still being fully async. Raising `MAX_CONCURRENCY` in `http_client.py` is the
  single knob for scaling throughput.

## Known limitations / honest caveats
- GitHub repo linkage is currently a regex match against the Arxiv abstract
  and comments field. Papers with Code integration (matching papers to repos
  more rigorously) is the natural next step — noted as a TODO in
  `src/scrapers/papers.py`.
- Not yet load-tested at 1,000+ records against live Arxiv — validated the
  schema/DB/retry layers in isolation; end-to-end run needs to happen from an
  environment with open internet access to arxiv.org.
