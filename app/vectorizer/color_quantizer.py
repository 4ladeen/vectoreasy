"""Color quantizer for the VectorEasy vectorization pipeline."""

from __future__ import annotations

import colorsys
from typing import Any

import cv2
import numpy as np
from sklearn.cluster import MiniBatchKMeans


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bgr_to_hex(bgr: tuple[int, int, int]) -> str:
    b, g, r = int(bgr[0]), int(bgr[1]), int(bgr[2])
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return (b, g, r)


def _color_distance(c1: np.ndarray, c2: np.ndarray) -> float:
    """Perceptual distance in BGR space (fast approximation)."""
    dr = float(c1[2]) - float(c2[2])
    dg = float(c1[1]) - float(c2[1])
    db = float(c1[0]) - float(c2[0])
    r_mean = (float(c1[2]) + float(c2[2])) / 2.0
    return ((2 + r_mean / 256) * dr * dr + 4 * dg * dg + (2 + (255 - r_mean) / 256) * db * db) ** 0.5


# ---------------------------------------------------------------------------
# Median Cut
# ---------------------------------------------------------------------------

class _MedianCutBox:
    def __init__(self, pixels: np.ndarray) -> None:
        self.pixels = pixels

    def _channel_range(self) -> int:
        ranges = self.pixels.max(axis=0) - self.pixels.min(axis=0)
        return int(np.argmax(ranges))

    def split(self) -> tuple[_MedianCutBox, _MedianCutBox]:
        ch = self._channel_range()
        sorted_pixels = self.pixels[self.pixels[:, ch].argsort()]
        mid = len(sorted_pixels) // 2
        return _MedianCutBox(sorted_pixels[:mid]), _MedianCutBox(sorted_pixels[mid:])

    @property
    def average(self) -> np.ndarray:
        return self.pixels.mean(axis=0).astype(np.uint8)


def _median_cut(pixels: np.ndarray, n_colors: int) -> np.ndarray:
    """Return *n_colors* representative colors via median cut."""
    boxes: list[_MedianCutBox] = [_MedianCutBox(pixels)]
    while len(boxes) < n_colors:
        # Split the largest box
        boxes.sort(key=lambda b: len(b.pixels), reverse=True)
        largest = boxes.pop(0)
        if len(largest.pixels) < 2:
            boxes.insert(0, largest)
            break
        left, right = largest.split()
        boxes.extend([left, right])
    return np.array([b.average for b in boxes], dtype=np.uint8)


# ---------------------------------------------------------------------------
# Octree Node
# ---------------------------------------------------------------------------

