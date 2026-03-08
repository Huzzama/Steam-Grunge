import numpy as np
from PIL import Image, ImageFilter, ImageDraw
import random


def apply_film_grain(img: Image.Image, intensity: float) -> Image.Image:
    """Add film grain noise. intensity 0-100."""
    if intensity <= 0:
        return img
    arr = np.array(img, dtype=np.float32)
    sigma = intensity * 0.25
    noise = np.random.normal(0, sigma, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def apply_scratches(img: Image.Image, intensity: float) -> Image.Image:
    """Draw vertical scratch lines. intensity 0-100."""
    if intensity <= 0:
        return img
    result = img.copy().convert("RGBA")
    draw = ImageDraw.Draw(result)
    w, h = img.size
    count = int(intensity * 0.3)
    for _ in range(count):
        x = random.randint(0, w)
        alpha = random.randint(40, 140)
        thickness = random.choice([1, 1, 1, 2])
        length = random.randint(h // 4, h)
        y_start = random.randint(0, h - length)
        color = (220, 210, 200, alpha)
        draw.line([(x, y_start), (x, y_start + length)], fill=color, width=thickness)
    return result.convert(img.mode)


def apply_dust(img: Image.Image, intensity: float) -> Image.Image:
    """Add dust particle spots. intensity 0-100."""
    if intensity <= 0:
        return img
    result = img.copy().convert("RGBA")
    draw = ImageDraw.Draw(result)
    w, h = img.size
    count = int(intensity * 2)
    for _ in range(count):
        x = random.randint(0, w)
        y = random.randint(0, h)
        r = random.randint(1, 3)
        alpha = random.randint(60, 180)
        color = (200, 195, 185, alpha)
        draw.ellipse([(x - r, y - r), (x + r, y + r)], fill=color)
    return result.convert(img.mode)


def apply_edge_wear(img: Image.Image, intensity: float) -> Image.Image:
    """Darken and roughen edges. intensity 0-100."""
    if intensity <= 0:
        return img
    result = img.copy().convert("RGBA")
    w, h = img.size
    arr = np.array(result, dtype=np.float32)
    factor = intensity / 100.0

    # Create vignette-style edge mask
    cx, cy = w / 2, h / 2
    y_coords, x_coords = np.mgrid[0:h, 0:w]
    dist = np.sqrt(((x_coords - cx) / cx) ** 2 + ((y_coords - cy) / cy) ** 2)
    vignette = np.clip(1.0 - dist * factor * 0.8, 0, 1)

    for c in range(3):
        arr[:, :, c] *= vignette

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert(img.mode)


def apply_paper_texture(img: Image.Image, intensity: float) -> Image.Image:
    """Overlay subtle paper texture. intensity 0-100."""
    if intensity <= 0:
        return img
    w, h = img.size
    arr = np.array(img.convert("RGBA"), dtype=np.float32)

    # Procedural paper noise
    noise = np.random.uniform(0.85, 1.0, (h, w))
    noise = Image.fromarray((noise * 255).astype(np.uint8), "L")
    noise = noise.filter(ImageFilter.GaussianBlur(1))
    noise_arr = np.array(noise, dtype=np.float32) / 255.0

    blend = intensity / 100.0
    for c in range(3):
        arr[:, :, c] = arr[:, :, c] * (1 - blend * 0.3 + noise_arr * blend * 0.3)

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert(img.mode)


DETERIORATION_PRESETS = {
    "none":         {"scratches": 0,  "dust": 0,  "film_grain": 0,  "edge_wear": 0},
    "light":        {"scratches": 15, "dust": 10, "film_grain": 15, "edge_wear": 10},
    "medium":       {"scratches": 35, "dust": 25, "film_grain": 30, "edge_wear": 30},
    "heavy":        {"scratches": 65, "dust": 50, "film_grain": 55, "edge_wear": 55},
    "destroyed":    {"scratches": 90, "dust": 80, "film_grain": 80, "edge_wear": 80},
    "silent_hill":  {"scratches": 50, "dust": 40, "film_grain": 60, "edge_wear": 45},
    "vhs_tape":     {"scratches": 70, "dust": 30, "film_grain": 70, "edge_wear": 20},
}