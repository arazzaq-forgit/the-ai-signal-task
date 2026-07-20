"""
The extraction orchestrator: chunk text, try Gemini Flash, fall back to Groq
Llama 3, fall back to DeepSeek, parse+validate whatever comes back. If every
tier fails, return None — we never fabricate a result just to have one.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

from src.llm.chunking import DEFAULT_CHAR_BUDGET, chunk_text
from src.llm.providers import call_deepseek, call_gemini, call_groq

logger = logging.getLogger("llm.extractor")

_JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass
class LLMKeys:
    gemini: Optional[str] = None
    groq: Optional[str] = None
    deepseek: Optional[str] = None


@dataclass
class ExtractionResult:
    data: Optional[dict]
    provider_used: Optional[str]
    attempts: list[str] = field(default_factory=list)


def _strip_json_fences(raw: str) -> str:
    """Some models wrap JSON in ```json ... ``` even when explicitly told
    not to. Strip it defensively rather than failing the whole extraction
    over formatting the prompt already asked it not to use."""
    return _JSON_FENCE_PATTERN.sub("", raw.strip()).strip()


def _try_parse_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    cleaned = _strip_json_fences(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def build_prompt(text: str, schema_description: str, char_budget: int = DEFAULT_CHAR_BUDGET) -> str:
    chunked = chunk_text(text, char_budget)
    return (
        f"Extract structured data from the following text according to this schema:\n"
        f"{schema_description}\n\n"
        f"Text:\n{chunked}"
    )


# Provider chain order. Functions are looked up by name at call time (via
# globals()) rather than captured as direct references here, so the chain
# order can be reasoned about/tested independently of the concrete callables.
_PROVIDER_ORDER = [
    ("gemini", "call_gemini", "gemini"),
    ("groq", "call_groq", "groq"),
    ("deepseek", "call_deepseek", "deepseek"),
]


async def extract_structured(
    session: aiohttp.ClientSession,
    text: str,
    schema_description: str,
    keys: LLMKeys,
    char_budget: int = DEFAULT_CHAR_BUDGET,
) -> ExtractionResult:
    """Runs the full fallback chain. Returns an ExtractionResult whose
    `data` is None if every tier failed or every tier's key was missing —
    callers should treat that as 'could not extract', not as an exception,
    since a source article that defeats every LLM tier is a real, expected
    outcome to log and move past, not a crash."""
    prompt = build_prompt(text, schema_description, char_budget)
    attempts: list[str] = []

    for provider_name, fn_name, key_attr in _PROVIDER_ORDER:
        api_key = getattr(keys, key_attr)
        if not api_key:
            attempts.append(f"{provider_name}: skipped (no API key configured)")
            continue
        call_fn = globals()[fn_name]
        try:
            raw = await call_fn(session, prompt, api_key)
        except Exception as e:
            attempts.append(f"{provider_name}: failed ({e})")
            logger.info(f"{provider_name} extraction failed, falling back: {e}")
            continue

        parsed = _try_parse_json(raw)
        if parsed is None:
            attempts.append(f"{provider_name}: returned unparseable JSON")
            logger.warning(f"{provider_name} returned text that wasn't valid JSON, falling back")
            continue

        attempts.append(f"{provider_name}: success")
        return ExtractionResult(data=parsed, provider_used=provider_name, attempts=attempts)

    attempts.append("all providers exhausted")
    logger.warning(f"All LLM providers failed or were unconfigured: {attempts}")
    return ExtractionResult(data=None, provider_used=None, attempts=attempts)