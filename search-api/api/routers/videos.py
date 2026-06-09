from fastapi import APIRouter, Body, HTTPException

from models.responses import SearchParameters, VideoResult, VideosResponse
from services import cache, searxng

router = APIRouter()


class VideosRequest(SearchParameters):
    pass


@router.post("/videos", response_model=VideosResponse)
async def videos_search(req: VideosRequest = Body(...)):
    cache_params = {"page": req.page, "gl": req.gl, "hl": req.hl}
    cached = await cache.get_cached("videos", req.q, cache_params)
    if cached:
        return cached

    try:
        data = await searxng.query(
            q=req.q,
            category="videos",
            pageno=req.page,
            num=req.num,
            language=req.hl,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Search backend error: {exc}")

    results = data.get("results", [])
    videos = [
        VideoResult(
            title=r.get("title", ""),
            link=r.get("url", ""),
            snippet=r.get("content") or r.get("description"),
            imageUrl=r.get("thumbnail") or r.get("img_src"),
            duration=r.get("length"),
            source=r.get("engine"),
            date=r.get("publishedDate"),
            position=i + 1,
        )
        for i, r in enumerate(results[: req.num])
    ]

    response = VideosResponse(
        searchParameters=SearchParameters(
            q=req.q, num=req.num, page=req.page, gl=req.gl, hl=req.hl, type="videos"
        ),
        videos=videos,
    )
    payload = response.model_dump()
    await cache.set_cached("videos", req.q, cache_params, payload)
    return payload
