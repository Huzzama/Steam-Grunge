from __future__ import annotations
from typing import List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QLabel, QSizePolicy, QScrollArea, QFrame,
    QSplitter,
)
from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtGui  import QColor, QCursor, QPainter, QPixmap

from app.ui.kit   import IconButton, hbox, label
from app.ui.theme import C, CONTROL_H, SP, repolish

from app.ui.searchPanel        import SearchPanel
from app.ui.editorPanel        import EditorPanel
from app.ui.canvas.previewCanvas import PreviewCanvas
from app.ui.floatingContextTb  import FloatingContextTb
from app.state                 import AppState          # class, not singleton


# ── Per-tab state ──────────────────────────────────────────────────────────────
# Side panel widths: they open at *_MAX_W and the user can drag them narrower.
SEARCH_MIN_W, SEARCH_MAX_W = 300, 400
EDITOR_MIN_W, EDITOR_MAX_W = 360, 500
CANVAS_MIN_W = 480          # the artwork is the point — keep it visible


class WorkspaceTab(QWidget):
    """One fully independent editor workspace."""

    status_changed = Signal(str)   # emits status text for the main status bar
    label_changed  = Signal(str)   # tab title (game name / project name)
    dirty_changed  = Signal()      # unsaved-changes flag toggled

    def __init__(self, tab_id: int, parent=None):
        super().__init__(parent)
        self.tab_id   = tab_id
        self.label    = f"Tab {tab_id}"   # updated when a game is selected
        self.state    = AppState()        # own independent state

        # ── Project file state (per tab) ──────────────────────────────────
        self.project_path: str = ""       # "" = not yet saved to disk
        self.dirty: bool       = False    # True when there are unsaved changes

        # Main compose timer — fires after user stops dragging
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
        self.search_panel.artwork_layer_ready.connect(self._on_artwork_layer_ready)
        self.search_panel.game_selected.connect(self._on_game_selected)
        self.search_panel.setMinimumWidth(SEARCH_MIN_W)
        self.search_panel.setMaximumWidth(SEARCH_MAX_W)
        splitter.addWidget(self.search_panel)

        # Center — canvas (takes all remaining space)
        self.preview_canvas = PreviewCanvas()
        self.preview_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        splitter.addWidget(self.preview_canvas)

        # Right — editor
        self.editor_panel = EditorPanel()
        self.editor_panel.settings_changed.connect(self.schedule_compose)
        self.editor_panel.template_changed.connect(self._on_template_changed)
        self.editor_panel.setMinimumWidth(EDITOR_MIN_W)
        self.editor_panel.setMaximumWidth(EDITOR_MAX_W)
        splitter.addWidget(self.editor_panel)

        # Canvas gets all extra space, panels stay compact
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        # Both side panels open fully extended; the canvas takes the rest.
        # (setSizes before the first layout pass is ignored, hence the timer.)
        self._splitter = splitter
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.expand_panels)

        self.editor_panel.set_canvas(self.preview_canvas, tab_state=self.state, tab_ref=self)

        # Anything that changes the document marks this tab dirty
        self.preview_canvas.layers_changed.connect(self.mark_dirty)
        self.editor_panel.settings_changed.connect(self.mark_dirty)

        root.addWidget(splitter, 1)

        # Floating context toolbar
        self.ctx_tb = FloatingContextTb(self.preview_canvas)
        self.ctx_tb.set_canvas(self.preview_canvas)

        # Initial render
        self._do_compose()

    def expand_panels(self) -> None:
        """Open both side panels fully extended — but never squeeze the canvas
        under CANVAS_MIN_W: on small windows the panels shrink towards their
        minimum widths first (both by the same share)."""
        total = max(self.width(), SEARCH_MIN_W + EDITOR_MIN_W + CANVAS_MIN_W)
        left, right = SEARCH_MAX_W, EDITOR_MAX_W
        overflow = left + right + CANVAS_MIN_W - total
        if overflow > 0:
            slack_l, slack_r = SEARCH_MAX_W - SEARCH_MIN_W, EDITOR_MAX_W - EDITOR_MIN_W
            share = min(1.0, overflow / max(1, slack_l + slack_r))
            left = int(SEARCH_MAX_W - slack_l * share)
            right = int(EDITOR_MAX_W - slack_r * share)
        self._splitter.setSizes([left, total - left - right, right])

    # ── compose ───────────────────────────────────────────────────────────────
    def schedule_compose(self):
        """Debounced compose — restarts timer on each call."""
        self._compose_timer.start()

    def _do_compose(self):
        """
        Single rendering pipeline — drives PreviewCanvas only.
        PreviewCanvas is the only live render/edit authority.

        set_template() is only called when the template key actually changes,
        preventing the unconditional viewport recompute that previously
        reset the user's pan offset on every 120 ms compose tick.
        """
        try:
            canvas = self.preview_canvas
            st     = self.state

            # Guard: only call set_template when it has actually changed.
            # set_template() resets _pan_offset when doc size changes, so
            # calling it on every colour/effect slider update silently
            # discards the user's current view position.
            if canvas.template_key() != st.current_template:
                canvas.set_template(st.current_template)

            r, g, b = getattr(st, "bg_color", (0, 0, 0))
            canvas.set_background_color(QColor(r, g, b))

            canvas.update_effects_overlay(
                getattr(st, "film_grain", 0.0),
                getattr(st, "chromatic_aberration", 0.0),
            )

            canvas.update()

            size = f"{canvas.doc_size().width()}×{canvas.doc_size().height()}"
            self.status_changed.emit(
                f"Template: {st.current_template.upper()}  |  "
                f"Size: {size}  |  "
                f"Game: {st.selected_game_name or '—'}"
            )
        except Exception as e:
            import traceback
            self.status_changed.emit(f"Render error: {e}")
            traceback.print_exc()

    # ── slots ─────────────────────────────────────────────────────────────────
    def _on_game_selected(self, game_name: str):
        """
        A game was picked in the search list: remember it, rename the tab and
        look up its Steam AppID in the background so that Apply to Steam
        needs no dialog later. Only a confident (near-identical) match is
        accepted silently; anything else waits for the confirm dialog.
        """
        if game_name and game_name != self.state.selected_game_name:
            from app.services.exportFlow import invalidate_app_id_cache
            invalidate_app_id_cache(self)
        self.state.selected_game_name = game_name
        self._update_label(game_name)
        if self.state.confirmed_app_id is not None or not game_name:
            return

        from app.services.appIdRegistry import AppIdRegistry
        cached = AppIdRegistry.shared().lookup(game_name)
        if cached is not None:
            self.state.confirmed_app_id   = cached
            self.state.confirmed_app_name = AppIdRegistry.shared().lookup_canonical(game_name) or game_name
            self.status_changed.emit(f"AppID {cached} — {self.state.confirmed_app_name}")
            return

        from PySide6.QtCore import QObject, Signal
        class _Bridge(QObject):
            done = Signal(object)
        bridge = _Bridge(self)

        def _finish(res):
            bridge.deleteLater()
            if self.state.selected_game_name != game_name:
                return                      # user moved on to another game
            if isinstance(res, tuple):
                app_id, canonical = res
                self.state.confirmed_app_id   = app_id
                self.state.confirmed_app_name = canonical
                AppIdRegistry.shared().register(game_name, app_id, canonical=canonical)
                self.status_changed.emit(f"AppID {app_id} — {canonical}")
        bridge.done.connect(_finish)

        def _work():
            try:
                from app.services.appIdGetter import (search_candidates,
                                                      match_confidence, CONFIDENT_SCORE)
                cands = search_candidates(game_name)
                best, score = match_confidence(cands, game_name)
                bridge.done.emit((best["id"], best["name"])
                                 if best and score >= CONFIDENT_SCORE else None)
            except Exception:
                bridge.done.emit(None)
        import threading
        threading.Thread(target=_work, daemon=True).start()

    def _on_artwork_layer_ready(self, local_path: str, game_name: str):
        # Invalidate AppID cache if game changed
        if game_name and game_name != self.state.selected_game_name:
            from app.services.exportFlow import invalidate_app_id_cache
            invalidate_app_id_cache(self)
        self.state.selected_game_name = game_name
        try:
            self.preview_canvas.add_image_layer(local_path, name=game_name or "Artwork")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Could not add image", f"{local_path}\n\n{e}")
            return
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
        self.label_changed.emit(self.label)

    def set_label(self, label: str):
        self._update_label(label)

    # ── dirty / project state ─────────────────────────────────────────────────
    def mark_dirty(self):
        if not self.dirty:
            self.dirty = True
            self.dirty_changed.emit()

    def mark_clean(self):
        if self.dirty:
            self.dirty = False
            self.dirty_changed.emit()

    def is_empty(self) -> bool:
        """True when nothing has been done in this tab (safe to reuse)."""
        return (not self.dirty and not self.project_path
                and not self.preview_canvas.layers)

    def display_name(self) -> str:
        import os
        if self.project_path:
            return os.path.basename(self.project_path)
        return self.state.selected_game_name or "Untitled"

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



