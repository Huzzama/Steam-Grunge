"""
widgets.py  —  Reusable primitive UI widgets for the Steam Grunge Editor.

All widgets follow the dark steam-grunge aesthetic:
  Background:  #1a1a22
  Borders:     #2e2e3e
  Text:        #888 (dim), #ccc (active), #fff (accent)
  Accent:      #5566cc (blue-purple)

Exported widgets:
  LabeledSlider    — horizontal slider with label + live readout
  ColorSwatch      — clickable square that opens QColorDialog
  IconButton       — flat icon-only QPushButton with hover glow
  SectionHeader    — uppercase monospace section divider
  HRule            — subtle horizontal separator line
  TagBadge         — small pill label (file type, status, etc.)
  CollapsibleBox   — expandable/collapsible group container
  SearchBar        — styled QLineEdit with magnifier icon + clear button
  StatusBar        — one-line status text at the bottom of a panel
  ToolRow          — horizontal group of small tool buttons
  NumericInput     — validated integer/float QLineEdit with +/- steppers
"""
from __future__ import annotations
import math
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSlider,
    QLineEdit, QPushButton, QFrame, QSizePolicy, QToolButton,
    QColorDialog, QScrollArea, QApplication,
)
from PySide6.QtCore  import Qt, Signal, QPoint, QRect, QSize, QTimer
from PySide6.QtGui   import (
    QColor, QPainter, QPen, QBrush, QFont, QFontMetrics, QPainterPath,
    QPixmap, QIcon,
)

# ── Shared palette ─────────────────────────────────────────────────────────────
_BG       = "#1a1a22"
_BORDER   = "#2e2e3e"
_DIM      = "#555"
_TEXT     = "#999"
_ACTIVE   = "#ccc"
_ACCENT   = "#5566cc"
_ACCENT2  = "#8877ee"
_WARN     = "#cc7733"
_OK       = "#44aa66"
_MONO     = "Courier New"


# ─────────────────────────────────────────────────────────────────────────────
#  HRule
# ─────────────────────────────────────────────────────────────────────────────
class HRule(QFrame):
    """
    A one-pixel horizontal divider.

    Usage:
        layout.addWidget(HRule())
        layout.addWidget(HRule(color="#3a3a5a", margin=6))
    """
    def __init__(self, color: str = _BORDER, margin: int = 2, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.HLine)
        self.setFrameShadow(QFrame.Plain)
        self.setFixedHeight(1 + margin * 2)
        self.setContentsMargins(0, margin, 0, margin)
        self.setStyleSheet(f"color:{color};background:{color};border:none;")


# ─────────────────────────────────────────────────────────────────────────────
#  SectionHeader
# ─────────────────────────────────────────────────────────────────────────────
class SectionHeader(QLabel):
    """
    An uppercase, letter-spaced section label in the Courier New monospace style.

    Usage:
        layout.addWidget(SectionHeader("BRUSH SETTINGS"))
        layout.addWidget(SectionHeader("COLOR", dim=True))
    """
    def __init__(self, text: str, dim: bool = False, parent=None):
        super().__init__(text.upper(), parent)
        color = _DIM if dim else "#3a3a6a"
        self.setStyleSheet(
            f"color:{color};"
            f"font-family:'{_MONO}';"
            f"font-size:10px;"
            f"font-weight:bold;"
            f"letter-spacing:2px;"
            f"padding:4px 0 2px 0;"
            f"background:transparent;"
        )


# ─────────────────────────────────────────────────────────────────────────────
#  TagBadge
# ─────────────────────────────────────────────────────────────────────────────
class TagBadge(QLabel):
    """
    A small rounded-pill label for file types, status, flags, etc.

    Usage:
        layout.addWidget(TagBadge("GBR"))
        layout.addWidget(TagBadge("LOCKED", color="#cc3333"))
        layout.addWidget(TagBadge("★ FAV", color="#ccaa00"))
    """
    def __init__(self, text: str, color: str = _ACCENT, parent=None):
        super().__init__(text, parent)
        self._color = color
        self.setAlignment(Qt.AlignCenter)
        self._apply_style()
        # Minimum width so single chars don't look squashed
        fm = QFontMetrics(self.font())
        w  = fm.horizontalAdvance(text) + 14
        self.setMinimumWidth(max(28, w))
        self.setFixedHeight(16)

    def _apply_style(self):
        self.setStyleSheet(
            f"color:{self._color};"
            f"background:transparent;"
            f"border:1px solid {self._color};"
            f"border-radius:7px;"
            f"font-family:'{_MONO}';"
            f"font-size:9px;"
            f"font-weight:bold;"
            f"letter-spacing:1px;"
            f"padding:0 5px;"
        )

    def set_color(self, color: str):
        self._color = color
        self._apply_style()


