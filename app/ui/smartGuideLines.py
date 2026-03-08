"""
smartGuideLines.py  —  Smart Guides for Steam Grunge Editor

Collects alignment candidates from the canvas (document bounds + all visible
layers including group children), detects proximity during move/resize, draws
temporary guide lines, and applies optional soft snapping.

Usage
─────
Instantiated once by PreviewCanvas:

    from app.ui.smartGuideLines import SmartGuides
    self._smart_guides = SmartGuides(canvas=self)

Then called inside:

    mouseMoveEvent  →  self._smart_guides.update(layer, snap=True)
                       returns (snapped_dx, snapped_dy) offset correction
    paintEvent      →  self._smart_guides.draw(painter, canvas_rect)
    mouseReleaseEvent → self._smart_guides.clear()

Architecture
────────────
SmartGuides
  ├── _collect_candidates()   → list[AlignRect]   (doc + visible layers)
  ├── _align_points(rect)     → AlignPoints        (l/cx/r, t/cy/b)
  ├── _detect(moving, others) → list[Guide]        (h or v lines in doc coords)
  ├── draw(painter, cr)       → renders guides in widget space
  └── clear()                 → removes all active guides
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing      import List, Optional, Tuple

from PySide6.QtCore import QRect, QLine
from PySide6.QtGui  import QColor, QPen, QPainter
from PySide6.QtCore import Qt

# ── tunables ──────────────────────────────────────────────────────────────────
SNAP_THRESHOLD  = 6    # px in document space: below this → snap
GUIDE_THRESHOLD = 8    # px in document space: below this → show guide
SNAP_STRENGTH   = 1.0  # 1.0 = hard snap, 0.5 = soft pull

_GUIDE_H_COLOR  = QColor(0,   200, 255, 220)   # horizontal guide: cyan
_GUIDE_V_COLOR  = QColor(255, 80,  200, 220)   # vertical guide  : magenta
_GUIDE_W        = 1                             # line width in px


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class AlignPoints:
    left:    int
    center_x: int
    right:   int
    top:     int
    center_y: int
    bottom:  int

    def h_points(self) -> List[int]:   # horizontal positions (x-axis)
        return [self.left, self.center_x, self.right]

    def v_points(self) -> List[int]:   # vertical positions   (y-axis)
        return [self.top, self.center_y, self.bottom]


@dataclass
class Guide:
    """One guide line in document (canvas) coordinate space."""
    horizontal: bool     # True → horizontal line at y=pos, False → vertical at x=pos
    pos: int             # doc-space position
    span_start: int      # doc-space start of the line (for limited-length guides)
    span_end:   int      # doc-space end


# ─────────────────────────────────────────────────────────────────────────────
class SmartGuides:

    def __init__(self, canvas):
        self._canvas  = canvas
        self._guides: List[Guide] = []

    # ── public API ────────────────────────────────────────────────────────────

    def update(self, moving_layer, snap: bool = True) -> Tuple[int, int]:
        """
        Call during mouseMoveEvent after the layer position has been updated.

        Returns (dx, dy) correction in document coords that should be added
        to the layer position for snapping.  Returns (0, 0) if no snap.
        """
        self._guides.clear()

        ap_moving = self._align_points(moving_layer)
        candidates = self._collect_candidates(moving_layer)

        snap_x = None   # snapped x doc-coord (None = no snap)
        snap_y = None

        used_h: set[int] = set()   # avoid duplicate guide lines
        used_v: set[int] = set()

        # Compare each of our 3 h-points vs each candidate's 3 h-points
        for cand_ap, cand_rect in candidates:
            for my_x in ap_moving.h_points():
                for tgt_x in cand_ap.h_points():
                    diff = abs(my_x - tgt_x)
                    if diff <= GUIDE_THRESHOLD:
                        if tgt_x not in used_v:
                            # vertical guide line (constant x)
                            span_s = min(moving_layer.y,
                                         cand_rect.top()    if hasattr(cand_rect,'top') else cand_rect[1])
                            span_e = max(moving_layer.y + moving_layer.h,
                                         cand_rect.bottom() if hasattr(cand_rect,'bottom') else cand_rect[3])
                            self._guides.append(Guide(
                                horizontal=False, pos=tgt_x,
                                span_start=span_s, span_end=span_e))
                            used_v.add(tgt_x)
                        # Snap: pick whichest of our points triggered first
                        if snap and diff <= SNAP_THRESHOLD and snap_x is None:
                            snap_x = tgt_x - my_x   # correction

            for my_y in ap_moving.v_points():
                for tgt_y in cand_ap.v_points():
                    diff = abs(my_y - tgt_y)
                    if diff <= GUIDE_THRESHOLD:
                        if tgt_y not in used_h:
                            span_s = min(moving_layer.x,
                                         cand_rect.left()   if hasattr(cand_rect,'left') else cand_rect[0])
                            span_e = max(moving_layer.x + moving_layer.w,
                                         cand_rect.right()  if hasattr(cand_rect,'right') else cand_rect[2])
                            self._guides.append(Guide(
                                horizontal=True, pos=tgt_y,
                                span_start=span_s, span_end=span_e))
                            used_h.add(tgt_y)
                        if snap and diff <= SNAP_THRESHOLD and snap_y is None:
                            snap_y = tgt_y - my_y

        dx = int(snap_x * SNAP_STRENGTH) if snap_x is not None else 0
        dy = int(snap_y * SNAP_STRENGTH) if snap_y is not None else 0
        return dx, dy

    def draw(self, painter: QPainter, canvas_rect: QRect):
        """
        Call inside paintEvent, after layers are drawn, before p.end().
        canvas_rect is the QRect of the document in widget space.
        """
        if not self._guides:
            return

        c = self._canvas

        for g in self._guides:
            if g.horizontal:
                # Horizontal line: convert y from doc→widget, x spans full width
                wy  = int(g.pos * c._scale + c._oy)
                wx0 = int(g.span_start * c._scale + c._ox)
                wx1 = int(g.span_end   * c._scale + c._ox)
                # Clamp to canvas widget rect
                wx0 = max(canvas_rect.left(),  wx0)
                wx1 = min(canvas_rect.right(), wx1)
                pen = QPen(_GUIDE_H_COLOR, _GUIDE_W, Qt.SolidLine)
                painter.setPen(pen)
                painter.drawLine(wx0, wy, wx1, wy)

                # Small perpendicular tick marks for clarity
                pen2 = QPen(_GUIDE_H_COLOR, 1)
                painter.setPen(pen2)
                for tx in (wx0, wx1):
                    painter.drawLine(tx, wy - 4, tx, wy + 4)

            else:
                # Vertical line: convert x from doc→widget, y spans full height
                wx  = int(g.pos * c._scale + c._ox)
                wy0 = int(g.span_start * c._scale + c._oy)
                wy1 = int(g.span_end   * c._scale + c._oy)
                wy0 = max(canvas_rect.top(),    wy0)
                wy1 = min(canvas_rect.bottom(), wy1)
                pen = QPen(_GUIDE_V_COLOR, _GUIDE_W, Qt.SolidLine)
                painter.setPen(pen)
                painter.drawLine(wx, wy0, wx, wy1)

                pen2 = QPen(_GUIDE_V_COLOR, 1)
                painter.setPen(pen2)
                for ty in (wy0, wy1):
                    painter.drawLine(wx - 4, ty, wx + 4, ty)

    def clear(self):
        """Call on mouseRelease to remove all guides."""
        if self._guides:
            self._guides.clear()
            self._canvas.update()

    # ── internals ─────────────────────────────────────────────────────────────

    def _align_points(self, layer) -> AlignPoints:
        x, y, w, h = layer.x, layer.y, layer.w, layer.h
        return AlignPoints(
            left     = x,
            center_x = x + w // 2,
            right    = x + w,
            top      = y,
            center_y = y + h // 2,
            bottom   = y + h,
        )

    def _align_points_from_rect(self, x, y, w, h) -> AlignPoints:
        return AlignPoints(
            left     = x,
            center_x = x + w // 2,
            right    = x + w,
            top      = y,
            center_y = y + h // 2,
            bottom   = y + h,
        )

    def _collect_candidates(self, moving_layer) -> List[Tuple[AlignPoints, object]]:
        """
        Return list of (AlignPoints, rect_obj) for:
          - the document bounding box
          - all visible non-selected layers (including group children)
          - group bounding boxes
        """
        c      = self._canvas
        layers = c._layers
        sel    = c._sel

        doc_w = c._doc_w if hasattr(c, '_doc_w') else c._canvas_rect().width()
        doc_h = c._doc_h if hasattr(c, '_doc_h') else c._canvas_rect().height()

        # Try to get real document dimensions
        try:
            doc_w = c._doc_w
            doc_h = c._doc_h
        except AttributeError:
            cr = c._canvas_rect()
            doc_w = int(cr.width()  / c._scale)
            doc_h = int(cr.height() / c._scale)

        results = []

        # 1. Document / canvas itself
        class _DocRect:
            def top(self): return 0
            def bottom(self): return doc_h
            def left(self): return 0
            def right(self): return doc_w

        results.append((
            self._align_points_from_rect(0, 0, doc_w, doc_h),
            _DocRect()
        ))

        # 2. All visible layers (skip selected, skip groups as containers)
        group_bounds: dict[int, list] = {}  # group_idx → [x,y,x2,y2] bbox

        for i, layer in enumerate(layers):
            if i == sel:
                continue
            if not layer.visible:
                continue
            if layer.kind == "group":
                # We'll compute group bbox from children below
                continue

            # Individual layer
            x, y, w, h = layer.x, layer.y, layer.w, layer.h
            if w <= 0 or h <= 0:
                continue

            class _LRect:
                def __init__(self, lx, ly, lw, lh):
                    self._x, self._y, self._w, self._h = lx, ly, lw, lh
                def top(self):    return self._y
                def bottom(self): return self._y + self._h
                def left(self):   return self._x
                def right(self):  return self._x + self._w

            results.append((
                self._align_points_from_rect(x, y, w, h),
                _LRect(x, y, w, h)
            ))

            # Accumulate into parent group bbox if applicable
            parent_idx = getattr(layer, '_group_parent', None)
            if parent_idx is not None and parent_idx != sel:
                if parent_idx not in group_bounds:
                    group_bounds[parent_idx] = [x, y, x+w, y+h]
                else:
                    gb = group_bounds[parent_idx]
                    gb[0] = min(gb[0], x)
                    gb[1] = min(gb[1], y)
                    gb[2] = max(gb[2], x + w)
                    gb[3] = max(gb[3], y + h)

        # 3. Group bounding boxes
        for gidx, (gx0, gy0, gx1, gy1) in group_bounds.items():
            gw, gh = gx1 - gx0, gy1 - gy0
            if gw <= 0 or gh <= 0:
                continue

            class _GRect:
                def __init__(self, lx, ly, lw, lh):
                    self._x, self._y, self._w, self._h = lx, ly, lw, lh
                def top(self):    return self._y
                def bottom(self): return self._y + self._h
                def left(self):   return self._x
                def right(self):  return self._x + self._w

            results.append((
                self._align_points_from_rect(gx0, gy0, gw, gh),
                _GRect(gx0, gy0, gw, gh)
            ))

        return results