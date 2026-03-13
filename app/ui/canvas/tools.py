"""
canvas/tools.py  —  Tool-mode mouse event handlers.

Each handler receives the PreviewCanvas instance and the mouse event.
They mutate canvas state directly (same as before, just extracted here
to keep previewCanvas.py focused on painting + public API).

Handlers (all called from PreviewCanvas):
  handle_press(canvas, event)
  handle_move(canvas, event)
  handle_release(canvas, event)
"""
from __future__ import annotations
import math
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QPoint, QRect
from PySide6.QtGui  import QMouseEvent

from app.ui.canvas.handles import hit_handle, MIN_SIZE, HANDLE_HALF

if TYPE_CHECKING:
    from app.ui.canvas.previewCanvas import PreviewCanvas


# ── Press ──────────────────────────────────────────────────────────────────────
def handle_press(canvas: "PreviewCanvas", e: QMouseEvent):
    canvas._update_viewport()
    pos = e.position().toPoint()
    TM  = canvas._ToolMode

    # Middle mouse → pan (all tool modes)
    if e.button() == Qt.MiddleButton:
        canvas._pan_active = True
        canvas._pan_start  = pos
        canvas.setCursor(Qt.ClosedHandCursor)
        return

    # Hand tool
    if canvas._tool == TM.HAND and e.button() == Qt.LeftButton:
        canvas._hand_active = True
        canvas._hand_start  = pos
        canvas.setCursor(Qt.ClosedHandCursor)
        return

    # Zoom tool
    if canvas._tool == TM.ZOOM and e.button() in (Qt.LeftButton, Qt.RightButton):
        zoom_in = (e.button() == Qt.LeftButton and
                not (e.modifiers() & Qt.ShiftModifier))
        step = 1.25 if zoom_in else (1.0 / 1.25)
        canvas.set_zoom(canvas._zoom_factor * step)
        return

    if e.button() != Qt.LeftButton:
        return

    # Brush / Eraser
    if canvas._tool in (TM.BRUSH, TM.ERASER):
        doc = canvas._w2c(pos)
        if canvas.brush_paint_requested:
            erasing = (canvas._tool == TM.ERASER)
            try:
                canvas.brush_paint_requested(doc.x(), doc.y(), erasing)
            except TypeError:
                canvas.brush_paint_requested(doc.x(), doc.y())
        return

    # Color picker
    if canvas._tool == TM.COLOR_PICKER:
        _sample_color(canvas, pos)
        return

    # Shape tools: start drag
    if canvas._tool in (TM.RECTANGLE, TM.ELLIPSE):
        canvas._shape_drawing   = True
        canvas._shape_start_doc = canvas._w2c(pos)
        canvas._shape_cur_doc   = canvas._w2c(pos)
        return

    # Crop mode
    if canvas._crop_mode and canvas._crop_rect:
        h = _hit_crop_handle(canvas, pos)
        if h >= 0:
            canvas._crop_drag_handle = h
            canvas._crop_drag_start  = pos
            canvas._crop_orig_rect   = QRect(canvas._crop_rect)
            return
        cr_tl = canvas._c2w(QPoint(canvas._crop_rect.left(),  canvas._crop_rect.top()))
        cr_br = canvas._c2w(QPoint(canvas._crop_rect.right(), canvas._crop_rect.bottom()))
        if QRect(cr_tl, cr_br).contains(pos):
            canvas._crop_drag_handle = 4
            canvas._crop_drag_start  = pos
            canvas._crop_orig_rect   = QRect(canvas._crop_rect)
        return

    # MOVE tool: handles + drag
    if 0 <= canvas._sel < len(canvas._layers):
        layer = canvas._layers[canvas._sel]
        if not canvas._is_locked(layer):
            corner = hit_handle(canvas, layer, pos)
            if corner == 8:
                canvas._rotate_active = True
                wr = canvas._layer_wrect(layer)
                canvas._rotate_cx = (wr.left() + wr.right()) / 2.0
                canvas._rotate_cy = (wr.top()  + wr.bottom()) / 2.0
                canvas._rotate_start_ang = math.degrees(
                    math.atan2(pos.y() - canvas._rotate_cy,
                               pos.x() - canvas._rotate_cx))
                canvas._rotate_orig_ang = layer.rotation
                canvas._drag_start = pos
                canvas.setCursor(Qt.CrossCursor)
                return
            if corner >= 0:
                canvas._resize_active  = True
                canvas._resize_corner  = corner
                canvas._drag_start     = pos
                canvas._orig_rect      = QRect(layer.x, layer.y, layer.w, layer.h)
                canvas._ar_ratio       = layer.w / max(1, layer.h)
                canvas._resize_rotation = layer.rotation
                canvas.setCursor(canvas._corner_cursor(corner))
                return

    idx = canvas._hit_layer(pos)
    canvas._sel = idx
    if idx >= 0:
        layer = canvas._layers[idx]
        if not canvas._is_locked(layer):
            canvas._drag_active = True
            canvas._drag_start  = pos
            canvas._orig_rect   = QRect(layer.x, layer.y, layer.w, layer.h)
            canvas.setCursor(Qt.SizeAllCursor)
        canvas.layer_selected.emit(idx)
    else:
        canvas.layer_selected.emit(-1)
    canvas.update()


