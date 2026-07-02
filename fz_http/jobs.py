"""Background job manager for long-running fz operations (fzr, fzd).

Each job runs in its own subprocess so the fz call executes in that process's
main thread (fzr requires it for signal handling) with an isolated working
directory. The child streams progress and the final result back through a
``multiprocessing.Queue``; a parent-side daemon thread drains it into the
in-memory job state that clients poll.

State is in-memory (single server process): jobs are lost on restart. For
durability/scale, back this with Redis or a database.
"""

import multiprocessing as mp
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .worker import execute


@dataclass
class Job:
    job_id: str
    kind: str
    status: str = "pending"  # pending | running | completed | failed
    completed: int = 0
    total: int = 0
    eta_seconds: Optional[float] = None
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "progress": {
                "completed": self.completed,
                "total": self.total,
                "eta_seconds": self.eta_seconds,
            },
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _child_main(kind: str, payload: Dict[str, Any], queue) -> None:
    """Entry point run in the subprocess: execute fz and report via ``queue``."""

    def progress(**kwargs) -> None:
        queue.put(("progress", kwargs))

    try:
        result = execute(kind, payload, progress)
        queue.put(("result", result))
    except Exception as exc:  # noqa: BLE001 - forward any failure to the parent
        queue.put(("error", f"{type(exc).__name__}: {exc}"))


class JobManager:
    def __init__(self, max_jobs: int = 1000):
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_jobs = max_jobs
        self._ctx = mp.get_context()

    def submit(self, kind: str, payload: Dict[str, Any]) -> Job:
        job = Job(job_id=uuid.uuid4().hex, kind=kind)
        with self._lock:
            self._evict_if_needed()
            self._jobs[job.job_id] = job

        queue = self._ctx.Queue()
        proc = self._ctx.Process(
            target=_child_main,
            args=(kind, payload, queue),
            name=f"fzhttp-job-{job.job_id}",
            daemon=True,
        )

        def _supervise() -> None:
            with self._lock:
                job.status = "running"
                job.started_at = time.time()
            proc.start()
            try:
                self._drain(job, queue, proc)
            finally:
                proc.join()
                with self._lock:
                    if job.status == "running":
                        # Process died without reporting a terminal message.
                        job.status = "failed"
                        job.error = job.error or (
                            f"worker exited with code {proc.exitcode}"
                        )
                    job.finished_at = time.time()

        threading.Thread(
            target=_supervise, name=f"fzhttp-sup-{job.job_id}", daemon=True
        ).start()
        return job

    def _drain(self, job: Job, queue, proc) -> None:
        while True:
            if not proc.is_alive() and queue.empty():
                break
            try:
                kind, payload = queue.get(timeout=0.2)
            except Exception:
                continue
            with self._lock:
                if kind == "progress":
                    if "completed" in payload:
                        job.completed = int(payload["completed"])
                    if "total" in payload:
                        job.total = int(payload["total"])
                    if payload.get("eta_seconds") is not None:
                        job.eta_seconds = float(payload["eta_seconds"])
                elif kind == "result":
                    job.result = payload
                    job.status = "completed"
                    return
                elif kind == "error":
                    job.error = payload
                    job.status = "failed"
                    return

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def snapshot(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.as_dict() if job else None

    def list_ids(self) -> list:
        with self._lock:
            return list(self._jobs.keys())

    def _evict_if_needed(self) -> None:
        # Caller holds self._lock. Drop oldest finished jobs when over capacity.
        if len(self._jobs) < self._max_jobs:
            return
        finished = [
            j for j in self._jobs.values() if j.status in ("completed", "failed")
        ]
        finished.sort(key=lambda j: j.finished_at or 0)
        for j in finished[: max(1, len(self._jobs) - self._max_jobs + 1)]:
            self._jobs.pop(j.job_id, None)
