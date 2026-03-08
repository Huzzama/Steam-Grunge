"""
tabManager.py  —  Multi-tab workspace system for Steam Grunge Editor.

Each tab is a fully independent WorkspaceTab containing:
  - Its own PreviewCanvas (layers, template, undo history)
  - Its own EditorPanel  (effects, layer list, properties)
  - Its own SearchPanel  (game search, artwork)
  - Its own AppState     (game name, template, effects values)
  - Its own BrushPanel   (shared UI but connected to its canvas)
  - Its own FloatingContextTb

TabBar sits at the very top of the window (browser-style).
  - Click tab  → switch workspace
  - "+" button → new tab
  - "×" button → close tab (min 1 tab always stays open)

Usage (in MainWindow._build_ui):
    self.tab_manager = TabManager(parent_window=self)
    layout.addWidget(self.tab_manager)
"""
from __future__ import annotations
from typing import List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QLabel, QSizePolicy, QScrollArea, QFrame,
    QSplitter,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui  import QColor

from app.ui.searchPanel        import SearchPanel
from app.ui.editorPanel        import EditorPanel
from app.ui.canvas.previewCanvas import PreviewCanvas
from app.ui.brushPanel         import BrushPanel
from app.ui.floatingContextTb  import FloatingContextTb
from app.editor                import compositor
from app.editor                import exports as exporter
from app.state                 import AppState          # class, not singleton


