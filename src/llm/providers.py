"""
Provider adapters for the multi-tier LLM fallback chain: Gemini Flash ->
Groq Llama 3 -> DeepSeek. Each adapter has a different request/response
shape (Gemini's own format vs. the OpenAI-compatible format Groq/DeepSeek
use) but presents the same interface upward: given a prompt, return raw
text or raise.

All three request the model to respond in strict JSON only — the caller
(extractor.py) is still responsible for validating that what comes back is
actually valid JSON and actually matches the target schema, since an LLM
saying "here is your JSON" and then not producing valid JSON is a real
failure mode, not a hypothetical one.
"""
from __future__ import annotations

import logging
from typing import Optional

import aiohttp

from src.http_client import post_json as _post_json

logger = logging.getLogger("llm.providers")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

_JSON_INSTRUCTION = (
    "Respond with ONLY a single valid JSON object matching the requested "
    "schema. No markdown code fences, no preamble, no explanation — just "
    "the raw JSON object. If a field cannot be determined from the given "
    "text, use null for that field rather than guessing or inventing a value."
)


async def call_gemini(session: aiohttp.ClientSession, prompt: str, api_key: str) -> str:
    if not api_key:
        raise ValueError("No Gemini API key configured")
    url = f"{GEMINI_URL}?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": f"{_JSON_INSTRUCTION}\n\n{prompt}"}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    data = await _post_json(session, url, json_body=payload, headers={"Content-Type": "application/json"})
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise ValueError(f"Unexpected Gemini response shape: {e}")


async def call_groq(session: aiohttp.ClientSession, prompt: str, api_key: str) -> str:
    if not api_key:
        raise ValueError("No Groq API key configured")
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": _JSON_INSTRUCTION},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = await _post_json(session, GROQ_URL, json_body=payload, headers=headers)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise ValueError(f"Unexpected Groq response shape: {e}")


async def call_deepseek(session: aiohttp.ClientSession, prompt: str, api_key: str) -> str:
    if not api_key:
        raise ValueError("No DeepSeek API key configured")
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": _JSON_INSTRUCTION},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = await _post_json(session, DEEPSEEK_URL, json_body=payload, headers=headers)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise ValueError(f"Unexpected DeepSeek response shape: {e}")