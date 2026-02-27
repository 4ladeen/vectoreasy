"""SVG optimizer for VectorEasy."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from io import StringIO


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COORD_RE = re.compile(r"(-?\d+\.?\d*(?:e[+-]?\d+)?)", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _round_coords(match: re.Match) -> str:
    """Round a coordinate value to 2 decimal places."""
    val = float(match.group(1))
    rounded = round(val, 2)
    # Remove trailing zeros after decimal point
    s = f"{rounded:.2f}".rstrip("0").rstrip(".")
    return s


def _round_path_coords(d: str) -> str:
    """Round all numeric values in an SVG path ``d`` attribute."""
    return _COORD_RE.sub(_round_coords, d)


# ---------------------------------------------------------------------------
# Main optimizer
# ---------------------------------------------------------------------------

class SVGOptimizer:
    """Optimize SVG content by simplifying paths, merging groups, etc."""

    def optimize_svg(self, svg_content: str, settings: dict) -> str:
        """Return an optimized version of *svg_content*.

        Optimization steps controlled by *settings*:
        - ``round_coords`` (bool, default True)
        - ``remove_comments`` (bool, default True)
        - ``minify`` (bool, default True)
        - ``merge_paths`` (bool, default True)
        - ``collapse_groups`` (bool, default True)
        - ``optimize_viewbox`` (bool, default True)
        """
        if not svg_content:
            return svg_content

        do_round = settings.get("round_coords", True)
        do_comments = settings.get("remove_comments", True)
        do_minify = settings.get("minify", True)
        do_merge = settings.get("merge_paths", True)
        do_collapse = settings.get("collapse_groups", True)
        do_viewbox = settings.get("optimize_viewbox", True)

        svg = svg_content

        # 1. Remove XML comments
        if do_comments:
            svg = _COMMENT_RE.sub("", svg)

        # 2. Parse and manipulate the tree
        try:
            ET.register_namespace("", "http://www.w3.org/2000/svg")
            ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
            root = ET.fromstring(svg)
        except ET.ParseError:
            # If parsing fails, return original (possibly just minified)
            if do_minify:
                svg = _WHITESPACE_RE.sub(" ", svg).strip()
            return svg

        ns = {"svg": "http://www.w3.org/2000/svg"}

        # 3. Round path coordinates
        if do_round:
            self._round_all_paths(root)

        # 4. Collapse empty groups
        if do_collapse:
            self._collapse_empty_groups(root)

        # 5. Merge adjacent paths with the same fill
        if do_merge:
            self._merge_same_fill_paths(root)

        # 6. Optimize viewBox
        if do_viewbox:
            self._optimize_viewbox(root)

        # 7. Serialise
        svg_out = ET.tostring(root, encoding="unicode", xml_declaration=False)
        # Re-add XML declaration
        svg_out = '<?xml version="1.0" encoding="UTF-8"?>\n' + svg_out

        # 8. Minify
        if do_minify:
            svg_out = self._minify(svg_out)

        return svg_out

    # ------------------------------------------------------------------ #
    #  Step implementations                                                #
    # ------------------------------------------------------------------ #

    def _round_all_paths(self, root: ET.Element) -> None:
        """Round coordinates in all path 'd' attributes."""
        for elem in root.iter():
            d = elem.get("d")
            if d:
                elem.set("d", _round_path_coords(d))
            # Also round width/height/x/y/cx/cy/r attributes
            for attr in ("x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
                         "width", "height"):
                val = elem.get(attr)
                if val:
                    try:
                        elem.set(attr, str(round(float(val), 2)))
                    except ValueError:
                        pass

    def _collapse_empty_groups(self, root: ET.Element) -> None:
        """Remove <g> elements that have no children or attributes."""
        changed = True
        while changed:
            changed = False
            for parent in root.iter():
                to_remove = []
                for child in list(parent):
                    tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if tag == "g":
                        attribs = {k: v for k, v in child.attrib.items()
                                   if k not in ("id",)}
                        if not attribs and len(child) == 0:
                            to_remove.append(child)
                        elif not attribs and len(child) > 0:
                            # Unwrap group – move children up
                            idx = list(parent).index(child)
                            for i, grandchild in enumerate(list(child)):
                                parent.insert(idx + i, grandchild)
                            to_remove.append(child)
                            changed = True
                for child in to_remove:
                    try:
                        parent.remove(child)
                    except ValueError:
                        pass

    def _merge_same_fill_paths(self, root: ET.Element) -> None:
        """Merge consecutive <path> siblings that share the same fill."""
        for parent in root.iter():
            children = list(parent)
            if len(children) < 2:
                continue

            i = 0
            while i < len(children) - 1:
                curr = children[i]
                nxt = children[i + 1]

                curr_tag = curr.tag.split("}")[-1] if "}" in curr.tag else curr.tag
                nxt_tag = nxt.tag.split("}")[-1] if "}" in nxt.tag else nxt.tag

                if curr_tag == "path" and nxt_tag == "path":
                    curr_fill = curr.get("fill", "")
                    nxt_fill = nxt.get("fill", "")
                    curr_rule = curr.get("fill-rule", "")
                    nxt_rule = nxt.get("fill-rule", "")
                    if curr_fill == nxt_fill and curr_rule == nxt_rule and curr_fill:
                        # Merge path data
                        merged_d = (curr.get("d", "") + " " + nxt.get("d", "")).strip()
                        curr.set("d", merged_d)
                        parent.remove(nxt)
                        children = list(parent)
                        continue  # re-check same position
                i += 1

    def _optimize_viewbox(self, root: ET.Element) -> None:
        """Ensure viewBox attribute is consistent with width/height."""
        width = root.get("width")
        height = root.get("height")
        viewbox = root.get("viewBox")
        if width and height and not viewbox:
            try:
                w = float(width)
                h = float(height)
                root.set("viewBox", f"0 0 {w:.2f} {h:.2f}")
            except ValueError:
                pass

    def _minify(self, svg: str) -> str:
        """Collapse excess whitespace while keeping the SVG valid."""
        # Remove newlines and tabs
        svg = svg.replace("\n", " ").replace("\r", " ").replace("\t", " ")
        # Collapse multiple spaces
        svg = _WHITESPACE_RE.sub(" ", svg)
        # Remove spaces around XML punctuation
        svg = re.sub(r"\s*>\s*", ">", svg)
        svg = re.sub(r"\s*<\s*", "<", svg)
        svg = re.sub(r"\s*=\s*", "=", svg)
        return svg.strip()