# ── Move ───────────────────────────────────────────────────────────────────────
def handle_move(canvas: "PreviewCanvas", e: QMouseEvent):
    canvas._update_viewport()
    pos = e.position().toPoint()
    TM  = canvas._ToolMode

    # MMB Pan
    if canvas._pan_active:
        delta = pos - canvas._pan_start
        canvas._pan_offset += delta
        canvas._pan_start   = pos
        canvas._update_viewport()
        canvas.update()
        return

    # Hand tool pan
    if canvas._hand_active and (e.buttons() & Qt.LeftButton):
        delta = pos - canvas._hand_start
        canvas._pan_offset += delta
        canvas._hand_start  = pos
        canvas._update_viewport()
        canvas.update()
        return

    # Brush / Eraser
    if canvas._tool in (TM.BRUSH, TM.ERASER) and (e.buttons() & Qt.LeftButton):
        doc = canvas._w2c(pos)
        if canvas.brush_paint_requested:
            erasing = (canvas._tool == TM.ERASER)
            try:
                canvas.brush_paint_requested(doc.x(), doc.y(), erasing)
            except TypeError:
                canvas.brush_paint_requested(doc.x(), doc.y())
        return

    # Shape drag
    if canvas._shape_drawing and (e.buttons() & Qt.LeftButton):
        canvas._shape_cur_doc = canvas._w2c(pos)
        canvas.update()
        return

    # Color picker drag
    if canvas._tool == TM.COLOR_PICKER and (e.buttons() & Qt.LeftButton):
        _sample_color(canvas, pos)
        return

    # Crop drag
    if canvas._crop_mode and canvas._crop_drag_handle >= 0 and canvas._crop_orig_rect:
        dx = int((pos.x() - canvas._crop_drag_start.x()) / canvas._scale)
        dy = int((pos.y() - canvas._crop_drag_start.y()) / canvas._scale)
        r  = QRect(canvas._crop_orig_rect)
        h  = canvas._crop_drag_handle
        layer = canvas.selected_layer()
        lx, ly = (layer.x, layer.y) if layer else (0, 0)
        lw, lh = (layer.w, layer.h) if layer else (canvas._doc_size.width(), canvas._doc_size.height())
        if   h == 0: r.setLeft(min(r.right()-10, r.left()+dx));  r.setTop(min(r.bottom()-10, r.top()+dy))
        elif h == 1: r.setRight(max(r.left()+10, r.right()+dx)); r.setTop(min(r.bottom()-10, r.top()+dy))
        elif h == 2: r.setRight(max(r.left()+10, r.right()+dx)); r.setBottom(max(r.top()+10, r.bottom()+dy))
        elif h == 3: r.setLeft(min(r.right()-10, r.left()+dx));  r.setBottom(max(r.top()+10, r.bottom()+dy))
        elif h == 4: r.moveLeft(r.left()+dx); r.moveTop(r.top()+dy)
        r.setLeft(max(lx, r.left()));      r.setTop(max(ly, r.top()))
        r.setRight(min(lx+lw, r.right())); r.setBottom(min(ly+lh, r.bottom()))
        canvas._crop_rect = r
        canvas.update()
        return

    # Rotation
    if canvas._rotate_active and 0 <= canvas._sel < len(canvas._layers):
        layer = canvas._layers[canvas._sel]
        if canvas._is_locked(layer):
            canvas._rotate_active = False
            return
        cx  = getattr(canvas, "_rotate_cx", 0.0)
        cy  = getattr(canvas, "_rotate_cy", 0.0)
        cur_ang = math.degrees(math.atan2(pos.y() - cy, pos.x() - cx))
        delta   = cur_ang - canvas._rotate_start_ang
        new_ang = canvas._rotate_orig_ang + delta
        if e.modifiers() & Qt.ShiftModifier:
            new_ang = round(new_ang / 15) * 15
        layer.rotation = new_ang % 360
        layer.invalidate()
        canvas.update()
        return

    # Move layer
    if canvas._drag_active and 0 <= canvas._sel < len(canvas._layers):
        layer = canvas._layers[canvas._sel]
        if canvas._is_locked(layer):
            canvas._drag_active = False
            return
        dx = int((pos.x() - canvas._drag_start.x()) / canvas._scale)
        dy = int((pos.y() - canvas._drag_start.y()) / canvas._scale)

        if layer.kind == "group":
            for child_idx in getattr(layer, "children", []):
                if 0 <= child_idx < len(canvas._layers):
                    cl = canvas._layers[child_idx]
                    cl.x = cl.x - (layer.x - (canvas._orig_rect.x() + dx))
                    cl.y = cl.y - (layer.y - (canvas._orig_rect.y() + dy))
                    cl.invalidate()

        orig = canvas._orig_rect
        layer.x = orig.x() + dx
        layer.y = orig.y() + dy

        canvas._guides_active = True
        sdx, sdy = canvas._smart_guides.update(layer, snap=True)
        if sdx: layer.x += sdx
        if sdy: layer.y += sdy
        canvas.update()
        return

    # Resize layer
    if canvas._resize_active and 0 <= canvas._sel < len(canvas._layers):
        layer = canvas._layers[canvas._sel]
        if canvas._is_locked(layer):
            canvas._resize_active = False
            return

        c    = canvas._resize_corner
        orig = canvas._orig_rect

        rot_rad = math.radians(canvas._resize_rotation)
        cos_r   = math.cos(rot_rad)
        sin_r   = math.sin(rot_rad)

        wdx = float(pos.x() - canvas._drag_start.x())
        wdy = float(pos.y() - canvas._drag_start.y())
        ldx = ( wdx * cos_r + wdy * sin_r) / canvas._scale
        ldy = (-wdx * sin_r + wdy * cos_r) / canvas._scale

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
            ratio = canvas._ar_ratio
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

        hw_o, hh_o = ow / 2.0, oh / 2.0
        hw_n, hh_n = new_w / 2.0, new_h / 2.0

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

        aw_x = orig_cx + anchor_u_orig * cos_r  + anchor_v_orig * (-sin_r)
        aw_y = orig_cy + anchor_u_orig * sin_r  + anchor_v_orig * ( cos_r)

        new_cx = aw_x - anchor_u_new * cos_r  - anchor_v_new * (-sin_r)
        new_cy = aw_y - anchor_u_new * sin_r  - anchor_v_new * ( cos_r)

        layer.w = int(new_w); layer.h = int(new_h)
        layer.x = int(new_cx - new_w / 2.0)
        layer.y = int(new_cy - new_h / 2.0)

        layer.invalidate()
        canvas._guides_active = True
        canvas._smart_guides.update(layer, snap=False)
        canvas.update()
        return

    # ── Hover cursors ──────────────────────────────────────────────────────────
    if canvas._tool == TM.HAND:
        canvas.setCursor(Qt.OpenHandCursor)
        return
    if canvas._tool == TM.ZOOM:
        canvas.setCursor(Qt.CrossCursor)
        return
    if canvas._tool in (TM.BRUSH, TM.ERASER, TM.RECTANGLE, TM.ELLIPSE, TM.COLOR_PICKER):
        canvas.setCursor(Qt.CrossCursor)
        return

    if canvas._crop_mode:
        h = _hit_crop_handle(canvas, pos)
        canvas.setCursor(Qt.SizeFDiagCursor if h in (0, 2) else
                         Qt.SizeBDiagCursor if h in (1, 3) else
                         Qt.SizeAllCursor   if h == 4       else
                         Qt.CrossCursor)
        return

    if 0 <= canvas._sel < len(canvas._layers):
        layer = canvas._layers[canvas._sel]
        corner = hit_handle(canvas, layer, pos)
        if corner == 8:
            canvas.setCursor(Qt.CrossCursor)
            return
        if corner >= 0:
            rot = layer.rotation if hasattr(layer, "rotation") else 0.0
            canvas.setCursor(canvas._corner_cursor(corner) if rot == 0.0
                             else Qt.SizeAllCursor)
            return
        if canvas._hit_layer(pos) == canvas._sel:
            canvas.setCursor(Qt.SizeAllCursor)
            return
    canvas.setCursor(Qt.ArrowCursor)


