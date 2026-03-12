"""
layerProperties.py  —  Context-sensitive Layer Properties panel.

Displays and edits all properties for the currently-selected layer.
Meant to be embedded inside EditorPanel or used as a floating panel.

Handles these layer kinds:
  paint / image / texture / file  → transform, color adjustments, tint
  text                            → font, size, style, outline, shadow
  fill                            → fill type, colors, angle
  group                           → placeholder (no editable properties)
  locked / child of locked group  → lock notice, all controls hidden

Signals:
  layer_changed(str)   emitted with a reason string on every property edit

Dependencies:
  widgets.py           LabeledSlider, ColorSwatch, HRule, SectionHeader,
                       TagBadge, ToolRow, NumericInput
"""
from __future__ import annotations
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QCheckBox, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore  import Qt, Signal
from PySide6.QtGui   import QColor, QFont

# Internal widget library
from app.ui.widgets import (
    LabeledSlider, ColorSwatch, HRule, SectionHeader,
    TagBadge, ToolRow, NumericInput,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Shared style constants
# ─────────────────────────────────────────────────────────────────────────────
_MONO   = "Courier New"
_BG     = "#1a1a22"
_BORDER = "#2e2e3e"
_TEXT   = "#777"
_ACTIVE = "#ccc"
_ACCENT = "#5566cc"

_STYLE = f"""
QWidget        {{ background:transparent; }}
QLabel         {{ color:{_TEXT}; font-family:'{_MONO}'; font-size:11px;
                  background:transparent; }}
QLineEdit      {{ background:#111118; color:{_ACTIVE}; border:1px solid {_BORDER};
                  border-radius:2px; padding:2px 5px;
                  font-family:'{_MONO}'; font-size:11px; }}
QLineEdit:focus{{ border-color:{_ACCENT}; }}
QComboBox      {{ background:#181822; color:{_ACTIVE}; border:1px solid {_BORDER};
                  border-radius:2px; padding:3px 6px;
                  font-family:'{_MONO}'; font-size:11px; }}
QComboBox::drop-down{{ border:none; }}
QComboBox QAbstractItemView{{
    background:#181822; color:{_ACTIVE};
    selection-background-color:#252550;
    border:1px solid {_BORDER};
}}
QCheckBox      {{ color:{_TEXT}; font-family:'{_MONO}'; font-size:11px; spacing:5px; }}
QCheckBox::indicator{{ width:13px; height:13px;
    border:1px solid #3a3a5a; border-radius:2px; background:#111; }}
QCheckBox::indicator:checked{{ background:{_ACCENT}; border-color:{_ACCENT}; }}
QPushButton    {{ background:#1e1e2e; color:{_TEXT}; border:1px solid {_BORDER};
                  border-radius:2px; padding:3px 8px;
                  font-family:'{_MONO}'; font-size:11px; }}
QPushButton:hover{{ background:#252545; color:{_ACTIVE}; border-color:{_ACCENT}; }}
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Helper — small two-column property row
# ─────────────────────────────────────────────────────────────────────────────
def _prop_row(label: str, widget: QWidget,
              label_width: int = 68) -> QHBoxLayout:
    """Returns a QHBoxLayout with a dim label + right-side widget."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    lbl = QLabel(label)
    lbl.setFixedWidth(label_width)
    lbl.setStyleSheet(f"color:{_TEXT};font-family:'{_MONO}';font-size:11px;"
                      f"background:transparent;")
    row.addWidget(lbl)
    row.addWidget(widget, 1)
    return row


# ─────────────────────────────────────────────────────────────────────────────
#  Placeholder panel
# ─────────────────────────────────────────────────────────────────────────────
class _PlaceholderPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 20, 12, 20)
        self._icon  = QLabel("◻")
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setStyleSheet(
            f"color:#2a2a4a;font-size:28px;background:transparent;")
        self._text = QLabel("Select a layer to\nedit its properties")
        self._text.setAlignment(Qt.AlignCenter)
        self._text.setWordWrap(True)
        self._text.setStyleSheet(
            f"color:#333;font-family:'{_MONO}';font-size:12px;"
            f"background:transparent;")
        lay.addStretch()
        lay.addWidget(self._icon)
        lay.addSpacing(6)
        lay.addWidget(self._text)
        lay.addStretch()

    def set_message(self, icon: str, text: str):
        self._icon.setText(icon)
        self._text.setText(text)


