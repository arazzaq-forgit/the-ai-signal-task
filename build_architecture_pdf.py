"""Generates architecture.pdf from content addressing Phase VI's 4 required
topics. Run once locally: python build_architecture_pdf.py"""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="H1", parent=styles["Heading1"], spaceBefore=14, spaceAfter=6, fontSize=15))
styles.add(ParagraphStyle(name="H2", parent=styles["Heading2"], spaceBefore=10, spaceAfter=4, fontSize=12))
styles.add(ParagraphStyle(name="BodyText2", parent=styles["BodyText"], spaceAfter=8, leading=14))
styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=9, textColor="#555555", spaceAfter=10, leading=12))

doc = SimpleDocTemplate(
    "architecture.pdf",
    pagesize=letter,
    topMargin=0.7 * inch,
    bottomMargin=0.7 * inch,
    leftMargin=0.75 * inch,
    rightMargin=0.75 * inch,
)

story = []

def h1(text):
    story.append(Paragraph(text, styles["H1"]))

def h2(text):
    story.append(Paragraph(text, styles["H2"]))

def p(text):
    story.append(Paragraph(text, styles["BodyText2"]))

def small(text):
    story.append(Paragraph(text, styles["Small"]))

def bullets(items):
    story.append(ListFlowable(
        [ListItem(Paragraph(i, styles["BodyText2"]), leftIndent=12) for i in items],
        bulletType="bullet", start="•",
    ))

# Title
story.append(Paragraph("Data Intelligence Pipeline — Architecture & Production Design", styles["Title"]))
small("AI Engineer / Data Intelligence Trial Assignment — Architecture Document")

# 1. Scale Strategy
h1("1. Scale Strategy: Collecting 500,000+ Records Without Manual Intervention")
p("The core scale principle applied throughout this pipeline is <b>prefer a structured API "
  "over scraping a web page, wherever one exists</b> — and where a page must be dealt with, "
  "prefer async concurrency with per-source throttling over brute-force parallelism. This trial "
  "implementation collects 1,000 records per vertical (startups, products, papers) as a demonstration; "
  "scaling to 500k is an infrastructure change, not a code change, for the following reasons:")
bullets([
    "<b>Papers (Arxiv + Hugging Face + GitHub):</b> the Arxiv API is queried by category "
    "(<i>cat:cs.AI</i>). Sharding across additional categories (cs.CL, cs.LG, cs.CV, ...) and running "
    "each shard as an independent worker process trivially multiplies throughput with zero code "
    "change — <code>src/scrapers/papers.py</code>'s <code>run_papers_pipeline(query, target_count)</code> "
    "already takes the query as a parameter for exactly this reason.",
    "<b>Startups (YC dataset) / Products (Product Hunt):</b> Product Hunt's GraphQL API is "
    "cursor-paginated already (<code>src/scrapers/products.py</code>) — raising <code>target_count</code> "
    "is the only change needed to pull more. The YC dataset is a bounded snapshot (~6,000 companies); "
    "scaling this vertical past that ceiling means adding more directory sources in the same file shape "
    "(each a <code>run_x_pipeline()</code> function), run as parallel workers.",
    "<b>Concurrency model:</b> every scraper uses <code>asyncio</code> + <code>aiohttp</code> with a "
    "global <code>asyncio.Semaphore</code> (<code>src/http_client.py</code>) bounding in-flight requests, "
    "plus a per-host minimum-interval throttle keyed by domain. This is the single knob that scales: "
    "raising <code>MAX_CONCURRENCY</code> and/or running additional worker processes/containers scales "
    "throughput without touching scraper logic.",
    "<b>Distributed workers, not a bigger single process:</b> the practical path to 500k is running "
    "N worker processes (one per source-shard, e.g. one per Arxiv category or one per job board), each "
    "independently rate-limited to its own source's real tolerance, writing to a shared datastore "
    "(see Storage Strategy) rather than scaling a single process's concurrency indefinitely — a single "
    "process hitting one source harder eventually just trips that source's real rate limit, which this "
    "project hit firsthand (see Section 2).",
])

# 2. Handling 413s and 429s
h1("2. Handling 413 (Payload Too Large) and 429 (Rate Limited)")
h2("429 — Rate Limits")
p("<code>src/http_client.py</code> implements two complementary layers: (a) <b>reactive</b> — "
  "a <code>tenacity</code>-based retry decorator with exponential backoff and jitter, triggered only "
  "on 429/5xx/genuine network failures (explicitly <i>not</i> on 404/403/other 4xx, which are retried "
  "elsewhere in this project by mistake early on and cost real time before being fixed — see "
  "<code>ClientHTTPError</code>); and (b) <b>proactive</b> — a per-host minimum-interval throttle "
  "(<code>MIN_INTERVAL_SECONDS</code>) that paces requests to each source's own documented or observed "
  "tolerance before a 429 ever happens. This project's real Hugging Face Papers API integration hit "
  "persistent 429s that turned out to be a missing-User-Agent bot-detection issue, not a true rate "
  "limit — fixing the header, not just slowing down further, resolved it. The general lesson encoded "
  "into policy: identify yourself correctly first, then throttle to the source's real documented limit "
  "(discovered here via the API's own <code>RateLimit-Policy</code> response header).")
