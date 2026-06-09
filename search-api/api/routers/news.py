from typing import Literal

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import PlainTextResponse

from models.responses import NewsResponse, NewsResult, SearchParameters
from services import cache, searxng

router = APIRouter()


class NewsRequest(SearchParameters):
    response_format: Literal["json", "text"] = "json"


def _to_text(response: NewsResponse) -> str:
    q = response.searchParameters.q
    lines = [f'News results for: "{q}"\n']
    for r in response.news:
        lines.append(f"{r.position}. {r.title}")
        lines.append(f"   URL: {r.link}")
        if r.source:
            lines.append(f"   Source: {r.source}")
        if r.snippet:
            lines.append(f"   {r.snippet}")
        if r.date:
            lines.append(f"   Date: {r.date}")
        lines.append("")
    return "\n".join(lines)


@router.post("/news")
async def news_search(req: NewsRequest = Body(...)):
    cache_params = {"page": req.page, "gl": req.gl, "hl": req.hl}
    cached = await cache.get_cached("news", req.q, cache_params)
    if cached:
        if req.response_format == "text":
            return PlainTextResponse(_to_text(NewsResponse(**cached)))
        return cached

    try:
        data = await searxng.query(
            q=req.q,
            category="news",
            pageno=req.page,
            num=req.num,
            language=req.hl,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Search backend error: {exc}")

    results = data.get("results", [])
    news = [
        NewsResult(
            title=r.get("title", ""),
            link=r.get("url", ""),
            snippet=r.get("content") or r.get("description"),
            date=r.get("publishedDate"),
            source=r.get("metadata") or r.get("engine"),
            imageUrl=r.get("img_src"),
            position=i + 1,
        )
        for i, r in enumerate(results[: req.num])
    ]

    response = NewsResponse(
        searchParameters=SearchParameters(
            q=req.q, num=req.num, page=req.page, gl=req.gl, hl=req.hl, type="news"
        ),
        news=news,
    )
    payload = response.model_dump()
    await cache.set_cached("news", req.q, cache_params, payload)

    if req.response_format == "text":
        return PlainTextResponse(_to_text(response))
    return payload