# ─────────────────────────────────────────────────────────────────────────────
#  Shared controls (opacity + blend)  — shown for all non-group layers
# ─────────────────────────────────────────────────────────────────────────────
class _SharedPanel(QWidget):
    """Opacity slider + blend mode combo."""
    opacity_changed    = Signal(float)
    blend_mode_changed = Signal(str)

    BLEND_MODES = [
        "normal", "multiply", "screen", "overlay",
        "soft_light", "color-dodge", "color-burn",
        "hard-light", "difference", "exclusion",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        self._opac_sl = LabeledSlider("Opacity", 0, 100, 100,
                                      fmt=lambda v: f"{v}%",
                                      label_width=58)
        self._opac_sl.value_changed.connect(
            lambda v: self.opacity_changed.emit(v / 100.0))
        lay.addWidget(self._opac_sl)

        blend_row = QHBoxLayout()
        blend_row.setSpacing(6)
        blend_lbl = QLabel("Blend:")
        blend_lbl.setFixedWidth(58)
        blend_lbl.setStyleSheet(
            f"color:{_TEXT};font-family:'{_MONO}';font-size:11px;background:transparent;")
        self._blend_combo = QComboBox()
        self._blend_combo.addItems(self.BLEND_MODES)
        self._blend_combo.currentTextChanged.connect(self.blend_mode_changed)
        blend_row.addWidget(blend_lbl)
        blend_row.addWidget(self._blend_combo, 1)
        lay.addLayout(blend_row)

    def sync(self, layer):
        self._opac_sl.set_value(int(layer.opacity * 100))
        idx = self._blend_combo.findText(layer.blend_mode)
        self._blend_combo.blockSignals(True)
        self._blend_combo.setCurrentIndex(max(0, idx))
        self._blend_combo.blockSignals(False)


# ─────────────────────────────────────────────────────────────────────────────
#  Paint / image layer properties
# ─────────────────────────────────────────────────────────────────────────────
class _PaintPanel(QWidget):
    """Transform + color adjustments + tint for paint/image layers."""
    changed = Signal(str, object)  # (attr_name, value)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        # ── Transform ──────────────────────────────────────────────────────
        lay.addWidget(SectionHeader("TRANSFORM", dim=True))

        self._rot_sl = LabeledSlider("Rotate", -180, 180, 0,
                                     fmt=lambda v: f"{v}°", label_width=58)
        self._rot_sl.value_changed.connect(
            lambda v: self.changed.emit("rotation", float(v)))
        lay.addWidget(self._rot_sl)

        flip_row = ToolRow(buttons=[
            ("↔", "Flip Horizontal", self._flip_h),
            ("↕", "Flip Vertical",   self._flip_v),
        ], btn_size=28)
        lay.addWidget(flip_row)

        lay.addWidget(HRule())

        # ── Color adjustments ──────────────────────────────────────────────
        lay.addWidget(SectionHeader("COLOR ADJUST", dim=True))

        self._bright_sl = LabeledSlider("Brightness", 0, 100, 50, label_width=68)
        self._bright_sl.value_changed.connect(
            lambda v: self.changed.emit("brightness", v))
        lay.addWidget(self._bright_sl)

        self._contrast_sl = LabeledSlider("Contrast", 0, 100, 50, label_width=68)
        self._contrast_sl.value_changed.connect(
            lambda v: self.changed.emit("contrast", v))
        lay.addWidget(self._contrast_sl)

        self._sat_sl = LabeledSlider("Saturation", 0, 100, 50, label_width=68)
        self._sat_sl.value_changed.connect(
            lambda v: self.changed.emit("saturation", v))
        lay.addWidget(self._sat_sl)

        lay.addWidget(HRule())

        # ── Tint ───────────────────────────────────────────────────────────
        lay.addWidget(SectionHeader("TINT OVERLAY", dim=True))

        tint_row = QHBoxLayout()
        tint_row.setSpacing(6)
        tint_lbl = QLabel("Color:")
        tint_lbl.setFixedWidth(46)
        tint_lbl.setStyleSheet(
            f"color:{_TEXT};font-family:'{_MONO}';font-size:11px;background:transparent;")
        self._tint_swatch = ColorSwatch(QColor(255, 100, 100), size=22)
        self._tint_swatch.color_changed.connect(self._on_tint_color)
        tint_row.addWidget(tint_lbl)
        tint_row.addWidget(self._tint_swatch)
        tint_row.addStretch()
        lay.addLayout(tint_row)

        self._tint_str_sl = LabeledSlider("Strength", 0, 100, 0,
                                          fmt=lambda v: f"{v}%", label_width=58)
        self._tint_str_sl.value_changed.connect(
            lambda v: self.changed.emit("tint_strength", v / 100.0))
        lay.addWidget(self._tint_str_sl)

    def _flip_h(self): self.changed.emit("flip_h", "__toggle__")
    def _flip_v(self): self.changed.emit("flip_v", "__toggle__")

    def _on_tint_color(self, c: QColor):
        self.changed.emit("tint_color", (c.red(), c.green(), c.blue()))

    def sync(self, layer):
        self._rot_sl.set_value(int(layer.rotation))
        self._bright_sl.set_value(int(layer.brightness))
        self._contrast_sl.set_value(int(layer.contrast))
        self._sat_sl.set_value(int(layer.saturation))
        if layer.tint_color:
            self._tint_swatch.set_color(QColor(*layer.tint_color))
        self._tint_str_sl.set_value(int(layer.tint_strength * 100))


# ─────────────────────────────────────────────────────────────────────────────
#  Text layer properties
# ─────────────────────────────────────────────────────────────────────────────
class _TextPanel(QWidget):
    """Font, style, size, color, orientation, outline, shadow."""
    changed = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        lay.addWidget(SectionHeader("FONT", dim=True))

        # Font picker
        self._font_combo = QComboBox()
        self._font_combo.addItem("default")
        try:
            from app.config import FONTS_DIR
            if os.path.isdir(FONTS_DIR):
                for fn in sorted(os.listdir(FONTS_DIR)):
                    if fn.lower().endswith((".ttf", ".otf")):
                        self._font_combo.addItem(fn)
        except Exception:
            pass
        self._font_combo.currentTextChanged.connect(
            lambda v: self.changed.emit("font_name", v))
        lay.addLayout(_prop_row("Font:", self._font_combo))

        # Size + Color row
        size_color_row = QHBoxLayout()
        size_color_row.setSpacing(6)
        sz_lbl = QLabel("Size:")
        sz_lbl.setFixedWidth(32)
        sz_lbl.setStyleSheet(f"color:{_TEXT};font-family:'{_MONO}';font-size:11px;background:transparent;")
        self._font_size = NumericInput(48, 4, 999, 1, unit="px", width=52)
        self._font_size.value_changed.connect(
            lambda v: self.changed.emit("font_size", int(v)))
        size_color_row.addWidget(sz_lbl)
        size_color_row.addWidget(self._font_size)
        size_color_row.addStretch()
        col_lbl = QLabel("Color:")
        col_lbl.setStyleSheet(f"color:{_TEXT};font-family:'{_MONO}';font-size:11px;background:transparent;")
        self._text_color = ColorSwatch(QColor(255, 255, 255), size=22)
        self._text_color.color_changed.connect(
            lambda c: self.changed.emit("font_color", (c.red(), c.green(), c.blue())))
        size_color_row.addWidget(col_lbl)
        size_color_row.addWidget(self._text_color)
        lay.addLayout(size_color_row)

        # Style checkboxes
        style_row = QHBoxLayout()
        style_row.setSpacing(8)
        self._bold_cb   = QCheckBox("Bold")
        self._italic_cb = QCheckBox("Italic")
        self._upper_cb  = QCheckBox("CAPS")
        for cb, attr in [(self._bold_cb,   "font_bold"),
                          (self._italic_cb, "font_italic"),
                          (self._upper_cb,  "font_uppercase")]:
            cb.stateChanged.connect(
                lambda v, a=attr: self.changed.emit(a, bool(v)))
            style_row.addWidget(cb)
        style_row.addStretch()
        lay.addLayout(style_row)

        lay.addWidget(HRule())
        lay.addWidget(SectionHeader("SPACING & ORIENTATION", dim=True))

        self._letter_sp = NumericInput(0, -50, 200, 1, label="", unit="px", width=52)
        self._letter_sp.value_changed.connect(
            lambda v: self.changed.emit("letter_spacing", int(v)))
        lay.addLayout(_prop_row("Letter sp:", self._letter_sp))

        self._orient_combo = QComboBox()
        self._orient_combo.addItems(["horizontal", "vertical", "rotate90", "rotate270"])
        self._orient_combo.currentTextChanged.connect(
            lambda v: self.changed.emit("text_orientation", v))
        lay.addLayout(_prop_row("Orientation:", self._orient_combo))

        align_combo = QComboBox()
        align_combo.addItems(["left", "center", "right"])
        align_combo.currentTextChanged.connect(
            lambda v: self.changed.emit("text_align", v))
        self._align_combo = align_combo
        lay.addLayout(_prop_row("Align:", self._align_combo))

        lay.addWidget(HRule())
        lay.addWidget(SectionHeader("OUTLINE & SHADOW", dim=True))

        self._outline_sl = LabeledSlider("Outline", 0, 30, 0, label_width=58)
        self._outline_sl.value_changed.connect(
            lambda v: self.changed.emit("outline_size", int(v)))
        lay.addWidget(self._outline_sl)

        self._shadow_sl = LabeledSlider("Shadow", 0, 30, 0, label_width=58)
        self._shadow_sl.value_changed.connect(
            lambda v: self.changed.emit("shadow_offset", int(v)))
        lay.addWidget(self._shadow_sl)

        # Outline color
        self._outline_color = ColorSwatch(QColor(0, 0, 0), size=20)
        self._outline_color.color_changed.connect(
            lambda c: self.changed.emit("outline_color",
                                        (c.red(), c.green(), c.blue())))
        lay.addLayout(_prop_row("Outline col:", self._outline_color))

        # Shadow color
        self._shadow_color = ColorSwatch(QColor(0, 0, 0), size=20)
        self._shadow_color.color_changed.connect(
            lambda c: self.changed.emit("shadow_color",
                                        (c.red(), c.green(), c.blue())))
        lay.addLayout(_prop_row("Shadow col:", self._shadow_color))

    def sync(self, layer):
        # Font
        idx = self._font_combo.findText(layer.font_name)
        self._font_combo.blockSignals(True)
        self._font_combo.setCurrentIndex(max(0, idx))
        self._font_combo.blockSignals(False)
        self._font_size.set_value(layer.font_size)
        if layer.font_color:
            self._text_color.set_color(QColor(*layer.font_color))
        # Style
        for cb, attr in [(self._bold_cb,   "font_bold"),
                          (self._italic_cb, "font_italic"),
                          (self._upper_cb,  "font_uppercase")]:
            cb.blockSignals(True)
            cb.setChecked(getattr(layer, attr, False))
            cb.blockSignals(False)
        # Spacing / orientation
        self._letter_sp.set_value(layer.letter_spacing)
        oi = self._orient_combo.findText(layer.text_orientation)
        self._orient_combo.blockSignals(True)
        self._orient_combo.setCurrentIndex(max(0, oi))
        self._orient_combo.blockSignals(False)
        ai = self._align_combo.findText(layer.text_align)
        self._align_combo.blockSignals(True)
        self._align_combo.setCurrentIndex(max(0, ai))
        self._align_combo.blockSignals(False)
        # Outline / shadow
        self._outline_sl.set_value(layer.outline_size)
        self._shadow_sl.set_value(layer.shadow_offset)
        if layer.outline_color:
            self._outline_color.set_color(QColor(*layer.outline_color))
        if layer.shadow_color:
            self._shadow_color.set_color(QColor(*layer.shadow_color))


# ─────────────────────────────────────────────────────────────────────────────
#  Fill layer properties
# ─────────────────────────────────────────────────────────────────────────────
class _FillPanel(QWidget):
    """Fill type, colors, gradient angle."""
    changed = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        lay.addWidget(SectionHeader("FILL TYPE", dim=True))

        self._type_combo = QComboBox()
        self._type_combo.addItems(["solid", "gradient"])
        self._type_combo.currentTextChanged.connect(
            lambda v: self.changed.emit("fill_type", v))
        lay.addLayout(_prop_row("Type:", self._type_combo))

        self._c1 = ColorSwatch(QColor(80, 80, 200), size=22)
        self._c1.color_changed.connect(
            lambda c: self.changed.emit(
                "fill_color", (c.red(), c.green(), c.blue())))
        lay.addLayout(_prop_row("Color 1:", self._c1))

        self._c2 = ColorSwatch(QColor(200, 80, 80), size=22)
        self._c2.color_changed.connect(
            lambda c: self.changed.emit(
                "fill_color2", (c.red(), c.green(), c.blue())))
        lay.addLayout(_prop_row("Color 2:", self._c2))

        self._angle_sl = LabeledSlider("Angle", 0, 359, 0,
                                       fmt=lambda v: f"{v}°", label_width=58)
        self._angle_sl.value_changed.connect(
            lambda v: self.changed.emit("fill_angle", float(v)))
        lay.addWidget(self._angle_sl)

    def sync(self, layer):
        self._type_combo.blockSignals(True)
        self._type_combo.setCurrentText(layer.fill_type)
        self._type_combo.blockSignals(False)
        self._c1.set_color(QColor(*layer.fill_color))
        self._c2.set_color(QColor(*layer.fill_color2))
        self._angle_sl.set_value(int(layer.fill_angle))


# ─────────────────────────────────────────────────────────────────────────────
#  Main public widget
# ─────────────────────────────────────────────────────────────────────────────
class LayerPropertiesWidget(QWidget):
    """
    Context-sensitive layer property editor.

    Connect to canvas and call refresh() after any layer selection change.

    Signals:
        layer_changed(str)   — reason string, e.g. "opacity", "rotation"

    API:
        set_canvas(canvas)   — bind to PreviewCanvas
        refresh()            — re-sync all controls from the selected layer
    """
    layer_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_STYLE)
        self._canvas = None

        # Scrollable wrapper so the panel doesn't clip on small heights
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{border:none;background:#1a1a22;}"
            "QScrollBar:vertical{background:#111;width:5px;border:none;}"
            "QScrollBar::handle:vertical{background:#2a2a4a;border-radius:2px;min-height:16px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        outer.addWidget(scroll)

        # Inner container
        inner = QWidget()
        inner.setStyleSheet("background:#1a1a22;")
        self._inner_lay = QVBoxLayout(inner)
        self._inner_lay.setContentsMargins(8, 6, 8, 8)
        self._inner_lay.setSpacing(6)
        scroll.setWidget(inner)

        # ── Build sub-panels ───────────────────────────────────────────────
        self._placeholder = _PlaceholderPanel()
        self._inner_lay.addWidget(self._placeholder)

        self._shared = _SharedPanel()
        self._shared.opacity_changed.connect(
            lambda v: self._set("opacity", v, "opacity"))
        self._shared.blend_mode_changed.connect(
            lambda v: self._set("blend_mode", v, "blend"))
        self._inner_lay.addWidget(self._shared)

        self._inner_lay.addWidget(HRule())

        self._paint_panel = _PaintPanel()
        self._paint_panel.changed.connect(self._on_panel_change)
        self._inner_lay.addWidget(self._paint_panel)

        self._text_panel = _TextPanel()
        self._text_panel.changed.connect(self._on_panel_change)
        self._inner_lay.addWidget(self._text_panel)

        self._fill_panel = _FillPanel()
        self._fill_panel.changed.connect(self._on_panel_change)
        self._inner_lay.addWidget(self._fill_panel)

        self._inner_lay.addStretch()

        # Default: show placeholder
        self._show("placeholder")

    # ── Public API ────────────────────────────────────────────────────────────

    def set_canvas(self, canvas):
        self._canvas = canvas

    def refresh(self):
        """
        Sync all visible controls from the currently selected canvas layer.
        Call this whenever the canvas selection changes.
        """
        if not self._canvas:
            self._show("placeholder"); return

        idx = self._canvas.selected_layer_index()
        if idx < 0 or idx >= len(self._canvas.layers):
            self._placeholder.set_message("◻", "Select a layer to\nedit its properties")
            self._show("placeholder"); return

        layer = self._canvas.layers[idx]

        # ── Group layer ────────────────────────────────────────────────────
        if layer.kind == "group":
            self._placeholder.set_message(
                "📁",
                f"{layer.name}\n\nGroup layer — select\na child to edit.")
            self._show("placeholder"); return

        # ── Locked? (own lock or parent group lock) ────────────────────────
        parent_idx = getattr(layer, "_group_parent", None)
        parent_locked = False
        if parent_idx is not None and 0 <= parent_idx < len(self._canvas.layers):
            parent_locked = getattr(self._canvas.layers[parent_idx], "locked", False)
        if getattr(layer, "locked", False) or parent_locked:
            self._placeholder.set_message(
                "🔒", "Layer is locked\n\nUnlock it to edit\nits properties.")
            self._show("placeholder"); return

        # ── Normal layer ───────────────────────────────────────────────────
        is_paint = layer.kind in ("paint", "image", "texture", "file")
        is_text  = layer.kind == "text"
        is_fill  = layer.kind == "fill"

        if   is_paint: section = "paint"
        elif is_text:  section = "text"
        elif is_fill:  section = "fill"
        else:
            # Unrecognised kind — show placeholder
            self._placeholder.set_message("◻", f"Kind: {layer.kind}\n(no properties)")
            self._show("placeholder"); return

        self._show(section)
        self._shared.sync(layer)

        if is_paint: self._paint_panel.sync(layer)
        if is_text:  self._text_panel.sync(layer)
        if is_fill:  self._fill_panel.sync(layer)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _show(self, which: str):
        """Show only the relevant section widgets."""
        is_ph = which == "placeholder"
        self._placeholder.setVisible(is_ph)
        self._shared.setVisible(not is_ph)
        # Separator only when content is visible
        # (we find the HRule between shared and paint by index)
        self._paint_panel.setVisible(which == "paint")
        self._text_panel.setVisible(which  == "text")
        self._fill_panel.setVisible(which  == "fill")

    def _on_panel_change(self, attr: str, value):
        """Handle 'changed' signals from sub-panels."""
        if not self._canvas: return
        layer = self._canvas.selected_layer()
        if not layer: return

        if value == "__toggle__":
            # Flip boolean attribute
            value = not getattr(layer, attr, False)

        self._set(attr, value, attr)

    def _set(self, attr: str, value, reason: str = ""):
        """Apply an attribute to the selected layer via the canvas authority.
        Routes through update_selected_layer() so undo history is pushed,
        FX cache is invalidated, and layers_changed is emitted correctly."""
        if not self._canvas: return
        try:
            self._canvas.update_selected_layer(**{attr: value})
        except Exception:
            pass
        self.layer_changed.emit(reason)