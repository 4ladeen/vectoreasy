"""Multi-format exporter for VectorEasy SVG output."""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from typing import Any

import cairosvg
import ezdxf
import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _svg_to_png_bytes(svg_content: str, scale: int = 1) -> bytes:
    """Rasterize SVG to PNG bytes at *scale* factor."""
    return cairosvg.svg2png(bytestring=svg_content.encode(), scale=scale)


def _png_bytes_to_pil(png_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png_bytes))


# ---------------------------------------------------------------------------
# SVG path data parser (minimal, for DXF export)
# ---------------------------------------------------------------------------

_CMD_RE = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])")


def _parse_svg_paths(svg_content: str) -> list[list[tuple[float, float]]]:
    """Extract polyline point lists from all <path d="..."> elements."""
    polylines: list[list[tuple[float, float]]] = []
    try:
        root = ET.fromstring(svg_content)
    except ET.ParseError:
        return polylines

    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag != "path":
            continue
        d = elem.get("d", "")
        if not d:
            continue
        polyline = _path_d_to_points(d)
        if len(polyline) >= 2:
            polylines.append(polyline)
    return polylines


def _path_d_to_points(d: str) -> list[tuple[float, float]]:
    """Very simplified path-d parser producing a flat polyline."""
    points: list[tuple[float, float]] = []
    tokens = _CMD_RE.split(d.strip())
    i = 0
    cur_x = cur_y = 0.0
    start_x = start_y = 0.0

    def _next_nums(token_str: str) -> list[float]:
        return [float(v) for v in re.findall(r"-?\d+\.?\d*(?:e[+-]?\d+)?", token_str, re.I)]

    while i < len(tokens):
        tok = tokens[i].strip()
        if not tok:
            i += 1
            continue
        if len(tok) == 1 and tok.isalpha():
            cmd = tok
            i += 1
            args_str = tokens[i] if i < len(tokens) else ""
            nums = _next_nums(args_str)
            i += 1

            if cmd == "M":
                j = 0
                while j + 1 < len(nums):
                    cur_x, cur_y = nums[j], nums[j + 1]
                    if j == 0:
                        start_x, start_y = cur_x, cur_y
                    points.append((cur_x, cur_y))
                    j += 2
            elif cmd == "m":
                j = 0
                while j + 1 < len(nums):
                    cur_x += nums[j]; cur_y += nums[j + 1]
                    if j == 0:
                        start_x, start_y = cur_x, cur_y
                    points.append((cur_x, cur_y))
                    j += 2
            elif cmd == "L":
                j = 0
                while j + 1 < len(nums):
                    cur_x, cur_y = nums[j], nums[j + 1]
                    points.append((cur_x, cur_y))
                    j += 2
            elif cmd == "l":
                j = 0
                while j + 1 < len(nums):
                    cur_x += nums[j]; cur_y += nums[j + 1]
                    points.append((cur_x, cur_y))
                    j += 2
            elif cmd == "H":
                for v in nums:
                    cur_x = v
                    points.append((cur_x, cur_y))
            elif cmd == "h":
                for v in nums:
                    cur_x += v
                    points.append((cur_x, cur_y))
            elif cmd == "V":
                for v in nums:
                    cur_y = v
                    points.append((cur_x, cur_y))
            elif cmd == "v":
                for v in nums:
                    cur_y += v
                    points.append((cur_x, cur_y))
            elif cmd in ("C", "c"):
                # Cubic bezier – sample end points only
                relative = cmd == "c"
                j = 0
                while j + 5 <= len(nums) - 1:
                    if relative:
                        cur_x += nums[j + 4]; cur_y += nums[j + 5]
                    else:
                        cur_x, cur_y = nums[j + 4], nums[j + 5]
                    points.append((cur_x, cur_y))
                    j += 6
            elif cmd in ("S", "s"):
                j = 0
                while j + 3 <= len(nums) - 1:
                    if cmd == "s":
                        cur_x += nums[j + 2]; cur_y += nums[j + 3]
                    else:
                        cur_x, cur_y = nums[j + 2], nums[j + 3]
                    points.append((cur_x, cur_y))
                    j += 4
            elif cmd in ("Z", "z"):
                cur_x, cur_y = start_x, start_y
                points.append((cur_x, cur_y))
        else:
            i += 1

    return points


# ---------------------------------------------------------------------------
# Exporter class
# ---------------------------------------------------------------------------

class SVGExporter:
    """Export SVG content to various formats."""

    def export_svg(self, svg_content: str) -> bytes:
        return svg_content.encode("utf-8")

    def export_eps(self, svg_content: str) -> bytes:
        return cairosvg.svg2eps(bytestring=svg_content.encode())

    def export_pdf(self, svg_content: str) -> bytes:
        return cairosvg.svg2pdf(bytestring=svg_content.encode())

    def export_png(self, svg_content: str, scale: int = 1) -> bytes:
        scale = max(1, min(8, scale))
        return _svg_to_png_bytes(svg_content, scale=scale)

    def export_jpg(self, svg_content: str, quality: int = 90) -> bytes:
        png_bytes = _svg_to_png_bytes(svg_content, scale=1)
        img = _png_bytes_to_pil(png_bytes).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()

    def export_gif(self, svg_content: str) -> bytes:
        png_bytes = _svg_to_png_bytes(svg_content, scale=1)
        img = _png_bytes_to_pil(png_bytes).convert("RGBA")
        # Convert to palette mode for GIF
        gif_img = img.convert("P", palette=Image.ADAPTIVE, colors=256)
        buf = io.BytesIO()
        gif_img.save(buf, format="GIF")
        return buf.getvalue()

    def export_bmp(self, svg_content: str) -> bytes:
        png_bytes = _svg_to_png_bytes(svg_content, scale=1)
        img = _png_bytes_to_pil(png_bytes).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="BMP")
        return buf.getvalue()

    def export_tiff(self, svg_content: str) -> bytes:
        png_bytes = _svg_to_png_bytes(svg_content, scale=1)
        img = _png_bytes_to_pil(png_bytes)
        buf = io.BytesIO()
        img.save(buf, format="TIFF", compression="lzw")
        return buf.getvalue()

    def export_dxf(self, svg_content: str) -> bytes:
        """Convert SVG paths to DXF polylines/splines."""
        doc = ezdxf.new(dxfversion="R2010")
        msp = doc.modelspace()

        polylines = _parse_svg_paths(svg_content)
        for polyline in polylines:
            if len(polyline) < 2:
                continue
            if len(polyline) == 2:
                msp.add_line(polyline[0], polyline[1])
            else:
                # Add as a lightweight polyline (2D)
                points_2d = [(p[0], p[1]) for p in polyline]
                try:
                    msp.add_lwpolyline(points_2d, close=False)
                except Exception:
                    for j in range(len(points_2d) - 1):
                        msp.add_line(points_2d[j], points_2d[j + 1])

        buf = io.StringIO()
        doc.write(buf)
        return buf.getvalue().encode("utf-8")
