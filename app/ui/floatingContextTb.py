"""
floatingContextTb.py  —  Floating contextual toolbar for Steam Grunge Editor.

Frameless Qt.Tool window positioned to the LEFT of the selected object on the
canvas.  Feels like Canva's in-canvas contextual toolbar — detached, dynamic,
lightweight.
"""
from __future__ import annotations
import math
from typing import List, Optional

import numpy as np
from PIL import Image as PILImage

from PySide6.QtCore    import Qt, QPoint, QTimer, Signal
from PySide6.QtGui     import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QSlider, QFrame,
    QToolButton, QColorDialog, QMainWindow,
    QGraphicsDropShadowEffect,
)

MAX_SWATCHES = 8
SIMPLE_THRESH = 10
COLOUR_TOL = 38
MERGE_DELTA = 28
SWATCH_SZ = 26
MIN_ALPHA = 30
TB_WIDTH = 60
SIDE_GAP = 10
_BG    = "#16161f"
_BORDER= "#2e2e44"
_MONO  = "Courier New"


def _extract_palette(img):
    img = img.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)
    mask = arr[:, :, 3] >= MIN_ALPHA
    visible = arr[mask]
    if len(visible) < 10:
        return []
    step = max(1, len(visible) // 4000)
    sampled = visible[::step, :3]
    proxy = PILImage.fromarray(sampled.reshape(1, len(sampled), 3).astype(np.uint8), "RGB")
    try:
        q = proxy.quantize(colors=MAX_SWATCHES * 2, method=PILImage.Quantize.MEDIANCUT)
        pal = np.array(q.getpalette(), dtype=np.uint8).reshape(-1, 3)
        counts = np.bincount(np.array(q.getdata(), dtype=np.uint8), minlength=len(pal))
    except Exception:
        return []
    colours = []
    for idx in np.argsort(-counts):
        if counts[idx] == 0:
            continue
        r, g, b = int(pal[idx, 0]), int(pal[idx, 1]), int(pal[idx, 2])
        cand = QColor(r, g, b)
        if any(math.sqrt((cand.red()-e.red())**2 + (cand.green()-e.green())**2 + (cand.blue()-e.blue())**2) < MERGE_DELTA for e in colours):
            continue
        colours.append(cand)
        if len(colours) >= MAX_SWATCHES:
            break
    return colours


def _is_simple(img):
    if img is None:
        return False
    w, h = img.size
    if w * h > 1200 * 1200:
        return False
    arr = np.array(img.convert("RGBA"), dtype=np.uint8)
    visible = arr[arr[:, :, 3] >= MIN_ALPHA, :3]
    if len(visible) < 4:
        return False
    step = max(1, len(visible) // 2000)
    proxy = PILImage.fromarray(visible[::step].reshape(1, -1, 3).astype(np.uint8), "RGB")
    try:
        q = proxy.quantize(colors=SIMPLE_THRESH, method=PILImage.Quantize.MEDIANCUT)
        return len(set(q.getdata())) <= SIMPLE_THRESH
    except Exception:
        return False


def _replace_colour(img, old_c, new_c, tol=COLOUR_TOL):
    arr = np.array(img.convert("RGBA"), dtype=np.float32)
    dist = np.sqrt((arr[:,:,0]-old_c.red())**2 + (arr[:,:,1]-old_c.green())**2 + (arr[:,:,2]-old_c.blue())**2)
    ratio = np.clip(1.0 - dist / tol, 0.0, 1.0)[:, :, np.newaxis]
    alive = (arr[:,:,3] >= MIN_ALPHA)[:, :, np.newaxis]
    new_rgb = np.array([new_c.red(), new_c.green(), new_c.blue()], np.float32)
    out = arr.copy()
    out[:,:,:3] = np.where(alive, arr[:,:,:3]*(1-ratio) + new_rgb*ratio, arr[:,:,:3])
    return PILImage.fromarray(out.clip(0, 255).astype(np.uint8), "RGBA")


class _Swatch(QToolButton):
    replace = Signal(QColor, QColor)

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._c = color
        self.setFixedSize(SWATCH_SZ + 2, SWATCH_SZ + 2)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(color.name().upper())
        self._style()
        self.clicked.connect(self._pick)

    def _style(self):
        lum = 0.299*self._c.red() + 0.587*self._c.green() + 0.114*self._c.blue()
        border = "#aaa" if lum < 80 else "#444"
        self.setStyleSheet(f"QToolButton{{background:{self._c.name()};border:2px solid {border};border-radius:4px;}} QToolButton:hover{{border-color:#aabbff;}}")

    def _pick(self):
        dlg = QColorDialog(self._c, self)
        dlg.setOption(QColorDialog.ShowAlphaChannel, False)
        if dlg.exec():
            new = dlg.selectedColor()
            old = QColor(self._c)
            self._c = new
            self._style()
            self.replace.emit(old, new)


class FloatingContextTb(QWidget):
    """
    Frameless floating toolbar.  Parent should be the canvas widget so
    mapToGlobal positions correctly.

    Usage in MainWindow._build_ui():
        self.ctx_tb = FloatingContextTb(self.preview_canvas)
        self.ctx_tb.set_canvas(self.preview_canvas)
    """

    def __init__(self, parent=None):
        super().__init__(parent,
                         Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._canvas = None
        self._swatches: List[_Swatch] = []

        self._repos_timer = QTimer(self)
        self._repos_timer.setSingleShot(True)
        self._repos_timer.setInterval(25)
        self._repos_timer.timeout.connect(self._do_reposition)

        self._build_ui()
        self.hide()

    def set_canvas(self, canvas):
        self._canvas = canvas
        # Qt.Tool windows must be children of the top-level QMainWindow to float
        # correctly over the application — find it and re-parent.
        top = canvas
        while top.parent() is not None:
            top = top.parent()
        if top is not self.parent():
            self.setParent(top, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
        canvas.layer_selected.connect(self._on_sel)
        canvas.layers_changed.connect(self._on_changed)

    def _on_sel(self, idx):
        self._refresh()

    def _on_changed(self):
        self._sync_opacity()
        self._repos_timer.start()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(7, 7, 7, 7)

        self._card = QWidget(self)
        self._card.setObjectName("card")
        self._card.setStyleSheet(f"""
            #card {{
                background:{_BG};
                border:1px solid {_BORDER};
                border-radius:10px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 180))
        self._card.setGraphicsEffect(shadow)
        outer.addWidget(self._card)

        inner = QVBoxLayout(self._card)
        inner.setContentsMargins(6, 8, 6, 8)
        inner.setSpacing(6)
        inner.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        # COLORS
        self._col_sec = QWidget()
        cl = QVBoxLayout(self._col_sec)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(3)
        cl.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        cl.addWidget(self._sec_label("COLORS"))
        self._sw_box = QWidget()
        self._sw_vl = QVBoxLayout(self._sw_box)
        self._sw_vl.setContentsMargins(0, 0, 0, 0)
        self._sw_vl.setSpacing(3)
        self._sw_vl.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        cl.addWidget(self._sw_box)
        inner.addWidget(self._col_sec)

        self._sep1 = _Div()
        inner.addWidget(self._sep1)

        # OPACITY
        op = QWidget()
        ol = QVBoxLayout(op)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(2)
        ol.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        ol.addWidget(self._sec_label("OPACITY"))
        self._op_sl = QSlider(Qt.Vertical)
        self._op_sl.setRange(0, 100)
        self._op_sl.setValue(100)
        self._op_sl.setFixedHeight(70)
        self._op_sl.setStyleSheet("""
            QSlider::groove:vertical{background:#222233;width:4px;border-radius:2px;}
            QSlider::handle:vertical{background:#5566cc;border:1px solid #3344aa;width:12px;height:12px;margin:-4px -4px;border-radius:6px;}
            QSlider::sub-page:vertical{background:#5566cc;border-radius:2px;}
        """)
        self._op_sl.valueChanged.connect(self._on_opacity)
        self._op_lbl = QLabel("100%")
        self._op_lbl.setAlignment(Qt.AlignHCenter)
        self._op_lbl.setStyleSheet(f"color:#555;font-size:8px;font-family:'{_MONO}';background:transparent;")
        ol.addWidget(self._op_sl, 0, Qt.AlignHCenter)
        ol.addWidget(self._op_lbl)
        inner.addWidget(op)

        inner.addWidget(_Div())

        # TOOLS
        tl_w = QWidget()
        tl = QVBoxLayout(tl_w)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(4)
        tl.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        tl.addWidget(self._sec_label("TOOLS"))

        btn_ss = f"""
            QToolButton{{background:#1a1a28;color:#555;border:1px solid {_BORDER};border-radius:6px;font-size:14px;min-width:34px;min-height:34px;max-width:34px;max-height:34px;}}
            QToolButton:hover{{background:#222238;color:#aaa;border-color:#4455aa;}}
            QToolButton:pressed{{background:#2a2a50;}}
        """
        for icon, tip, slot in [
            ("✂",  "Crop",        self._on_crop),
            ("↺",  "Rotate −90°", lambda: self._on_rotate(-90)),
            ("↻",  "Rotate +90°", lambda: self._on_rotate(+90)),
        ]:
            b = QToolButton()
            b.setText(icon)
            b.setToolTip(tip)
            b.setStyleSheet(btn_ss)
            b.clicked.connect(slot)
            tl.addWidget(b, 0, Qt.AlignHCenter)
        inner.addWidget(tl_w)

        self.setFixedWidth(TB_WIDTH + 14)

    def _sec_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:#383858;font-size:7px;font-weight:bold;letter-spacing:1px;font-family:'{_MONO}';background:transparent;")
        lbl.setAlignment(Qt.AlignHCenter)
        return lbl

    def _refresh(self):
        if self._canvas is None:
            self.hide(); return
        layer = self._canvas.selected_layer()
        if layer is None or layer.kind in ("group", "text", "fill", "vector"):
            self.hide(); return

        pil = layer.pil_image
        if pil is not None and _is_simple(pil):
            self._rebuild_swatches(_extract_palette(pil))
            self._col_sec.setVisible(True)
            self._sep1.setVisible(True)
        else:
            self._clear_swatches()
            self._col_sec.setVisible(False)
            self._sep1.setVisible(False)

        self._sync_opacity()
        self.adjustSize()
        self._do_reposition()
        self.show()
        self.raise_()

    def _sync_opacity(self):
        if self._canvas is None: return
        layer = self._canvas.selected_layer()
        if layer is None: return
        val = int(round(getattr(layer, 'opacity', 1.0) * 100))
        self._op_sl.blockSignals(True)
        self._op_sl.setValue(val)
        self._op_sl.blockSignals(False)
        self._op_lbl.setText(f"{val}%")

    def _clear_swatches(self):
        for s in self._swatches:
            s.setParent(None); s.deleteLater()
        self._swatches.clear()

    def _rebuild_swatches(self, colours):
        self._clear_swatches()
        for c in colours:
            s = _Swatch(c, self._sw_box)
            s.replace.connect(self._on_col_replace)
            self._sw_vl.addWidget(s, 0, Qt.AlignHCenter)
            self._swatches.append(s)

    def _do_reposition(self):
        if self._canvas is None or not self.isVisible(): return
        layer = self._canvas.selected_layer()
        if layer is None: return

        wrect   = self._canvas._layer_wrect(layer)   # widget-space QRect
        cg      = self._canvas.mapToGlobal(QPoint(0, 0))
        tb_w    = self.width()
        tb_h    = self.height()

        # Try left side first
        gx = cg.x() + wrect.left() - tb_w - SIDE_GAP
        gy = cg.y() + wrect.top() + wrect.height() // 2 - tb_h // 2

        # Not enough room on left → go right
        if gx < cg.x() + 4:
            gx = cg.x() + wrect.right() + SIDE_GAP

        # Clamp to canvas vertical bounds
        gy = max(cg.y() + 4, min(gy, cg.y() + self._canvas.height() - tb_h - 4))

        self.move(gx, gy)

    def _on_opacity(self, val):
        self._op_lbl.setText(f"{val}%")
        if self._canvas:
            self._canvas.update_selected_layer(opacity=val / 100.0)

    def _on_crop(self):
        mw = self._mw()
        if mw and hasattr(mw, '_toggle_crop'):
            mw._toggle_crop(True)

    def _on_rotate(self, delta):
        if self._canvas is None: return
        layer = self._canvas.selected_layer()
        if layer is None: return
        self._canvas.update_selected_layer(rotation=(getattr(layer, 'rotation', 0.0) + delta) % 360)

    def _on_col_replace(self, old_c, new_c):
        if self._canvas is None: return
        layer = self._canvas.selected_layer()
        if layer is None or layer.pil_image is None: return
        layer.pil_image = _replace_colour(layer.pil_image, old_c, new_c)
        layer.invalidate()
        self._canvas.layers_changed.emit()
        self._canvas.update()

    def _mw(self):
        w = self.parent()
        while w:
            if isinstance(w, QMainWindow): return w
            w = w.parent()
        return None


class _Div(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.HLine)
        self.setStyleSheet(f"color:{_BORDER};background:{_BORDER};max-height:1px;")