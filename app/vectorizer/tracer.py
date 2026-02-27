"""Multi-layer SVG tracing engine for VectorEasy."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Ramer-Douglas-Peucker simplification
# ---------------------------------------------------------------------------

def _rdp_simplify(points: np.ndarray, epsilon: float) -> np.ndarray:
    """Ramer-Douglas-Peucker polyline simplification."""
    if len(points) < 3:
        return points

    def _rdp_rec(pts: np.ndarray, eps: float) -> list[int]:
        if len(pts) < 3:
            return list(range(len(pts)))
        start, end = pts[0], pts[-1]
        line_vec = end - start
        line_len = np.linalg.norm(line_vec)
        if line_len == 0:
            dists = np.linalg.norm(pts - start, axis=1)
        else:
            line_unit = line_vec / line_len
            proj = np.dot(pts - start, line_unit)
            proj_pts = start + np.outer(proj, line_unit)
            dists = np.linalg.norm(pts - proj_pts, axis=1)
        idx = int(np.argmax(dists))
        if dists[idx] > eps:
            left_indices = _rdp_rec(pts[: idx + 1], eps)
            right_indices = _rdp_rec(pts[idx:], eps)
            # right_indices are relative to pts[idx:], shift them by idx
            return left_indices[:-1] + [idx + i for i in right_indices]
        else:
            return [0, len(pts) - 1]

    keep = _rdp_rec(points, epsilon)
    keep = sorted(set(keep))
    return points[keep]


# ---------------------------------------------------------------------------
# Chaikin's corner cutting
# ---------------------------------------------------------------------------

def _chaikin_smooth(points: np.ndarray, iterations: int = 2, closed: bool = True) -> np.ndarray:
    """Chaikin's corner-cutting algorithm for curve smoothing."""
    pts = points.astype(np.float64)
    for _ in range(iterations):
        new_pts: list[np.ndarray] = []
        n = len(pts)
        end = n if closed else n - 1
        for i in range(end):
            p0 = pts[i]
            p1 = pts[(i + 1) % n]
            new_pts.append(0.75 * p0 + 0.25 * p1)
            new_pts.append(0.25 * p0 + 0.75 * p1)
        pts = np.array(new_pts)
    return pts


# ---------------------------------------------------------------------------
# Bezier fitting helpers
# ---------------------------------------------------------------------------

def _cubic_bezier_to_svg(p0: np.ndarray, p1: np.ndarray, p2: np.ndarray, p3: np.ndarray) -> str:
    return (
        f"C {p1[0]:.2f} {p1[1]:.2f} "
        f"{p2[0]:.2f} {p2[1]:.2f} "
        f"{p3[0]:.2f} {p3[1]:.2f}"
    )


def _fit_cubic_bezier(points: np.ndarray) -> str:
    """Fit a cubic Bezier to a polyline segment and return SVG path commands."""
    if len(points) < 2:
        return ""
    if len(points) == 2:
        return f"L {points[-1][0]:.2f} {points[-1][1]:.2f}"
    # Use Catmull-Rom to derive control points
    path_cmds: list[str] = []
    n = len(points)
    for i in range(n - 1):
        p0 = points[max(i - 1, 0)]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[min(i + 2, n - 1)]
        cp1 = p1 + (p2 - p0) / 6.0
        cp2 = p2 - (p3 - p1) / 6.0
        path_cmds.append(_cubic_bezier_to_svg(p1, cp1, cp2, p2))
    return " ".join(path_cmds)


# ---------------------------------------------------------------------------
# Contour-to-path conversion
# ---------------------------------------------------------------------------

DETAIL_EPSILON = {
    "low": 3.0,
    "medium": 1.5,
    "high": 0.8,
    "ultra": 0.3,
}

DETAIL_CHAIKIN = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "ultra": 4,
}


def _contour_to_path(contour: np.ndarray, detail: str = "medium", smooth: bool = True) -> str:
    """Convert an OpenCV contour (N,1,2) to an SVG path string."""
    pts = contour.reshape(-1, 2).astype(np.float64)
    if len(pts) < 3:
        return ""

    epsilon = DETAIL_EPSILON.get(detail, 1.5)
    pts = _rdp_simplify(pts, epsilon)
    if len(pts) < 3:
        return ""

    if smooth:
        iters = DETAIL_CHAIKIN.get(detail, 2)
        pts = _chaikin_smooth(pts, iterations=iters, closed=True)

    start = pts[0]
    path = f"M {start[0]:.2f} {start[1]:.2f} "

    if smooth and len(pts) > 3:
        path += _fit_cubic_bezier(pts)
    else:
        for pt in pts[1:]:
            path += f"L {pt[0]:.2f} {pt[1]:.2f} "

    path += " Z"
    return path.strip()


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class SVGTracer:
    """Trace binary masks into SVG path data."""

    def trace_layer(
        self,
        mask: np.ndarray,
        color: str,
        settings: dict,
    ) -> str:
        """Return an SVG ``<path>`` element string for *mask*.

        Parameters
        ----------
        mask:
            Binary uint8 mask (0/255).
        color:
            Fill color as ``'#rrggbb'``.
        settings:
            Dict with optional keys: ``detail`` (low/medium/high/ultra),
            ``smooth`` (bool).
        """
        detail = settings.get("detail", "medium")
        smooth = settings.get("smooth", True)
        min_area = settings.get("min_area", 4)

        if mask is None or mask.size == 0:
            return ""

        # Find external and hole contours
        contours, hierarchy = cv2.findContours(
            mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours or hierarchy is None:
            return ""

        hierarchy = hierarchy[0]  # (N, 4): next, prev, first_child, parent
        path_data_parts: list[str] = []

        for i, contour in enumerate(contours):
            area = cv2.contourArea(contour)
            if area < min_area:
                continue

            # Only process top-level contours (parent == -1) here;
            # holes are children and are added as counter-clockwise sub-paths
            if hierarchy[i][3] != -1:
                continue

            outer_path = _contour_to_path(contour, detail, smooth)
            if not outer_path:
                continue
            path_data_parts.append(outer_path)

            # Find holes (children)
            child_idx = hierarchy[i][2]
            while child_idx >= 0:
                hole = contours[child_idx]
                hole_area = cv2.contourArea(hole)
                if hole_area >= min_area:
                    hole_path = _contour_to_path(hole[::-1], detail, smooth)  # reverse = CW hole
                    if hole_path:
                        path_data_parts.append(hole_path)
                child_idx = hierarchy[child_idx][0]

        if not path_data_parts:
            return ""

        path_data = " ".join(path_data_parts)
        return (
            f'<path fill="{color}" fill-rule="evenodd" '
            f'd="{path_data}"/>'
        )

    def assemble_svg(
        self,
        layers: list[tuple[str, str]],  # list of (color, path_element_str)
        width: int,
        height: int,
        settings: dict | None = None,
    ) -> str:
        """Assemble a complete SVG document from traced layers.

        Parameters
        ----------
        layers:
            List of ``(hex_color, path_element_string)`` tuples.
        width, height:
            Image dimensions in pixels.
        settings:
            Optional dict; supports ``background`` (hex color or 'none').
        """
        settings = settings or {}
        bg = settings.get("background", "none")

        svg_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}">',
        ]

        if bg and bg != "none":
            svg_lines.append(f'  <rect width="{width}" height="{height}" fill="{bg}"/>')

        for color, path_el in layers:
            if path_el:
                svg_lines.append(f"  {path_el}")

        svg_lines.append("</svg>")
        return "\n".join(svg_lines)
