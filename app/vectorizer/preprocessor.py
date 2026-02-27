"""Image preprocessor for the VectorEasy vectorization pipeline."""

from __future__ import annotations

import cv2
import numpy as np


class ImagePreprocessor:
    """Preprocesses raster images before vectorization.

    Steps (in order):
    1. Alpha channel handling – preserve transparency through a separate mask.
    2. Auto-upscaling – images whose longest side is < 1000 px are upscaled 2-4×
       using INTER_LANCZOS4.
    3. Non-Local Means Denoising.
    4. Bilateral Filtering.
    5. CLAHE contrast enhancement.
    6. Edge-aware sharpening (unsharp mask).
    7. Alpha re-application.
    """

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def preprocess(self, image: np.ndarray, settings: dict) -> np.ndarray:
        """Return a pre-processed copy of *image* according to *settings*.

        Parameters
        ----------
        image:
            BGR or BGRA uint8 ndarray read by OpenCV.
        settings:
            Dictionary with optional overrides:
            - ``upscale`` (bool, default True)
            - ``denoise`` (bool, default True)
            - ``bilateral`` (bool, default True)
            - ``clahe`` (bool, default True)
            - ``sharpen`` (bool, default True)
            - ``mode`` (str) – hints from the engine ('photo', 'logo',
              'line_art', 'pixel_art', 'auto')

        Returns
        -------
        np.ndarray
            Preprocessed BGR or BGRA uint8 ndarray.
        """
        if image is None or image.size == 0:
            raise ValueError("Empty or None image passed to preprocessor")

        image = image.copy()
        mode = settings.get("mode", "auto")

        # --- Separate alpha ---
        alpha: np.ndarray | None = None
        if image.ndim == 3 and image.shape[2] == 4:
            alpha = image[:, :, 3].copy()
            image = image[:, :, :3]

        # --- Analyse image ---
        params = self._analyse(image, mode)

        # --- Upscale ---
        if settings.get("upscale", True):
            image = self._upscale(image, params)

        # --- Denoise ---
        if settings.get("denoise", True) and params["denoise"]:
            image = self._denoise(image, params)

        # --- Bilateral filter ---
        if settings.get("bilateral", True) and params["bilateral"]:
            image = self._bilateral(image, params)

        # --- CLAHE ---
        if settings.get("clahe", True) and params["clahe"]:
            image = self._clahe(image, params)

        # --- Sharpen ---
        if settings.get("sharpen", True) and params["sharpen"]:
            image = self._sharpen(image, params)

        # --- Re-apply alpha (upscaled if needed) ---
        if alpha is not None:
            h, w = image.shape[:2]
            alpha_resized = cv2.resize(alpha, (w, h), interpolation=cv2.INTER_LANCZOS4)
            image = cv2.merge([image[:, :, 0], image[:, :, 1], image[:, :, 2], alpha_resized])

        return image

    # ------------------------------------------------------------------ #
    #  Analysis                                                            #
    # ------------------------------------------------------------------ #

    def _analyse(self, image: np.ndarray, mode: str) -> dict:
        """Derive adaptive parameters from the image and chosen mode."""
        h, w = image.shape[:2]
        longest = max(h, w)

        # Compute noise estimate from high-frequency content
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        # Lower variance ⇒ blurry / smooth; higher ⇒ noisy / detailed

        # Color diversity (rough)
        unique_ratio = np.unique(gray).size / 256.0

        # Edge density
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(edges.sum() / 255) / (h * w)

        # --- Decide per-step parameters ---
        # Upscale factor
        if longest < 200:
            scale = 4
        elif longest < 500:
            scale = 3
        elif longest < 1000:
            scale = 2
        else:
            scale = 1

        # Mode overrides
        if mode == "pixel_art":
            # pixel art: no denoising, no blur, hard upscale with NEAREST
            return dict(
                scale=scale, interp=cv2.INTER_NEAREST,
                denoise=False, bilateral=False, clahe=False, sharpen=False,
                h_lum=5, template_window=7, search_window=21,
                bilateral_d=5, bilateral_sigma_color=50, bilateral_sigma_space=50,
                clahe_clip=2.0, clahe_grid=(8, 8),
                sharpen_amount=0.5,
            )

        if mode == "line_art":
            scale = scale if scale > 1 else 1
            return dict(
                scale=scale, interp=cv2.INTER_LANCZOS4,
                denoise=True, bilateral=False, clahe=True, sharpen=True,
                h_lum=4, template_window=7, search_window=21,
                bilateral_d=7, bilateral_sigma_color=75, bilateral_sigma_space=75,
                clahe_clip=3.0, clahe_grid=(8, 8),
                sharpen_amount=1.5,
            )

        if mode == "logo":
            return dict(
                scale=scale, interp=cv2.INTER_LANCZOS4,
                denoise=True, bilateral=True, clahe=True, sharpen=True,
                h_lum=5, template_window=7, search_window=21,
                bilateral_d=9, bilateral_sigma_color=75, bilateral_sigma_space=75,
                clahe_clip=2.0, clahe_grid=(8, 8),
                sharpen_amount=0.8,
            )

        # photo / auto – adaptive
        noise_level = laplacian_var
        heavy_noise = noise_level > 500
        low_contrast = unique_ratio < 0.3

        h_lum = 10 if heavy_noise else 6
        bilateral_sigma = 100 if heavy_noise else 75

        return dict(
            scale=scale, interp=cv2.INTER_LANCZOS4,
            denoise=heavy_noise or mode == "photo",
            bilateral=True,
            clahe=low_contrast or mode == "photo",
            sharpen=True,
            h_lum=h_lum, template_window=7, search_window=21,
            bilateral_d=9,
            bilateral_sigma_color=bilateral_sigma,
            bilateral_sigma_space=bilateral_sigma,
            clahe_clip=2.0, clahe_grid=(8, 8),
            sharpen_amount=1.0,
        )

    # ------------------------------------------------------------------ #
    #  Pipeline steps                                                      #
    # ------------------------------------------------------------------ #

    def _upscale(self, image: np.ndarray, params: dict) -> np.ndarray:
        scale = params["scale"]
        if scale <= 1:
            return image
        h, w = image.shape[:2]
        interp = params.get("interp", cv2.INTER_LANCZOS4)
        return cv2.resize(image, (w * scale, h * scale), interpolation=interp)

    def _denoise(self, image: np.ndarray, params: dict) -> np.ndarray:
        try:
            return cv2.fastNlMeansDenoisingColored(
                image,
                None,
                h=params["h_lum"],
                hColor=params["h_lum"],
                templateWindowSize=params["template_window"],
                searchWindowSize=params["search_window"],
            )
        except cv2.error:
            return image

    def _bilateral(self, image: np.ndarray, params: dict) -> np.ndarray:
        try:
            return cv2.bilateralFilter(
                image,
                d=params["bilateral_d"],
                sigmaColor=params["bilateral_sigma_color"],
                sigmaSpace=params["bilateral_sigma_space"],
            )
        except cv2.error:
            return image

    def _clahe(self, image: np.ndarray, params: dict) -> np.ndarray:
        try:
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l_ch, a_ch, b_ch = cv2.split(lab)
            clahe = cv2.createCLAHE(
                clipLimit=params["clahe_clip"],
                tileGridSize=params["clahe_grid"],
            )
            l_ch = clahe.apply(l_ch)
            lab = cv2.merge([l_ch, a_ch, b_ch])
            return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        except cv2.error:
            return image

    def _sharpen(self, image: np.ndarray, params: dict) -> np.ndarray:
        """Unsharp mask sharpening."""
        amount = params.get("sharpen_amount", 1.0)
        sigma = 1.0
        blurred = cv2.GaussianBlur(image, (0, 0), sigma)
        # unsharp mask: sharpened = original + amount * (original - blurred)
        sharpened = cv2.addWeighted(image, 1.0 + amount, blurred, -amount, 0)
        return np.clip(sharpened, 0, 255).astype(np.uint8)
