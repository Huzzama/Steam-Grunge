import numpy as np
from PIL import Image


def apply_chromatic_aberration(img: Image.Image, intensity: float) -> Image.Image:
    """Shift RGB channels slightly. intensity 0-100."""
    if intensity <= 0:
        return img
    arr = np.array(img.convert("RGB"))
    shift = max(1, int(intensity * 0.08))

    r = np.roll(arr[:, :, 0], shift, axis=1)
    g = arr[:, :, 1]
    b = np.roll(arr[:, :, 2], -shift, axis=1)

    result = np.stack([r, g, b], axis=2).astype(np.uint8)
    return Image.fromarray(result).convert(img.mode)


def apply_scanlines(img: Image.Image, intensity: float) -> Image.Image:
    """Add horizontal scanlines. intensity 0-100."""
    if intensity <= 0:
        return img
    result = img.copy().convert("RGBA")
    arr = np.array(result, dtype=np.float32)
    h, w = arr.shape[:2]
    alpha = intensity / 100.0

    for y in range(0, h, 3):
        arr[y, :, :3] *= (1.0 - alpha * 0.5)

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert(img.mode)


def apply_vhs_noise(img: Image.Image, intensity: float) -> Image.Image:
    """Add VHS-style horizontal noise banding. intensity 0-100."""
    if intensity <= 0:
        return img
    arr = np.array(img.convert("RGB"), dtype=np.float32)
    h, w = arr.shape[:2]
    count = int(intensity * 0.1)

    for _ in range(count):
        y = np.random.randint(0, h)
        band_h = np.random.randint(1, 4)
        shift = np.random.randint(-8, 8)
        band = arr[y:y+band_h, :, :]
        arr[y:y+band_h, :, :] = np.roll(band, shift, axis=1)

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert(img.mode)