"""
Product pipeline: Product Hunt's official GraphQL API (v2).

Source choice: Product Hunt is a structured, purpose-built directory of AI
(and other) products/tools, which is exactly the Product vertical this
schema targets — much better fit than scraping a generic AI-tools listicle
site, and it has a real, stable, documented API instead of a scraping target.

Auth note: Product Hunt's API requires a free developer token (client
credentials grant — no user login needed, just an app registration at
https://api.producthunt.com/v2/oauth/applications). See README for setup.

Pricing model caveat: Product Hunt doesn't expose a structured pricing field.
We heuristically scan the tagline/description for explicit pricing language
("free", "freemium", "paid", "enterprise") and only set pricingModel when we
find an unambiguous signal — otherwise we leave it null rather than guess.
This keeps every field honest per the "no hallucinated data" requirement.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import aiohttp

from src.db import is_seen, mark_seen, save_raw_text, save_record
from src.http_client import fetch_json, post_json
from src.schemas import PricingModel, ProductContent, ProductEntity, Source

logger = logging.getLogger("scrapers.products")

PH_GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"

POSTS_QUERY = """
query Posts($after: String) {
  posts(first: 50, after: $after, order: NEWEST) {
    edges {
      node {
        id
        name
        tagline
        description
        url
        website
        makers {
          name
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

_PRICING_PATTERNS: list[tuple[re.Pattern, PricingModel]] = [
    (re.compile(r"\bfreemium\b", re.I), PricingModel.FREEMIUM),
    (re.compile(r"\benterprise\b", re.I), PricingModel.ENTERPRISE),
    (re.compile(r"\bfree\b", re.I), PricingModel.FREE),
    (re.compile(r"\b(paid|subscription|pricing plan)\b", re.I), PricingModel.PAID),
]


def _infer_pricing_model(text: str) -> Optional[PricingModel]:
    for pattern, model in _PRICING_PATTERNS:
        if pattern.search(text or ""):
            return model
    return None


async def _fetch_posts_page(session: aiohttp.ClientSession, token: str, after: Optional[str]) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {"query": POSTS_QUERY, "variables": {"after": after}}
    return await post_json(session, PH_GRAPHQL_URL, json_body=payload, headers=headers)


def process_post(node: dict) -> Optional[ProductEntity]:
    post_url = node.get("url")
    if not post_url or is_seen(post_url):
        return None

    name = node.get("name")
    if not name:
        return None

    makers = node.get("makers") or []
    startup_name = makers[0]["name"] if makers and makers[0].get("name") else name

    pricing_text = f"{node.get('tagline', '')} {node.get('description', '')}"
    pricing_model = _infer_pricing_model(pricing_text)

    entity = ProductEntity(
        source=Source(name="Product Hunt", url=post_url),
        content=ProductContent(
            startupName=startup_name,
            pricingModel=pricing_model,
        ),
    )
    mark_seen(post_url, "PRODUCT")
    save_record("PRODUCT", entity.model_dump(mode="json"))
    save_raw_text(post_url, pricing_text)
    return entity


async def run_products_pipeline(token: str, target_count: int = 1000) -> int:
    """Entry point. Returns the number of new records saved.
    Uses GraphQL cursor pagination (50 per page) until target_count is hit
    or Product Hunt runs out of pages. To scale toward 500k, raise
    target_count — pagination already handles arbitrary depth, no code
    change needed.
    """
    saved = 0
    after: Optional[str] = None

    async with aiohttp.ClientSession() as session:
        while saved < target_count:
            data = await _fetch_posts_page(session, token, after)
            posts = data.get("data", {}).get("posts", {})
            edges = posts.get("edges", [])
            if not edges:
                logger.info("No more posts returned by Product Hunt API")
                break

            for edge in edges:
                entity = process_post(edge["node"])
                if entity is not None:
                    saved += 1
                if saved >= target_count:
                    break

            page_info = posts.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                logger.info("Reached the last page of Product Hunt results")
                break
            after = page_info.get("endCursor")

    return saved