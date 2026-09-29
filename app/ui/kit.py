"""
Small widget kit shared by every panel and dialog — so layouts line up and
nothing carries its own stylesheet.

    from app.ui.kit import (vbox, hbox, grid, label, Button, IconButton, Section,
                            SliderRow, ColorSwatch, Divider, ChipRow, Toast)
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from PySide6.QtCore import QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QSlider, QSpinBox, QVBoxLayout, QWidget)

from app.ui import icons
from app.ui.theme import C, CONTROL_H, R, SP, repolish


# ── layouts ───────────────────────────────────────────────────────────────────

def vbox(parent=None, margins=(0, 0, 0, 0), spacing: int = SP["sm"]) -> QVBoxLayout:
    l = QVBoxLayout(parent) if parent is not None else QVBoxLayout()
    l.setContentsMargins(*margins)
    l.setSpacing(spacing)
    return l


def hbox(parent=None, margins=(0, 0, 0, 0), spacing: int = SP["sm"]) -> QHBoxLayout:
    l = QHBoxLayout(parent) if parent is not None else QHBoxLayout()
    l.setContentsMargins(*margins)
    l.setSpacing(spacing)
    return l


def grid(parent=None, margins=(0, 0, 0, 0), h: int = SP["sm"], v: int = SP["sm"]) -> QGridLayout:
    l = QGridLayout(parent) if parent is not None else QGridLayout()
    l.setContentsMargins(*margins)
    l.setHorizontalSpacing(h)
    l.setVerticalSpacing(v)
    return l


# ── text ──────────────────────────────────────────────────────────────────────

def label(text: str = "", role: str = "body", tone: Optional[str] = None, *,
          align=None, wrap: bool = False, elide: bool = False) -> QLabel:
    """role: title · section · eyebrow · body · dim · muted · value · mono"""
    l = ElidedLabel(text) if elide else QLabel(text)
    l.setProperty("role", role)
    if tone:
        l.setProperty("tone", tone)
    if align is not None:
        l.setAlignment(align)
    l.setWordWrap(wrap)
    return l


class ElidedLabel(QLabel):
    """Single-line label that elides with … instead of overflowing its column."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(24)

    def setText(self, t: str):
        self._full = t
        super().setText(t)
        self._elide()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, Qt.TextElideMode.ElideRight, max(10, self.width())))
        self.setToolTip(self._full if fm.horizontalAdvance(self._full) > self.width() else "")


def set_tone(widget: QWidget, tone: Optional[str]) -> None:
    widget.setProperty("tone", tone or "")
    repolish(widget)


class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "divider")
        self.setFixedHeight(1)


# ── buttons ───────────────────────────────────────────────────────────────────

_ICON_TONE = {"primary": C["accent"], "success": C["green"], "danger": C["red"], "ghost": C["text_dim"],
              "link": C["accent"], "default": C["text_dim"], "icon": C["text_2"], "tool": C["text_2"],
              "chip": C["text_dim"], "template": C["text_dim"]}


class Button(QPushButton):
    """variant: default · primary · success · danger · ghost · link · chip · template"""

    def __init__(self, text: str = "", variant: str = "default", icon: Optional[str] = None,
                 on_click: Optional[Callable] = None, parent=None, icon_size: int = 15, tooltip: str = ""):
        super().__init__(text, parent)
        self._variant, self._icon_name, self._icon_size = variant, icon, icon_size
        self.setProperty("variant", variant)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if tooltip:
            self.setToolTip(tooltip)
        if icon:
            self.set_icon(icon)
        if on_click:
            self.clicked.connect(on_click)

    def set_icon(self, name: str, color: Optional[str] = None):
        self._icon_name = name
        self.setIcon(icons.icon(name, color or _ICON_TONE.get(self._variant, C["text_dim"]), self._icon_size))
        self.setIconSize(QSize(self._icon_size, self._icon_size))

    def set_active(self, active: bool):
        if (self.property("active") == "true") != active:
            self.setProperty("active", "true" if active else "false")
            if self._icon_name:
                self.set_icon(self._icon_name, C["accent"] if active else None)
            repolish(self)

    def set_loading(self, loading: bool, text: Optional[str] = None):
        self.setEnabled(not loading)
        if loading:
            self._saved = (self.text(), self._icon_name)
            if text is not None:
                self.setText(text)
            self.set_icon("loader-circle")
        elif getattr(self, "_saved", None):
            t, ic = self._saved
            self.setText(t)
            if ic:
                self.set_icon(ic)
            else:
                self.setIcon(icons.QIcon())
            self._saved = None


