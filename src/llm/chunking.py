"""
Chunking strategy for the LLM extraction engine.

Goal: never send a payload large enough to trigger a 413, while keeping the
most semantically dense part of the text — the opening paragraphs of an
article or product description almost always carry the key facts (title,
who/what/when), so truncating from the END rather than the middle is a
deliberate choice, not just convenience.

We truncate at the nearest paragraph boundary (blank line) under the budget,
falling back to the nearest sentence boundary, falling back to a hard cut
only as a last resort — mid-sentence cuts risk confusing the LLM into
inventing a completion, which is exactly the hallucination risk we want to
avoid.
"""
from __future__ import annotations

import re

# Conservative chars-per-token estimate (English prose averages ~4). We stay
# well under any provider's real context window so this is about avoiding
# 413s and keeping cost/latency down, not maximizing usable window.
DEFAULT_CHAR_BUDGET = 6000

_SENTENCE_END = re.compile(r"[.!?]\s")


def chunk_text(text: str, char_budget: int = DEFAULT_CHAR_BUDGET) -> str:
    """Truncate text to fit char_budget, preferring paragraph boundaries,
    then sentence boundaries, then a hard cut as a last resort."""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= char_budget:
        return text

    window = text[:char_budget]

    # Prefer the last paragraph break within the window.
    para_break = window.rfind("\n\n")
    if para_break > char_budget * 0.5:  # don't cut away most of the budget just to hit a break
        return window[:para_break].strip()

    # Fall back to the last sentence boundary within the window.
    last_sentence_end = None
    for match in _SENTENCE_END.finditer(window):
        last_sentence_end = match.end()
    if last_sentence_end and last_sentence_end > char_budget * 0.5:
        return window[:last_sentence_end].strip()

    # Last resort: hard cut. Still better than sending nothing.
    return window.strip()