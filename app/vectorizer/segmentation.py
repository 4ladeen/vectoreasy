"""Segmentation editor for VectorEasy."""

from __future__ import annotations

import cv2
import numpy as np


def _hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return (b, g, r)


def _bgr_to_hex(bgr: tuple[int, int, int] | np.ndarray) -> str:
    b, g, r = int(bgr[0]), int(bgr[1]), int(bgr[2])
    return f"#{r:02x}{g:02x}{b:02x}"


class SegmentationEditor:
    """Provides in-place editing operations on a quantized image segmentation."""

    # ------------------------------------------------------------------ #
    #  Merge                                                               #
    # ------------------------------------------------------------------ #

    def merge_segments(
        self,
        quantized_img: np.ndarray,
        masks: list[np.ndarray],
        palette: list[str],
        indices_to_merge: list[int],
    ) -> tuple[np.ndarray, list[np.ndarray], list[str]]:
        """Merge several segments into one.

        The merged segment receives the color of the first index in
        *indices_to_merge*.  All other indices are removed.

        Returns
        -------
        (new_img, new_masks, new_palette)
        """
        if not indices_to_merge or len(indices_to_merge) < 2:
            return quantized_img, masks, palette

        indices_to_merge = sorted(set(indices_to_merge))
        keep_idx = indices_to_merge[0]
        keep_color = palette[keep_idx]
        keep_bgr = np.array(_hex_to_bgr(keep_color), dtype=np.uint8)

        new_img = quantized_img.copy()
        merged_mask = np.zeros_like(masks[keep_idx])

        for idx in indices_to_merge:
            merged_mask = cv2.bitwise_or(merged_mask, masks[idx])
            if idx != keep_idx:
                new_img[masks[idx] == 255] = keep_bgr

        new_masks = []
        new_palette = []
        for i, (m, c) in enumerate(zip(masks, palette)):
            if i in indices_to_merge and i != keep_idx:
                continue
            if i == keep_idx:
                new_masks.append(merged_mask)
                new_palette.append(c)
            else:
                new_masks.append(m)
                new_palette.append(c)

        return new_img, new_masks, new_palette

    # ------------------------------------------------------------------ #
    #  Split                                                               #
    # ------------------------------------------------------------------ #

    def split_segment(
        self,
        quantized_img: np.ndarray,
        masks: list[np.ndarray],
        palette: list[str],
        index: int,
        n_parts: int = 2,
    ) -> tuple[np.ndarray, list[np.ndarray], list[str]]:
        """Split a segment into *n_parts* via k-means on pixel positions.

        New parts receive the original color (visually identical) but are
        tracked as separate segments so users can recolor them independently.
        """
        if index < 0 or index >= len(masks):
            return quantized_img, masks, palette
        if n_parts < 2:
            return quantized_img, masks, palette

        mask = masks[index]
        color = palette[index]
        ys, xs = np.where(mask == 255)
        if len(ys) < n_parts:
            return quantized_img, masks, palette

        pixel_coords = np.column_stack([xs, ys]).astype(np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        _, labels, _ = cv2.kmeans(pixel_coords, n_parts, None, criteria, 5, cv2.KMEANS_PP_CENTERS)
        labels = labels.flatten()

        new_masks: list[np.ndarray] = []
        for i in range(index):
            new_masks.append(masks[i])

        part_masks = []
        for part in range(n_parts):
            part_mask = np.zeros_like(mask)
            part_pixels = pixel_coords[labels == part].astype(np.int32)
            for px, py in part_pixels:
                part_mask[py, px] = 255
            part_masks.append(part_mask)

        new_masks.extend(part_masks)
        for i in range(index + 1, len(masks)):
            new_masks.append(masks[i])

        new_palette = palette[:index] + [color] * n_parts + palette[index + 1:]

        return quantized_img.copy(), new_masks, new_palette

    # ------------------------------------------------------------------ #
    #  Recolor                                                             #
    # ------------------------------------------------------------------ #

    def recolor_segment(
        self,
        quantized_img: np.ndarray,
        masks: list[np.ndarray],
        palette: list[str],
        index: int,
        new_color: str,
    ) -> tuple[np.ndarray, list[np.ndarray], list[str]]:
        """Change the color of segment *index* to *new_color*."""
        if index < 0 or index >= len(masks):
            return quantized_img, masks, palette

        new_bgr = np.array(_hex_to_bgr(new_color), dtype=np.uint8)
        new_img = quantized_img.copy()
        new_img[masks[index] == 255] = new_bgr

        new_palette = list(palette)
        new_palette[index] = new_color.lower() if new_color.startswith("#") else f"#{new_color}"

        return new_img, list(masks), new_palette

    # ------------------------------------------------------------------ #
    #  Delete                                                              #
    # ------------------------------------------------------------------ #

    def delete_segment(
        self,
        quantized_img: np.ndarray,
        masks: list[np.ndarray],
        palette: list[str],
        index: int,
    ) -> tuple[np.ndarray, list[np.ndarray], list[str]]:
        """Remove segment *index* (pixels become transparent / black)."""
        if index < 0 or index >= len(masks):
            return quantized_img, masks, palette

        new_img = quantized_img.copy()
        new_img[masks[index] == 255] = 0  # black

        new_masks = [m for i, m in enumerate(masks) if i != index]
        new_palette = [c for i, c in enumerate(palette) if i != index]

        return new_img, new_masks, new_palette

    # ------------------------------------------------------------------ #
    #  Grow / Shrink                                                       #
    # ------------------------------------------------------------------ #

    def grow_shrink_segment(
        self,
        mask: np.ndarray,
        pixels: int,
    ) -> np.ndarray:
        """Grow (positive *pixels*) or shrink (negative *pixels*) a mask.

        Uses morphological dilation or erosion with a circular kernel.
        """
        if pixels == 0:
            return mask.copy()

        abs_px = abs(pixels)
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * abs_px + 1, 2 * abs_px + 1)
        )
        if pixels > 0:
            return cv2.dilate(mask, kernel)
        else:
            return cv2.erode(mask, kernel)
