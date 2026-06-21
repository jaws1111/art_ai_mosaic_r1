"""In-memory live job telemetry (activity log + worker flags)."""

from __future__ import annotations

from app.models.mosaic import ActivityEvent, WorkerStatus


class JobTelemetry:
    def __init__(self, max_events: int = 200) -> None:
        self.max_events = max_events
        self._events: dict[str, list[ActivityEvent]] = {}
        self._workers: dict[str, WorkerStatus] = {}
        self._api_calls: dict[str, int] = {}

    def init_job(self, job_id: str) -> None:
        self._events[job_id] = []
        self._workers[job_id] = WorkerStatus()
        self._api_calls[job_id] = 0

    def log(
        self,
        job_id: str,
        category: str,
        message: str,
        detail: str | None = None,
        ts: float = 0.0,
    ) -> ActivityEvent:
        event = ActivityEvent(ts=ts, category=category, message=message, detail=detail)
        events = self._events.setdefault(job_id, [])
        events.append(event)
        if len(events) > self.max_events:
            del events[: len(events) - self.max_events]
        return event

    def set_workers(self, job_id: str, **kwargs: object) -> WorkerStatus:
        current = self._workers.get(job_id, WorkerStatus())
        data = current.model_dump()
        data.update(kwargs)
        updated = WorkerStatus(**data)
        self._workers[job_id] = updated
        return updated

    def increment_api_calls(self, job_id: str) -> int:
        self._api_calls[job_id] = self._api_calls.get(job_id, 0) + 1
        return self._api_calls[job_id]

    def get_events(self, job_id: str) -> list[ActivityEvent]:
        return list(self._events.get(job_id, []))

    def get_workers(self, job_id: str) -> WorkerStatus:
        return self._workers.get(job_id, WorkerStatus())

    def get_api_calls(self, job_id: str) -> int:
        return self._api_calls.get(job_id, 0)

    def clear_job(self, job_id: str) -> None:
        self._events.pop(job_id, None)
        self._workers.pop(job_id, None)
        self._api_calls.pop(job_id, None)


job_telemetry = JobTelemetry()
