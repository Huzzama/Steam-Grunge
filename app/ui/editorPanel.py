from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QComboBox, QCheckBox, QPushButton, QLineEdit,
    QScrollArea, QFrame, QGroupBox, QSizePolicy,
    QListWidget, QListWidgetItem, QFileDialog, QInputDialog,
    QColorDialog, QStyledItemDelegate, QStyle, QApplication,
)
from PySide6.QtCore import Qt, Signal, QRect, QSize, QPoint
from PySide6.QtGui import QFont, QColor, QPixmap, QPainter, QPen, QBrush, QFontMetrics
import os, io

from app.config import PLATFORM_BARS_DIR, TEXTURES_DIR, FONTS_DIR, TEMPLATES_DIR, RATINGS_DIR
from app.ui.fontImporter import import_fonts, register_all_fonts


from app.ui.layerDelegate import LayerDelegate

# ── Small UI helpers ───────────────────────────────────────────────────────────
def _mini_header(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet("color:#666; font-size:11px; letter-spacing:2px; "
                    "font-family:'Courier New'; padding-top:4px;")
    return l

def _hline() -> QFrame:
    f = QFrame(); f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color:#2a2a2a;"); return f

def _wrap(layout) -> QWidget:
    w = QWidget(); w.setLayout(layout)
    w.setContentsMargins(0,0,0,0); return w

PANEL_STYLE = """
QWidget#EditorPanel {
    background: #161616;
    border-left: 1px solid #2a2a2a;
}
QGroupBox {
    border: 1px solid #2a2a2a;
    border-radius: 2px;
    margin-top: 8px;
    font-family: 'Courier New', monospace;
    font-size: 14px;
    font-weight: bold;
    color: #888;
    letter-spacing: 2px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 6px;
    padding: 0 4px;
}
QLabel {
    color: #999;
    font-family: 'Courier New', monospace;
    font-size: 14px;
}
QLabel#slider_val {
    color: #ccc;
    font-size: 14px;
    min-width: 28px;
}
QSlider::groove:horizontal {
    height: 3px;
    background: #333;
    border-radius: 1px;
}
QSlider::handle:horizontal {
    width: 10px;
    height: 10px;
    background: #888;
    border-radius: 5px;
    margin: -4px 0;
}
QSlider::handle:horizontal:hover {
    background: #bbb;
}
QSlider::sub-page:horizontal {
    background: #555;
    border-radius: 1px;
}
QComboBox {
    background: #1a1a1a;
    border: 1px solid #333;
    color: #ccc;
    font-family: 'Courier New', monospace;
    font-size: 14px;
    padding: 4px 6px;
    border-radius: 2px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background: #1a1a1a;
    border: 1px solid #444;
    color: #ccc;
    selection-background-color: #2a2a4a;
}
QCheckBox {
    color: #aaa;
    font-family: 'Courier New', monospace;
    font-size: 14px;
}
QCheckBox::indicator {
    width: 12px; height: 12px;
    background: #222; border: 1px solid #444;
}
QCheckBox::indicator:checked {
    background: #555; border-color: #888;
}
QLineEdit {
    background: #111;
    border: 1px solid #333;
    color: #ccc;
    font-family: 'Courier New', monospace;
    font-size: 14px;
    padding: 4px 6px;
    border-radius: 2px;
}
QPushButton {
    background: #252525;
    border: 1px solid #404040;
    color: #bbb;
    padding: 5px 10px;
    font-family: 'Courier New', monospace;
    font-size: 14px;
    border-radius: 2px;
}
QPushButton:hover {
    background: #303030;
    border-color: #666;
    color: #fff;
}
QPushButton#export_btn {
    background: #1a2e1a;
    border-color: #3a6e3a;
    color: #88cc88;
    font-size: 14px;
    padding: 8px;
}
QPushButton#export_btn:hover {
    background: #22422a;
    color: #aaffaa;
}
"""


class LabeledSlider(QWidget):
    value_changed = Signal(float)

    def __init__(self, label: str, min_v: int = 0, max_v: int = 100, default: int = 50):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Top row: label + value
        top = QHBoxLayout()
        self.lbl = QLabel(label)
        self.val_lbl = QLabel(str(default))
        self.val_lbl.setObjectName("slider_val")
        self.val_lbl.setAlignment(Qt.AlignRight)
        top.addWidget(self.lbl)
        top.addWidget(self.val_lbl)
        layout.addLayout(top)

        # Bottom row: 0, slider, 100
        row = QHBoxLayout()
        row.addWidget(QLabel("0"))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(min_v, max_v)
        self.slider.setValue(default)
        self.slider.valueChanged.connect(self._on_change)
        row.addWidget(self.slider, stretch=1)
        row.addWidget(QLabel(str(max_v)))
        layout.addLayout(row)

    def _on_change(self, v: int):
        self.val_lbl.setText(str(v))
        self.value_changed.emit(float(v))

    def set_value(self, v: float):
        self.slider.blockSignals(True)
        self.slider.setValue(int(v))
        self.val_lbl.setText(str(int(v)))
        self.slider.blockSignals(False)

    def value(self) -> float:
        return float(self.slider.value())



# ─────────────────────────────────────────────────────────────────────────────
#  Font Panel Widgets
# ─────────────────────────────────────────────────────────────────────────────

class _FontPreviewList(QWidget):
    """
    Scrollable list of fonts, each rendered in its own typeface.
    Shows "STEAM GRUNGE" as preview text (or the font name if rendering fails).
    """
    font_selected = Signal(str, str)   # (display_name, userData/filename)

    ITEM_H   = 38
    PREVIEW  = "STEAM GRUNGE"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str,str]] = []   # (display, userData)
        self._filtered: list[tuple[str,str]] = []
        self._sel_idx = -1
        self._hover_idx = -1
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Scroll offset
        self._scroll_y = 0
        self.setFocusPolicy(Qt.StrongFocus)

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
            self._filtered = [(d,u) for d,u in self._items
                              if q in d.lower()]
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

    # ── paint ─────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W = self.width()
        H = self.height()

        # Background
        p.fillRect(self.rect(), QColor(14, 14, 22))

        # Border
        p.setPen(QPen(QColor(40, 40, 60), 1))
        p.drawRect(0, 0, W-1, H-1)

        if not self._filtered:
            p.setPen(QColor(80, 80, 100))
            p.setFont(QFont("Courier New", 10))
            p.drawText(self.rect(), Qt.AlignCenter, "No fonts match")
            p.end()
            return

        total_h = len(self._filtered) * self.ITEM_H
        max_scroll = max(0, total_h - H)
        self._scroll_y = max(0, min(self._scroll_y, max_scroll))

        p.setClipRect(1, 1, W-2, H-2)

        for i, (display, userdata) in enumerate(self._filtered):
            iy = i * self.ITEM_H - self._scroll_y
            if iy + self.ITEM_H < 0 or iy > H:
                continue
            item_rect = QRect(0, iy, W, self.ITEM_H)

            # Background
            if i == self._sel_idx:
                p.fillRect(item_rect, QColor(34, 40, 88))
            elif i == self._hover_idx:
                p.fillRect(item_rect, QColor(22, 22, 38))

            # Separator
            p.setPen(QPen(QColor(30, 30, 48), 1))
            p.drawLine(0, iy + self.ITEM_H - 1, W, iy + self.ITEM_H - 1)

            # Try to render preview in the actual font
            try:
                from PySide6.QtGui import QFontDatabase
                fid = QFontDatabase.addApplicationFont(
                    os.path.join(FONTS_DIR, userdata) if userdata else "")
                fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                fam  = fams[0] if fams else display
                preview_font = QFont(fam, 13)
            except Exception:
                preview_font = QFont("Courier New", 10)

            # Preview text (left side)
            p.setFont(preview_font)
            lum_check = QColor(180, 180, 200)
            p.setPen(lum_check if i != self._sel_idx else QColor(200, 210, 255))
            text_rect = QRect(8, iy, W - 90, self.ITEM_H)
            p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft,
                       self.PREVIEW)

            # Font name (right side, small mono)
            p.setFont(QFont("Courier New", 8))
            p.setPen(QColor(60, 60, 90) if i != self._sel_idx else QColor(100, 120, 200))
            name_rect = QRect(W - 88, iy, 84, self.ITEM_H)
            p.drawText(name_rect, Qt.AlignVCenter | Qt.AlignRight,
                       display[:14])

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
        if e.key() == Qt.Key_Up and self._sel_idx > 0:
            self._sel_idx -= 1
            self._ensure_visible(self._sel_idx)
            self.update()
            self.font_selected.emit(*self._filtered[self._sel_idx])
        elif e.key() == Qt.Key_Down and self._sel_idx < len(self._filtered) - 1:
            self._sel_idx += 1
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
        self._font_fam  = "Courier New"
        self._size      = 16
        self._bold      = False
        self._italic    = False
        self._color     = QColor(220, 220, 240)
        self.setStyleSheet("background:#0c0c14; border:1px solid #1e1e32; border-radius:3px;")

    def update_preview(self, font_fam="", size=16, bold=False, italic=False,
                       color: QColor = None):
        if font_fam: self._font_fam = font_fam
        if size:     self._size = max(8, min(size, 28))
        self._bold   = bold
        self._italic = italic
        if color:    self._color = color
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(12, 12, 20))
        f = QFont(self._font_fam, self._size)
        f.setBold(self._bold)
        f.setItalic(self._italic)
        p.setFont(f)
        p.setPen(self._color)
        p.drawText(self.rect().adjusted(8, 0, -8, 0),
                   Qt.AlignVCenter | Qt.AlignLeft, self._text)
        p.end()