# ── Per-tab state ──────────────────────────────────────────────────────────────
class WorkspaceTab(QWidget):
    """One fully independent editor workspace."""

    status_changed = Signal(str)   # emits status text for the main status bar

    def __init__(self, tab_id: int, parent=None):
        super().__init__(parent)
        self.tab_id   = tab_id
        self.label    = f"Tab {tab_id}"   # updated when a game is selected
        self.state    = AppState()        # own independent state

        self._compose_timer = QTimer()
        self._compose_timer.setSingleShot(True)
        self._compose_timer.setInterval(120)
        self._compose_timer.timeout.connect(self._do_compose)

        self._build()

    # ── build layout ──────────────────────────────────────────────────────────
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)

        # Left — search
        self.search_panel = SearchPanel()
        self.search_panel.artwork_selected.connect(self._on_artwork_selected)
        self.search_panel.artwork_layer_ready.connect(self._on_artwork_layer_ready)
        self.search_panel.setFixedWidth(340)
        splitter.addWidget(self.search_panel)

        # Center — canvas
        self.preview_canvas = PreviewCanvas()
        splitter.addWidget(self.preview_canvas)

        # Right — editor
        self.editor_panel = EditorPanel()
        self.editor_panel.settings_changed.connect(self.schedule_compose)
        self.editor_panel.template_changed.connect(self._on_template_changed)
        self.editor_panel.setFixedWidth(420)
        self.editor_panel.setContentsMargins(0, 0, 8, 0)
        splitter.addWidget(self.editor_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        self.editor_panel.set_canvas(self.preview_canvas, tab_state=self.state, tab_ref=self)

        root.addWidget(splitter, 1)

        # Floating context toolbar
        self.ctx_tb = FloatingContextTb(self.preview_canvas)
        self.ctx_tb.set_canvas(self.preview_canvas)

        # Brush panel (hidden by default)
        self.brush_panel = BrushPanel()
        self.brush_panel.setFixedWidth(248)
        self.brush_panel.setVisible(False)
        self.brush_panel.set_canvas(self.preview_canvas)
        root.addWidget(self.brush_panel, 0)

        self.editor_panel.set_brush_panel(self.brush_panel)

        # Initial render
        self._do_compose()

    # ── compose ───────────────────────────────────────────────────────────────
    def schedule_compose(self):
        self._compose_timer.start()

    def _do_compose(self):
        try:
            self.preview_canvas.set_template(self.state.current_template)
            r, g, b = getattr(self.state, "bg_color", (0, 0, 0))
            self.preview_canvas.set_background_color(QColor(r, g, b))
            img = compositor.compose(self.state)
            self.state.composed_image = img
            self.preview_canvas.update()
            size = (f"{self.preview_canvas._doc_size.width()}"
                    f"×{self.preview_canvas._doc_size.height()}")
            self.status_changed.emit(
                f"Template: {self.state.current_template.upper()}  |  "
                f"Size: {size}  |  "
                f"Game: {self.state.selected_game_name or '—'}"
            )
        except Exception as e:
            import traceback
            self.status_changed.emit(f"Render error: {e}")
            traceback.print_exc()

    # ── slots ─────────────────────────────────────────────────────────────────
    def _on_artwork_selected(self, pil_image, game_name: str):
        # Invalidate AppID cache if game changed
        if game_name and game_name != self.state.selected_game_name:
            from app.services.exportFlow import invalidate_app_id_cache
            invalidate_app_id_cache(self)
        self.state.base_image        = pil_image
        self.state.selected_game_name = game_name
        if not self.state.spine_text:
            self.state.spine_text = game_name
            self.editor_panel.set_spine_text(game_name)
        self._update_label(game_name)
        self.status_changed.emit(f"Loaded: {game_name}")
        self.schedule_compose()

    def _on_artwork_layer_ready(self, local_path: str, game_name: str):
        # Invalidate AppID cache if game changed
        if game_name and game_name != self.state.selected_game_name:
            from app.services.exportFlow import invalidate_app_id_cache
            invalidate_app_id_cache(self)
        self.state.selected_game_name = game_name
        if not self.state.spine_text and game_name:
            self.state.spine_text = game_name
            self.editor_panel.set_spine_text(game_name)
        self.preview_canvas.add_image_layer(local_path, name=game_name or "Artwork")
        self.editor_panel._refresh_layer_list()
        self._update_label(game_name)
        self.status_changed.emit(f"Added layer: {game_name or local_path}")

    def _on_template_changed(self, template: str):
        self.state.current_template = template
        self.schedule_compose()

    def _update_label(self, game_name: str):
        if game_name:
            # Shorten long names to fit the tab
            self.label = game_name[:18] + ("…" if len(game_name) > 18 else "")
        else:
            self.label = f"Tab {self.tab_id}"

    # ── export ────────────────────────────────────────────────────────────────
    def export(self, parent_widget=None) -> str | None:
        """Run full export flow: AppID confirm (once) → save with Steam filename."""
        from app.services.exportFlow import run_export_flow
        return run_export_flow(self, parent_widget=parent_widget)

    # ── undo / redo ───────────────────────────────────────────────────────────
    def undo(self):
        self.preview_canvas.undo()
        self.editor_panel._refresh_layer_list()

    def redo(self):
        self.preview_canvas.redo()
        self.editor_panel._refresh_layer_list()

    # ── brush panel toggle ────────────────────────────────────────────────────
    def toggle_brush_panel(self, visible: bool | None = None):
        if visible is None:
            visible = not self.brush_panel.isVisible()
        self.brush_panel.setVisible(visible)


# ── Tab bar widget ─────────────────────────────────────────────────────────────
class TabBar(QWidget):
    """
    Horizontal browser-style tab bar.
    Emits tab_switched(index) and tab_closed(index).
    """
    tab_switched = Signal(int)
    tab_closed   = Signal(int)
    tab_new      = Signal()

    _TAB_STYLE = """
        QPushButton {{
            background: {bg};
            color: {fg};
            border: none;
            border-bottom: {bb};
            border-right: 1px solid #1e1e1e;
            font-family: 'Courier New';
            font-size: 12px;
            padding: 0 10px;
            min-width: 120px;
            max-width: 200px;
            height: 30px;
            text-align: left;
        }}
        QPushButton:hover {{ background: #222233; color: #ddd; }}
    """
    _CLOSE_STYLE = """
        QPushButton {
            background: transparent;
            color: #555;
            border: none;
            font-size: 13px;
            padding: 0 4px;
            min-width: 18px;
            max-width: 18px;
            height: 30px;
        }
        QPushButton:hover { color: #ff6666; background: transparent; }
    """
    _ADD_STYLE = """
        QPushButton {
            background: transparent;
            color: #666;
            border: none;
            border-left: 1px solid #1e1e1e;
            font-size: 18px;
            padding: 0 12px;
            min-width: 38px;
            height: 30px;
        }
        QPushButton:hover { color: #88cc88; background: #1a1a2a; }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setStyleSheet("background:#111111; border-bottom:1px solid #1e1e1e;")

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._tab_widgets: List[QWidget] = []   # each is a QWidget holding label+close
        self._active = 0

        # "+" new tab button at the end
        self._btn_new = QPushButton("+")
        self._btn_new.setStyleSheet(self._ADD_STYLE)
        self._btn_new.setToolTip("New tab  (Ctrl+T)")
        self._btn_new.clicked.connect(self.tab_new.emit)

        self._layout.addStretch(1)
        self._layout.addWidget(self._btn_new)

    # ── public API ────────────────────────────────────────────────────────────
    def add_tab(self, label: str) -> int:
        idx = len(self._tab_widgets)
        self._insert_tab_widget(idx, label)
        self._refresh_styles()
        return idx

    def rename_tab(self, idx: int, label: str):
        if 0 <= idx < len(self._tab_widgets):
            btn = self._tab_widgets[idx].findChild(QPushButton, "tab_label")
            if btn:
                btn.setText(f"  {label}")
        self._refresh_styles()

    def set_active(self, idx: int):
        self._active = idx
        self._refresh_styles()

    def count(self) -> int:
        return len(self._tab_widgets)

    # ── internals ─────────────────────────────────────────────────────────────
    def _insert_tab_widget(self, idx: int, label: str):
        container = QWidget()
        container.setFixedHeight(30)
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        btn_label = QPushButton(f"  {label}")
        btn_label.setObjectName("tab_label")
        btn_label.setFlat(True)
        btn_label.clicked.connect(lambda _, i=idx: self.tab_switched.emit(i))

        btn_close = QPushButton("×")
        btn_close.setObjectName("tab_close")
        btn_close.setStyleSheet(self._CLOSE_STYLE)
        btn_close.setToolTip("Close tab")
        btn_close.clicked.connect(lambda _, i=idx: self.tab_closed.emit(i))

        lay.addWidget(btn_label, 1)
        lay.addWidget(btn_close, 0)

        self._tab_widgets.insert(idx, container)
        # Insert before the stretch + new button (last 2 items)
        insert_pos = self._layout.count() - 2
        self._layout.insertWidget(insert_pos, container)

    def _refresh_styles(self):
        for i, container in enumerate(self._tab_widgets):
            btn = container.findChild(QPushButton, "tab_label")
            if not btn:
                continue
            active = (i == self._active)
            btn.setStyleSheet(self._TAB_STYLE.format(
                bg  = "#1e1e2e" if active else "#111111",
                fg  = "#ddddff" if active else "#666677",
                bb  = "2px solid #5566cc" if active else "2px solid transparent",
            ))

    def remove_tab(self, idx: int):
        if not (0 <= idx < len(self._tab_widgets)):
            return
        container = self._tab_widgets.pop(idx)
        self._layout.removeWidget(container)
        container.deleteLater()
        # Re-wire close buttons so indices stay correct
        self._rewire_buttons()
        self._refresh_styles()

    def _rewire_buttons(self):
        for i, container in enumerate(self._tab_widgets):
            btn_label = container.findChild(QPushButton, "tab_label")
            btn_close = container.findChild(QPushButton, "tab_close")
            if btn_label:
                try: btn_label.clicked.disconnect()
                except Exception: pass
                btn_label.clicked.connect(lambda _, i=i: self.tab_switched.emit(i))
            if btn_close:
                try: btn_close.clicked.disconnect()
                except Exception: pass
                btn_close.clicked.connect(lambda _, i=i: self.tab_closed.emit(i))


# ── Tab manager (tab bar + stacked workspaces) ─────────────────────────────────
class TabManager(QWidget):
    """
    Top-level widget that owns the TabBar + QStackedWidget of WorkspaceTabs.
    Drop this into MainWindow's central layout.

    Public API used by MainWindow:
      .current_tab()         → WorkspaceTab
      .add_tab()             → WorkspaceTab
      .close_tab(idx)
      .switch_tab(idx)
      .tab_count()           → int
    """

    status_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tab_bar   = TabBar()
        self._stack     = QStackedWidget()
        self._tabs:     List[WorkspaceTab] = []
        self._next_id   = 1

        root.addWidget(self._tab_bar)
        root.addWidget(self._stack, 1)

        self._tab_bar.tab_switched.connect(self.switch_tab)
        self._tab_bar.tab_closed.connect(self.close_tab)
        self._tab_bar.tab_new.connect(self.add_tab)

        # Create the first tab
        self.add_tab()

    # ── public API ────────────────────────────────────────────────────────────
    def current_tab(self) -> WorkspaceTab:
        return self._tabs[self._stack.currentIndex()]

    def tab_count(self) -> int:
        return len(self._tabs)

    def add_tab(self) -> WorkspaceTab:
        tab = WorkspaceTab(tab_id=self._next_id)
        tab.status_changed.connect(self.status_changed)
        self._next_id += 1
        self._tabs.append(tab)
        self._stack.addWidget(tab)
        idx = len(self._tabs) - 1
        self._tab_bar.add_tab(tab.label)
        self.switch_tab(idx)
        return tab

    def switch_tab(self, idx: int):
        if not (0 <= idx < len(self._tabs)):
            return
        # Hide floating toolbar of every tab, show only the active one
        for i, t in enumerate(self._tabs):
            if hasattr(t, 'ctx_tb'):
                t.ctx_tb.hide()
        self._stack.setCurrentIndex(idx)
        self._tab_bar.set_active(idx)
        # Emit current status for the main status bar
        tab = self._tabs[idx]
        self.status_changed.emit(
            f"Template: {tab.state.current_template.upper()}  |  "
            f"Game: {tab.state.selected_game_name or '—'}"
        )

    def close_tab(self, idx: int):
        if len(self._tabs) <= 1:
            return   # always keep at least one tab
        tab = self._tabs.pop(idx)
        self._stack.removeWidget(tab)
        tab.deleteLater()
        self._tab_bar.remove_tab(idx)
        # Clamp active index
        new_idx = min(idx, len(self._tabs) - 1)
        self.switch_tab(new_idx)

    # ── proxy helpers used by MainWindow ──────────────────────────────────────
    @property
    def preview_canvas(self) -> PreviewCanvas:
        return self.current_tab().preview_canvas

    @property
    def editor_panel(self) -> EditorPanel:
        return self.current_tab().editor_panel

    @property
    def brush_panel(self) -> BrushPanel:
        return self.current_tab().brush_panel

    def rename_current(self, label: str):
        idx = self._stack.currentIndex()
        self._tabs[idx].label = label
        self._tab_bar.rename_tab(idx, label)