# ── Tab bar widget ─────────────────────────────────────────────────────────────
TAB_H = 32


class _Tab(QFrame):
    """One tab: [dirty dot] title … [close]. Paints its own active state (accent underline)."""

    clicked = Signal()
    close_clicked = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.index = 0
        self._active = False
        self._hover = False
        self._dirty = False
        self.setFixedHeight(TAB_H)
        self.setMinimumWidth(110)
        self.setMaximumWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        lay = hbox(self, (SP["md"], 0, SP["xs"], 0), SP["xs"])
        self._dot = QLabel()
        self._dot.setFixedSize(8, TAB_H)
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dot.setPixmap(_dot_pixmap(C["gold"], 6))
        self._dot.setVisible(False)
        self._dot.setToolTip("Unsaved changes")
        lay.addWidget(self._dot)
        self._title = label(title, "dim", elide=True)
        lay.addWidget(self._title, 1)
        self._close = IconButton("x", "Close tab  (Ctrl+W)", 12, on_click=self.close_clicked.emit,
                                 variant="ghost", color=C["text_dim"])
        self._close.setFixedSize(20, 20)
        lay.addWidget(self._close)

    # ── state ─────────────────────────────────────────────────────────────────
    def set_title(self, text: str):
        self._title.setText(text)

    def title(self) -> str:
        return self._title.text()

    def set_dirty(self, dirty: bool):
        self._dirty = dirty
        self._dot.setVisible(dirty)

    def set_active(self, active: bool):
        if active == self._active:
            return
        self._active = active
        self._title.setProperty("role", "body" if active else "dim")
        self._title.setProperty("tone", "accent" if active else "")
        repolish(self._title)
        self.setProperty("active", "true" if active else "false")
        self.update()

    def sizeHint(self):
        return QSize(190, TAB_H)

    # ── events ────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        r = self.rect()
        if self._active:
            p.fillRect(r, QColor(C["bg"]))
        elif self._hover:
            p.fillRect(r, QColor(C["surface"]))
        p.fillRect(r.right(), 0, 1, r.height(), QColor(C["border"]))
        if self._active:
            p.fillRect(0, r.height() - 2, r.width(), 2, QColor(C["accent"]))
        p.end()