h2("413 — Payload Too Large / Context Window Overflows")
p("The LLM extraction chain (<code>src/llm/chunking.py</code>) truncates any input text to a "
  "conservative character budget (default 6,000 chars, well under any provider's real context window) "
  "<i>before</i> sending it, so 413s are avoided proactively rather than caught and retried. Truncation "
  "prefers the nearest paragraph boundary within budget, then the nearest sentence boundary, and only "
  "falls back to a hard character cut as a last resort — a mid-sentence cut risks the model inventing a "
  "plausible-sounding completion, which is a hallucination risk this project explicitly avoids "
  "throughout. <code>src/http_client.py</code> also has an explicit <code>PayloadTooLargeError</code> "
  "raised on an actual 413 response, for defense in depth if a payload slips past the proactive budget.")
h2("At thousands of concurrent extractions")
p("The same per-host throttle and bounded semaphore used for scraping apply identically to the three "
  "LLM providers (<code>src/llm/providers.py</code>). Each provider has its own throttle interval, "
  "calibrated to its real published/observed rate limit rather than a single global guess — Groq's "
  "generous free-tier limits get a much shorter interval than Gemini's stricter one, for example. This "
  "is the same principle as Section 2's 429 handling, applied to LLM calls specifically.")

# 3. Freshness Tracking
h1("3. Freshness Tracking Across Distributed Crawler Nodes")
p("Every pipeline in this project — not just news/jobs — dedups through a single shared mechanism: "
  "<code>src/db.py</code>'s <code>seen_urls</code> table, keyed on the record's real source URL. "
  "<code>is_seen(url)</code> is checked before processing and <code>mark_seen(url, record_type)</code> "
  "is called whether or not the record ultimately passed the freshness filter — so a URL that was "
  "checked once and found stale (or duplicate) is never re-fetched or re-evaluated on a later run.")
p("For distributed nodes specifically: this trial uses SQLite for simplicity, which is single-writer "
  "and not safely shared across multiple machines. The <code>is_seen</code>/<code>mark_seen</code>/"
  "<code>save_record</code> interface in <code>src/db.py</code> is intentionally small and storage-"
  "agnostic — swapping the SQLite implementation for Postgres (with a unique constraint on "
  "<code>url</code>) or Redis (a distributed <code>SETNX</code>-based seen-set) requires no change to "
  "any scraper's logic, only to <code>db.py</code>'s internals. That is the concrete mechanism by which "
  "multiple distributed crawler nodes would never double-process the same article or job: they'd all "
  "check/write against the same shared, atomic dedup store instead of each node's own local state.")
h2("Relative and missing dates")
p("<code>src/freshness.py</code> normalizes both standard formats (RFC 822 from RSS, ISO-8601 from "
  "JSON APIs) and relative phrases (\"2 hours ago\", \"yesterday\") to timezone-aware UTC, so freshness "
  "comparisons are always apples-to-apples regardless of source format. For sources with no date at all, "
  "the same dedup mechanism above doubles as the \"intelligent heuristic\": a never-before-seen URL is "
  "treated as new exactly once; a second run correctly skips it via dedup rather than re-treating an "
  "old, dateless item as fresh indefinitely.")

# 4. Storage Strategy
h1("4. Storage Strategy: Primary Database and Relationship Mapping")
h2("This trial: SQLite")
p("Chosen deliberately for a single-machine, one-time bulk-extraction trial: zero setup, crash-safe "
  "(each <code>save_record</code> call commits immediately), and sufficient for the ~5,000 records "
  "this run produces. It is explicitly not the recommended choice at 500k+ scale or multi-node "
  "operation — see below.")
h2("Production recommendation: PostgreSQL as primary store")
p("For the structured entities themselves (Startup, Product, Research Paper, Job — all fixed, "
  "well-defined schemas per the assignment's field tables), PostgreSQL is the right primary store: "
  "ACID guarantees for safe concurrent writes from multiple crawler nodes, mature JSONB support for "
  "the semi-structured <code>content</code> field without needing a rigid column-per-field schema, and "
  "a unique constraint on source URL gives the distributed dedup story in Section 3 for free at the "
  "database layer rather than needing a separate coordination service.")
h2("Relationship mapping: a graph layer alongside Postgres, not instead of it")
p("The entity resolution work in this project (Startup name canonicalization, "
  "<code>src/resolver/</code>) is exactly the kind of many-to-many relationship — a Product belongs to "
  "a canonical Startup, a Research Paper's authors may found Startups, a Job posting belongs to a "
  "Company that may or may not match a canonical Startup — that a purely relational model represents "
  "awkwardly as it grows. For mapping this at scale, a graph database (Neo4j, or Postgres's own AGE "
  "extension to avoid a second system entirely) modeling Startups, Products, Papers, and People as "
  "nodes with typed edges (FOUNDED_BY, PUBLISHES, EMPLOYS, COMPETES_WITH) directly supports the kind "
  "of traversal query this product's premise depends on — \"show me all research papers by founders of "
  "companies that raised funding in the last quarter\" is a natural graph traversal and an awkward "
  "multi-join in pure SQL.")
h2("Vector storage: for semantic search/dedup, not required by this trial's schemas")
p("Not required by the assignment's exact field schemas, but a natural next addition: embedding paper "
  "abstracts and product descriptions into a vector store (pgvector as a Postgres extension, avoiding "
  "yet another system, or a dedicated store like Pinecone/Weaviate at larger scale) enables semantic "
  "\"similar startups/papers\" queries and a second, embedding-similarity layer of entity resolution "
  "beyond the string-fuzzy-matching approach implemented in Phase IV — useful when two entities describe "
  "the same thing in genuinely different words, which string similarity alone cannot catch.")

doc.build(story)
print("architecture.pdf built successfully")