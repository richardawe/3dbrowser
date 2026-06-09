from pydantic import BaseModel
from typing import Optional


class SearchParameters(BaseModel):
    q: str
    num: int = 10
    page: int = 1
    gl: Optional[str] = None
    hl: Optional[str] = None
    type: Optional[str] = None


class OrganicResult(BaseModel):
    title: str
    link: str
    snippet: Optional[str] = None
    position: int
    date: Optional[str] = None
    engine: Optional[str] = None


class NewsResult(BaseModel):
    title: str
    link: str
    snippet: Optional[str] = None
    date: Optional[str] = None
    source: Optional[str] = None
    imageUrl: Optional[str] = None
    position: int


class ImageResult(BaseModel):
    title: str
    imageUrl: str
    imageWidth: Optional[int] = None
    imageHeight: Optional[int] = None
    thumbnailUrl: Optional[str] = None
    source: Optional[str] = None
    link: Optional[str] = None
    position: int


class VideoResult(BaseModel):
    title: str
    link: str
    snippet: Optional[str] = None
    imageUrl: Optional[str] = None
    duration: Optional[str] = None
    source: Optional[str] = None
    date: Optional[str] = None
    position: int


class SearchResponse(BaseModel):
    searchParameters: SearchParameters
    organic: list[OrganicResult] = []


class NewsResponse(BaseModel):
    searchParameters: SearchParameters
    news: list[NewsResult] = []


class ImagesResponse(BaseModel):
    searchParameters: SearchParameters
    images: list[ImageResult] = []


class VideosResponse(BaseModel):
    searchParameters: SearchParameters
    videos: list[VideoResult] = []