# ── Release ────────────────────────────────────────────────────────────────────
def handle_release(canvas: "PreviewCanvas", e: QMouseEvent):
    TM = canvas._ToolMode

    if e.button() == Qt.MiddleButton:
        canvas._pan_active = False
        canvas.setCursor(canvas._tool_cursor())
        return

    if e.button() == Qt.LeftButton:
        if canvas._hand_active:
            canvas._hand_active = False
            canvas.setCursor(Qt.OpenHandCursor)
            return

        if canvas._shape_drawing:
            canvas._shape_drawing = False
            canvas._commit_shape()
            return

        canvas._crop_drag_handle = -1
        moved = canvas._drag_active or canvas._resize_active or canvas._rotate_active
        canvas._drag_active = canvas._resize_active = canvas._rotate_active = False
        canvas._guides_active = False
        canvas._smart_guides.clear()
        canvas.setCursor(Qt.CrossCursor if canvas._crop_mode
                         else canvas._tool_cursor())
        if moved:
            canvas._push_history()
            canvas.layers_changed.emit()


# ── Private helpers ────────────────────────────────────────────────────────────
def _sample_color(canvas: "PreviewCanvas", widget_pos: QPoint):
    try:
        img = canvas.grab()
        if img.isNull():
            return
        qi = img.toImage()
        x  = max(0, min(widget_pos.x(), qi.width()  - 1))
        y  = max(0, min(widget_pos.y(), qi.height() - 1))
        canvas.color_picked.emit(qi.pixelColor(x, y))
    except Exception:
        pass


def _crop_handle_rects(canvas: "PreviewCanvas"):
    if not canvas._crop_rect:
        return []
    r = canvas._crop_rect
    corners = [QPoint(r.left(), r.top()), QPoint(r.right(), r.top()),
               QPoint(r.right(), r.bottom()), QPoint(r.left(), r.bottom())]
    hs = 10
    return [QRect(canvas._c2w(c).x() - hs // 2,
                  canvas._c2w(c).y() - hs // 2, hs, hs)
            for c in corners]


def _hit_crop_handle(canvas: "PreviewCanvas", pos: QPoint) -> int:
    for i, hr in enumerate(_crop_handle_rects(canvas)):
        if hr.contains(pos):
            return i
    return -1