class IconButton(QPushButton):
    """Square icon-only button. variant 'icon' (28 px) or 'tool' (34 px, toggleable)."""

    def __init__(self, icon: str, tooltip: str = "", size: int = 16, color: Optional[str] = None,
                 on_click: Optional[Callable] = None, checkable: bool = False, variant: str = "icon", parent=None):
        super().__init__(parent)
        self._icon_name, self._size, self._color = icon, size, color
        self.setProperty("variant", variant)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setCheckable(checkable)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.set_icon(icon, color)
        if checkable:
            self.toggled.connect(lambda on: self.set_icon(self._icon_name, C["accent"] if on else self._color))
        if on_click:
            self.clicked.connect(on_click)

    def set_icon(self, name: str, color: Optional[str] = None):
        self._icon_name = name
        self.setIcon(icons.icon(name, color or C["text_2"], self._size))
        self.setIconSize(QSize(self._size, self._size))

    def setChecked(self, on: bool):  # noqa: N802 — Qt name
        super().setChecked(on)
        self.set_icon(self._icon_name, C["accent"] if on else self._color)


class VDivider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "vdivider")
        self.setFixedWidth(1)


class StatusDot(QWidget):
    """8 px painted circle; tone: green · red · gold · accent · muted."""

    def __init__(self, tone: str = "muted", size: int = 8, parent=None):
        super().__init__(parent)
        self._tone = tone
        self._size = size
        self.setFixedSize(size, size)

    def set_tone(self, tone: str):
        self._tone = tone
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.get(self._tone, C["text_muted"])))
        p.drawEllipse(0, 0, self._size, self._size)
        p.end()


class StatusLine(QWidget):
    """[icon] message — icon + tone follow the state: ok · error · warning · info · busy."""

    _MAP = {"ok": ("circle-check", "green"), "error": ("circle-x", "red"), "warning": ("triangle-alert", "gold"),
            "info": ("info", "accent"), "busy": ("loader-circle", "accent"), "idle": ("minus", "muted")}

    def __init__(self, text: str = "", state: str = "idle", parent=None):
        super().__init__(parent)
        lay = hbox(self, spacing=SP["sm"])
        self._icon = QLabel()
        self._icon.setFixedSize(16, 16)
        lay.addWidget(self._icon)
        self._text = label(text, "dim", wrap=True)
        lay.addWidget(self._text, 1)
        self.set(text, state)

    def set(self, text: str, state: str = "idle"):
        name, tone = self._MAP.get(state, self._MAP["idle"])
        self._icon.setPixmap(icons.pixmap(name, C.get(tone, C["text_dim"]), 16))
        self._text.setText(text)
        set_tone(self._text, tone if state != "idle" else None)


def form_row(g: QGridLayout, row: int, title: str, field: QWidget, trailing: Optional[QWidget] = None) -> None:
    """Label column (~110 px) · field (stretch) · optional trailing widget."""
    l = label(title, "dim")
    l.setMinimumWidth(110)
    g.addWidget(l, row, 0, Qt.AlignmentFlag.AlignVCenter)
    if trailing is None:
        g.addWidget(field, row, 1, 1, 2)
    else:
        g.addWidget(field, row, 1)
        g.addWidget(trailing, row, 2)
    g.setColumnStretch(1, 1)


class ChipRow(QWidget):
    """Single-select row of chips. changed(key)."""
    changed = Signal(str)

    def __init__(self, options: Iterable[tuple[str, str]], current: Optional[str] = None, parent=None):
        super().__init__(parent)
        lay = hbox(self, spacing=SP["xs"])
        self._btns: dict[str, Button] = {}
        self._current = None
        for key, text in options:
            b = Button(text, "chip", on_click=lambda _=False, k=key: self.set_current(k))
            self._btns[key] = b
            lay.addWidget(b)
        lay.addStretch()
        if current is not None:
            self.set_current(current, emit=False)

    def current(self) -> Optional[str]:
        return self._current

    def set_current(self, key: Optional[str], emit: bool = True):
        if key == self._current:
            return
        self._current = key
        for k, b in self._btns.items():
            b.set_active(k == key)
        if emit and key is not None:
            self.changed.emit(key)


