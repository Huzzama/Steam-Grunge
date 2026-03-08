"""
brushImporter.py  —  GIMP brush parser + thumbnail cache + ZIP importer.

Supported formats:
  .gbr  — GIMP Brush raster (v1 and v2, 1/2/3/4 bpp)
  .gih  — GIMP Image Hose (multi-cell; extracts first cell)
  .vbr  — GIMP Parametric Brush (rendered from INI params)
  .png / .jpg / .jpeg — plain image brushes

Thumbnail cache:
  Parsed previews are saved as small PNGs in BRUSHES_DIR/.cache/<sha1>.png.
  The cache key combines file path + mtime so stale entries are automatically
  bypassed on next access.

Key public API:
  load_brush_preview(path, thumb_size, use_cache, bg_mode) -> PILImage
      Always returns a usable image — never None, never silent blank.
  make_fallback_thumb(path, size) -> PILImage
      Readable "GBR" / "GIH" badge tile used when parsing fails.
  import_zip(zip_path, progress_cb) -> BrushImportResult
  run_zip_import_dialog(parent) -> BrushImportResult | None
"""
from __future__ import annotations
import os, io, zipfile, shutil, struct, tempfile, hashlib, logging
import numpy as np
from PIL import Image as PILImage

from app.config import ASSETS_DIR

log = logging.getLogger(__name__)

BRUSHES_DIR = os.path.join(ASSETS_DIR, "brushes")
CACHE_DIR   = os.path.join(BRUSHES_DIR, ".cache")
VALID_EXTS  = {".gbr", ".gih", ".vbr", ".png", ".jpg", ".jpeg"}


# ── Thumbnail cache ───────────────────────────────────────────────────────────

def _cache_key(path: str) -> str:
    try:    mtime = str(os.path.getmtime(path))
    except  OSError: mtime = "0"
    raw = (os.path.abspath(path) + mtime).encode()
    return hashlib.sha1(raw).hexdigest()

def _cache_path(path: str) -> str:
    return os.path.join(CACHE_DIR, _cache_key(path) + ".png")

def get_cached_thumb(path: str) -> PILImage.Image | None:
    cp = _cache_path(path)
    try:
        if os.path.exists(cp):
            return PILImage.open(cp).convert("RGBA")
    except Exception as e:
        log.debug("cache read failed %s: %s", cp, e)
    return None

def save_cached_thumb(path: str, img: PILImage.Image) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        img.save(_cache_path(path), "PNG")
    except Exception as e:
        log.debug("cache write failed %s: %s", path, e)


# ── Format parsers ────────────────────────────────────────────────────────────

