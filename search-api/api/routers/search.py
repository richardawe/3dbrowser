from typing import Literal, Union

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import PlainTextResponse

from models.responses import OrganicResult, SearchParameters, SearchResponse
from services import cache, searxng

router = APIRouter()


class SearchRequest(SearchParameters):
    response_format: Literal["json", "text"] = "json"


def _to_text(response: SearchResponse) -> str:
    q = response.searchParameters.q
    lines = [f'Web search results for: "{q}"\n']
    for r in response.organic:
        lines.append(f"{r.position}. {r.title}")
        lines.append(f"   URL: {r.link}")
        if r.snippet:
            lines.append(f"   {r.snippet}")
        if r.date:
            lines.append(f"   Date: {r.date}")
        lines.append("")
    return "\n".join(lines)


@router.post("/search")
async def web_search(req: SearchRequest = Body(...)):
    cache_params = {"page": req.page, "gl": req.gl, "hl": req.hl}
    cached = await cache.get_cached("web", req.q, cache_params)
    if cached:
        if req.response_format == "text":
            return PlainTextResponse(_to_text(SearchResponse(**cached)))
        return cached

    try:
        data = await searxng.query(
            q=req.q,
            category="general",
            pageno=req.page,
            num=req.num,
            language=req.hl,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Search backend error: {exc}")

    results = data.get("results", [])
    organic = [
        OrganicResult(
            title=r.get("title", ""),
            link=r.get("url", ""),
            snippet=r.get("content") or r.get("description"),
            position=i + 1,
            date=r.get("publishedDate"),
            engine=r.get("engine"),
        )
        for i, r in enumerate(results[: req.num])
    ]

    response = SearchResponse(
        searchParameters=SearchParameters(
            q=req.q, num=req.num, page=req.page, gl=req.gl, hl=req.hl, type="search"
        ),
        organic=organic,
    )
    payload = response.model_dump()
    await cache.set_cached("web", req.q, cache_params, payload)

    if req.response_format == "text":
        return PlainTextResponse(_to_text(response))
    return payload
