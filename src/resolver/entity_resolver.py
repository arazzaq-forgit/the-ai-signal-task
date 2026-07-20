"""
Entity resolution: canonicalizes messy startup/product name strings against
the seed list of known AI startups.

Resolution strategy, in order of confidence (most to least certain):
1. Exact match against a known alias (after normalization) -> confidence 1.0
2. Exact match against a canonical name itself (after normalization) -> 1.0
3. Fuzzy match against canonical names, above a similarity threshold -> score/100
4. No match found -> the name is returned UNCHANGED as its own "canonical"
   form, with confidence 0.0. We deliberately do not force a fuzzy match
   below the threshold just to produce a result — a wrong canonicalization
   is worse than an honest "not in our seed list, left as-is".

Fuzzy scorer choice: we use rapidfuzz's plain `ratio` (whole-string
Levenshtein-based similarity), NOT `WRatio`. WRatio blends in partial-string
matching, which badly overmatches short canonical names — e.g. "Deepika
Sharma" contains "pika" as a literal substring, so WRatio scored it ~90%
against the canonical "Pika". Plain `ratio` compares the full strings
end-to-end and doesn't reward partial containment, which is what
short-name-heavy data like company names needs. We additionally guard
against short/length-mismatched inputs, since fuzzy matching on very short
strings ("Tab", "GL", "L.") is inherently unreliable regardless of scorer.

Every resolution (matched or not) gets logged to entity_mapping_log via
src/db.py's save_mapping(), which is what feeds the "Entity Mapping Log"
deliverable tab (raw name vs canonical name).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz, process

from src.resolver.seed_data import CANONICAL_STARTUPS

FUZZY_MATCH_THRESHOLD = 90.0  # 0-100 scale; below this we don't force a match
MIN_LENGTH_FOR_FUZZY_MATCH = 4  # normalized names shorter than this are too ambiguous to fuzzy-match at all
MAX_LENGTH_RATIO = 1.6  # reject matches where one string is disproportionately longer than the other

_LEGAL_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|pbc|plc)\b\.?",
    re.IGNORECASE,
)
_DOMAIN_SUFFIX = re.compile(r"\.(com|ai|io|dev|art|co)\b", re.IGNORECASE)
_PUNCTUATION = re.compile(r"[.,\-_/&]")
_WHITESPACE = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    """Lowercase, strip legal suffixes/domain extensions/punctuation, and
    collapse whitespace — the goal is that 'OpenAI, Inc.' and 'Open AI' and
    'openai.com' all reduce to something comparable."""
    if not raw:
        return ""
    text = raw.lower()
    text = _DOMAIN_SUFFIX.sub("", text)
    text = _LEGAL_SUFFIXES.sub("", text)
    text = _PUNCTUATION.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text


@dataclass
class ResolutionResult:
    raw_name: str
    canonical_name: str
    confidence: float
    method: str  # "exact_alias" | "exact_canonical" | "fuzzy" | "no_match"


def _build_alias_lookup() -> dict[str, str]:
    """normalized alias/canonical text -> canonical name, built once at
    import time from the seed data."""
    lookup: dict[str, str] = {}
    for canonical, aliases in CANONICAL_STARTUPS.items():
        lookup[normalize_name(canonical)] = canonical
        for alias in aliases:
            lookup[normalize_name(alias)] = canonical
    return lookup


_ALIAS_LOOKUP = _build_alias_lookup()
_CANONICAL_NAMES = list(CANONICAL_STARTUPS.keys())
_NORMALIZED_CANONICALS = {normalize_name(name): name for name in _CANONICAL_NAMES}


def _length_ratio_ok(a: str, b: str) -> bool:
    shorter, longer = sorted([len(a), len(b)])
    if shorter == 0:
        return False
    return (longer / shorter) <= MAX_LENGTH_RATIO


def resolve_entity(raw_name: str) -> ResolutionResult:
    if not raw_name or not raw_name.strip():
        return ResolutionResult(raw_name=raw_name, canonical_name=raw_name, confidence=0.0, method="no_match")

    normalized = normalize_name(raw_name)

    # Exact match against a known alias or canonical name.
    if normalized in _ALIAS_LOOKUP:
        canonical = _ALIAS_LOOKUP[normalized]
        method = "exact_canonical" if normalized in _NORMALIZED_CANONICALS else "exact_alias"
        return ResolutionResult(raw_name=raw_name, canonical_name=canonical, confidence=1.0, method=method)

    # Fuzzy match against canonical names (normalized) as a fallback for
    # typos/minor variations not present in the alias list. Skip entirely
    # for names too short to fuzzy-match reliably (e.g. "Tab", "GL", "L.").
    if len(normalized) >= MIN_LENGTH_FOR_FUZZY_MATCH:
        candidates = [
            name for name in _NORMALIZED_CANONICALS.keys()
            if _length_ratio_ok(normalized, name)
        ]
        match = process.extractOne(
            normalized,
            candidates,
            scorer=fuzz.ratio,
            score_cutoff=FUZZY_MATCH_THRESHOLD,
        )
        if match is not None:
            matched_normalized, score, _ = match
            canonical = _NORMALIZED_CANONICALS[matched_normalized]
            return ResolutionResult(raw_name=raw_name, canonical_name=canonical, confidence=round(score / 100, 3), method="fuzzy")

    # Not in the seed list at all — honest non-match, name kept as-is.
    return ResolutionResult(raw_name=raw_name, canonical_name=raw_name, confidence=0.0, method="no_match")