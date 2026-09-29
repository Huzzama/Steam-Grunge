from __future__ import annotations
from enum import Enum, auto

from PySide6.QtWidgets import QFrame, QSizePolicy, QButtonGroup
from PySide6.QtCore  import Qt, Signal
from PySide6.QtGui   import QColor, QPainter

from app.ui.kit   import IconButton, Divider, vbox
from app.ui.theme import C, SP


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


# ── Per-tool metadata (Lucide icon, label, tooltip with keyboard shortcut hint) ─
_TOOL_META: dict[ToolMode, dict] = {
    ToolMode.MOVE:         dict(icon="move",       label="Move",   tip="Move Tool  [V]\nDrag layers. Group moves all children."),
    ToolMode.BRUSH:        dict(icon="paintbrush", label="Brush",  tip="Brush Tool  [B]\nPaint on the active paint layer."),
    ToolMode.ERASER:       dict(icon="eraser",     label="Eraser", tip="Eraser Tool  [E]\nErase pixels (writes transparency)."),
    ToolMode.RECTANGLE:    dict(icon="square",     label="Rect",   tip="Rectangle Tool  [R]\nDraw a new rectangle shape layer."),
    ToolMode.ELLIPSE:      dict(icon="circle-dot", label="Ellipse",tip="Ellipse Tool  [O]\nDraw a new ellipse shape layer."),
    ToolMode.COLOR_PICKER: dict(icon="pipette",    label="Pick",   tip="Color Picker  [I]\nClick canvas to sample color."),
    ToolMode.HAND:         dict(icon="maximize",   label="Hand",   tip="Hand Tool  [H]\nPan the canvas by dragging."),
    ToolMode.ZOOM:         dict(icon="zoom-in",    label="Zoom",   tip="Zoom Tool  [Z]\nClick = zoom in.  Shift/Right = zoom out."),
}

# Keyboard shortcut → ToolMode (handled in ToolBar.keyPressEvent forwarded
# from MainWindow; these are advisory, the canvas also handles them)
KEY_SHORTCUTS: dict[str, ToolMode] = {
    "v": ToolMode.MOVE,
    # "b" / "e" (brush / eraser) removed — the brush engine no longer exists
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

# first tool of each logical group gets a separator above it
_GROUP_STARTS = {ToolMode.RECTANGLE, ToolMode.COLOR_PICKER, ToolMode.HAND}


# ─────────────────────────────────────────────────────────────────────────────
#  Individual tool button
# ─────────────────────────────────────────────────────────────────────────────
class _ToolButton(IconButton):
    def __init__(self, mode: ToolMode, parent=None):
        meta = _TOOL_META[mode]
        super().__init__(meta["icon"], meta["tip"], 18, checkable=True, variant="tool", parent=parent)
        self.mode = mode

    def setChecked(self, v: bool):
        super().setChecked(v)
        # the toggled hook is skipped while signals are blocked — keep the tint in sync
        self.set_icon(self._icon_name, C["accent"] if v else self._color)


# ─────────────────────────────────────────────────────────────────────────────
#  ToolBar widget
# ─────────────────────────────────────────────────────────────────────────────
class ToolBar(QFrame):
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
        self.setProperty("surface", "panel")
        self.setFixedWidth(34 + 2 * SP["xs"] + 1)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        layout = vbox(self, (SP["xs"], SP["sm"], SP["xs"] + 1, SP["sm"]), SP["xs"])
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._buttons: dict[ToolMode, _ToolButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for mode in _ORDERED:
            if mode in _GROUP_STARTS:
                layout.addWidget(Divider())
            btn = _ToolButton(mode, self)
            btn.clicked.connect(lambda checked, m=mode: self._on_btn_clicked(m))
            self._group.addButton(btn)
            self._buttons[mode] = btn
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch()

        # Default tool = Move
        self._active: ToolMode = ToolMode.MOVE
        self._buttons[ToolMode.MOVE].setChecked(True)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C["bg_deep"]))
        p.fillRect(self.width() - 1, 0, 1, self.height(), QColor(C["border"]))
        p.end()

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
