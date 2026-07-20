"""
Applies entity resolution across the collected Startup and Product records
and logs every raw->canonical mapping — this is what populates the "Entity
Mapping Log" deliverable tab.

Deliberately non-destructive: we do NOT overwrite the original STARTUP/
PRODUCT records' names in place. The mapping log is a separate, additive
layer, so the raw extracted data stays traceable to its original source
text (matching the "every record traces back to a legitimate source"
principle) while still giving downstream consumers a clean canonical name
to join on.
"""
from __future__ import annotations

import logging

from src.db import fetch_records, save_mapping
from src.resolver.entity_resolver import resolve_entity

logger = logging.getLogger("resolver.pipeline")


def run_entity_resolution() -> dict[str, int]:
    """Entry point. Returns counts of how each match method resolved, e.g.
    {'exact_alias': 12, 'exact_canonical': 5, 'fuzzy': 3, 'no_match': 980}.
    A large no_match count is expected and honest — most scraped startup
    names simply aren't in a 50-company seed list; that's not a failure,
    it's what a small mock seed database against 1000 real records looks
    like.
    """
    counts: dict[str, int] = {"exact_alias": 0, "exact_canonical": 0, "fuzzy": 0, "no_match": 0}

    startups = fetch_records("STARTUP")
    for record in startups:
        raw_name = record.get("content", {}).get("entityName")
        if not raw_name:
            continue
        result = resolve_entity(raw_name)
        save_mapping(result.raw_name, result.canonical_name, result.confidence)
        counts[result.method] += 1

    products = fetch_records("PRODUCT")
    for record in products:
        raw_name = record.get("content", {}).get("startupName")
        if not raw_name:
            continue
        result = resolve_entity(raw_name)
        save_mapping(result.raw_name, result.canonical_name, result.confidence)
        counts[result.method] += 1

    logger.info(f"Entity resolution complete: {counts}")
    return counts