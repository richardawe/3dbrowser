"""
LLM-powered property discovery using a self-hosted search API + LLM extraction.

Search provider:
  Self-hosted — set SEARCH_API_URL and SEARCH_API_KEY
  SEARCH_API_URL: public HTTPS URL of your search API (e.g. Cloudflare tunnel)
  SEARCH_API_KEY: the key set in your search-api .env file
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

import requests
from pydantic import BaseModel

from engine.extractor import ExtractionError, extract

_SELF_HOSTED_URL = os.getenv("SEARCH_API_URL", "http://localhost:8000") + "/search"

_SITE_DOMAINS: dict[str, str] = {
    "rightmove": "rightmove.co.uk",
    "zoopla": "zoopla.co.uk",
    "spareroom": "spareroom.co.uk",
    "openrent": "openrent.co.uk",
    "onthemarket": "onthemarket.com",
    "gumtree_uk": "gumtree.com",
    "craigslist": "craigslist.org",
}

_SNIPPET_CHARS = 300


class _PropertyListing(BaseModel):
    address: str | None = None
    price: int | None = None
    rent_monthly: int | None = None
    beds: int | None = None
    property_type: str | None = None
    features: list[str] = []
    url: str = ""


class _PropertyListResult(BaseModel):
    properties: list[_PropertyListing] = []


def _build_query(
    source_id: str,
    workflow_type: str,
    requirements: dict[str, Any],
    location: str,
) -> str:
    site = _SITE_DOMAINS.get(source_id, source_id)
    parts = [f"site:{site}", location]

    beds_min = requirements.get("bedrooms_min")
    if beds_min:
        parts.append(f"{beds_min} bed")

    prop_types = requirements.get("property_types") or []
    if prop_types:
        parts.append(prop_types[0])

    if workflow_type == "buy":
        parts.append("for sale")
        b_max = requirements.get("budget_max")
        if b_max:
            parts.append(f"under £{b_max:,}")
    else:
        parts.append("to rent")
        r_max = requirements.get("rent_max")
        if r_max:
            parts.append(f"under £{r_max:,} pcm")

    return " ".join(parts)


def _search(query: str, max_results: int) -> list[dict[str, str]]:
    key = os.environ.get("SEARCH_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "SEARCH_API_KEY is not set. "
            "Add it to your .env file or GitHub Actions secrets."
        )

    resp = requests.post(
        _SELF_HOSTED_URL,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        json={"q": query, "num": min(max_results, 20)},
        timeout=15,
    )
    if resp.status_code in (401, 403):
        raise RuntimeError(f"Search API rejected the key (HTTP {resp.status_code}). Check SEARCH_API_KEY.")
    if resp.status_code == 429:
        raise RuntimeError("Search API rate limit hit.")
    resp.raise_for_status()
    return [
        {"title": r.get("title", ""), "url": r.get("link", ""), "body": r.get("snippet", "")}
        for r in resp.json().get("organic", [])
    ]


def _url_id(source_id: str, url: str) -> str:
    return f"{source_id}-{hashlib.sha1(url.encode()).hexdigest()[:12]}"


def run_llm_search(
    source_id: str,
    workflow_type: str,
    requirements: dict[str, Any],
    location: str,
    *,
    max_results: int = 20,
) -> list[dict[str, Any]]:
    """
    Search for property listings via the self-hosted Search API + LLM extraction.
    Returns property dicts compatible with the eligibility and scoring engine.
    Returns an empty list on extraction failure.
    """
    query = _build_query(source_id, workflow_type, requirements, location)
    raw = _search(query, max_results)
    if not raw:
        return []

    snippets = "\n\n".join(
        f"[{i + 1}] Title: {r.get('title', '')}\n"
        f"    URL: {r.get('url', '')}\n"
        f"    Snippet: {r.get('body', '')[:_SNIPPET_CHARS]}"
        for i, r in enumerate(raw)
    )

    price_field = (
        "rent_monthly (integer, monthly rent in GBP)"
        if workflow_type == "rent"
        else "price (integer, sale price in GBP)"
    )

    prompt = (
        f"Extract individual property listings from these search results.\n\n"
        f"{snippets}\n\n"
        f'Return JSON: {{"properties": [...]}} where each item has:\n'
        f"- address (string or null)\n"
        f"- {price_field}\n"
        f"- beds (integer or null)\n"
        f"- property_type (e.g. flat, house, semi-detached, or null)\n"
        f'- features (list of strings, e.g. ["garden", "parking", "garage"])\n'
        f"- url (the result URL string)\n\n"
        f"Only include results that describe a single specific property listing. "
        f"Skip search pages, category pages, and non-property results."
    )

    try:
        result, _ = extract(prompt, _PropertyListResult, max_tokens=2048)
    except ExtractionError:
        return []

    props: list[dict[str, Any]] = []
    for p in result.properties:
        if p.price is None and p.rent_monthly is None:
            continue
        d = p.model_dump()
        d["source_id"] = source_id
        d["external_id"] = _url_id(source_id, d.get("url") or "")
        props.append(d)
    return props
