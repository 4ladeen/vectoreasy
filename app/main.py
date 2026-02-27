"""FastAPI application for VectorEasy."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
import uuid
from typing import Any, Optional

import numpy as np
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.batch.processor import BatchProcessor
from app.vectorizer.engine import VectorizationEngine
from app.vectorizer.exporter import SVGExporter
from app.vectorizer.segmentation import SegmentationEditor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="VectorEasy", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

_JOBS: dict[str, dict[str, Any]] = {}
_BATCH_PROCESSORS: dict[str, BatchProcessor] = {}

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_engine = VectorizationEngine()
_exporter = SVGExporter()
_segmentation = SegmentationEditor()


def _new_job(job_type: str = "single") -> tuple[str, dict]:
    job_id = str(uuid.uuid4())
    job: dict[str, Any] = {
        "job_id": job_id,
        "type": job_type,
        "status": "queued",
        "progress": 0,
        "stage": "queued",
        "error": None,
        "svg": None,
        "palette": [],
        "masks": [],
        "quantized_img": None,
        "width": 0,
        "height": 0,
        "created_at": time.time(),
    }
    _JOBS[job_id] = job
    return job_id, job


def _progress_cb(job: dict) -> Any:
    def _cb(pct: int, stage: str) -> None:
        job["progress"] = pct
        job["stage"] = stage
    return _cb


def _run_vectorize(job: dict, image_data: bytes, settings: dict) -> None:
    """Blocking vectorization task executed in a thread pool."""
    job["status"] = "processing"
    try:
        result = _engine.vectorize(image_data, settings, progress_callback=_progress_cb(job))
        job["svg"] = result["svg"]
        job["palette"] = result["palette"]
        # Store masks and quantized_img for segmentation operations
        job["masks"] = result["masks"]
        job["quantized_img"] = result["quantized_img"]
        job["width"] = result["width"]
        job["height"] = result["height"]
        job["status"] = "done"
        job["progress"] = 100
        job["stage"] = "done"
    except Exception as exc:
        logger.exception("Vectorization failed for job %s", job["job_id"])
        job["status"] = "error"
        job["error"] = str(exc)
        job["stage"] = "error"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/vectorize")
async def vectorize(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    settings: str = Form("{}"),
) -> JSONResponse:
    """Accept a single image upload and start vectorization."""
    import json

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large (max 100 MB)")

    try:
        settings_dict = json.loads(settings) if settings else {}
    except json.JSONDecodeError:
        settings_dict = {}

    job_id, job = _new_job("single")
    background_tasks.add_task(_run_vectorize, job, content, settings_dict)
    return JSONResponse({"job_id": job_id})


@app.post("/api/batch")
async def batch_upload(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    settings: str = Form("{}"),
) -> JSONResponse:
    """Accept multiple images and queue them for batch processing."""
    import json

    try:
        settings_dict = json.loads(settings) if settings else {}
    except json.JSONDecodeError:
        settings_dict = {}

    batch_id = str(uuid.uuid4())
    processor = BatchProcessor()
    _BATCH_PROCESSORS[batch_id] = processor

    job_ids: list[str] = []
    for f in files:
        content = await f.read()
        if len(content) > MAX_FILE_SIZE:
            continue
        job_id = processor.add_job(content, f.filename or "image", settings_dict)
        job_ids.append(job_id)

    # Create a synthetic "batch job" entry so /api/status/{batch_id} works
    _JOBS[batch_id] = {
        "job_id": batch_id,
        "type": "batch",
        "batch_processor": processor,
        "job_ids": job_ids,
        "status": "processing",
    }

    background_tasks.add_task(_run_batch, processor)
    return JSONResponse({"batch_id": batch_id, "job_ids": job_ids})


def _run_batch(processor: BatchProcessor) -> None:
    """Run batch processing in a new event loop (thread-safe)."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(processor.process_all())
    finally:
        loop.close()


@app.get("/api/status/{job_id}")
async def job_status(job_id: str) -> JSONResponse:
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job.get("type") == "batch":
        bp: BatchProcessor = job["batch_processor"]
        st = bp.get_status()
        st["job_id"] = job_id
        st["status"] = "done" if st["percent"] == 100 else "processing"
        return JSONResponse(st)

    return JSONResponse({
        "job_id": job_id,
        "status": job["status"],
        "progress": job.get("progress", 0),
        "stage": job.get("stage", ""),
        "error": job.get("error"),
    })


@app.get("/api/result/{job_id}")
async def job_result(job_id: str) -> JSONResponse:
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "done":
        raise HTTPException(409, f"Job not done yet (status={job['status']})")

    return JSONResponse({
        "job_id": job_id,
        "svg": job["svg"],
        "palette": job["palette"],
        "width": job["width"],
        "height": job["height"],
    })


