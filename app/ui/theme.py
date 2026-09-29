"""
Steam Grunge Editor — the one place the look lives ("cyber-sigil": near-black
blue-tinted surfaces, sky accent, Courier New everywhere, tight radii).

    from app.ui.theme import C, SP, R, apply, repolish
    apply(app)                     # once, after QApplication()

Widgets pick styles through dynamic properties instead of inline QSS:
    QLabel[role]     title · section · eyebrow · body · dim · muted · value · mono
    QPushButton[variant]  default · primary · ghost · danger · icon · chip · tool
    QPushButton[active="true"]   (chips, template picks, tool toggles)
    QFrame[surface]  panel · card · inset · divider
    QWidget[tone]    accent · green · red · gold   (thin colour hint for labels)
After changing a property at runtime call repolish(widget).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette

# ── Colour tokens ─────────────────────────────────────────────────────────────
C = {
    "bg":            "#080a0e",   # window
    "bg_deep":       "#040608",   # menu bar / status bar / tab strip
    "surface":       "#060c14",   # inputs, buttons, cards
    "surface_2":     "#0a1520",   # hover / inset
    "surface_3":     "#0d1f30",   # selected rows, active chips
    "hover":         "#0a1a28",
    "border":        "#0d2030",
    "border_strong": "#1a4060",
    "text":          "#c8d8e8",
    "text_2":        "#90b8c8",
    "text_dim":      "#607888",
    "text_muted":    "#304a5a",
    "accent":        "#38bdf8",
    "accent_bright": "#7dd3fc",
    "accent_dim":    "#0d2a3e",
    "on_accent":     "#03111c",
    "green":         "#4ade80",
    "green_dim":     "#0b2a1a",
    "gold":          "#fbbf24",
    "gold_dim":      "#2a2008",
    "red":           "#f87171",
    "red_dim":       "#2a0f12",
    "violet":        "#a78bfa",
}

SP = {"xs": 4, "sm": 6, "md": 10, "lg": 14, "xl": 20}
R  = {"sm": 2, "md": 3, "lg": 4}
FONT = "Courier New"
FS = {"xs": 10, "sm": 11, "base": 12, "md": 13, "lg": 15, "xl": 18, "2xl": 24}

# every control is this tall → rows line up, nothing overlaps
CONTROL_H = 28

_tmp: dict[str, str] = {}


def _svg_file(name: str, svg: str) -> str:
    """QSS `image:` needs a file url; write tinted SVGs once per run."""
    if name not in _tmp:
        f = Path(tempfile.gettempdir()) / f"steamgrunge_{name}.svg"
        try:
            f.write_text(svg, encoding="utf-8")
            _tmp[name] = f.as_posix()
        except OSError:
            _tmp[name] = ""
    return _tmp[name]


def _chevron(color: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="m6 9 6 6 6-6"/></svg>')


def _check(color: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="M20 6 9 17l-5-5"/></svg>')


def font(size: str = "base", bold: bool = False) -> QFont:
    f = QFont(FONT, FS[size])
    f.setBold(bold)
    return f


def stylesheet() -> str:
    c = C
    chev = _svg_file("chevron", _chevron(c["accent"]))
    chev_dim = _svg_file("chevron_dim", _chevron(c["text_dim"]))
    check = _svg_file("check", _check(c["on_accent"]))
    return f"""
    /* ── base ─────────────────────────────────────────────────────────── */
    QMainWindow, QDialog {{ background: {c['bg']}; }}
    QWidget {{ background: transparent; color: {c['text']}; font-family: '{FONT}', 'Consolas', monospace;
               font-size: {FS['base']}px; }}
    QToolTip {{ background: {c['surface_3']}; color: {c['text']}; border: 1px solid {c['border_strong']};
                padding: 5px 8px; border-radius: {R['sm']}px; }}

    /* ── text roles ───────────────────────────────────────────────────── */
    QLabel[role="title"]   {{ color: {c['text']}; font-size: {FS['lg']}px; font-weight: bold; letter-spacing: 3px; }}
    QLabel[role="section"] {{ color: {c['text_muted']}; font-size: {FS['sm']}px; font-weight: bold; letter-spacing: 3px; }}
    QLabel[role="eyebrow"] {{ color: {c['text_dim']}; font-size: {FS['xs']}px; letter-spacing: 2px; }}
    QLabel[role="body"]    {{ color: {c['text_2']}; }}
    QLabel[role="dim"]     {{ color: {c['text_dim']}; }}
    QLabel[role="muted"]   {{ color: {c['text_muted']}; font-size: {FS['sm']}px; }}
    QLabel[role="value"]   {{ color: {c['accent']}; font-size: {FS['base']}px; font-weight: bold; }}
    QLabel[role="mono"]    {{ color: {c['text_2']}; }}
    QLabel[tone="accent"]  {{ color: {c['accent']}; }}
    QLabel[tone="green"]   {{ color: {c['green']}; }}
    QLabel[tone="red"]     {{ color: {c['red']}; }}
    QLabel[tone="gold"]    {{ color: {c['gold']}; }}

    /* ── surfaces ─────────────────────────────────────────────────────── */
    QFrame[surface="panel"]   {{ background: {c['bg']}; border: none; }}
    QFrame[surface="card"]    {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {R['md']}px; }}
    QFrame[surface="card"][hoverable="true"]:hover {{ border-color: {c['border_strong']}; }}
    QFrame[surface="card"][active="true"] {{ border-color: {c['accent']}; background: {c['accent_dim']}; }}
    QFrame[surface="vdivider"] {{ background: {c['border']}; max-width: 1px; min-width: 1px; border: none; }}
    QFrame[surface="inset"]   {{ background: {c['bg_deep']}; border: 1px solid {c['border']}; border-radius: {R['sm']}px; }}
    QFrame[surface="divider"] {{ background: {c['border']}; max-height: 1px; min-height: 1px; border: none; }}
    QFrame[surface="strip"]   {{ background: {c['bg_deep']}; border-bottom: 1px solid {c['border']}; }}

    /* ── menu bar / menus ─────────────────────────────────────────────── */
    QMenuBar {{ background: {c['bg_deep']}; color: {c['text_dim']}; padding: 2px 4px;
                border-bottom: 1px solid {c['border']}; spacing: 2px; }}
    QMenuBar::item {{ padding: 4px 10px; border-radius: {R['sm']}px; }}
    QMenuBar::item:selected {{ background: {c['border']}; color: {c['accent']}; }}
    QMenu {{ background: {c['bg']}; border: 1px solid {c['border']}; color: {c['text_2']}; padding: 4px 0; }}
    QMenu::item {{ padding: 6px 24px 6px 14px; }}
    QMenu::item:selected {{ background: {c['surface_3']}; color: {c['accent']}; }}
    QMenu::item:disabled {{ color: {c['text_muted']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 3px 8px; }}
    QMenu::icon {{ margin-left: 8px; }}

    /* ── status bar ───────────────────────────────────────────────────── */
    QStatusBar {{ background: {c['bg_deep']}; color: {c['text_dim']}; border-top: 1px solid {c['border']};
                  font-size: {FS['sm']}px; min-height: 26px; }}
    QStatusBar::item {{ border: none; }}

    /* ── buttons ──────────────────────────────────────────────────────── */
    QPushButton {{ background: {c['surface']}; color: {c['text_dim']}; border: 1px solid {c['border']};
                   border-radius: {R['sm']}px; padding: 0 12px; min-height: {CONTROL_H}px; max-height: {CONTROL_H}px; }}
    QPushButton:hover {{ background: {c['hover']}; color: {c['accent']}; border-color: {c['accent']}; }}
    QPushButton:pressed {{ background: {c['bg_deep']}; color: {c['accent_bright']}; border-color: {c['accent_bright']}; }}
    QPushButton:disabled {{ color: {c['text_muted']}; border-color: {c['border']}; background: {c['bg']}; }}
    QPushButton:checked, QPushButton[active="true"] {{ background: {c['accent_dim']}; color: {c['accent']};
                                                       border-color: {c['accent']}; }}
    QPushButton[variant="primary"] {{ background: {c['accent_dim']}; color: {c['accent']}; border-color: {c['accent']};
                                      font-weight: bold; letter-spacing: 2px; min-height: 34px; max-height: 34px; }}
    QPushButton[variant="primary"]:hover {{ background: {c['accent']}; color: {c['on_accent']}; }}
    QPushButton[variant="primary"]:disabled {{ background: {c['bg']}; color: {c['text_muted']}; border-color: {c['border']}; }}
    QPushButton[variant="success"] {{ background: {c['green_dim']}; color: {c['green']}; border-color: {c['green']}; }}
    QPushButton[variant="danger"]  {{ color: {c['red']}; border-color: {c['red_dim']}; }}
    QPushButton[variant="danger"]:hover {{ background: {c['red_dim']}; border-color: {c['red']}; }}
    QPushButton[variant="ghost"] {{ background: transparent; border-color: transparent; }}
    QPushButton[variant="ghost"]:hover {{ background: {c['hover']}; border-color: {c['border']}; }}
    QPushButton[variant="link"] {{ background: transparent; border: none; color: {c['accent']}; padding: 0 4px;
                                   text-decoration: underline; }}
    QPushButton[variant="icon"] {{ padding: 0; min-width: {CONTROL_H}px; max-width: {CONTROL_H}px; }}
    QPushButton[variant="mini"] {{ padding: 0; min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px;
                                   background: transparent; border-color: transparent; }}
    QPushButton[variant="mini"]:hover {{ background: {c['hover']}; border-color: {c['border']}; }}
    QPushButton[variant="tool"] {{ padding: 0; min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px;
                                   background: transparent; border-color: transparent; }}
    QPushButton[variant="tool"]:hover {{ background: {c['hover']}; border-color: {c['border']}; }}
    QPushButton[variant="tool"]:checked, QPushButton[variant="tool"][active="true"] {{ background: {c['accent_dim']};
                                   border-color: {c['accent']}; }}
    QPushButton[variant="chip"] {{ padding: 0 10px; min-height: 24px; max-height: 24px; font-size: {FS['sm']}px;
                                   border-radius: {R['lg']}px; }}
    QPushButton[variant="template"] {{ text-align: left; padding: 0 10px; min-height: 30px; max-height: 30px; }}
    QPushButton::menu-indicator {{ image: none; width: 0; }}

    QToolButton {{ background: transparent; color: {c['text_dim']}; border: 1px solid transparent;
                   border-radius: {R['sm']}px; padding: 4px; }}
    QToolButton:hover {{ background: {c['hover']}; color: {c['accent']}; border-color: {c['border']}; }}
    QToolButton:checked {{ background: {c['accent_dim']}; color: {c['accent']}; border-color: {c['accent']}; }}
    QToolBar {{ background: {c['bg_deep']}; border: none; border-bottom: 1px solid {c['border']}; spacing: 2px; padding: 2px 4px; }}
    QToolBar::separator {{ background: {c['border']}; width: 1px; margin: 4px 4px; }}

    /* ── inputs ───────────────────────────────────────────────────────── */
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {R['sm']}px;
        color: {c['text_2']}; padding: 0 8px; min-height: {CONTROL_H}px; selection-background-color: {c['accent_dim']};
        selection-color: {c['text']}; }}
    QPlainTextEdit, QTextEdit {{ padding: 6px 8px; }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QPlainTextEdit:hover {{ border-color: {c['border_strong']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border-color: {c['accent']}; background: {c['bg_deep']}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {c['text_muted']}; }}
    QLineEdit[error="true"] {{ border-color: {c['red']}; }}
    QComboBox {{ max-height: {CONTROL_H}px; padding-right: 26px; }}
    QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; border: none; width: 24px; }}
    QComboBox::down-arrow {{ image: url({chev}); width: 12px; height: 12px; }}
    QComboBox::down-arrow:disabled {{ image: url({chev_dim}); }}
    QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['border_strong']}; color: {c['text_2']};
                                   selection-background-color: {c['accent_dim']}; selection-color: {c['text']};
                                   outline: none; padding: 4px 0; }}
    QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 0 8px; }}
    QSpinBox, QDoubleSpinBox {{ padding-right: 4px; max-height: {CONTROL_H}px; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 0; height: 0; border: none; }}
    QAbstractSpinBox {{ min-width: 44px; }}

    /* ── checkbox / radio ─────────────────────────────────────────────── */
    QCheckBox, QRadioButton {{ color: {c['text_dim']}; spacing: 8px; min-height: 22px; }}
    QCheckBox:hover, QRadioButton:hover {{ color: {c['text_2']}; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {c['border_strong']};
                                                     background: {c['surface']}; border-radius: {R['sm']}px; }}
    QRadioButton::indicator {{ border-radius: 7px; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {c['accent']}; }}
    QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({check}); }}
    QRadioButton::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}

    /* ── sliders ──────────────────────────────────────────────────────── */
    QSlider {{ min-height: 20px; }}
    QSlider::groove:horizontal {{ height: 2px; background: {c['border']}; border-radius: 1px; }}
    QSlider::sub-page:horizontal {{ background: {c['border_strong']}; height: 2px; }}
    QSlider::handle:horizontal {{ background: {c['accent']}; border: none; width: 12px; height: 12px;
                                  margin: -5px 0; border-radius: {R['sm']}px; }}
    QSlider::handle:horizontal:hover {{ background: {c['accent_bright']}; }}
    QSlider::handle:horizontal:disabled {{ background: {c['text_muted']}; }}
    QSlider::groove:vertical {{ width: 2px; background: {c['border']}; border-radius: 1px; }}
    QSlider::add-page:vertical {{ background: {c['border_strong']}; width: 2px; }}
    QSlider::handle:vertical {{ background: {c['accent']}; border: none; width: 12px; height: 12px;
                                margin: 0 -5px; border-radius: {R['sm']}px; }}
    QSlider::handle:vertical:hover {{ background: {c['accent_bright']}; }}

    /* ── progress ─────────────────────────────────────────────────────── */
    QProgressBar {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {R['sm']}px;
                    height: 6px; text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: {R['sm']}px; }}

    /* ── lists / trees ────────────────────────────────────────────────── */
    QListWidget, QListView, QTreeView, QTableView {{ background: {c['bg_deep']}; border: 1px solid {c['border']};
        border-radius: {R['sm']}px; color: {c['text_2']}; outline: none; alternate-background-color: {c['bg']}; }}
    QListWidget::item, QListView::item, QTreeView::item {{ padding: 4px 6px; border-radius: {R['sm']}px; }}
    QListWidget::item:hover, QListView::item:hover, QTreeView::item:hover {{ background: {c['surface_2']}; }}
    QListWidget::item:selected, QListView::item:selected, QTreeView::item:selected {{ background: {c['accent_dim']};
        color: {c['text']}; }}
    QHeaderView::section {{ background: {c['bg_deep']}; color: {c['text_dim']}; border: none;
        border-bottom: 1px solid {c['border']}; padding: 4px 6px; }}

    /* ── group boxes (legacy sections) ────────────────────────────────── */
    QGroupBox {{ border: 1px solid {c['border']}; border-radius: {R['md']}px; margin-top: 16px; padding: 10px 8px 8px 8px;
                 font-size: {FS['sm']}px; font-weight: bold; color: {c['text_muted']}; letter-spacing: 3px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; background: {c['bg']}; }}

    /* ── scrollbars ───────────────────────────────────────────────────── */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: {c['bg_deep']}; width: 8px; border-left: 1px solid {c['border']}; }}
    QScrollBar::handle:vertical {{ background: {c['border_strong']}; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: {c['bg_deep']}; height: 8px; border-top: 1px solid {c['border']}; }}
    QScrollBar::handle:horizontal {{ background: {c['border_strong']}; min-width: 24px; }}
    QScrollBar::handle:horizontal:hover {{ background: {c['accent']}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* ── splitter / tabs ──────────────────────────────────────────────── */
    QSplitter::handle {{ background: {c['border']}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}
    QSplitter::handle:hover {{ background: {c['accent']}; }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: {R['sm']}px; top: -1px; }}
    QTabBar::tab {{ background: {c['bg_deep']}; color: {c['text_dim']}; border: 1px solid {c['border']}; border-bottom: none;
                    padding: 6px 14px; margin-right: 2px; border-top-left-radius: {R['sm']}px; border-top-right-radius: {R['sm']}px; }}
    QTabBar::tab:selected {{ background: {c['bg']}; color: {c['accent']}; }}
    QTabBar::tab:hover {{ color: {c['text']}; }}

    /* ── dialogs / message boxes ──────────────────────────────────────── */
    QMessageBox {{ background: {c['bg']}; }}
    QMessageBox QLabel {{ color: {c['text']}; }}
    QMessageBox QPushButton {{ min-width: 84px; }}
    QDialogButtonBox QPushButton {{ min-width: 84px; }}
    """


def palette() -> QPalette:
    p = QPalette()
    m = {
        QPalette.ColorRole.Window: C["bg"], QPalette.ColorRole.WindowText: C["text"],
        QPalette.ColorRole.Base: C["surface"], QPalette.ColorRole.AlternateBase: C["bg"],
        QPalette.ColorRole.Text: C["text"], QPalette.ColorRole.Button: C["surface"],
        QPalette.ColorRole.ButtonText: C["text"], QPalette.ColorRole.Highlight: C["accent"],
        QPalette.ColorRole.HighlightedText: C["on_accent"], QPalette.ColorRole.ToolTipBase: C["surface_3"],
        QPalette.ColorRole.ToolTipText: C["text"], QPalette.ColorRole.PlaceholderText: C["text_muted"],
        QPalette.ColorRole.Link: C["accent"],
    }
    for role, hexv in m.items():
        p.setColor(role, QColor(hexv))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(C["text_muted"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(C["text_muted"]))
    return p


def apply(app) -> None:
    """Fusion style + palette + the global stylesheet. Call once after QApplication()."""
    app.setStyle("Fusion")
    app.setPalette(palette())
    app.setFont(font("base"))
    app.setStyleSheet(stylesheet())


def repolish(widget) -> None:
    """Re-run QSS after a dynamic property (active / variant / role / tone) changed."""
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()
