from PIL import Image, ImageDraw, ImageFont
import os

from app.config import (
    COVER_SIZE, WIDE_SIZE, COVER_SPINE_WIDTH, COVER_PLATFORM_BAR_HEIGHT,
    PLATFORM_BARS_DIR, FONTS_DIR, TEMPLATES_DIR
)
from app.filters import color as color_filters, vhs as vhs_filters



def _find_font(font_name: str, font_size: int) -> ImageFont.ImageFont:
    """Load font by name from assets/fonts directory, fallback to default."""
    try:
        if font_name and font_name != "default":
            font_path = os.path.join(FONTS_DIR, font_name)
            if not font_path.endswith((".ttf", ".otf")):
                # Try common extensions
                for ext in (".ttf", ".otf", ".TTF", ".OTF"):
                    candidate = font_path + ext
                    if os.path.exists(candidate):
                        font_path = candidate
                        break
            if os.path.exists(font_path):
                return ImageFont.truetype(font_path, font_size)
            # Search recursively in FONTS_DIR
            for root, _, files in os.walk(FONTS_DIR):
                for f in files:
                    if f.lower().startswith(font_name.lower().split(".")[0]) and                        f.lower().endswith((".ttf", ".otf")):
                        return ImageFont.truetype(os.path.join(root, f), font_size)
    except Exception:
        pass
    try:
        return ImageFont.load_default(size=font_size)
    except Exception:
        return ImageFont.load_default()


