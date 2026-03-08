"""
brushPanel.py  —  Brush tool panel for Steam Grunge Editor.

New features over previous version:
  • Mathematically correct color wheel + barycentric triangle picker
      pos → color and color → pos use identical triangle geometry
  • Search bar (debounced, case-insensitive, matches name/file/pack)
  • Favorites system — right-click tile to star; persisted as JSON
  • Recent brushes bar — auto-updated, last MAX_RECENTS entries
  • Extended brush controls: Size, Opacity, Hardness, Spacing, Angle, Scatter
  • Preview background modes: Dark | Light | Checker
  • Brush info panel — name, pack, type, size×opacity×hardness
  • Thumbnail cache — never re-parses binary on every UI refresh
  • Graceful fallback thumbnails — never blank tiles
"""
from __future__ import annotations
import os, io, math, json
import numpy as np
from PIL import Image as PILImage

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QScrollArea, QGridLayout, QGroupBox,
    QComboBox, QSplitter, QFrame, QToolButton,
)
from PySide6.QtCore  import Qt, Signal, QPoint, QRect, QPointF, QSize, QTimer
from PySide6.QtGui   import (
    QPainter, QColor, QPen, QBrush, QPixmap, QImage,
    QLinearGradient, QFont, QPainterPath,
)

from app.config import ASSETS_DIR
from app.ui.widgets import (
    LabeledSlider, SearchBar, StatusBar,
    SectionHeader, HRule, TagBadge, IconButton,
)

BRUSHES_DIR    = os.path.join(ASSETS_DIR, "brushes")
FAVORITES_FILE = os.path.join(BRUSHES_DIR, ".favorites.json")
VALID_EXTS     = {".gbr", ".gih", ".vbr", ".png", ".jpg", ".jpeg"}
MAX_RECENTS    = 10

_MONO   = "Courier New"
_BG     = "#1a1a22"
_BORDER = "#2e2e3e"
_ACCENT = "#5566cc"


# ─────────────────────────────────────────────────────────────────────────────
#  Favorites store
# ─────────────────────────────────────────────────────────────────────────────
class _FavStore:
    def __init__(self):
        self._favs: set[str] = set()
        self._load()

    def _load(self):
        try:
            if os.path.exists(FAVORITES_FILE):
                with open(FAVORITES_FILE) as f:
                    self._favs = set(json.load(f).get("favorites", []))
        except Exception:
            self._favs = set()

    def save(self):
        try:
            os.makedirs(BRUSHES_DIR, exist_ok=True)
            with open(FAVORITES_FILE, "w") as f:
                json.dump({"favorites": sorted(self._favs)}, f, indent=2)
        except Exception:
            pass

    def is_fav(self, path: str) -> bool: return path in self._favs
    def toggle(self, path: str) -> bool:
        if path in self._favs: self._favs.discard(path)
        else:                  self._favs.add(path)
        self.save()
        return self.is_fav(path)


_FAVS = _FavStore()


