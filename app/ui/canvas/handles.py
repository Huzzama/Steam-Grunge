"""
canvas/handles.py  —  Resize and rotation handle geometry + hit-testing.

All functions receive a PreviewCanvas instance (or the minimal attributes
they need) so they stay stateless and easy to test independently.

Public API:
  HANDLE_SIZE, HANDLE_HALF, MIN_SIZE   — shared constants
  handle_points(canvas, layer)         → List[QPointF]  (9 points: 0-7 resize, 8 rot)
  hit_handle(canvas, layer, pos)       → int  (-1 = miss)
  corner_cursor(corner)                → Qt.CursorShape
"""
from __future__ import annotations
import math
from typing import TYPE_CHECKING, List

from PySide6.QtCore import QPoint, QPointF, QRect
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from app.ui.canvas.previewCanvas import PreviewCanvas
    from app.ui.canvas.layers import Layer

# ── Shared geometry constants ──────────────────────────────────────────────────
HANDLE_SIZE = 12
HANDLE_HALF = HANDLE_SIZE // 2
MIN_SIZE    = 20

_CURSORS = [
    Qt.SizeFDiagCursor, Qt.SizeVerCursor,  Qt.SizeBDiagCursor,
    Qt.SizeHorCursor,
    Qt.SizeFDiagCursor, Qt.SizeVerCursor,  Qt.SizeBDiagCursor,
    Qt.SizeHorCursor,
    Qt.CrossCursor,   # 8 = rotation handle
]


def corner_cursor(corner: int) -> Qt.CursorShape:
    return _CURSORS[corner]


def handle_points(canvas: "PreviewCanvas", layer: "Layer") -> List[QPointF]:
    """
    Return 9 QPointF handle centres in widget space, rotated with the layer.
    Indices 0-7 = resize handles (TL,T,TR,R,BR,B,BL,L), 8 = rotation knob.
    """
    wr    = canvas._layer_wrect(layer)
    cx    = (wr.left()  + wr.right())  / 2.0
    cy    = (wr.top()   + wr.bottom()) / 2.0
    rot   = layer.rotation if hasattr(layer, "rotation") else 0.0
    rad   = math.radians(rot)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)

    def rp(x: float, y: float) -> QPointF:
        dx, dy = x - cx, y - cy
        return QPointF(cx + dx * cos_a - dy * sin_a,
                       cy + dx * sin_a + dy * cos_a)

    l_ = float(wr.left())
    r_ = float(wr.right())
    t_ = float(wr.top())
    b_ = float(wr.bottom())
    mx = cx
    my = cy

    pts: List[QPointF] = [
        rp(l_, t_),   # 0 TL
        rp(mx, t_),   # 1 T
        rp(r_, t_),   # 2 TR
        rp(r_, my),   # 3 R
        rp(r_, b_),   # 4 BR
        rp(mx, b_),   # 5 B
        rp(l_, b_),   # 6 BL
        rp(l_, my),   # 7 L
    ]

    # Rotation knob: STEM_LEN px above the rotated top-centre
    STEM_LEN = 32.0
    tc = pts[1]
    pts.append(QPointF(tc.x() - sin_a * STEM_LEN,
                       tc.y() - cos_a * STEM_LEN))   # 8 ROT
    return pts


def hit_handle(canvas: "PreviewCanvas", layer: "Layer", pos: QPoint) -> int:
    """
    Hit-test all 9 handles using point-distance (rotation-aware).
    Rotation knob (index 8) is checked first with a larger hit radius.
    Returns handle index or -1 if no hit.
    """
    pts = handle_points(canvas, layer)
    p   = QPointF(pos.x(), pos.y())

    # Rotation knob — larger radius
    ROT_THRESH = HANDLE_HALF + 9
    rh = pts[8]
    dx, dy = rh.x() - p.x(), rh.y() - p.y()
    if dx * dx + dy * dy <= ROT_THRESH * ROT_THRESH:
        return 8

    THRESH = HANDLE_HALF + 5
    for i, hp in enumerate(pts[:8]):
        dx, dy = hp.x() - p.x(), hp.y() - p.y()
        if dx * dx + dy * dy <= THRESH * THRESH:
            return i
    return -1