def _render_text_layer(img: Image.Image, layer, doc_size: tuple) -> Image.Image:
    """Render a text layer onto img using PIL, matching Qt canvas position/style."""
    from PIL import ImageFilter
    import math

    text = layer.text
    if not text:
        return img

    if layer.font_uppercase:
        text = text.upper()

    doc_w, doc_h = doc_size
    img_w, img_h = img.size

    # Scale factor from doc coords to export coords
    sx = img_w / doc_w if doc_w else 1.0
    sy = img_h / doc_h if doc_h else 1.0

    font_size  = max(4, int(layer.font_size * min(sx, sy)))
    font       = _find_font(layer.font_name, font_size)
    color_rgba = (*layer.font_color, 255)

    # Create text layer at document size then scale
    txt_layer  = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw       = ImageDraw.Draw(txt_layer)

    # Scaled position and bounds
    x  = int(layer.x * sx)
    y  = int(layer.y * sy)
    lw = int(layer.w * sx)
    lh = int(layer.h * sy)

    # Letter spacing via manual char drawing
    def draw_spaced(d, pos, txt, fnt, fill, spacing=0):
        cx, cy = pos
        for ch in txt:
            d.text((cx, cy), ch, font=fnt, fill=fill)
            bbox = fnt.getbbox(ch)
            cx += (bbox[2] - bbox[0]) + spacing
        return cx

    # Shadow
    if layer.shadow_offset > 0:
        so = int(layer.shadow_offset * min(sx, sy))
        shadow_fill = (*layer.shadow_color, 180)
        if layer.letter_spacing:
            draw_spaced(draw, (x + so, y + so), text, font,
                        shadow_fill, int(layer.letter_spacing * sx))
        else:
            draw.text((x + so, y + so), text, font=font, fill=shadow_fill)

    # Outline
    if layer.outline_size > 0:
        os_ = max(1, int(layer.outline_size * min(sx, sy)))
        outline_fill = (*layer.outline_color, 255)
        for dx in range(-os_, os_ + 1):
            for dy in range(-os_, os_ + 1):
                if dx == 0 and dy == 0:
                    continue
                if layer.letter_spacing:
                    draw_spaced(draw, (x + dx, y + dy), text, font,
                                outline_fill, int(layer.letter_spacing * sx))
                else:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline_fill)

    # Main text
    if layer.letter_spacing:
        draw_spaced(draw, (x, y), text, font, color_rgba,
                    int(layer.letter_spacing * sx))
    else:
        draw.text((x, y), text, font=font, fill=color_rgba)

    # Rotation
    angle = 0
    if layer.text_orientation == "rotate90":
        angle = -90
    elif layer.text_orientation == "rotate270":
        angle = 90
    elif layer.text_orientation == "vertical":
        angle = -90

    if angle != 0:
        txt_layer = txt_layer.rotate(angle, expand=False, center=(x + lw//2, y + lh//2))

    # Opacity
    if layer.opacity < 1.0:
        r, g, b, a = txt_layer.split()
        a = a.point(lambda v: int(v * layer.opacity))
        txt_layer = Image.merge("RGBA", (r, g, b, a))

    img = img.convert("RGBA")
    img = Image.alpha_composite(img, txt_layer)
    return img.convert("RGB")


def _render_image_layer(img: Image.Image, layer, doc_size: tuple) -> Image.Image:
    """Render an image/texture layer onto img."""
    if layer.pil_image is None:
        return img

    doc_w, doc_h = doc_size
    img_w, img_h = img.size
    sx = img_w / doc_w if doc_w else 1.0
    sy = img_h / doc_h if doc_h else 1.0

    try:
        lx = int(layer.x * sx)
        ly = int(layer.y * sy)
        lw = max(1, int(layer.w * sx))
        lh = max(1, int(layer.h * sy))

        src = layer.pil_image.copy().convert("RGBA")
        src = src.resize((lw, lh), Image.LANCZOS)

        if layer.flip_h:
            src = src.transpose(Image.FLIP_LEFT_RIGHT)
        if layer.flip_v:
            src = src.transpose(Image.FLIP_TOP_BOTTOM)
        if layer.rotation:
            src = src.rotate(-layer.rotation, expand=True, resample=Image.BICUBIC)

        if layer.opacity < 1.0:
            r, g, b, a = src.split()
            a = a.point(lambda v: int(v * layer.opacity))
            src = Image.merge("RGBA", (r, g, b, a))

        canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
        canvas.paste(src, (lx, ly), src)

        img = img.convert("RGBA")
        img = Image.alpha_composite(img, canvas)
        return img.convert("RGB")
    except Exception as e:
        print(f"[Compositor] Image layer error: {e}")
        return img


def compose(state) -> Image.Image:
    """
    Full composition pipeline — renders all layers including text.
    Matches what the Qt canvas shows.
    """
    size = COVER_SIZE if state.current_template == "cover" else WIDE_SIZE

    # Doc size = canvas size at editing resolution
    doc_w = getattr(state, "canvas_width",  size[0])
    doc_h = getattr(state, "canvas_height", size[1])
    doc_size = (doc_w, doc_h)

    # 1. Background
    bg  = getattr(state, "bg_color", (0, 0, 0))
    img = Image.new("RGB", size, bg)

    # 2. Template base PNG
    tpl_path = os.path.join(TEMPLATES_DIR, f"template_{state.current_template}.png")
    if os.path.exists(tpl_path):
        tpl = Image.open(tpl_path).convert("RGBA").resize(size, Image.LANCZOS)
        img = img.convert("RGBA")
        img = Image.alpha_composite(img, tpl).convert("RGB")

    # 3. Base artwork
    if state.base_image:
        art = state.base_image.copy().convert("RGB").resize(size, Image.LANCZOS)
        img = Image.blend(img, art, alpha=1.0)

    # 4. Color adjustments on base
    img = color_filters.apply_brightness(img, state.brightness)
    img = color_filters.apply_contrast(img, state.contrast)
    img = color_filters.apply_saturation(img, state.saturation)

    # 5. Render layers (bottom to top, respecting visibility)
    layers = getattr(state, "layers", [])
    for layer in reversed(layers):  # layers list is top-to-bottom, render bottom-first
        if not layer.visible:
            continue
        if layer.kind in ("image", "texture", "file", "paint"):
            img = _render_image_layer(img, layer, doc_size)
        elif layer.kind == "text":
            img = _render_text_layer(img, layer, doc_size)

    # 6. VHS effects on top
    img = vhs_filters.apply_chromatic_aberration(img, state.chromatic_aberration)
    img = vhs_filters.apply_scanlines(img, state.vhs_scanlines)

    return img