# ── sections ──────────────────────────────────────────────────────────────────

class Section(QFrame):
    """
    Collapsible panel section with an uppercase header row:
        s = Section("TEMPLATES", collapsible=True, trailing=Button(...))
        s.body.addWidget(...)
    """

    toggled = Signal(bool)

    def __init__(self, title: str, collapsible: bool = True, expanded: bool = True,
                 trailing: Optional[QWidget] = None, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "card")
        outer = vbox(self, (0, 0, 0, 0), 0)

        self._header = QWidget()
        self._header.setFixedHeight(30)
        self._header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if collapsible else Qt.CursorShape.ArrowCursor))
        hl = hbox(self._header, (SP["md"], 0, SP["sm"], 0), SP["sm"])
        self._chev = QLabel()
        self._chev.setFixedSize(12, 12)
        hl.addWidget(self._chev)
        self._title = label(title.upper(), "section")
        hl.addWidget(self._title, 1)
        if trailing is not None:
            hl.addWidget(trailing)
        outer.addWidget(self._header)

        self._body_w = QWidget()
        self.body = vbox(self._body_w, (SP["md"], SP["xs"], SP["md"], SP["md"]), SP["sm"])
        outer.addWidget(self._body_w)

        self._collapsible = collapsible
        self._expanded = True
        self._chev.setVisible(collapsible)
        if collapsible:
            self._header.mouseReleaseEvent = lambda e: self.set_expanded(not self._expanded)
        self.set_expanded(expanded)

    def set_title(self, text: str):
        self._title.setText(text.upper())

    def set_expanded(self, expanded: bool):
        self._expanded = expanded
        self._body_w.setVisible(expanded)
        self._chev.setPixmap(icons.pixmap("chevron-down" if expanded else "chevron-right", C["text_dim"], 12))
        self.toggled.emit(expanded)

    def is_expanded(self) -> bool:
        return self._expanded


class SubHeader(QWidget):
    """Small eyebrow-style label separating groups inside a Section."""

    def __init__(self, text: str, trailing: Optional[QWidget] = None, parent=None):
        super().__init__(parent)
        lay = hbox(self, (0, SP["xs"], 0, 0), SP["sm"])
        self.title = label(text.upper(), "eyebrow")
        lay.addWidget(self.title)
        line = Divider()
        lay.addWidget(line, 1)
        if trailing is not None:
            lay.addWidget(trailing)


# ── controls ──────────────────────────────────────────────────────────────────

class SliderRow(QWidget):
    """
    [label] ────────●──── [value] [reset]   — one fixed-height row, never overlaps.
        r = SliderRow("Grain", 0, 100, 20, suffix="%")
        r.valueChanged.connect(fn)   r.value()   r.set_value(v, emit=False)
    """
    valueChanged = Signal(int)

    def __init__(self, title: str, lo: int, hi: int, value: int, default: Optional[int] = None,
                 suffix: str = "", parent=None):
        super().__init__(parent)
        self._default = value if default is None else default
        self._suffix = suffix
        self.setFixedHeight(20 + 20)
        col = vbox(self, (0, 0, 0, 0), 0)
        top = hbox(spacing=SP["sm"])
        self.title = label(title, "dim")
        top.addWidget(self.title, 1)
        self.value_lbl = label("", "value")
        self.value_lbl.setMinimumWidth(36)
        self.value_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.value_lbl)
        self.reset_btn = IconButton("rotate-ccw", "Reset", 12, on_click=self.reset, variant="mini")
        top.addWidget(self.reset_btn)
        col.addLayout(top)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._on_change)
        col.addWidget(self.slider)
        self._on_change(value)

    def _on_change(self, v: int):
        self.value_lbl.setText(f"{v}{self._suffix}")
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, v: int, emit: bool = True):
        if not emit:
            self.slider.blockSignals(True)
        self.slider.setValue(v)
        if not emit:
            self.slider.blockSignals(False)
            self.value_lbl.setText(f"{v}{self._suffix}")

    def reset(self):
        self.slider.setValue(self._default)

    def set_default(self, v: int):
        self._default = v