def parse_gbr(path: str) -> PILImage.Image | None:
    """
    GIMP Brush v1/v2 binary format.
    Header (big-endian uint32 each):
      header_size | version | width | height | bytes_per_pixel
    Pixel data starts at offset = header_size.
    Supported bpp: 1 (gray mask), 2 (gray+alpha), 3 (RGB), 4 (RGBA).
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()

        if len(raw) < 20:
            log.debug("parse_gbr: %s too short", path)
            return None

        hdr_size, version, w, h, bpp = struct.unpack_from(">IIIII", raw, 0)

        if not (1 <= w <= 4096 and 1 <= h <= 4096):
            log.debug("parse_gbr: %s bad dims %dx%d", path, w, h)
            return None
        if bpp not in (1, 2, 3, 4):
            log.debug("parse_gbr: %s unsupported bpp=%d", path, bpp)
            return None
        if hdr_size > len(raw):
            log.debug("parse_gbr: %s hdr_size %d > file len", path, hdr_size)
            return None

        pixels   = raw[hdr_size:]
        expected = w * h * bpp

        # Pad short data rather than failing outright
        if len(pixels) < expected:
            if len(pixels) < w * bpp:
                log.debug("parse_gbr: %s insufficient data (%d < %d)",
                          path, len(pixels), expected)
                return None
            pixels = pixels + bytes(expected - len(pixels))
            log.debug("parse_gbr: %s padded short data", path)

        arr = np.frombuffer(pixels[:expected], np.uint8)

        if bpp == 1:
            a2d = arr.reshape((h, w))
            # GIMP bpp=1: the byte value IS opacity (0=transparent, 255=fully opaque).
            # White pixels in the brush = fully opaque mark. No inversion needed.
            g = PILImage.fromarray(a2d, "L")
            return PILImage.merge("RGBA", (g, g, g, g))
        elif bpp == 2:
            a3d = arr.reshape((h, w, 2))
            gray, alpha = a3d[:,:,0], a3d[:,:,1]
            g_ch = PILImage.fromarray(gray,  "L")
            a_ch = PILImage.fromarray(alpha, "L")
            return PILImage.merge("RGBA", (g_ch, g_ch, g_ch, a_ch))
        elif bpp == 3:
            return PILImage.fromarray(arr.reshape((h, w, 3)), "RGB").convert("RGBA")
        else:  # bpp == 4
            return PILImage.fromarray(arr.reshape((h, w, 4)), "RGBA")

    except Exception as e:
        log.warning("parse_gbr failed %s: %s", path, e)
        return None


def parse_gih(path: str) -> PILImage.Image | None:
    """
    GIMP Image Hose (.gih) — two text header lines followed by a sequence of
    embedded GBR-format brush blocks (one per cell).

    Real GIH format:
      Line 1:  brush name  (arbitrary text)
      Line 2:  "<spacing> ncells:<N> cellwidth:<W> cellheight:<H> dim:<D> ..."
      Remainder: N back-to-back GBR binary blocks.

    Each GBR block starts with a 20-byte binary header (same as parse_gbr):
      header_size | version | width | height | bpp  (5 × uint32 big-endian)
    followed by optional name bytes up to header_size, then pixel data.

    We extract the first cell only and return its image.

    Fallback: if the embedded data doesn't parse as GBR (old flat format),
    we attempt to read it as raw 1-bpp or 4-bpp pixel data using cellwidth/
    cellheight from the header line.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()

        try:
            nl1 = raw.index(b"\n")
            nl2 = raw.index(b"\n", nl1 + 1)
        except ValueError:
            log.debug("parse_gih: %s missing header newlines", path)
            return None

        params_line = raw[nl1 + 1: nl2].decode("ascii", errors="ignore").strip()
        cell_data   = raw[nl2 + 1:]

        # Parse header params
        cw = ch = 64
        for tok in params_line.split():
            k, _, v = tok.partition(":")
            try:
                if k == "cellwidth":    cw = max(1, min(int(v), 2048))
                elif k == "cellheight": ch = max(1, min(int(v), 2048))
            except ValueError:
                pass

        # ── Try reading the first embedded GBR block ──────────────────────
        # Each cell is a complete GBR file embedded back-to-back.
        if len(cell_data) >= 20:
            try:
                hdr_size, version, w, h, bpp = struct.unpack_from(">IIIII", cell_data, 0)
                if (1 <= w <= 4096 and 1 <= h <= 4096
                        and bpp in (1, 2, 3, 4)
                        and hdr_size <= len(cell_data)):
                    pixels   = cell_data[hdr_size:]
                    expected = w * h * bpp
                    if len(pixels) < w * bpp:
                        raise ValueError("insufficient GBR pixel data")
                    if len(pixels) < expected:
                        pixels = pixels + bytes(expected - len(pixels))
                    arr = np.frombuffer(pixels[:expected], np.uint8)
                    if bpp == 1:
                        a2d = arr.reshape((h, w))
                        # Value IS opacity (white=opaque), no inversion
                        g   = PILImage.fromarray(a2d, "L")
                        img = PILImage.merge("RGBA", (g, g, g, g))
                    elif bpp == 2:
                        a3d  = arr.reshape((h, w, 2))
                        g_ch = PILImage.fromarray(a3d[:,:,0], "L")
                        a_ch = PILImage.fromarray(a3d[:,:,1], "L")
                        img  = PILImage.merge("RGBA", (g_ch, g_ch, g_ch, a_ch))
                    elif bpp == 3:
                        img = PILImage.fromarray(arr.reshape((h, w, 3)), "RGB").convert("RGBA")
                    else:
                        img = PILImage.fromarray(arr.reshape((h, w, 4)), "RGBA")
                    log.debug("parse_gih: %s first cell %dx%d bpp=%d via GBR", path, w, h, bpp)
                    return img
            except Exception as e2:
                log.debug("parse_gih: %s GBR-in-GIH parse failed: %s", path, e2)

        # ── Fallback: try flat raw pixel block (old/non-standard format) ──
        exp_rgba = cw * ch * 4
        exp_gray = cw * ch

        if len(cell_data) >= exp_rgba:
            arr = np.frombuffer(cell_data[:exp_rgba], np.uint8).reshape((ch, cw, 4))
            log.debug("parse_gih: %s flat RGBA %dx%d", path, cw, ch)
            return PILImage.fromarray(arr, "RGBA")

        if len(cell_data) >= exp_gray:
            arr  = np.frombuffer(cell_data[:exp_gray], np.uint8).reshape((ch, cw))
            g    = PILImage.fromarray(arr, "L")
            log.debug("parse_gih: %s flat gray %dx%d", path, cw, ch)
            return PILImage.merge("RGBA", (g, g, g, g))

        # Best-effort partial
        avail = len(cell_data)
        rows  = max(1, avail // max(1, cw))
        if rows > 0 and rows * cw <= avail:
            arr    = np.frombuffer(cell_data[:rows * cw], np.uint8).reshape((rows, cw))
            padded = np.zeros((ch, cw), dtype=np.uint8)
            padded[:rows, :] = arr
            g   = PILImage.fromarray(padded, "L")
            log.debug("parse_gih: %s partial %d/%d rows", path, rows, ch)
            return PILImage.merge("RGBA", (g, g, g, g))

        log.debug("parse_gih: %s insufficient data (%d bytes)", path, len(cell_data))
        return None

    except Exception as e:
        log.warning("parse_gih failed %s: %s", path, e)
        return None


def parse_vbr(path: str) -> PILImage.Image | None:
    """
    GIMP Parametric Brush — INI-style text. We render an approximation.
    """
    try:
        params: dict[str, str] = {}
        with open(path, "r", errors="ignore") as f:
            for line in f:
                if "=" in line:
                    k, _, v = line.partition("=")
                    params[k.strip().lower()] = v.strip()

        radius   = max(3.0, min(float(params.get("radius",   "20")),  120.0))
        hardness = max(0.0, min(float(params.get("hardness", "1.0")),    1.0))
        aspect   = max(0.05, min(float(params.get("aspect-ratio", "1.0")), 20.0))
        angle    = float(params.get("angle", "0.0"))

        size = int(radius * 2) + 8
        img  = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))

        from PIL import ImageDraw, ImageFilter
        draw = ImageDraw.Draw(img)
        cx = cy = size // 2
        rx = int(radius)
        ry = max(1, int(radius / aspect))
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(0, 0, 0, 255))

        if abs(angle) > 1.0:
            img = img.rotate(-angle, resample=PILImage.BICUBIC, expand=False)
        if hardness < 0.95:
            blur_r = max(1, int((1 - hardness) * radius * 0.55))
            img = img.filter(ImageFilter.GaussianBlur(blur_r))

        return img
    except Exception as e:
        log.warning("parse_vbr failed %s: %s", path, e)
        return None


