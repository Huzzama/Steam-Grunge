from __future__ import annotations
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image as PILImage

from PySide6.QtCore    import Qt, QPoint, QTimer, Signal
from PySide6.QtGui     import QColor, QCursor, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel, QSlider, QFrame,
    QPushButton, QMainWindow,
    QGraphicsDropShadowEffect,
)

from app.ui.kit   import IconButton, Divider, label, vbox, hbox
from app.ui.theme import C, R, SP

MIN_ALPHA          = 30
TB_WIDTH           = 64
SIDE_GAP           = 10
MAX_PALETTE_COLORS = 6
SWATCH_SIZE        = 22


class _Swatch(QPushButton):
    """Palette colour chip — painted, no stylesheet. clicked → replace this colour."""

    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.setFixedSize(SWATCH_SIZE, SWATCH_SIZE)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.set_color(color)

    def set_color(self, color: QColor):
        self.color = QColor(color)
        self.setToolTip(f"Replace rgb({self.color.red()},{self.color.green()},{self.color.blue()})")
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setBrush(self.color)
        p.setPen(QColor(C["accent"] if self.underMouse() else C["border_strong"]))
        p.drawRoundedRect(r, R["sm"], R["sm"])
        p.end()


def _replace_colour(img, old_c, new_c, tol=38):
    """Soft-replace old_c with new_c in a PIL RGBA image within the given tolerance."""
    arr = np.array(img.convert("RGBA"), dtype=np.float32)
    dist = np.sqrt((arr[:,:,0]-old_c.red())**2 + (arr[:,:,1]-old_c.green())**2 + (arr[:,:,2]-old_c.blue())**2)
    ratio = np.clip(1.0 - dist / tol, 0.0, 1.0)[:, :, np.newaxis]
    alive = (arr[:,:,3] >= MIN_ALPHA)[:, :, np.newaxis]
    new_rgb = np.array([new_c.red(), new_c.green(), new_c.blue()], np.float32)
    out = arr.copy()
    out[:,:,:3] = np.where(alive, arr[:,:,:3]*(1-ratio) + new_rgb*ratio, arr[:,:,:3])
    return PILImage.fromarray(out.clip(0, 255).astype(np.uint8), "RGBA")


