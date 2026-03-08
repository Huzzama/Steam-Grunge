"""
toolBar.py  —  Vertical left-side tool selector for Steam Grunge Editor.

Tools (in order):
  Move        — select + drag layers / group children
  Brush       — paint on active paint layer
  Eraser      — erase on active paint layer (writes transparency)
  Rectangle   — draw a new rectangle fill layer
  Ellipse     — draw a new ellipse fill layer
  ColorPicker — sample canvas pixel → update brush color
  Hand        — pan the canvas by dragging
  Zoom        — click to zoom in (Shift/Right-click = zoom out)

Architecture:
  • ToolMode enum — single source of truth for all tool identifiers
  • ToolBar widget — vertical strip of ToolButton widgets
  • Signals: tool_changed(ToolMode) emitted on every tool switch
  • The canvas consumes this via set_tool(mode) and changes its mouse
    behaviour purely based on the current ToolMode — no scattered flags.

Integration (in mainWindow.py):
    self.tool_bar = ToolBar()
    self.tool_bar.tool_changed.connect(self.preview_canvas.set_tool)
    # To read active tool from outside:
    mode = self.tool_bar.active_tool()
    # To push a tool programmatically (e.g. brush toggle button):
    self.tool_bar.set_tool(ToolMode.BRUSH)
"""
from __future__ import annotations
from enum import Enum, auto

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QToolButton, QLabel, QSizePolicy,
    QButtonGroup,
)
from PySide6.QtCore  import Qt, Signal, QSize
from PySide6.QtGui   import QFont, QColor, QPainter, QPen, QBrush


# ─────────────────────────────────────────────────────────────────────────────
#  Tool mode enum
# ─────────────────────────────────────────────────────────────────────────────
class ToolMode(Enum):
    MOVE         = auto()
    BRUSH        = auto()
    ERASER       = auto()
    RECTANGLE    = auto()
    ELLIPSE      = auto()
    COLOR_PICKER = auto()
    HAND         = auto()
    ZOOM         = auto()


# ── Per-tool metadata (icon, label, tooltip, keyboard shortcut hint) ──────────
_TOOL_META: dict[ToolMode, dict] = {
    ToolMode.MOVE:         dict(icon="✥",  label="Move",   tip="Move Tool  [V]\nDrag layers. Group moves all children."),
    ToolMode.BRUSH:        dict(icon="✏",  label="Brush",  tip="Brush Tool  [B]\nPaint on the active paint layer."),
    ToolMode.ERASER:       dict(icon="⌫",  label="Eraser", tip="Eraser Tool  [E]\nErase pixels (writes transparency)."),
    ToolMode.RECTANGLE:    dict(icon="▭",  label="Rect",   tip="Rectangle Tool  [R]\nDraw a new rectangle shape layer."),
    ToolMode.ELLIPSE:      dict(icon="◯",  label="Ellipse",tip="Ellipse Tool  [O]\nDraw a new ellipse shape layer."),
    ToolMode.COLOR_PICKER: dict(icon="⊕",  label="Pick",   tip="Color Picker  [I]\nClick canvas to sample color."),
    ToolMode.HAND:         dict(icon="✋",  label="Hand",   tip="Hand Tool  [H]\nPan the canvas by dragging."),
    ToolMode.ZOOM:         dict(icon="⊕",  label="Zoom",   tip="Zoom Tool  [Z]\nClick = zoom in.  Shift/Right = zoom out."),
}

# Keyboard shortcut → ToolMode (handled in ToolBar.keyPressEvent forwarded
# from MainWindow; these are advisory, the canvas also handles them)
KEY_SHORTCUTS: dict[str, ToolMode] = {
    "v": ToolMode.MOVE,
    "b": ToolMode.BRUSH,
    "e": ToolMode.ERASER,
    "r": ToolMode.RECTANGLE,
    "o": ToolMode.ELLIPSE,
    "i": ToolMode.COLOR_PICKER,
    "h": ToolMode.HAND,
    "z": ToolMode.ZOOM,
}

_ORDERED = [
    ToolMode.MOVE,
    ToolMode.BRUSH,
    ToolMode.ERASER,
    ToolMode.RECTANGLE,
    ToolMode.ELLIPSE,
    ToolMode.COLOR_PICKER,
    ToolMode.HAND,
    ToolMode.ZOOM,
]