class ColorSwatch(QPushButton):
    """Colour preview button; clicked opens a QColorDialog. color_changed(hex)."""
    color_changed = Signal(str)

    def __init__(self, color: str = "#000000", tooltip: str = "Pick colour", size: int = CONTROL_H, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(size + 12, size)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(tooltip)
        self.clicked.connect(self._pick)

    def color(self) -> str:
        return self._color

    def set_color(self, hexv: str, emit: bool = False):
        self._color = hexv
        self.update()
        if emit:
            self.color_changed.emit(hexv)

    def _pick(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(self._color), self.window(), self.toolTip(),
                                  QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if c.isValid():
            self.set_color(c.name(QColor.NameFormat.HexArgb if c.alpha() < 255 else QColor.NameFormat.HexRgb), emit=True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        # checker for alpha
        p.fillRect(r, QColor(C["surface"]))
        p.setBrush(QColor(self._color))
        p.setPen(QColor(C["border_strong"]))
        p.drawRoundedRect(r, R["sm"], R["sm"])
        p.end()


class SpinRow(QWidget):
    """[label] [spinbox] — compact numeric field."""

    def __init__(self, title: str, lo: int, hi: int, value: int, suffix: str = "", parent=None):
        super().__init__(parent)
        lay = hbox(self, spacing=SP["sm"])
        lay.addWidget(label(title, "dim"))
        self.spin = QSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setValue(value)
        self.spin.setSuffix(suffix)
        self.spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.spin, 1)


class EmptyState(QWidget):
    """Centred icon + title + subtitle for empty lists / results."""

    def __init__(self, icon: str, title: str, subtitle: str = "", parent=None, compact: bool = False):
        super().__init__(parent)
        pad = SP["sm"] if compact else SP["xl"]
        lay = vbox(self, (SP["lg"], pad, SP["lg"], pad), SP["xs"] if compact else SP["sm"])
        lay.addStretch()
        self._icon_size = 20 if compact else 28
        self._ic = ic = QLabel()
        ic.setPixmap(icons.pixmap(icon, C["text_muted"], self._icon_size))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        self.title = label(title, "dim", align=Qt.AlignmentFlag.AlignCenter, wrap=True)
        lay.addWidget(self.title)
        self.subtitle = label(subtitle, "muted", align=Qt.AlignmentFlag.AlignCenter, wrap=True)
        self.subtitle.setVisible(bool(subtitle))
        lay.addWidget(self.subtitle)
        lay.addStretch()

    def set_icon(self, name: str):
        self._ic.setPixmap(icons.pixmap(name, C["text_muted"], self._icon_size))

    def set_text(self, title: str, subtitle: str = ""):
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))


# ── toasts ────────────────────────────────────────────────────────────────────

class Toast(QFrame):
    def __init__(self, message: str, tone: str, parent):
        super().__init__(parent)
        color = {"success": C["green"], "error": C["red"], "warning": C["gold"], "info": C["accent"]}[tone]
        icon_name = {"success": "circle-check", "error": "circle-x", "warning": "triangle-alert", "info": "info"}[tone]
        self.setProperty("surface", "card")
        lay = hbox(self, (SP["md"], SP["sm"], SP["lg"], SP["sm"]), SP["sm"])
        ic = QLabel(); ic.setPixmap(icons.pixmap(icon_name, color, 16))
        lay.addWidget(ic)
        lbl = label(message, "body", wrap=len(message) > 60)
        lbl.setMaximumWidth(440)
        lay.addWidget(lbl)
        self.adjustSize()


class ToastHost:
    """host = ToastHost(main_window); host.show("Saved", "success")"""

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._toasts: list[Toast] = []

    def show(self, message: str, tone: str = "info", duration_ms: int = 3200):
        t = Toast(message, tone, self._parent)
        self._toasts.append(t)
        self._place()
        t.show()
        t.raise_()
        eff = QGraphicsOpacityEffect(t); t.setGraphicsEffect(eff)
        a = QPropertyAnimation(eff, b"opacity", t); a.setStartValue(0.0); a.setEndValue(1.0); a.setDuration(160); a.start()
        QTimer.singleShot(duration_ms, lambda: self._dismiss(t))

    def _dismiss(self, t: Toast):
        if t not in self._toasts:
            return
        self._toasts.remove(t)
        t.deleteLater()
        self._place()

    def _place(self):
        pw, ph = self._parent.width(), self._parent.height()
        y = ph - 40
        for t in reversed(self._toasts):
            t.adjustSize()
            y -= t.height()
            t.move(pw - t.width() - SP["xl"], y)
            y -= SP["sm"]

    def relayout(self):
        self._place()