# ── Fallback thumbnail ────────────────────────────────────────────────────────

def make_fallback_thumb(path: str, size: int = 56) -> PILImage.Image:
    """
    A readable fallback tile when the brush cannot be parsed.
    Shows: file extension badge (top-left), brush icon, filename (bottom).
    """
    from PIL import ImageDraw
    ext  = os.path.splitext(path)[1].upper().lstrip(".")
    name = os.path.splitext(os.path.basename(path))[0][:14]

    img  = PILImage.new("RGBA", (size, size), (38, 36, 52, 255))
    draw = ImageDraw.Draw(img)

    # Concentric faint circles — stylized brush icon
    cx = cy = size // 2
    for r in range(size // 4, 2, -2):
        alpha = int(60 * r / (size // 4))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                     outline=(140, 130, 190, alpha))

    # Extension badge
    bw = min(size - 4, len(ext) * 6 + 10)
    draw.rectangle([2, 2, bw, 14], fill=(70, 65, 110, 230))

    try:
        from PIL import ImageFont
        fnt  = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 8)
        fnt2 = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 6)
    except Exception:
        from PIL import ImageFont
        fnt = fnt2 = ImageFont.load_default()

    draw.text((4, 3),        ext,  fill=(210, 200, 255, 255), font=fnt)
    draw.text((2, size - 10), name, fill=(130, 125, 160, 200), font=fnt2)

    return img


# ── Main preview loader ───────────────────────────────────────────────────────

def load_brush_preview(path: str,
                       thumb_size:  int  = 56,
                       use_cache:   bool = True,
                       bg_mode:     str  = "dark") -> PILImage.Image:
    """
    Load any supported brush file and return a composited RGBA thumbnail.

    bg_mode:
      "dark"     — dark #1e1e28 background  (default; good for light brushes)
      "light"    — light #e8e8e8 background  (good for dark brushes)
      "checker"  — checkerboard               (shows transparency explicitly)

    Never returns None. If parsing fails, returns make_fallback_thumb().
    """
    # ── 1. Cache hit ──────────────────────────────────────────────────────
    if use_cache:
        cached = get_cached_thumb(path)
        if cached is not None:
            return cached

    ext = os.path.splitext(path)[1].lower()
    img: PILImage.Image | None = None

    # ── 2. Parse ──────────────────────────────────────────────────────────
    try:
        if   ext == ".gbr":             img = parse_gbr(path)
        elif ext == ".gih":             img = parse_gih(path)
        elif ext == ".vbr":             img = parse_vbr(path)
        elif ext in (".png",".jpg",".jpeg"):
            img = PILImage.open(path).convert("RGBA")
    except Exception as e:
        log.warning("load_brush_preview: parse error %s: %s", path, e)
        img = None

    # ── 3. Fallback if parsing failed ─────────────────────────────────────
    if img is None:
        log.info("load_brush_preview: fallback for %s", path)
        return make_fallback_thumb(path, thumb_size)
        # Deliberate: do not cache the fallback; retry on next launch

    # ── 4. Resize ─────────────────────────────────────────────────────────
    img.thumbnail((thumb_size, thumb_size), PILImage.LANCZOS)
    tw, th = img.size

    # ── 5. Background composite ───────────────────────────────────────────
    if bg_mode == "light":
        bg = PILImage.new("RGBA", (tw, th), (232, 232, 232, 255))
    elif bg_mode == "checker":
        bg  = PILImage.new("RGBA", (tw, th), (255, 255, 255, 255))
        sq  = max(4, tw // 8)
        from PIL import ImageDraw
        d   = ImageDraw.Draw(bg)
        for ry in range(0, th, sq):
            for rx in range(0, tw, sq):
                if (rx // sq + ry // sq) % 2 == 0:
                    d.rectangle([rx, ry, rx + sq - 1, ry + sq - 1],
                                 fill=(190, 190, 190, 255))
    else:  # dark
        bg = PILImage.new("RGBA", (tw, th), (30, 28, 40, 255))

    out = PILImage.alpha_composite(bg, img)

    # ── 6. Auto-boost near-invisible brushes ──────────────────────────────
    #   If the alpha channel is nearly empty the brush probably stores its
    #   shape in luminance (inverted mask). Boost by inverting luminance.
    alpha_max = np.array(img.split()[3], dtype=np.float32).max()
    if alpha_max < 15:
        rgb = np.array(out.convert("RGB"), dtype=np.float32)
        if rgb.mean() > 210:
            out = PILImage.fromarray((255 - rgb).astype(np.uint8), "RGB").convert("RGBA")

    # ── 7. Save to cache ──────────────────────────────────────────────────
    if use_cache:
        save_cached_thumb(path, out)

    return out


# ── ZIP importer ──────────────────────────────────────────────────────────────

class BrushImportResult:
    def __init__(self):
        self.imported:  list[str] = []
        self.skipped:   list[str] = []
        self.errors:    list[str] = []
        self.pack_name: str = ""


def clear_gih_cache() -> int:
    """Delete cached thumbnails for all .gih files so they get re-parsed."""
    count = 0
    if not os.path.isdir(CACHE_DIR):
        return 0
    for f in os.listdir(CACHE_DIR):
        if f.endswith(".png"):
            fp = os.path.join(CACHE_DIR, f)
            try:
                os.remove(fp)
                count += 1
            except Exception:
                pass
    return count


def import_zip(zip_path: str, progress_cb=None) -> BrushImportResult:
    """
    Extract a ZIP, copy valid brush files to BRUSHES_DIR/<pack_name>/,
    and pre-generate thumbnail cache for each imported brush.

    progress_cb(current, total, filename) — optional; total is 2× file count
    (first half = extract, second half = cache-gen).
    """
    result    = BrushImportResult()
    pack_name = os.path.splitext(os.path.basename(zip_path))[0]
    result.pack_name = pack_name
    dest_dir  = os.path.join(BRUSHES_DIR, pack_name)
    os.makedirs(dest_dir, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sge_brushes_") as tmp:
        # ── Extract ───────────────────────────────────────────────────────
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                members = zf.namelist()
                total   = len(members)
                for i, member in enumerate(members):
                    if progress_cb:
                        progress_cb(i, total * 2, member)
                    try:
                        zf.extract(member, tmp)
                    except Exception as e:
                        result.errors.append(f"Extract failed: {member} — {e}")
        except zipfile.BadZipFile as e:
            result.errors.append(f"Not a valid ZIP: {e}")
            return result

        # ── Collect valid files ────────────────────────────────────────────
        candidates = []
        for root, _, files in os.walk(tmp):
            for fname in sorted(files):
                if os.path.splitext(fname)[1].lower() in VALID_EXTS:
                    candidates.append(os.path.join(root, fname))

        if not candidates:
            result.skipped.append("No valid brush files found.")
            return result

        # ── Copy + cache ──────────────────────────────────────────────────
        base_total = len(candidates)
        for i, src in enumerate(candidates):
            fname = os.path.basename(src)
            if progress_cb:
                progress_cb(base_total + i, base_total * 2, fname)

            # Deduplicate dst name
            dst = os.path.join(dest_dir, fname)
            base, ext2 = os.path.splitext(fname)
            counter = 1
            while os.path.exists(dst):
                dst = os.path.join(dest_dir, f"{base}_{counter}{ext2}")
                counter += 1

            try:
                shutil.copy2(src, dst)
            except Exception as e:
                result.errors.append(f"Copy failed {fname}: {e}")
                continue

            # Pre-generate thumbnail
            try:
                load_brush_preview(dst, thumb_size=64, use_cache=True, bg_mode="dark")
            except Exception as e:
                log.warning("cache-gen failed %s: %s", dst, e)

            result.imported.append(os.path.basename(dst))

    return result


# ── Qt Dialog helpers ─────────────────────────────────────────────────────────

def run_zip_import_dialog(parent=None) -> BrushImportResult | None:
    from PySide6.QtWidgets import QFileDialog, QProgressDialog, QMessageBox
    from PySide6.QtCore    import Qt

    zip_path, _ = QFileDialog.getOpenFileName(
        parent, "Import Brush Pack", "",
        "Brush Packs (*.zip);;All Files (*)")
    if not zip_path:
        return None

    prog = QProgressDialog("Importing brush pack…", "Cancel", 0, 100, parent)
    prog.setWindowTitle("Importing Brushes")
    prog.setWindowModality(Qt.WindowModal)
    prog.setMinimumWidth(420)
    prog.setStyleSheet("""
        QProgressDialog{background:#161616;color:#ccc;font-family:'Courier New';font-size:12px;}
        QProgressBar{background:#1a1a1a;border:1px solid #333;color:#88cc88;text-align:center;}
        QProgressBar::chunk{background:#3a6e3a;}
        QPushButton{background:#252525;color:#aaa;border:1px solid #444;
                    padding:4px 12px;font-family:'Courier New';}
    """)
    prog.show()
    cancelled = [False]

    def progress_cb(current, total, fname):
        if prog.wasCanceled():
            cancelled[0] = True; return
        prog.setValue(int(current / max(1, total) * 100))
        prog.setLabelText(f"Processing: {fname[:52]}")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

    result = import_zip(zip_path, progress_cb)
    prog.setValue(100); prog.close()

    if cancelled[0]:
        return None

    lines = [f"Pack: {result.pack_name}", "",
             f"✔ Imported:  {len(result.imported)} brushes"]
    if result.skipped: lines.append(f"⚠ Skipped:   {len(result.skipped)}")
    if result.errors:  lines.append(f"✖ Errors:    {len(result.errors)}")
    if result.imported:
        lines += ["", "Imported:"] + [f"  • {n}" for n in result.imported[:20]]
        if len(result.imported) > 20:
            lines.append(f"  … and {len(result.imported)-20} more")
    if result.errors:
        lines += ["", "Errors:"] + [f"  ! {e}" for e in result.errors[:5]]

    msg = QMessageBox(parent)
    msg.setWindowTitle("Import Complete")
    msg.setText(f"Imported {len(result.imported)} brush(es) from {result.pack_name}")
    msg.setDetailedText("\n".join(lines))
    msg.setIcon(QMessageBox.Information if result.imported else QMessageBox.Warning)
    msg.setStyleSheet("""
        QMessageBox{background:#161616;color:#ccc;font-family:'Courier New';}
        QLabel{color:#ccc;font-size:12px;}
        QPushButton{background:#252525;color:#aaa;border:1px solid #444;
                    padding:4px 12px;font-family:'Courier New';border-radius:3px;}
    """)
    msg.exec()
    return result