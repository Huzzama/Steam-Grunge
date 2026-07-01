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


def export_image(img: Image.Image, template: str, game_name: str = "untitled",
                 app_id: int = None) -> str:
    """
    Export the composed image to the correct exports sub-folder.
    Logo and icon templates are saved as RGBA PNGs (transparent background).
    All others are saved as RGB PNGs.
    Returns the saved file path.

    Filename convention:
      With app_id (preferred):  {appid}.png / {appid}p.png / {appid}_hero.png etc.
      Without app_id (fallback): GameName_template_YYYYMMDD_HHMMSS.png
    """
    folder = _FOLDER_MAP.get(template, EXPORT_COVER)

    if app_id is not None:
        # Use the canonical Steam filename — matches what steamSync expects
        # and avoids accumulating GameName_timestamp_... legacy files.
        _SUFFIX = {
            "cover":        f"{app_id}.png",
            "vhs_cover":    f"{app_id}.png",
            "wide":         f"{app_id}p.png",
            "vhs_pile":     f"{app_id}p.png",
            "vhs_cassette": f"{app_id}p.png",
            "hero":         f"{app_id}_hero.png",
            "logo":         f"{app_id}_logo.png",
            "icon":         f"{app_id}_icon.png",
        }
        filename = _SUFFIX.get(template, f"{app_id}.png")
    else:
        # Fallback for when app_id is not yet confirmed
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in game_name)
        safe_name = safe_name.strip().replace(" ", "_") or "untitled"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename  = f"{safe_name}_{template}_{timestamp}.png"

    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, filename)

    # Transparent templates keep RGBA so the background stays see-through
    if template in TRANSPARENT_TEMPLATES:
        out_img = img.convert("RGBA")
    else:
        out_img = img.convert("RGB")

    out_img.save(out_path, "PNG")
    return out_path