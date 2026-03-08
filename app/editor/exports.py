import os
from PIL import Image
from datetime import datetime
from app.config import (
    EXPORT_COVER, EXPORT_WIDE, EXPORT_HERO, EXPORT_LOGO, EXPORT_ICON,
    TRANSPARENT_TEMPLATES,
)

# Map template name → export folder
_FOLDER_MAP = {
    "cover":     EXPORT_COVER,
    "vhs_cover": EXPORT_COVER,
    "wide":      EXPORT_WIDE,
    "hero":      EXPORT_HERO,
    "logo":      EXPORT_LOGO,
    "icon":      EXPORT_ICON,
}


def export_image(img: Image.Image, template: str, game_name: str = "untitled") -> str:
    """
    Export the composed image to the correct exports sub-folder.
    Logo and icon templates are saved as RGBA PNGs (transparent background).
    All others are saved as RGB PNGs.
    Returns the saved file path.
    """
    folder = _FOLDER_MAP.get(template, EXPORT_COVER)
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in game_name)
    safe_name = safe_name.strip().replace(" ", "_") or "untitled"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"{safe_name}_{template}_{timestamp}.png"
    out_path  = os.path.join(folder, filename)

    # Transparent templates keep RGBA so the background stays see-through
    if template in TRANSPARENT_TEMPLATES:
        out_img = img.convert("RGBA")
    else:
        out_img = img.convert("RGB")

    out_img.save(out_path, "PNG")
    return out_path