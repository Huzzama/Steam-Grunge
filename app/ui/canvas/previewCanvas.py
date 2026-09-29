from __future__ import annotations
import os
from typing import Optional, List, Tuple

import numpy as np
from PIL import Image as PILImage

from PySide6.QtWidgets import QWidget, QSizePolicy, QMenu
from PySide6.QtCore    import Qt, QPoint, QRect, QSize, QPointF, QRectF, Signal
from PySide6.QtGui     import (
    QPainter, QPixmap, QColor, QPen, QBrush,
    QFont, QKeyEvent, QMouseEvent, QContextMenuEvent, QAction,
    QFontDatabase,
)
from app.config           import COVER_SIZE, WIDE_SIZE, TEMPLATES_DIR, font_path
from app.ui.smartGuideLines import SmartGuides

# Canonical Layer definition — single source of truth
from app.ui.canvas.layers import Layer

HANDLE_SIZE = 12
HANDLE_HALF = HANDLE_SIZE // 2
MIN_SIZE    = 20

# ── Canvas ─────────────────────────────────────────────────────────────────────
class PreviewCanvas(QWidget):
    layer_selected        = Signal(int)
    layers_changed        = Signal()
    color_picked          = Signal(object)   # emits QColor when color-picker tool samples
    tool_shortcut_pressed = Signal(object)   # emits ToolMode when a key shortcut switches tool
    zoom_changed          = Signal(int)      # emits zoom % (int) so the zoom slider stays in sync

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background:#0e0e0e;")

        self._doc_size  = QSize(*COVER_SIZE)
        self._template  = "cover"
        self._layers:   List[Layer] = []
        self._sel       = -1

        # These are ALWAYS kept up-to-date by _update_viewport()
        self._scale  = 1.0
        self._ox     = 0
        self._oy     = 0

        self._smart_guides  = SmartGuides(self)
        self._guides_active = False
        self._drag_active   = False
        self._resize_active = False
        self._resize_corner = -1
        self._drag_start    = QPoint()
        self._orig_rect     = QRect()

        # ── Pan (middle mouse button) ────────────────────────────────────────
        self._pan_active    = False
        self._pan_start     = QPoint()
        self._pan_offset    = QPoint(0, 0)   # pixel offset from base-centered position

        # ── Rotation handle ─────────────────────────────────────────────────
        self._rotate_active    = False
        self._rotate_start_ang = 0.0         # angle at drag start
        self._rotate_orig_ang  = 0.0         # layer.rotation at drag start
        self._rotate_cx        = 0.0         # widget-space center X at press
        self._rotate_cy        = 0.0         # widget-space center Y at press

        # ── Aspect-ratio lock (held during corner resize) ────────────────────
        self._ar_ratio: float = 0.0          # w/h of layer at resize start
        self._resize_rotation: float = 0.0  # layer.rotation at resize start

        self._bg_pix:       Optional[QPixmap] = None
        self._template_pix: Optional[QPixmap] = None
        self._bg_color:     QColor = QColor(0, 0, 0)
        self._transparent_bg: bool  = False   # True for logo/icon templates

        # ── Undo / Redo ────────────────────────────────────────────────────────
        # Each entry is a list of shallow Layer copies (pil_image shared by
        # reference — images are only ever replaced, never mutated in place).
        # Every entry is the state AFTER a mutation; history[-1] == current.
        self._history:      List[list] = []
        self._redo_stack:   List[list] = []
        self._MAX_HISTORY   = 60
        self._last_hist_key = None     # coalescing key for slider drags
        self._last_hist_time = 0.0

        # ── Crop tool ──────────────────────────────────────────────────────────
        self._crop_mode     = False
        self._crop_rect:    Optional[QRect] = None   # in doc coords
        self._crop_drag_handle = -1   # -1=none, 0-3=corner, 4=move
        self._crop_drag_start  = QPoint()
        self._crop_orig_rect:  Optional[QRect] = None

        # ── Zoom ───────────────────────────────────────────────────────────────
        self._zoom_factor: float = 1.0

        # ── Canvas view rotation (degrees, view-only — does not affect export) ─
        self._view_angle:  float = 0.0

        # ── Effects overlay (film grain + chromatic aberration, rendered live) ─
        self._effects_pix:    Optional[QPixmap] = None
        self._fx_cache:       Optional[QPixmap] = None   # processed composite cache
        self._fx_cache_key:   tuple = ()                  # (grain, ca) that built cache
        self._effects_grain:  float = 0.0
        self._effects_ca:     float = 0.0
        self._grain_seed:     int   = 1337   # fixed → preview == export

        # ── Tool mode ──────────────────────────────────────────────────────────
        # Import lazily to avoid any circular-import issues during startup
        try:
            from app.ui.toolBar import ToolMode
        except ImportError:
            # Fallback stub so the canvas still works standalone
            from enum import Enum, auto
            class ToolMode(Enum):   # type: ignore[no-redef]
                MOVE=auto(); BRUSH=auto(); ERASER=auto()
                RECTANGLE=auto(); ELLIPSE=auto()
                COLOR_PICKER=auto(); HAND=auto(); ZOOM=auto()

        self._ToolMode = ToolMode
        self._tool     = ToolMode.MOVE           # active tool

        # ── Brush / eraser mode (legacy attribute kept for back-compat) ──────────
        self._brush_mode = False                 # True when tool==BRUSH or ERASER
        self.brush_paint_requested = None        # callable(doc_x, doc_y, eraser=False)

        # ── Shape drawing (RECTANGLE / ELLIPSE) ──────────────────────────────────
        self._shape_drawing   = False            # drag in progress
        self._shape_start_doc = QPoint()         # doc-space anchor point
        self._shape_cur_doc   = QPoint()         # doc-space current point

        # ── Hand tool state ────────────────────────────────────────────────────
        self._hand_active = False
        self._hand_start  = QPoint()

        self._load_template_pix("cover")
        self._push_history()

    # ── viewport ───────────────────────────────────────────────────────────────
    def _update_viewport(self):
        """Recompute scale + offset so the document fits the widget, with zoom + pan."""
        W, H   = max(self.width(), 1), max(self.height(), 1)
        dw, dh = self._doc_size.width(), self._doc_size.height()
        base   = min(W / dw, H / dh) * 0.92
        self._scale = base * self._zoom_factor
        self._ox = int((W - dw * self._scale) / 2) + self._pan_offset.x()
        self._oy = int((H - dh * self._scale) / 2) + self._pan_offset.y()

    # ── Tool API ───────────────────────────────────────────────────────────────
    def set_tool(self, mode):
        """
        Set the active tool mode.  Accepts a ToolMode enum value.
        Updates cursor and legacy _brush_mode flag for back-compat.
        """
        self._tool = mode
        TM = self._ToolMode

        # Legacy flag keeps old brush_paint_requested pathway working
        self._brush_mode = mode in (TM.BRUSH, TM.ERASER)

        # Cancel any in-progress shape draw when tool changes
        self._shape_drawing = False

        cursor_map = {
            TM.MOVE:         Qt.ArrowCursor,
            TM.BRUSH:        Qt.CrossCursor,
            TM.ERASER:       Qt.CrossCursor,
            TM.RECTANGLE:    Qt.CrossCursor,
            TM.ELLIPSE:      Qt.CrossCursor,
            TM.COLOR_PICKER: Qt.CrossCursor,
            TM.HAND:         Qt.OpenHandCursor,
            TM.ZOOM:         Qt.CrossCursor,
        }
        self.setCursor(cursor_map.get(mode, Qt.ArrowCursor))
        self.update()

    def active_tool(self):
        return self._tool

    # ── Legacy enter/exit brush mode (kept for any external callers) ───────────
    def enter_brush_mode(self):
        self.set_tool(self._ToolMode.BRUSH)

    def exit_brush_mode(self):
        self.set_tool(self._ToolMode.MOVE)

    def set_zoom(self, factor: float):
        """Set zoom factor (0.25–4.0). 1.0 = fit to window."""
        self._zoom_factor = max(0.25, min(4.0, factor))
        self._update_viewport()
        self.zoom_changed.emit(round(self._zoom_factor * 100))
        self.update()

    def set_view_angle(self, angle: float):
        """Rotate the canvas view (degrees). View-only — export is unaffected."""
        self._view_angle = angle % 360
        self.update()

    def update_effects_overlay(self, film_grain: float, chromatic_aberration: float):
        """Store global effect params and trigger a repaint.
        Effects are now applied as true post-processing on the full composite
        in _build_composited_pix(), not as a separate overlay texture.
        """
        self._effects_grain = film_grain
        self._effects_ca    = chromatic_aberration
        self._effects_pix   = None   # no longer used for display
        self._fx_cache      = None   # invalidate processed snapshot cache
        self.update()

    # ── Post-processing helpers (applied to the full composite) ────────────────

    @staticmethod
    def _apply_film_grain(arr: "np.ndarray", strength: float,
                          seed: int = 0) -> "np.ndarray":
        """Add luminance-based random noise to an RGBA numpy array in-place.

        The noise is generated from *seed* so the same document always gets
        the same grain: preview and export match, and the grain does not
        "crawl" every time the canvas repaints."""
        if strength <= 0:
            return arr
        sigma = strength * 0.35          # 0–100 → 0–35 std-dev
        h, w  = arr.shape[:2]
        rng   = np.random.default_rng(seed)
        noise = rng.normal(0, sigma, (h, w)).astype(np.float32)
        # Apply to R,G,B channels equally (preserves alpha)
        for c in range(3):
            arr[:, :, c] = np.clip(arr[:, :, c].astype(np.float32) + noise, 0, 255)
        return arr

    @staticmethod
    def _apply_chromatic_aberration(arr: "np.ndarray", strength: float) -> "np.ndarray":
        """Shift R and B channels horizontally in opposite directions."""
        if strength <= 0:
            return arr
        shift = max(1, int(strength * 0.15))   # 0–100 → 0–15 px shift
        # Shift R channel left, B channel right (classic CA look)
        arr[:, :, 0] = np.roll(arr[:, :, 0],  shift, axis=1)   # R → right
        arr[:, :, 2] = np.roll(arr[:, :, 2], -shift, axis=1)   # B → left
        # Black out the border columns where roll wrapped to avoid artefacts
        arr[:, :shift,  0] = 0
        arr[:, -shift:, 2] = 0
        return arr

    def _canvas_rect(self) -> QRect:
        dw, dh = self._doc_size.width(), self._doc_size.height()
        return QRect(self._ox, self._oy,
                     int(dw * self._scale), int(dh * self._scale))

    def _w2c(self, p: QPoint) -> QPoint:
        return QPoint(int((p.x() - self._ox) / self._scale),
                      int((p.y() - self._oy) / self._scale))

    def _c2w(self, p: QPoint) -> QPoint:
        return QPoint(int(p.x() * self._scale + self._ox),
                      int(p.y() * self._scale + self._oy))

    def _c2w_f(self, x: float, y: float) -> "QPointF":
        """Sub-pixel precision world→widget transform (no int truncation).
        Used for drawing handles and bounding boxes to eliminate 1-px jitter."""
        from PySide6.QtCore import QPointF
        return QPointF(x * self._scale + self._ox,
                       y * self._scale + self._oy)

    def _layer_wrect(self, l: Layer) -> QRect:
        tl = self._c2w(QPoint(l.x,       l.y))
        br = self._c2w(QPoint(l.x + l.w, l.y + l.h))
        return QRect(tl, br)

    def _layer_wrect_f(self, l: Layer) -> "QRectF":
        """Sub-pixel precision layer bounding rect for drawing and hit-testing.
        Eliminates the 1-px jitter caused by int() truncation in _layer_wrect."""
        from PySide6.QtCore import QRectF
        x1 = l.x       * self._scale + self._ox
        y1 = l.y       * self._scale + self._oy
        x2 = (l.x + l.w) * self._scale + self._ox
        y2 = (l.y + l.h) * self._scale + self._oy
        return QRectF(x1, y1, x2 - x1, y2 - y1)

    # ── rotated handle geometry ────────────────────────────────────────────────
    def _rot_matrix(self, angle_deg: float):
        """Return (cos, sin) for angle in degrees."""
        import math
        a = math.radians(angle_deg)
        return math.cos(a), math.sin(a)

    def _rotate_point(self, px: float, py: float,
                      cx: float, cy: float,
                      cos_a: float, sin_a: float):
        """Rotate point (px,py) around (cx,cy)."""
        dx, dy = px - cx, py - cy
        return cx + dx*cos_a - dy*sin_a, cy + dx*sin_a + dy*cos_a

    def _handle_points(self, l: Layer):
        """
        Return 9 QPointF handle centres in widget space, rotated with the layer.
        Indices 0-7 = resize handles, 8 = rotation knob.

        JITTER FIX: uses _layer_wrect_f (float precision) instead of
        _layer_wrect (int-truncated) so handle positions don't snap to
        whole pixels as the layer moves — eliminates 1-px jitter.
        """
        from PySide6.QtCore import QPointF
        import math

        wr   = self._layer_wrect_f(l)      # <-- float rect, no truncation
        cx   = wr.left()  + wr.width()  / 2.0
        cy   = wr.top()   + wr.height() / 2.0
        rot  = l.rotation if hasattr(l, 'rotation') else 0.0
        rad  = math.radians(rot)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        def rp(x, y):
            # Rotate (x, y) around (cx, cy) by rot degrees
            dx, dy = x - cx, y - cy
            return QPointF(cx + dx*cos_a - dy*sin_a,
                           cy + dx*sin_a + dy*cos_a)

        l_  = wr.left()
        r_  = wr.right()
        t_  = wr.top()
        b_  = wr.bottom()
        mx  = cx          # mid-x
        my  = cy          # mid-y

        pts = [
            rp(l_, t_),   # 0 TL
            rp(mx, t_),   # 1 T
            rp(r_, t_),   # 2 TR
            rp(r_, my),   # 3 R
            rp(r_, b_),   # 4 BR
            rp(mx, b_),   # 5 B
            rp(l_, b_),   # 6 BL
            rp(l_, my),   # 7 L
        ]

        # Rotation knob: STEM_LEN px above the rotated top-centre (handle 1).
        # "Above" in rotated space = move opposite to the local-down direction.
        # local-down = (sin_a, cos_a) in screen space  (Qt: Y increases downward)
        # local-up   = (-sin_a, -cos_a)
        STEM_LEN = 32.0
        tc = pts[1]  # already the rotated top-centre
        pts.append(QPointF(tc.x() - sin_a * STEM_LEN,
                           tc.y() - cos_a * STEM_LEN))   # 8 ROT
        return pts

    def _handles(self, l: Layer):
        """Legacy: return QRects for the 8 resize handles (axis-aligned, for non-rotated compat)."""
        # Only called for cursors / non-rotated fallback; real drawing uses _handle_points
        return []   # drawing now done entirely in _paint_selected_overlay

    def _hit_handle(self, l: Layer, pos: QPoint) -> int:
        """Hit-test all 9 handles using distance to point (rotation-aware).
        Rotation knob (index 8) is checked first and has a larger hit radius."""
        from PySide6.QtCore import QPointF
        pts = self._handle_points(l)
        p   = QPointF(pos.x(), pos.y())

        # Check rotation knob first — larger radius so it's easy to grab
        ROT_THRESH = HANDLE_HALF + 9
        rh = pts[8]
        dx, dy = rh.x() - p.x(), rh.y() - p.y()
        if dx*dx + dy*dy <= ROT_THRESH * ROT_THRESH:
            return 8

        # Resize handles
        THRESH = HANDLE_HALF + 5
        for i, hp in enumerate(pts[:8]):
            dx, dy = hp.x() - p.x(), hp.y() - p.y()
            if dx*dx + dy*dy <= THRESH * THRESH:
                return i
        return -1

    def _is_locked(self, layer: Layer) -> bool:
        """Return True if layer is locked, OR if it belongs to a locked group."""
        if getattr(layer, 'locked', False):
            return True
        parent_idx = getattr(layer, '_group_parent', None)
        if parent_idx is not None and 0 <= parent_idx < len(self._layers):
            parent = self._layers[parent_idx]
            if getattr(parent, 'locked', False):
                return True
        return False

    def _hit_layer(self, pos: QPoint) -> int:
        """Hit-test layers top-to-bottom. Skips groups (invisible) and locked layers."""
        import math
        for i in range(len(self._layers)-1, -1, -1):
            l = self._layers[i]
            if not l.visible:          continue
            if l.kind == "group":      continue   # groups have no canvas body
            if self._is_locked(l):     continue   # locked layers are untouchable
            rot = l.rotation if hasattr(l, 'rotation') else 0.0
            if rot == 0.0:
                if l.rect.contains(self._w2c(pos)):
                    return i
            else:
                wr  = self._layer_wrect(l)
                cx  = (wr.left()  + wr.right())  / 2.0
                cy  = (wr.top()   + wr.bottom()) / 2.0
                cos_a, sin_a = self._rot_matrix(-rot)
                dx, dy = pos.x() - cx, pos.y() - cy
                lx = dx*cos_a - dy*sin_a
                ly = dx*sin_a + dy*cos_a
                hw, hh = wr.width()/2.0, wr.height()/2.0
                if abs(lx) <= hw and abs(ly) <= hh:
                    return i
        return -1

    # ── public API ─────────────────────────────────────────────────────────────
    def doc_size(self) -> QSize:
        """Return the current document size (width × height) as a QSize."""
        return QSize(self._doc_size)

    def template_key(self) -> str:
        """Return the current template identifier (e.g. 'cover', 'wide', 'hero').

        Use this instead of reading canvas._template externally.
        AppState is the declarative owner of the desired template key;
        this accessor reflects what the canvas was last told to render.
        """
        return self._template

    def set_template(self, tpl: str):
        from app.config import COVER_SIZE, WIDE_SIZE, VHS_COVER_SIZE, HERO_SIZE, LOGO_SIZE, ICON_SIZE
        size_map = {
            "cover":        COVER_SIZE,
            "vhs_cover":    VHS_COVER_SIZE,
            "wide":         WIDE_SIZE,
            "vhs_pile":     WIDE_SIZE,
            "vhs_cassette": WIDE_SIZE,
            "hero":         HERO_SIZE,
            "logo":         LOGO_SIZE,
            "icon":         ICON_SIZE,
        }
        new_size        = QSize(*size_map.get(tpl, COVER_SIZE))
        new_transparent = tpl in {"logo", "icon"}

        # Only reset pan/zoom when the doc canvas size actually changes.
        # Skipping this reset on same-size template changes preserves the
        # user's current view position when effects, colours, or unrelated
        # tab-state changes trigger a schedule_compose().
        if new_size != self._doc_size:
            self._pan_offset = QPoint(0, 0)

        self._template       = tpl
        self._transparent_bg = new_transparent
        self._doc_size       = new_size
        self._load_template_pix(tpl)
        self._bg_pix         = None
        self._update_viewport()
        self.update()

    def _load_template_pix(self, tpl: str):
        """Load the template overlay PNG for the given template key."""
        # Explicit filename map for templates whose filenames don't follow the generic pattern
        EXPLICIT = {
            "vhs_pile":     "pile_of_vhs_template_wide.png",
            "vhs_cassette": "vhs_cassette_template_wide.png",
        }
        if tpl in EXPLICIT:
            path = os.path.join(TEMPLATES_DIR, EXPLICIT[tpl])
            self._template_pix = QPixmap(path) if os.path.exists(path) else None
            return
        # Generic fallback: template_{tpl}.png  or  {tpl}_template.png
        candidates = [
            os.path.join(TEMPLATES_DIR, f"template_{tpl}.png"),
            os.path.join(TEMPLATES_DIR, f"{tpl}_template.png"),
        ]
        for path in candidates:
            if os.path.exists(path):
                self._template_pix = QPixmap(path)
                return
        self._template_pix = None

    def set_background_color(self, color: QColor):
        """Set the solid background color shown behind the template PNG."""
        self._bg_color = color
        self.update()

    def set_background(self, pil: PILImage.Image):
        """Set filter-composed background overlay (PIL → QPixmap, no PNG round-trip)."""
        import numpy as np
        from PySide6.QtGui import QImage
        arr = np.ascontiguousarray(np.array(pil.convert("RGBA"), dtype=np.uint8))
        h, w = arr.shape[:2]
        qi = QImage(arr.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        self._bg_pix = QPixmap.fromImage(qi)
        self._fx_cache = None   # bg changed → invalidate FX composite
        self.update()

    # backward compat
    def set_image(self, pil): self.set_background(pil)

    @property
    def layers(self): return self._layers

    def add_layer(self, layer: Layer):
        self._layers.append(layer)
        self._sel = len(self._layers) - 1
        # Invalidate FX composite cache — layer stack changed
        self._fx_cache = None
        self._effects_pix = None
        self._push_history()
        self.layer_selected.emit(self._sel)
        self.layers_changed.emit()
        self.update()

    def add_image_layer(self, path: str, name: str = "") -> Layer:
        img = PILImage.open(path).convert("RGBA")
        dw, dh = self._doc_size.width(), self._doc_size.height()
        img.thumbnail((dw, dh), PILImage.LANCZOS)
        w, h = img.size
        layer = Layer(kind="image",
                      name=name or os.path.basename(path),
                      x=(dw-w)//2, y=(dh-h)//2, w=w, h=h,
                      pil_image=img, source_path=path)
        self.add_layer(layer)
        return layer

    def add_text_layer(self, text="Text", font_name="default",
                       font_size=48, color=(255,255,255)) -> Layer:
        dw, dh = self._doc_size.width(), self._doc_size.height()
        layer = Layer(kind="text", name=f"T: {text[:12]}",
                      x=dw//4, y=dh//2-font_size,
                      w=dw//2, h=font_size+20,
                      text=text, font_name=font_name,
                      font_size=font_size, font_color=color)
        self.add_layer(layer)
        return layer

    def remove_layer(self, idx: int):
        if 0 <= idx < len(self._layers):
            self._layers.pop(idx)
            self._sel = min(self._sel, len(self._layers)-1)
            # Invalidate FX composite cache — layer stack changed
            self._fx_cache = None
            self._effects_pix = None
            self._push_history()
            self.layer_selected.emit(self._sel)
            self.layers_changed.emit(); self.update()

    def move_layer_up(self, idx: int):
        if idx < len(self._layers)-1:
            self._layers[idx], self._layers[idx+1] = self._layers[idx+1], self._layers[idx]
            self._sel = idx+1
            self._fx_cache = None
            self._effects_pix = None
            self._push_history()
            self.layers_changed.emit(); self.update()

    def move_layer_down(self, idx: int):
        if idx > 0:
            self._layers[idx], self._layers[idx-1] = self._layers[idx-1], self._layers[idx]
            self._sel = idx-1
            self._fx_cache = None
            self._effects_pix = None
            self._push_history()
            self.layers_changed.emit(); self.update()

    # ── Clean public authority API ─────────────────────────────────────────
    # All UI code must call these methods. Direct mutation of _sel, _layers,
    # or any other hidden canvas field from outside is a bug.

    def select_layer(self, canvas_idx: int):
        """Select a layer by canvas index. Emits layer_selected + repaints."""
        self._sel = max(-1, min(canvas_idx, len(self._layers) - 1))
        self.layer_selected.emit(self._sel)
        self.update()

    def set_layer_visibility(self, canvas_idx: int, visible: bool):
        """Toggle layer visibility. Does not push undo (non-destructive)."""
        if 0 <= canvas_idx < len(self._layers):
            self._layers[canvas_idx].visible = visible
            self._fx_cache = None
            self.layers_changed.emit()
            self.update()

    def set_layer_locked(self, canvas_idx: int, locked: bool):
        """Set layer locked state."""
        if 0 <= canvas_idx < len(self._layers):
            self._layers[canvas_idx].locked = locked
            self.layers_changed.emit()

    def reorder_layers(self, new_layer_list: list):
        """
        Replace the layer stack with a reordered list of the SAME Layer
        objects. Tracks the currently selected Layer object and re-finds its
        position in the new order.  Pushes undo, emits layers_changed.
        """
        if len(new_layer_list) != len(self._layers):
            return  # safety guard against count mismatches
        sel_obj = (self._layers[self._sel]
                   if 0 <= self._sel < len(self._layers) else None)
        self._layers = new_layer_list
        if sel_obj is not None:
            try:
                self._sel = self._layers.index(sel_obj)
            except ValueError:
                self._sel = max(0, len(self._layers) - 1)
        self._fx_cache = None
        self._effects_pix = None
        self._push_history()
        self.layers_changed.emit()
        self.update()

    def clear_canvas(self):
        """
        Reset canvas to empty state (new document / discard all layers).
        Clears undo history and FX cache. Does NOT reset pan — caller may
        call reset_pan() separately if desired.
        """
        self._layers.clear()
        self._sel = -1
        self._fx_cache = None
        self._effects_pix = None
        self._history.clear()
        self._redo_stack.clear()
        self._push_history()
        self.layers_changed.emit()
        self.layer_selected.emit(-1)
        self.update()

    def duplicate_selected_layer(self, offset: int = 20):
        """
        Duplicate the selected layer using the safe clone_for_duplicate() path.
        Selects the new layer after insertion. Returns the new Layer or None.
        """
        layer = self.selected_layer()
        if layer is None:
            return None
        new_layer = layer.clone_for_duplicate(offset=offset)
        self._layers.append(new_layer)
        self._sel = len(self._layers) - 1
        self._fx_cache = None
        self._effects_pix = None
        self._push_history()
        self.layer_selected.emit(self._sel)
        self.layers_changed.emit()
        self.update()
        return new_layer

    def selected_layer(self) -> Optional[Layer]:
        return self._layers[self._sel] if 0 <= self._sel < len(self._layers) else None

    def selected_layer_index(self) -> int:
        """Return the currently selected layer index, or -1 if nothing selected.
        UI code must call this instead of reading _sel directly."""
        return self._sel

    def update_selected_layer(self, **kw):
        """Set attributes on the selected layer and record ONE undo step.
        Rapid successive calls with the same attribute set (a slider drag)
        are coalesced into a single history entry."""
        l = self.selected_layer()
        if l:
            for k, v in kw.items():
                if hasattr(l, k): setattr(l, k, v)
            l.invalidate()
            self._fx_cache = None
            self._push_history(coalesce_key=(id(l), tuple(sorted(kw))))
            self.layers_changed.emit(); self.update()

    def update_layer_no_history(self, **kw):
        """Apply field updates to the selected layer WITHOUT pushing undo history.
        Use for high-frequency slider feedback (brightness, contrast, saturation)
        where pushing an undo entry on every tick would flood the undo stack.
        Still invalidates the layer pixmap cache and FX composite cache."""
        l = self.selected_layer()
        if l:
            changed = False
            for k, v in kw.items():
                if hasattr(l, k):
                    setattr(l, k, v)
                    changed = True
            if changed:
                l._pix = None
                l._pix_dirty = True
                self._fx_cache = None
                self.update()

    def invalidate_fx_cache(self):
        """Invalidate the FX composite cache so the next paint rebuilds it.
        Call this whenever anything that affects the full-scene render changes."""
        self._fx_cache = None
        self._effects_pix = None
        self.update()

    def invalidate_layer_cache(self, layer: Layer):
        """Invalidate the pixmap cache for a specific layer and the FX composite.
        Use this when the layer's PIL image has been modified externally
        (e.g. after a pixel-level edit) and a redraw is needed.
        Does NOT push undo history — caller is responsible for that if needed."""
        layer._pix = None
        layer._pix_dirty = True
        self._fx_cache = None
        self._effects_pix = None
        self.layers_changed.emit()
        self.update()

    def replace_selected_layer_image(self, new_pil_image):
        """Replace the PIL image of the selected layer, push undo, and redraw.
        Use this for pixel-level image edits (e.g. colour replace operations)
        that change the layer content but not its geometry."""
        layer = self.selected_layer()
        if layer is None:
            return
        layer.pil_image = new_pil_image
        layer._pix = None
        layer._pix_dirty = True
        self._fx_cache = None
        self._effects_pix = None
        self._push_history()
        self.layers_changed.emit()
        self.update()

    def layer_widget_rect(self, layer: Layer) -> "QRect":
        """Return the widget-space bounding rect for a layer.
        Public alias for _layer_wrect — use this from outside the canvas."""
        return self._layer_wrect(layer)

    def replace_layers(self, layers: list, selected_index: int = -1):
        """
        Replace the entire layer stack for project-load bootstrap.
        This is the ONLY sanctioned path for bulk layer replacement from outside
        the canvas (e.g. projectIO.load_project).

        - Resets all interaction state (drag, resize, rotate, pan, crop, shape).
        - Clears FX and pixmap caches.
        - Clears undo/redo history and pushes one clean entry for the loaded state.
        - Does NOT reset pan/zoom — caller must call reset_pan() if desired.
        - Emits layers_changed and layer_selected.
        """
        # Cancel any in-progress interaction so no stale state leaks
        self._drag_active      = False
        self._resize_active    = False
        self._rotate_active    = False
        self._pan_active       = False
        self._hand_active      = False
        self._guides_active    = False
        self._crop_mode        = False
        self._crop_rect        = None
        self._crop_drag_handle = -1
        self._shape_drawing    = False

        # Clear all caches
        self._fx_cache      = None
        self._fx_cache_key  = ()
        self._effects_pix   = None

        # Clear undo history — project load is the new baseline
        self._history.clear()
        self._redo_stack.clear()

        # Invalidate per-layer pixmap caches so they rebuild from PIL data
        for layer in layers:
            layer._pix = None
            layer._pix_dirty = True
            if hasattr(layer, '_transform_dirty'):
                layer._transform_dirty = False

        # Replace layer stack and selection
        self._layers = layers
        if layers:
            self._sel = max(0, min(selected_index, len(layers) - 1))
        else:
            self._sel = -1

        # Push one clean history entry so undo doesn't go below loaded state
        self._push_history()

        self.layers_changed.emit()
        self.layer_selected.emit(self._sel)
        self.update()

    # ── Undo / Redo ────────────────────────────────────────────────────────────
    @staticmethod
    def _copy_layer(l: Layer) -> Layer:
        """Shallow copy safe for history: own attribute dict, no pixmap cache,
        own copies of the mutable list fields, shared (immutable) PIL image."""
        import copy
        lc = copy.copy(l)
        lc._pix = None
        lc._pix_dirty = True
        if l.vector_paths:
            lc.vector_paths = [dict(pth) for pth in l.vector_paths]
        return lc

    def _snapshot(self) -> tuple:
        """(layer copies, selected index)"""
        return ([self._copy_layer(l) for l in self._layers], self._sel)

    def _push_history(self, coalesce_key=None):
        """
        Record the CURRENT state (call after mutating).

        coalesce_key: pass the same key for a burst of rapid changes (a slider
        drag) — the top entry is replaced instead of appended, so one drag is
        one undo step and the entry below is the state before the drag began.
        """
        import time
        now  = time.monotonic()
        snap = self._snapshot()
        if (coalesce_key is not None and self._history
                and coalesce_key == self._last_hist_key
                and now - self._last_hist_time < 1.0):
            self._history[-1] = snap
        else:
            self._history.append(snap)
            if len(self._history) > self._MAX_HISTORY:
                self._history.pop(0)
        self._last_hist_key  = coalesce_key
        self._last_hist_time = now
        self._redo_stack.clear()

    def _restore(self, snap: tuple):
        layers, sel = snap
        self._layers = [self._copy_layer(l) for l in layers]
        self._sel = sel if 0 <= sel < len(self._layers) else len(self._layers) - 1
        self._fx_cache = None
        self._effects_pix = None
        self._last_hist_key = None
        # Drop any interaction that was in progress on the old objects
        self._drag_active = self._resize_active = self._rotate_active = False
        self._crop_mode = False
        self._crop_rect = None
        self._smart_guides.clear()
        self.layer_selected.emit(self._sel)
        self.layers_changed.emit()
        self.update()

    def undo(self):
        if len(self._history) <= 1:
            return
        self._redo_stack.append(self._history.pop())
        self._restore(self._history[-1])

    def redo(self):
        if not self._redo_stack:
            return
        self._history.append(self._redo_stack.pop())
        self._restore(self._history[-1])

    # ── Crop tool ──────────────────────────────────────────────────────────────
    def enter_crop_mode(self):
        """Activate interactive crop tool for the selected layer."""
        l = self.selected_layer()
        if not l or l.kind not in ("image", "texture"):
            return
        self._crop_mode = True
        # Default crop rect = full layer bounds
        self._crop_rect = QRect(l.x, l.y, l.w, l.h)
        self.setCursor(Qt.CrossCursor)
        self.update()

    def exit_crop_mode(self, apply: bool = False):
        """Exit crop mode. If apply=True, commit the crop to the layer."""
        if apply and self._crop_rect and self._crop_mode:
            l = self.selected_layer()
            if l and l.pil_image and l.w > 0 and l.h > 0:
                cr = self._crop_rect
                lx, ly = l.x, l.y
                # Convert crop rect (doc coords) to pixel coords within the layer
                pw = l.pil_image.width;  ph = l.pil_image.height
                sx = pw / l.w;  sy = ph / l.h
                px1 = int(max(0, (cr.left()  - lx) * sx))
                py1 = int(max(0, (cr.top()   - ly) * sy))
                px2 = int(min(pw, (cr.right() - lx) * sx))
                py2 = int(min(ph, (cr.bottom()- ly) * sy))
                if px2 > px1 and py2 > py1:
                    l.pil_image = l.pil_image.crop((px1, py1, px2, py2))
                    # Update layer rect to match crop
                    l.x, l.y = cr.left(), cr.top()
                    l.w, l.h = cr.width(), cr.height()
                    l.invalidate()
                    self._fx_cache = None
                    self._push_history()
                self.layers_changed.emit()
        self._crop_mode = False
        self._crop_rect = None
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def _crop_handle_rects(self) -> List[QRect]:
        """4 corner handles for crop rect in widget coords."""
        if not self._crop_rect:
            return []
        r = self._crop_rect
        corners = [QPoint(r.left(), r.top()), QPoint(r.right(), r.top()),
                   QPoint(r.right(), r.bottom()), QPoint(r.left(), r.bottom())]
        hs = 10
        return [QRect(self._c2w(c).x()-hs//2, self._c2w(c).y()-hs//2, hs, hs)
                for c in corners]

    def _hit_crop_handle(self, pos: QPoint) -> int:
        for i, hr in enumerate(self._crop_handle_rects()):
            if hr.contains(pos):
                return i
        return -1

    # ── paint ──────────────────────────────────────────────────────────────────
    def _draw_checkerboard(self, painter: QPainter, rect: QRect, tile: int = 12):
        """Draw a grey/white checkerboard to indicate a transparent canvas background."""
        col_a = QColor(180, 180, 180)
        col_b = QColor(120, 120, 120)
        painter.save()
        painter.setClipRect(rect)
        x0, y0 = rect.left(), rect.top()
        cols = (rect.width()  // tile) + 2
        rows = (rect.height() // tile) + 2
        for row in range(rows):
            for col in range(cols):
                color = col_a if (row + col) % 2 == 0 else col_b
                painter.fillRect(
                    x0 + col * tile,
                    y0 + row * tile,
                    tile, tile,
                    color,
                )
        painter.restore()

    def paintEvent(self, _):
        self._update_viewport()          # always fresh before drawing
        cr = self._canvas_rect()
        p  = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)

        # ── Apply view rotation around canvas center ───────────────────────────
        if self._view_angle != 0.0:
            cx = cr.x() + cr.width()  / 2.0
            cy = cr.y() + cr.height() / 2.0
            p.translate(cx, cy)
            p.rotate(self._view_angle)
            p.translate(-cx, -cy)

        fx_active = (getattr(self, "_effects_grain", 0) > 0 or
                     getattr(self, "_effects_ca", 0) > 0)

        interacting = (self._drag_active or self._resize_active or
                        self._rotate_active or self._pan_active or self._hand_active)

        if fx_active and not interacting:
            # ── FX path (idle): render scene offscreen, apply FX, draw result ──
            # Only runs when no interaction is in progress, so the offscreen
            # QPixmap allocation and numpy pass never slow down drag/rotate.
            scene_pix = self._render_scene_to_pixmap(cr)
            scene_pix = self._apply_fx_to_pixmap(scene_pix)
            p.drawPixmap(cr.topLeft(), scene_pix)
        else:
            # ── Direct paint path ──────────────────────────────────────────────
            # Used for: no FX, OR any active interaction (drag/rotate/resize/pan).
            # During interaction this path is always taken — it is the fastest
            # possible render with zero allocation overhead.
            self._render_scene(p, cr, export=False)

        # canvas border
        p.setPen(QPen(QColor(55,55,55), 1))
        p.drawRect(cr)

        # ── Shape rubber-band ghost ────────────────────────────────────────────
        if self._shape_drawing:
            self._draw_shape_ghost(p)

        # ── Crop overlay ───────────────────────────────────────────────────────
        if self._crop_mode and self._crop_rect:
            # Darken area outside crop rect
            cr_w = self._c2w(QPoint(self._crop_rect.left(),  self._crop_rect.top()))
            cr_br = self._c2w(QPoint(self._crop_rect.right(), self._crop_rect.bottom()))
            crop_wr = QRect(cr_w, cr_br)

            p.setBrush(QBrush(QColor(0, 0, 0, 140)))
            p.setPen(Qt.NoPen)
            # Top strip
            p.drawRect(QRect(cr.left(), cr.top(), cr.width(), crop_wr.top() - cr.top()))
            # Bottom strip
            p.drawRect(QRect(cr.left(), crop_wr.bottom(), cr.width(), cr.bottom() - crop_wr.bottom()))
            # Left strip
            p.drawRect(QRect(cr.left(), crop_wr.top(), crop_wr.left() - cr.left(), crop_wr.height()))
            # Right strip
            p.drawRect(QRect(crop_wr.right(), crop_wr.top(), cr.right() - crop_wr.right(), crop_wr.height()))

            # Crop border + rule-of-thirds grid
            p.setPen(QPen(QColor(255, 220, 80), 2, Qt.SolidLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(crop_wr)

            # Rule of thirds lines
            p.setPen(QPen(QColor(255, 220, 80, 80), 1, Qt.DashLine))
            for i in (1, 2):
                x = crop_wr.left() + crop_wr.width() * i // 3
                y = crop_wr.top() + crop_wr.height() * i // 3
                p.drawLine(x, crop_wr.top(), x, crop_wr.bottom())
                p.drawLine(crop_wr.left(), y, crop_wr.right(), y)

            # Corner handles
            p.setBrush(QBrush(QColor(255, 220, 80)))
            p.setPen(QPen(QColor(30, 30, 30), 1))
            for hr in self._crop_handle_rects():
                p.drawRect(hr)

            # Instructions
            p.setPen(QPen(QColor(255, 220, 80)))
            p.setFont(QFont("Courier New", 10))
            p.drawText(cr.left() + 6, cr.bottom() - 8,
                       "✂  Drag corners to crop  |  Enter = Apply  |  Esc = Cancel")

        # Smart guides
        if self._guides_active:
            self._smart_guides.draw(p, self._canvas_rect())

        # Selection overlay — ALWAYS drawn last so global FX cannot cover it.
        # Uses QTransform.map to compute the true rotated polygon geometry.
        if not self._crop_mode:
            self._paint_selection_overlay(p)

        p.end()

    # ── Selection overlay ─────────────────────────────────────────────────────

    def _paint_selection_overlay(self, p: QPainter):
        """
        Draw the selection bounding box, resize handles, and rotation knob
        on top of ALL composited content (including global FX).

        Key correctness guarantees:
        - Called after _draw_with_global_fx so FX never paints over the handles.
        - Uses QTransform.map to compute the exact rotated polygon corners from
          the layer's widget-space rect — so the box tracks the visual content
          precisely even at arbitrary rotation angles.
        - Resets opacity and composition mode before drawing so no FX state leaks.
        - Clips to the canvas rect (plus one handle-size margin) so handles at
          exact canvas edges remain fully visible.
        """
        n = len(self._layers)
        if n == 0 or not (0 <= self._sel < n):
            return
        l = self._layers[self._sel]
        if not l.visible:
            return

        from PySide6.QtCore  import QPointF, QRectF
        from PySide6.QtGui   import QTransform, QPolygonF
        import math as _math

        cr = self._canvas_rect()

        # Sub-pixel widget rect for the layer's axis-aligned bounding box
        wr = self._layer_wrect_f(l)
        cx_f = wr.left() + wr.width()  / 2.0
        cy_f = wr.top()  + wr.height() / 2.0
        rot  = l.rotation if hasattr(l, "rotation") else 0.0

        # Build the QTransform that maps local (unrotated) rect coords
        # to their final widget positions.  This is the correct way to compute
        # rotated handles — no manual sin/cos arithmetic needed.
        T = QTransform()
        T.translate(cx_f, cy_f)
        T.rotate(rot)
        T.translate(-cx_f, -cy_f)

        # Four corners of the axis-aligned rect → mapped to rotated widget space
        corners_local = [
            QPointF(wr.left(),  wr.top()),
            QPointF(wr.right(), wr.top()),
            QPointF(wr.right(), wr.bottom()),
            QPointF(wr.left(),  wr.bottom()),
        ]
        corners_w = [T.map(pt) for pt in corners_local]

        # The 8 handle anchor points (mapped through the same transform)
        handle_pts_local = [
            QPointF(wr.left(),  wr.top()),       # 0 TL
            QPointF(cx_f,       wr.top()),        # 1 T  (top-centre)
            QPointF(wr.right(), wr.top()),        # 2 TR
            QPointF(wr.right(), cy_f),            # 3 R
            QPointF(wr.right(), wr.bottom()),     # 4 BR
            QPointF(cx_f,       wr.bottom()),     # 5 B
            QPointF(wr.left(),  wr.bottom()),     # 6 BL
            QPointF(wr.left(),  cy_f),            # 7 L
        ]
        handle_pts_w = [T.map(pt) for pt in handle_pts_local]

        # Rotation stem: top-centre → knob (upward in the rotated frame)
        STEM = 32
        tc_local   = QPointF(cx_f, wr.top())
        stem_local = QPointF(cx_f, wr.top() - STEM)
        tc_w   = T.map(tc_local)
        stem_w = T.map(stem_local)

        p.save()
        p.setOpacity(1.0)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # Allow handles at the canvas edge to remain visible
        p.setClipRect(cr.adjusted(-HANDLE_SIZE, -HANDLE_SIZE,
                                   HANDLE_SIZE,  HANDLE_SIZE))

        H = HANDLE_SIZE

        # ── Dashed rotated bounding polygon ──────────────────────────────────
        poly = QPolygonF(corners_w + [corners_w[0]])   # close the polygon
        p.setPen(QPen(QColor(80, 160, 255), 1, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(poly)

        # ── Rotation stem ─────────────────────────────────────────────────────
        p.setPen(QPen(QColor(80, 160, 255, 160), 1, Qt.SolidLine))
        p.drawLine(tc_w, stem_w)

        # ── 8 resize handles ─────────────────────────────────────────────────
        for i, pt in enumerate(handle_pts_w):
            is_corner = i in (0, 2, 4, 6)
            p.setPen(QPen(QColor(255, 255, 255), 1))
            p.setBrush(QBrush(QColor(80, 160, 255) if is_corner
                              else QColor(20, 40, 80, 200)))
            hr = QRectF(pt.x() - HANDLE_HALF,
                        pt.y() - HANDLE_HALF, H, H)
            p.drawRect(hr)

        # ── Rotation knob ─────────────────────────────────────────────────────
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.setBrush(QBrush(QColor(60, 220, 180)))
        p.drawEllipse(stem_w, HANDLE_HALF, HANDLE_HALF)

        p.restore()

    def _fx_cache_key_current(self) -> tuple:
        """
        Stable key that covers everything affecting the FX composite.
        If this matches _fx_cache_key the cached QPixmap is still valid.
        Now includes per-layer colour adjustments and crop so cache properly
        invalidates when those values change.
        """
        layer_sig = tuple(
            (l.kind, l.visible, l.x, l.y, l.w, l.h,
             id(l.pil_image), l.opacity, l.rotation,
             l.brightness, l.contrast, l.saturation,
             l.tint_color, l.tint_strength,
             l.crop_l, l.crop_t, l.crop_r, l.crop_b,
             l.flip_h, l.flip_v, l.blend_mode)
            for l in self._layers
        )
        return (
            self._effects_grain,
            self._effects_ca,
            self._bg_color.rgb(),
            id(self._template_pix),
            id(self._bg_pix),
            self._zoom_factor,
            self._ox,
            self._oy,
            layer_sig,
        )

    def _render_scene_to_pixmap(self, cr: QRect) -> QPixmap:
        """
        Render the scene (background + template + layers) into an offscreen
        QPixmap of exactly cr.size() using the normal Qt paint pipeline.
        This is the ONLY place the scene is rendered when FX are active.
        FX are applied afterwards by _apply_fx_to_pixmap — never here.
        """
        pix = QPixmap(cr.size())
        pix.fill(Qt.transparent)
        p2 = QPainter(pix)
        p2.setRenderHint(QPainter.SmoothPixmapTransform)
        p2.setRenderHint(QPainter.Antialiasing)

        # Translate so doc coords map into the pixmap (cr offset removed)
        p2.translate(-cr.x(), -cr.y())
        self._render_scene(p2, cr, export=False)
        p2.end()
        return pix

    def _render_scene(self, p: QPainter, cr: QRect, *, export: bool):
        """
        THE scene renderer — background, template, filter overlay and every
        visible layer — used by the live preview, the FX preview path and
        compose_to_pil().  Whatever is drawn here is exactly what is exported.

        export=True  : transparent templates stay transparent (no checkerboard)
                       and editor-only hints (clone link icon, placeholder
                       boxes for empty vector / filter / mask layers) are
                       not drawn.
        """
        # 1. Background
        if getattr(self, "_transparent_bg", False):
            if not export:
                self._draw_checkerboard(p, cr)
        else:
            p.fillRect(cr, self._bg_color)

        # 2. Template PNG
        if self._template_pix:
            p.drawPixmap(cr, self._template_pix)

        # 3. Filter-composed overlay
        if self._bg_pix:
            p.drawPixmap(cr, self._bg_pix)

        # 4. Layers
        p.save(); p.setClipRect(cr)
        for layer in self._layers:
            if layer.visible and layer.kind != "group":
                self._paint_layer(p, layer, export=export)
        p.restore()

    def _apply_fx_to_pixmap(self, pix: QPixmap) -> QPixmap:
        """
        Apply Film Grain and Chromatic Aberration to a QPixmap in-place
        (returns a new QPixmap).  Uses a cached result keyed on effect strengths
        + a hash of the source pixels so repeated calls with the same frame are
        free.  During active interaction (drag/resize/rotate) the previous cached
        result is returned immediately — effects rebuild on mouseRelease.
        """
        grain = getattr(self, "_effects_grain", 0)
        ca    = getattr(self, "_effects_ca",    0)
        if grain <= 0 and ca <= 0:
            return pix

        # During interaction return stale cache to keep sliders fast
        if self._drag_active or self._resize_active or self._rotate_active:
            if self._fx_cache is not None:
                return self._fx_cache
            return pix

        # Cache key: effect strengths + scene state (layer positions etc.)
        cur_key = self._fx_cache_key_current()
        if self._fx_cache is not None and cur_key == self._fx_cache_key:
            return self._fx_cache

        # Convert QPixmap → numpy array (no file I/O)
        from PySide6.QtGui import QImage
        qi  = pix.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        w, h = qi.width(), qi.height()
        arr = np.frombuffer(qi.bits(), dtype=np.uint8).reshape((h, w, 4)).copy().astype(np.float32)

        arr = self._apply_film_grain(arr, grain, seed=self._grain_seed)
        arr = self._apply_chromatic_aberration(arr, ca)

        arr_out = np.ascontiguousarray(arr.clip(0, 255).astype(np.uint8))
        qi_out  = QImage(arr_out.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        result  = QPixmap.fromImage(qi_out)

        self._fx_cache     = result
        self._fx_cache_key = cur_key
        return result

    def _paint_layer(self, p: QPainter, l: Layer, export: bool = False):
        wr = self._layer_wrect(l)
        p.setOpacity(l.opacity)

        bm_map = {
            "normal":     QPainter.CompositionMode.CompositionMode_SourceOver,
            "multiply":   QPainter.CompositionMode.CompositionMode_Multiply,
            "screen":     QPainter.CompositionMode.CompositionMode_Screen,
            "overlay":    QPainter.CompositionMode.CompositionMode_Overlay,
            "soft_light": QPainter.CompositionMode.CompositionMode_SoftLight,
            "color":      QPainter.CompositionMode.CompositionMode_ColorBurn,
        }
        p.setCompositionMode(bm_map.get(l.blend_mode,
            QPainter.CompositionMode.CompositionMode_SourceOver))

        # ── Image-like kinds (paint, image, texture, file) ─────────────────────
        if l.kind in ("paint", "image", "texture", "file"):
            pix = self._get_pix(l)
            if pix:
                if l.rotation != 0 or l.flip_h or l.flip_v:
                    p.save()
                    cx = wr.x() + wr.width()  / 2
                    cy = wr.y() + wr.height() / 2
                    p.translate(cx, cy)
                    if l.rotation != 0: p.rotate(l.rotation)
                    if l.flip_h: p.scale(-1, 1)
                    if l.flip_v: p.scale(1, -1)
                    p.drawPixmap(QRect(-wr.width()//2, -wr.height()//2,
                                       wr.width(), wr.height()), pix)
                    p.restore()
                else:
                    p.drawPixmap(wr, pix)

        # ── Text ────────────────────────────────────────────────────────────────
        elif l.kind == "text":
            self._paint_text_layer(p, l, wr)

        # ── Clone layer ─────────────────────────────────────────────────────────
        elif l.kind == "clone":
            src_idx = l.clone_source_idx
            if 0 <= src_idx < len(self._layers):
                src = self._layers[src_idx]
                pix = self._get_pix(src)
                if pix:
                    p.drawPixmap(wr, pix)
                if pix and not export:
                    # Overlay chain-link icon hint (editor only)
                    p.save(); p.setOpacity(0.55)
                    p.setFont(QFont("Segoe UI Emoji", max(8, int(16 * self._scale))))
                    p.setPen(QColor(200, 220, 255))
                    p.drawText(wr.adjusted(4,4,0,0), Qt.AlignTop | Qt.AlignLeft, "🔗")
                    p.restore()
            elif not export:
                # No source — draw placeholder
                p.save()
                p.fillRect(wr, QColor(30, 30, 50))
                p.setPen(QColor(100, 120, 180))
                p.setFont(QFont("Courier New", max(8, int(11 * self._scale))))
                p.drawText(wr, Qt.AlignCenter, "🔗  Clone\n(no source)")
                p.restore()

        # ── Vector layer ────────────────────────────────────────────────────────
        elif l.kind == "vector":
            p.save()
            if not export:
                p.fillRect(wr, QColor(20, 30, 20, 60))
            if l.vector_paths:
                from PySide6.QtGui import QPainterPath as QPPath
                stroke = QColor(*l.vector_stroke)
                fill   = QColor(*l.vector_fill)
                p.setPen(QPen(stroke, l.vector_stroke_w * self._scale))
                for path_data in l.vector_paths:
                    pts = path_data.get("points", [])
                    if len(pts) >= 2:
                        qpath = QPPath()
                        wp0 = self._c2w(QPoint(int(pts[0][0]+l.x), int(pts[0][1]+l.y)))
                        qpath.moveTo(wp0.x(), wp0.y())
                        for px2, py2 in pts[1:]:
                            wpt = self._c2w(QPoint(int(px2+l.x), int(py2+l.y)))
                            qpath.lineTo(wpt.x(), wpt.y())
                        if path_data.get("closed"):
                            qpath.closeSubpath()
                            p.fillPath(qpath, QBrush(fill))
                        p.drawPath(qpath)
            elif not export:
                p.setPen(QPen(QColor(80,200,80), 2, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(wr.adjusted(1,1,-1,-1))
                p.setFont(QFont("Segoe UI Emoji", max(9, int(18 * self._scale))))
                p.setPen(QColor(80, 200, 80))
                p.drawText(wr, Qt.AlignCenter, "◎  Vector\n(empty)")
            p.restore()

        # ── Filter layer ────────────────────────────────────────────────────────
        elif l.kind == "filter" and not export:
            # Apply filter effect to what's below — render as a tinted glass overlay
            p.save()
            p.setOpacity(0.22)
            p.fillRect(wr, QColor(200, 160, 60))
            p.setOpacity(1.0)
            p.setPen(QPen(QColor(220, 180, 80), 2, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(wr.adjusted(1,1,-1,-1))
            p.setFont(QFont("Segoe UI Emoji", max(9, int(16 * self._scale))))
            p.setPen(QColor(220, 180, 80))
            ft = l.filter_type or "Filter"
            p.drawText(wr, Qt.AlignCenter, f"🔧  {ft}")
            p.restore()

        # ── Fill layer ──────────────────────────────────────────────────────────
        elif l.kind == "fill":
            p.save()
            if l.fill_type == "gradient":
                from PySide6.QtGui import QLinearGradient
                import math
                angle = math.radians(l.fill_angle)
                dx = math.cos(angle) * wr.width()
                dy = math.sin(angle) * wr.height()
                grad = QLinearGradient(wr.x(), wr.y(),
                                       wr.x() + dx, wr.y() + dy)
                grad.setColorAt(0, QColor(*l.fill_color))
                grad.setColorAt(1, QColor(*l.fill_color2))
                p.fillRect(wr, QBrush(grad))
            else:
                p.fillRect(wr, QColor(*l.fill_color))
            p.restore()

        # ── Transparency mask ────────────────────────────────────────────────────
        elif l.kind == "mask_transparency" and not export:
            p.save()
            # Checkerboard pattern to represent transparency
            p.setOpacity(0.5)
            sq = max(4, int(8 * self._scale))
            for ry in range(wr.top(), wr.bottom(), sq):
                for rx in range(wr.left(), wr.right(), sq):
                    odd = ((rx - wr.left())//sq + (ry - wr.top())//sq) % 2
                    p.fillRect(QRect(rx, ry, sq, sq),
                               QColor(200,200,200) if odd else QColor(120,120,120))
            p.setOpacity(1.0)
            p.setPen(QPen(QColor(180, 180, 200), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(wr.adjusted(1,1,-1,-1))
            p.restore()

        # ── Filter mask ─────────────────────────────────────────────────────────
        elif l.kind == "mask_filter" and not export:
            p.save()
            p.setOpacity(0.3)
            p.fillRect(wr, QColor(200, 160, 60))
            p.setOpacity(1.0)
            p.setPen(QPen(QColor(220, 180, 80), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(wr.adjusted(1,1,-1,-1))
            p.setFont(QFont("Segoe UI Emoji", max(9, int(14 * self._scale))))
            p.setPen(QColor(220, 180, 80))
            p.drawText(wr, Qt.AlignCenter, "🔧  Filter Mask")
            p.restore()

        # ── Colorize mask ────────────────────────────────────────────────────────
        elif l.kind == "mask_colorize":
            pix = self._get_pix(l)
            if pix:
                p.drawPixmap(wr, pix)
            elif not export:
                p.save()
                p.setOpacity(0.4)
                p.fillRect(wr, QColor(*l.mask_color))
                p.setOpacity(1.0)
                p.setPen(QPen(QColor(*l.mask_color).lighter(160), 2, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(wr.adjusted(1,1,-1,-1))
                p.setFont(QFont("Segoe UI Emoji", max(9, int(14 * self._scale))))
                p.setPen(QColor(*l.mask_color).lighter(160))
                p.drawText(wr, Qt.AlignCenter, "🎨  Colorize")
                p.restore()

        # ── Transform mask ───────────────────────────────────────────────────────
        elif l.kind == "mask_transform" and not export:
            p.save()
            p.setOpacity(0.25)
            p.fillRect(wr, QColor(80, 200, 200))
            p.setOpacity(1.0)
            # Draw transform arrows at corners
            p.setPen(QPen(QColor(80, 220, 220), 2, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(wr.adjusted(1,1,-1,-1))
            p.setFont(QFont("Segoe UI Emoji", max(9, int(14 * self._scale))))
            p.setPen(QColor(80, 220, 220))
            p.drawText(wr, Qt.AlignCenter, "⟳  Transform Mask")
            p.restore()

        # ── Local selection mask ─────────────────────────────────────────────────
        elif l.kind == "mask_selection" and not export:
            p.save()
            p.setOpacity(0.35)
            p.fillRect(wr, QColor(100, 150, 255))
            p.setOpacity(1.0)
            p.setPen(QPen(QColor(140, 190, 255), 2,
                          Qt.CustomDashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(wr.adjusted(1,1,-1,-1))
            p.setFont(QFont("Segoe UI Emoji", max(9, int(14 * self._scale))))
            p.setPen(QColor(180, 210, 255))
            p.drawText(wr, Qt.AlignCenter, "⬡  Selection")
            p.restore()

        # Reset painter state
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setOpacity(1.0)

    def _get_pix(self, l: Layer) -> Optional[QPixmap]:
        # ── Fast path during active resize ───────────────────────────────────
        # While the user is dragging a resize handle we skip the expensive PIL
        # colour-adjustment pipeline and return the existing cached pixmap (or
        # the raw source image pixmap).  Qt will scale it on-the-fly via the
        # transform set in _paint_layer — visually "good enough" and smooth.
        # The full rebuild happens in mouseReleaseEvent (l.invalidate() + update).
        if self._resize_active:
            if l._pix:
                return l._pix
            # No cache yet — do a fast raw conversion without adjustments
            if l.pil_image:
                try:
                    arr = __import__("numpy").ascontiguousarray(
                        __import__("numpy").array(l.pil_image.convert("RGBA"), dtype=__import__("numpy").uint8))
                    h_r, w_r = arr.shape[:2]
                    from PySide6.QtGui import QImage
                    qi = QImage(arr.data, w_r, h_r, w_r * 4,
                                QImage.Format.Format_RGBA8888).copy()
                    return QPixmap.fromImage(qi)
                except Exception:
                    return None
            return None

        # Size the pixmap actually needs on screen (or in the export, scale=1).
        # Qt scales the pixmap to the layer rect anyway, so working on a source
        # bigger than ~1.5× that is wasted time on every slider tick.
        tw = max(1, int(l.w * self._scale * 1.5))
        th = max(1, int(l.h * self._scale * 1.5))
        if l._pix:
            cached = getattr(l, "_pix_target", None)
            if cached is None or (cached[0] >= tw and cached[1] >= th) \
                    or cached[2]:   # cached at full source res → always fine
                return l._pix
        if not l.pil_image: return None

        img = l.pil_image.convert("RGBA")

        # Apply crop (in source pixel coordinates — must happen before scaling)
        w, h = img.size
        cl, ct, cr_px, cb = l.crop_l, l.crop_t, l.crop_r, l.crop_b
        if cl or ct or cr_px or cb:
            box = (cl, ct, max(cl+1, w - cr_px), max(ct+1, h - cb))
            img = img.crop(box)

        full_res = True
        if img.width > tw and img.height > th:
            img = img.resize((tw, th), PILImage.LANCZOS)
            full_res = False

        # Apply per-layer color adjustments (brightness/contrast/saturation)
        if l.brightness != 50 or l.contrast != 50 or l.saturation != 50:
            from PIL import ImageEnhance
            rgb = img.convert("RGB")
            if l.brightness != 50:
                f = l.brightness / 50.0   # 0=black, 1=original, 2=double
                rgb = ImageEnhance.Brightness(rgb).enhance(f)
            if l.contrast != 50:
                f = l.contrast / 50.0
                rgb = ImageEnhance.Contrast(rgb).enhance(f)
            if l.saturation != 50:
                f = l.saturation / 50.0
                rgb = ImageEnhance.Color(rgb).enhance(f)
            # Re-apply alpha channel
            r2, g2, b2 = rgb.split()
            _, _, _, a2 = img.split()
            img = PILImage.merge("RGBA", (r2, g2, b2, a2))

        # Apply tint color overlay (replaces hue, keeps luminance)
        if l.tint_color and l.tint_strength > 0:
            tr, tg, tb = l.tint_color
            tint = PILImage.new("RGBA", img.size,
                                (tr, tg, tb, int(255 * l.tint_strength)))
            # Composite tint over image using alpha
            img = PILImage.alpha_composite(img, tint)

        # Convert PIL → QPixmap via QImage (no PNG encode/decode round-trip)
        arr_out = np.ascontiguousarray(np.array(img, dtype=np.uint8))
        h_out, w_out = arr_out.shape[:2]
        from PySide6.QtGui import QImage
        qi = QImage(arr_out.data, w_out, h_out,
                    w_out * 4, QImage.Format.Format_RGBA8888).copy()
        pix = QPixmap.fromImage(qi)
        l._pix = pix
        l._pix_target = (img.width, img.height, full_res)
        l.mark_clean()
        return pix

    def _paint_text_layer(self, p: QPainter, l: Layer, wr: QRect):
        """
        Draw a text layer: shadow → outline → fill, honouring orientation,
        alignment, letter spacing and word-wrap. Used by preview AND export.
        """
        import math
        display_text = l.text.upper() if l.font_uppercase else l.text
        p.setFont(self._make_qfont(l))
        align_map = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}
        qt_align  = align_map.get(l.text_align, Qt.AlignLeft) | Qt.AlignTop | Qt.TextWordWrap

        # Text box in the painter's coordinate system after orientation
        p.save()
        if l.text_orientation in ("rotate90", "vertical"):
            p.translate(wr.x() + wr.width() / 2, wr.y() + wr.height() / 2)
            p.rotate(90)
            box = QRect(-wr.height() // 2, -wr.width() // 2, wr.height(), wr.width())
        elif l.text_orientation == "rotate270":
            p.translate(wr.x() + wr.width() / 2, wr.y() + wr.height() / 2)
            p.rotate(-90)
            box = QRect(-wr.height() // 2, -wr.width() // 2, wr.height(), wr.width())
        else:
            box = wr

        sc = self._scale
        # 1. Shadow
        if l.shadow_offset > 0:
            off = max(1, round(l.shadow_offset * sc))
            p.setPen(QPen(QColor(*l.shadow_color)))
            p.drawText(box.translated(off, off), qt_align, display_text)
        # 2. Outline — text drawn in 8 directions around the fill
        if l.outline_size > 0:
            r = max(1, round(l.outline_size * sc))
            p.setPen(QPen(QColor(*l.outline_color)))
            for i in range(8):
                a  = i * math.pi / 4
                dx = round(math.cos(a) * r)
                dy = round(math.sin(a) * r)
                p.drawText(box.translated(dx, dy), qt_align, display_text)
        # 3. Fill
        p.setPen(QPen(QColor(*l.font_color)))
        p.drawText(box, qt_align, display_text)
        p.restore()

    _FONT_FAMILY_CACHE: dict = {}   # font file path → Qt family name

    def _make_qfont(self, l: Layer) -> QFont:
        fp = font_path(l.font_name)
        fam = self._FONT_FAMILY_CACHE.get(fp)
        if fam is None:
            # Register each font file once — this ran on every repaint before.
            fid  = QFontDatabase.addApplicationFont(fp)
            fams = QFontDatabase.applicationFontFamilies(fid)
            fam  = fams[0] if fams else "Courier New"
            self._FONT_FAMILY_CACHE[fp] = fam
        qf = QFont(fam, max(6, int(l.font_size * self._scale)))
        qf.setBold(l.font_bold)
        qf.setItalic(l.font_italic)
        if l.letter_spacing != 0:
            qf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, l.letter_spacing)
        return qf

    # ── mouse ──────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e: QMouseEvent):
        self._update_viewport()
        pos = e.position().toPoint()
        TM  = self._ToolMode

        # ── Middle mouse button: pan (works in ALL tool modes) ─────────────────
        if e.button() == Qt.MiddleButton:
            self._pan_active = True
            self._pan_start  = pos
            self.setCursor(Qt.ClosedHandCursor)
            return

        # ── Hand tool ─────────────────────────────────────────────────────────
        if self._tool == TM.HAND and e.button() == Qt.LeftButton:
            self._hand_active = True
            self._hand_start  = pos
            self.setCursor(Qt.ClosedHandCursor)
            return

        # ── Zoom tool ─────────────────────────────────────────────────────────
        if self._tool == TM.ZOOM and e.button() in (Qt.LeftButton, Qt.RightButton):
            zoom_in = (e.button() == Qt.LeftButton and
                       not (e.modifiers() & Qt.ShiftModifier))
            step = 1.25 if zoom_in else (1.0 / 1.25)
            self.set_zoom(self._zoom_factor * step)
            return

        if e.button() != Qt.LeftButton:
            return

        # ── Brush tool ────────────────────────────────────────────────────────
        if self._tool in (TM.BRUSH, TM.ERASER):
            doc = self._w2c(pos)
            if self.brush_paint_requested:
                erasing = (self._tool == TM.ERASER)
                try:
                    self.brush_paint_requested(doc.x(), doc.y(), erasing)
                except TypeError:
                    # Back-compat: old callbacks don't accept eraser kwarg
                    self.brush_paint_requested(doc.x(), doc.y())
            return

        # ── Color picker ──────────────────────────────────────────────────────
        if self._tool == TM.COLOR_PICKER:
            self._sample_color(pos)
            return

        # ── Shape tools: start drag ───────────────────────────────────────────
        if self._tool in (TM.RECTANGLE, TM.ELLIPSE):
            self._shape_drawing   = True
            self._shape_start_doc = self._w2c(pos)
            self._shape_cur_doc   = self._w2c(pos)
            return

        # ── Crop mode ─────────────────────────────────────────────────────────
        if self._crop_mode and self._crop_rect:
            h = self._hit_crop_handle(pos)
            if h >= 0:
                self._crop_drag_handle = h
                self._crop_drag_start  = pos
                self._crop_orig_rect   = QRect(self._crop_rect)
                return
            cr_tl = self._c2w(QPoint(self._crop_rect.left(), self._crop_rect.top()))
            cr_br = self._c2w(QPoint(self._crop_rect.right(), self._crop_rect.bottom()))
            if QRect(cr_tl, cr_br).contains(pos):
                self._crop_drag_handle = 4
                self._crop_drag_start  = pos
                self._crop_orig_rect   = QRect(self._crop_rect)
            return

        # ── MOVE tool: handles + drag ─────────────────────────────────────────
        if 0 <= self._sel < len(self._layers):
            l = self._layers[self._sel]
            if not self._is_locked(l):
                corner = self._hit_handle(l, pos)
                if corner == 8:
                    import math
                    self._rotate_active = True
                    wr = self._layer_wrect(l)
                    self._rotate_cx = (wr.left() + wr.right()) / 2.0
                    self._rotate_cy = (wr.top()  + wr.bottom()) / 2.0
                    self._rotate_start_ang = math.degrees(
                        math.atan2(pos.y() - self._rotate_cy,
                                   pos.x() - self._rotate_cx))
                    self._rotate_orig_ang  = l.rotation
                    self._drag_start = pos
                    self.setCursor(Qt.CrossCursor)
                    return
                if corner >= 0:
                    self._resize_active = True
                    self._resize_corner = corner
                    self._drag_start    = pos
                    self._orig_rect     = QRect(l.x, l.y, l.w, l.h)
                    self._ar_ratio = l.w / max(1, l.h)
                    self._resize_rotation = l.rotation
                    self.setCursor(self._corner_cursor(corner))
                    return

        idx = self._hit_layer(pos)
        self._sel = idx
        if idx >= 0:
            l = self._layers[idx]
            if not self._is_locked(l):
                self._drag_active = True
                self._drag_start  = pos
                self._orig_rect   = QRect(l.x, l.y, l.w, l.h)
                self.setCursor(Qt.SizeAllCursor)
            self.layer_selected.emit(idx)
        else:
            self.layer_selected.emit(-1)
        self.update()

    def mouseMoveEvent(self, e: QMouseEvent):
        self._update_viewport()
        pos = e.position().toPoint()
        TM  = self._ToolMode

        # ── MMB Pan (all tool modes) ───────────────────────────────────────────
        if self._pan_active:
            delta = pos - self._pan_start
            self._pan_offset += delta
            self._pan_start   = pos
            self._update_viewport()
            self.update()
            return

        # ── Hand tool pan ─────────────────────────────────────────────────────
        if self._hand_active and (e.buttons() & Qt.LeftButton):
            delta = pos - self._hand_start
            self._pan_offset += delta
            self._hand_start  = pos
            self._update_viewport()
            self.update()
            return

        # ── Brush / Eraser ────────────────────────────────────────────────────
        if self._tool in (TM.BRUSH, TM.ERASER) and (e.buttons() & Qt.LeftButton):
            doc = self._w2c(pos)
            if self.brush_paint_requested:
                erasing = (self._tool == TM.ERASER)
                try:
                    self.brush_paint_requested(doc.x(), doc.y(), erasing)
                except TypeError:
                    self.brush_paint_requested(doc.x(), doc.y())
            return

        # ── Shape drag ────────────────────────────────────────────────────────
        if self._shape_drawing and (e.buttons() & Qt.LeftButton):
            self._shape_cur_doc = self._w2c(pos)
            self.update()
            return

        # ── Color picker ──────────────────────────────────────────────────────
        if self._tool == TM.COLOR_PICKER and (e.buttons() & Qt.LeftButton):
            self._sample_color(pos)
            return

        # ── Crop mode ─────────────────────────────────────────────────────────
        if self._crop_mode and self._crop_drag_handle >= 0 and self._crop_orig_rect:
            dx = int((pos.x() - self._crop_drag_start.x()) / self._scale)
            dy = int((pos.y() - self._crop_drag_start.y()) / self._scale)
            r  = QRect(self._crop_orig_rect)
            h  = self._crop_drag_handle
            l = self.selected_layer()
            lx, ly = (l.x, l.y) if l else (0, 0)
            lw, lh = (l.w, l.h) if l else (self._doc_size.width(), self._doc_size.height())
            if h == 0:
                r.setLeft(min(r.right()-10, r.left()+dx))
                r.setTop(min(r.bottom()-10, r.top()+dy))
            elif h == 1:
                r.setRight(max(r.left()+10, r.right()+dx))
                r.setTop(min(r.bottom()-10, r.top()+dy))
            elif h == 2:
                r.setRight(max(r.left()+10, r.right()+dx))
                r.setBottom(max(r.top()+10, r.bottom()+dy))
            elif h == 3:
                r.setLeft(min(r.right()-10, r.left()+dx))
                r.setBottom(max(r.top()+10, r.bottom()+dy))
            elif h == 4:
                r.moveLeft(r.left()+dx); r.moveTop(r.top()+dy)
            r.setLeft(max(lx, r.left())); r.setTop(max(ly, r.top()))
            r.setRight(min(lx+lw, r.right())); r.setBottom(min(ly+lh, r.bottom()))
            self._crop_rect = r
            self.update(); return

        # ── Rotation ──────────────────────────────────────────────────────────
        if self._rotate_active and 0 <= self._sel < len(self._layers):
            import math
            l = self._layers[self._sel]
            if self._is_locked(l):
                self._rotate_active = False; return
            cx = getattr(self, '_rotate_cx', 0.0)
            cy = getattr(self, '_rotate_cy', 0.0)
            cur_ang = math.degrees(math.atan2(pos.y() - cy, pos.x() - cx))
            delta   = cur_ang - self._rotate_start_ang
            new_ang = self._rotate_orig_ang + delta
            if e.modifiers() & Qt.ShiftModifier:
                new_ang = round(new_ang / 15) * 15
            l.rotation = new_ang % 360
            l.invalidate_transform()
            self.update(); return

        # ── Move ──────────────────────────────────────────────────────────────
        if self._drag_active and 0 <= self._sel < len(self._layers):
            l = self._layers[self._sel]
            if self._is_locked(l):
                self._drag_active = False; return
            dx   = int((pos.x() - self._drag_start.x()) / self._scale)
            dy   = int((pos.y() - self._drag_start.y()) / self._scale)

            # Move group children together
            if l.kind == "group":
                for child_idx in getattr(l, 'children', []):
                    if 0 <= child_idx < len(self._layers):
                        cl = self._layers[child_idx]
                        cl.x = cl.x - (l.x - (self._orig_rect.x() + dx))
                        cl.y = cl.y - (l.y - (self._orig_rect.y() + dy))
                        cl.invalidate_transform()

            orig = self._orig_rect
            l.x = orig.x() + dx
            l.y = orig.y() + dy

            self._guides_active = True
            sdx, sdy = self._smart_guides.update(l, snap=True)
            if sdx: l.x += sdx
            if sdy: l.y += sdy

            self.update(); return

        # ── Resize ────────────────────────────────────────────────────────────
        if self._resize_active and 0 <= self._sel < len(self._layers):
            import math
            l    = self._layers[self._sel]
            if self._is_locked(l):
                self._resize_active = False; return
            c    = self._resize_corner
            orig = self._orig_rect

            rot_rad = math.radians(self._resize_rotation)
            cos_r   = math.cos(rot_rad)
            sin_r   = math.sin(rot_rad)

            wdx = float(pos.x() - self._drag_start.x())
            wdy = float(pos.y() - self._drag_start.y())

            ldx = ( wdx * cos_r + wdy * sin_r)  / self._scale
            ldy = (-wdx * sin_r + wdy * cos_r)  / self._scale

            ow = float(orig.width())
            oh = float(orig.height())

            sx, sy = {
                0: (-1, -1), 1: ( 0, -1), 2: ( 1, -1),
                3: ( 1,  0), 4: ( 1,  1), 5: ( 0,  1),
                6: (-1,  1), 7: (-1,  0),
            }[c]

            raw_w = max(float(MIN_SIZE), ow + sx * ldx) if sx != 0 else ow
            raw_h = max(float(MIN_SIZE), oh + sy * ldy) if sy != 0 else oh

            if c in (0, 2, 4, 6):
                ratio = self._ar_ratio
                if abs(sx * ldx) >= abs(sy * ldy):
                    new_w = raw_w
                    new_h = max(float(MIN_SIZE), new_w / ratio)
                else:
                    new_h = raw_h
                    new_w = max(float(MIN_SIZE), new_h * ratio)
            else:
                new_w, new_h = raw_w, raw_h

            new_w = max(float(MIN_SIZE), new_w)
            new_h = max(float(MIN_SIZE), new_h)

            hw_o = ow / 2.0;  hh_o = oh / 2.0
            hw_n = new_w / 2.0; hh_n = new_h / 2.0

            anchor_u_orig, anchor_v_orig, anchor_u_new, anchor_v_new = {
                0: ( hw_o,  hh_o,  hw_n,  hh_n),
                1: (  0.0,  hh_o,   0.0,  hh_n),
                2: (-hw_o,  hh_o, -hw_n,  hh_n),
                3: (-hw_o,   0.0, -hw_n,   0.0),
                4: (-hw_o, -hh_o, -hw_n, -hh_n),
                5: (  0.0, -hh_o,   0.0, -hh_n),
                6: ( hw_o, -hh_o,  hw_n, -hh_n),
                7: ( hw_o,   0.0,  hw_n,   0.0),
            }[c]

            orig_cx = float(orig.x()) + ow / 2.0
            orig_cy = float(orig.y()) + oh / 2.0

            aw_x = orig_cx + anchor_u_orig * cos_r + anchor_v_orig * (-sin_r)
            aw_y = orig_cy + anchor_u_orig * sin_r + anchor_v_orig * ( cos_r)

            new_cx = aw_x - anchor_u_new * cos_r  - anchor_v_new * (-sin_r)
            new_cy = aw_y - anchor_u_new * sin_r  - anchor_v_new * ( cos_r)

            l.w = int(new_w); l.h = int(new_h)
            l.x = int(new_cx - new_w / 2.0)
            l.y = int(new_cy - new_h / 2.0)

            l.invalidate_transform()   # size changed → pix redrawn at new dims on next paint
            l._pix = None              # but DO discard cached pix since dimensions changed
            self._guides_active = True
            self._smart_guides.update(l, snap=False)
            self.update(); return

        # ── Hover cursors ─────────────────────────────────────────────────────
        if self._tool == TM.HAND:
            self.setCursor(Qt.OpenHandCursor); return
        if self._tool == TM.ZOOM:
            self.setCursor(Qt.CrossCursor if not (e.modifiers() & Qt.ShiftModifier)
                           else Qt.CrossCursor); return
        if self._tool in (TM.BRUSH, TM.ERASER, TM.RECTANGLE,
                          TM.ELLIPSE, TM.COLOR_PICKER):
            self.setCursor(Qt.CrossCursor); return

        if self._crop_mode:
            h = self._hit_crop_handle(pos)
            self.setCursor(Qt.SizeFDiagCursor if h in (0,2) else
                           Qt.SizeBDiagCursor if h in (1,3) else
                           Qt.SizeAllCursor   if h == 4 else
                           Qt.CrossCursor)
            return
        if 0 <= self._sel < len(self._layers):
            l = self._layers[self._sel]
            corner = self._hit_handle(l, pos)
            if corner == 8:
                self.setCursor(Qt.CrossCursor); return
            if corner >= 0:
                rot = l.rotation if hasattr(l, 'rotation') else 0.0
                self.setCursor(self._corner_cursor(corner) if rot == 0.0
                               else Qt.SizeAllCursor); return
            if self._hit_layer(pos) == self._sel:
                self.setCursor(Qt.SizeAllCursor); return
        self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, e: QMouseEvent):
        TM = self._ToolMode

        if e.button() == Qt.MiddleButton:
            self._pan_active = False
            self.setCursor(self._tool_cursor())
            return

        if e.button() == Qt.LeftButton:
            # ── Hand tool ──────────────────────────────────────────────────────
            if self._hand_active:
                self._hand_active = False
                self.setCursor(Qt.OpenHandCursor)
                return

            # ── Shape tool: commit new layer ───────────────────────────────────
            if self._shape_drawing:
                self._shape_drawing = False
                self._commit_shape()
                return

            self._crop_drag_handle = -1
            was_rotating = self._rotate_active
            was_resizing = self._resize_active
            moved = self._drag_active or self._resize_active or self._rotate_active

            # Explicit flag resets — prevents the "rotate once then stuck" bug.
            self._drag_active   = False
            self._resize_active = False
            self._rotate_active = False
            self._guides_active = False
            self._smart_guides.clear()
            self.setCursor(Qt.CrossCursor if self._crop_mode
                           else self._tool_cursor())

            if moved:
                # After resize the pixel cache is stale (new dimensions).
                # After rotate the transform is stale but pix is reusable.
                if was_resizing and 0 <= self._sel < len(self._layers):
                    self._layers[self._sel].invalidate()
                elif was_rotating and 0 <= self._sel < len(self._layers):
                    self._layers[self._sel].invalidate_transform()
                # Always invalidate global FX cache when geometry changes.
                self._fx_cache = None
                self._effects_pix = None
                self._push_history()
                self.layers_changed.emit()
                self.update()

    # ── Tool helpers ───────────────────────────────────────────────────────────

    def _tool_cursor(self):
        """Return the default cursor for the current tool."""
        TM = self._ToolMode
        return {
            TM.MOVE:         Qt.ArrowCursor,
            TM.BRUSH:        Qt.CrossCursor,
            TM.ERASER:       Qt.CrossCursor,
            TM.RECTANGLE:    Qt.CrossCursor,
            TM.ELLIPSE:      Qt.CrossCursor,
            TM.COLOR_PICKER: Qt.CrossCursor,
            TM.HAND:         Qt.OpenHandCursor,
            TM.ZOOM:         Qt.CrossCursor,
        }.get(self._tool, Qt.ArrowCursor)

    def _sample_color(self, widget_pos: QPoint):
        """
        Color-picker: sample the visible colour at widget_pos.
        Renders the canvas to a QImage, reads the pixel, emits color_picked.
        """
        try:
            img = self.grab()          # QPixmap of the current widget
            if img.isNull():
                return
            qi  = img.toImage()
            x   = max(0, min(widget_pos.x(), qi.width()  - 1))
            y   = max(0, min(widget_pos.y(), qi.height() - 1))
            c   = qi.pixelColor(x, y)
            self.color_picked.emit(c)
        except Exception:
            pass

    def _commit_shape(self):
        """
        Convert the shape-drag rect into a new fill or paint layer.
        RECTANGLE → fill layer with solid color + transparency.
        ELLIPSE   → paint layer with ellipse drawn onto a transparent bitmap.
        """
        TM  = self._ToolMode
        x1  = min(self._shape_start_doc.x(), self._shape_cur_doc.x())
        y1  = min(self._shape_start_doc.y(), self._shape_cur_doc.y())
        x2  = max(self._shape_start_doc.x(), self._shape_cur_doc.x())
        y2  = max(self._shape_start_doc.y(), self._shape_cur_doc.y())
        w   = max(MIN_SIZE, x2 - x1)
        h   = max(MIN_SIZE, y2 - y1)

        if self._tool == TM.RECTANGLE:
            layer = Layer(
                kind="fill", name="Rectangle",
                x=x1, y=y1, w=w, h=h,
                fill_type="solid",
                fill_color=(80, 120, 200),
            )
        elif self._tool == TM.ELLIPSE:
            from PIL import ImageDraw
            img  = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([0, 0, w - 1, h - 1], fill=(80, 120, 200, 255))
            layer = Layer(
                kind="paint", name="Ellipse",
                x=x1, y=y1, w=w, h=h,
                pil_image=img,
            )
        else:
            return

        self.add_layer(layer)

    def _draw_shape_ghost(self, p: QPainter):
        """
        Draw the in-progress shape rubber-band over the canvas.
        Called from paintEvent when _shape_drawing is True.
        """
        x1  = min(self._shape_start_doc.x(), self._shape_cur_doc.x())
        y1  = min(self._shape_start_doc.y(), self._shape_cur_doc.y())
        x2  = max(self._shape_start_doc.x(), self._shape_cur_doc.x())
        y2  = max(self._shape_start_doc.y(), self._shape_cur_doc.y())

        tl  = self._c2w(QPoint(x1, y1))
        br  = self._c2w(QPoint(x2, y2))
        wr  = QRect(tl, br)

        p.save()
        p.setPen(QPen(QColor(100, 160, 255), 1, Qt.DashLine))
        p.setBrush(QBrush(QColor(80, 120, 200, 45)))
        TM = self._ToolMode
        if self._tool == TM.ELLIPSE:
            p.drawEllipse(wr)
        else:
            p.drawRect(wr)
        # dimension hint
        dw = x2 - x1; dh = y2 - y1
        if dw > 20 and dh > 12:
            p.setPen(QColor(200, 220, 255))
            p.setFont(QFont("Courier New", 9))
            p.drawText(wr.adjusted(4, 4, 0, 0),
                       Qt.AlignTop | Qt.AlignLeft,
                       f"{dw}×{dh}")
        p.restore()

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        self._update_viewport()
        idx = self._hit_layer(e.position().toPoint())
        if idx >= 0 and self._layers[idx].kind == "text":
            from PySide6.QtWidgets import QInputDialog
            l = self._layers[idx]
            text, ok = QInputDialog.getText(self, "Edit Text", "Text:", text=l.text)
            if ok:
                l.text = text; l.name = f"T: {text[:12]}"
                self._fx_cache = None
                self._push_history()
                self.layers_changed.emit(); self.update()

    def keyPressEvent(self, e: QKeyEvent):
        # Undo / Redo
        if e.modifiers() & Qt.ControlModifier:
            # Ctrl+Shift+Z must be checked before plain Ctrl+Z
            if e.key() == Qt.Key_Y or (e.key() == Qt.Key_Z and
                                        e.modifiers() & Qt.ShiftModifier):
                self.redo(); return
            if e.key() == Qt.Key_Z:
                self.undo(); return

        # Crop tool keyboard
        if self._crop_mode:
            if e.key() == Qt.Key_Return or e.key() == Qt.Key_Enter:
                self.exit_crop_mode(apply=True)
            elif e.key() == Qt.Key_Escape:
                self.exit_crop_mode(apply=False)
            return

        # ── Tool shortcuts ────────────────────────────────────────────────────
        try:
            from app.ui.toolBar import KEY_SHORTCUTS, ToolMode
            key_char = e.text().lower()
            if key_char in KEY_SHORTCUTS and not (e.modifiers() & Qt.ControlModifier):
                self.set_tool(KEY_SHORTCUTS[key_char])
                # Notify toolbar to sync highlight
                self.tool_shortcut_pressed.emit(KEY_SHORTCUTS[key_char])
                return
        except (ImportError, AttributeError):
            pass

        if e.key() == Qt.Key_Delete and self._sel >= 0:
            self.remove_layer(self._sel)
        step = 10 if e.modifiers() & Qt.ShiftModifier else 1
        if 0 <= self._sel < len(self._layers):
            l = self._layers[self._sel]
            if e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                if e.key() == Qt.Key_Left:  l.x -= step
                if e.key() == Qt.Key_Right: l.x += step
                if e.key() == Qt.Key_Up:    l.y -= step
                if e.key() == Qt.Key_Down:  l.y += step
                l.invalidate_transform()
                self._fx_cache = None
                # a burst of arrow presses is one undo step
                self._push_history(coalesce_key=("nudge", id(l)))
                self.layers_changed.emit()
                self.update()
                return
        super().keyPressEvent(e)

    def contextMenuEvent(self, e: QContextMenuEvent):
        self._update_viewport()
        idx = self._hit_layer(e.pos())
        if idx < 0: return
        if idx != self._sel:
            self._sel = idx
            self.layer_selected.emit(idx)
        self.update()
        m = QMenu(self)
        m.setStyleSheet("QMenu{background:#1e1e1e;border:1px solid #444;color:#ccc;"
                        "font-family:'Courier New';font-size:11px;}"
                        "QMenu::item:selected{background:#2a2a4a;}")
        m.addAction("🗑 Delete",    lambda: self.remove_layer(idx))
        m.addSeparator()
        m.addAction("▲ Move Up",   lambda: self.move_layer_up(idx))
        m.addAction("▼ Move Down", lambda: self.move_layer_down(idx))
        m.exec(e.globalPos())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_viewport()
        self.update()

    def wheelEvent(self, e):
        """
        Scroll wheel zooms the canvas.
        BUG FIX: wheel events from combo-boxes and sliders in the editor panel
        bubble up to the canvas via Qt's event propagation.  When they do, any
        in-progress drag/resize would previously leave _drag_active stuck True
        because mouseReleaseEvent never fires for a scroll.  We now cancel all
        interaction state on any wheel event so handles can't get orphaned.
        """
        from PySide6.QtWidgets import QApplication as _QA
        if not (_QA.mouseButtons() & Qt.LeftButton):
            self._cancel_interaction()

        delta = e.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else (1.0 / 1.15)
        self.set_zoom(self._zoom_factor * factor)

    def focusOutEvent(self, e):
        """
        BUG FIX: cancel all drag/resize/rotate state when the canvas loses
        focus (e.g. user clicks a combo-box or slider in the editor panel).
        Without this, the drag state stays True and the next mouse-press picks
        up a phantom delta, making layers teleport or handles disappear.
        """
        super().focusOutEvent(e)
        self._cancel_interaction()

    def leaveEvent(self, e):
        """
        BUG FIX: when the mouse leaves the canvas widget while a button is
        still held (e.g. dragging off the edge), Qt may not deliver a
        mouseReleaseEvent.  Cancel interaction so state doesn't stay stuck.
        """
        super().leaveEvent(e)
        if not (self._drag_active or self._resize_active or
                self._rotate_active or self._pan_active or self._hand_active):
            return
        # Only cancel if no buttons are actually pressed anymore
        from PySide6.QtWidgets import QApplication
        if not (QApplication.mouseButtons() & Qt.LeftButton) and \
           not (QApplication.mouseButtons() & Qt.MiddleButton):
            self._cancel_interaction()

    def _cancel_interaction(self):
        """
        Reset all interaction flags to a clean idle state.
        Safe to call at any time — commits a history snapshot if a move/resize
        was in progress so no work is lost.
        """
        was_active = (self._drag_active or self._resize_active or
                      self._rotate_active)
        self._drag_active      = False
        self._resize_active    = False
        self._rotate_active    = False
        self._pan_active       = False
        self._hand_active      = False
        self._guides_active    = False
        self._crop_drag_handle = -1
        self._smart_guides.clear()

        if was_active:
            self._push_history()
            self.layers_changed.emit()

        self.setCursor(self._tool_cursor())
        self.update()

    # ── export ─────────────────────────────────────────────────────────────────
    def compose_to_pil(self) -> PILImage.Image:
        """
        Export the document at its native resolution.

        Renders through the SAME painter code as the live preview
        (_render_scene → _paint_layer) into a QImage of doc size, then applies
        the global FX with the same seeded grain the preview uses — so the PNG
        is exactly what the canvas shows.
        """
        from PySide6.QtGui import QImage
        dw, dh = self._doc_size.width(), self._doc_size.height()

        img = QImage(dw, dh, QImage.Format.Format_RGBA8888)
        img.fill(Qt.transparent)

        # Map doc coords 1:1 — temporarily override the viewport transform
        saved = (self._scale, self._ox, self._oy)
        self._scale, self._ox, self._oy = 1.0, 0, 0
        try:
            p = QPainter(img)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.setRenderHint(QPainter.Antialiasing)
            self._render_scene(p, QRect(0, 0, dw, dh), export=True)
            p.end()
        finally:
            self._scale, self._ox, self._oy = saved

        arr = np.frombuffer(img.bits(), dtype=np.uint8).reshape((dh, dw, 4)).copy()
        grain = getattr(self, "_effects_grain", 0)
        ca    = getattr(self, "_effects_ca", 0)
        if grain > 0 or ca > 0:
            arr = arr.astype(np.float32)
            arr = self._apply_film_grain(arr, grain, seed=self._grain_seed)
            arr = self._apply_chromatic_aberration(arr, ca)
            arr = arr.clip(0, 255).astype(np.uint8)
        return PILImage.fromarray(arr, "RGBA")  # caller decides RGB vs RGBA

    # ── helpers ────────────────────────────────────────────────────────────────
    _CURSORS = [
        Qt.SizeFDiagCursor, Qt.SizeVerCursor,  Qt.SizeBDiagCursor,
        Qt.SizeHorCursor,
        Qt.SizeFDiagCursor, Qt.SizeVerCursor,  Qt.SizeBDiagCursor,
        Qt.SizeHorCursor,
        Qt.CrossCursor,   # 8 = rotation handle
    ]
    def _corner_cursor(self, c: int): return self._CURSORS[c]

    def reset_pan(self):
        """Reset canvas pan offset to center."""
        self._pan_offset = QPoint(0, 0)
        self._update_viewport()
        self.update()