class EditorPanel(QWidget):
    settings_changed = Signal()
    template_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EditorPanel")
        self.setStyleSheet(PANEL_STYLE)
        self._brush_panel_ref = None   # set by MainWindow after both panels created
        # Tab-local state and tab ref — set by set_canvas()
        self._tab_state = None
        self._tab_ref   = None
        # Register existing fonts with Qt so they're available immediately
        register_all_fonts(FONTS_DIR)
        self._build_ui()

    # ── Tab-local state accessor ───────────────────────────────────────────────
    def _st(self):
        """Return the current tab's AppState, or None if not yet connected."""
        return self._tab_state

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: #161616; }")
        outer.addWidget(scroll)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        scroll.setWidget(container)

        # ── TEMPLATES ──────────────────────────────────────
        grp_tpl = QGroupBox("TEMPLATES")
        tpl_layout = QVBoxLayout(grp_tpl)
        tpl_layout.setSpacing(4)

        self.tpl_cover_btn      = QPushButton("COVER  (600×900)")
        self.tpl_vhs_btn        = QPushButton("VHS COVER  (600×900)")
        self.tpl_wide_btn       = QPushButton("WIDE COVER  (920×430)")
        self.tpl_vhs_pile_btn   = QPushButton("VHS PILE  (920×430)")
        self.tpl_vhs_cass_btn   = QPushButton("VHS CASSETTE  (920×430)")
        self.tpl_hero_btn       = QPushButton("BACKGROUND / HERO  (3840×1240)")
        self.tpl_logo_btn       = QPushButton("LOGO  (1280×720)  ✦ transparent")
        self.tpl_icon_btn       = QPushButton("ICON  (512×512)   ✦ transparent")

        self.tpl_cover_btn.clicked.connect(lambda:    self._select_template("cover"))
        self.tpl_vhs_btn.clicked.connect(lambda:      self._select_template("vhs_cover"))
        self.tpl_wide_btn.clicked.connect(lambda:     self._select_template("wide"))
        self.tpl_vhs_pile_btn.clicked.connect(lambda: self._select_template("vhs_pile"))
        self.tpl_vhs_cass_btn.clicked.connect(lambda: self._select_template("vhs_cassette"))
        self.tpl_hero_btn.clicked.connect(lambda:     self._select_template("hero"))
        self.tpl_logo_btn.clicked.connect(lambda:     self._select_template("logo"))
        self.tpl_icon_btn.clicked.connect(lambda:     self._select_template("icon"))

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#2a2a2a; margin:2px 0;")

        tpl_layout.addWidget(self.tpl_cover_btn)
        tpl_layout.addWidget(self.tpl_vhs_btn)
        tpl_layout.addWidget(self.tpl_wide_btn)
        tpl_layout.addWidget(self.tpl_vhs_pile_btn)
        tpl_layout.addWidget(self.tpl_vhs_cass_btn)
        tpl_layout.addWidget(self.tpl_hero_btn)
        tpl_layout.addWidget(sep)
        tpl_layout.addWidget(self.tpl_logo_btn)
        tpl_layout.addWidget(self.tpl_icon_btn)

        layout.addWidget(grp_tpl)
        self._update_template_buttons()

        # ── CONSOLE BARS ───────────────────────────────────
        grp_bars = QGroupBox("CONSOLE BARS")
        bars_layout = QVBoxLayout(grp_bars)

        # Preview thumbnail (must exist before _populate_platform_combo)
        self.bar_preview = QLabel()
        self.bar_preview.setFixedHeight(52)
        self.bar_preview.setAlignment(Qt.AlignCenter)
        self.bar_preview.setStyleSheet("background:#0a0a0a; border:1px solid #2a2a2a;")

        self.platform_combo = QComboBox()
        self._populate_platform_combo()
        self.platform_combo.currentIndexChanged.connect(self._on_platform_changed)
        bars_layout.addWidget(self.platform_combo)
        bars_layout.addWidget(self.bar_preview)

        btn_add_bar_direct = QPushButton("+ Add bar as layer")
        btn_add_bar_direct.setStyleSheet("font-size:13px; padding:5px 8px;")
        btn_add_bar_direct.clicked.connect(self._add_bar_layer_from_combo)
        bars_layout.addWidget(btn_add_bar_direct)
        layout.addWidget(grp_bars)

        # ── RATINGS ────────────────────────────────────────
        grp_ratings = QGroupBox("RATINGS")
        ratings_layout = QVBoxLayout(grp_ratings)

        self.ratings_preview = QLabel()
        self.ratings_preview.setFixedHeight(52)
        self.ratings_preview.setAlignment(Qt.AlignCenter)
        self.ratings_preview.setStyleSheet("background:#0a0a0a; border:1px solid #2a2a2a;")

        self.ratings_combo = QComboBox()
        self._populate_ratings_combo()
        self.ratings_combo.currentIndexChanged.connect(self._on_rating_changed)
        ratings_layout.addWidget(self.ratings_combo)
        ratings_layout.addWidget(self.ratings_preview)

        btn_add_rating = QPushButton("+ Add rating as layer")
        btn_add_rating.setStyleSheet("font-size:13px; padding:5px 8px;")
        btn_add_rating.clicked.connect(self._add_rating_layer_from_combo)
        ratings_layout.addWidget(btn_add_rating)
        layout.addWidget(grp_ratings)

        # ── DETERIORATION (textures) ───────────────────────
        grp_det = QGroupBox("DETERIORATION TEXTURE")
        det_layout = QVBoxLayout(grp_det)

        # Preview
        self.det_preview = QLabel()
        self.det_preview.setFixedHeight(52)
        self.det_preview.setAlignment(Qt.AlignCenter)
        self.det_preview.setStyleSheet("background:#0a0a0a; border:1px solid #2a2a2a;")

        self.det_combo = QComboBox()
        self._populate_det_combo()                       # reads from assets/textures/
        self.det_combo.currentIndexChanged.connect(self._on_det_changed)
        det_layout.addWidget(self.det_combo)
        det_layout.addWidget(self.det_preview)

        btn_add_det = QPushButton("+ Add texture as layer")
        btn_add_det.setStyleSheet("font-size:13px; padding:5px 8px;")
        btn_add_det.clicked.connect(self._add_det_layer_from_combo)
        det_layout.addWidget(btn_add_det)
        layout.addWidget(grp_det)

        # ── BACKGROUND COLOR ───────────────────────────────
        grp_bg = QGroupBox("BACKGROUND")
        bg_layout = QHBoxLayout(grp_bg)
        self.bg_color_preview = QLabel()
        self.bg_color_preview.setFixedSize(36, 26)
        self.bg_color_preview.setStyleSheet("background:#000000; border:1px solid #555;")
        self._current_bg_color = QColor(0, 0, 0)
        bg_layout.addWidget(self.bg_color_preview)
        btn_bg_color = QPushButton("Pick Background Color")
        btn_bg_color.clicked.connect(self._pick_bg_color)
        bg_layout.addWidget(btn_bg_color)
        layout.addWidget(grp_bg)

        # ── FILM GRAIN ─────────────────────────────────────
        grp_fg = QGroupBox("FILM GRAIN")
        fg_layout = QVBoxLayout(grp_fg)
        self.grain_slider = LabeledSlider("Grain", 0, 100, 0)
        self.grain_slider.value_changed.connect(self._on_grain)
        fg_layout.addWidget(self.grain_slider)
        layout.addWidget(grp_fg)

        # ── CHROMATIC ABERRATION ───────────────────────────
        grp_ca = QGroupBox("CHROMATIC ABE")
        ca_layout = QVBoxLayout(grp_ca)
        self.ca_slider = LabeledSlider("Aberration", 0, 100, 0)
        self.ca_slider.value_changed.connect(self._on_ca)
        ca_layout.addWidget(self.ca_slider)
        layout.addWidget(grp_ca)

        # ── COLOR ──────────────────────────────────────────
        grp_col = QGroupBox("COLOR")
        col_layout = QVBoxLayout(grp_col)

        self.bright_slider = LabeledSlider("Brightness", 0, 100, 50)
        self.bright_slider.value_changed.connect(self._on_brightness)
        col_layout.addWidget(self.bright_slider)

        self.contrast_slider = LabeledSlider("Contrast", 0, 100, 50)
        self.contrast_slider.value_changed.connect(self._on_contrast)
        col_layout.addWidget(self.contrast_slider)

        self.sat_slider = LabeledSlider("Saturation", 0, 100, 50)
        self.sat_slider.value_changed.connect(self._on_saturation)
        col_layout.addWidget(self.sat_slider)
        layout.addWidget(grp_col)

        # ── VHS ────────────────────────────────────────────
        grp_vhs = QGroupBox("VHS")
        vhs_layout = QVBoxLayout(grp_vhs)

        self.scanlines_slider = LabeledSlider("Scanlines", 0, 100, 0)
        self.scanlines_slider.value_changed.connect(self._on_scanlines)
        vhs_layout.addWidget(self.scanlines_slider)
        layout.addWidget(grp_vhs)

        # ── LAYERS ────────────────────────────────────────
        grp_layers = QGroupBox("LAYERS")
        layers_layout = QVBoxLayout(grp_layers)
        layers_layout.setSpacing(3)

        # ── Row 1: Blend mode dropdown (Krita-style top bar) ──────────────────
        blend_row = QHBoxLayout()
        blend_row.setSpacing(4)
        from PySide6.QtWidgets import QComboBox as _CB
        self._layer_blend_top = _CB()
        for m in ["normal","multiply","screen","overlay","darken","lighten",
                  "color-dodge","color-burn","hard-light","soft-light",
                  "difference","exclusion","hue","saturation","color","luminosity"]:
            self._layer_blend_top.addItem(m)
        self._layer_blend_top.setStyleSheet("""
            QComboBox { background:#1a1a28; color:#ccc; border:1px solid #333;
                        padding:2px 6px; font-family:'Courier New'; font-size:11px; }
            QComboBox::drop-down { border:none; }
            QComboBox QAbstractItemView { background:#1a1a28; color:#ccc;
                                          selection-background-color:#2a2a4a; }
        """)
        self._layer_blend_top.currentTextChanged.connect(self._on_blend_top_changed)
        blend_row.addWidget(self._layer_blend_top, 1)
        layers_layout.addLayout(blend_row)

        # ── Row 2: Opacity spinbox-style bar (Krita style) ────────────────────
        opac_row = QHBoxLayout()
        opac_row.setSpacing(4)
        opac_lbl = QLabel("Opacity:")
        opac_lbl.setStyleSheet("color:#888; font-family:'Courier New'; font-size:11px;")
        opac_row.addWidget(opac_lbl)
        self._layer_opac_slider = QSlider(Qt.Horizontal)
        self._layer_opac_slider.setRange(0, 100)
        self._layer_opac_slider.setValue(100)
        self._layer_opac_slider.setStyleSheet("""
            QSlider::groove:horizontal { height:18px; background:#1a1a28;
                border:1px solid #333; border-radius:3px; }
            QSlider::sub-page:horizontal { background:#2a4a7a; border-radius:3px; }
            QSlider::handle:horizontal { width:0px; height:0px; }
        """)
        self._layer_opac_slider.valueChanged.connect(self._on_layer_opac_top)
        opac_row.addWidget(self._layer_opac_slider, 1)
        self._layer_opac_lbl = QLabel("100%")
        self._layer_opac_lbl.setFixedWidth(36)
        self._layer_opac_lbl.setStyleSheet("color:#ccc; font-family:'Courier New'; font-size:11px;")
        opac_row.addWidget(self._layer_opac_lbl)
        layers_layout.addLayout(opac_row)

        # ── Layer list (rows with thumb + name + badges) ──────────────────────
        self._layer_delegate = LayerDelegate()
        self.layer_list = QListWidget()
        self.layer_list.setItemDelegate(self._layer_delegate)
        self.layer_list.setMinimumHeight(150)
        self.layer_list.setMaximumHeight(340)
        self.layer_list.setUniformItemSizes(True)
        self.layer_list.setSpacing(0)
        # Drag-and-drop for layer reordering and grouping
        self.layer_list.setDragEnabled(True)
        self.layer_list.setAcceptDrops(True)
        self.layer_list.setDropIndicatorShown(False)   # we draw our own
        self.layer_list.setDragDropMode(QListWidget.DragDrop)
        self.layer_list.setDefaultDropAction(Qt.MoveAction)
        self.layer_list.setStyleSheet("""
            QListWidget {
                background: #141420;
                border: 1px solid #2a2a3a;
                outline: none;
            }
            QListWidget::item { border-bottom: 1px solid #1e1e2e; }
            QListWidget::item:selected { background: #1e3050; }
            QScrollBar:vertical { background:#0d0d0d; width:8px; border:none; }
            QScrollBar::handle:vertical { background:#2a2a4a; border-radius:4px; min-height:20px; }
        """)
        self.layer_list.currentRowChanged.connect(self._on_layer_list_select)
        self.layer_list.clicked.connect(self._on_layer_list_clicked)
        self.layer_list.doubleClicked.connect(self._on_layer_double_clicked)
        # Drag-and-drop signals
        self.layer_list.model().rowsMoved.connect(self._on_rows_moved)
        self._drag_drop_indicator_row = -1   # row where drop indicator is shown
        layers_layout.addWidget(self.layer_list)

        # ── Bottom action bar (Krita-style) ──────────────────────────────────────
        action_row = QHBoxLayout()
        action_row.setSpacing(1)
        btn_style = """
            QPushButton {
                font-size:15px; padding:0px; min-width:28px;
                background:#141420; border:1px solid #2a2a3a;
                border-radius:2px; color:#8888aa;
            }
            QPushButton:hover  { background:#1e1e3a; color:#aaaaff; }
            QPushButton:pressed { background:#111128; }
        """
        menu_style = """
            QMenu {
                background:#1a1a28; border:1px solid #3a3a5a;
                padding:4px 0px; color:#ccccee;
                font-family:'Segoe UI'; font-size:12px;
            }
            QMenu::item { padding:6px 24px 6px 10px; }
            QMenu::item:selected { background:#2a2a4a; color:#ffffff; }
            QMenu::separator { height:1px; background:#2e2e4a; margin:3px 8px; }
            QMenu::item:disabled { color:#555566; }
        """

        # ── "+" Add Layer button with dropdown menu ───────────────────────────
        from PySide6.QtWidgets import QMenu
        btn_add = QPushButton("+")
        btn_add.setToolTip("Add layer")
        btn_add.setFixedSize(26, 26)
        btn_add.setStyleSheet(btn_style + """
            QPushButton { font-size:18px; font-weight:bold; color:#88aacc; }
            QPushButton:hover { color:#aaddff; }
        """)

        add_menu = QMenu(btn_add)
        add_menu.setStyleSheet(menu_style)

        # ── Core layer types ───────────────────────────────────────────────────
        act = add_menu.addAction("🖼  Paint Layer")
        act.setToolTip("Create a blank paint layer")
        act.triggered.connect(self._add_paint_layer)

        act = add_menu.addAction("📁  Group Layer")
        act.setToolTip("Create an empty group folder")
        act.triggered.connect(self._add_group_layer)

        act = add_menu.addAction("🪣  Fill Layer")
        act.setToolTip("Create a solid color or gradient fill")
        act.triggered.connect(self._add_fill_layer)

        add_menu.addSeparator()

        # ── Quick add helpers ─────────────────────────────────────────────────
        lbl_q = add_menu.addAction("— Quick Add —")
        lbl_q.setEnabled(False)

        act = add_menu.addAction("T    Text Layer")
        act.triggered.connect(self._add_text_layer)

        act = add_menu.addAction("🎮  Platform Bar")
        act.triggered.connect(self._add_bar_layer)

        act = add_menu.addAction("🌫  Texture Layer")
        act.triggered.connect(self._add_texture_layer)

        add_menu.addSeparator()

        # ── Import (file picker) ──────────────────────────────────────────────
        lbl_i = add_menu.addAction("— Import —")
        lbl_i.setEnabled(False)

        act = add_menu.addAction("📂  Import Image File…")
        act.setToolTip("Import a PNG or JPG as a layer")
        act.triggered.connect(self._import_file_layer)

        btn_add.setMenu(add_menu)
        action_row.addWidget(btn_add)

        action_row.addStretch()

        action_btns = [
            ("▲",    "Move layer up",       self._move_layer_up),
            ("▼",    "Move layer down",     self._move_layer_down),
            ("DUP",  "Duplicate layer",     self._duplicate_layer),
            ("VIS",  "Toggle visibility",   self._toggle_layer_visibility),
            ("🔒",   "Lock / unlock layer", self._toggle_layer_lock),
            ("DEL",  "Delete layer",        self._delete_selected_layer),
        ]
        for label, tip, slot in action_btns:
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setFixedHeight(26)
            if label in ("DUP", "VIS", "DEL"):
                b.setFixedWidth(36)
                b.setStyleSheet(btn_style + "QPushButton { font-size:11px; letter-spacing:1px; }")
            else:
                b.setStyleSheet(btn_style)
            b.clicked.connect(slot)
            action_row.addWidget(b)

        layers_layout.addLayout(action_row)
        layout.addWidget(grp_layers)

        # ── LAYER PROPERTIES (context-sensitive) ─────────
        self.props_group = QGroupBox("LAYER PROPERTIES")
        self.props_group.setVisible(True)
        props_layout = QVBoxLayout(self.props_group)
        props_layout.setSpacing(4)

        # No-selection placeholder
        self.props_placeholder = QLabel("Select a layer to\nedit its properties")
        self.props_placeholder.setAlignment(Qt.AlignCenter)
        self.props_placeholder.setStyleSheet(
            "color:#444; font-size:12px; font-family:'Courier New'; padding:16px;")
        props_layout.addWidget(self.props_placeholder)

        # ── Shared: Opacity + Blend mode ─────────────────
        shared_frame = QFrame()
        shared_layout = QVBoxLayout(shared_frame)
        shared_layout.setContentsMargins(0,0,0,0)
        shared_layout.setSpacing(3)

        self.opacity_slider = LabeledSlider("Opacity", 0, 100, 100)
        self.opacity_slider.value_changed.connect(self._on_opacity)
        shared_layout.addWidget(self.opacity_slider)

        blend_row = QHBoxLayout()
        blend_row.addWidget(QLabel("Blend:"))
        self.blend_combo = QComboBox()
        self.blend_combo.addItems(["normal","multiply","screen","overlay","soft_light"])
        self.blend_combo.currentTextChanged.connect(
            lambda v: self._canvas.update_selected_layer(blend_mode=v) if hasattr(self,'_canvas') else None)
        blend_row.addWidget(self.blend_combo)
        shared_layout.addWidget(_wrap(blend_row))
        props_layout.addWidget(shared_frame)

        props_layout.addWidget(_hline())

        # ── IMAGE controls ────────────────────────────────
        self.img_controls = QFrame()
        img_layout = QVBoxLayout(self.img_controls)
        img_layout.setContentsMargins(0,0,0,0)
        img_layout.setSpacing(3)

        # Transform
        img_layout.addWidget(_mini_header("TRANSFORM"))
        self.rotation_slider = LabeledSlider("Rotate", -180, 180, 0)
        self.rotation_slider.value_changed.connect(
            lambda v: self._canvas.update_selected_layer(rotation=v) if hasattr(self,'_canvas') else None)
        img_layout.addWidget(self.rotation_slider)

        flip_row = QHBoxLayout()
        btn_fh = QPushButton("↔ Flip H")
        btn_fv = QPushButton("↕ Flip V")
        btn_fh.setStyleSheet("font-size:13px; padding:5px 8px;")
        btn_fv.setStyleSheet("font-size:13px; padding:5px 8px;")
        btn_fh.clicked.connect(self._flip_horizontal)
        btn_fv.clicked.connect(self._flip_vertical)
        flip_row.addWidget(btn_fh); flip_row.addWidget(btn_fv)
        img_layout.addWidget(_wrap(flip_row))

        # Fit controls
        img_layout.addWidget(_mini_header("FIT"))
        fit_row = QHBoxLayout()
        for label, slot in [("Fit", self._fit_canvas),
                             ("Fill", self._fill_canvas),
                             ("Center", self._center_layer)]:
            b = QPushButton(label)
            b.setStyleSheet("font-size:13px; padding:5px 6px;")
            b.clicked.connect(slot)
            fit_row.addWidget(b)
        img_layout.addWidget(_wrap(fit_row))

        # Color adjustments (per-layer)
        img_layout.addWidget(_mini_header("COLOR ADJUST"))
        self.layer_bright = LabeledSlider("Bright", 0, 100, 50)
        self.layer_bright.value_changed.connect(
            lambda v: self._layer_color_changed("brightness", v))
        img_layout.addWidget(self.layer_bright)
        self.layer_contrast = LabeledSlider("Contrast", 0, 100, 50)
        self.layer_contrast.value_changed.connect(
            lambda v: self._layer_color_changed("contrast", v))
        img_layout.addWidget(self.layer_contrast)
        self.layer_sat = LabeledSlider("Sat", 0, 100, 50)
        self.layer_sat.value_changed.connect(
            lambda v: self._layer_color_changed("saturation", v))
        img_layout.addWidget(self.layer_sat)

        # Color tint
        img_layout.addWidget(_mini_header("COLOR TINT"))
        tint_row = QHBoxLayout()
        self.tint_preview = QLabel()
        self.tint_preview.setFixedSize(28, 22)
        self.tint_preview.setStyleSheet("background:#ffffff; border:1px solid #555;")
        self._current_tint = QColor(255, 255, 255)
        tint_row.addWidget(self.tint_preview)
        btn_tint = QPushButton("Pick Tint Color")
        btn_tint.setStyleSheet("font-size:12px; padding:3px 6px;")
        btn_tint.clicked.connect(self._pick_tint_color)
        tint_row.addWidget(btn_tint)
        img_layout.addWidget(_wrap(tint_row))
        self.tint_strength_slider = LabeledSlider("Strength", 0, 100, 0)
        self.tint_strength_slider.value_changed.connect(self._on_tint_strength)
        img_layout.addWidget(self.tint_strength_slider)

        props_layout.addWidget(self.img_controls)

        # ── TEXT controls ─────────────────────────────────
        self.text_controls = QFrame()
        txt_layout = QVBoxLayout(self.text_controls)
        txt_layout.setContentsMargins(0, 0, 0, 2)
        txt_layout.setSpacing(4)

        # ── FONT section ──────────────────────────────────────────────────────
        txt_layout.addWidget(_mini_header("FONT"))

        # Search + Import row
        font_search_row = QHBoxLayout()
        font_search_row.setSpacing(4)
        self._font_search = QLineEdit()
        self._font_search.setPlaceholderText("Search fonts…")
        self._font_search.setStyleSheet("""
            QLineEdit {
                background:#111; color:#ccc; border:1px solid #2a2a3e;
                border-radius:3px; font-size:11px; padding:3px 6px;
            }
            QLineEdit:focus { border-color:#4455aa; }
        """)
        self._font_search.textChanged.connect(self._on_font_search)
        font_search_row.addWidget(self._font_search, 1)

        btn_import_font = QPushButton("⊕")
        btn_import_font.setFixedSize(26, 26)
        btn_import_font.setToolTip("Import .ttf / .otf fonts or a ZIP font pack")
        btn_import_font.setStyleSheet("""
            QPushButton {
                background:#1a2a1a; color:#5a9; border:1px solid #2a4a2a;
                border-radius:3px; font-size:14px; padding:0;
            }
            QPushButton:hover { background:#1e361e; color:#7bc; border-color:#3a6a3a; }
        """)
        btn_import_font.clicked.connect(self._import_fonts_dialog)
        font_search_row.addWidget(btn_import_font)
        txt_layout.addLayout(font_search_row)

        # Hidden combo must exist BEFORE _populate_font_combo is called
        self.font_combo = QComboBox()
        self.font_combo.setVisible(False)
        self.font_combo.currentTextChanged.connect(self._on_font_changed)

        # Font list with per-font preview rendering
        self._font_list = _FontPreviewList()
        self._font_list.setFixedHeight(160)
        self._font_list.font_selected.connect(self._on_font_list_selected)
        txt_layout.addWidget(self._font_list)
        self._populate_font_combo()   # fills both font_combo and _font_list

        # ── Live preview bar ──────────────────────────────────────────────────
        self._font_preview_bar = _FontPreviewBar()
        self._font_preview_bar.setFixedHeight(40)
        txt_layout.addWidget(self._font_preview_bar)

        # ── STYLE section ─────────────────────────────────────────────────────
        txt_layout.addWidget(_mini_header("STYLE"))

        size_spc_row = QHBoxLayout()
        size_spc_row.setSpacing(6)
        size_spc_row.addWidget(QLabel("Size:"))
        self.font_size_input = QLineEdit("48")
        self.font_size_input.setFixedWidth(52)
        self.font_size_input.textChanged.connect(self._on_font_size_changed)
        self.font_size_input.textChanged.connect(self._update_font_preview)
        size_spc_row.addWidget(self.font_size_input)
        size_spc_row.addSpacing(8)
        size_spc_row.addWidget(QLabel("Spc:"))
        self.letter_spacing_input = QLineEdit("0")
        self.letter_spacing_input.setFixedWidth(44)
        self.letter_spacing_input.setPlaceholderText("0")
        self.letter_spacing_input.textChanged.connect(self._on_letter_spacing_changed)
        size_spc_row.addWidget(self.letter_spacing_input)
        size_spc_row.addStretch()
        txt_layout.addLayout(size_spc_row)

        style_row = QHBoxLayout()
        style_row.setSpacing(6)
        _cb_ss = "font-size:12px; padding:2px 4px;"
        self.bold_cb   = QCheckBox("Bold")
        self.italic_cb = QCheckBox("Italic")
        self.upper_cb  = QCheckBox("AA")
        self.bold_cb.setStyleSheet(_cb_ss + "font-weight:bold;")
        self.italic_cb.setStyleSheet(_cb_ss + "font-style:italic;")
        self.upper_cb.setStyleSheet(_cb_ss)
        self.bold_cb.stateChanged.connect(lambda v: self._canvas.update_selected_layer(font_bold=bool(v)) if hasattr(self,'_canvas') else None)
        self.bold_cb.stateChanged.connect(self._update_font_preview)
        self.italic_cb.stateChanged.connect(lambda v: self._canvas.update_selected_layer(font_italic=bool(v)) if hasattr(self,'_canvas') else None)
        self.italic_cb.stateChanged.connect(self._update_font_preview)
        self.upper_cb.stateChanged.connect(lambda v: self._canvas.update_selected_layer(font_uppercase=bool(v)) if hasattr(self,'_canvas') else None)
        for cb in (self.bold_cb, self.italic_cb, self.upper_cb):
            style_row.addWidget(cb)
        style_row.addStretch()
        txt_layout.addLayout(style_row)

        # ── LAYOUT section ────────────────────────────────────────────────────
        txt_layout.addWidget(_mini_header("LAYOUT"))

        align_row = QHBoxLayout()
        align_row.setSpacing(3)
        _aln_ss = """
            QPushButton { font-size:14px; padding:3px 8px;
                          background:#1a1a28; border:1px solid #2e2e44; border-radius:3px; }
            QPushButton:hover { background:#22223a; border-color:#4455aa; }
            QPushButton:checked { background:#2a2a5a; border-color:#5566cc; color:#aabbff; }
        """
        for icon, val in [("⬛ L", "left"), ("⬛ C", "center"), ("⬛ R", "right")]:
            b = QPushButton(icon)
            b.setCheckable(True)
            b.setStyleSheet(_aln_ss)
            b.clicked.connect(lambda _, v=val, btn=b: self._on_align_btn(v, btn))
            align_row.addWidget(b)
        align_row.addStretch()
        self._align_btns = [align_row.itemAt(i).widget() for i in range(3)]
        self._align_btns[0].setChecked(True)
        txt_layout.addLayout(align_row)

        orient_row = QHBoxLayout()
        orient_row.addWidget(QLabel("Orient:"))
        orient_combo = QComboBox()
        orient_combo.addItems(["horizontal", "rotate90", "rotate270", "vertical"])
        orient_combo.currentTextChanged.connect(
            lambda v: self._canvas.update_selected_layer(text_orientation=v) if hasattr(self,'_canvas') else None)
        self.orient_combo = orient_combo
        orient_row.addWidget(orient_combo, 1)
        txt_layout.addLayout(orient_row)

        # ── COLOR section ─────────────────────────────────────────────────────
        txt_layout.addWidget(_mini_header("COLOR"))

        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        self._txt_color_swatch = QLabel()
        self._txt_color_swatch.setFixedSize(32, 24)
        self._txt_color_swatch.setStyleSheet(
            "background:#ffffff; border:1px solid #555; border-radius:3px;")
        self._txt_color_swatch.setCursor(Qt.PointingHandCursor)
        self._txt_color_swatch.mousePressEvent = lambda _: self._pick_text_color()
        self._txt_color_val = QColor(255, 255, 255)
        color_row.addWidget(self._txt_color_swatch)
        btn_txt_color = QPushButton("Text Color")
        btn_txt_color.setStyleSheet("font-size:12px; padding:4px 8px;")
        btn_txt_color.clicked.connect(self._pick_text_color)
        color_row.addWidget(btn_txt_color)
        color_row.addStretch()
        txt_layout.addLayout(color_row)

        # ── EFFECTS section ───────────────────────────────────────────────────
        txt_layout.addWidget(_mini_header("EFFECTS"))

        self.outline_slider = LabeledSlider("Outline", 0, 20, 0)
        self.outline_slider.value_changed.connect(
            lambda v: self._canvas.update_selected_layer(outline_size=int(v)) if hasattr(self,'_canvas') else None)
        txt_layout.addWidget(self.outline_slider)

        self.shadow_slider = LabeledSlider("Shadow", 0, 30, 0)
        self.shadow_slider.value_changed.connect(
            lambda v: self._canvas.update_selected_layer(shadow_offset=int(v)) if hasattr(self,'_canvas') else None)
        txt_layout.addWidget(self.shadow_slider)

        props_layout.addWidget(self.text_controls)

        # ── FILL LAYER CONTROLS ───────────────────────────────────────────────
        self.fill_controls = QFrame()
        self.fill_controls.setVisible(False)
        fl = QVBoxLayout(self.fill_controls)
        fl.setSpacing(4); fl.setContentsMargins(0,0,0,0)

        fl.addWidget(QLabel("Fill Type"))
        self._fill_type_combo = QComboBox()
        self._fill_type_combo.addItems(["solid", "gradient", "pattern"])
        self._fill_type_combo.currentTextChanged.connect(self._on_fill_type_changed)
        fl.addWidget(self._fill_type_combo)

        color1_row = QHBoxLayout()
        color1_row.addWidget(QLabel("Color"))
        self._fill_color_swatch = QLabel()
        self._fill_color_swatch.setFixedSize(26, 18)
        self._fill_color_swatch.setStyleSheet("background:#000; border:1px solid #555;")
        self._fill_color_swatch.setCursor(Qt.PointingHandCursor)
        self._fill_color_swatch.mousePressEvent = lambda _: self._pick_fill_color(1)
        color1_row.addWidget(self._fill_color_swatch); color1_row.addStretch()
        fl.addLayout(color1_row)

        color2_row = QHBoxLayout()
        color2_row.addWidget(QLabel("Color 2 (gradient)"))
        self._fill_color2_swatch = QLabel()
        self._fill_color2_swatch.setFixedSize(26, 18)
        self._fill_color2_swatch.setStyleSheet("background:#fff; border:1px solid #555;")
        self._fill_color2_swatch.setCursor(Qt.PointingHandCursor)
        self._fill_color2_swatch.mousePressEvent = lambda _: self._pick_fill_color(2)
        color2_row.addWidget(self._fill_color2_swatch); color2_row.addStretch()
        fl.addLayout(color2_row)

        self._fill_angle_slider = LabeledSlider("Angle°", 0, 360, 0)
        self._fill_angle_slider.value_changed.connect(self._on_fill_angle)
        fl.addWidget(self._fill_angle_slider)
        props_layout.addWidget(self.fill_controls)

        # ── FILTER LAYER CONTROLS ─────────────────────────────────────────────
        self.filter_controls = QFrame()
        self.filter_controls.setVisible(False)
        flt = QVBoxLayout(self.filter_controls)
        flt.setSpacing(4); flt.setContentsMargins(0,0,0,0)
        self._filter_type_lbl = QLabel("Filter: —")
        self._filter_type_lbl.setStyleSheet("color:#cc9; font-family:'Courier New'; font-size:11px;")
        flt.addWidget(self._filter_type_lbl)
        btn_change_filter = QPushButton("Change Filter Type…")
        btn_change_filter.clicked.connect(self._change_filter_type)
        flt.addWidget(btn_change_filter)
        self._filter_strength = LabeledSlider("Strength", 0, 100, 100)
        self._filter_strength.value_changed.connect(
            lambda v: self._canvas.update_selected_layer(opacity=v/100.) if hasattr(self,'_canvas') else None)
        flt.addWidget(self._filter_strength)
        props_layout.addWidget(self.filter_controls)

        # ── CLONE LAYER CONTROLS ──────────────────────────────────────────────
        self.clone_controls = QFrame()
        self.clone_controls.setVisible(False)
        cll = QVBoxLayout(self.clone_controls)
        cll.setSpacing(4); cll.setContentsMargins(0,0,0,0)
        cll.addWidget(QLabel("Source layer:"))
        self._clone_source_combo = QComboBox()
        self._clone_source_combo.currentIndexChanged.connect(self._on_clone_source_changed)
        cll.addWidget(self._clone_source_combo)
        info = QLabel("Clone mirrors its source.\nEditing the source updates this layer.")
        info.setWordWrap(True)
        info.setStyleSheet("color:#666; font-size:10px; font-family:'Courier New';")
        cll.addWidget(info)
        props_layout.addWidget(self.clone_controls)

        # ── VECTOR LAYER CONTROLS ─────────────────────────────────────────────
        self.vector_controls = QFrame()
        self.vector_controls.setVisible(False)
        vl = QVBoxLayout(self.vector_controls)
        vl.setSpacing(4); vl.setContentsMargins(0,0,0,0)
        stroke_row = QHBoxLayout()
        stroke_row.addWidget(QLabel("Stroke"))
        self._vec_stroke_swatch = QLabel()
        self._vec_stroke_swatch.setFixedSize(26,18)
        self._vec_stroke_swatch.setStyleSheet("background:#fff; border:1px solid #555;")
        self._vec_stroke_swatch.setCursor(Qt.PointingHandCursor)
        self._vec_stroke_swatch.mousePressEvent = lambda _: self._pick_vector_color("stroke")
        stroke_row.addWidget(self._vec_stroke_swatch); stroke_row.addStretch()
        vl.addLayout(stroke_row)
        fill_row = QHBoxLayout()
        fill_row.addWidget(QLabel("Fill"))
        self._vec_fill_swatch = QLabel()
        self._vec_fill_swatch.setFixedSize(26,18)
        self._vec_fill_swatch.setStyleSheet("background:#fff; border:1px solid #555;")
        self._vec_fill_swatch.setCursor(Qt.PointingHandCursor)
        self._vec_fill_swatch.mousePressEvent = lambda _: self._pick_vector_color("fill")
        fill_row.addWidget(self._vec_fill_swatch); fill_row.addStretch()
        vl.addLayout(fill_row)
        vl.addWidget(QLabel("(Vector drawing tools coming soon)", ))
        props_layout.addWidget(self.vector_controls)

        # ── GROUP LAYER CONTROLS ──────────────────────────────────────────────
        self.group_controls = QFrame()
        self.group_controls.setVisible(False)
        gl = QVBoxLayout(self.group_controls)
        gl.setSpacing(4); gl.setContentsMargins(0,0,0,0)
        info_g = QLabel("Group layer — use Move/Resize\nto reposition child layers together.")
        info_g.setWordWrap(True)
        info_g.setStyleSheet("color:#666; font-size:10px; font-family:'Courier New';")
        gl.addWidget(info_g)
        props_layout.addWidget(self.group_controls)

        # ── MASK CONTROLS (shared for all mask types) ─────────────────────────
        self.mask_controls = QFrame()
        self.mask_controls.setVisible(False)
        ml = QVBoxLayout(self.mask_controls)
        ml.setSpacing(4); ml.setContentsMargins(0,0,0,0)
        self._mask_feather_slider = LabeledSlider("Feather (blur)", 0, 50, 0)
        self._mask_feather_slider.value_changed.connect(self._on_mask_feather)
        ml.addWidget(self._mask_feather_slider)
        mask_col_row = QHBoxLayout()
        mask_col_row.addWidget(QLabel("Mask Color"))
        self._mask_color_swatch = QLabel()
        self._mask_color_swatch.setFixedSize(26,18)
        self._mask_color_swatch.setStyleSheet("background:#fff; border:1px solid #555;")
        self._mask_color_swatch.setCursor(Qt.PointingHandCursor)
        self._mask_color_swatch.mousePressEvent = lambda _: self._pick_mask_color()
        mask_col_row.addWidget(self._mask_color_swatch); mask_col_row.addStretch()
        ml.addLayout(mask_col_row)
        props_layout.addWidget(self.mask_controls)
        layout.addWidget(self.props_group)

        # ── EXPORT ─────────────────────────────────────────
        self.export_btn = QPushButton("⬇  EXPORT IMAGE")
        self.export_btn.setObjectName("export_btn")
        self.export_btn.clicked.connect(self._on_export)
        layout.addWidget(self.export_btn)

        layout.addStretch()

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
        active_style      = ("background:#1a2e1a; border:1px solid #3a6e3a; "
                             "color:#88cc88; font-size:13px; padding:5px 8px;")
        active_alpha_style = ("background:#1a1e2e; border:1px solid #3a4a6e; "
                              "color:#88aacc; font-size:13px; padding:5px 8px;")
        inactive_style    = ""
        st = self._st()
        tpl = st.current_template if st else "cover"
        self.tpl_cover_btn.setStyleSheet(    active_style       if tpl == "cover"        else inactive_style)
        self.tpl_vhs_btn.setStyleSheet(      active_style       if tpl == "vhs_cover"    else inactive_style)
        self.tpl_wide_btn.setStyleSheet(     active_style       if tpl == "wide"         else inactive_style)
        self.tpl_vhs_pile_btn.setStyleSheet( active_style       if tpl == "vhs_pile"     else inactive_style)
        self.tpl_vhs_cass_btn.setStyleSheet( active_style       if tpl == "vhs_cassette" else inactive_style)
        self.tpl_hero_btn.setStyleSheet(     active_style       if tpl == "hero"         else inactive_style)
        self.tpl_logo_btn.setStyleSheet(     active_alpha_style if tpl == "logo"         else inactive_style)
        self.tpl_icon_btn.setStyleSheet(     active_alpha_style if tpl == "icon"         else inactive_style)

    def _populate_platform_combo(self):
        """Read actual image files from platformBars folder."""
        self.platform_combo.blockSignals(True)
        self.platform_combo.clear()
        self.platform_combo.addItem("none", userData=None)
        if os.path.isdir(PLATFORM_BARS_DIR):
            for f in sorted(os.listdir(PLATFORM_BARS_DIR)):
                if f.lower().endswith((".png", ".jpg", ".jpeg")):
                    label = os.path.splitext(f)[0]
                    full  = os.path.join(PLATFORM_BARS_DIR, f)
                    self.platform_combo.addItem(label, userData=full)
        self.platform_combo.blockSignals(False)
        self._update_bar_preview()

    def _update_bar_preview(self):
        path = self.platform_combo.currentData()
        if path and os.path.exists(path):
            pix = QPixmap(path).scaledToHeight(34, Qt.SmoothTransformation)
            self.bar_preview.setPixmap(pix)
        else:
            self.bar_preview.clear()
            self.bar_preview.setText("none")

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
        if os.path.isdir(TEXTURES_DIR):
            for f in sorted(os.listdir(TEXTURES_DIR)):
                if f.lower().endswith((".png", ".jpg", ".jpeg")):
                    label = os.path.splitext(f)[0]
                    full  = os.path.join(TEXTURES_DIR, f)
                    self.det_combo.addItem(label, userData=full)
        self.det_combo.blockSignals(False)
        self._update_det_preview()

    def _update_det_preview(self):
        path = self.det_combo.currentData()
        if path and os.path.exists(path):
            pix = QPixmap(path).scaledToHeight(50, Qt.SmoothTransformation)
            self.det_preview.setPixmap(pix)
        else:
            self.det_preview.clear()
            self.det_preview.setText("none")

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
                    label = os.path.splitext(f)[0]
                    self.ratings_combo.addItem(label, userData=os.path.join(RATINGS_DIR, f))
        self.ratings_combo.blockSignals(False)
        self._update_ratings_preview()

    def _update_ratings_preview(self):
        path = self.ratings_combo.currentData()
        if path and os.path.exists(path):
            pix = QPixmap(path).scaledToHeight(48, Qt.SmoothTransformation)
            self.ratings_preview.setPixmap(pix)
            self.ratings_preview.setText("")
        else:
            self.ratings_preview.setPixmap(QPixmap())
            self.ratings_preview.setText("none")

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

    def _pick_bg_color(self):
        color = QColorDialog.getColor(self._current_bg_color, self, "Background Color")
        if color.isValid():
            self._current_bg_color = color
            hex_c = color.name()
            self.bg_color_preview.setStyleSheet(
                f"background:{hex_c}; border:1px solid #555;")
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
        # PERF: do NOT emit settings_changed here — grain is a canvas-only
        # post-processing effect handled by previewCanvas._draw_with_global_fx.
        # Emitting settings_changed would trigger compositor.compose() which
        # runs a second full PIL render with no visual benefit for grain changes.

    def _on_ca(self, v: float):
        st = self._st()
        if st is not None:
            st.chromatic_aberration = v
        self._apply_document_fx_to_canvas()
        # PERF: same as _on_grain — CA is canvas-only, compositor doesn't use it.

    def _apply_document_fx_to_canvas(self):
        """Push the current tab's FX settings (grain + CA) to the canvas."""
        if not hasattr(self, '_canvas'):
            return
        st = self._st()
        grain = st.film_grain if st is not None else 0.0
        ca    = st.chromatic_aberration if st is not None else 0.0
        self._canvas.update_effects_overlay(grain, ca)

    def _on_brightness(self, v: float):
        # Per-layer setting — route through the canvas authority (no undo history on every tick).
        if hasattr(self, '_canvas') and self._canvas is not None:
            self._canvas.update_layer_no_history(brightness=v)
        self.settings_changed.emit()

    def _on_contrast(self, v: float):
        if hasattr(self, '_canvas') and self._canvas is not None:
            self._canvas.update_layer_no_history(contrast=v)
        self.settings_changed.emit()

    def _on_saturation(self, v: float):
        if hasattr(self, '_canvas') and self._canvas is not None:
            self._canvas.update_layer_no_history(saturation=v)
        self.settings_changed.emit()

    def _on_scanlines(self, v: float):
        st = self._st()
        if st is not None:
            st.vhs_scanlines = v
        self.settings_changed.emit()

    def _on_export(self):
        from PySide6.QtWidgets import QMessageBox
        # Delegate to the tab's export() which runs the full confirm→save flow
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
            QMessageBox.information(self, "Exported", f"Saved:\n{path}")

    def set_spine_text(self, text: str):
        pass  # spine removed

    def refresh_from_state(self):
        """Sync all document-level controls from the current tab state.
        Called when the canvas/tab is first attached and after project load."""
        st = self._st()
        if st is None:
            return
        # Block signals during bulk sync so we don't trigger cascading updates
        for sl, attr in [
            (self.grain_slider,     'film_grain'),
            (self.ca_slider,        'chromatic_aberration'),
            (self.bright_slider,    'brightness'),
            (self.contrast_slider,  'contrast'),
            (self.sat_slider,       'saturation'),
            (self.scanlines_slider, 'vhs_scanlines'),
        ]:
            sl.set_value(getattr(st, attr, sl.value()))

        # Sync template button highlight
        self._update_template_buttons()

        # Sync background color preview
        bg = getattr(st, 'bg_color', (0, 0, 0))
        q = QColor(*bg) if bg else QColor(0, 0, 0)
        self._current_bg_color = q
        self.bg_color_preview.setStyleSheet(
            f"background:{q.name()}; border:1px solid #555;")

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
        skip_until_group_end = set()
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
            item.setData(Qt.UserRole + 20, canvas_idx)
            thumb = self._make_layer_thumb(layer)
            item.setData(LayerDelegate.PIX_ROLE, thumb)
            self.layer_list.addItem(item)

        # Highlight current selection
        sel_canvas = self._canvas.selected_layer_index()
        for row in range(self.layer_list.count()):
            it = self.layer_list.item(row)
            if it and it.data(Qt.UserRole + 20) == sel_canvas:
                self.layer_list.setCurrentRow(row)
                break

        self.layer_list.blockSignals(False)

    def _sync_layer_list_selection(self, canvas_idx: int):
        """Highlight the row matching canvas_idx without rebuilding."""
        self.layer_list.blockSignals(True)
        for row in range(self.layer_list.count()):
            it = self.layer_list.item(row)
            if it and it.data(Qt.UserRole + 20) == canvas_idx:
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
        canvas_idx = item.data(Qt.UserRole + 20)
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
        canvas_idx = item.data(Qt.UserRole + 20)
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
                new_order_canvas_indices.append(it.data(Qt.UserRole + 20))

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
            ci = it.data(Qt.UserRole + 20)
            if not (0 <= ci < len(old_layers)):
                continue
            layer = old_layers[ci]
            parent_group_ci = None
            for above_row in range(row - 1, -1, -1):
                above_it = self.layer_list.item(above_row)
                if above_it:
                    above_kind = (above_it.data(LayerDelegate.KIND_ROLE) or "").lower()
                    if above_kind == "group":
                        parent_group_ci = above_it.data(Qt.UserRole + 20)
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
            self.props_placeholder.setVisible(True)
            self.img_controls.setVisible(False)
            self.text_controls.setVisible(False)
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
            self.props_placeholder.setVisible(True)
            self.props_placeholder.setText(
                f"📁  {layer.name}\n\n"
                "Group layer — select a child\nlayer to edit its properties."
            )
            self.img_controls.setVisible(False)
            self.text_controls.setVisible(False)
            for attr in ("fill_controls","filter_controls","clone_controls",
                         "vector_controls","group_controls","mask_controls"):
                if hasattr(self, attr):
                    getattr(self, attr).setVisible(False)
            return

        # Locked layers: show unlock button + notice, hide edit controls
        if effectively_locked:
            self.props_placeholder.setVisible(True)
            self.props_placeholder.setText(
                "🔒  Layer is locked"
            )
            self.img_controls.setVisible(False)
            self.text_controls.setVisible(False)
            for attr in ("fill_controls","filter_controls","clone_controls",
                         "vector_controls","group_controls","mask_controls"):
                if hasattr(self, attr):
                    getattr(self, attr).setVisible(False)
            # Show a dedicated unlock button so the user isn't stuck
            if not hasattr(self, "_unlock_btn"):
                from PySide6.QtWidgets import QPushButton
                self._unlock_btn = QPushButton("🔓  Unlock Layer")
                self._unlock_btn.setStyleSheet("""
                    QPushButton {
                        background: #2a1a1a; color: #ffaa44;
                        border: 1px solid #885522; border-radius: 4px;
                        font-size: 12px; padding: 6px 14px; margin-top: 6px;
                    }
                    QPushButton:hover { background: #3a2a1a; border-color: #cc7733; }
                """)
                self._unlock_btn.clicked.connect(self._toggle_layer_lock)
                # Insert below placeholder in props_stack layout
                try:
                    self.props_stack.layout().addWidget(self._unlock_btn)
                except Exception:
                    pass
            self._unlock_btn.setVisible(True)
            return
        # Hide unlock button when layer is not locked
        if hasattr(self, "_unlock_btn"):
            self._unlock_btn.setVisible(False)

        self.props_placeholder.setVisible(False)
        self.props_placeholder.setText("Select a layer to\nedit its properties")  # reset text

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
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.set_value(int(layer.opacity * 100))
        self.opacity_slider.blockSignals(False)

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
            self._layer_opac_slider.blockSignals(True)
            self._layer_opac_slider.setValue(int(layer.opacity * 100))
            self._layer_opac_lbl.setText(f"{int(layer.opacity*100)}%")
            self._layer_opac_slider.blockSignals(False)

        if is_paint:
            self.rotation_slider.blockSignals(True)
            self.rotation_slider.set_value(int(layer.rotation))
            self.rotation_slider.blockSignals(False)
            self.layer_bright.set_value(int(layer.brightness))
            self.layer_contrast.set_value(int(layer.contrast))
            self.layer_sat.set_value(int(layer.saturation))
            if layer.tint_color:
                tr, tg, tb = layer.tint_color
                c = QColor(tr, tg, tb)
                self._current_tint = c
                self.tint_preview.setStyleSheet(
                    f"background:{c.name()}; border:1px solid #555;")
            self.tint_strength_slider.set_value(int(layer.tint_strength * 100))

        if is_text:
            self.font_size_input.blockSignals(True)
            self.font_size_input.setText(str(layer.font_size))
            self.font_size_input.blockSignals(False)
            self.letter_spacing_input.blockSignals(True)
            self.letter_spacing_input.setText(str(layer.letter_spacing))
            self.letter_spacing_input.blockSignals(False)
            for cb, attr in [(self.bold_cb, "font_bold"),
                             (self.italic_cb, "font_italic"),
                             (self.upper_cb,  "font_uppercase")]:
                cb.blockSignals(True)
                cb.setChecked(getattr(layer, attr))
                cb.blockSignals(False)
            oi = self.orient_combo.findText(layer.text_orientation)
            self.orient_combo.blockSignals(True)
            self.orient_combo.setCurrentIndex(max(0, oi))
            self.orient_combo.blockSignals(False)
            self.outline_slider.set_value(layer.outline_size)
            self.shadow_slider.set_value(layer.shadow_offset)

        if is_fill and hasattr(self, '_fill_type_combo'):
            self._fill_type_combo.blockSignals(True)
            self._fill_type_combo.setCurrentText(layer.fill_type)
            self._fill_type_combo.blockSignals(False)
            self._fill_color_swatch.setStyleSheet(
                f"background: rgb{layer.fill_color}; border:1px solid #555;")
            self._fill_color2_swatch.setStyleSheet(
                f"background: rgb{layer.fill_color2}; border:1px solid #555;")
            self._fill_angle_slider.blockSignals(True)
            self._fill_angle_slider.set_value(int(layer.fill_angle))
            self._fill_angle_slider.blockSignals(False)

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
            self._mask_feather_slider.blockSignals(True)
            self._mask_feather_slider.set_value(int(layer.mask_feather))
            self._mask_feather_slider.blockSignals(False)

        if is_vector and hasattr(self, '_vec_stroke_swatch'):
            self._vec_stroke_swatch.setStyleSheet(
                f"background: rgb{layer.vector_stroke}; border:1px solid #555;")
            self._vec_fill_swatch.setStyleSheet(
                f"background: rgb{layer.vector_fill}; border:1px solid #555;")

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

    # ── Color Palette ─────────────────────────────────────────────────────────

    def set_brush_panel(self, bp):
        """Called by MainWindow after BrushPanel is created."""
        self._brush_panel_ref = bp

    # ── Font panel helpers ────────────────────────────────────────────────────

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
            from PySide6.QtGui import QFontDatabase
            sel_display, sel_userdata = self._font_list.selected()
            fam = sel_display or "Courier New"
            if sel_userdata:
                fid  = QFontDatabase.addApplicationFont(
                    os.path.join(FONTS_DIR, sel_userdata))
                fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                if fams:
                    fam = fams[0]
            sz = int(self.font_size_input.text() or "16")
        except Exception:
            fam, sz = "Courier New", 16
        self._font_preview_bar.update_preview(
            font_fam=fam, size=min(sz, 26),
            bold=self.bold_cb.isChecked(),
            italic=self.italic_cb.isChecked(),
            color=getattr(self, '_txt_color_val', QColor(220, 220, 240)),
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
            self._layer_opac_slider.blockSignals(True)
            self._layer_opac_slider.setValue(int(v))
            self._layer_opac_lbl.setText(f"{int(v)}%")
            self._layer_opac_slider.blockSignals(False)

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
        self._layer_opac_lbl.setText(f"{v}%")
        if not hasattr(self, '_canvas'): return
        self._canvas.update_selected_layer(opacity=v / 100.0)
        if hasattr(self, 'opacity_slider'):
            self.opacity_slider.blockSignals(True)
            self.opacity_slider.set_value(v)
            self.opacity_slider.blockSignals(False)

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
            self._current_tint = color
            self.tint_preview.setStyleSheet(
                f"background:{color.name()}; border:1px solid #555;")
            if hasattr(self, '_canvas'):
                self._canvas.update_selected_layer(
                    tint_color=(color.red(), color.green(), color.blue()))

    def _on_tint_strength(self, v: float):
        if hasattr(self, '_canvas'):
            self._canvas.update_selected_layer(tint_strength=v / 100.0)

    # ── Text layer slots ───────────────────────────────────────────────────────

    def _on_letter_spacing_changed(self, txt: str):
        try:
            v = int(txt)
            if hasattr(self, '_canvas'):
                self._canvas.update_selected_layer(letter_spacing=v)
        except ValueError:
            pass

    def _add_image_layer(self):
        if not hasattr(self, '_canvas'):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Add Image Layer", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self._canvas.add_image_layer(path)
            self._refresh_layer_list()

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
            self, "Select Texture", TEXTURES_DIR,
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

    def _add_text_layer(self):
        if not hasattr(self, '_canvas'):
            return
        text, ok = QInputDialog.getText(self, "Add Text", "Enter text:")
        if ok and text.strip():
            self._canvas.add_text_layer(text.strip())
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
        from PySide6.QtWidgets import QColorDialog
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
        from PySide6.QtWidgets import QColorDialog
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if not l: return
        init = QColor(*l.fill_color) if which == 1 else QColor(*l.fill_color2)
        col = QColorDialog.getColor(init, self)
        if not col.isValid(): return
        rgb = (col.red(), col.green(), col.blue())
        if which == 1:
            self._canvas.update_selected_layer(fill_color=rgb)
            self._fill_color_swatch.setStyleSheet(f"background:{col.name()}; border:1px solid #555;")
        else:
            self._canvas.update_selected_layer(fill_color2=rgb)
            self._fill_color2_swatch.setStyleSheet(f"background:{col.name()}; border:1px solid #555;")
        # Rebuild the fill pil_image
        self._rebuild_fill_image(l)

    def _rebuild_fill_image(self, layer):
        """Re-render a fill layer's pil_image from its fill_type/color settings."""
        from PIL import Image as PILImage
        import math
        w, h = layer.w or 100, layer.h or 100
        if layer.fill_type == "gradient":
            img = PILImage.new("RGBA", (w, h))
            c1 = layer.fill_color; c2 = layer.fill_color2
            angle = math.radians(layer.fill_angle)
            for py in range(h):
                for px in range(w):
                    t = (px * math.cos(angle) + py * math.sin(angle)) / max(1, w)
                    t = max(0., min(1., t))
                    r = int(c1[0] + (c2[0]-c1[0])*t)
                    g = int(c1[1] + (c2[1]-c1[1])*t)
                    b = int(c1[2] + (c2[2]-c1[2])*t)
                    img.putpixel((px,py),(r,g,b,255))
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
            l.name = f"🔧 {choice}"
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
        from PySide6.QtWidgets import QColorDialog
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if not l: return
        col = QColorDialog.getColor(QColor(*l.mask_color), self)
        if col.isValid():
            rgb = (col.red(), col.green(), col.blue())
            self._canvas.update_selected_layer(mask_color=rgb)
            self._mask_color_swatch.setStyleSheet(f"background:{col.name()}; border:1px solid #555;")

    def _pick_vector_color(self, which: str):
        from PySide6.QtWidgets import QColorDialog
        if not hasattr(self, '_canvas'): return
        l = self._canvas.selected_layer()
        if not l: return
        init = QColor(*(l.vector_stroke if which == "stroke" else l.vector_fill))
        col = QColorDialog.getColor(init, self)
        if col.isValid():
            rgb = (col.red(), col.green(), col.blue())
            if which == "stroke":
                self._canvas.update_selected_layer(vector_stroke=rgb)
                self._vec_stroke_swatch.setStyleSheet(f"background:{col.name()}; border:1px solid #555;")
            else:
                self._canvas.update_selected_layer(vector_fill=rgb)
                self._vec_fill_swatch.setStyleSheet(f"background:{col.name()}; border:1px solid #555;")

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
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Fonts",
            os.path.expanduser("~"),
            "Fonts & Packs (*.zip *.ttf *.otf *.woff *.woff2);;"
            "ZIP Font Pack (*.zip);;"
            "Font Files (*.ttf *.otf *.woff *.woff2)"
        )
        if not paths:
            return

        result = import_fonts(paths, FONTS_DIR)
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
        from PySide6.QtGui import QFontDatabase
        current = self.font_combo.currentText()
        self.font_combo.blockSignals(True)
        self.font_combo.clear()
        self.font_combo.addItem("default")

        if os.path.isdir(FONTS_DIR):
            entries = []
            for root, _dirs, files in os.walk(FONTS_DIR):
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in (".ttf", ".otf"):
                        continue
                    fpath = os.path.join(root, fname)
                    # Get Qt family name (already registered at startup)
                    fid   = QFontDatabase.addApplicationFont(fpath)
                    fams  = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                    display = fams[0] if fams else (
                        os.path.splitext(fname)[0].replace("-", " ").replace("_", " ")
                    )
                    # Store relative path from FONTS_DIR as userData
                    rel = os.path.relpath(fpath, FONTS_DIR)
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

    def _on_font_size_changed(self, txt: str):
        try:
            size = int(txt)
            if size > 0 and hasattr(self, '_canvas'):
                self._canvas.update_selected_layer(font_size=size)
        except ValueError:
            pass

    def _pick_text_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            if hasattr(self, '_txt_color_swatch'):
                self._txt_color_swatch.setStyleSheet(
                    f"background:{color.name()}; border:1px solid #555; border-radius:3px;")
                self._txt_color_val = color
            self._update_font_preview()
            if hasattr(self, '_canvas'):
                self._canvas.update_selected_layer(
                    font_color=(color.red(), color.green(), color.blue()))