"""
Entry point for running individual pipeline phases.

Usage:
    python main.py papers --query "cat:cs.AI" --count 1000 --github-token $GITHUB_TOKEN

Design note: each phase is runnable independently so you can parallelize them
(e.g. run `papers` and `startups` as separate processes/containers) without
any code change — that's the "scale via infrastructure, not code" story for
Phase VI.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os

from src.db import init_db, count_records
from src.scrapers.papers import run_papers_pipeline
from src.scrapers.startups import run_startups_pipeline
from src.scrapers.products import run_products_pipeline
from src.scrapers.news import run_news_pipeline
from src.scrapers.jobs import run_jobs_pipeline
from src.llm.extractor import LLMKeys
from src.llm.news_enrichment import run_news_enrichment_pipeline
from src.llm.pricing_backfill import run_pricing_backfill_pipeline
from src.resolver.pipeline import run_entity_resolution
from src.export.sheets_export import export_to_sheet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


async def run_papers(args: argparse.Namespace) -> None:
    saved = await run_papers_pipeline(
        query=args.query,
        target_count=args.count,
        github_token=args.github_token or os.environ.get("GITHUB_TOKEN"),
    )
    total = count_records("RESEARCH_PAPER")
    logger.info(f"Papers pipeline done. New records this run: {saved}. Total in DB: {total}")


async def run_startups(args: argparse.Namespace) -> None:
    saved = await run_startups_pipeline(target_count=args.count)
    total = count_records("STARTUP")
    logger.info(f"Startups pipeline done. New records this run: {saved}. Total in DB: {total}")


async def run_products(args: argparse.Namespace) -> None:
    token = args.token or os.environ.get("PRODUCTHUNT_TOKEN")
    if not token:
        raise SystemExit("Product Hunt token required: pass --token or set PRODUCTHUNT_TOKEN env var. See README for how to get one (free).")
    saved = await run_products_pipeline(token=token, target_count=args.count)
    total = count_records("PRODUCT")
    logger.info(f"Products pipeline done. New records this run: {saved}. Total in DB: {total}")


async def run_news(args: argparse.Namespace) -> None:
    saved = await run_news_pipeline()
    total = count_records("NEWS")
    logger.info(f"News pipeline done. New (24hr-fresh) records this run: {saved}. Total in DB: {total}")


async def run_jobs(args: argparse.Namespace) -> None:
    saved = await run_jobs_pipeline()
    total = count_records("JOB")
    logger.info(f"Jobs pipeline done. New (24hr-fresh) records this run: {saved}. Total in DB: {total}")


async def run_extract_news(args: argparse.Namespace) -> None:
    keys = LLMKeys(
        gemini=args.gemini_key or os.environ.get("GEMINI_API_KEY"),
        groq=args.groq_key or os.environ.get("GROQ_API_KEY"),
        deepseek=args.deepseek_key or os.environ.get("DEEPSEEK_API_KEY"),
    )
    if not any([keys.gemini, keys.groq, keys.deepseek]):
        raise SystemExit(
            "No LLM API keys configured. Set at least one of GEMINI_API_KEY, "
            "GROQ_API_KEY, DEEPSEEK_API_KEY (or pass --gemini-key/--groq-key/--deepseek-key). "
            "See README for how to get free keys."
        )
    succeeded = await run_news_enrichment_pipeline(keys)
    total = count_records("NEWS_ENRICHED")
    logger.info(f"News extraction done. Successfully enriched this run: {succeeded}. Total attempts logged: {total}")


async def run_resolve_entities(args: argparse.Namespace) -> None:
    counts = run_entity_resolution()
    logger.info(f"Entity resolution done. Breakdown: {counts}")


async def run_backfill_pricing(args: argparse.Namespace) -> None:
    keys = LLMKeys(
        gemini=args.gemini_key or os.environ.get("GEMINI_API_KEY"),
        groq=args.groq_key or os.environ.get("GROQ_API_KEY"),
        deepseek=args.deepseek_key or os.environ.get("DEEPSEEK_API_KEY"),
    )
    if not any([keys.gemini, keys.groq, keys.deepseek]):
        raise SystemExit(
            "No LLM API keys configured. Set at least one of GEMINI_API_KEY, "
            "GROQ_API_KEY, DEEPSEEK_API_KEY. See README for how to get free keys."
        )
    result = await run_pricing_backfill_pipeline(keys)
    logger.info(f"Pricing backfill done. Attempted: {result['attempted']}, backfilled: {result['backfilled']}")


async def run_export_sheets(args: argparse.Namespace) -> None:
    creds_path = args.creds or os.environ.get("GOOGLE_SHEETS_CREDS")
    if not creds_path:
        raise SystemExit(
            "Service account credentials required: pass --creds path/to/creds.json "
            "or set GOOGLE_SHEETS_CREDS env var. See README for setup."
        )
    url = export_to_sheet(creds_path, sheet_key=args.sheet_key, sheet_title=args.title)
    logger.info(f"Export complete. Sheet URL: {url}")


async def run_all(args: argparse.Namespace) -> None:
    """Runs every phase in sequence with sensible defaults, skipping (with a
    clear warning, not a crash) any step whose credentials aren't
    configured — so `python main.py run-all` does as much as it can with
    whatever's set up, rather than failing all-or-nothing on the first
    missing key. Prints a final summary of what ran vs. what was skipped.
    """
    summary: list[str] = []

    async def step(name: str, coro):
        try:
            await coro
            summary.append(f"✅ {name}")
        except SystemExit as e:
            logger.warning(f"Skipping {name}: {e}")
            summary.append(f"⏭️  {name} (skipped: missing credentials)")
        except Exception as e:
            logger.error(f"{name} failed: {e}")
            summary.append(f"❌ {name} (failed: {e})")

    count = args.count
    await step("startups", run_startups(argparse.Namespace(count=count)))
    await step("products", run_products(argparse.Namespace(count=count, token=None)))
    await step("papers", run_papers(argparse.Namespace(query="cat:cs.AI", count=count, github_token=None)))
    await step("news", run_news(argparse.Namespace()))
    await step("jobs", run_jobs(argparse.Namespace()))
    await step("resolve-entities", run_resolve_entities(argparse.Namespace()))
    await step("backfill-pricing", run_backfill_pricing(argparse.Namespace(gemini_key=None, groq_key=None, deepseek_key=None)))
    await step("extract-news", run_extract_news(argparse.Namespace(gemini_key=None, groq_key=None, deepseek_key=None)))

    if args.export:
        await step("export-sheets", run_export_sheets(argparse.Namespace(creds=None, sheet_key=None, title="AI Signal Trial Output")))
    else:
        summary.append("⏭️  export-sheets (not requested — pass --export to include)")

    logger.info("=" * 60)
    logger.info("run-all summary:")
    for line in summary:
        logger.info(f"  {line}")
    logger.info("=" * 60)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Signal data intelligence pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    papers = sub.add_parser("papers", help="Run the Arxiv + GitHub stars pipeline")
    papers.add_argument("--query", default="cat:cs.AI", help="Arxiv search query")
    papers.add_argument("--count", type=int, default=1000, help="Target number of papers")
    papers.add_argument("--github-token", default=None, help="GitHub PAT (or set GITHUB_TOKEN env var)")
    papers.set_defaults(func=run_papers)

    startups = sub.add_parser("startups", help="Run the Y Combinator startups pipeline")
    startups.add_argument("--count", type=int, default=1000, help="Target number of startups")
    startups.set_defaults(func=run_startups)

    products = sub.add_parser("products", help="Run the Product Hunt products pipeline")
    products.add_argument("--count", type=int, default=1000, help="Target number of products")
    products.add_argument("--token", default=None, help="Product Hunt API token (or set PRODUCTHUNT_TOKEN env var)")
    products.set_defaults(func=run_products)

    news = sub.add_parser("news", help="Run the 24hr-fresh AI news crawler")
    news.set_defaults(func=run_news)

    jobs = sub.add_parser("jobs", help="Run the 24hr-fresh AI jobs crawler")
    jobs.set_defaults(func=run_jobs)

    extract_news = sub.add_parser("extract-news", help="Run the LLM extraction fallback chain over collected news full-text")
    extract_news.add_argument("--gemini-key", default=None, help="Gemini API key (or set GEMINI_API_KEY env var)")
    extract_news.add_argument("--groq-key", default=None, help="Groq API key (or set GROQ_API_KEY env var)")
    extract_news.add_argument("--deepseek-key", default=None, help="DeepSeek API key (or set DEEPSEEK_API_KEY env var)")
    extract_news.set_defaults(func=run_extract_news)

    resolve = sub.add_parser("resolve-entities", help="Canonicalize Startup/Product names against the seed database")
    resolve.set_defaults(func=run_resolve_entities)

    backfill = sub.add_parser("backfill-pricing", help="Use the LLM chain to fill in pricingModel for products the heuristic missed")
    backfill.add_argument("--gemini-key", default=None, help="Gemini API key (or set GEMINI_API_KEY env var)")
    backfill.add_argument("--groq-key", default=None, help="Groq API key (or set GROQ_API_KEY env var)")
    backfill.add_argument("--deepseek-key", default=None, help="DeepSeek API key (or set DEEPSEEK_API_KEY env var)")
    backfill.set_defaults(func=run_backfill_pricing)

    export = sub.add_parser("export-sheets", help="Export all collected data to a Google Sheet (6 tabs)")
    export.add_argument("--creds", default=None, help="Path to Google service account JSON (or set GOOGLE_SHEETS_CREDS env var)")
    export.add_argument("--sheet-key", default=None, help="Existing sheet's key/ID to write into (omit to create a new sheet)")
    export.add_argument("--title", default="AI Signal Trial Output", help="Title for a newly created sheet (ignored if --sheet-key given)")
    export.set_defaults(func=run_export_sheets)

    run_all_parser = sub.add_parser("run-all", help="Run every phase in sequence, skipping steps whose credentials aren't configured")
    run_all_parser.add_argument("--count", type=int, default=1000, help="Target record count for startups/products/papers")
    run_all_parser.add_argument("--export", action="store_true", help="Also run the Google Sheets export at the end (requires GOOGLE_SHEETS_CREDS)")
    run_all_parser.set_defaults(func=run_all)

    return parser


def main() -> None:
    init_db()
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()