def _dot_pixmap(color: str, size: int) -> QPixmap:
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(0, 0, size * dpr, size * dpr)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


class TabBar(QFrame):
    """
    Horizontal browser-style tab bar.
    Emits tab_switched(index) and tab_closed(index).
    """
    tab_switched = Signal(int)
    tab_closed   = Signal(int)
    tab_new      = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "strip")
        self.setFixedHeight(TAB_H + 1)

        self._layout = hbox(self, (0, 0, SP["xs"], 1), 0)

        self._tab_widgets: List[_Tab] = []
        self._active = 0

        # "+" new tab button at the end
        self._btn_new = IconButton("plus", "New tab  (Ctrl+T)", 14, on_click=self.tab_new.emit, variant="ghost")
        self._btn_new.setFixedSize(CONTROL_H, CONTROL_H)
        self._layout.addSpacing(SP["xs"])
        self._layout.addWidget(self._btn_new)
        self._layout.addStretch(1)

    # ── public API ────────────────────────────────────────────────────────────
    def add_tab(self, label: str) -> int:
        idx = len(self._tab_widgets)
        self._insert_tab_widget(idx, label)
        self._refresh_styles()
        return idx

    def rename_tab(self, idx: int, label: str):
        if 0 <= idx < len(self._tab_widgets):
            self._tab_widgets[idx].set_title(label)
        self._refresh_styles()

    def set_dirty(self, idx: int, dirty: bool):
        if 0 <= idx < len(self._tab_widgets):
            self._tab_widgets[idx].set_dirty(dirty)

    def set_active(self, idx: int):
        self._active = idx
        self._refresh_styles()

    def count(self) -> int:
        return len(self._tab_widgets)

    # ── internals ─────────────────────────────────────────────────────────────
    def _insert_tab_widget(self, idx: int, label: str):
        tab = _Tab(label)
        tab.clicked.connect(lambda t=tab: self.tab_switched.emit(t.index))
        tab.close_clicked.connect(lambda t=tab: self.tab_closed.emit(t.index))
        self._tab_widgets.insert(idx, tab)
        self._layout.insertWidget(idx, tab)
        self._rewire_buttons()

    def _refresh_styles(self):
        for i, tab in enumerate(self._tab_widgets):
            tab.set_active(i == self._active)

    def remove_tab(self, idx: int):
        if not (0 <= idx < len(self._tab_widgets)):
            return
        tab = self._tab_widgets.pop(idx)
        self._layout.removeWidget(tab)
        tab.deleteLater()
        # Re-index so close / switch signals stay correct
        self._rewire_buttons()
        self._refresh_styles()

    def _rewire_buttons(self):
        for i, tab in enumerate(self._tab_widgets):
            tab.index = i


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

    status_changed  = Signal(str)
    current_changed = Signal(object)   # WorkspaceTab now shown
    close_requested = Signal(int)      # user clicked the close button / Ctrl+W — MainWindow confirms
    tab_added       = Signal(object)   # new WorkspaceTab created
    zoom_changed    = Signal(int)      # current tab's canvas zoom (percent)

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
        self._tab_bar.tab_closed.connect(self.close_requested)
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
        tab.label_changed.connect(lambda _l, t=tab: self._refresh_tab_title(t))
        tab.dirty_changed.connect(lambda t=tab: self._refresh_tab_title(t))
        tab.preview_canvas.zoom_changed.connect(
            lambda pct, t=tab: self.zoom_changed.emit(pct) if t is self.current_tab() else None)
        self._next_id += 1
        self._tabs.append(tab)
        self._stack.addWidget(tab)
        idx = len(self._tabs) - 1
        self._tab_bar.add_tab(tab.label)
        self.tab_added.emit(tab)
        self.switch_tab(idx)
        return tab

    def _refresh_tab_title(self, tab: WorkspaceTab):
        if tab not in self._tabs:
            return
        idx = self._tabs.index(tab)
        self._tab_bar.rename_tab(idx, tab.label)
        self._tab_bar.set_dirty(idx, tab.dirty)

    def index_of(self, tab: WorkspaceTab) -> int:
        return self._tabs.index(tab)

    def tabs(self) -> List[WorkspaceTab]:
        return list(self._tabs)

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
        # Re-show the floating toolbar of the active tab (it was hidden above)
        if hasattr(tab, "ctx_tb") and tab.preview_canvas.selected_layer() is not None:
            try:
                tab.ctx_tb._refresh()
            except Exception:
                pass
        self.current_changed.emit(tab)
        self.zoom_changed.emit(round(tab.preview_canvas._zoom_factor * 100))

    def next_tab(self, step: int = 1):
        n = len(self._tabs)
        if n > 1:
            self.switch_tab((self._stack.currentIndex() + step) % n)

    def close_tab(self, idx: int):
        """Close without asking — MainWindow confirms unsaved changes first."""
        if not (0 <= idx < len(self._tabs)):
            return
        if len(self._tabs) == 1:
            # Closing the last tab: replace it with a fresh one so the
            # workspace never ends up empty.
            self.add_tab()
            idx = 0
        tab = self._tabs.pop(idx)
        self._stack.removeWidget(tab)
        tab.deleteLater()
        self._tab_bar.remove_tab(idx)
        new_idx = min(idx, len(self._tabs) - 1)
        self.switch_tab(new_idx)

    # ── proxy helpers used by MainWindow ──────────────────────────────────────
    @property
    def preview_canvas(self) -> PreviewCanvas:
        return self.current_tab().preview_canvas

    @property
    def search_panel(self):
        return self.current_tab().search_panel

    @property
    def editor_panel(self) -> EditorPanel:
        return self.current_tab().editor_panel


    def rename_current(self, label: str):
        self.current_tab().set_label(label)