def _extract_palette(pil_image: PILImage.Image,
                     n: int = MAX_PALETTE_COLORS) -> List[Tuple[int, int, int]]:
    """
    Return up to n dominant (R,G,B) tuples from pil_image via PIL median-cut.
    Transparent pixels are excluded before quantizing.
    Returns [] on any failure so callers can safely hide the COLORS section.
    """
    try:
        img = pil_image.convert("RGBA")
        # Composite onto black to drop transparent regions before color analysis
        bg = PILImage.new("RGB", img.size, (0, 0, 0))
        bg.paste(img.convert("RGB"), mask=img.split()[3])
        thumb = bg.copy()
        thumb.thumbnail((256, 256), PILImage.LANCZOS)
        quantized = thumb.quantize(colors=n, method=PILImage.Quantize.MEDIANCUT)
        palette = quantized.getpalette()   # flat [R,G,B, R,G,B, ...]
        if not palette:
            return []
        colors: List[Tuple[int, int, int]] = []
        for i in range(n):
            r, g, b = palette[i*3], palette[i*3+1], palette[i*3+2]
            if r + g + b < 12:   # skip near-black transparency artefacts
                continue
            colors.append((r, g, b))
            if len(colors) >= n:
                break
        return colors
    except Exception:
        return []


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
        self._swatch_btns:    List[_Swatch]                = []
        self._palette_colors: List[Tuple[int, int, int]] = []

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

        self._card = QFrame(self)
        self._card.setProperty("surface", "card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 180))
        self._card.setGraphicsEffect(shadow)
        outer.addWidget(self._card)

        inner = vbox(self._card, (SP["xs"], SP["xs"], SP["xs"], SP["xs"]), SP["xs"])
        inner.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # OPACITY
        op = QWidget()
        ol = vbox(op, (0, 0, 0, 0), 2)
        ol.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        ol.addWidget(self._sec_label("OPACITY"))
        self._op_sl = QSlider(Qt.Orientation.Vertical)
        self._op_sl.setRange(0, 100)
        self._op_sl.setValue(100)
        self._op_sl.setFixedHeight(70)
        self._op_sl.setToolTip("Layer opacity")
        self._op_sl.valueChanged.connect(self._on_opacity)
        self._op_lbl = label("100%", "mono", align=Qt.AlignmentFlag.AlignHCenter)
        ol.addWidget(self._op_sl, 0, Qt.AlignmentFlag.AlignHCenter)
        ol.addWidget(self._op_lbl)
        inner.addWidget(op)

        inner.addWidget(Divider())

        # COLORS — palette swatches, populated dynamically in _rebuild_swatches()
        self._colors_w = QWidget()
        cl = vbox(self._colors_w, (0, 0, 0, 0), 3)
        cl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        cl.addWidget(self._sec_label("COLORS"))
        self._swatch_grid = QWidget()
        self._swatch_layout = QGridLayout(self._swatch_grid)
        self._swatch_layout.setContentsMargins(0, 0, 0, 0)
        self._swatch_layout.setSpacing(3)
        cl.addWidget(self._swatch_grid, 0, Qt.AlignmentFlag.AlignHCenter)
        inner.addWidget(self._colors_w)

        inner.addWidget(Divider())

        # TOOLS
        tl_w = QWidget()
        tl = vbox(tl_w, (0, 0, 0, 0), SP["xs"])
        tl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        tl.addWidget(self._sec_label("TOOLS"))
        for icon, tip, slot in [
            ("crosshair",  "Crop layer",        self._on_crop),
            ("rotate-ccw", "Rotate layer -90°", lambda: self._on_rotate(-90)),
            ("rotate-cw",  "Rotate layer +90°", lambda: self._on_rotate(+90)),
        ]:
            tl.addWidget(IconButton(icon, tip, 15, on_click=slot), 0, Qt.AlignmentFlag.AlignHCenter)
        inner.addWidget(tl_w)

        self.setFixedWidth(TB_WIDTH + 14)

    def _sec_label(self, text):
        return label(text, "eyebrow", align=Qt.AlignmentFlag.AlignHCenter)

    def _refresh(self):
        if self._canvas is None:
            self.hide(); return
        layer = self._canvas.selected_layer()
        if layer is None or layer.kind in ("group", "text", "fill", "vector"):
            self.hide(); return

        show_colors = layer.kind in ("paint", "image", "file", "texture")
        self._colors_w.setVisible(show_colors)
        if show_colors and layer.pil_image is not None:
            self._rebuild_swatches(layer)
        else:
            self._clear_swatches()

        self._sync_opacity()
        self.adjustSize()
        self._do_reposition()
        self.show()
        self.raise_()

    def _rebuild_swatches(self, layer):
        """Extract palette from layer.pil_image and build clickable swatch buttons."""
        self._clear_swatches()
        colors = _extract_palette(layer.pil_image, MAX_PALETTE_COLORS)
        if not colors:
            self._colors_w.setVisible(False)
            return
        self._palette_colors = colors
        for i, (r, g, b) in enumerate(colors):
            btn = _Swatch(QColor(r, g, b))
            # Capture the button itself — its .color is updated after a replace
            btn.clicked.connect(
                lambda _chk=False, sw=btn: self._on_swatch_clicked(QColor(sw.color), sw)
            )
            self._swatch_layout.addWidget(btn, i // 2, i % 2)
            self._swatch_btns.append(btn)

    def _clear_swatches(self):
        for btn in self._swatch_btns:
            self._swatch_layout.removeWidget(btn)
            btn.deleteLater()
        self._swatch_btns.clear()
        self._palette_colors.clear()

    def _on_swatch_clicked(self, src_color: QColor, swatch: Optional[_Swatch] = None):
        """Open color picker seeded with src_color; on accept replace it in the layer."""
        if self._canvas is None:
            return
        layer = self._canvas.selected_layer()
        if layer is None or layer.pil_image is None:
            return
        from PySide6.QtWidgets import QColorDialog
        new_c = QColorDialog.getColor(
            src_color, self,
            f"Replace rgb({src_color.red()},{src_color.green()},{src_color.blue()})"
        )
        if not new_c.isValid():
            return
        new_img = _replace_colour(layer.pil_image, src_color, new_c)
        self._canvas.replace_selected_layer_image(new_img)
        # Update the clicked swatch face to the newly chosen color
        if swatch is None:
            swatch = next((b for b in self._swatch_btns if b.color == src_color), None)
        if swatch is not None:
            swatch.set_color(new_c)

    def _sync_opacity(self):
        if self._canvas is None: return
        layer = self._canvas.selected_layer()
        if layer is None: return
        val = int(round(getattr(layer, 'opacity', 1.0) * 100))
        self._op_sl.blockSignals(True)
        self._op_sl.setValue(val)
        self._op_sl.blockSignals(False)
        self._op_lbl.setText(f"{val}%")

    def _do_reposition(self):
        if self._canvas is None or not self.isVisible(): return
        layer = self._canvas.selected_layer()
        if layer is None: return

        wrect   = self._canvas.layer_widget_rect(layer)   # widget-space QRect
        cg      = self._canvas.mapToGlobal(QPoint(0, 0))
        tb_w    = self.width()
        tb_h    = self.height()

        # HANDLE_CLEAR: extra gap beyond the layer edge to avoid covering
        # the resize handles (handle half = 6px, plus 5px hit radius, plus margin)
        HANDLE_CLEAR = 20

        # Try left side first — clear handle area
        gx = cg.x() + wrect.left() - tb_w - SIDE_GAP - HANDLE_CLEAR
        gy = cg.y() + wrect.top() + wrect.height() // 2 - tb_h // 2

        # Not enough room on left → go right, also clearing right handles
        if gx < cg.x() + 4:
            gx = cg.x() + wrect.right() + SIDE_GAP + HANDLE_CLEAR

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

    def _mw(self):
        w = self.parent()
        while w:
            if isinstance(w, QMainWindow): return w
            w = w.parent()
        return None
