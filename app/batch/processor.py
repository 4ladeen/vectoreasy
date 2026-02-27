"""Batch processor for VectorEasy."""

from __future__ import annotations

import asyncio
import io
import logging
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from typing import Any

from app.vectorizer.engine import VectorizationEngine
from app.vectorizer.exporter import SVGExporter

logger = logging.getLogger(__name__)


@dataclass
class _BatchJob:
    job_id: str
    filename: str
    image_data: bytes
    settings: dict
    status: str = "queued"   # queued | processing | done | error
    error: str | None = None
    svg: str | None = None
    started_at: float | None = None
    finished_at: float | None = None


class BatchProcessor:
    """Processes a queue of vectorization jobs concurrently."""

    def __init__(self, max_workers: int = 4) -> None:
        self._jobs: dict[str, _BatchJob] = {}
        self._order: list[str] = []
        self._max_workers = max_workers
        self._engine = VectorizationEngine()
        self._exporter = SVGExporter()

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def add_job(
        self,
        image_data: bytes,
        filename: str,
        settings: dict,
    ) -> str:
        """Enqueue an image for vectorization and return a job ID."""
        job_id = str(uuid.uuid4())
        job = _BatchJob(
            job_id=job_id,
            filename=filename,
            image_data=image_data,
            settings=settings,
        )
        self._jobs[job_id] = job
        self._order.append(job_id)
        return job_id

    async def process_all(self) -> None:
        """Process all queued jobs with bounded concurrency."""
        queued = [jid for jid in self._order if self._jobs[jid].status == "queued"]
        semaphore = asyncio.Semaphore(self._max_workers)

        async def _run(job_id: str) -> None:
            async with semaphore:
                await self._process_job(job_id)

        await asyncio.gather(*[_run(jid) for jid in queued])

    def get_status(self) -> dict:
        """Return overall and per-job progress."""
        total = len(self._jobs)
        done = sum(1 for j in self._jobs.values() if j.status == "done")
        error_count = sum(1 for j in self._jobs.values() if j.status == "error")
        in_progress = sum(1 for j in self._jobs.values() if j.status == "processing")

        return {
            "total": total,
            "done": done,
            "error": error_count,
            "in_progress": in_progress,
            "queued": total - done - error_count - in_progress,
            "percent": int(done / total * 100) if total else 0,
            "jobs": {
                jid: {
                    "filename": j.filename,
                    "status": j.status,
                    "error": j.error,
                }
                for jid, j in self._jobs.items()
            },
        }

    def create_zip(self) -> bytes:
        """Package all successfully vectorized SVGs into a ZIP archive."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for job in self._jobs.values():
                if job.status == "done" and job.svg:
                    basename = job.filename.rsplit(".", 1)[0]
                    zf.writestr(f"{basename}.svg", job.svg)
        return buf.getvalue()

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    async def _process_job(self, job_id: str) -> None:
        job = self._jobs[job_id]
        job.status = "processing"
        job.started_at = time.time()
        try:
            # Run CPU-bound work in a thread pool to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._run_vectorize,
                job.image_data,
                job.settings,
            )
            job.svg = result["svg"]
            job.status = "done"
        except Exception as exc:
            logger.error("Batch job %s failed: %s", job_id, exc)
            job.status = "error"
            job.error = str(exc)
        finally:
            job.finished_at = time.time()

    def _run_vectorize(self, image_data: bytes, settings: dict) -> dict:
        engine = VectorizationEngine()
        return engine.vectorize(image_data, settings)
