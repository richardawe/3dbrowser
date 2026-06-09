from fastapi import APIRouter, Body, HTTPException

from models.responses import ImageResult, ImagesResponse, SearchParameters
from services import cache, searxng

router = APIRouter()


class ImagesRequest(SearchParameters):
    pass


@router.post("/images", response_model=ImagesResponse)
async def images_search(req: ImagesRequest = Body(...)):
    cache_params = {"page": req.page, "gl": req.gl, "hl": req.hl}
    cached = await cache.get_cached("images", req.q, cache_params)
    if cached:
        return cached

    try:
        data = await searxng.query(
            q=req.q,
            category="images",
            pageno=req.page,
            num=req.num,
            language=req.hl,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Search backend error: {exc}")

    results = data.get("results", [])
    images = [
        ImageResult(
            title=r.get("title", ""),
            imageUrl=r.get("img_src") or r.get("url", ""),
            imageWidth=r.get("img_width") or r.get("resolution", {}).get("width") if isinstance(r.get("resolution"), dict) else None,
            imageHeight=r.get("img_height") or r.get("resolution", {}).get("height") if isinstance(r.get("resolution"), dict) else None,
            thumbnailUrl=r.get("thumbnail_src") or r.get("thumbnail"),
            source=r.get("engine"),
            link=r.get("url"),
            position=i + 1,
        )
        for i, r in enumerate(results[: req.num])
    ]

    response = ImagesResponse(
        searchParameters=SearchParameters(
            q=req.q, num=req.num, page=req.page, gl=req.gl, hl=req.hl, type="images"
        ),
        images=images,
    )
    payload = response.model_dump()
    await cache.set_cached("images", req.q, cache_params, payload)
    return payload
