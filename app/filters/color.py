from PIL import Image, ImageEnhance, ImageFilter
import numpy as np


def apply_brightness(img: Image.Image, value: float) -> Image.Image:
    """value 0-100, 50 = neutral."""
    factor = value / 50.0
    return ImageEnhance.Brightness(img).enhance(factor)


def apply_contrast(img: Image.Image, value: float) -> Image.Image:
    """value 0-100, 50 = neutral."""
    factor = value / 50.0
    return ImageEnhance.Contrast(img).enhance(factor)


def apply_saturation(img: Image.Image, value: float) -> Image.Image:
    """value 0-100, 50 = neutral."""
    factor = value / 50.0
    return ImageEnhance.Color(img).enhance(factor)


def apply_tint(img: Image.Image, color: tuple, strength: float = 0.15) -> Image.Image:
    """Overlay a color tint. color = (r,g,b)."""
    tint = Image.new("RGB", img.size, color)
    return Image.blend(img.convert("RGB"), tint, strength)