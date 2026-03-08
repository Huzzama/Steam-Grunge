"""
canvas/fx.py  —  Global post-processing effects for the canvas.

Functions:
  apply_film_grain(arr, strength)           — numpy RGBA array → numpy RGBA array
  apply_chromatic_aberration(arr, strength) — numpy RGBA array → numpy RGBA array
  qpixmap_to_pil(pix)                       — QPixmap → PIL Image (no file I/O)
  build_fx_composite(canvas)                — renders full scene + applies effects,
                                              returns a QPixmap ready to draw
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import io
import numpy as np
from PIL import Image as PILImage

from PySide6.QtGui import QPixmap, QImage

if TYPE_CHECKING:
    from app.ui.canvas.previewCanvas import PreviewCanvas


# ── QPixmap → PIL (zero file I/O, uses numpy shared memory) ───────────────────
def qpixmap_to_pil(pix: QPixmap) -> PILImage.Image:
    """Convert a QPixmap to a PIL Image via numpy — no BytesIO / disk I/O needed."""
    img = pix.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    ptr  = img.bits()
    arr  = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 4)).copy()
    return PILImage.fromarray(arr, "RGBA")


# ── PIL Image → QPixmap ────────────────────────────────────────────────────────
def pil_to_qpixmap(img: PILImage.Image) -> QPixmap:
    """Convert a PIL Image to a QPixmap via BytesIO."""
    buf = io.BytesIO()
    img.save(buf, "PNG")
    pix = QPixmap()
    pix.loadFromData(buf.getvalue())
    return pix


# ── Individual effect processors ──────────────────────────────────────────────
def apply_film_grain(arr: np.ndarray, strength: float) -> np.ndarray:
    """Add luminance-based random noise to an RGBA numpy float32 array."""
    if strength <= 0:
        return arr
    sigma = strength * 0.35          # 0–100 → 0–35 std-dev
    h, w  = arr.shape[:2]
    noise = np.random.normal(0, sigma, (h, w)).astype(np.float32)
    for c in range(3):               # R, G, B — leave alpha untouched
        arr[:, :, c] = np.clip(arr[:, :, c] + noise, 0, 255)
    return arr


def apply_chromatic_aberration(arr: np.ndarray, strength: float) -> np.ndarray:
    """Shift R and B channels horizontally in opposite directions (classic CA)."""
    if strength <= 0:
        return arr
    shift = max(1, int(strength * 0.15))   # 0–100 → 0–15 px
    arr[:, :, 0] = np.roll(arr[:, :, 0],  shift, axis=1)   # R → right
    arr[:, :, 2] = np.roll(arr[:, :, 2], -shift, axis=1)   # B → left
    # Black out wrapped border columns to avoid roll artefacts
    arr[:, :shift,  0] = 0
    arr[:, -shift:, 2] = 0
    return arr


# ── Full scene compositor with effects ────────────────────────────────────────
def build_fx_composite(canvas: "PreviewCanvas") -> QPixmap:
    """
    Render the entire canvas scene (bg color + template + bg overlay + all
    visible layers) into a doc-resolution PIL image, apply Film Grain and
    Chromatic Aberration, then return the result as a QPixmap.

    Called by PreviewCanvas._draw_with_global_fx() and compose_to_pil().
    """
    dw = canvas._doc_size.width()
    dh = canvas._doc_size.height()

    # 1. Solid background (or transparent for logo/icon templates)
    r, g, b = (canvas._bg_color.red(),
                canvas._bg_color.green(),
                canvas._bg_color.blue())
    if getattr(canvas, "_transparent_bg", False):
        comp = PILImage.new("RGBA", (dw, dh), (0, 0, 0, 0))
    else:
        comp = PILImage.new("RGBA", (dw, dh), (r, g, b, 255))

    # 2. Template PNG overlay
    if canvas._template_pix and not canvas._template_pix.isNull():
        tpl = qpixmap_to_pil(canvas._template_pix).convert("RGBA").resize(
            (dw, dh), PILImage.LANCZOS)
        comp = PILImage.alpha_composite(comp, tpl)

    # 3. Filter-composed background overlay
    if canvas._bg_pix and not canvas._bg_pix.isNull():
        bg = qpixmap_to_pil(canvas._bg_pix).convert("RGBA").resize(
            (dw, dh), PILImage.LANCZOS)
        comp = PILImage.alpha_composite(comp, bg)

    # 4. All visible layers
    for layer in canvas._layers:
        if not layer.visible or layer.kind == "group":
            continue
        if layer.is_image_like and layer.pil_image:
            try:
                img = layer.pil_image.convert("RGBA").resize(
                    (max(1, layer.w), max(1, layer.h)), PILImage.LANCZOS)
                if layer.opacity < 1.0:
                    a = img.split()[3].point(lambda px: int(px * layer.opacity))
                    img.putalpha(a)
                tmp = PILImage.new("RGBA", (dw, dh), (0, 0, 0, 0))
                tmp.paste(img, (layer.x, layer.y), img)
                comp = PILImage.alpha_composite(comp, tmp)
            except Exception:
                pass

    # 5. Apply global effects on the full composite
    arr = np.array(comp, dtype=np.float32)
    arr = apply_film_grain(arr, getattr(canvas, "_effects_grain", 0))
    arr = apply_chromatic_aberration(arr, getattr(canvas, "_effects_ca", 0))
    comp = PILImage.fromarray(arr.clip(0, 255).astype(np.uint8), "RGBA")

    return pil_to_qpixmap(comp)