# ─────────────────────────────────────────────────────────────────────────────
#  LabeledSlider
# ─────────────────────────────────────────────────────────────────────────────
class LabeledSlider(QWidget):
    """
    Horizontal slider with a fixed-width label on the left and
    a live numeric readout on the right.

    Signals:
        value_changed(float)  — emitted on every slider move

    Usage:
        sl = LabeledSlider("Size", 1, 200, 20)
        sl.value_changed.connect(my_handler)

        sl = LabeledSlider("Opacity", 0, 100, 80, fmt=lambda v: f"{v}%")
        sl = LabeledSlider("Angle",   0, 359,  0, fmt=lambda v: f"{v}°")

    set_value(v) — sets slider without emitting value_changed
    value()      — returns current int value
    """
    value_changed = Signal(float)

    def __init__(self, label: str, lo: int, hi: int, default: int,
                 fmt=None, label_width: int = 60, parent=None):
        super().__init__(parent)
        self._fmt = fmt or str
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self._lbl = QLabel(label)
        self._lbl.setFixedWidth(label_width)
        self._lbl.setStyleSheet(
            f"color:{_TEXT};font-family:'{_MONO}';font-size:11px;background:transparent;")
        layout.addWidget(self._lbl)

        self._sl = QSlider(Qt.Horizontal)
        self._sl.setRange(lo, hi)
        self._sl.setValue(default)
        self._sl.setStyleSheet(f"""
            QSlider::groove:horizontal{{
                height:3px;background:#252535;border-radius:1px;
            }}
            QSlider::handle:horizontal{{
                width:13px;height:13px;
                background:#44445a;border:1px solid {_ACCENT};
                border-radius:6px;margin:-5px 0;
            }}
            QSlider::handle:horizontal:hover{{
                background:{_ACCENT};
            }}
            QSlider::sub-page:horizontal{{
                background:{_ACCENT};border-radius:1px;
            }}
        """)
        layout.addWidget(self._sl, 1)

        self._val_lbl = QLabel(self._fmt(default))
        self._val_lbl.setFixedWidth(38)
        self._val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._val_lbl.setStyleSheet(
            f"color:{_ACTIVE};font-family:'{_MONO}';font-size:10px;background:transparent;")
        layout.addWidget(self._val_lbl)

        self._sl.valueChanged.connect(self._on_change)

    def _on_change(self, v: int):
        self._val_lbl.setText(self._fmt(v))
        self.value_changed.emit(float(v))

    def set_value(self, v: float):
        """Set value silently (no signal)."""
        self._sl.blockSignals(True)
        self._sl.setValue(int(round(v)))
        self._val_lbl.setText(self._fmt(int(round(v))))
        self._sl.blockSignals(False)

    def value(self) -> float:
        return float(self._sl.value())

    def set_label(self, text: str):
        self._lbl.setText(text)

    def set_enabled(self, v: bool):
        self._sl.setEnabled(v)
        alpha = "ff" if v else "66"
        self._lbl.setStyleSheet(
            f"color:{_TEXT}{alpha};font-family:'{_MONO}';font-size:11px;background:transparent;")