_BG      = "#141420"
_BORDER  = "#252535"
_ACTIVE  = "#3a3a6a"
_ACCENT  = "#5566cc"
_TEXT    = "#666"
_ACTIVE_TEXT = "#ddd"


# ─────────────────────────────────────────────────────────────────────────────
#  Individual tool button
# ─────────────────────────────────────────────────────────────────────────────
class _ToolButton(QToolButton):
    def __init__(self, mode: ToolMode, parent=None):
        super().__init__(parent)
        self.mode = mode
        meta = _TOOL_META[mode]
        self.setText(meta["icon"])
        self.setToolTip(meta["tip"])
        self.setCheckable(True)
        self.setFixedSize(44, 44)
        self.setFocusPolicy(Qt.NoFocus)
        self._apply_style(False)

    def _apply_style(self, active: bool):
        if active:
            self.setStyleSheet(f"""
                QToolButton {{
                    background: {_ACTIVE};
                    color: {_ACTIVE_TEXT};
                    border: 1px solid {_ACCENT};
                    border-radius: 6px;
                    font-size: 18px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QToolButton {{
                    background: transparent;
                    color: {_TEXT};
                    border: 1px solid transparent;
                    border-radius: 6px;
                    font-size: 18px;
                }}
                QToolButton:hover {{
                    background: #1e1e30;
                    color: #aaa;
                    border-color: {_BORDER};
                }}
            """)

    def setChecked(self, v: bool):
        super().setChecked(v)
        self._apply_style(v)


# ─────────────────────────────────────────────────────────────────────────────
#  ToolBar widget
# ─────────────────────────────────────────────────────────────────────────────
class ToolBar(QWidget):
    """
    Vertical tool selector strip.

    Signals:
        tool_changed(ToolMode)  — emitted whenever the active tool changes

    API:
        active_tool() -> ToolMode
        set_tool(mode: ToolMode) — programmatically select a tool
    """
    tool_changed = Signal(object)  # ToolMode

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(52)
        self.setStyleSheet(f"""
            QWidget {{
                background: {_BG};
                border-right: 1px solid {_BORDER};
            }}
        """)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignTop)

        # Header dot
        dot = QLabel("✦")
        dot.setAlignment(Qt.AlignCenter)
        dot.setFixedHeight(20)
        dot.setStyleSheet(
            "color: #2a2a4a; font-size: 12px; background: transparent;"
            "border: none;")
        layout.addWidget(dot)
        layout.addSpacing(6)

        self._buttons: dict[ToolMode, _ToolButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        prev_group: list[ToolMode] = []

        for mode in _ORDERED:
            # Separator between logical groups
            if mode == ToolMode.RECTANGLE and prev_group:
                layout.addWidget(self._sep())
            elif mode == ToolMode.COLOR_PICKER and prev_group:
                layout.addWidget(self._sep())
            elif mode == ToolMode.HAND and prev_group:
                layout.addWidget(self._sep())

            btn = _ToolButton(mode, self)
            btn.clicked.connect(lambda checked, m=mode: self._on_btn_clicked(m))
            self._group.addButton(btn)
            self._buttons[mode] = btn
            layout.addWidget(btn)
            prev_group.append(mode)

        layout.addStretch()

        # Default tool = Move
        self._active: ToolMode = ToolMode.MOVE
        self._buttons[ToolMode.MOVE].setChecked(True)

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _sep() -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {_BORDER}; border: none;")
        return line

    # ── API ───────────────────────────────────────────────────────────────────
    def active_tool(self) -> ToolMode:
        return self._active

    def set_tool(self, mode: ToolMode):
        if mode == self._active:
            return
        self._active = mode
        for m, btn in self._buttons.items():
            btn.blockSignals(True)
            btn.setChecked(m == mode)
            btn.blockSignals(False)
        self.tool_changed.emit(mode)

    # ── Slots ─────────────────────────────────────────────────────────────────
    def _on_btn_clicked(self, mode: ToolMode):
        if mode != self._active:
            self._active = mode
            # Update visual state of all buttons
            for m, btn in self._buttons.items():
                btn.blockSignals(True)
                btn.setChecked(m == mode)
                btn.blockSignals(False)
            self.tool_changed.emit(mode)