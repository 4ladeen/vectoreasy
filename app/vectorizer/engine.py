"""Vectorization orchestrator for VectorEasy."""

from __future__ import annotations

import io
import logging
from typing import Callable, Any

import cv2
import numpy as np
from PIL import Image

from app.vectorizer.preprocessor import ImagePreprocessor
from app.vectorizer.color_quantizer import ColorQuantizer
from app.vectorizer.tracer import SVGTracer
from app.vectorizer.optimizer import SVGOptimizer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, Any] = {
    "mode": "auto",           # auto | photo | logo | line_art | pixel_art
    "n_colors": 16,           # 2-64
    "quantize_method": "kmeans",  # kmeans | median_cut | octree
    "detail": "medium",       # low | medium | high | ultra
    "smooth": True,
    "upscale": True,
    "denoise": True,
    "bilateral": True,
    "clahe": True,
    "sharpen": True,
    "background": "none",
    "optimize": True,
    "min_area": 4,
}

# ---------------------------------------------------------------------------
# Image type auto-detection
# ---------------------------------------------------------------------------

def _detect_mode(image: np.ndarray) -> str:
    """Guess the best vectorization mode from pixel statistics."""
    if image.ndim == 2 or (image.ndim == 3 and image.shape[2] == 1):
        return "line_art"

    bgr = image[:, :, :3] if image.shape[2] >= 3 else image
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Unique color count (sampled)
    h, w = gray.shape
    sample = bgr.reshape(-1, 3)
    if len(sample) > 10000:
        idx = np.random.choice(len(sample), 10000, replace=False)
        sample = sample[idx]
    unique_colors = len(np.unique(sample.view(np.dtype((np.void, sample.dtype.itemsize * 3)))))

    edge_density = float(cv2.Canny(gray, 50, 150).sum() / 255) / (h * w)
    std_dev = float(gray.std())

    if unique_colors < 64 and edge_density < 0.05:
        return "logo"
    if unique_colors < 16:
        return "pixel_art"
    if std_dev < 30:
        return "line_art"
    if unique_colors > 1000:
        return "photo"
    return "auto"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class VectorizationEngine:
    """End-to-end image vectorization pipeline."""

    def __init__(self) -> None:
        self._preprocessor = ImagePreprocessor()
        self._quantizer = ColorQuantizer()
        self._tracer = SVGTracer()
        self._optimizer = SVGOptimizer()

    def vectorize(
        self,
        image_data: bytes,
        settings: dict,
        progress_callback: Callable[[int, str], None] | None = None,
    ) -> dict:
        """Vectorize raw image bytes.

        Parameters
        ----------
        image_data:
            Raw bytes of any supported raster format (JPG, PNG, BMP, TIFF,
            WebP, GIF).
        settings:
            Dict overriding DEFAULT_SETTINGS entries.
        progress_callback:
            Optional ``callback(percent: int, stage: str)`` function.

        Returns
        -------
        dict with keys:
            ``svg``          – optimized SVG string
            ``quantized_img``– BGR uint8 ndarray
            ``palette``      – list of hex color strings
            ``masks``        – list of binary uint8 masks
            ``width``        – image width (after preprocessing)
            ``height``       – image height (after preprocessing)
        """
        cfg = {**DEFAULT_SETTINGS, **settings}

        def _progress(pct: int, stage: str) -> None:
            if progress_callback:
                try:
                    progress_callback(pct, stage)
                except Exception:
                    pass

        _progress(0, "loading")

        # --- Load image ---
        image = self._load_image(image_data)

        # --- Auto-detect mode ---
        if cfg["mode"] == "auto":
            cfg["mode"] = _detect_mode(image)
            logger.debug("Auto-detected mode: %s", cfg["mode"])

        _progress(10, "preprocessing")

        # --- Preprocess ---
        try:
            processed = self._preprocessor.preprocess(image, cfg)
        except Exception as exc:
            logger.warning("Preprocessing failed (%s), using raw image", exc)
            processed = image

        _progress(30, "quantizing")

        # --- Strip alpha for quantization ---
        alpha: np.ndarray | None = None
        if processed.ndim == 3 and processed.shape[2] == 4:
            alpha = processed[:, :, 3]
            bgr_image = processed[:, :, :3]
        else:
            bgr_image = processed

        h, w = bgr_image.shape[:2]

        # Handle grayscale
        if bgr_image.ndim == 2:
            bgr_image = cv2.cvtColor(bgr_image, cv2.COLOR_GRAY2BGR)
        elif bgr_image.shape[2] == 1:
            bgr_image = cv2.cvtColor(bgr_image, cv2.COLOR_GRAY2BGR)

        # Handle single-color images
        unique_pixels = np.unique(bgr_image.reshape(-1, 3), axis=0)
        if len(unique_pixels) == 1:
            color = tuple(int(v) for v in unique_pixels[0])
            hex_c = "#{:02x}{:02x}{:02x}".format(color[2], color[1], color[0])
            full_mask = np.full((h, w), 255, dtype=np.uint8)
            svg = self._tracer.assemble_svg(
                [(hex_c, self._tracer.trace_layer(full_mask, hex_c, cfg))],
                w, h, cfg,
            )
            return dict(svg=svg, quantized_img=bgr_image, palette=[hex_c],
                        masks=[full_mask], width=w, height=h)

        # --- Quantize ---
        n_colors = cfg.get("n_colors", 16)
        method = cfg.get("quantize_method", "kmeans")
        try:
            quantized_img, palette, masks = self._quantizer.quantize(
                bgr_image, n_colors, method
            )
        except Exception as exc:
            logger.error("Quantization failed: %s", exc)
            raise

        _progress(55, "tracing")

        # --- Trace each layer ---
        layers: list[tuple[str, str]] = []
        for i, (color, mask) in enumerate(zip(palette, masks)):
            try:
                path_el = self._tracer.trace_layer(mask, color, cfg)
                if path_el:
                    layers.append((color, path_el))
            except Exception as exc:
                logger.warning("Tracing layer %d failed: %s", i, exc)

        _progress(80, "assembling")

        # --- Assemble SVG ---
        svg_raw = self._tracer.assemble_svg(layers, w, h, cfg)

        _progress(90, "optimizing")

        # --- Optimize ---
        if cfg.get("optimize", True):
            try:
                svg_final = self._optimizer.optimize_svg(svg_raw, cfg)
            except Exception as exc:
                logger.warning("SVG optimization failed: %s", exc)
                svg_final = svg_raw
        else:
            svg_final = svg_raw

        _progress(100, "done")

        return dict(
            svg=svg_final,
            quantized_img=quantized_img,
            palette=palette,
            masks=masks,
            width=w,
            height=h,
        )

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _load_image(self, image_data: bytes) -> np.ndarray:
        """Decode image bytes to a BGR(A) ndarray."""
        # Try OpenCV first
        arr = np.frombuffer(image_data, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if image is not None:
            return image

        # Fallback: Pillow (handles WebP, animated GIF frame-0, etc.)
        try:
            pil_img = Image.open(io.BytesIO(image_data))
            # Take first frame for animated images
            pil_img.seek(0)
            pil_img = pil_img.convert("RGBA")
            np_img = np.array(pil_img)
            # RGBA → BGRA
            bgra = cv2.cvtColor(np_img, cv2.COLOR_RGBA2BGRA)
            return bgra
        except Exception as exc:
            raise ValueError(f"Cannot decode image data: {exc}") from exc