# ─────────────────────────────────────────────────────────────────────────────
#  ColorSwatch
# ─────────────────────────────────────────────────────────────────────────────
class ColorSwatch(QWidget):
    """
    A clickable colored square that opens QColorDialog on click.
    Supports alpha.

    Signals:
        color_changed(QColor)

    Usage:
        sw = ColorSwatch(QColor(255, 80, 80))
        sw.color_changed.connect(my_handler)
        current = sw.color()
        sw.set_color(QColor("#ff0000"))
    """
    color_changed = Signal(QColor)

    def __init__(self, color: QColor = None, size: int = 24,
                 allow_alpha: bool = False, parent=None):
        super().__init__(parent)
        self._color = color or QColor(255, 255, 255)
        self._allow_alpha = allow_alpha
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to change color")

    def color(self) -> QColor:
        return self._color

    def set_color(self, c: QColor):
        self._color = c
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)

        # Checkerboard background for alpha visibility
        if self._allow_alpha and self._color.alpha() < 255:
            sq = max(3, self.width() // 4)
            for ry in range(0, r.height(), sq):
                for rx in range(0, r.width(), sq):
                    odd = (rx // sq + ry // sq) % 2
                    p.fillRect(
                        QRect(r.left() + rx, r.top() + ry, sq, sq),
                        QColor(180, 180, 180) if odd else QColor(220, 220, 220))

        p.setBrush(QBrush(self._color))
        p.setPen(QPen(QColor(_BORDER), 1))
        p.drawRoundedRect(r, 3, 3)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            opts = QColorDialog.ShowAlphaChannel if self._allow_alpha else QColorDialog.ColorDialogOptions()
            col  = QColorDialog.getColor(self._color, self, "Choose Color",
                                         QColorDialog.ShowAlphaChannel if self._allow_alpha
                                         else QColorDialog.ColorDialogOptions())
            if col.isValid():
                self._color = col
                self.update()
                self.color_changed.emit(col)


# ─────────────────────────────────────────────────────────────────────────────
#  IconButton
# ─────────────────────────────────────────────────────────────────────────────
class IconButton(QToolButton):
    """
    Flat icon-only button with a soft hover glow effect.
    Supports text emoji icons or QIcon.

    Usage:
        btn = IconButton("✕", tooltip="Close", size=22)
        btn = IconButton("★", tooltip="Favorite", size=20, accent="#ffcc00")
        btn.clicked.connect(handler)
        btn.set_active(True)   # highlights the button
    """
    def __init__(self, icon_text: str = "", tooltip: str = "",
                 size: int = 24, accent: str = _ACCENT, parent=None):
        super().__init__(parent)
        self._accent  = accent
        self._active  = False
        self._icon_text = icon_text
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        if icon_text:
            self.setText(icon_text)
        self._apply_style()

    def _apply_style(self):
        bg      = "#2a2a40" if self._active else _BG
        color   = self._accent if self._active else _TEXT
        border  = self._accent if self._active else _BORDER
        sz      = self.width()
        self.setStyleSheet(f"""
            QToolButton{{
                background:{bg};
                color:{color};
                border:1px solid {border};
                border-radius:{sz//3}px;
                font-size:{sz//2 - 2}px;
                padding:0;
            }}
            QToolButton:hover{{
                background:#252545;
                color:{self._accent};
                border-color:{self._accent};
            }}
            QToolButton:pressed{{
                background:#1a1a35;
            }}
        """)

    def set_active(self, v: bool):
        self._active = v
        self._apply_style()

    def is_active(self) -> bool:
        return self._active

    def toggle_active(self) -> bool:
        self.set_active(not self._active)
        return self._active


# ─────────────────────────────────────────────────────────────────────────────
#  SearchBar
# ─────────────────────────────────────────────────────────────────────────────
class SearchBar(QWidget):
    """
    Styled search input with a magnifier prefix and a live-clear button.
    Emits search_changed(str) 200ms after the last keystroke (debounced).
    Also emits immediately on Enter/Return.

    Usage:
        bar = SearchBar(placeholder="Search brushes…")
        bar.search_changed.connect(my_filter_fn)
        bar.clear()
    """
    search_changed = Signal(str)

    def __init__(self, placeholder: str = "Search…",
                 debounce_ms: int = 200, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        self._edit.setClearButtonEnabled(True)
        self._edit.setStyleSheet(f"""
            QLineEdit{{
                background:#111118;
                color:{_ACTIVE};
                border:1px solid {_BORDER};
                border-radius:3px;
                padding:3px 6px 3px 24px;
                font-family:'{_MONO}';
                font-size:11px;
            }}
            QLineEdit:focus{{
                border-color:{_ACCENT};
            }}
        """)
        layout.addWidget(self._edit)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._emit)
        self._edit.textChanged.connect(lambda _: self._timer.start(debounce_ms))
        self._edit.returnPressed.connect(self._emit_now)

    def _emit(self):
        self.search_changed.emit(self._edit.text())

    def _emit_now(self):
        self._timer.stop()
        self._emit()

    def text(self) -> str:
        return self._edit.text()

    def clear(self):
        self._edit.clear()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setPen(QColor(_DIM))
        p.setFont(QFont(_MONO, 10))
        p.drawText(QRect(4, 0, 18, self.height()), Qt.AlignCenter, "🔍")
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
#  StatusBar
# ─────────────────────────────────────────────────────────────────────────────
class StatusBar(QLabel):
    """
    One-line dim status text at the bottom of a panel.

    Usage:
        sb = StatusBar()
        sb.set_status("24 brushes · 3 packs")
        sb.set_status("Error loading brush", level="warn")
        sb.set_status("Imported 12 brushes", level="ok")
    """
    COLORS = {"normal": _DIM, "warn": _WARN, "ok": _OK, "error": "#cc4444"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self._base_style = (
            f"font-family:'{_MONO}';"
            f"font-size:10px;"
            f"background:transparent;"
            f"padding:0 2px;"
        )
        self.set_status("")

    def set_status(self, text: str, level: str = "normal"):
        color = self.COLORS.get(level, _DIM)
        self.setText(text)
        self.setStyleSheet(self._base_style + f"color:{color};")


# ─────────────────────────────────────────────────────────────────────────────
#  ToolRow
# ─────────────────────────────────────────────────────────────────────────────
class ToolRow(QWidget):
    """
    A horizontal row of small flat icon/text buttons.
    Keeps all buttons the same size and evenly spaced.

    Usage:
        row = ToolRow(buttons=[
            ("↔", "Flip Horizontal", handler_fh),
            ("↕", "Flip Vertical",   handler_fv),
            ("⟲", "Reset Transform", handler_reset),
        ], btn_size=28)
        layout.addWidget(row)
    """
    def __init__(self, buttons: list[tuple[str, str, object]] = None,
                 btn_size: int = 26, spacing: int = 3, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)
        self._buttons: list[IconButton] = []
        if buttons:
            for icon_text, tooltip, handler in buttons:
                btn = IconButton(icon_text, tooltip=tooltip, size=btn_size)
                if handler:
                    btn.clicked.connect(handler)
                layout.addWidget(btn)
                self._buttons.append(btn)
        layout.addStretch()

    def add_button(self, icon_text: str, tooltip: str = "",
                   handler=None, size: int = 26) -> IconButton:
        btn = IconButton(icon_text, tooltip=tooltip, size=size)
        if handler:
            btn.clicked.connect(handler)
        self.layout().insertWidget(self.layout().count() - 1, btn)
        self._buttons.append(btn)
        return btn

    def buttons(self) -> list[IconButton]:
        return list(self._buttons)


# ─────────────────────────────────────────────────────────────────────────────
#  NumericInput
# ─────────────────────────────────────────────────────────────────────────────
class NumericInput(QWidget):
    """
    A validated integer/float input with optional +/- stepper buttons.

    Signals:
        value_changed(float)

    Usage:
        ni = NumericInput(value=48, lo=6, hi=512, label="Size", unit="px")
        ni.value_changed.connect(handler)
        ni.set_value(72)
        v = ni.value()

    Keyboard:
        Up/Down arrows increment/decrement by step.
        Shift+Up/Down uses step×10.
    """
    value_changed = Signal(float)

    def __init__(self, value: float = 0, lo: float = 0, hi: float = 9999,
                 step: float = 1, label: str = "", unit: str = "",
                 decimals: int = 0, width: int = 64, parent=None):
        super().__init__(parent)
        self._lo       = lo
        self._hi       = hi
        self._step     = step
        self._decimals = decimals
        self._value    = float(value)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        if label:
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color:{_TEXT};font-family:'{_MONO}';font-size:11px;background:transparent;")
            layout.addWidget(lbl)

        self._minus = self._small_btn("−")
        self._minus.clicked.connect(lambda: self._step_by(-self._step))
        layout.addWidget(self._minus)

        self._edit = QLineEdit(self._fmt(value))
        self._edit.setFixedWidth(width)
        self._edit.setAlignment(Qt.AlignCenter)
        self._edit.setStyleSheet(f"""
            QLineEdit{{
                background:#111118;color:{_ACTIVE};
                border:1px solid {_BORDER};border-radius:2px;
                font-family:'{_MONO}';font-size:11px;padding:2px 4px;
            }}
            QLineEdit:focus{{border-color:{_ACCENT};}}
        """)
        self._edit.editingFinished.connect(self._on_edited)
        self._edit.installEventFilter(self)
        layout.addWidget(self._edit)

        self._plus = self._small_btn("+")
        self._plus.clicked.connect(lambda: self._step_by(self._step))
        layout.addWidget(self._plus)

        if unit:
            ul = QLabel(unit)
            ul.setStyleSheet(
                f"color:{_DIM};font-family:'{_MONO}';font-size:10px;background:transparent;")
            layout.addWidget(ul)

    def _small_btn(self, text: str) -> QToolButton:
        btn = QToolButton()
        btn.setText(text)
        btn.setFixedSize(18, 22)
        btn.setStyleSheet(f"""
            QToolButton{{
                background:#1e1e2a;color:{_TEXT};border:1px solid {_BORDER};
                border-radius:2px;font-size:13px;padding:0;
            }}
            QToolButton:hover{{background:#2a2a40;color:{_ACTIVE};}}
        """)
        return btn

    def _fmt(self, v: float) -> str:
        if self._decimals == 0:
            return str(int(round(v)))
        return f"{v:.{self._decimals}f}"

    def _clamp(self, v: float) -> float:
        return max(self._lo, min(self._hi, v))

    def _step_by(self, delta: float):
        self._value = self._clamp(self._value + delta)
        self._edit.setText(self._fmt(self._value))
        self.value_changed.emit(self._value)

    def _on_edited(self):
        try:
            v = float(self._edit.text().replace(",", "."))
            self._value = self._clamp(v)
            self._edit.setText(self._fmt(self._value))
            self.value_changed.emit(self._value)
        except ValueError:
            self._edit.setText(self._fmt(self._value))

    def eventFilter(self, obj, event):
        if obj is self._edit and event.type() == event.Type.KeyPress:
            from PySide6.QtCore import QEvent
            from PySide6.QtGui  import QKeyEvent
            ke: QKeyEvent = event  # type: ignore
            mult = 10 if (ke.modifiers() & Qt.ShiftModifier) else 1
            if ke.key() == Qt.Key_Up:
                self._step_by(self._step * mult); return True
            if ke.key() == Qt.Key_Down:
                self._step_by(-self._step * mult); return True
        return super().eventFilter(obj, event)

    def set_value(self, v: float):
        self._value = self._clamp(float(v))
        self._edit.blockSignals(True)
        self._edit.setText(self._fmt(self._value))
        self._edit.blockSignals(False)

    def value(self) -> float:
        return self._value


# ─────────────────────────────────────────────────────────────────────────────
#  CollapsibleBox
# ─────────────────────────────────────────────────────────────────────────────
class CollapsibleBox(QWidget):
    """
    Expandable/collapsible section with an animated arrow toggle.

    Usage:
        box = CollapsibleBox("BRUSH SETTINGS")
        inner = QVBoxLayout()
        inner.addWidget(my_slider)
        box.set_content_layout(inner)
        layout.addWidget(box)
    """
    def __init__(self, title: str, collapsed: bool = False, parent=None):
        super().__init__(parent)
        self._collapsed = collapsed

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header row
        header = QWidget()
        header.setFixedHeight(26)
        header.setCursor(Qt.PointingHandCursor)
        header.setStyleSheet(f"""
            QWidget{{
                background:#1e1e2c;
                border-bottom:1px solid {_BORDER};
            }}
            QWidget:hover{{background:#222234;}}
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8, 0, 6, 0)

        self._arrow = QLabel("▶" if collapsed else "▼")
        self._arrow.setStyleSheet(
            f"color:{_ACCENT};font-size:9px;background:transparent;")
        self._arrow.setFixedWidth(14)
        hl.addWidget(self._arrow)

        self._title_lbl = QLabel(title.upper())
        self._title_lbl.setStyleSheet(
            f"color:#3a3a6a;font-family:'{_MONO}';font-size:10px;"
            f"font-weight:bold;letter-spacing:2px;background:transparent;")
        hl.addWidget(self._title_lbl, 1)

        root.addWidget(header)
        header.mousePressEvent = lambda _: self.toggle()

        # ── Content
        self._content = QWidget()
        self._content.setVisible(not collapsed)
        self._content.setStyleSheet("background:#1a1a22;")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 6, 8, 6)
        self._content_layout.setSpacing(5)
        root.addWidget(self._content)

    def set_content_layout(self, layout):
        """Replace the inner content layout."""
        # Clear existing
        while self._content_layout.count():
            self._content_layout.takeAt(0)
        # Transfer items from provided layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                self._content_layout.addWidget(item.widget())
            elif item.layout():
                self._content_layout.addLayout(item.layout())
            else:
                self._content_layout.addItem(item)

    def add_widget(self, w: QWidget):
        self._content_layout.addWidget(w)

    def add_layout(self, lay):
        self._content_layout.addLayout(lay)

    def toggle(self):
        self._collapsed = not self._collapsed
        self._content.setVisible(not self._collapsed)
        self._arrow.setText("▶" if self._collapsed else "▼")

    def set_collapsed(self, v: bool):
        if v != self._collapsed:
            self.toggle()

    def is_collapsed(self) -> bool:
        return self._collapsed