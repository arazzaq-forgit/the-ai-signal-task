"""
Exports data/state.db into static JSON files under docs/data/, which
the deployed dashboard (docs/index.html) fetches directly. Run this
once after your pipelines have populated the database, then commit the
docs/ folder — GitHub Pages serves directly from it.

Usage: python export_dashboard_data.py
"""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path("data/state.db")
OUT_DIR = Path("docs/data")


def fetch_records(conn, record_type):
    rows = conn.execute("SELECT payload FROM records WHERE record_type = ?", (record_type,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def fetch_mappings(conn):
    rows = conn.execute(
        "SELECT raw_name, canonical_name, confidence FROM entity_mapping_log ORDER BY confidence DESC"
    ).fetchall()
    return [{"raw": r[0], "canonical": r[1], "confidence": r[2]} for r in rows]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    data = {
        "startups": fetch_records(conn, "STARTUP"),
        "products": fetch_records(conn, "PRODUCT"),
        "papers": fetch_records(conn, "RESEARCH_PAPER"),
        "jobs": fetch_records(conn, "JOB"),
        "news": fetch_records(conn, "NEWS"),
    }
    mappings = fetch_mappings(conn)

    for name, records in data.items():
        with open(OUT_DIR / f"{name}.json", "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False)
        print(f"{name}: {len(records)} records")

    with open(OUT_DIR / "entity_mappings.json", "w", encoding="utf-8") as f:
        json.dump(mappings, f, ensure_ascii=False)
    print(f"entity_mappings: {len(mappings)} rows")

    papers_with_stars = sum(1 for p in data["papers"] if p.get("content", {}).get("github_stars"))
    products_with_pricing = sum(1 for p in data["products"] if p.get("content", {}).get("pricingModel"))
    real_mappings = sum(1 for m in mappings if m["confidence"] and m["confidence"] > 0)

    summary = {
        "startups": len(data["startups"]),
        "products": len(data["products"]),
        "papers": len(data["papers"]),
        "papersWithGithubStars": papers_with_stars,
        "jobs": len(data["jobs"]),
        "news": len(data["news"]),
        "productsWithPricing": products_with_pricing,
        "entityMappingsResolved": real_mappings,
        "entityMappingsTotal": len(mappings),
    }
    with open(OUT_DIR / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False)
    print("summary:", summary)

    conn.close()
    print(f"\nDone. Exported to {OUT_DIR}/")


if __name__ == "__main__":
    main()