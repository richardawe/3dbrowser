"""
Job scheduler — APScheduler-backed, fully user-managed from the UI.
No cron setup required. Persists jobs to jobs.json across restarts.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

JOBS_FILE = Path(__file__).parent / "jobs.json"

_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


class JobScheduler:
    def __init__(self) -> None:
        self._sched = AsyncIOScheduler(timezone="UTC")
        self._jobs: dict[str, dict] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def load(self, run_fn: Callable[[dict], Awaitable[None]]) -> None:
        """Load persisted jobs and re-register them."""
        if JOBS_FILE.exists():
            try:
                self._jobs = json.loads(JOBS_FILE.read_text())
            except Exception:
                self._jobs = {}
        for job_id, job in self._jobs.items():
            self._register(job_id, job, run_fn)

    def start(self) -> None:
        self._sched.start()

    def stop(self) -> None:
        if self._sched.running:
            self._sched.shutdown(wait=False)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def list_jobs(self) -> list[dict]:
        result = []
        for job in self._jobs.values():
            row = dict(job)
            try:
                sj = self._sched.get_job(job["id"])
                if sj and sj.next_run_time:
                    row["next_run"] = sj.next_run_time.isoformat()
            except Exception:
                pass
            result.append(row)
        return result

    def create(
        self,
        name: str,
        job_type: str,
        args: list[str] | str,
        schedule: dict,
        run_fn: Callable[[dict], Awaitable[None]],
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:8]
        job: dict[str, Any] = {
            "id": job_id,
            "name": name,
            "type": job_type,      # "research" | "briefing"
            "args": args,          # str query or list[str] topics
            "schedule": schedule,  # {"type":"daily","time":"08:00"} etc.
            "created_at": datetime.utcnow().isoformat(),
            "last_run": None,
            "last_status": None,
        }
        self._jobs[job_id] = job
        self._persist()
        self._register(job_id, job, run_fn)
        return job

    def delete(self, job_id: str) -> None:
        try:
            self._sched.remove_job(job_id)
        except Exception:
            pass
        self._jobs.pop(job_id, None)
        self._persist()

    def update_last_run(self, job_id: str, status: str) -> None:
        if job_id in self._jobs:
            self._jobs[job_id]["last_run"] = datetime.utcnow().isoformat()
            self._jobs[job_id]["last_status"] = status
            self._persist()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _register(self, job_id: str, job: dict, run_fn: Callable) -> None:
        s = job.get("schedule", {})
        stype = s.get("type", "")

        if stype == "daily":
            hour, minute = s.get("time", "08:00").split(":")
            trigger = CronTrigger(hour=int(hour), minute=int(minute))
        elif stype == "weekly":
            hour, minute = s.get("time", "08:00").split(":")
            day = s.get("day", "mon")
            trigger = CronTrigger(day_of_week=day, hour=int(hour), minute=int(minute))
        elif stype == "interval":
            hours = max(1, int(s.get("hours", 6)))
            trigger = IntervalTrigger(hours=hours)
        else:
            return

        self._sched.add_job(
            run_fn,
            trigger=trigger,
            id=job_id,
            args=[job],
            replace_existing=True,
            misfire_grace_time=3600,
        )

    def _persist(self) -> None:
        JOBS_FILE.write_text(json.dumps(self._jobs, indent=2))
