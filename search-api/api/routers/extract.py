import io
import csv
from typing import Any, Literal, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, HttpUrl

router = APIRouter()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class ExtractRequest(BaseModel):
    url: str
    mode: Literal["auto", "tables", "links", "list"] = "auto"
    table_index: int = 0  # which table to extract when multiple exist


class ExtractResponse(BaseModel):
    url: str
    mode: str
    title: Optional[str] = None
    columns: list[str]
    rows: list[list[str]]
    count: int
    tables_found: int = 0


# ── helpers ─────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    return " ".join(text.split()).strip()


def _extract_tables(soup: BeautifulSoup, table_index: int) -> tuple[list[str], list[list[str]], int]:
    tables = soup.find_all("table")
    if not tables:
        return [], [], 0

    idx = min(table_index, len(tables) - 1)
    table = tables[idx]

    # Build columns: prefer th[scope=col], then thead ths, then first all-th row
    columns: list[str] = []
    col_headers = table.find_all("th", scope="col")
    if col_headers:
        columns = [_clean(th.get_text()) for th in col_headers]
    else:
        thead = table.find("thead")
        if thead:
            first_row = thead.find("tr")
            if first_row:
                columns = [_clean(c.get_text()) for c in first_row.find_all(["th", "td"])]

    rows: list[list[str]] = []
    all_trs = table.find_all("tr")
    for tr in all_trs:
        cells_tags = tr.find_all(["td", "th"])
        # Skip rows that are purely column-header rows
        if all(c.name == "th" and c.get("scope") in ("col", "colgroup") for c in cells_tags):
            continue
        cells = [_clean(c.get_text()) for c in cells_tags]
        if not cells or all(c == "" for c in cells):
            continue
        # If we still have no columns, use the first all-th row
        if not columns and all(c.name == "th" for c in cells_tags):
            columns = cells
            continue
        rows.append(cells)

    if not columns and rows:
        columns = [f"Column {i+1}" for i in range(len(rows[0]))]

    # Normalise row length to column count
    n = len(columns) if columns else (len(rows[0]) if rows else 0)
    if n:
        rows = [(r + [""] * n)[:n] for r in rows if r]

    return columns, rows, len(tables)


def _extract_links(soup: BeautifulSoup, base_url: str) -> tuple[list[str], list[list[str]]]:
    """Extract all meaningful links — good for directory/index pages."""
    columns = ["Text", "URL", "Title"]
    rows = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        abs_url = urljoin(base_url, href)
        text = _clean(a.get_text())
        title = a.get("title", "")
        if abs_url in seen or not text:
            continue
        seen.add(abs_url)
        rows.append([text, abs_url, title])
    return columns, rows


def _extract_list(soup: BeautifulSoup) -> tuple[list[str], list[list[str]]]:
    """Extract structured list items (ul/ol > li)."""
    # Find the biggest list on the page
    best: list[Any] = []
    for ul in soup.find_all(["ul", "ol"]):
        items = ul.find_all("li", recursive=False)
        if len(items) > len(best):
            best = items

    if not best:
        return [], []

    rows = []
    for li in best:
        text = _clean(li.get_text())
        link = li.find("a")
        url = link["href"] if link and link.get("href") else ""
        rows.append([text, url] if url else [text])

    has_url = any(len(r) > 1 for r in rows)
    columns = ["Item", "URL"] if has_url else ["Item"]
    rows = [(r + [""] * len(columns))[:len(columns)] for r in rows]
    return columns, rows


def _is_directory_listing(soup: BeautifulSoup) -> bool:
    title = (soup.title.string or "") if soup.title else ""
    low = title.lower()
    return any(k in low for k in ("index of", "directory listing", "directory of"))


# ── endpoint ─────────────────────────────────────────────────────────────────

@router.post("/extract", response_model=ExtractResponse)
async def extract_url(req: ExtractRequest = Body(...)):
    try:
        async with httpx.AsyncClient(
            headers=HEADERS,
            timeout=httpx.Timeout(20.0, connect=8.0),
            follow_redirects=True,
        ) as client:
            resp = await client.get(req.url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "xml" not in content_type:
                raise HTTPException(
                    status_code=422,
                    detail=f"URL returned non-HTML content ({content_type}). Only HTML pages are supported."
                )
            html = resp.text
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Remote server returned {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach URL: {e}")

    soup = BeautifulSoup(html, "lxml")
    title = _clean(soup.title.string) if soup.title else None
    base_url = str(resp.url)

    mode = req.mode
    columns: list[str] = []
    rows: list[list[str]] = []
    tables_found = 0

    if mode == "auto":
        # 1. Try tables
        columns, rows, tables_found = _extract_tables(soup, req.table_index)
        if rows:
            mode = "tables"
        # 2. Directory listing → links
        elif _is_directory_listing(soup):
            columns, rows = _extract_links(soup, base_url)
            mode = "links"
        # 3. Try lists
        else:
            columns, rows = _extract_list(soup)
            if rows:
                mode = "list"
            else:
                columns, rows = _extract_links(soup, base_url)
                mode = "links"

    elif mode == "tables":
        columns, rows, tables_found = _extract_tables(soup, req.table_index)
    elif mode == "links":
        columns, rows = _extract_links(soup, base_url)
    elif mode == "list":
        columns, rows = _extract_list(soup)

    if not rows:
        raise HTTPException(
            status_code=422,
            detail=f"No extractable data found on this page using mode '{mode}'. Try a different mode."
        )

    return ExtractResponse(
        url=base_url,
        mode=mode,
        title=title,
        columns=columns,
        rows=rows,
        count=len(rows),
        tables_found=tables_found,
    )