class _OctreeNode:
    def __init__(self, level: int) -> None:
        self.level = level
        self.red = self.green = self.blue = 0
        self.pixel_count = 0
        self.children: list[_OctreeNode | None] = [None] * 8

    def add_color(self, r: int, g: int, b: int) -> None:
        self.red += r
        self.green += g
        self.blue += b
        self.pixel_count += 1

    @property
    def average(self) -> np.ndarray:
        n = max(self.pixel_count, 1)
        return np.array([self.blue // n, self.green // n, self.red // n], dtype=np.uint8)

    def is_leaf(self) -> bool:
        return self.pixel_count > 0 and all(c is None for c in self.children)


def _octree_quantize(pixels: np.ndarray, n_colors: int) -> np.ndarray:
    """Simplified octree quantization returning *n_colors* centroids."""
    # Use OpenCV's built-in kmeans after sampling for large images
    # (true octree can be slow in pure Python for large images)
    sample_size = min(len(pixels), 50000)
    idx = np.random.choice(len(pixels), sample_size, replace=False)
    sample = pixels[idx].astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, _, centers = cv2.kmeans(sample, n_colors, None, criteria, 5, cv2.KMEANS_PP_CENTERS)
    return centers.astype(np.uint8)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ColorQuantizer:
    """Quantize an image to a fixed palette using several algorithms."""

    def quantize(
        self,
        image: np.ndarray,
        n_colors: int,
        method: str = "kmeans",
    ) -> tuple[np.ndarray, list[str], list[np.ndarray]]:
        """Quantize *image* to *n_colors* colors.

        Parameters
        ----------
        image:
            BGR or BGRA uint8 ndarray.
        n_colors:
            Target palette size (2–64).  If 0 or negative, use auto-selection.
        method:
            ``'kmeans'``, ``'median_cut'``, or ``'octree'``.

        Returns
        -------
        quantized_img:
            BGR uint8 ndarray where every pixel has been replaced by its
            closest palette color.
        hex_colors:
            List of ``'#rrggbb'`` strings (one per cluster).
        masks:
            List of binary masks (uint8, 0/255) – one per cluster.
        """
        n_colors = max(2, min(64, n_colors))

        # Handle alpha
        alpha: np.ndarray | None = None
        if image.ndim == 3 and image.shape[2] == 4:
            alpha = image[:, :, 3]
            image = image[:, :, :3]

        h, w = image.shape[:2]

        # Auto-select K if 0
        if n_colors == 0:
            n_colors = self._auto_k(image)

        pixels = image.reshape(-1, 3).astype(np.float32)

        # --- Compute palette ---
        if method == "median_cut":
            palette = _median_cut(pixels.astype(np.uint8), n_colors)
        elif method == "octree":
            palette = _octree_quantize(pixels, n_colors)
        else:  # kmeans (default)
            palette = self._kmeans(pixels, n_colors)

        # --- Assign each pixel to closest palette color ---
        labels = self._assign_labels(pixels, palette)

        # --- Rebuild image ---
        flat_result = palette[labels]
        quantized_img = flat_result.reshape(h, w, 3).astype(np.uint8)

        # --- Refine palette: remove insignificant colors, merge similar ---
        palette, labels_2d = self._refine_palette(quantized_img, palette, labels.reshape(h, w))
        quantized_img, palette, labels_2d = self._rebuild_from_labels(labels_2d, palette, h, w)

        # --- Build outputs ---
        hex_colors = [_bgr_to_hex(tuple(int(v) for v in c)) for c in palette]  # type: ignore[arg-type]
        masks = self._build_masks(labels_2d, len(palette))

        # Re-apply alpha as mask if present
        if alpha is not None:
            for i in range(len(masks)):
                masks[i] = cv2.bitwise_and(masks[i], alpha)

        return quantized_img, hex_colors, masks

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _kmeans(self, pixels: np.ndarray, k: int) -> np.ndarray:
        sample_size = min(len(pixels), 100_000)
        if len(pixels) > sample_size:
            idx = np.random.choice(len(pixels), sample_size, replace=False)
            sample = pixels[idx]
        else:
            sample = pixels

        kmeans = MiniBatchKMeans(
            n_clusters=k,
            random_state=42,
            batch_size=min(10000, len(sample)),
            n_init=3,
            max_iter=100,
        )
        kmeans.fit(sample)
        return kmeans.cluster_centers_.astype(np.uint8)

    def _assign_labels(self, pixels: np.ndarray, palette: np.ndarray) -> np.ndarray:
        """Assign each pixel to the nearest palette entry (vectorized)."""
        # pixels: (N, 3) float32, palette: (K, 3) uint8
        p = palette.astype(np.float32)
        # Compute squared distances: (N, K)
        diff = pixels[:, np.newaxis, :] - p[np.newaxis, :, :]
        dist_sq = (diff ** 2).sum(axis=2)
        return np.argmin(dist_sq, axis=1).astype(np.int32)

    def _auto_k(self, image: np.ndarray) -> int:
        """Estimate a good number of colors from histogram analysis."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
        # Count peaks in histogram as proxy for distinct tone groups
        non_zero_bins = int((hist > 0).sum())
        k = max(2, min(32, non_zero_bins // 8))
        return k

    def _refine_palette(
        self,
        quantized_img: np.ndarray,
        palette: np.ndarray,
        labels_2d: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Merge very similar colors and remove colors covering < 0.1% of pixels."""
        h, w = labels_2d.shape
        total = h * w
        k = len(palette)
        pixel_counts = np.bincount(labels_2d.flatten(), minlength=k)

        # Indices to keep (coverage ≥ 0.1%)
        keep = np.where(pixel_counts / total >= 0.001)[0]
        if len(keep) == 0:
            keep = np.array([np.argmax(pixel_counts)])

        palette = palette[keep]

        # Remap labels
        remap = {old_idx: new_idx for new_idx, old_idx in enumerate(keep)}
        new_labels = np.zeros_like(labels_2d)
        for old_idx, new_idx in remap.items():
            new_labels[labels_2d == old_idx] = new_idx
        # Unmapped pixels (removed colors) → nearest kept
        unmapped_mask = np.isin(labels_2d, keep, invert=True)
        if unmapped_mask.any():
            flat_pixels = quantized_img[unmapped_mask].astype(np.float32)
            new_labels[unmapped_mask] = self._assign_labels(flat_pixels, palette)

        # Merge very similar palette entries (distance < 15)
        merged = True
        while merged and len(palette) > 2:
            merged = False
            for i in range(len(palette)):
                for j in range(i + 1, len(palette)):
                    if _color_distance(palette[i], palette[j]) < 15:
                        # Merge j into i
                        new_labels[new_labels == j] = i
                        # Re-index
                        palette = np.delete(palette, j, axis=0)
                        new_labels = self._compact_labels(new_labels, j)
                        merged = True
                        break
                if merged:
                    break

        return palette, new_labels

    def _compact_labels(self, labels: np.ndarray, removed_idx: int) -> np.ndarray:
        """Shift labels > removed_idx down by 1."""
        new = labels.copy()
        new[labels > removed_idx] -= 1
        return new

    def _rebuild_from_labels(
        self,
        labels_2d: np.ndarray,
        palette: np.ndarray,
        h: int,
        w: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        quantized = palette[labels_2d].astype(np.uint8)
        return quantized, palette, labels_2d

    def _build_masks(self, labels_2d: np.ndarray, k: int) -> list[np.ndarray]:
        masks = []
        for i in range(k):
            mask = np.where(labels_2d == i, np.uint8(255), np.uint8(0))
            masks.append(mask)
        return masks
