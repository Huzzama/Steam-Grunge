from PIL import Image, ImageDraw, ImageFont
import os

from app.config import (
    COVER_SIZE, WIDE_SIZE, COVER_SPINE_WIDTH, COVER_PLATFORM_BAR_HEIGHT,
    PLATFORM_BARS_DIR, FONTS_DIR, TEMPLATES_DIR
)
from app.filters import color as color_filters, vhs as vhs_filters
from app.filters.distressed import apply_film_grain


def compose(state) -> Image.Image:
    """
    Composition pipeline.
    Scratches / dust / edge-wear removed — those are now texture layers.
    """
    size = COVER_SIZE if state.current_template == "cover" else WIDE_SIZE

    # 1. Solid background color from state (default black)
    bg = getattr(state, 'bg_color', (0, 0, 0))
    img = Image.new("RGB", size, bg)

    # 2. Template base PNG (non-layer, always at bottom)
    tpl_path = os.path.join(TEMPLATES_DIR, f"template_{state.current_template}.png")
    if os.path.exists(tpl_path):
        tpl = Image.open(tpl_path).convert("RGBA").resize(size, Image.LANCZOS)
        img = img.convert("RGBA")
        img = Image.alpha_composite(img, tpl).convert("RGB")

    # 3. Base artwork (if set)
    if state.base_image:
        art = state.base_image.copy().convert("RGB").resize(size, Image.LANCZOS)
        img = Image.blend(img, art, alpha=1.0)

    # 4. Color adjustments
    img = color_filters.apply_brightness(img, state.brightness)
    img = color_filters.apply_contrast(img, state.contrast)
    img = color_filters.apply_saturation(img, state.saturation)

    # 5. Film grain only (scratches/dust/edge removed)
    img = apply_film_grain(img, state.film_grain)

    # 6. VHS effects
    img = vhs_filters.apply_chromatic_aberration(img, state.chromatic_aberration)
    img = vhs_filters.apply_scanlines(img, state.vhs_scanlines)

    return img