@app.get("/api/download/{job_id}/{fmt}")
async def download(job_id: str, fmt: str) -> Response:
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "done":
        raise HTTPException(409, "Job not done yet")

    svg: str = job["svg"]
    fmt = fmt.lower()

    content_types = {
        "svg": "image/svg+xml",
        "eps": "application/postscript",
        "pdf": "application/pdf",
        "dxf": "application/dxf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
    }
    if fmt not in content_types:
        raise HTTPException(400, f"Unsupported format: {fmt}")

    try:
        if fmt == "svg":
            data = _exporter.export_svg(svg)
        elif fmt == "eps":
            data = _exporter.export_eps(svg)
        elif fmt == "pdf":
            data = _exporter.export_pdf(svg)
        elif fmt == "dxf":
            data = _exporter.export_dxf(svg)
        elif fmt == "png":
            data = _exporter.export_png(svg, scale=1)
        elif fmt == "jpg":
            data = _exporter.export_jpg(svg)
        elif fmt == "gif":
            data = _exporter.export_gif(svg)
        elif fmt == "bmp":
            data = _exporter.export_bmp(svg)
        elif fmt == "tiff":
            data = _exporter.export_tiff(svg)
        else:
            raise HTTPException(400, "Unknown format")
    except Exception as exc:
        logger.exception("Export failed for job %s fmt %s", job_id, fmt)
        raise HTTPException(500, f"Export failed: {exc}") from exc

    return Response(
        content=data,
        media_type=content_types[fmt],
        headers={"Content-Disposition": f'attachment; filename="vectoreasy.{fmt}"'},
    )


@app.get("/api/batch/download/{batch_id}")
async def batch_download(batch_id: str) -> Response:
    job = _JOBS.get(batch_id)
    if not job or job.get("type") != "batch":
        raise HTTPException(404, "Batch not found")
    bp: BatchProcessor = job["batch_processor"]
    zip_bytes = bp.create_zip()
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="vectoreasy_batch.zip"'},
    )


# ---------------------------------------------------------------------------
# Segmentation endpoints
# ---------------------------------------------------------------------------

def _get_job_seg_data(job_id: str) -> tuple[dict, np.ndarray, list, list]:
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "done":
        raise HTTPException(409, "Job not done yet")
    return job, job["quantized_img"], job["masks"], job["palette"]


def _update_job_after_seg(job: dict, new_img: np.ndarray, new_masks: list, new_palette: list) -> None:
    from app.vectorizer.tracer import SVGTracer
    from app.vectorizer.optimizer import SVGOptimizer

    job["quantized_img"] = new_img
    job["masks"] = new_masks
    job["palette"] = new_palette

    tracer = SVGTracer()
    optimizer = SVGOptimizer()

    layers = []
    for color, mask in zip(new_palette, new_masks):
        path_el = tracer.trace_layer(mask, color, {"detail": "medium", "smooth": True})
        if path_el:
            layers.append((color, path_el))

    h, w = new_img.shape[:2]
    svg_raw = tracer.assemble_svg(layers, w, h, {})
    job["svg"] = optimizer.optimize_svg(svg_raw, {})


@app.post("/api/segment/merge")
async def segment_merge(request: Request) -> JSONResponse:
    body = await request.json()
    job_id = body.get("job_id")
    indices = body.get("indices", [])
    job, q_img, masks, palette = _get_job_seg_data(job_id)
    new_img, new_masks, new_palette = _segmentation.merge_segments(
        q_img, masks, palette, indices
    )
    _update_job_after_seg(job, new_img, new_masks, new_palette)
    return JSONResponse({"status": "ok", "palette": new_palette})


@app.post("/api/segment/split")
async def segment_split(request: Request) -> JSONResponse:
    body = await request.json()
    job_id = body.get("job_id")
    index = body.get("index", 0)
    n_parts = body.get("n_parts", 2)
    job, q_img, masks, palette = _get_job_seg_data(job_id)
    new_img, new_masks, new_palette = _segmentation.split_segment(
        q_img, masks, palette, index, n_parts
    )
    _update_job_after_seg(job, new_img, new_masks, new_palette)
    return JSONResponse({"status": "ok", "palette": new_palette})


@app.post("/api/segment/recolor")
async def segment_recolor(request: Request) -> JSONResponse:
    body = await request.json()
    job_id = body.get("job_id")
    index = body.get("index", 0)
    new_color = body.get("color", "#000000")
    job, q_img, masks, palette = _get_job_seg_data(job_id)
    new_img, new_masks, new_palette = _segmentation.recolor_segment(
        q_img, masks, palette, index, new_color
    )
    _update_job_after_seg(job, new_img, new_masks, new_palette)
    return JSONResponse({"status": "ok", "palette": new_palette})


@app.post("/api/segment/delete")
async def segment_delete(request: Request) -> JSONResponse:
    body = await request.json()
    job_id = body.get("job_id")
    index = body.get("index", 0)
    job, q_img, masks, palette = _get_job_seg_data(job_id)
    new_img, new_masks, new_palette = _segmentation.delete_segment(
        q_img, masks, palette, index
    )
    _update_job_after_seg(job, new_img, new_masks, new_palette)
    return JSONResponse({"status": "ok", "palette": new_palette})


@app.post("/api/clipboard")
async def clipboard_paste(request: Request) -> JSONResponse:
    """Accept a base64-encoded image (e.g. from clipboard paste via JS)."""
    import json as _json

    body = await request.json()
    data_url: str = body.get("data", "")
    settings_raw: str = body.get("settings", "{}")

    try:
        settings_dict = _json.loads(settings_raw)
    except Exception:
        settings_dict = {}

    # Strip data URL prefix
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(data_url)
    except Exception as exc:
        raise HTTPException(400, f"Invalid base64 data: {exc}") from exc

    job_id, job = _new_job("single")

    # Run in background (non-blocking)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_vectorize, job, image_bytes, settings_dict)

    return JSONResponse({"job_id": job_id})
