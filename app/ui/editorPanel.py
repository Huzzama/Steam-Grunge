"""
Right-hand editor panel: template picker, asset library, canvas effects, the
layer stack and the context-sensitive layer properties, with the export
buttons pinned in a footer under the scroll area.

Every section is a collapsible ``kit.Section``; expanded state is remembered
per section at class level so it survives tab switches.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QScrollArea,
    QSizePolicy, QStackedWidget, QWidget,
)

from app.config import (PLATFORM_BARS_DIR, RATINGS_DIR, USER_FONTS_DIR, USER_TEXTURES_DIR,
                        font_dirs, font_path, texture_dirs)
from app.ui import icons, theme
from app.ui.fontImporter import import_fonts, register_all_fonts
from app.ui.kit import (Button, ChipRow, ColorSwatch, Divider, EmptyState, IconButton, Section,
                        SliderRow, SpinRow, SubHeader, grid, hbox, label, vbox)
from app.ui.layerDelegate import LayerDelegate
from app.ui.theme import C, CONTROL_H, R, SP

BLEND_MODES = ["normal", "multiply", "screen", "overlay", "darken", "lighten",
               "color-dodge", "color-burn", "hard-light", "soft-light",
               "difference", "exclusion", "hue", "saturation", "color", "luminosity"]

TEMPLATES = [
    # key, label, icon (transparent templates get the image icon)
    ("cover",        "COVER · 600×900",        None),
    ("vhs_cover",    "VHS COVER · 600×900",    None),
    ("wide",         "WIDE · 920×430",         None),
    ("vhs_pile",     "VHS PILE · 920×430",     None),
    ("vhs_cassette", "VHS CASSETTE · 920×430", None),
    ("hero",         "HERO · 3840×1240",       None),
    ("logo",         "LOGO · 1280×720",        "image"),
    ("icon",         "ICON · 512×512",         "image"),
]


# ── Small UI helpers ───────────────────────────────────────────────────────────

def _combo(items=()) -> QComboBox:
    """Combo that stretches with the panel instead of forcing its width."""
    cb = QComboBox()
    cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    cb.setMinimumContentsLength(6)
    cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    for it in items:
        cb.addItem(it)
    return cb


def _row(*widgets, stretch_last: bool = True):
    lay = hbox(spacing=SP["sm"])
    for i, w in enumerate(widgets):
        lay.addWidget(w, 1 if (stretch_last and i == len(widgets) - 1) else 0)
    return lay


class LabeledSlider(SliderRow):
    """
    ``kit.SliderRow`` with the float API the slots have always used:
    ``value_changed(float)``, ``set_value(v)`` silently, ``value() -> float``.
    Double-clicking the slider resets it, like before.
    """
    value_changed = Signal(float)

    def __init__(self, title: str, min_v: int = 0, max_v: int = 100, default: int = 50, suffix: str = ""):
        super().__init__(title, min_v, max_v, default, default, suffix)
        self.valueChanged.connect(lambda v: self.value_changed.emit(float(v)))
        self.slider.setToolTip("Double-click to reset")
        self.slider.mouseDoubleClickEvent = lambda _e: self.reset()
        self.reset_btn.setToolTip(f"Reset to {default}{suffix}")

    def set_value(self, v, emit: bool = False):
        super().set_value(int(round(float(v))), emit=emit)

    def value(self) -> float:
        return float(self.slider.value())


class _TemplateChip(Button):
    """Template button that elides its label instead of widening the panel."""

    def __init__(self, text: str, icon=None, on_click=None):
        super().__init__(text, "template", icon=icon, on_click=on_click, icon_size=13)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(40)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        avail = self.width() - 22 - (self._icon_size + 6 if self._icon_name else 0)
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(12, avail)))


class _Thumb(QLabel):
    """Asset preview: inset surface, fixed height, pixmap rescaled to the width."""

    def __init__(self, height: int = 56):
        super().__init__("none")
        self.setProperty("surface", "inset")
        self.setProperty("role", "muted")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._src = QPixmap()

    def set_source(self, path):
        self._src = QPixmap(path) if path and os.path.exists(path) else QPixmap()
        self._rescale()

    def _rescale(self):
        if self._src.isNull():
            self.setPixmap(QPixmap())
            self.setText("none")
            return
        w, h = max(32, self.width() - 12), self.height() - 12
        self.setPixmap(self._src.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._src.isNull():
            self._rescale()


# ─────────────────────────────────────────────────────────────────────────────
#  Font Panel Widgets
# ─────────────────────────────────────────────────────────────────────────────

class _FontPreviewList(QWidget):
    """
    Scrollable list of fonts, each rendered in its own typeface.
    Shows "STEAM GRUNGE" as preview text (or the font name if rendering fails).
    (QFont is unavoidable here: the whole point is drawing each font family.)
    """
    font_selected = Signal(str, str)   # (display_name, userData/filename)

    ITEM_H   = 38
    PREVIEW  = "STEAM GRUNGE"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, str]] = []   # (display, userData)
        self._filtered: list[tuple[str, str]] = []
        self._sel_idx = -1
        self._hover_idx = -1
        self._fam_cache: dict[str, str] = {}
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._scroll_y = 0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_items(self, items: list):
        """items: list of (display_name, userData)"""
        self._items    = list(items)
        self._filtered = list(items)
        self._sel_idx  = 0 if items else -1
        self._scroll_y = 0
        self.update()

    def apply_filter(self, query: str):
        q = query.strip().lower()
        if q:
            self._filtered = [(d, u) for d, u in self._items if q in d.lower()]
        else:
            self._filtered = list(self._items)
        self._sel_idx  = 0 if self._filtered else -1
        self._scroll_y = 0
        self.update()
        if self._filtered:
            self.font_selected.emit(*self._filtered[0])

    def select_by_userdata(self, userdata: str):
        for i, (d, u) in enumerate(self._filtered):
            if u == userdata:
                self._sel_idx = i
                self._ensure_visible(i)
                self.update()
                return

    def selected(self):
        if 0 <= self._sel_idx < len(self._filtered):
            return self._filtered[self._sel_idx]
        return None, None

    def _family(self, display: str, userdata: str) -> str:
        key = userdata or display
        fam = self._fam_cache.get(key)
        if fam is None:
            try:
                fid = QFontDatabase.addApplicationFont(font_path(userdata) if userdata else "")
                fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                fam = fams[0] if fams else display
            except Exception:
                fam = theme.FONT
            self._fam_cache[key] = fam
        return fam

    # ── paint ─────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.fillRect(self.rect(), QColor(C["bg_deep"]))
        p.setPen(QPen(QColor(C["border"]), 1))
        p.drawRect(0, 0, W - 1, H - 1)

        if not self._filtered:
            p.setPen(QColor(C["text_muted"]))
            p.setFont(theme.font("sm"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No fonts match")
            p.end()
            return

        total_h = len(self._filtered) * self.ITEM_H
        max_scroll = max(0, total_h - H)
        self._scroll_y = max(0, min(self._scroll_y, max_scroll))
        p.setClipRect(1, 1, W - 2, H - 2)

        name_w = min(120, max(60, W // 3))
        for i, (display, userdata) in enumerate(self._filtered):
            iy = i * self.ITEM_H - self._scroll_y
            if iy + self.ITEM_H < 0 or iy > H:
                continue
            item_rect = QRect(0, iy, W, self.ITEM_H)
            sel = i == self._sel_idx
            if sel:
                p.fillRect(item_rect, QColor(C["accent_dim"]))
            elif i == self._hover_idx:
                p.fillRect(item_rect, QColor(C["surface_2"]))
            p.setPen(QPen(QColor(C["border"]), 1))
            p.drawLine(0, iy + self.ITEM_H - 1, W, iy + self.ITEM_H - 1)

            # Preview text in the actual font (left side)
            p.setFont(QFont(self._family(display, userdata), 13))
            p.setPen(QColor(C["text"] if sel else C["text_2"]))
            p.drawText(QRect(8, iy, W - name_w - 12, self.ITEM_H),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.PREVIEW)

            # Font name (right side, small mono)
            p.setFont(theme.font("xs"))
            p.setPen(QColor(C["accent"] if sel else C["text_muted"]))
            p.drawText(QRect(W - name_w - 4, iy, name_w, self.ITEM_H),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       p.fontMetrics().elidedText(display, Qt.TextElideMode.ElideRight, name_w))
        p.end()

    # ── events ────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        idx = (e.pos().y() + self._scroll_y) // self.ITEM_H
        if 0 <= idx < len(self._filtered):
            self._sel_idx = idx
            self.update()
            self.font_selected.emit(*self._filtered[idx])

    def mouseMoveEvent(self, e):
        idx = (e.pos().y() + self._scroll_y) // self.ITEM_H
        new_hover = idx if 0 <= idx < len(self._filtered) else -1
        if new_hover != self._hover_idx:
            self._hover_idx = new_hover
            self.update()

    def leaveEvent(self, _):
        self._hover_idx = -1
        self.update()

    def wheelEvent(self, e):
        self._scroll_y -= e.angleDelta().y() // 2
        total_h = len(self._filtered) * self.ITEM_H
        self._scroll_y = max(0, min(self._scroll_y, max(0, total_h - self.height())))
        self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Up and self._sel_idx > 0:
            self._sel_idx -= 1
        elif e.key() == Qt.Key.Key_Down and self._sel_idx < len(self._filtered) - 1:
            self._sel_idx += 1
        else:
            return
        self._ensure_visible(self._sel_idx)
        self.update()
        self.font_selected.emit(*self._filtered[self._sel_idx])

    def _ensure_visible(self, idx):
        iy = idx * self.ITEM_H
        if iy < self._scroll_y:
            self._scroll_y = iy
        elif iy + self.ITEM_H > self._scroll_y + self.height():
            self._scroll_y = iy + self.ITEM_H - self.height()


class _FontPreviewBar(QWidget):
    """Shows a live text preview using the currently selected font+style."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text      = "STEAM GRUNGE"
        self._font_fam  = theme.FONT
        self._size      = 16
        self._bold      = False
        self._italic    = False
        self._color     = QColor(C["text"])

    def update_preview(self, font_fam="", size=16, bold=False, italic=False, color: QColor = None):
        if font_fam: self._font_fam = font_fam
        if size:     self._size = max(8, min(size, 28))
        self._bold   = bold
        self._italic = italic
        if color:    self._color = color
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setBrush(QColor(C["surface"]))
        p.setPen(QPen(QColor(C["border"]), 1))
        p.drawRoundedRect(r, R["sm"], R["sm"])
        f = QFont(self._font_fam, self._size)
        f.setBold(self._bold)
        f.setItalic(self._italic)
        p.setFont(f)
        p.setPen(self._color)
        p.drawText(r.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
#  Editor panel
# ─────────────────────────────────────────────────────────────────────────────

class EditorPanel(QFrame):
    settings_changed = Signal()
    template_changed = Signal(str)

    # section key -> expanded?  (class-level so it survives tab switches)
    _expanded: dict[str, bool] = {}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EditorPanel")
        self.setProperty("surface", "panel")
        # Tab-local state and tab ref — set by set_canvas()
        self._tab_state = None
        self._tab_ref   = None
        # Register existing fonts with Qt so they're available immediately
        for _d in font_dirs():
            register_all_fonts(_d)
        self._build_ui()

    # ── Tab-local state accessor ───────────────────────────────────────────────
    def _st(self):
        """Return the current tab's AppState, or None if not yet connected."""
        return self._tab_state

    # ── Build ──────────────────────────────────────────────────────────────────

    def _section(self, key: str, title: str, trailing=None) -> Section:
        sec = Section(title, expanded=EditorPanel._expanded.get(key, True), trailing=trailing)
        sec.toggled.connect(lambda on, k=key: EditorPanel._expanded.__setitem__(k, on))
        return sec

    def _build_ui(self):
        outer = vbox(self, (0, 0, 0, 0), 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        container = QWidget()
        self._content = vbox(container, (SP["md"], SP["md"], SP["md"], SP["md"]), SP["md"])
        scroll.setWidget(container)

        self._content.addWidget(self._build_template())
        self._content.addWidget(self._build_assets())
        self._content.addWidget(self._build_canvas())
        layers = self._build_layers()
        self._content.addWidget(layers, 1)
        layers.toggled.connect(lambda on: self._content.setStretchFactor(layers, 1 if on else 0))
        self._content.addWidget(self._build_layer_props())
        self._content.addStretch(0)

        outer.addWidget(self._build_footer())

    # ── TEMPLATE ──────────────────────────────────────────────────────────────
    def _build_template(self) -> Section:
        sec = self._section("template", "Template")
        g = grid(h=SP["sm"], v=SP["sm"])
        self._tpl_buttons: dict[str, _TemplateChip] = {}
        for i, (key, text, icon) in enumerate(TEMPLATES):
            b = _TemplateChip(text, icon, on_click=lambda _=False, k=key: self._select_template(k))
            b.setToolTip(text + ("  (transparent)" if icon else ""))
            self._tpl_buttons[key] = b
            g.addWidget(b, i // 2, i % 2)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        sec.body.addLayout(g)
        # legacy names
        self.tpl_cover_btn    = self._tpl_buttons["cover"]
        self.tpl_vhs_btn      = self._tpl_buttons["vhs_cover"]
        self.tpl_wide_btn     = self._tpl_buttons["wide"]
        self.tpl_vhs_pile_btn = self._tpl_buttons["vhs_pile"]
        self.tpl_vhs_cass_btn = self._tpl_buttons["vhs_cassette"]
        self.tpl_hero_btn     = self._tpl_buttons["hero"]
        self.tpl_logo_btn     = self._tpl_buttons["logo"]
        self.tpl_icon_btn     = self._tpl_buttons["icon"]
        self._update_template_buttons()
        return sec

    # ── ASSETS (bars · ratings · texture) ─────────────────────────────────────
    def _asset_page(self, combo: QComboBox, thumb: _Thumb, slot, tip: str) -> QWidget:
        page = QWidget()
        lay = vbox(page, (0, 0, 0, 0), SP["sm"])
        lay.addWidget(combo)
        lay.addWidget(thumb)
        lay.addWidget(Button("Add as layer", icon="plus", on_click=slot, tooltip=tip))
        return page

    def _build_assets(self) -> Section:
        sec = self._section("assets", "Assets")
        self._asset_chips = ChipRow([("bars", "Bars"), ("ratings", "Ratings"), ("texture", "Texture")])
        sec.body.addWidget(self._asset_chips)
        self._asset_stack = QStackedWidget()
        self._asset_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sec.body.addWidget(self._asset_stack)

        # Console bars (preview must exist before _populate_platform_combo)
        self.bar_preview = _Thumb()
        self.platform_combo = _combo()
        self._populate_platform_combo()
        self.platform_combo.currentIndexChanged.connect(self._on_platform_changed)
        self._asset_stack.addWidget(self._asset_page(
            self.platform_combo, self.bar_preview, self._add_bar_layer_from_combo,
            "Add the selected console bar as a layer across the top of the canvas"))

        # Ratings
        self.ratings_preview = _Thumb()
        self.ratings_combo = _combo()
        self._populate_ratings_combo()
        self.ratings_combo.currentIndexChanged.connect(self._on_rating_changed)
        self._asset_stack.addWidget(self._asset_page(
            self.ratings_combo, self.ratings_preview, self._add_rating_layer_from_combo,
            "Add the selected rating badge as a layer (bottom-right corner)"))

        # Deterioration textures
        self.det_preview = _Thumb()
        self.det_combo = _combo()
        self._populate_det_combo()                       # reads from assets/textures/
        self.det_combo.currentIndexChanged.connect(self._on_det_changed)
        self._asset_stack.addWidget(self._asset_page(
            self.det_combo, self.det_preview, self._add_det_layer_from_combo,
            "Add the selected texture as a full-canvas overlay layer"))

        order = ["bars", "ratings", "texture"]
        self._asset_chips.changed.connect(lambda k: self._asset_stack.setCurrentIndex(order.index(k)))
        self._asset_chips.set_current("bars", emit=False)
        return sec

    # ── CANVAS (background · grain · aberration) ──────────────────────────────
    def _build_canvas(self) -> Section:
        sec = self._section("canvas", "Canvas")
        self._current_bg_color = QColor(0, 0, 0)
        self.bg_swatch = ColorSwatch("#000000", "Background colour")
        self.bg_swatch.color_changed.connect(lambda h: self._apply_bg_color(QColor(h)))
        sec.body.addLayout(_row(self.bg_swatch, label("Background", "dim")))

        self.grain_slider = LabeledSlider("Film grain", 0, 100, 0)
        self.grain_slider.value_changed.connect(self._on_grain)
        sec.body.addWidget(self.grain_slider)

        self.ca_slider = LabeledSlider("Chromatic aberration", 0, 100, 0)
        self.ca_slider.value_changed.connect(self._on_ca)
        sec.body.addWidget(self.ca_slider)
        return sec

    # ── LAYERS ────────────────────────────────────────────────────────────────
    def _build_layers(self) -> Section:
        sec = self._section("layers", "Layers")

        self._layer_blend_top = _combo(BLEND_MODES)
        self._layer_blend_top.setToolTip("Blend mode of the selected layer")
        self._layer_blend_top.currentTextChanged.connect(self._on_blend_top_changed)
        sec.body.addLayout(_row(label("Blend", "dim"), self._layer_blend_top))

        self._layer_opac_slider = LabeledSlider("Opacity", 0, 100, 100, "%")
        self._layer_opac_lbl = self._layer_opac_slider.value_lbl
        self._layer_opac_slider.valueChanged.connect(self._on_layer_opac_top)
        sec.body.addWidget(self._layer_opac_slider)

        # Layer list (rows with thumb + name + badges)
        self._layer_delegate = LayerDelegate()
        self.layer_list = QListWidget()
        self.layer_list.setItemDelegate(self._layer_delegate)
        self.layer_list.setMinimumHeight(160)
        self.layer_list.setMaximumHeight(400)
        self.layer_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.layer_list.setUniformItemSizes(True)
        self.layer_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.layer_list.setSpacing(0)
        # Drag-and-drop for layer reordering and grouping
        self.layer_list.setDragEnabled(True)
        self.layer_list.setAcceptDrops(True)
        self.layer_list.setDropIndicatorShown(False)   # we draw our own
        self.layer_list.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.layer_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.layer_list.currentRowChanged.connect(self._on_layer_list_select)
        self.layer_list.clicked.connect(self._on_layer_list_clicked)
        self.layer_list.doubleClicked.connect(self._on_layer_double_clicked)
        self.layer_list.model().rowsMoved.connect(self._on_rows_moved)
        self._drag_drop_indicator_row = -1   # row where drop indicator is shown
        sec.body.addWidget(self.layer_list, 1)

        # Toolbar
        tb = hbox(spacing=SP["xs"])
        self._add_layer_btn = IconButton("plus", "Add layer")
        self._add_layer_btn.setMenu(self._build_add_menu(self._add_layer_btn))
        tb.addWidget(self._add_layer_btn)
        tb.addStretch()
        for icon, tip, slot in [
            ("arrow-up",   "Move layer up",        self._move_layer_up),
            ("arrow-down", "Move layer down",      self._move_layer_down),
            ("copy",       "Duplicate layer",      self._duplicate_layer),
            ("eye",        "Toggle visibility",    self._toggle_layer_visibility),
            ("lock",       "Lock / unlock layer",  self._toggle_layer_lock),
            ("trash",      "Delete layer",         self._delete_selected_layer),
        ]:
            tb.addWidget(IconButton(icon, tip, on_click=slot))
        sec.body.addLayout(tb)
        return sec

    def _build_add_menu(self, parent) -> QMenu:
        m = QMenu(parent)
        ic = lambda n: icons.icon(n, C["text_2"], 14)

        act = m.addAction(ic("paintbrush"), "Paint layer", self._add_paint_layer)
        act.setToolTip("Create a blank paint layer")
        act = m.addAction(ic("folder"), "Group layer", self._add_group_layer)
        act.setToolTip("Create an empty group folder")
        act = m.addAction(ic("droplet"), "Fill layer", self._add_fill_layer)
        act.setToolTip("Create a solid colour or gradient fill")
        m.addSeparator()
        m.addAction("Quick add").setEnabled(False)
        m.addAction(ic("type"), "Text layer", self._add_text_layer)
        m.addAction(ic("gamepad-2"), "Platform bar", self._add_bar_layer)
        m.addAction(ic("sparkles"), "Texture layer", self._add_texture_layer)
        m.addSeparator()
        m.addAction("Import").setEnabled(False)
        act = m.addAction(ic("folder-open"), "Import image file…", self._import_file_layer)
        act.setToolTip("Import a PNG or JPG as a layer")
        return m

    # ── LAYER PROPERTIES ──────────────────────────────────────────────────────
    def _build_layer_props(self) -> Section:
        sec = self._section("props", "Layer properties")
        body = sec.body

        # Placeholders (one visible at a time)
        self.props_placeholder = EmptyState("layers", "Select a layer",
                                            "Pick a layer in the list above to edit its properties.")
        self._group_placeholder = EmptyState("folder", "Group", "Select a child layer to edit its properties.")
        self._locked_placeholder = EmptyState("lock", "Layer is locked", "Unlock it to edit its properties.")
        self._unlock_btn = Button("Unlock layer", icon="lock-open", on_click=self._toggle_layer_lock)
        for w in (self.props_placeholder, self._group_placeholder, self._locked_placeholder, self._unlock_btn):
            body.addWidget(w)

        # Shared: opacity + blend
        self.shared_controls = QWidget()
        sl = vbox(self.shared_controls, (0, 0, 0, 0), SP["sm"])
        sl.addWidget(SubHeader("Blend & opacity"))
        self.opacity_slider = LabeledSlider("Opacity", 0, 100, 100, "%")
        self.opacity_slider.value_changed.connect(self._on_opacity)
        sl.addWidget(self.opacity_slider)
        self.blend_combo = _combo(["normal", "multiply", "screen", "overlay", "soft_light"])
        self.blend_combo.currentTextChanged.connect(
            lambda v: self._canvas.update_selected_layer(blend_mode=v) if hasattr(self, '_canvas') else None)
        sl.addLayout(_row(label("Blend", "dim"), self.blend_combo))
        body.addWidget(self.shared_controls)

        body.addWidget(self._build_image_controls())
        body.addWidget(self._build_text_controls())
        body.addWidget(self._build_fill_controls())
        body.addWidget(self._build_filter_controls())
        body.addWidget(self._build_clone_controls())
        body.addWidget(self._build_vector_controls())
        body.addWidget(self._build_group_controls())
        body.addWidget(self._build_mask_controls())

        self._set_props_mode("empty")
        return sec

    def _build_image_controls(self) -> QWidget:
        self.img_controls = QWidget()
        lay = vbox(self.img_controls, (0, 0, 0, 0), SP["sm"])

        lay.addWidget(SubHeader("Transform"))
        self.rotation_slider = LabeledSlider("Rotate", -180, 180, 0, "°")
        self.rotation_slider.value_changed.connect(
            lambda v: self._canvas.update_selected_layer(rotation=v) if hasattr(self, '_canvas') else None)
        lay.addWidget(self.rotation_slider)
        flip = hbox(spacing=SP["sm"])
        flip.addWidget(Button("Flip H", icon="flip-horizontal", on_click=self._flip_horizontal,
                              tooltip="Mirror horizontally"), 1)
        flip.addWidget(Button("Flip V", icon="flip-vertical", on_click=self._flip_vertical,
                              tooltip="Mirror vertically"), 1)
        lay.addLayout(flip)

        lay.addWidget(SubHeader("Fit"))
        fit = hbox(spacing=SP["sm"])
        for text, tip, slot in [("Fit", "Scale to fit inside the canvas", self._fit_canvas),
                                ("Fill", "Scale to cover the canvas (may crop)", self._fill_canvas),
                                ("Center", "Centre the layer on the canvas", self._center_layer)]:
            fit.addWidget(Button(text, on_click=slot, tooltip=tip), 1)
        lay.addLayout(fit)

        lay.addWidget(SubHeader("Colour"))
        self.layer_bright = LabeledSlider("Brightness", 0, 100, 50)
        self.layer_bright.value_changed.connect(lambda v: self._layer_color_changed("brightness", v))
        lay.addWidget(self.layer_bright)
        self.layer_contrast = LabeledSlider("Contrast", 0, 100, 50)
        self.layer_contrast.value_changed.connect(lambda v: self._layer_color_changed("contrast", v))
        lay.addWidget(self.layer_contrast)
        self.layer_sat = LabeledSlider("Saturation", 0, 100, 50)
        self.layer_sat.value_changed.connect(lambda v: self._layer_color_changed("saturation", v))
        lay.addWidget(self.layer_sat)

        lay.addWidget(SubHeader("Tint"))
        self._current_tint = QColor(255, 255, 255)
        self.tint_preview = ColorSwatch("#ffffff", "Tint colour")
        self.tint_preview.color_changed.connect(lambda h: self._apply_tint_color(QColor(h)))
        lay.addLayout(_row(self.tint_preview, label("Tint colour", "dim")))
        self.tint_strength_slider = LabeledSlider("Strength", 0, 100, 0, "%")
        self.tint_strength_slider.value_changed.connect(self._on_tint_strength)
        lay.addWidget(self.tint_strength_slider)
        return self.img_controls

    def _build_text_controls(self) -> QWidget:
        self.text_controls = QWidget()
        lay = vbox(self.text_controls, (0, 0, 0, 0), SP["sm"])

        lay.addWidget(SubHeader("Text"))
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Type your text… (multi-line OK)")
        self.text_edit.setMinimumHeight(64)
        self.text_edit.setMaximumHeight(88)
        self.text_edit.textChanged.connect(self._on_text_edited)
        lay.addWidget(self.text_edit)

        lay.addWidget(SubHeader("Font"))
        self._font_search = QLineEdit()
        self._font_search.setPlaceholderText("Search fonts…")
        self._font_search.setClearButtonEnabled(True)
        self._font_search.textChanged.connect(self._on_font_search)
        self._font_import_btn = IconButton("folder-plus", "Import .ttf / .otf fonts or a ZIP font pack",
                                           on_click=self._import_fonts_dialog)
        srow = hbox(spacing=SP["sm"])
        srow.addWidget(self._font_search, 1)
        srow.addWidget(self._font_import_btn)
        lay.addLayout(srow)

        # Hidden combo must exist BEFORE _populate_font_combo is called
        self.font_combo = QComboBox()
        self.font_combo.setVisible(False)
        self.font_combo.currentTextChanged.connect(self._on_font_changed)

        self._font_list = _FontPreviewList()
        self._font_list.setFixedHeight(192)
        self._font_list.font_selected.connect(self._on_font_list_selected)
        lay.addWidget(self._font_list)
        self._populate_font_combo()   # fills both font_combo and _font_list

        self._font_preview_bar = _FontPreviewBar()
        self._font_preview_bar.setFixedHeight(44)
        lay.addWidget(self._font_preview_bar)

        lay.addWidget(SubHeader("Style"))
        self._size_row = SpinRow("Size", 4, 999, 48)
        self._spacing_row = SpinRow("Spacing", -100, 500, 0)
        self.font_size_input = self._size_row.spin
        self.letter_spacing_input = self._spacing_row.spin
        self.font_size_input.valueChanged.connect(self._on_font_size_changed)
        self.font_size_input.valueChanged.connect(self._update_font_preview)
        self.letter_spacing_input.valueChanged.connect(self._on_letter_spacing_changed)
        lay.addLayout(_row(self._size_row, self._spacing_row, stretch_last=False))

        self.bold_cb   = QCheckBox("Bold")
        self.italic_cb = QCheckBox("Italic")
        self.upper_cb  = QCheckBox("AA")
        self.upper_cb.setToolTip("Uppercase")
        self.bold_cb.stateChanged.connect(lambda v: self._canvas.update_selected_layer(font_bold=bool(v)) if hasattr(self, '_canvas') else None)
        self.bold_cb.stateChanged.connect(self._update_font_preview)
        self.italic_cb.stateChanged.connect(lambda v: self._canvas.update_selected_layer(font_italic=bool(v)) if hasattr(self, '_canvas') else None)
        self.italic_cb.stateChanged.connect(self._update_font_preview)
        self.upper_cb.stateChanged.connect(lambda v: self._canvas.update_selected_layer(font_uppercase=bool(v)) if hasattr(self, '_canvas') else None)
        crow = hbox(spacing=SP["md"])
        for cb in (self.bold_cb, self.italic_cb, self.upper_cb):
            crow.addWidget(cb)
        crow.addStretch()
        lay.addLayout(crow)

        lay.addWidget(SubHeader("Layout"))
        lrow = hbox(spacing=SP["xs"])
        self._align_btns = []
        for icon, tip, val in [("text-align-start", "Align left", "left"),
                               ("text-align-center", "Align centre", "center"),
                               ("text-align-end", "Align right", "right")]:
            b = IconButton(icon, tip, checkable=True)
            b.clicked.connect(lambda _=False, v=val, btn=b: self._on_align_btn(v, btn))
            self._align_btns.append(b)
            lrow.addWidget(b)
        self._align_btns[0].setChecked(True)
        lrow.addSpacing(SP["sm"])
        self.orient_combo = _combo(["horizontal", "rotate90", "rotate270", "vertical"])
        self.orient_combo.setToolTip("Text orientation")
        self.orient_combo.currentTextChanged.connect(
            lambda v: self._canvas.update_selected_layer(text_orientation=v) if hasattr(self, '_canvas') else None)
        lrow.addWidget(self.orient_combo, 1)
        lay.addLayout(lrow)

        lay.addWidget(SubHeader("Colour"))
        self._txt_color_val = QColor(255, 255, 255)
        self._txt_color_swatch = ColorSwatch("#ffffff", "Text colour")
        self._txt_color_swatch.color_changed.connect(lambda h: self._apply_text_color(QColor(h)))
        lay.addLayout(_row(self._txt_color_swatch, label("Text colour", "dim")))

        lay.addWidget(SubHeader("Effects"))
        self.outline_slider = LabeledSlider("Outline", 0, 20, 0, "px")
        self.outline_slider.value_changed.connect(
            lambda v: self._canvas.update_selected_layer(outline_size=int(v)) if hasattr(self, '_canvas') else None)
        lay.addWidget(self.outline_slider)
        self.shadow_slider = LabeledSlider("Shadow", 0, 30, 0, "px")
        self.shadow_slider.value_changed.connect(
            lambda v: self._canvas.update_selected_layer(shadow_offset=int(v)) if hasattr(self, '_canvas') else None)
        lay.addWidget(self.shadow_slider)
        return self.text_controls

    def _build_fill_controls(self) -> QWidget:
        self.fill_controls = QWidget()
        self.fill_controls.setVisible(False)
        fl = vbox(self.fill_controls, (0, 0, 0, 0), SP["sm"])
        fl.addWidget(SubHeader("Fill"))
        self._fill_type_combo = _combo(["solid", "gradient", "pattern"])
        self._fill_type_combo.currentTextChanged.connect(self._on_fill_type_changed)
        fl.addLayout(_row(label("Type", "dim"), self._fill_type_combo))
        self._fill_color_swatch = ColorSwatch("#000000", "Fill colour")
        self._fill_color_swatch.color_changed.connect(lambda h: self._apply_fill_color(1, QColor(h)))
        fl.addLayout(_row(self._fill_color_swatch, label("Colour", "dim")))
        self._fill_color2_swatch = ColorSwatch("#ffffff", "Second gradient colour")
        self._fill_color2_swatch.color_changed.connect(lambda h: self._apply_fill_color(2, QColor(h)))
        fl.addLayout(_row(self._fill_color2_swatch, label("Colour 2 (gradient)", "dim", elide=True)))
        self._fill_angle_slider = LabeledSlider("Angle", 0, 360, 0, "°")
        self._fill_angle_slider.value_changed.connect(self._on_fill_angle)
        fl.addWidget(self._fill_angle_slider)
        return self.fill_controls

    def _build_filter_controls(self) -> QWidget:
        self.filter_controls = QWidget()
        self.filter_controls.setVisible(False)
        flt = vbox(self.filter_controls, (0, 0, 0, 0), SP["sm"])
        flt.addWidget(SubHeader("Filter"))
        self._filter_type_lbl = label("Filter: —", "body", tone="gold", elide=True)
        flt.addWidget(self._filter_type_lbl)
        flt.addWidget(Button("Change filter type…", icon="sliders-horizontal", on_click=self._change_filter_type))
        self._filter_strength = LabeledSlider("Strength", 0, 100, 100, "%")
        self._filter_strength.value_changed.connect(
            lambda v: self._canvas.update_selected_layer(opacity=v / 100.) if hasattr(self, '_canvas') else None)
        flt.addWidget(self._filter_strength)
        return self.filter_controls

    def _build_clone_controls(self) -> QWidget:
        self.clone_controls = QWidget()
        self.clone_controls.setVisible(False)
        cll = vbox(self.clone_controls, (0, 0, 0, 0), SP["sm"])
        cll.addWidget(SubHeader("Clone"))
        self._clone_source_combo = _combo()
        self._clone_source_combo.currentIndexChanged.connect(self._on_clone_source_changed)
        cll.addLayout(_row(label("Source", "dim"), self._clone_source_combo))
        cll.addWidget(label("Clone mirrors its source. Editing the source updates this layer.", "muted", wrap=True))
        return self.clone_controls

    def _build_vector_controls(self) -> QWidget:
        self.vector_controls = QWidget()
        self.vector_controls.setVisible(False)
        vl = vbox(self.vector_controls, (0, 0, 0, 0), SP["sm"])
        vl.addWidget(SubHeader("Vector"))
        self._vec_stroke_swatch = ColorSwatch("#ffffff", "Stroke colour")
        self._vec_stroke_swatch.color_changed.connect(lambda h: self._apply_vector_color("stroke", QColor(h)))
        vl.addLayout(_row(self._vec_stroke_swatch, label("Stroke", "dim")))
        self._vec_fill_swatch = ColorSwatch("#ffffff", "Fill colour")
        self._vec_fill_swatch.color_changed.connect(lambda h: self._apply_vector_color("fill", QColor(h)))
        vl.addLayout(_row(self._vec_fill_swatch, label("Fill", "dim")))
        vl.addWidget(label("Vector drawing tools coming soon.", "muted", wrap=True))
        return self.vector_controls

    def _build_group_controls(self) -> QWidget:
        self.group_controls = QWidget()
        self.group_controls.setVisible(False)
        gl = vbox(self.group_controls, (0, 0, 0, 0), SP["sm"])
        gl.addWidget(label("Group layer — use Move/Resize to reposition child layers together.", "muted", wrap=True))
        return self.group_controls

    def _build_mask_controls(self) -> QWidget:
        self.mask_controls = QWidget()
        self.mask_controls.setVisible(False)
        ml = vbox(self.mask_controls, (0, 0, 0, 0), SP["sm"])
        ml.addWidget(SubHeader("Mask"))
        self._mask_feather_slider = LabeledSlider("Feather (blur)", 0, 50, 0, "px")
        self._mask_feather_slider.value_changed.connect(self._on_mask_feather)
        ml.addWidget(self._mask_feather_slider)
        self._mask_color_swatch = ColorSwatch("#ffffff", "Mask colour")
        self._mask_color_swatch.color_changed.connect(lambda h: self._apply_mask_color(QColor(h)))
        ml.addLayout(_row(self._mask_color_swatch, label("Mask colour", "dim")))
        return self.mask_controls

    # ── FOOTER (pinned) ───────────────────────────────────────────────────────
    def _build_footer(self) -> QWidget:
        footer = QWidget()
        outer = vbox(footer, (0, 0, 0, 0), 0)
        outer.addWidget(Divider())
        inner = QWidget()
        lay = vbox(inner, (SP["md"], SP["md"], SP["md"], SP["md"]), SP["sm"])
        self.export_btn = Button("APPLY TO STEAM", "primary", icon="upload", on_click=self._on_export,
                                 tooltip="Export with the Steam filename and install it into your "
                                         "Steam grid folder  (Ctrl+E)")
        lay.addWidget(self.export_btn)
        self.export_png_btn = Button("Export PNG only", "ghost", icon="download", on_click=self._on_export_png,
                                     tooltip="Save the PNG to the exports folder without touching Steam")
        lay.addWidget(self.export_png_btn)
        outer.addWidget(inner)
        return footer

    _TYPE_CONTROLS = ("img_controls", "text_controls", "fill_controls", "filter_controls",
                      "clone_controls", "vector_controls", "group_controls", "mask_controls")

    def _set_props_mode(self, mode: str):
        """mode: empty · group · locked · edit — shows the matching placeholder / controls."""
        self.props_placeholder.setVisible(mode == "empty")
        self._group_placeholder.setVisible(mode == "group")
        self._locked_placeholder.setVisible(mode == "locked")
        self._unlock_btn.setVisible(mode == "locked")
        self.shared_controls.setVisible(mode == "edit")
        if mode != "edit":
            for attr in self._TYPE_CONTROLS:
                getattr(self, attr).setVisible(False)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _select_template(self, tpl: str):
        st = self._st()
        if st is not None:
            st.current_template = tpl
        self._update_template_buttons()
        # Directly update canvas size + template PNG immediately
        if hasattr(self, '_canvas'):
            self._canvas.set_template(tpl)
        self.template_changed.emit(tpl)

    def _update_template_buttons(self):
        st = self._st()
        tpl = st.current_template if st else "cover"
        for key, b in self._tpl_buttons.items():
            b.set_active(key == tpl)

    def _populate_platform_combo(self):
        """Read actual image files from platformBars folder."""
        self.platform_combo.blockSignals(True)
        self.platform_combo.clear()
        self.platform_combo.addItem("none", userData=None)
        if os.path.isdir(PLATFORM_BARS_DIR):
            for f in sorted(os.listdir(PLATFORM_BARS_DIR)):
                if f.lower().endswith((".png", ".jpg", ".jpeg")):
                    label_ = os.path.splitext(f)[0]
                    full   = os.path.join(PLATFORM_BARS_DIR, f)
                    self.platform_combo.addItem(label_, userData=full)
        self.platform_combo.blockSignals(False)
        self._update_bar_preview()

    def _update_bar_preview(self):
        self.bar_preview.set_source(self.platform_combo.currentData())

    def _on_platform_changed(self, index: int):
        path = self.platform_combo.itemData(index)
        name = self.platform_combo.itemText(index)
        st = self._st()
        if st is not None:
            st.platform_bar_name = name
            st.show_platform_bar = (path is not None)
        self._update_bar_preview()
        self.settings_changed.emit()

    def _add_bar_layer_from_combo(self):
        """Add currently selected platform bar as a canvas layer."""
        if not hasattr(self, '_canvas'):
            return
        path = self.platform_combo.currentData()
        if not path or not os.path.exists(path):
            return
        layer = self._canvas.add_image_layer(path,
            name=self.platform_combo.currentText())
        dw = self._canvas.doc_size().width()
        layer.x, layer.y, layer.w, layer.h = 0, 0, dw, 70
        self._canvas.invalidate_layer_cache(layer)
        self._refresh_layer_list()

    def _populate_det_combo(self):
        """Read texture PNGs from assets/textures/ folder."""
        self.det_combo.blockSignals(True)
        self.det_combo.clear()
        self.det_combo.addItem("none", userData=None)
        seen = set()
        for d in texture_dirs():
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                if f.lower().endswith((".png", ".jpg", ".jpeg")) and f not in seen:
                    seen.add(f)
                    label_ = os.path.splitext(f)[0]
                    self.det_combo.addItem(label_, userData=os.path.join(d, f))
        self.det_combo.blockSignals(False)
        self._update_det_preview()

    def _update_det_preview(self):
        self.det_preview.set_source(self.det_combo.currentData())

    def _on_det_changed(self, index: int):
        self._update_det_preview()

    def _add_det_layer_from_combo(self):
        """Add selected texture as a full-canvas layer."""
        if not hasattr(self, '_canvas'):
            return
        path = self.det_combo.currentData()
        if not path or not os.path.exists(path):
            return
        dw = self._canvas.doc_size().width()
        dh = self._canvas.doc_size().height()
        layer = self._canvas.add_image_layer(path,
            name=self.det_combo.currentText())
        layer.x, layer.y, layer.w, layer.h = 0, 0, dw, dh
        layer.opacity  = 0.6
        layer.blend_mode = "overlay"
        self._canvas.invalidate_layer_cache(layer)
        self._refresh_layer_list()

    # ── Ratings ─────────────────────────────────────────────────────────────────

    def _populate_ratings_combo(self):
        self.ratings_combo.blockSignals(True)
        self.ratings_combo.clear()
        self.ratings_combo.addItem("none", userData=None)
        if os.path.isdir(RATINGS_DIR):
            for f in sorted(os.listdir(RATINGS_DIR)):
                if f.lower().endswith((".png", ".jpg", ".jpeg")):
                    label_ = os.path.splitext(f)[0]
                    self.ratings_combo.addItem(label_, userData=os.path.join(RATINGS_DIR, f))
        self.ratings_combo.blockSignals(False)
        self._update_ratings_preview()

    def _update_ratings_preview(self):
        self.ratings_preview.set_source(self.ratings_combo.currentData())

    def _on_rating_changed(self, _):
        self._update_ratings_preview()

    def _add_rating_layer_from_combo(self):
        if not hasattr(self, '_canvas'):
            return
        path = self.ratings_combo.currentData()
        if not path or not os.path.exists(path):
            return
        from PIL import Image as PILImage
        img = PILImage.open(path).convert("RGBA")
        # Place bottom-right corner, natural size capped at 200px wide
        dw = self._canvas.doc_size().width()
        dh = self._canvas.doc_size().height()
        w = min(img.width, 200)
        h = int(img.height * w / img.width)
        from app.ui.canvas.layers import Layer
        layer = Layer(kind="image",
                      name=self.ratings_combo.currentText(),
                      x=dw - w - 10, y=dh - h - 10,
                      w=w, h=h, pil_image=img)
        self._canvas.add_layer(layer)
        self._refresh_layer_list()

    # ── Background / document FX ────────────────────────────────────────────────

    def _pick_bg_color(self):
        color = QColorDialog.getColor(self._current_bg_color, self, "Background Color")
        if color.isValid():
            self._apply_bg_color(color)

    def _apply_bg_color(self, color: QColor):
        self._current_bg_color = color
        self.bg_swatch.set_color(color.name())
        # Update tab-local state
        st = self._st()
        if st is not None:
            st.bg_color = (color.red(), color.green(), color.blue())
        # Update canvas preview immediately
        if hasattr(self, '_canvas'):
            self._canvas.set_background_color(color)
        # Trigger recompose
        self.settings_changed.emit()

    def _on_grain(self, v: float):
        st = self._st()
        if st is not None:
            st.film_grain = v
        self._apply_document_fx_to_canvas()
        # Grain is a canvas post-processing effect — no recompose needed.

    def _on_ca(self, v: float):
        st = self._st()
        if st is not None:
            st.chromatic_aberration = v
        self._apply_document_fx_to_canvas()

    def _apply_document_fx_to_canvas(self):
        """Push the current tab's FX settings (grain + CA) to the canvas —
        debounced, because every tick means a full-window numpy pass."""
        if not hasattr(self, '_canvas'):
            return
        if not hasattr(self, "_fx_timer"):
            from PySide6.QtCore import QTimer
            self._fx_timer = QTimer(self)
            self._fx_timer.setSingleShot(True)
            self._fx_timer.setInterval(60)
            self._fx_timer.timeout.connect(self._flush_document_fx)
        self._fx_timer.start()

    def _flush_document_fx(self):
        if not hasattr(self, '_canvas') or self._canvas is None:
            return
        st = self._st()
        grain = st.film_grain if st is not None else 0.0
        ca    = st.chromatic_aberration if st is not None else 0.0
        self._canvas.update_effects_overlay(grain, ca)

    def _on_export(self):
        from PySide6.QtWidgets import QApplication
        # Same behaviour as File → Export: confirm AppID once, save with the
        # Steam filename and apply to Steam.
        for widget in QApplication.topLevelWidgets():
            if hasattr(widget, "_export"):
                widget._export()
                return
        self._on_export_png()

    def _on_export_png(self):
        """Save the PNG (Steam filename, exports folder) without applying."""
        from PySide6.QtWidgets import QMessageBox
        tab = getattr(self, '_tab_ref', None)
        if tab is not None:
            path = tab.export(parent_widget=self)
        elif hasattr(self, '_canvas') and self._canvas is not None:
            # fallback: no tab ref, use exportFlow directly with a minimal stub
            from app.services.exportFlow import run_export_flow
            # build minimal tab-like object
            class _Stub:
                pass
            stub = _Stub()
            stub.preview_canvas = self._canvas
            stub.state = getattr(self, '_tab_state', None)
            if stub.state is None:
                QMessageBox.warning(self, "Export", "No canvas state available.")
                return
            path = run_export_flow(stub, parent_widget=self)
        else:
            QMessageBox.warning(self, "Export", "No canvas available.")
            return
        if path:
            tab = getattr(self, '_tab_ref', None)
            if tab is not None:
                tab.status_changed.emit(f"Saved PNG: {path}")
            else:
                QMessageBox.information(self, "Exported", f"Saved:\n{path}")

    def refresh_from_state(self):
        """Sync all document-level controls from the current tab state.
        Called when the canvas/tab is first attached and after project load."""
        st = self._st()
        if st is None:
            return
        # set_value() is silent, so this bulk sync doesn't cascade
        for sl, attr in [
            (self.grain_slider,     'film_grain'),
            (self.ca_slider,        'chromatic_aberration'),
        ]:
            sl.set_value(getattr(st, attr, sl.value()))

        # Sync template button highlight
        self._update_template_buttons()

        # Sync background colour swatch
        bg = getattr(st, 'bg_color', (0, 0, 0))
        q = QColor(*bg) if bg else QColor(0, 0, 0)
        self._current_bg_color = q
        self.bg_swatch.set_color(q.name())

    # ── Layer management (called by canvas signal) ─────────────────────────────

    def set_canvas(self, canvas, tab_state=None, tab_ref=None):
        """Store reference to the PreviewCanvas and the owning tab.

        tab_state : the WorkspaceTab's AppState instance — becomes the single
                    source of truth for all document-level settings in this panel.
        tab_ref   : the WorkspaceTab itself (used for export flow)

        After connecting, refresh_from_state() is called so all document-level
        controls immediately reflect the tab's state instead of stale defaults.
        """
        self._canvas = canvas
        if tab_state is not None:
            self._tab_state = tab_state
        if tab_ref is not None:
            self._tab_ref = tab_ref
        canvas.layer_selected.connect(self._on_canvas_layer_selected)
        canvas.layers_changed.connect(self._refresh_layer_list)
        # Populate document-level controls from the tab state right away.
        # This ensures the panel reflects the correct document when a new tab
        # is opened or when the panel is reused after a tab switch.
        self.refresh_from_state()

    def _refresh_layer_list(self):
        """Rebuild the layer list, respecting group hierarchy and collapse state."""
        if not hasattr(self, '_canvas'):
            return
        self.layer_list.blockSignals(True)
        self.layer_list.clear()

        # Build a flat display list from the canvas layer stack (reversed: top first).
        # Each entry: (layer, canvas_idx, indent_level)
        display = []
        layers  = self._canvas.layers
        n       = len(layers)

        # Track which group layers are collapsed so we can hide their children.
        # groups_collapsed maps canvas_idx → bool
        groups_collapsed = {}
        for i, layer in enumerate(layers):
            if layer.kind == "group":
                groups_collapsed[i] = getattr(layer, 'group_collapsed', False)

        # Walk reversed (top-of-stack first)
        for canvas_idx in range(n - 1, -1, -1):
            layer = layers[canvas_idx]
            parent_idx = getattr(layer, '_group_parent', None)

            # Determine indent level (children of a group are indented)
            indent = 1 if parent_idx is not None else 0

            # If the parent group is collapsed, skip this child
            if parent_idx is not None and groups_collapsed.get(parent_idx, False):
                continue

            display.append((layer, canvas_idx, indent))

        for layer, canvas_idx, indent in display:
            # Effective lock = own lock OR parent group is locked
            parent_idx  = getattr(layer, '_group_parent', None)
            parent_locked = False
            if parent_idx is not None and 0 <= parent_idx < len(layers):
                parent_locked = getattr(layers[parent_idx], 'locked', False)
            effectively_locked = getattr(layer, 'locked', False) or parent_locked

            item = QListWidgetItem(layer.name)
            item.setData(LayerDelegate.EYE_ROLE,       layer.visible)
            item.setData(LayerDelegate.KIND_ROLE,       layer.kind)
            item.setData(LayerDelegate.OPAC_ROLE,       layer.opacity)
            item.setData(LayerDelegate.LOCK_ROLE,       effectively_locked)
            item.setData(LayerDelegate.INDENT_ROLE,     indent)
            item.setData(LayerDelegate.COLLAPSED_ROLE,  getattr(layer, 'group_collapsed', False))
            item.setData(LayerDelegate.DROP_ABOVE,      False)
            item.setData(LayerDelegate.DROP_INTO,       False)
            # Store canvas_idx so we can reverse-map without arithmetic
            item.setData(Qt.ItemDataRole.UserRole + 20, canvas_idx)
            thumb = self._make_layer_thumb(layer)
            item.setData(LayerDelegate.PIX_ROLE, thumb)
            self.layer_list.addItem(item)

        # Highlight current selection
        sel_canvas = self._canvas.selected_layer_index()
        for row in range(self.layer_list.count()):
            it = self.layer_list.item(row)
            if it and it.data(Qt.ItemDataRole.UserRole + 20) == sel_canvas:
                self.layer_list.setCurrentRow(row)
                break

        self.layer_list.blockSignals(False)

    def _sync_layer_list_selection(self, canvas_idx: int):
        """Highlight the row matching canvas_idx without rebuilding."""
        self.layer_list.blockSignals(True)
        for row in range(self.layer_list.count()):
            it = self.layer_list.item(row)
            if it and it.data(Qt.ItemDataRole.UserRole + 20) == canvas_idx:
                self.layer_list.setCurrentRow(row)
                break
        self.layer_list.blockSignals(False)

    def _make_layer_thumb(self, layer) -> QPixmap:
        return LayerDelegate.make_thumb(layer)

    def _on_layer_list_clicked(self, index):
        """Handle eye toggle and group collapse arrow on click."""
        item = self.layer_list.itemFromIndex(index)
        if not item:
            return
        canvas_idx = item.data(Qt.ItemDataRole.UserRole + 20)
        if canvas_idx is None or not hasattr(self, '_canvas'):
            return
        indent = int(item.data(LayerDelegate.INDENT_ROLE) or 0)
        kind   = (item.data(LayerDelegate.KIND_ROLE) or "").lower()

        row_rect  = self.layer_list.visualRect(index)
        click_pos = self.layer_list.mapFromGlobal(self.layer_list.cursor().pos())

        # Eye icon hit test
        eye_r = self._layer_delegate.eye_rect_for_row(row_rect, indent)
        if eye_r.contains(click_pos):
            if 0 <= canvas_idx < len(self._canvas.layers):
                cur_vis = self._canvas.layers[canvas_idx].visible
                self._canvas.set_layer_visibility(canvas_idx, not cur_vis)
                self._refresh_layer_list()
            return

        # Collapse arrow hit test (groups only)
        if kind == "group":
            arrow_r = self._layer_delegate.arrow_rect_for_row(row_rect, indent)
            if arrow_r.contains(click_pos):
                if 0 <= canvas_idx < len(self._canvas.layers):
                    l = self._canvas.layers[canvas_idx]
                    l.group_collapsed = not getattr(l, 'group_collapsed', False)
                    self._refresh_layer_list()
                return

    def _on_layer_list_select(self, list_row: int):
        """Translate list row → canvas index and select on canvas."""
        if not hasattr(self, '_canvas') or list_row < 0:
            return
        item = self.layer_list.item(list_row)
        if not item:
            return
        canvas_idx = item.data(Qt.ItemDataRole.UserRole + 20)
        if canvas_idx is None:
            return
        if 0 <= canvas_idx < len(self._canvas.layers):
            self._canvas.select_layer(canvas_idx)

    def _on_rows_moved(self, parent, src_start, src_end, dest_parent, dest_row):
        """Called after QListWidget drag-drop reorder completes.
        Delegates to canvas.reorder_layers() — never mutates _layers or _sel directly."""
        if not hasattr(self, '_canvas'):
            return

        count = self.layer_list.count()
        new_order_canvas_indices = []
        for row in range(count):
            it = self.layer_list.item(row)
            if it:
                new_order_canvas_indices.append(it.data(Qt.ItemDataRole.UserRole + 20))

        # List row 0 = highest layer; canvas._layers[0] = lowest → reverse
        new_canvas_order = list(reversed(new_order_canvas_indices))
        old_layers = list(self._canvas.layers)
        new_layers = [old_layers[i] for i in new_canvas_order
                      if 0 <= i < len(old_layers)]

        # Assign group parent from list adjacency (operates on Layer objects
        # before handing them to canvas, so this is pure data prep, not a mutation
        # of canvas internals)
        for row in range(count):
            it = self.layer_list.item(row)
            if not it:
                continue
            ci = it.data(Qt.ItemDataRole.UserRole + 20)
            if not (0 <= ci < len(old_layers)):
                continue
            layer = old_layers[ci]
            parent_group_ci = None
            for above_row in range(row - 1, -1, -1):
                above_it = self.layer_list.item(above_row)
                if above_it:
                    above_kind = (above_it.data(LayerDelegate.KIND_ROLE) or "").lower()
                    if above_kind == "group":
                        parent_group_ci = above_it.data(Qt.ItemDataRole.UserRole + 20)
                        break
                    else:
                        break
            layer._group_parent = parent_group_ci  # type: ignore[attr-defined]

        # Delegate to canvas authority — pushes undo, updates _sel, emits signals
        self._canvas.reorder_layers(new_layers)
        self._refresh_layer_list()

    def _on_canvas_layer_selected(self, idx: int):
        """Called when canvas emits layer_selected. Syncs panel controls to the selected layer."""
        self._sync_layer_list_selection(idx)

        if not hasattr(self, '_canvas') or idx < 0 or idx >= len(self._canvas.layers):
            self._set_props_mode("empty")
            return

        layer = self._canvas.layers[idx]

        # Check effective lock (own OR parent group)
        parent_idx    = getattr(layer, '_group_parent', None)
        parent_locked = False
        if parent_idx is not None and 0 <= parent_idx < len(self._canvas.layers):
            parent_locked = getattr(self._canvas.layers[parent_idx], 'locked', False)
        effectively_locked = getattr(layer, 'locked', False) or parent_locked

        # Group layers: show a minimal placeholder — they have no canvas body to edit
        if layer.kind == "group":
            self._group_placeholder.title.setText(layer.name)
            self._set_props_mode("group")
            return

        # Locked layers: notice + unlock button, hide edit controls
        if effectively_locked:
            self._set_props_mode("locked")
            return

        self._set_props_mode("edit")

        # Determine which controls to show
        is_paint  = layer.kind in ("paint", "image", "texture", "file")
        is_text   = layer.kind == "text"
        is_fill   = layer.kind == "fill"
        is_filter = layer.kind == "filter"
        is_clone  = layer.kind == "clone"
        is_vector = layer.kind == "vector"
        is_mask   = layer.kind.startswith("mask_")

        self.img_controls.setVisible(is_paint)
        self.text_controls.setVisible(is_text)
        for attr, flag in [
            ("fill_controls",   is_fill),
            ("filter_controls", is_filter),
            ("clone_controls",  is_clone),
            ("vector_controls", is_vector),
            ("group_controls",  False),    # group_controls never shown for non-groups
            ("mask_controls",   is_mask),
        ]:
            if hasattr(self, attr):
                getattr(self, attr).setVisible(flag)

        # Sync shared controls
        self.opacity_slider.set_value(int(layer.opacity * 100))

        idx_blend = self.blend_combo.findText(layer.blend_mode)
        self.blend_combo.blockSignals(True)
        self.blend_combo.setCurrentIndex(max(0, idx_blend))
        self.blend_combo.blockSignals(False)

        # Sync layers-panel top bar (blend + opacity)
        if hasattr(self, '_layer_blend_top'):
            self._layer_blend_top.blockSignals(True)
            bi = self._layer_blend_top.findText(layer.blend_mode)
            self._layer_blend_top.setCurrentIndex(max(0, bi))
            self._layer_blend_top.blockSignals(False)
        if hasattr(self, '_layer_opac_slider'):
            self._layer_opac_slider.set_value(int(layer.opacity * 100))

        if is_paint:
            self.rotation_slider.set_value(int(layer.rotation))
            self.layer_bright.set_value(int(layer.brightness))
            self.layer_contrast.set_value(int(layer.contrast))
            self.layer_sat.set_value(int(layer.saturation))
            if layer.tint_color:
                tr, tg, tb = layer.tint_color
                c = QColor(tr, tg, tb)
                self._current_tint = c
                self.tint_preview.set_color(c.name())
            self.tint_strength_slider.set_value(int(layer.tint_strength * 100))

        if is_text:
            if self.text_edit.toPlainText() != layer.text:
                self.text_edit.blockSignals(True)
                self.text_edit.setPlainText(layer.text)
                self.text_edit.blockSignals(False)
            self.font_size_input.blockSignals(True)
            self.font_size_input.setValue(int(layer.font_size))
            self.font_size_input.blockSignals(False)
            self.letter_spacing_input.blockSignals(True)
            self.letter_spacing_input.setValue(int(layer.letter_spacing))
            self.letter_spacing_input.blockSignals(False)
            for cb, attr in [(self.bold_cb, "font_bold"),
                             (self.italic_cb, "font_italic"),
                             (self.upper_cb,  "font_uppercase")]:
                cb.blockSignals(True)
                cb.setChecked(getattr(layer, attr))
                cb.blockSignals(False)
            for btn, val in zip(self._align_btns, ("left", "center", "right")):
                btn.setChecked(val == getattr(layer, "text_align", "left"))
            oi = self.orient_combo.findText(layer.text_orientation)
            self.orient_combo.blockSignals(True)
            self.orient_combo.setCurrentIndex(max(0, oi))
            self.orient_combo.blockSignals(False)
            fc = getattr(layer, "font_color", None)
            if fc:
                self._txt_color_val = QColor(*fc[:3])
                self._txt_color_swatch.set_color(self._txt_color_val.name())
            self.outline_slider.set_value(layer.outline_size)
            self.shadow_slider.set_value(layer.shadow_offset)
            self._update_font_preview()

        if is_fill and hasattr(self, '_fill_type_combo'):
            self._fill_type_combo.blockSignals(True)
            self._fill_type_combo.setCurrentText(layer.fill_type)
            self._fill_type_combo.blockSignals(False)
            self._fill_color_swatch.set_color(QColor(*layer.fill_color[:3]).name())
            self._fill_color2_swatch.set_color(QColor(*layer.fill_color2[:3]).name())
            self._fill_angle_slider.set_value(int(layer.fill_angle))

        if is_filter and hasattr(self, '_filter_type_lbl'):
            self._filter_type_lbl.setText(f"Filter: {layer.filter_type or '—'}")

        if is_clone and hasattr(self, '_clone_source_combo'):
            self._clone_source_combo.blockSignals(True)
            self._clone_source_combo.clear()
            for ci, cl in enumerate(self._canvas.layers):
                if cl is not layer:
                    self._clone_source_combo.addItem(f"[{ci}] {cl.name}", ci)
            sel_i = self._clone_source_combo.findData(layer.clone_source_idx)
            self._clone_source_combo.setCurrentIndex(max(0, sel_i))
            self._clone_source_combo.blockSignals(False)

        if is_mask and hasattr(self, '_mask_feather_slider'):
            self._mask_feather_slider.set_value(int(layer.mask_feather))

        if is_vector and hasattr(self, '_vec_stroke_swatch'):
            self._vec_stroke_swatch.set_color(QColor(*layer.vector_stroke[:3]).name())
            self._vec_fill_swatch.set_color(QColor(*layer.vector_fill[:3]).name())

    # ── New layer action slots ─────────────────────────────────────────────────

    def _duplicate_layer(self):
        """Duplicate the selected layer via the safe canvas authority method."""
        if not hasattr(self, '_canvas') or self._canvas is None:
            return
        new_layer = self._canvas.duplicate_selected_layer(offset=20)
        if new_layer is not None:
            self._refresh_layer_list()

    def _rename_layer(self):
        if not hasattr(self, '_canvas'): return
        layer = self._canvas.selected_layer()
        if not layer: return
        name, ok = QInputDialog.getText(self, "Rename Layer", "Name:", text=layer.name)
        if ok and name.strip():
            layer.name = name.strip()
            self._refresh_layer_list()

    def _on_layer_double_clicked(self, index):
        """Double-clicking a layer row opens an inline rename dialog."""
        if not hasattr(self, '_canvas'): return
        count = self.layer_list.count()
        canvas_idx = (count - 1) - index.row()
        if 0 <= canvas_idx < len(self._canvas.layers):
            layer = self._canvas.layers[canvas_idx]
            name, ok = QInputDialog.getText(
                self, "Rename Layer", "Layer name:", text=layer.name)
            if ok and name.strip():
                layer.name = name.strip()
                self._refresh_layer_list()

    # ── Text / font panel helpers ─────────────────────────────────────────────

    def _on_text_edited(self):
        """Live text edit → layer (one undo step per typing burst)."""
        if not hasattr(self, '_canvas') or self._canvas is None:
            return
        l = self._canvas.selected_layer()
        if l is None or l.kind != "text":
            return
        text = self.text_edit.toPlainText()
        self._canvas.update_selected_layer(text=text, name=f"T: {text[:12]}")

    def _on_font_search(self, text: str):
        """Filter font list in real time."""
        self._font_list.apply_filter(text)

    def _on_font_list_selected(self, display: str, userdata: str):
        """User clicked / keyboarded to a font in the list."""
        # Sync hidden combo (triggers _on_font_changed → canvas update)
        idx = self.font_combo.findData(userdata)
        if idx < 0:
            idx = self.font_combo.findText(display)
        if idx >= 0:
            self.font_combo.blockSignals(False)
            self.font_combo.setCurrentIndex(idx)
        self._update_font_preview()

    def _on_align_btn(self, val: str, clicked_btn):
        """Exclusive alignment button logic."""
        for btn in self._align_btns:
            btn.setChecked(btn is clicked_btn)
        if hasattr(self, '_canvas'):
            self._canvas.update_selected_layer(text_align=val)

    def _update_font_preview(self, *_):
        """Refresh the live preview bar from current UI state."""
        if not hasattr(self, '_font_preview_bar'):
            return
        try:
            sel_display, sel_userdata = self._font_list.selected()
            fam = sel_display or theme.FONT
            if sel_userdata:
                fid  = QFontDatabase.addApplicationFont(font_path(sel_userdata))
                fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                if fams:
                    fam = fams[0]
            sz = int(self.font_size_input.value() or 16)
        except Exception:
            fam, sz = theme.FONT, 16
        self._font_preview_bar.update_preview(
            font_fam=fam, size=min(sz, 26),
            bold=self.bold_cb.isChecked(),
            italic=self.italic_cb.isChecked(),
            color=getattr(self, '_txt_color_val', QColor(C["text"])),
        )

    def _toggle_layer_lock(self):
        """Lock or unlock the selected layer.
        If it is a group, all children inherit the new locked state."""
        if not hasattr(self, '_canvas'): return
        layer = self._canvas.selected_layer()
        if not layer: return

        new_locked = not getattr(layer, 'locked', False)
        layer.locked = new_locked

        # Propagate to children if this is a group
        if layer.kind == "group":
            sel_idx = self._canvas.selected_layer_index()
            for child in self._canvas.layers:
                if getattr(child, '_group_parent', None) == sel_idx:
                    child.locked = new_locked

        self._refresh_layer_list()
        self._canvas.update()

    # ── Image layer slots ──────────────────────────────────────────────────────

    def _on_opacity(self, v: float):
        if hasattr(self, '_canvas'):
            self._canvas.update_selected_layer(opacity=v / 100.0)
        # Sync layers-panel top bar
        if hasattr(self, '_layer_opac_slider'):
            self._layer_opac_slider.set_value(int(v))

    def _on_blend_top_changed(self, mode: str):
        """Blend mode changed from the layers-panel top bar."""
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if not l: return
        self._canvas.update_selected_layer(blend_mode=mode)
        if hasattr(self, 'blend_combo'):
            idx = self.blend_combo.findText(mode)
            if idx >= 0:
                self.blend_combo.blockSignals(True)
                self.blend_combo.setCurrentIndex(idx)
                self.blend_combo.blockSignals(False)

    def _on_layer_opac_top(self, v: int):
        """Opacity slider in the layers-panel top bar."""
        if not hasattr(self, '_canvas'): return
        self._canvas.update_selected_layer(opacity=v / 100.0)
        if hasattr(self, 'opacity_slider'):
            self.opacity_slider.set_value(v)

    def _flip_horizontal(self):
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if l: self._canvas.update_selected_layer(flip_h=not l.flip_h)

    def _flip_vertical(self):
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if l: self._canvas.update_selected_layer(flip_v=not l.flip_v)

    def _fit_canvas(self):
        """Scale layer to fit inside canvas maintaining aspect ratio."""
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if not l or not l.pil_image: return
        dw, dh = self._canvas.doc_size().width(), self._canvas.doc_size().height()
        iw, ih = l.pil_image.size
        scale = min(dw / iw, dh / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        self._canvas.update_selected_layer(x=(dw-nw)//2, y=(dh-nh)//2, w=nw, h=nh)

    def _fill_canvas(self):
        """Scale layer to fill canvas (may crop)."""
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if not l or not l.pil_image: return
        dw, dh = self._canvas.doc_size().width(), self._canvas.doc_size().height()
        iw, ih = l.pil_image.size
        scale = max(dw / iw, dh / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        self._canvas.update_selected_layer(x=(dw-nw)//2, y=(dh-nh)//2, w=nw, h=nh)

    def _center_layer(self):
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if not l: return
        dw, dh = self._canvas.doc_size().width(), self._canvas.doc_size().height()
        self._canvas.update_selected_layer(x=(dw-l.w)//2, y=(dh-l.h)//2)

    def _layer_color_changed(self, prop: str, v: float):
        if hasattr(self, '_canvas'):
            self._canvas.update_selected_layer(**{prop: v})

    def _pick_tint_color(self):
        color = QColorDialog.getColor(self._current_tint, self, "Pick Tint Color")
        if color.isValid():
            self._apply_tint_color(color)

    def _apply_tint_color(self, color: QColor):
        self._current_tint = color
        self.tint_preview.set_color(color.name())
        if hasattr(self, '_canvas'):
            self._canvas.update_selected_layer(
                tint_color=(color.red(), color.green(), color.blue()))

    def _on_tint_strength(self, v: float):
        if hasattr(self, '_canvas'):
            self._canvas.update_selected_layer(tint_strength=v / 100.0)

    # ── Text layer slots ───────────────────────────────────────────────────────

    def _on_letter_spacing_changed(self, v):
        try:
            v = int(v)
            if hasattr(self, '_canvas'):
                self._canvas.update_selected_layer(letter_spacing=v)
        except (ValueError, TypeError):
            pass

    def _add_bar_layer(self):
        """Pick a platform bar from assets/platformBars/"""
        if not hasattr(self, '_canvas'):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Platform Bar", PLATFORM_BARS_DIR,
            "Images (*.png *.jpg *.jpeg)")
        if path:
            layer = self._canvas.add_image_layer(path,
                name=os.path.splitext(os.path.basename(path))[0])
            # Auto-snap to top of canvas, full width
            dw = self._canvas.doc_size().width()
            layer.x = 0
            layer.y = 0
            layer.w = dw
            layer.h = 70
            self._canvas.invalidate_layer_cache(layer)
            self._refresh_layer_list()

    def _add_texture_layer(self):
        """Pick a grunge texture from assets/textures/"""
        if not hasattr(self, '_canvas'):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Texture", str(USER_TEXTURES_DIR),
            "Images (*.png *.jpg *.jpeg)")
        if path:
            dw = self._canvas.doc_size().width()
            dh = self._canvas.doc_size().height()
            layer = self._canvas.add_image_layer(path,
                name=os.path.splitext(os.path.basename(path))[0])
            # Full-canvas texture
            layer.x, layer.y, layer.w, layer.h = 0, 0, dw, dh
            layer.opacity = 0.5
            self._canvas.invalidate_layer_cache(layer)
            self._refresh_layer_list()

    # ── Layer creation actions ─────────────────────────────────────────────────

    def _add_paint_layer(self):
        """Create a blank transparent paint layer immediately — no file picker."""
        if not hasattr(self, '_canvas'): return
        from app.ui.canvas.layers import Layer
        from PIL import Image as PILImage
        dw = self._canvas.doc_size().width()
        dh = self._canvas.doc_size().height()
        img = PILImage.new("RGBA", (dw, dh), (0, 0, 0, 0))
        # Count existing paint layers to auto-name
        n = sum(1 for l in self._canvas.layers if l.kind == "paint")
        layer = Layer(kind="paint", name=f"Paint {n+1}",
                      x=0, y=0, w=dw, h=dh, pil_image=img)
        self._canvas.add_layer(layer)
        self._refresh_layer_list()

    def _add_group_layer(self):
        """Create an empty group folder immediately — no dialog."""
        if not hasattr(self, '_canvas'): return
        from app.ui.canvas.layers import Layer
        dw = self._canvas.doc_size().width()
        dh = self._canvas.doc_size().height()
        n = sum(1 for l in self._canvas.layers if l.kind == "group")
        layer = Layer(kind="group", name=f"Group {n+1}",
                      x=0, y=0, w=dw, h=dh)
        layer.group_collapsed = False          # type: ignore[attr-defined]
        self._canvas.add_layer(layer)
        self._refresh_layer_list()

    def _add_fill_layer(self):
        """Create a fill layer. Shows a color picker then creates immediately."""
        if not hasattr(self, '_canvas'): return
        from app.ui.canvas.layers import Layer
        col = QColorDialog.getColor(QColor(60, 60, 200), self, "Pick Fill Color")
        if not col.isValid(): return
        dw = self._canvas.doc_size().width()
        dh = self._canvas.doc_size().height()
        rgb = (col.red(), col.green(), col.blue())
        n = sum(1 for l in self._canvas.layers if l.kind == "fill")
        layer = Layer(kind="fill", name=f"Fill {n+1} ({col.name()})",
                      x=0, y=0, w=dw, h=dh,
                      fill_type="solid", fill_color=rgb, fill_color2=rgb)
        self._canvas.add_layer(layer)
        self._refresh_layer_list()

    def _import_file_layer(self):
        """Import an image file as a layer (file picker — explicit import action)."""
        if not hasattr(self, '_canvas'): return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path: return
        layer = self._canvas.add_image_layer(
            path, name=os.path.splitext(os.path.basename(path))[0])
        layer.kind = "paint"   # treat imported file as a regular paint layer
        self._refresh_layer_list()

    # ── Kept helpers for Quick Add items ──────────────────────────────────────

    def _add_text_layer(self):
        if not hasattr(self, '_canvas'): return
        text, ok = QInputDialog.getText(self, "Add Text", "Enter text:")
        if ok and text.strip():
            self._canvas.add_text_layer(text.strip())
            self._refresh_layer_list()

    def _add_image_layer(self):
        """Legacy — calls import file layer."""
        self._import_file_layer()

    # ── Removed layer types (kept as stubs so old references don't crash) ────
    def _add_clone_layer(self):      pass
    def _add_vector_layer(self):     pass
    def _add_filter_layer(self):     pass
    def _add_file_layer(self):       self._import_file_layer()
    def _add_transparency_mask(self): pass
    def _add_filter_mask(self):      pass
    def _add_colorize_mask(self):    pass
    def _add_transform_mask(self):   pass
    def _add_local_selection(self):  pass

    # ── Specialized properties slots ─────────────────────────────────────────

    def _on_fill_type_changed(self, ft: str):
        if not hasattr(self, '_canvas'): return
        self._canvas.update_selected_layer(fill_type=ft)

    def _on_fill_angle(self, v: float):
        if not hasattr(self, '_canvas'): return
        self._canvas.update_selected_layer(fill_angle=float(v))

    def _pick_fill_color(self, which: int):
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if not l: return
        init = QColor(*l.fill_color) if which == 1 else QColor(*l.fill_color2)
        col = QColorDialog.getColor(init, self)
        if col.isValid():
            self._apply_fill_color(which, col)

    def _apply_fill_color(self, which: int, col: QColor):
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if not l: return
        rgb = (col.red(), col.green(), col.blue())
        if which == 1:
            self._canvas.update_selected_layer(fill_color=rgb)
            self._fill_color_swatch.set_color(col.name())
        else:
            self._canvas.update_selected_layer(fill_color2=rgb)
            self._fill_color2_swatch.set_color(col.name())
        # Rebuild the fill pil_image
        self._rebuild_fill_image(l)

    def _rebuild_fill_image(self, layer):
        """Re-render a fill layer's pil_image from its fill_type/color settings."""
        from PIL import Image as PILImage
        import math
        w, h = layer.w or 100, layer.h or 100
        if layer.fill_type == "gradient":
            import numpy as np
            c1 = np.array(layer.fill_color[:3], dtype=np.float32)
            c2 = np.array(layer.fill_color2[:3], dtype=np.float32)
            angle = math.radians(layer.fill_angle)
            xs = np.arange(w, dtype=np.float32)[None, :]
            ys = np.arange(h, dtype=np.float32)[:, None]
            t  = np.clip((xs * math.cos(angle) + ys * math.sin(angle)) / max(1, w), 0.0, 1.0)
            rgb = c1[None, None, :] + (c2 - c1)[None, None, :] * t[:, :, None]
            arr = np.empty((h, w, 4), dtype=np.uint8)
            arr[:, :, :3] = rgb.round().astype(np.uint8)
            arr[:, :, 3]  = 255
            img = PILImage.fromarray(arr, "RGBA")
        else:
            img = PILImage.new("RGBA", (w, h), (*layer.fill_color, 255))
        layer.pil_image = img
        self._canvas.invalidate_layer_cache(layer)

    def _change_filter_type(self):
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if not l: return
        items = ["Brightness/Contrast","Hue/Saturation","Color Balance",
                 "Levels","Curves","Invert","Desaturate","Blur","Sharpen"]
        choice, ok = QInputDialog.getItem(self, "Change Filter", "Filter type:", items, 0, False)
        if ok:
            self._canvas.update_selected_layer(filter_type=choice)
            l.name = f"Filter: {choice}"
            self._filter_type_lbl.setText(f"Filter: {choice}")
            self._refresh_layer_list()

    def _on_clone_source_changed(self, _):
        if not hasattr(self, '_canvas'): return
        idx = self._clone_source_combo.currentData()
        if idx is not None:
            self._canvas.update_selected_layer(clone_source_idx=int(idx))

    def _on_mask_feather(self, v: float):
        if not hasattr(self, '_canvas'): return
        self._canvas.update_selected_layer(mask_feather=float(v))

    def _pick_mask_color(self):
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if not l: return
        col = QColorDialog.getColor(QColor(*l.mask_color), self)
        if col.isValid():
            self._apply_mask_color(col)

    def _apply_mask_color(self, col: QColor):
        if not hasattr(self, '_canvas'): return
        rgb = (col.red(), col.green(), col.blue())
        self._canvas.update_selected_layer(mask_color=rgb)
        self._mask_color_swatch.set_color(col.name())

    def _pick_vector_color(self, which: str):
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if not l: return
        init = QColor(*(l.vector_stroke if which == "stroke" else l.vector_fill))
        col = QColorDialog.getColor(init, self)
        if col.isValid():
            self._apply_vector_color(which, col)

    def _apply_vector_color(self, which: str, col: QColor):
        if not hasattr(self, '_canvas'): return
        rgb = (col.red(), col.green(), col.blue())
        if which == "stroke":
            self._canvas.update_selected_layer(vector_stroke=rgb)
            self._vec_stroke_swatch.set_color(col.name())
        else:
            self._canvas.update_selected_layer(vector_fill=rgb)
            self._vec_fill_swatch.set_color(col.name())

    def _delete_selected_layer(self):
        if hasattr(self, '_canvas'):
            self._canvas.remove_layer(self._canvas.selected_layer_index())
            self._refresh_layer_list()

    def _move_layer_up(self):
        if hasattr(self, '_canvas'):
            self._canvas.move_layer_up(self._canvas.selected_layer_index())
            self._refresh_layer_list()

    def _move_layer_down(self):
        if hasattr(self, '_canvas'):
            self._canvas.move_layer_down(self._canvas.selected_layer_index())
            self._refresh_layer_list()

    def _toggle_layer_visibility(self):
        if not hasattr(self, '_canvas'):
            return
        layer = self._canvas.selected_layer()
        if layer:
            layer.visible = not layer.visible
            self._canvas.update()
            self._refresh_layer_list()

    # ── Text layer controls ────────────────────────────────────────────────────

    def _import_fonts_dialog(self):
        """Open file dialog → import fonts → refresh combo."""
        from PySide6.QtWidgets import QMessageBox
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Fonts",
            os.path.expanduser("~"),
            "Fonts & Packs (*.zip *.ttf *.otf *.woff *.woff2);;"
            "ZIP Font Pack (*.zip);;"
            "Font Files (*.ttf *.otf *.woff *.woff2)"
        )
        if not paths:
            return

        result = import_fonts(paths, str(USER_FONTS_DIR))
        self._populate_font_combo()

        # Focus the first newly installed font in the combo
        if result.installed:
            # result.installed contains raw filenames; convert to display name
            first_fname   = result.installed[0]
            first_display = os.path.splitext(first_fname)[0].replace("-"," ").replace("_"," ")
            idx = self.font_combo.findText(first_display)
            if idx < 0:
                # Try partial match (family name may differ slightly)
                for i in range(self.font_combo.count()):
                    if first_display.lower() in self.font_combo.itemText(i).lower():
                        idx = i; break
            if idx >= 0:
                self.font_combo.setCurrentIndex(idx)

        # User-facing summary
        msg = result.summary()
        if result.failed:
            msg += "\n\nFailed:\n" + "\n".join(result.failed)
        QMessageBox.information(self, "Font Import", msg)

    def _populate_font_combo(self):
        """
        Populate font dropdown with all installed fonts.
        Scans FONTS_DIR recursively, uses Qt family name where available,
        falls back to cleaned filename.  Stores filename as userData so
        the canvas can locate the actual file.
        """
        current = self.font_combo.currentText()
        self.font_combo.blockSignals(True)
        self.font_combo.clear()
        self.font_combo.addItem("default")

        entries, seen = [], set()
        for base in font_dirs():
            if not os.path.isdir(base):
                continue
            for root, _dirs, files in os.walk(base):
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in (".ttf", ".otf"):
                        continue
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, base)   # resolved later by font_path()
                    if rel in seen:
                        continue                     # user copy shadows bundled one
                    seen.add(rel)
                    # Get Qt family name (already registered at startup)
                    fid   = QFontDatabase.addApplicationFont(fpath)
                    fams  = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                    display = fams[0] if fams else (
                        os.path.splitext(fname)[0].replace("-", " ").replace("_", " ")
                    )
                    entries.append((display, rel))

        for display, rel in sorted(entries, key=lambda x: x[0].lower()):
            self.font_combo.addItem(display, userData=rel)

        self.font_combo.blockSignals(False)
        idx = self.font_combo.findText(current)
        self.font_combo.setCurrentIndex(idx if idx >= 0 else 0)

        # Also populate the visual font list if it exists
        if hasattr(self, '_font_list'):
            items = [(self.font_combo.itemText(i), self.font_combo.itemData(i) or "")
                     for i in range(1, self.font_combo.count())]  # skip "default"
            self._font_list.set_items(items)
            # Restore selection
            if current and current != "default":
                self._font_list.apply_filter("")   # reset filter first
                cur_data = self.font_combo.itemData(self.font_combo.currentIndex()) or ""
                self._font_list.select_by_userdata(cur_data)

    def _on_font_changed(self, name: str):
        if hasattr(self, '_canvas'):
            # Use the stored filename (userData) not the display name
            idx = self.font_combo.currentIndex()
            filename = self.font_combo.itemData(idx) if idx >= 0 else name
            self._canvas.update_selected_layer(font_name=filename or name)

    def _on_font_size_changed(self, v):
        try:
            size = int(v)
            if size > 0 and hasattr(self, '_canvas'):
                self._canvas.update_selected_layer(font_size=size)
        except (ValueError, TypeError):
            pass

    def _pick_text_color(self):
        color = QColorDialog.getColor(self._txt_color_val, self, "Text Color")
        if color.isValid():
            self._apply_text_color(color)

    def _apply_text_color(self, color: QColor):
        self._txt_color_val = color
        self._txt_color_swatch.set_color(color.name())
        self._update_font_preview()
        if hasattr(self, '_canvas'):
            self._canvas.update_selected_layer(
                font_color=(color.red(), color.green(), color.blue()))
