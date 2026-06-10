"""
FastAPI server: research (SSE), briefing (SSE), schedules CRUD, history.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Union

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

load_dotenv()

from agent import research
from briefing import run_briefing
from qa import review_research, review_briefing
from scheduler import JobScheduler

SEARCH_URL = os.getenv("SEARCH_API_URL", "http://localhost:8000")
API_KEY = os.getenv("SEARCH_API_KEY", "my-secret-key-change-me")
HISTORY_DIR = Path(__file__).parent / "history"

app = FastAPI(title="Research Engine")
_sched = JobScheduler()


# ── Request models ────────────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    question: str


class BriefingRequest(BaseModel):
    topics: list[str]


class ScheduleCreate(BaseModel):
    name: str
    type: str                         # "research" | "briefing"
    args: Union[list[str], str]       # topics list OR query string
    schedule: dict                    # {"type":"daily","time":"08:00"} etc.


# ── SSE endpoints ─────────────────────────────────────────────────────────────

@app.post("/ask")
async def ask(req: ResearchRequest):
    _answer: dict = {"v": ""}

    async def stream():
        async for event in research(req.question, SEARCH_URL, API_KEY):
            if event.get("type") == "answer":
                _answer["v"] = event["content"]
            yield {"data": json.dumps(event)}

        yield {"data": json.dumps({"type": "qa_start"})}
        qa = await review_research(req.question, _answer["v"])
        yield {"data": json.dumps({"type": "qa_result", **qa})}

        _save("research", req.question, _answer["v"], qa)
        yield {"data": "[DONE]"}

    return EventSourceResponse(stream())


@app.post("/briefing/run")
async def briefing_run(req: BriefingRequest):
    collected: list[dict] = []

    async def stream():
        async for event in run_briefing(req.topics, SEARCH_URL, API_KEY):
            if event.get("type") == "briefing_topic_done":
                collected.append(event)
            yield {"data": json.dumps(event)}

        yield {"data": json.dumps({"type": "qa_start"})}
        qa = await review_briefing(req.topics, collected)
        yield {"data": json.dumps({"type": "qa_result", **qa})}

        _save("briefing", ", ".join(req.topics), collected, qa)
        yield {"data": "[DONE]"}

    return EventSourceResponse(stream())


# ── Schedules ─────────────────────────────────────────────────────────────────

@app.get("/schedules")
async def list_schedules():
    return _sched.list_jobs()


@app.post("/schedules")
async def create_schedule(req: ScheduleCreate):
    return _sched.create(req.name, req.type, req.args, req.schedule, _run_job)


@app.delete("/schedules/{job_id}")
async def delete_schedule(job_id: str):
    _sched.delete(job_id)
    return {"ok": True}


# ── History ───────────────────────────────────────────────────────────────────

@app.get("/history")
async def list_history():
    HISTORY_DIR.mkdir(exist_ok=True)
    items = []
    for f in sorted(HISTORY_DIR.glob("*.json"), reverse=True)[:60]:
        try:
            d = json.loads(f.read_text())
            items.append(
                {
                    "id": f.stem,
                    "type": d.get("type"),
                    "label": d.get("label"),
                    "ts": d.get("ts"),
                    "qa_score": d.get("qa", {}).get("score"),
                }
            )
        except Exception:
            pass
    return items


@app.get("/history/{item_id}")
async def get_history_item(item_id: str):
    path = HISTORY_DIR / f"{item_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return json.loads(path.read_text())


@app.get("/health")
async def health():
    return {"status": "ok", "search_url": SEARCH_URL}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save(type_: str, label: str, content: object, qa: dict) -> None:
    HISTORY_DIR.mkdir(exist_ok=True)
    stem = datetime.utcnow().strftime("%Y%m%d_%H%M%S") + "_" + type_
    (HISTORY_DIR / f"{stem}.json").write_text(
        json.dumps(
            {"type": type_, "label": label, "content": content,
             "qa": qa, "ts": datetime.utcnow().isoformat()},
            default=str,
        )
    )


async def _run_job(job: dict) -> None:
    """Executor for scheduled jobs — saves result to history."""
    jtype = job.get("type")
    args = job.get("args", [])
    try:
        if jtype == "briefing":
            topics = args if isinstance(args, list) else [args]
            collected: list[dict] = []
            async for event in run_briefing(topics, SEARCH_URL, API_KEY):
                if event.get("type") == "briefing_topic_done":
                    collected.append(event)
            qa = await review_briefing(topics, collected)
            _save("briefing", job.get("name", "Briefing"), collected, qa)

        elif jtype == "research":
            query = args if isinstance(args, str) else (args[0] if args else "")
            answer = {"v": ""}
            async for event in research(query, SEARCH_URL, API_KEY):
                if event.get("type") == "answer":
                    answer["v"] = event["content"]
            qa = await review_research(query, answer["v"])
            _save("research", query, answer["v"], qa)

        _sched.update_last_run(job["id"], "success")
    except Exception as exc:
        _sched.update_last_run(job["id"], f"error: {str(exc)[:80]}")


# ── Lifecycle ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup() -> None:
    HISTORY_DIR.mkdir(exist_ok=True)
    _sched.load(_run_job)
    _sched.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    _sched.stop()


# Static frontend — must be last so API routes take priority
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