# ─────────────────────────────────────────────────────────────────────────────
#  Mathematically correct color wheel + barycentric triangle
# ─────────────────────────────────────────────────────────────────────────────
class ColorWheelWidget(QWidget):
    """
    Hue ring + inner equilateral SV triangle.

    Triangle vertices (in widget-space):
      ph  — pure hue corner  (H=hue, S=1, V=1)
      pb  — black corner     (H=hue, S=0, V=0)
      pw  — white corner     (H=hue, S=0, V=1)

    Barycentric weights (wh, wb, ww) → color:
      V = wh + ww       (bright = hue or white; dark = black only)
      S = wh / (wh+ww)  if (wh+ww) > 0 else 0

    Inverse (color → position):
      wh = S * V
      wb = 1 - V
      ww = (1-S) * V
      pos = wh*ph + wb*pb + ww*pw

    Both transforms use the *same* vertex coordinates, so the mapping is
    perfectly consistent — the cursor dot never drifts.
    """
    color_changed = Signal(QColor)
    SIZE   = 200
    RING_W = 22
    GAP    = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._hue  = 0.0    # 0-360
        self._sat  = 0.75
        self._val  = 0.85
        self._drag = None   # "ring" | "tri"
        self._ring_pix = None
        self._tri_pix  = None
        self._render_ring()
        self._render_tri()

    # ── Public ────────────────────────────────────────────────────────────────
    def color(self) -> QColor:
        return QColor.fromHsvF(
            self._hue / 360.0,
            max(0.0, min(1.0, self._sat)),
            max(0.0, min(1.0, self._val)))

    def set_color(self, c: QColor):
        h, s, v, _ = c.getHsvF()
        if h >= 0: self._hue = h * 360.0
        self._sat = max(0.0, min(1.0, s))
        self._val = max(0.0, min(1.0, v))
        self._render_tri(); self.update()

    # ── Triangle geometry ─────────────────────────────────────────────────────
    def _inner_radius(self) -> float:
        return self.SIZE / 2.0 - self.GAP - self.RING_W - self.GAP - 2

    def _tri_verts(self) -> tuple[QPointF, QPointF, QPointF]:
        """
        Equilateral triangle inscribed in a circle of _inner_radius().
        ph is at angle _hue; pb at hue+120°; pw at hue+240°.
        """
        cx = cy = self.SIZE / 2.0
        r  = self._inner_radius()
        a0 = math.radians(self._hue)
        def v(a): return QPointF(cx + r * math.cos(a), cy - r * math.sin(a))
        return v(a0), v(a0 + math.radians(120.0)), v(a0 + math.radians(240.0))

    # ── Coordinate conversion (the critical part) ─────────────────────────────
    def _pos_to_sv(self, pos: QPointF):
        """
        Widget-space point → (_sat, _val) via barycentric coordinates.

        Solve: pos = wh*ph + wb*pb + ww*pw  with  wh+wb+ww = 1
        using pw as the reference corner (eliminates ww by substitution).
        """
        ph, pb, pw = self._tri_verts()
        ax = ph.x() - pw.x();  ay = ph.y() - pw.y()
        bx = pb.x() - pw.x();  by = pb.y() - pw.y()
        px = pos.x() - pw.x(); py = pos.y() - pw.y()
        det = ax * by - ay * bx
        if abs(det) < 1e-6: return

        wh = (px * by - py * bx) / det
        wb = (ax * py - ay * px) / det
        ww = 1.0 - wh - wb

        # Clamp-then-normalise keeps the cursor inside the triangle during drags
        wh = max(0.0, wh); wb = max(0.0, wb); ww = max(0.0, ww)
        t  = wh + wb + ww
        if t < 1e-9: return
        wh /= t; wb /= t; ww /= t

        bright      = wh + ww
        self._val   = max(0.0, min(1.0, bright))
        self._sat   = max(0.0, min(1.0, wh / max(bright, 1e-9)))

    def _sv_to_pos(self) -> QPointF:
        """
        (_sat, _val) → widget-space point using the SAME weights.
        Exact inverse of _pos_to_sv.
        """
        ph, pb, pw = self._tri_verts()
        wh = self._sat * self._val
        wb = 1.0 - self._val
        ww = (1.0 - self._sat) * self._val
        return QPointF(
            wh * ph.x() + wb * pb.x() + ww * pw.x(),
            wh * ph.y() + wb * pb.y() + ww * pw.y())

    # ── Render ────────────────────────────────────────────────────────────────
    def _render_ring(self):
        import colorsys
        sz = self.SIZE; cx = cy = sz // 2
        outer = sz // 2 - self.GAP
        inner = outer - self.RING_W
        arr   = np.zeros((sz, sz, 4), dtype=np.uint8)
        ys, xs = np.mgrid[0:sz, 0:sz]
        dx   = xs.astype(np.float32) - cx
        dy   = cy - ys.astype(np.float32)
        dist = np.sqrt(dx * dx + dy * dy)
        ang  = (np.degrees(np.arctan2(dy, dx)) % 360).astype(np.float32)
        mask = (dist >= inner) & (dist <= outer)
        rows, cols = np.where(mask)
        for row, col in zip(rows, cols):
            r2, g2, b2 = colorsys.hsv_to_rgb(float(ang[row, col]) / 360.0, 1.0, 1.0)
            arr[row, col] = [int(b2*255), int(g2*255), int(r2*255), 255]
        img = QImage(arr.data, sz, sz, sz * 4, QImage.Format_ARGB32)
        self._ring_pix = QPixmap.fromImage(img.copy())

    def _render_tri(self):
        sz  = self.SIZE
        img = QImage(sz, sz, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        ph, pb, pw = self._tri_verts()
        hue_col = QColor.fromHsvF(self._hue / 360.0, 1.0, 1.0)

        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.moveTo(ph); path.lineTo(pb); path.lineTo(pw); path.closeSubpath()
        p.setClipPath(path)

        # Layer 1: white → black along pw→pb
        g1 = QLinearGradient(pw, pb)
        g1.setColorAt(0, QColor(255, 255, 255, 255))
        g1.setColorAt(1, QColor(0,   0,   0,   255))
        p.fillPath(path, QBrush(g1))

        # Layer 2: hue → transparent from ph → midpoint(pb,pw)
        # Multiply blend: hue vertex stays pure hue, black stays black, white stays white
        mid = QPointF((pb.x() + pw.x()) / 2.0, (pb.y() + pw.y()) / 2.0)
        g2  = QLinearGradient(ph, mid)
        hc  = QColor(hue_col); hc.setAlpha(255)
        ht  = QColor(hue_col); ht.setAlpha(0)
        g2.setColorAt(0, hc); g2.setColorAt(1, ht)
        p.setCompositionMode(QPainter.CompositionMode_Multiply)
        p.fillPath(path, QBrush(g2))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setClipping(False); p.end()
        self._tri_pix = QPixmap.fromImage(img)

    # ── Paint ─────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._ring_pix: p.drawPixmap(0, 0, self._ring_pix)
        if self._tri_pix:  p.drawPixmap(0, 0, self._tri_pix)

        sz = self.SIZE; cx = cy = sz // 2

        # Hue cursor on ring
        r_mid = sz // 2 - self.GAP - self.RING_W // 2
        ha    = math.radians(self._hue)
        hx    = cx + r_mid * math.cos(ha)
        hy    = cy - r_mid * math.sin(ha)
        p.setPen(QPen(QColor(255, 255, 255, 210), 2))
        p.setBrush(self.color())
        p.drawEllipse(QPointF(hx, hy), 9, 9)
        p.setPen(QPen(QColor(0, 0, 0, 100), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(hx, hy), 10, 10)

        # SV cursor — computed from the SAME weights as _render_tri uses
        sv = self._sv_to_pos()
        p.setPen(QPen(QColor(255, 255, 255), 2)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(sv, 6, 6)
        p.setPen(QPen(QColor(0, 0, 0, 180), 1))
        p.drawEllipse(sv, 7, 7)
        p.end()

    # ── Mouse ─────────────────────────────────────────────────────────────────
    def _in_ring(self, pos: QPointF) -> bool:
        cx = cy = self.SIZE / 2.0
        outer = self.SIZE / 2.0 - self.GAP
        inner = outer - self.RING_W
        d = math.hypot(pos.x() - cx, pos.y() - cy)
        return inner <= d <= outer + 2

    def mousePressEvent(self, e):
        pos = QPointF(e.position())
        self._drag = "ring" if self._in_ring(pos) else "tri"
        self._handle_drag(pos)

    def mouseMoveEvent(self, e):
        if self._drag: self._handle_drag(QPointF(e.position()))

    def mouseReleaseEvent(self, _): self._drag = None

    def _handle_drag(self, pos: QPointF):
        cx = cy = self.SIZE / 2.0
        if self._drag == "ring":
            self._hue = math.degrees(math.atan2(cy - pos.y(), pos.x() - cx)) % 360
            self._render_tri()
        else:
            self._pos_to_sv(pos)
        self.update()
        self.color_changed.emit(self.color())


# ─────────────────────────────────────────────────────────────────────────────
#  Brush tile
# ─────────────────────────────────────────────────────────────────────────────
class BrushTile(QWidget):
    clicked     = Signal(str)
    fav_toggled = Signal(str)
    TILE = 68

    def __init__(self, path: str, size: int = 68,
                 bg_mode: str = "dark", parent=None):
        super().__init__(parent)
        self.path      = path
        self.bg_mode   = bg_mode
        self._selected = False
        self._hovered  = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setToolTip(os.path.splitext(os.path.basename(path))[0])
        self._pix = self._load(size - 8)

    def _load(self, sz: int) -> QPixmap:
        from app.ui.brushImporter import load_brush_preview
        try:
            img = load_brush_preview(self.path, thumb_size=sz,
                                     use_cache=True, bg_mode=self.bg_mode)
        except Exception:
            from app.ui.brushImporter import make_fallback_thumb
            img = make_fallback_thumb(self.path, sz)
        buf = io.BytesIO(); img.save(buf, "PNG")
        pix = QPixmap(); pix.loadFromData(buf.getvalue())
        return pix

    def set_selected(self, v: bool): self._selected = v; self.update()

    def set_bg_mode(self, mode: str):
        if mode != self.bg_mode:
            self.bg_mode = mode
            self._pix = self._load_nocache(self.TILE - 8)
            self.update()

    def _load_nocache(self, sz: int) -> QPixmap:
        """Load with cache bypassed — used when bg_mode changes."""
        from app.ui.brushImporter import load_brush_preview
        try:
            img = load_brush_preview(self.path, thumb_size=sz,
                                     use_cache=False, bg_mode=self.bg_mode)
        except Exception:
            from app.ui.brushImporter import make_fallback_thumb
            img = make_fallback_thumb(self.path, sz)
        buf = io.BytesIO(); img.save(buf, "PNG")
        pix = QPixmap(); pix.loadFromData(buf.getvalue())
        return pix

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        if self._selected:     bg = QColor(40, 96, 200)
        elif self._hovered:    bg = QColor(50, 50, 70)
        else:                  bg = QColor(28, 28, 38)
        p.fillRect(self.rect(), bg)

        if self._pix and not self._pix.isNull():
            pw, ph = self._pix.width(), self._pix.height()
            p.drawPixmap((self.width() - pw) // 2, (self.height() - ph) // 2, self._pix)

        pen_col = (QColor(80, 140, 255) if self._selected else
                   QColor(66, 66, 95)   if self._hovered  else
                   QColor(42, 42, 58))
        p.setPen(QPen(pen_col, 1.5 if self._selected else 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 3, 3)

        # Favorite star (top-right)
        fav = _FAVS.is_fav(self.path)
        if fav or self._hovered:
            p.setFont(QFont(_MONO, 8))
            p.setPen(QColor(255, 210, 50) if fav else QColor(80, 80, 110))
            p.drawText(QRect(self.width() - 14, 2, 12, 12), Qt.AlignCenter, "★")
        p.end()

    def enterEvent(self, e): self._hovered = True;  self.update()
    def leaveEvent(self, e): self._hovered = False; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            _FAVS.toggle(self.path); self.update()
            self.fav_toggled.emit(self.path)
        else:
            self.clicked.emit(self.path)


# ─────────────────────────────────────────────────────────────────────────────
#  Recent brushes bar
# ─────────────────────────────────────────────────────────────────────────────
class RecentBrushBar(QWidget):
    """Horizontal strip of recently used brushes (small tiles)."""
    brush_selected = Signal(str)
    TILE = 38

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths: list[str] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0); lay.setSpacing(2)
        lbl = QLabel("RECENT")
        lbl.setStyleSheet(f"color:#2e2e4e;font-size:9px;font-family:'{_MONO}';"
                          "letter-spacing:1px;background:transparent;")
        lbl.setFixedWidth(44)
        lay.addWidget(lbl)
        self._inner = QWidget()
        self._inner.setStyleSheet("background:#141420;")
        self._ilay  = QHBoxLayout(self._inner)
        self._ilay.setContentsMargins(0, 0, 0, 0); self._ilay.setSpacing(2)
        self._ilay.addStretch()
        lay.addWidget(self._inner, 1)
        self.setFixedHeight(self.TILE + 8)
        self.setStyleSheet("background:#141420;border-radius:2px;")

    def push(self, path: str):
        if path in self._paths: self._paths.remove(path)
        self._paths.insert(0, path)
        self._paths = self._paths[:MAX_RECENTS]
        self._rebuild()

    def _rebuild(self):
        while self._ilay.count():
            item = self._ilay.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for path in self._paths:
            btn = QPushButton()
            btn.setFixedSize(self.TILE, self.TILE)
            btn.setToolTip(os.path.splitext(os.path.basename(path))[0])
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton{{background:#1e1e2c;border:1px solid {_BORDER};border-radius:2px;}}
                QPushButton:hover{{background:#252540;border-color:{_ACCENT};}}
            """)
            pix = self._mini_pix(path)
            if pix: btn.setIcon(pix); btn.setIconSize(QSize(self.TILE - 4, self.TILE - 4))
            btn.clicked.connect(lambda _, p=path: self.brush_selected.emit(p))
            self._ilay.addWidget(btn)
        self._ilay.addStretch()

    def _mini_pix(self, path: str) -> QPixmap | None:
        from app.ui.brushImporter import load_brush_preview
        try:
            img = load_brush_preview(path, thumb_size=self.TILE - 4,
                                     use_cache=True, bg_mode="dark")
            buf = io.BytesIO(); img.save(buf, "PNG")
            pix = QPixmap(); pix.loadFromData(buf.getvalue())
            return pix if not pix.isNull() else None
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
#  Brush info panel
# ─────────────────────────────────────────────────────────────────────────────
class BrushInfoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(2)

        def row(key: str) -> QLabel:
            r = QHBoxLayout(); r.setSpacing(4)
            k = QLabel(f"{key}:")
            k.setFixedWidth(50)
            k.setStyleSheet(f"color:#2e2e4e;font-size:10px;font-family:'{_MONO}';background:transparent;")
            v = QLabel("—")
            v.setStyleSheet(f"color:#666;font-size:10px;font-family:'{_MONO}';background:transparent;")
            r.addWidget(k); r.addWidget(v, 1); lay.addLayout(r)
            return v

        self._name = row("Name")
        self._pack = row("Pack")
        self._type = row("Type")
        self._dims = row("Info")

    def update_info(self, path: str, pack: str,
                    sz: int, opac: float, hard: float):
        if not path:
            for l in (self._name, self._pack, self._type, self._dims): l.setText("—")
            return
        name = os.path.splitext(os.path.basename(path))[0]
        ext  = os.path.splitext(path)[1].upper().lstrip(".")
        self._name.setText(name[:30])
        self._pack.setText(pack[:22])
        self._type.setText(ext or "?")
        self._dims.setText(f"{sz}px  ·  {int(opac*100)}%  ·  H{int(hard*100)}%")


# ─────────────────────────────────────────────────────────────────────────────
#  Panel style sheet
# ─────────────────────────────────────────────────────────────────────────────
_STYLE = f"""
QWidget{{background:{_BG};}}
QGroupBox{{
    border:1px solid {_BORDER};border-radius:4px;margin-top:12px;
    font-family:"{_MONO}";font-size:10px;font-weight:bold;
    color:#2e2e4e;letter-spacing:2px;
}}
QGroupBox::title{{subcontrol-origin:margin;left:8px;padding:0 4px;}}
QLabel{{color:#555;font-family:"{_MONO}";font-size:11px;background:transparent;}}
QPushButton{{
    background:#1e1e2c;color:#666;border:1px solid {_BORDER};border-radius:2px;
    font-family:"{_MONO}";font-size:11px;padding:3px 8px;
}}
QPushButton:hover{{background:#252540;color:#ccc;border-color:{_ACCENT};}}
QComboBox{{
    background:#181822;color:#888;border:1px solid {_BORDER};border-radius:2px;
    padding:2px 6px;font-family:"{_MONO}";font-size:11px;
}}
QComboBox::drop-down{{border:none;}}
QComboBox QAbstractItemView{{
    background:#181822;color:#888;selection-background-color:#252550;
    border:1px solid #3a3a5a;
}}
QScrollBar:vertical{{background:#111;width:5px;border:none;}}
QScrollBar::handle:vertical{{background:#2a2a4a;border-radius:2px;min-height:14px;}}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Main BrushPanel
# ─────────────────────────────────────────────────────────────────────────────
class BrushPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BrushPanel")
        self._canvas         = None
        self._selected_brush = ""
        self._selected_pack  = ""
        self._brush_tiles:   list[BrushTile] = []
        self._all_packs:     dict[str, list[str]] = {}
        self._show_favs_only = False
        self._bg_mode        = "dark"
        self._active_tool    = "move"    # brush|eraser|move|rect|ellipse|picker|hand|zoom
        self._tool_btns: dict[str, object] = {}
        self.setStyleSheet(_STYLE)
        self._build_ui()
        self._load_brushes()

    def set_canvas(self, canvas):
        self._canvas = canvas
        canvas.brush_paint_requested = self._on_canvas_paint
        # Sync initial tool to canvas
        try:
            from app.ui.toolBar import ToolMode
            mapping = {
                "move":    ToolMode.MOVE,
                "brush":   ToolMode.BRUSH,
                "eraser":  ToolMode.ERASER,
                "rect":    ToolMode.RECTANGLE,
                "ellipse": ToolMode.ELLIPSE,
                "picker":  ToolMode.COLOR_PICKER,
                "hand":    ToolMode.HAND,
                "zoom":    ToolMode.ZOOM,
            }
            canvas.set_tool(mapping.get(self._active_tool, ToolMode.BRUSH))
        except (ImportError, AttributeError):
            pass
        # Color picker result → update color wheel
        try:
            canvas.color_picked.connect(self._on_color_picked_from_canvas)
        except Exception:
            pass
        # Canvas tool shortcut → sync our buttons
        try:
            canvas.tool_shortcut_pressed.connect(self._on_canvas_tool_shortcut)
        except Exception:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._brush_tiles: self._reflow_grid()

    def _cols(self) -> int:
        tw = BrushTile.TILE + 2
        return max(1, (self._scroll.viewport().width() - 4) // tw)

    def _reflow_grid(self):
        visible = [t for t in self._brush_tiles if t.isVisible()]
        cols    = self._cols()
        for i, tile in enumerate(visible):
            self._grid_layout.addWidget(tile, i // cols, i % cols)


    # ─────────────────────────────────────────────────────────────────────────
    #  Tool strip (inside the panel, above brush controls)
    # ─────────────────────────────────────────────────────────────────────────

    # Tool definitions: (id, icon, tooltip)
    # (id, icon-char, tooltip)
    _TOOLS = [
        ("move",    "⬡",  "Move Tool  [V]\nDrag to move/transform layers."),
        ("brush",   "🖌",  "Brush Tool  [B]\nPaint on the active paint layer."),
        ("eraser",  "◫",  "Eraser Tool  [E]\nErase pixels (writes transparency)."),
        ("rect",    "▬",  "Rectangle Tool  [R]\nDrag to draw a rectangle layer."),
        ("ellipse", "⬤",  "Ellipse Tool  [O]\nDrag to draw an ellipse layer."),
        ("picker",  "🖊",  "Color Picker  [I]\nClick canvas to sample a color."),
        ("hand",    "🖐",  "Hand Tool  [H]\nPan the canvas by dragging."),
    ]

    _TOOL_BTN_BASE = """
        QToolButton {{
            background: #181824;
            color: #666;
            border: 1px solid #252535;
            border-radius: 6px;
            font-size: 18px;
            min-width: 38px; min-height: 38px;
            max-width: 38px; max-height: 38px;
            padding: 0px;
        }}
        QToolButton:hover {{
            background: #1e1e32;
            color: #bbb;
            border-color: #3a3a5a;
        }}
    """
    _TOOL_BTN_ACTIVE = """
        QToolButton {{
            background: #2a2a5a;
            color: #ffffff;
            border: 2px solid #5566cc;
            border-radius: 6px;
            font-size: 18px;
            min-width: 38px; min-height: 38px;
            max-width: 38px; max-height: 38px;
            padding: 0px;
        }}
    """

    def _build_tool_strip(self, parent_layout):
        """Build a compact 2-row tool grid inside the panel."""
        from PySide6.QtWidgets import QGridLayout, QToolButton

        grp = QGroupBox("TOOLS")
        gl  = QGridLayout(grp)
        gl.setContentsMargins(4, 6, 4, 6)
        gl.setSpacing(3)

        for i, (tool_id, icon, tip) in enumerate(self._TOOLS):
            btn = QToolButton()
            btn.setText(icon)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setChecked(tool_id == self._active_tool)
            btn.setStyleSheet(
                self._TOOL_BTN_ACTIVE if tool_id == self._active_tool
                else self._TOOL_BTN_BASE
            )
            # Use font that supports emoji
            from PySide6.QtGui import QFont as _QF
            f = _QF("Segoe UI Emoji", 14)
            btn.setFont(f)
            btn.clicked.connect(lambda checked, tid=tool_id: self._on_tool_selected(tid))
            self._tool_btns[tool_id] = btn
            gl.addWidget(btn, i // 4, i % 4)

        parent_layout.addWidget(grp)

    def _on_tool_selected(self, tool_id: str):
        """Switch active tool and sync canvas."""
        if tool_id == self._active_tool:
            return
        self._active_tool = tool_id

        # Update button styles
        for tid, btn in self._tool_btns.items():
            active = (tid == tool_id)
            btn.blockSignals(True)
            btn.setChecked(active)
            btn.setStyleSheet(
                self._TOOL_BTN_ACTIVE if active else self._TOOL_BTN_BASE
            )
            btn.blockSignals(False)

        # Tell canvas
        if self._canvas:
            try:
                from app.ui.toolBar import ToolMode
                mapping = {
                    "move":    ToolMode.MOVE,
                    "brush":   ToolMode.BRUSH,
                    "eraser":  ToolMode.ERASER,
                    "rect":    ToolMode.RECTANGLE,
                    "ellipse": ToolMode.ELLIPSE,
                    "picker":  ToolMode.COLOR_PICKER,
                    "hand":    ToolMode.HAND,
                    "zoom":    ToolMode.ZOOM,
                }
                if tool_id in mapping:
                    self._canvas.set_tool(mapping[tool_id])
            except (ImportError, AttributeError):
                pass

        # Show/hide brush controls based on whether brush/eraser is active
        is_brush_tool = tool_id in ("brush", "eraser")
        # Brush controls are always visible; just update status
        if hasattr(self, "_status"):
            labels = {
                "move":    "Move — drag layers",
                "brush":   "Brush — paint on paint layer",
                "eraser":  "Eraser — erase paint layer",
                "rect":    "Rectangle — drag to draw rect",
                "ellipse": "Ellipse — drag to draw ellipse",
                "picker":  "Color Picker — click canvas to sample",
                "hand":    "Hand — drag to pan",
                "zoom":    "Zoom — click to zoom in/out",
            }
            self._status.set_status(labels.get(tool_id, ""))


    # ── Build UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(5)
        splitter.setStyleSheet(
            f"QSplitter::handle{{background:#1c1c26;border-top:1px solid {_BORDER};}}"
            f"QSplitter::handle:hover{{background:#222234;}}")
        root.addWidget(splitter)

        # ── TOP: Color + Controls ─────────────────────────────────────────
        top = QWidget(); tl = QVBoxLayout(top)
        tl.setContentsMargins(8, 6, 8, 4); tl.setSpacing(6)

        grp_col = QGroupBox("COLOR")
        cl = QVBoxLayout(grp_col); cl.setSpacing(4)
        self._wheel = ColorWheelWidget()
        self._wheel.color_changed.connect(self._on_color_changed)
        cl.addWidget(self._wheel, 0, Qt.AlignHCenter)

        sw_row = QHBoxLayout(); sw_row.setSpacing(6)
        self._fg_swatch = QLabel()
        self._fg_swatch.setFixedSize(28, 28)
        self._fg_swatch.setStyleSheet(
            "background:#fff;border:1px solid #3a3a5a;border-radius:3px;")
        self._hex_lbl = QLabel("#ffffff")
        self._hex_lbl.setStyleSheet(
            f"color:#333;font-family:'{_MONO}';font-size:10px;background:transparent;")
        sw_row.addWidget(self._fg_swatch)
        sw_row.addWidget(self._hex_lbl); sw_row.addStretch()
        cl.addLayout(sw_row); tl.addWidget(grp_col)

        # ── TOOL STRIP ────────────────────────────────────────────────────────
        self._build_tool_strip(tl)

        grp_br = QGroupBox("BRUSH CONTROLS")
        bl = QVBoxLayout(grp_br); bl.setSpacing(4)

        def sl(label, lo, hi, val, fmt=None, tip=""):
            s = LabeledSlider(label, lo, hi, val,
                              fmt=fmt or str, label_width=60)
            if tip: s.setToolTip(tip)
            bl.addWidget(s); return s

        self._size_sl    = sl("Size",    1, 200, 20, tip="Stamp diameter in pixels")
        self._opac_sl    = sl("Opacity", 1, 100, 80, fmt=lambda v: f"{v}%")
        self._hard_sl    = sl("Hardness",0, 100, 60, fmt=lambda v: f"{v}%",
                               tip="100% = hard edge; 0% = fully soft")
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{_BORDER};"); bl.addWidget(sep)
        self._space_sl   = sl("Spacing", 1, 200, 25, fmt=lambda v: f"{v}%",
                               tip="Distance between stamps along stroke")
        self._angle_sl   = sl("Angle",   0, 359,  0, fmt=lambda v: f"{v}°",
                               tip="Fixed rotation of brush tip")
        self._scatter_sl = sl("Scatter", 0, 100,  0, fmt=lambda v: f"{v}%",
                               tip="Random offset of stamps from stroke path")
        tl.addWidget(grp_br)

        grp_info = QGroupBox("SELECTED BRUSH")
        il = QVBoxLayout(grp_info); il.setContentsMargins(4, 8, 4, 4)
        self._info_panel = BrushInfoPanel()
        il.addWidget(self._info_panel)
        tl.addWidget(grp_info)
        tl.addStretch()
        splitter.addWidget(top)

        # ── BOTTOM: Library ───────────────────────────────────────────────
        bot = QWidget(); blt = QVBoxLayout(bot)
        blt.setContentsMargins(6, 4, 6, 6); blt.setSpacing(3)

        # Header
        hr = QHBoxLayout(); hr.setSpacing(4)
        hl = QLabel("BRUSHES")
        hl.setStyleSheet(f"color:#2e2e4e;font-size:10px;font-weight:bold;"
                         f"letter-spacing:2px;font-family:'{_MONO}';background:transparent;")
        hr.addWidget(hl); hr.addStretch()
        bz = QPushButton("📦 ZIP");   bz.setFixedHeight(22); bz.clicked.connect(self._import_zip)
        bf = QPushButton("+ Files"); bf.setFixedHeight(22); bf.clicked.connect(self._import_files)
        hr.addWidget(bz); hr.addWidget(bf); blt.addLayout(hr)

        # Search + favorites toggle
        srch_row = QHBoxLayout(); srch_row.setSpacing(3)
        self._search_bar = SearchBar("🔍  Search brushes…")
        self._search_bar.search_changed.connect(self._on_search_changed)
        srch_row.addWidget(self._search_bar, 1)
        self._fav_btn = QPushButton("★")
        self._fav_btn.setFixedSize(26, 26)
        self._fav_btn.setCheckable(True)
        self._fav_btn.setToolTip("Show only favorites (right-click any tile to star)")
        self._fav_btn.setStyleSheet(f"""
            QPushButton{{background:#1c1c26;color:#333;border:1px solid {_BORDER};
                        border-radius:3px;font-size:14px;padding:0;}}
            QPushButton:checked{{background:#2a2010;color:#ffcc00;border-color:#996600;}}
            QPushButton:hover{{color:#ffdd44;}}
        """)
        self._fav_btn.toggled.connect(self._on_fav_filter)
        srch_row.addWidget(self._fav_btn); blt.addLayout(srch_row)

        # Pack filter + preview bg
        frow = QHBoxLayout(); frow.setSpacing(4)
        self._pack_combo = QComboBox()
        self._pack_combo.currentIndexChanged.connect(self._on_pack_changed)
        frow.addWidget(self._pack_combo, 1)
        bg_combo = QComboBox()
        bg_combo.addItems(["🌑 Dark", "☀ Light", "⊞ Checker"])
        bg_combo.setFixedWidth(96)
        bg_combo.setToolTip("Preview background mode")
        bg_combo.currentIndexChanged.connect(self._on_bg_mode)
        frow.addWidget(bg_combo); blt.addLayout(frow)

        # Recent bar
        self._recent_bar = RecentBrushBar()
        self._recent_bar.brush_selected.connect(self._on_brush_selected)
        blt.addWidget(self._recent_bar)

        # Grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"QScrollArea{{border:1px solid {_BORDER};background:#141420;}}")
        self._grid_widget = QWidget(); self._grid_widget.setStyleSheet("background:#141420;")
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setSpacing(2); self._grid_layout.setContentsMargins(3, 3, 3, 3)
        self._scroll.setWidget(self._grid_widget)
        blt.addWidget(self._scroll, 1)

        self._status = StatusBar()
        blt.addWidget(self._status)
        splitter.addWidget(bot)
        splitter.setSizes([430, 280])

    # ── Brush loading ─────────────────────────────────────────────────────────
    def _scan_brushes(self) -> dict:
        packs: dict[str, list[str]] = {}
        if not os.path.isdir(BRUSHES_DIR): return packs
        for f in sorted(os.listdir(BRUSHES_DIR)):
            full = os.path.join(BRUSHES_DIR, f)
            if os.path.isfile(full) and os.path.splitext(f)[1].lower() in VALID_EXTS:
                packs.setdefault("Default", []).append(full)
        for d in sorted(os.listdir(BRUSHES_DIR)):
            fd = os.path.join(BRUSHES_DIR, d)
            if not os.path.isdir(fd) or d.startswith("."): continue
            files = []
            for root, _, fs in os.walk(fd):
                for fn in sorted(fs):
                    if os.path.splitext(fn)[1].lower() in VALID_EXTS:
                        files.append(os.path.join(root, fn))
            if files: packs[d] = files
        return packs

    def _load_brushes(self):
        self._all_packs = self._scan_brushes()
        self._pack_combo.blockSignals(True)
        prev = self._pack_combo.currentText()
        self._pack_combo.clear(); self._pack_combo.addItem("All Packs")
        for name, paths in self._all_packs.items():
            self._pack_combo.addItem(f"{name}  ({len(paths)})")
        idx = self._pack_combo.findText(prev, Qt.MatchStartsWith)
        self._pack_combo.setCurrentIndex(max(0, idx))
        self._pack_combo.blockSignals(False)
        self._rebuild_grid()

    def _visible_paths(self) -> list[str]:
        # Pack filter
        t = self._pack_combo.currentText()
        if t.startswith("All Packs") or not self._all_packs:
            paths: list[str] = []
            for v in self._all_packs.values(): paths.extend(v)
        else:
            paths = list(self._all_packs.get(t.split("  (")[0], []))

        # Favorites filter
        if self._show_favs_only:
            paths = [p for p in paths if _FAVS.is_fav(p)]

        # Text search
        q = self._search_bar.text().lower().strip()
        if q:
            def match(p):
                fn   = os.path.basename(p).lower()
                name = os.path.splitext(fn)[0]
                pack = os.path.basename(os.path.dirname(p)).lower()
                return q in name or q in fn or q in pack
            paths = [p for p in paths if match(p)]
        return paths

    def _rebuild_grid(self):
        for tile in self._brush_tiles: tile.deleteLater()
        self._brush_tiles.clear()
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        paths = self._visible_paths()
        total = sum(len(v) for v in self._all_packs.values())
        shown = len(paths)

        txt = (f"{total} brush{'es' if total != 1 else ''}  ·  "
               f"{len(self._all_packs)} pack{'s' if len(self._all_packs) != 1 else ''}")
        if self._search_bar.text() or self._show_favs_only:
            txt += f"  ·  {shown} shown"
        self._status.set_status(txt)

        if not paths:
            msg = ("No favorites — right-click a tile to star it."
                   if self._show_favs_only else
                   f"No match for \"{self._search_bar.text()}\"."
                   if self._search_bar.text() else
                   "No brushes. Use ZIP or + Files to import.")
            lbl = QLabel(msg)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color:#2a2a3a;font-size:11px;padding:20px;background:#141420;"
                              f"font-family:'{_MONO}';")
            self._grid_layout.addWidget(lbl, 0, 0, 1, 4); return

        cols = self._cols()
        for i, path in enumerate(paths):
            tile = BrushTile(path, BrushTile.TILE, bg_mode=self._bg_mode)
            tile.clicked.connect(self._on_brush_selected)
            tile.fav_toggled.connect(self._on_fav_toggled)
            self._brush_tiles.append(tile)
            self._grid_layout.addWidget(tile, i // cols, i % cols)

        if not self._selected_brush and paths:
            self._on_brush_selected(paths[0])
        else:
            for tile in self._brush_tiles:
                tile.set_selected(tile.path == self._selected_brush)

    # ── Slots ─────────────────────────────────────────────────────────────────
    def _on_search_changed(self, _): self._rebuild_grid()
    def _on_fav_filter(self, checked): self._show_favs_only = checked; self._rebuild_grid()
    def _on_fav_toggled(self, _):
        if self._show_favs_only: self._rebuild_grid()
        else: self.update()
    def _on_pack_changed(self, _): self._rebuild_grid()
    def _on_bg_mode(self, idx):
        self._bg_mode = ["dark", "light", "checker"][idx]
        for tile in self._brush_tiles: tile.set_bg_mode(self._bg_mode)

    def _on_brush_selected(self, path: str):
        # Clear the stamp cache for the newly selected brush so it gets re-parsed
        self._brush_raw_cache.pop(path, None)
        if not os.path.exists(path): return
        self._selected_brush = path
        pack = os.path.basename(os.path.dirname(path))
        self._selected_pack  = pack
        for tile in self._brush_tiles: tile.set_selected(tile.path == path)
        self._info_panel.update_info(path, pack,
                                     self.brush_size(),
                                     self.brush_opacity(),
                                     self.brush_hardness())
        self._recent_bar.push(path)

    def _import_zip(self):
        from app.ui.brushImporter import run_zip_import_dialog
        r = run_zip_import_dialog(self)
        if r and r.imported: self._load_brushes()

    def _import_files(self):
        from PySide6.QtWidgets import QFileDialog
        import shutil
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Brush Files", "",
            "Brush Files (*.gbr *.gih *.vbr *.png *.jpg *.jpeg);;All Files (*)")
        if not paths: return
        os.makedirs(BRUSHES_DIR, exist_ok=True)
        for src in paths:
            dst = os.path.join(BRUSHES_DIR, os.path.basename(src))
            if src != dst:
                try: shutil.copy2(src, dst)
                except Exception: pass
        self._load_brushes()

    def _on_color_changed(self, color: QColor):
        name = color.name()
        self._fg_swatch.setStyleSheet(
            f"background:{name};border:1px solid #3a3a5a;border-radius:3px;")
        self._hex_lbl.setText(name.upper())

    # ── Accessors ─────────────────────────────────────────────────────────────
    def current_color(self)  -> QColor: return self._wheel.color()
    def brush_size(self)     -> int:    return int(self._size_sl.value())
    def brush_opacity(self)  -> float:  return self._opac_sl.value() / 100.0
    def brush_hardness(self) -> float:  return self._hard_sl.value() / 100.0
    def brush_spacing(self)  -> float:  return self._space_sl.value() / 100.0
    def brush_angle(self)    -> float:  return self._angle_sl.value()
    def brush_scatter(self)  -> float:  return self._scatter_sl.value() / 100.0

    # ── Painting ──────────────────────────────────────────────────────────────
    def paint_stroke(self, layer, doc_x: int, doc_y: int, erasing: bool = False):
        """
        Stamp one brush dab at (doc_x, doc_y) on layer.pil_image.

        erasing=True  → erase (write alpha=0) instead of painting.

        IMPORTANT: preview thumbnails are NEVER used as the paint stamp.
        The dab pipeline always reads raw brush data from the source file,
        resizes it to the current brush size, then composites it.
        """
        if not layer or not layer.pil_image: return
        color   = self.current_color()
        size    = self.brush_size()
        opacity = self.brush_opacity()
        hard    = self.brush_hardness()
        angle   = self.brush_angle()
        scatter = self.brush_scatter()

        # Convert document coords → layer pixel coords
        pw = layer.pil_image.width
        ph = layer.pil_image.height
        px = int((doc_x - layer.x) * pw / max(1, layer.w))
        py = int((doc_y - layer.y) * ph / max(1, layer.h))

        if scatter > 0:
            import random
            spread = int(size * scatter * 0.5)
            px += random.randint(-spread, spread)
            py += random.randint(-spread, spread)

        if erasing:
            self._erase_dab(layer.pil_image, px, py, size, opacity, hard)
        elif self._selected_brush and os.path.exists(self._selected_brush):
            self._stamp_brush(layer.pil_image, px, py, color, size, opacity, hard, angle)
        else:
            self._stamp_circle(layer.pil_image, px, py, color, size, opacity, hard, angle)
        layer.invalidate()

    def _erase_dab(self, img, px, py, size, opacity, hardness):
        """Erase a circular region — paint 0 alpha."""
        from PIL import ImageDraw, ImageFilter
        r     = max(1, size // 2)
        mask  = PILImage.new("L", (size, size), 0)
        draw  = ImageDraw.Draw(mask)
        draw.ellipse([0, 0, size - 1, size - 1], fill=int(opacity * 255))
        if hardness < 0.9:
            mask = mask.filter(
                ImageFilter.GaussianBlur(max(1, int((1 - hardness) * r * 0.6))))
        canvas = img.convert("RGBA")
        # For each pixel in the eraser dab region, multiply its alpha by (1 - erase_alpha)
        import numpy as np
        arr    = np.array(canvas, dtype=np.float32)
        mx     = np.array(mask,   dtype=np.float32) / 255.0  # 0..1
        # Paste region bounds
        x0, y0 = px - r, py - r
        x1, y1 = x0 + size, y0 + size
        # Clamp to image bounds
        cx0, cy0 = max(0, x0), max(0, y0)
        cx1, cy1 = min(arr.shape[1], x1), min(arr.shape[0], y1)
        if cx1 <= cx0 or cy1 <= cy0:
            return
        # Corresponding slice of the mask
        mx0, my0 = cx0 - x0, cy0 - y0
        mx1, my1 = mx0 + (cx1 - cx0), my0 + (cy1 - cy0)
        arr[cy0:cy1, cx0:cx1, 3] *= (1.0 - mx[my0:my1, mx0:mx1])
        result = PILImage.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
        img.paste(result.convert(img.mode))

    def _stamp_circle(self, img, px, py, color, size, opacity, hardness, angle=0.0):
        from PIL import ImageDraw, ImageFilter
        r     = max(1, size // 2)
        stamp = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
        draw  = ImageDraw.Draw(stamp)
        draw.ellipse([0, 0, size - 1, size - 1],
                     fill=(color.red(), color.green(), color.blue(),
                           int(opacity * 255)))
        if hardness < 0.9:
            stamp = stamp.filter(
                ImageFilter.GaussianBlur(max(1, int((1 - hardness) * r * 0.6))))
        if abs(angle) > 1.0:
            stamp = stamp.rotate(-angle, resample=PILImage.BICUBIC, expand=False)
        canvas = img.convert("RGBA")
        canvas.paste(stamp, (px - r, py - r), stamp)
        img.paste(canvas.convert(img.mode))

    # Per-brush raw image cache so we don't re-parse the binary on every stamp
    _brush_raw_cache: dict[str, object] = {}

    def _get_brush_raw(self) -> "PILImage.Image | None":
        """Return raw parsed brush image, cached per path."""
        path = self._selected_brush
        if not path:
            return None
        if path in self._brush_raw_cache:
            return self._brush_raw_cache[path]
        from app.ui.brushImporter import parse_gbr, parse_gih, parse_vbr
        ext = os.path.splitext(path)[1].lower()
        raw = None
        try:
            if   ext == ".gbr": raw = parse_gbr(path)
            elif ext == ".gih": raw = parse_gih(path)
            elif ext == ".vbr": raw = parse_vbr(path)
            elif ext in (".png", ".jpg", ".jpeg"):
                raw = PILImage.open(path).convert("RGBA")
        except Exception:
            pass
        if raw is not None:
            self._brush_raw_cache[path] = raw
        return raw

    def _stamp_brush(self, img, px, py, color, size, opacity, hardness=0.6, angle=0.0):
        """
        Stamp one dab of the selected brush onto img at pixel position (px, py).

        The brush alpha channel encodes the tip shape (0=transparent, 255=opaque).
        After resize we normalise the alpha so the peak always reaches full strength —
        this prevents blurry/washed-out stamps caused by LANCZOS downsampling
        smoothing out the high-frequency brush texture.
        """
        raw = self._get_brush_raw()
        if raw is None:
            self._stamp_circle(img, px, py, color, size, opacity, hardness, angle)
            return

        # ── 1. Scale to current brush size ────────────────────────────────────
        dab = raw.resize((size, size), PILImage.LANCZOS)

        # ── 2. Apply rotation ─────────────────────────────────────────────────
        if abs(angle) > 0.5:
            dab = dab.rotate(-angle, resample=PILImage.BICUBIC, expand=False)

        # ── 3. Extract alpha channel ──────────────────────────────────────────
        alpha_arr = np.array(dab.split()[3], dtype=np.float32)

        # ── 4. Normalise: rescale so the peak always reaches full strength ──────
        # LANCZOS downsampling averages pixels, crushing peak alpha on high-
        # frequency brushes. Normalising restores full contrast at any size.
        peak = alpha_arr.max()
        if peak > 1.0:
            alpha_arr = alpha_arr * (255.0 / peak)

        # ── 5. Apply hardness (Gaussian edge softening) ───────────────────────
        # Only blur noticeably when hardness < 0.5. At ≥0.5 the hardness blur
        # was killing the peak alpha and making every brush look like a soft fog.
        # After blur, re-normalise so we don't lose stamp strength.
        if hardness < 0.50:
            from PIL import ImageFilter
            blur_r = max(1, int((1.0 - hardness) * size * 0.30))
            alpha_img = PILImage.fromarray(alpha_arr.astype(np.uint8), "L")
            alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(blur_r))
            alpha_arr = np.array(alpha_img, dtype=np.float32)
            # Re-normalise after blur so peak stays at 255
            post_peak = alpha_arr.max()
            if post_peak > 1.0:
                alpha_arr = alpha_arr * (255.0 / post_peak)

        # ── 6. Apply opacity ──────────────────────────────────────────────────
        alpha_arr = (alpha_arr * opacity).clip(0, 255)

        # ── 7. Build tinted dab (solid brush colour + shaped alpha) ───────────
        r, g, b = color.red(), color.green(), color.blue()
        out = PILImage.new("RGBA", (size, size), (r, g, b, 0))
        out.putalpha(PILImage.fromarray(alpha_arr.astype(np.uint8), "L"))

        # ── 8. Composite onto layer ────────────────────────────────────────────
        half   = size // 2
        canvas = img.convert("RGBA")
        canvas.paste(out, (px - half, py - half), out)
        img.paste(canvas.convert(img.mode))

    def _on_color_picked_from_canvas(self, color):
        """Canvas color-picker tool sampled a color — push it to the wheel."""
        try:
            self._wheel.set_color(color)
            self._on_color_changed(color)
        except Exception:
            pass

    def _on_canvas_tool_shortcut(self, tool_mode):
        """Canvas handled a keyboard shortcut — sync our tool button highlight."""
        try:
            from app.ui.toolBar import ToolMode
            rev = {
                ToolMode.MOVE:         "move",
                ToolMode.BRUSH:        "brush",
                ToolMode.ERASER:       "eraser",
                ToolMode.RECTANGLE:    "rect",
                ToolMode.ELLIPSE:      "ellipse",
                ToolMode.COLOR_PICKER: "picker",
                ToolMode.HAND:         "hand",
                ToolMode.ZOOM:         "zoom",
            }
            tool_id = rev.get(tool_mode)
            if tool_id and tool_id != self._active_tool:
                self._active_tool = tool_id
                for tid, btn in self._tool_btns.items():
                    active = (tid == tool_id)
                    btn.blockSignals(True)
                    btn.setChecked(active)
                    btn.setStyleSheet(
                        self._TOOL_BTN_ACTIVE if active else self._TOOL_BTN_BASE
                    )
                    btn.blockSignals(False)
        except (ImportError, AttributeError):
            pass

    def _on_canvas_paint(self, doc_x: int, doc_y: int, erasing: bool = False):
        if not self._canvas: return
        layer = self._canvas.selected_layer()
        if layer and layer.kind in ("paint", "image", "texture"):
            self.paint_stroke(layer, doc_x, doc_y, erasing=erasing)
            self._canvas.update()