import os
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QStatusBar, QMenuBar, QMenu, QFileDialog,
    QMessageBox, QPushButton, QLabel, QSlider, QDialog, QLineEdit,
    QCheckBox, QComboBox, QListWidget, QProgressBar, QScrollArea, QGridLayout,
)
from PySide6.QtCore import Qt, QTimer, QSize, QObject, Signal
from PySide6.QtGui import QAction, QKeySequence, QColor, QPixmap, QPainter
from app.services.projectIO import (save_project, load_project,
                                    autosave, SGEPROJ_EXT,
                                    ProjectIOError)
from app.ui.canvas.previewCanvas import PreviewCanvas
from app.ui.searchPanel import SearchPanel
from app.ui.editorPanel import EditorPanel
from app.ui.floatingContextTb import FloatingContextTb
from app.ui.tabManager import TabManager
from app.ui import icons, kit
from app.ui.kit import Button, IconButton, Divider, Section, label, hbox, vbox, grid
from app.ui.theme import C, CONTROL_H, SP, repolish


def _dot(color: str, size: int = 8) -> QPixmap:
    """Small filled circle pixmap for status indicators (rendered at 2x)."""
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


def _vsep(height: int = 16) -> QLabel:
    """1 px vertical hairline for status-bar / toolbar rows."""
    pm = QPixmap(1, height)
    pm.fill(QColor(C["border"]))
    l = QLabel()
    l.setPixmap(pm)
    l.setFixedSize(1, height)
    return l


def _menu_icon(name: str):
    return icons.icon(name, C["text_dim"], 14)


class _Dialog(QDialog):
    """Themed dialog shell: title + optional explanation, body layout, button row."""

    def __init__(self, parent, title: str, explanation: str = "", min_width: int = 480,
                 icon: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(min_width)
        self.root = vbox(self, (SP["xl"], SP["lg"], SP["xl"], SP["lg"]), SP["md"])
        head = hbox(spacing=SP["sm"])
        if icon:
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icon, C["accent"], 18))
            head.addWidget(ic)
        head.addWidget(label(title.upper(), "title"), 1)
        self.root.addLayout(head)
        if explanation:
            self.root.addWidget(label(explanation, "dim", wrap=True))
        self.body = vbox(spacing=SP["md"])
        self.root.addLayout(self.body, 1)
        self.root.addWidget(Divider())
        self.buttons = hbox(spacing=SP["sm"])
        self.buttons.addStretch()
        self.root.addLayout(self.buttons)

    def grow_with_content(self):
        """Let a wrapped status label that changes while the dialog is open push the window taller."""
        from PySide6.QtWidgets import QLayout
        self.root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

    def add_button(self, text: str, variant: str = "default", on_click=None, icon=None) -> Button:
        b = Button(text, variant, icon=icon, on_click=on_click)
        if variant == "primary":
            b.setMinimumWidth(140)
        else:
            b.setMinimumWidth(90)
        self.buttons.addWidget(b)
        return b


def _fit_wrapped(lbl: QLabel):
    """A word-wrapped label whose text just changed: reserve the height the new text
    needs (Qt does not grow a shown dialog for height-for-width widgets by itself)."""
    w = lbl.width() if lbl.width() > 40 else 400
    lbl.setMinimumHeight(lbl.heightForWidth(w))
    top = lbl.window()
    if top is not None:
        top.adjustSize()


def _form_row(g: QGridLayout, row: int, text: str, widget, trailing=None):
    """Grid form row: fixed label column (~110 px) + stretching field (+ optional button)."""
    l = label(text, "dim")
    l.setMinimumWidth(110)
    l.setMaximumWidth(140)
    g.addWidget(l, row, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    span = 1 if trailing is not None else 2      # no trailing button → field spans both columns
    if isinstance(widget, QWidget):
        g.addWidget(widget, row, 1, 1, span)
    else:
        g.addLayout(widget, row, 1, 1, span)
    if trailing is not None:
        g.addWidget(trailing, row, 2)
    g.setColumnStretch(1, 1)

# Read version from the VERSION file at project root
try:
    import pathlib
    APP_VERSION = pathlib.Path(
        pathlib.Path(__file__).resolve().parents[2] / "VERSION"
    ).read_text(encoding="utf-8").strip()
except Exception:
    APP_VERSION = "0.0.0"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Steam Grunge Editor")
        self.setMinimumSize(1000, 650)
        self.resize(1400, 860)

        self._build_menu()
        self._build_status_bar()
        self._build_ui()

        # Compose timer (debounce re-renders)
        self._compose_timer = QTimer()
        self._compose_timer.setSingleShot(True)
        self._compose_timer.setInterval(120)
        self._compose_timer.timeout.connect(self._do_compose)

        # Update checker — fires 3 s after startup so it never delays launch
        QTimer.singleShot(3000, lambda: self._check_for_updates(manual=False))

        # Check PimpMySteam token on startup — non-blocking
        QTimer.singleShot(1500, self._check_token_on_startup)

        # Autosave every 5 minutes (silently, only dirty tabs)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(5 * 60 * 1000)
        self._autosave_timer.timeout.connect(self._do_autosave)
        self._autosave_timer.start()

    @staticmethod
    def _widget_alive(w) -> bool:
        """Return True if w is a valid, non-deleted Qt widget."""
        try:
            import sip  # type: ignore[import-untyped]
            return w is not None and not sip.isdeleted(w)
        except ImportError:
            # PySide6 doesn't ship sip; use a try/except probe instead
            try:
                w.isVisible()
                return True
            except RuntimeError:
                return False







    def _import_font_zip(self):
        """Fonts → Import Font Pack (ZIP)…"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from app.ui.fontImporter import import_fonts
        from app.config import USER_FONTS_DIR as FONTS_DIR
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Font Pack", "",
            "ZIP Font Pack (*.zip)"
        )
        if not path:
            return
        result = import_fonts([path], str(FONTS_DIR))
        self._refresh_font_combo()
        QMessageBox.information(self, "Font Import", result.summary())

    def _import_font_files(self):
        """Fonts → Import Font Files…"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from app.ui.fontImporter import import_fonts
        from app.config import USER_FONTS_DIR as FONTS_DIR
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Fonts", "",
            "Font Files (*.ttf *.otf *.woff *.woff2)"
        )
        if not paths:
            return
        result = import_fonts(paths, str(FONTS_DIR))
        self._refresh_font_combo()
        msg = result.summary()
        if result.failed:
            msg += "\n\nFailed:\n" + "\n".join(result.failed)
        QMessageBox.information(self, "Font Import", msg)

    def _open_fonts_folder(self):
        """Fonts → Open Fonts Folder…"""
        import subprocess, sys
        from app.config import USER_FONTS_DIR as FONTS_DIR
        os.makedirs(FONTS_DIR, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(FONTS_DIR)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", FONTS_DIR])
        else:
            subprocess.Popen(["xdg-open", FONTS_DIR])

    def _refresh_font_combo(self):
        """Repopulate the font dropdown in the editor panel after import."""
        if hasattr(self, 'editor_panel') and hasattr(self.editor_panel, '_populate_font_combo'):
            self.editor_panel._populate_font_combo()



    def _undo(self):
        if hasattr(self, 'preview_canvas'):
            self.preview_canvas.undo()
            if hasattr(self, 'editor_panel'):
                self.editor_panel._refresh_layer_list()

    def _redo(self):
        if hasattr(self, 'preview_canvas'):
            self.preview_canvas.redo()
            if hasattr(self, 'editor_panel'):
                self.editor_panel._refresh_layer_list()

    def _toggle_crop(self, checked: bool = True):
        if checked:
            l = self.preview_canvas.selected_layer()
            if not l or l.kind not in ("image", "texture"):
                if hasattr(self, '_btn_crop') and self._widget_alive(self._btn_crop):
                    self._btn_crop.setChecked(False)
                if hasattr(self, '_sb_btn_crop') and self._widget_alive(self._sb_btn_crop):
                    self._sb_btn_crop.setChecked(False)
                return
            self.preview_canvas.enter_crop_mode()
            if hasattr(self, '_btn_crop_apply') and self._widget_alive(self._btn_crop_apply):
                self._btn_crop_apply.setVisible(True)
            if hasattr(self, '_btn_crop_cancel') and self._widget_alive(self._btn_crop_cancel):
                self._btn_crop_cancel.setVisible(True)
            if hasattr(self, '_sb_btn_crop') and self._widget_alive(self._sb_btn_crop):
                self._sb_btn_crop.setChecked(True)
                self._sb_crop_apply.setVisible(True)
                self._sb_crop_cancel.setVisible(True)
        else:
            self._end_crop(False)

    def _end_crop(self, apply: bool):
        self.preview_canvas.exit_crop_mode(apply=apply)
        for attr in ('_btn_crop', '_btn_crop_apply', '_btn_crop_cancel'):
            w = getattr(self, attr, None)
            if w and self._widget_alive(w):
                if attr == '_btn_crop':
                    w.setChecked(False)
                else:
                    w.setVisible(False)
        for attr in ('_sb_btn_crop', '_sb_crop_apply', '_sb_crop_cancel'):
            w = getattr(self, attr, None)
            if w and self._widget_alive(w):
                if attr == '_sb_btn_crop':
                    w.setChecked(False)
                else:
                    w.setVisible(False)
        if apply and hasattr(self, 'editor_panel'):
            self.editor_panel._refresh_layer_list()

    def _build_menu(self):
        menubar = self.menuBar()

        def _act(menu, text, slot, shortcut=None, tip=None, icon=None):
            a = QAction(text, self)
            if icon:
                a.setIcon(_menu_icon(icon))
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        # ── FILE ──────────────────────────────────────────────────────────
        file_menu = menubar.addMenu("File")
        _act(file_menu, "New Project (new tab)",      self._new_project,       "Ctrl+N",       icon="file-plus")
        _act(file_menu, "Open Project…",              self._open_project,      "Ctrl+O",       icon="folder-open")
        _act(file_menu, "Save Project",               self._save_project,      "Ctrl+S",       icon="save")
        _act(file_menu, "Save Project As…",           self._save_project_as,   "Ctrl+Shift+S", icon="save-all")
        file_menu.addSeparator()
        _act(file_menu, "Import Image as Layer…",     self._import_image_as_layer, "Ctrl+Shift+O", icon="image-plus")
        _act(file_menu, "Import Texture Files…",      self._import_texture_files, icon="upload")
        _act(file_menu, "Open Textures Folder…",      self._open_textures_folder, icon="folder")
        file_menu.addSeparator()
        _act(file_menu, "Export Artwork (+ apply to Steam)", self._export,    "Ctrl+E",       icon="download")
        _act(file_menu, "Export All Assets…",         self._export_all_assets, "Ctrl+Shift+E", icon="files")
        _act(file_menu, "Open Exports Folder…",       self._open_exports_folder, icon="folder")
        file_menu.addSeparator()
        _act(file_menu, "Preferences…",               self._open_preferences,  "Ctrl+,",       icon="settings")
        file_menu.addSeparator()
        _act(file_menu, "Quit",                       self.close,              "Ctrl+Q",       icon="log-out")

        # ── EDIT ──────────────────────────────────────────────────────────
        edit_menu = menubar.addMenu("Edit")
        _act(edit_menu, "Undo",                       self._undo,              "Ctrl+Z",       icon="undo-2")
        redo_act = _act(edit_menu, "Redo",            self._redo,              "Ctrl+Y",       icon="redo-2")
        redo_act.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        edit_menu.addSeparator()
        _act(edit_menu, "Duplicate Layer",            self._duplicate_layer,   "Ctrl+D",       icon="copy")
        _act(edit_menu, "Delete Layer",               self._delete_layer,      "Delete",       icon="trash")
        _act(edit_menu, "Crop Layer",                 self._toggle_crop,       "Ctrl+Shift+C", icon="crosshair")
        edit_menu.addSeparator()
        _act(edit_menu, "Reset Effects",              self._reset_filters, icon="rotate-ccw")

        # ── FONTS ─────────────────────────────────────────────────────────
        fonts_menu = menubar.addMenu("Fonts")
        _act(fonts_menu, "Import Font Pack (ZIP)…",   self._import_font_zip, icon="package")
        _act(fonts_menu, "Import Font Files…",        self._import_font_files, icon="type")
        fonts_menu.addSeparator()
        _act(fonts_menu, "Reload Font Library",       self._reload_font_library, icon="refresh-cw")
        _act(fonts_menu, "Open Fonts Folder…",        self._open_fonts_folder, icon="folder")

        # ── SYNC TO STEAM ─────────────────────────────────────────────────
        sync_menu = menubar.addMenu("Sync to Steam")
        _act(sync_menu, "Sync to Steam…",             self._open_sync_dialog,  "Ctrl+Shift+A", icon="upload")
        sync_menu.addSeparator()
        _act(sync_menu, "Locate Steam Folder…",       self._locate_steam_folder,
             tip="Manually set Steam installation path if auto-detection fails", icon="folder-open")
        _act(sync_menu, "Rescan Steam Library",       self._rescan_steam_library,
             tip="Re-check Steam folders and available user accounts", icon="refresh-cw")
        sync_menu.addSeparator()
        _act(sync_menu, "Open Exports Folder…",       self._open_exports_folder, icon="folder")

        # ── BACKUP (Drive through PimpMySteam, or a file on a USB stick) ──
        cloud_menu = menubar.addMenu("Backup")
        _act(cloud_menu, "Connect via PimpMySteam…",  self._open_drive_connect, icon="key-round")
        cloud_menu.addSeparator()
        _act(cloud_menu, "Back Up Steam Artwork to Drive",
             lambda: self._drive_backup_restore("backup"), "Ctrl+Shift+U",
             tip="Zip your Steam userdata/<id>/config/grid folder and upload it to Drive", icon="cloud-upload")
        _act(cloud_menu, "Restore Steam Artwork from Drive…",
             lambda: self._drive_backup_restore("restore"), "Ctrl+Shift+D",
             tip="Download the backup ZIP and extract it into your Steam grid folder", icon="cloud-download")
        _act(cloud_menu, "Drive Backup Status…",      self._open_drive_status, icon="cloud")
        cloud_menu.addSeparator()
        _act(cloud_menu, "Export Artwork to File (USB)…", self._export_artwork_pack,
             tip="One zip with your grid artwork and Steam's librarycache — keep it on a USB stick", icon="hard-drive-download")
        _act(cloud_menu, "Import Artwork from File…", lambda: self._import_artwork_pack("file"),
             tip="A zip made by Export (or a Drive backup zip) → back into Steam", icon="hard-drive-upload")
        _act(cloud_menu, "Import Artwork from Folder…", lambda: self._import_artwork_pack("folder"),
             tip="A copied grid folder, librarycache folder, or a folder holding both", icon="folder-open")

        # ── HELP ──────────────────────────────────────────────────────────
        help_menu = menubar.addMenu("Help")
        _act(help_menu, "Getting SteamGridDB API Key", self._show_api_key_help, icon="key-round")
        _act(help_menu, "Quick Start Tutorial",       self._show_quickstart, icon="zap")
        _act(help_menu, "Keyboard Shortcuts",         self._show_shortcuts, icon="list")
        help_menu.addSeparator()
        _act(help_menu, "Report Issue",               self._report_issue, icon="triangle-alert")
        _act(help_menu, "Check for Updates",          self._check_for_updates, icon="refresh-cw")
        help_menu.addSeparator()
        _act(help_menu, "About",                      self._show_about, icon="info")

        # ── Corner: crop group + Sync to Steam ─────────────────────────────
        menubar.setMinimumHeight(CONTROL_H + SP["sm"])
        corner = QWidget()
        corner_layout = hbox(corner, (SP["sm"], 3, SP["sm"], 3), SP["xs"])

        # Undo / redo / crop live in the status bar; the corner only carries the
        # one action people reach for constantly. The hidden buttons keep the
        # old attribute names alive for the crop state machine.
        self._btn_undo = IconButton("undo-2", "Undo  (Ctrl+Z)", 15, on_click=self._undo)
        self._btn_redo = IconButton("redo-2", "Redo  (Ctrl+Y)", 15, on_click=self._redo)
        self._btn_crop = IconButton("crosshair", "Crop selected layer", 15, checkable=True, on_click=self._toggle_crop)
        self._btn_crop_apply = IconButton("check", "Apply crop  (Enter)", 15, color=C["green"],
                                          on_click=lambda: self._end_crop(True))
        self._btn_crop_cancel = IconButton("x", "Cancel crop  (Esc)", 15, color=C["red"],
                                           on_click=lambda: self._end_crop(False))
        for b in (self._btn_undo, self._btn_redo, self._btn_crop, self._btn_crop_apply, self._btn_crop_cancel):
            b.setParent(corner)
            b.setVisible(False)

        self._btn_sync = Button("Sync to Steam", "success", icon="upload", on_click=self._open_sync_dialog,
                                tooltip="Install artwork into Steam's custom grid folder")
        corner_layout.addWidget(self._btn_sync)

        self._menu_corner = corner            # keep a reference — PySide does not take ownership
        menubar.setCornerWidget(corner, Qt.Corner.TopRightCorner)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Tab manager owns the tab bar + all workspaces
        self.tab_manager = TabManager()
        self.tab_manager.status_changed.connect(self._status_label.setText)
        # Every tab tracks its own dirty flag / project path; the window title
        # and zoom slider follow whichever tab is current.
        self.tab_manager.zoom_changed.connect(self._on_canvas_zoom_changed)
        self.tab_manager.current_changed.connect(lambda _t: self._update_title())
        self.tab_manager.close_requested.connect(self._close_tab_requested)
        self.tab_manager.tab_added.connect(
            lambda t: t.dirty_changed.connect(self._update_title))
        for t in self.tab_manager.tabs():
            t.dirty_changed.connect(self._update_title)

        # Periodically refresh the API key status indicator (every 3s)
        # so it updates immediately after the user sets their key without
        # requiring a dedicated signal from SearchPanel.
        from PySide6.QtCore import QTimer
        self._api_status_timer = QTimer(self)
        self._api_status_timer.setInterval(3000)
        self._api_status_timer.timeout.connect(self._refresh_api_key_status)
        self._api_status_timer.start()
        root_layout.addWidget(self.tab_manager, 1)

        # Tab shortcuts
        from PySide6.QtGui import QShortcut
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(
            lambda: self.tab_manager.add_tab())
        QShortcut(QKeySequence("Ctrl+W"), self).activated.connect(
            lambda: self._close_tab_requested(self.tab_manager._stack.currentIndex()))
        QShortcut(QKeySequence("Ctrl+Tab"), self).activated.connect(
            lambda: self.tab_manager.next_tab(+1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self).activated.connect(
            lambda: self.tab_manager.next_tab(-1))
        self._update_title()

    # ── proxy properties so all existing slot code keeps working ──────────────
    @property
    def preview_canvas(self) -> PreviewCanvas:
        return self.tab_manager.preview_canvas

    @property
    def editor_panel(self) -> EditorPanel:
        return self.tab_manager.editor_panel

    def _build_status_bar(self):
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.setMinimumHeight(CONTROL_H + 2 * SP["xs"])
        self.setStatusBar(self.status_bar)

        # ── Left: undo / redo · crop group · status message ────────────────
        left_w = QWidget()
        left_lay = hbox(left_w, (SP["sm"], 0, SP["sm"], 0), SP["sm"])

        self._sb_btn_undo = IconButton("undo-2", "Undo  (Ctrl+Z)", 15, on_click=self._undo)
        self._sb_btn_redo = IconButton("redo-2", "Redo  (Ctrl+Y)", 15, on_click=self._redo)
        left_lay.addWidget(self._sb_btn_undo)
        left_lay.addWidget(self._sb_btn_redo)
        left_lay.addWidget(_vsep())

        self._sb_btn_crop = IconButton("crosshair", "Crop layer  (Ctrl+Shift+C)", 15,
                                       checkable=True, on_click=self._toggle_crop)
        left_lay.addWidget(self._sb_btn_crop)
        self._sb_crop_apply = IconButton("check", "Apply crop  (Enter)", 15, color=C["green"],
                                         on_click=lambda: self._end_crop(True))
        self._sb_crop_apply.setVisible(False)
        left_lay.addWidget(self._sb_crop_apply)
        self._sb_crop_cancel = IconButton("x", "Cancel crop  (Esc)", 15, color=C["red"],
                                          on_click=lambda: self._end_crop(False))
        self._sb_crop_cancel.setVisible(False)
        left_lay.addWidget(self._sb_crop_cancel)
        left_lay.addWidget(_vsep())

        self._status_label = label("Ready", "dim", elide=True)
        self._status_label.setFixedHeight(CONTROL_H)
        left_lay.addWidget(self._status_label, 1)
        self.status_bar.addWidget(left_w, 1)

        # ── Right: API key · zoom · rotation ───────────────────────────────
        right_w = QWidget()
        right_lay = hbox(right_w, (SP["sm"], 0, SP["md"], 0), SP["sm"])

        self._api_key_dot = QLabel()
        self._api_key_dot.setFixedSize(10, CONTROL_H)
        self._api_key_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_lay.addWidget(self._api_key_dot)
        self._api_key_lbl = label("API Key: Not Set", "dim")
        self._api_key_lbl.setObjectName("api_key_status")
        self._api_key_lbl.setFixedHeight(CONTROL_H)
        tip = "SteamGridDB API key status — use Help → Getting SteamGridDB API Key"
        self._api_key_lbl.setToolTip(tip)
        self._api_key_dot.setToolTip(tip)
        right_lay.addWidget(self._api_key_lbl)
        right_lay.addWidget(_vsep())

        right_lay.addWidget(IconButton("zoom-out", "Zoom out", 15, on_click=lambda: self._zoom_step(-25)))
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(25, 400)   # 25% – 400% (same as canvas)
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedSize(120, CONTROL_H)
        self._zoom_slider.setToolTip("Canvas zoom")
        self._zoom_slider.valueChanged.connect(self._on_zoom_changed)
        right_lay.addWidget(self._zoom_slider)
        self._zoom_pct_label = label("100%", "mono", align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._zoom_pct_label.setFixedSize(40, CONTROL_H)
        right_lay.addWidget(self._zoom_pct_label)
        right_lay.addWidget(IconButton("zoom-in", "Zoom in", 15, on_click=lambda: self._zoom_step(+25)))
        right_lay.addWidget(Button("1:1", "ghost", on_click=self._zoom_reset, tooltip="Reset zoom to 100%"))
        right_lay.addWidget(_vsep())

        right_lay.addWidget(IconButton("rotate-ccw", "Rotate canvas −15°", 15,
                                       on_click=lambda: self._rotate_canvas(-15)))
        self._rot_label = label("0.00°", "mono", align=Qt.AlignmentFlag.AlignCenter)
        self._rot_label.setFixedSize(60, CONTROL_H)
        self._rot_label.setToolTip("Canvas view rotation (double-click to reset)")
        self._rot_label.mouseDoubleClickEvent = lambda _: self._rotate_canvas_reset()
        right_lay.addWidget(self._rot_label)
        right_lay.addWidget(IconButton("rotate-cw", "Rotate canvas +15°", 15,
                                       on_click=lambda: self._rotate_canvas(+15)))

        self.status_bar.addPermanentWidget(right_w)
        self._refresh_api_key_status()

        # Transient notifications float above the status bar
        self.toasts = kit.ToastHost(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "toasts"):
            self.toasts.relayout()

    def _notify(self, msg: str, tone: str = "info"):
        """Status text + floating toast (saved / exported / synced / errors)."""
        self._status_label.setText(msg)
        if hasattr(self, "toasts"):
            self.toasts.show(msg, tone)

    def _zoom_step(self, delta: int):
        self._zoom_slider.setValue(max(25, min(400, self._zoom_slider.value() + delta)))

    def _on_zoom_changed(self, val: int):
        # Guard: if the canvas triggered this update don't call set_zoom again
        if getattr(self, '_zoom_slider_updating', False):
            return
        self._zoom_pct_label.setText(f"{val}%")
        if hasattr(self, 'preview_canvas'):
            self.preview_canvas.set_zoom(val / 100.0)

    def _on_canvas_zoom_changed(self, pct: int):
        """Keep the zoom slider in sync when wheel/tool changes the zoom."""
        self._zoom_slider_updating = True
        try:
            self._zoom_slider.setValue(max(25, min(400, pct)))
            self._zoom_pct_label.setText(f"{pct}%")
        finally:
            self._zoom_slider_updating = False

    def _zoom_reset(self):
        self._zoom_slider.setValue(100)

    def _refresh_api_key_status(self):
        """Update the API key status indicator in the status bar."""
        try:
            from app.services.steamgrid import client as sgdb_client
            has_key = bool(sgdb_client.api_key and sgdb_client.api_key.strip())
        except Exception:
            has_key = False
        if getattr(self, "_api_key_state", None) == has_key:
            return
        self._api_key_state = has_key
        self._api_key_dot.setPixmap(_dot(C["green"] if has_key else C["red"]))
        self._api_key_lbl.setText("API Key: Connected" if has_key else "API Key: Not Set")
        kit.set_tone(self._api_key_lbl, "green" if has_key else None)
        # NOTE: do NOT call reset_pan() here.
        # This method fires on a 3-second repeating timer; calling reset_pan()
        # was silently discarding the user's pan position every 3 seconds.

    def _set_rot_text(self, angle: float):
        display = angle if angle <= 180 else angle - 360
        self._rot_label.setText(f"{display:.2f}°")
        kit.set_tone(self._rot_label, "accent" if abs(angle) > 0.01 else None)

    def _rotate_canvas(self, delta: float):
        """Rotate the canvas view by delta degrees."""
        if not hasattr(self, 'preview_canvas'): return
        current = getattr(self.preview_canvas, '_view_angle', 0.0)
        new_angle = (current + delta) % 360
        self.preview_canvas.set_view_angle(new_angle)
        self._set_rot_text(new_angle)

    def _rotate_canvas_reset(self):
        """Reset canvas view rotation to 0°."""
        if not hasattr(self, 'preview_canvas'): return
        self.preview_canvas.set_view_angle(0.0)
        self._set_rot_text(0.0)

    def showMessage(self, msg: str):
        """Compatibility shim — update the status label."""
        self._status_label.setText(msg)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_settings_changed(self):
        self.tab_manager.current_tab().schedule_compose()

    def _on_template_changed(self, template: str):
        self.tab_manager.current_tab().state.current_template = template
        self.tab_manager.current_tab().schedule_compose()

    def schedule_compose(self):
        self.tab_manager.current_tab().schedule_compose()

    def _do_compose(self):
        self.tab_manager.current_tab().schedule_compose()

    def _export(self):
        """
        Export current canvas and apply it to Steam.

        Single export path for the whole app: run_export_flow() confirms the
        AppID (once per game) and saves with the Steam filename, so there is
        never a nameless GameName_timestamp.png file to clean up afterwards.
        """
        from app.services.exportFlow import run_export_flow
        tab  = self.tab_manager.current_tab()
        path = run_export_flow(tab, parent_widget=self)
        if not path:
            return   # nothing on canvas, or user cancelled the AppID dialog

        # Store path so Sync always uses this exact file
        tab.state.export_paths[tab.state.current_template] = path
        print(f"[export] {tab.state.current_template} -> {path}")

        # ── Apply to Steam ────────────────────────────────────────────────────
        app_id = tab.state.confirmed_app_id
        try:
            from app.services.steamSync import (
                sync_artwork, find_steam_userdata, list_steam_ids
            )
            userdata = find_steam_userdata()
            steam_id = self._pick_steam_id("Apply to Steam") if userdata else None
            if userdata and steam_id:
                result = sync_artwork(
                    app_id=app_id,
                    steam_id=steam_id,
                    userdata_path=userdata,
                    exports={tab.state.current_template: path},
                    overwrite=True,
                )
                if result.success:
                    name = tab.state.confirmed_app_name or tab.state.selected_game_name or app_id
                    self._notify(
                        f"Applied to Steam: {tab.state.current_template} → {name}  "
                        f"({os.path.basename(path)})", "success")
                    return
                self.toasts.show("Apply to Steam failed — see details", "error")
                QMessageBox.warning(self, "Apply to Steam failed",
                                    "Saved the PNG but Steam did not accept it:\n"
                                    + "\n".join(result.errors))
                return
        except Exception as e:
            self.toasts.show(f"Apply to Steam failed: {e}", "error")
            QMessageBox.warning(self, "Apply to Steam failed", f"Saved the PNG, but:\n{e}")
            return

        # Steam not found — the PNG is still saved
        self._notify(f"Saved (Steam not found): {path}", "warning")


    def _reset_filters(self):
        tab = self.tab_manager.current_tab()
        tab.state.reset_filters()
        tab.editor_panel.refresh_from_state()
        tab.schedule_compose()

    def _open_exports_folder(self):
        """Open the exports directory in the OS file manager."""
        import subprocess, sys
        from app.config import EXPORT_FOLDER
        import os
        os.makedirs(EXPORT_FOLDER, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(EXPORT_FOLDER)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", EXPORT_FOLDER])
        else:
            subprocess.Popen(["xdg-open", EXPORT_FOLDER])

    def _open_sync_dialog(self):
        """
        Open the Sync to Steam dialog.

        Always re-exports the current template from the live canvas so Sync
        never uses a stale previously-exported file after edits.
        Other templates retain their last-exported paths if they exist.
        """
        from app.services.exportFlow import run_export_flow
        tab = self.tab_manager.current_tab()

        # ── Always re-export the current template from the live canvas ────────
        # Same single export path as File → Export: confirms AppID once and
        # saves with the Steam filename (overwrites the previous export).
        path = run_export_flow(tab, parent_widget=self)
        if not path:
            return   # nothing on canvas, or user cancelled the AppID dialog
        tab.state.export_paths[tab.state.current_template] = path
        print(f"[sync] exported {tab.state.current_template} -> {path}")

        # ── Build exports dict: fresh current template + any prior exports ────
        exports = {
            tpl: p
            for tpl, p in tab.state.export_paths.items()
            if p and os.path.isfile(p)
        }

        # Log exactly what will be synced so mismatches are easy to spot
        print("[sync] files queued for Steam:")
        for tpl, p in exports.items():
            print(f"  {tpl:15s} → {p}")

        from app.ui.steamSyncDialog import SteamSyncDialog
        dlg = SteamSyncDialog(
            game_name=tab.state.selected_game_name or "",
            exports=exports,
            parent=self,
        )
        dlg.exec()
    # ── Backup handlers (Drive) ───────────────────────────────────────────────

    def _open_drive_connect(self):
        """Backup → Connect via PimpMySteam — shows inline token dialog."""
        from app.services.steamkustom_auth import get_token, save_token, verify_async

        dlg = _Dialog(self, "PimpMySteam account",
                      "Generate a token at pimpmysteam.com → Settings → Apps → Generate Token, "
                      "then paste it here to enable Google Drive sync.",
                      min_width=500, icon="key-round")

        form = grid(h=SP["md"], v=SP["sm"])
        saved = get_token() or ""
        token_edit = QLineEdit()
        token_edit.setPlaceholderText("Paste your app token here…")
        token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        if saved:
            token_edit.setText(saved)
        _form_row(form, 0, "App token", token_edit)

        status_row = hbox(spacing=SP["sm"])
        status_ic = QLabel()
        status_ic.setFixedSize(16, 16)
        status_lbl = label("Token saved" if saved else "Not connected", "dim", elide=True)
        if saved:
            status_ic.setPixmap(icons.pixmap("circle-check", C["green"], 16))
            kit.set_tone(status_lbl, "green")
        else:
            status_ic.setPixmap(icons.pixmap("circle-dot", C["text_muted"], 16))
        status_row.addWidget(status_ic)
        status_row.addWidget(status_lbl, 1)
        _form_row(form, 1, "Status", status_row)
        dlg.body.addLayout(form)

        link = Button("Open pimpmysteam.com → Settings → Apps", "link", icon="external-link",
                      on_click=lambda: __import__("webbrowser").open("https://pimpmysteam.com/settings"))
        dlg.body.addWidget(link, 0, Qt.AlignmentFlag.AlignLeft)

        def _set_status(text: str, tone, icon_name: str, color: str):
            status_lbl.setText(text)
            kit.set_tone(status_lbl, tone)
            status_ic.setPixmap(icons.pixmap(icon_name, color, 16))

        close_btn = dlg.add_button("Close", on_click=dlg.accept)
        verify_btn = dlg.add_button("Verify and save", "primary", icon="shield-check")

        # Signal bridge to safely update UI from background thread
        class _Bridge(QObject):
            result = Signal(bool, object)

        bridge = _Bridge()

        def _verify():
            token = token_edit.text().strip()
            if not token:
                _set_status("Enter a token first", "gold", "triangle-alert", C["gold"])
                return
            verify_btn.set_loading(True, "Verifying…")
            _set_status("Verifying…", "accent", "loader-circle", C["accent"])

            def _done(ok, user):
                # Emit signal — always received on main thread
                bridge.result.emit(ok, user)

            verify_async(token, _done)

        def _on_result(ok, user):
            verify_btn.set_loading(False)
            if ok and user:
                token = token_edit.text().strip()
                name = user.get("username", "Connected")
                if not save_token(token):
                    _set_status("Valid token but could not save it (check write permissions in data folder)",
                                "red", "circle-x", C["red"])
                    return
                _set_status(f"Connected as {name} — token saved", "green", "circle-check", C["green"])
                self._notify(f"[Drive] Connected as {name}", "success")
                print(f"[PimpMySteam] Token saved for {name}")
            else:
                _set_status("Invalid token — check pimpmysteam.com → Settings → Apps", "red", "circle-x", C["red"])
                print("[PimpMySteam] Token invalid")

        bridge.result.connect(_on_result)
        verify_btn.clicked.connect(_verify)
        dlg.exec()

    def _pick_steam_id(self, title: str):
        """Return the Steam account to use, asking only when there are several."""
        from app.services.steamSync import find_steam_userdata, list_steam_ids
        userdata  = find_steam_userdata()
        steam_ids = list_steam_ids(userdata) if userdata else []
        if not steam_ids:
            QMessageBox.warning(self, title,
                                "Steam installation not found.\n"
                                "Use  Sync to Steam → Locate Steam Folder…  first.")
            return None
        if len(steam_ids) == 1:
            return steam_ids[0]
        # Several accounts: ask once per session (list is most-recent first)
        remembered = getattr(self, "_steam_id_choice", None)
        if remembered in steam_ids:
            return remembered
        dlg = _Dialog(self, title, "Several Steam accounts were found in userdata. "
                      "Pick the one whose library should receive the artwork.", min_width=460, icon="gamepad-2")
        form = grid(h=SP["md"], v=SP["sm"])
        combo = QComboBox()
        combo.addItems(steam_ids)
        _form_row(form, 0, "Steam account", combo)
        dlg.body.addLayout(form)
        dlg.add_button("Cancel", on_click=dlg.reject)
        dlg.add_button("Use this account", "primary", on_click=dlg.accept, icon="check")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._steam_id_choice = combo.currentText()
            return self._steam_id_choice
        return None

    def _drive_backup_restore(self, mode: str):
        """
        Backup → Back Up / Restore Steam artwork.

        backup : zip userdata/<id>/config/grid → Drive
        restore: Drive zip → userdata/<id>/config/grid (overwrites same names)
        Runs in a worker thread; the UI is only touched through signals.
        """
        import threading
        from app.services.drive_sync import is_configured, backup_grid, restore_grid

        if not is_configured():
            QMessageBox.warning(self, "Not Connected",
                "Connect your PimpMySteam account first:\n"
                "Backup → Connect via PimpMySteam…")
            return

        title    = "Back Up Steam Artwork" if mode == "backup" else "Restore Steam Artwork"
        steam_id = self._pick_steam_id(title)
        if not steam_id:
            return

        if mode == "restore":
            ans = QMessageBox.question(
                self, title,
                f"This will download the backup for Steam account {steam_id}\n"
                "and overwrite files with the same name in your Steam grid folder.\n\n"
                "Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return

        # ── Progress dialog ───────────────────────────────────────────────────
        dlg = _Dialog(self, title, f"Steam account {steam_id}", min_width=460,
                      icon="cloud-upload" if mode == "backup" else "cloud-download")
        dlg.grow_with_content()
        row = hbox(spacing=SP["sm"])
        result_ic = QLabel()
        result_ic.setFixedSize(16, 16)
        result_ic.setPixmap(icons.pixmap("loader-circle", C["accent"], 16))
        row.addWidget(result_ic, 0, Qt.AlignmentFlag.AlignTop)
        status_lbl = label("Starting…", "body", wrap=True)
        row.addWidget(status_lbl, 1)
        dlg.body.addLayout(row)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setFixedHeight(6)
        bar.setTextVisible(False)
        dlg.body.addWidget(bar)
        close_btn = dlg.add_button("Close", "primary", on_click=dlg.accept)
        close_btn.setEnabled(False)

        class _Sig(QObject):
            progress = Signal(str)
            finished = Signal(bool, str)

        sig = _Sig()
        sig.progress.connect(status_lbl.setText)

        def _on_finished(ok, msg):
            status_lbl.setText(msg)
            _fit_wrapped(status_lbl)
            result_ic.setPixmap(icons.pixmap("circle-check" if ok else "circle-x",
                                             C["green"] if ok else C["red"], 16))
            bar.setRange(0, 1)
            bar.setValue(1)
            close_btn.setEnabled(True)
            self._notify(f"[Drive] {msg.splitlines()[0]}", "success" if ok else "error")
        sig.finished.connect(_on_finished)

        def _work():
            try:
                if mode == "backup":
                    r = backup_grid(steam_id, on_progress=sig.progress.emit)
                    if r["ok"]:
                        mb = r["bytes"] / 1024 / 1024
                        sig.finished.emit(True,
                            f"Backed up {r['files']} file(s) ({mb:.1f} MB) to Drive")
                    else:
                        sig.finished.emit(False, f"{r['error']}")
                else:
                    r = restore_grid(steam_id, on_progress=sig.progress.emit)
                    if r["ok"]:
                        sig.finished.emit(True,
                            f"Restored {r['files']} file(s) into your Steam grid folder.\n"
                            "Restart Steam to see the artwork.")
                    else:
                        sig.finished.emit(False, f"{r['error']}")
            except Exception as e:
                sig.finished.emit(False, f"{e}")

        threading.Thread(target=_work, daemon=True).start()
        dlg.exec()

    def _check_token_on_startup(self):
        """Verify the saved PimpMySteam token in the background and show who we are."""
        from app.services.steamkustom_auth import get_token
        token = get_token()
        if not token:
            return

        import threading

        class _Sig(QObject):
            status = Signal(str)

        sig = _Sig()
        sig.status.connect(self._status_label.setText)

        def _run():
            try:
                from app.services.steamkustom_auth import verify_token
                user = verify_token(token)
                if user:
                    sig.status.emit(f"[Drive] Connected as {user.get('username', '')}")
                else:
                    sig.status.emit("[Drive] Token saved but could not verify")
            except Exception as e:
                sig.status.emit(f"[Drive] Startup check error: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _open_drive_status(self):
        """Backup → Drive Backup Status — lists the backup ZIPs on Drive."""
        import threading
        from app.services.drive_sync import is_configured, drive_status, list_backups

        dlg = _Dialog(self, "Backup status", "Backups of your Steam grid folder stored on Google Drive "
                      "through PimpMySteam.", min_width=500, icon="cloud")
        dlg.grow_with_content()
        head = hbox(spacing=SP["sm"])
        state_ic = QLabel()
        state_ic.setFixedSize(16, 16)
        state_ic.setPixmap(icons.pixmap("loader-circle", C["accent"], 16))
        head.addWidget(state_ic, 0, Qt.AlignmentFlag.AlignTop)
        state_lbl = label("Checking Drive…", "body", wrap=True)
        head.addWidget(state_lbl, 1)
        dlg.body.addLayout(head)

        rows_w = QWidget()
        rows = grid(rows_w, h=SP["lg"], v=SP["xs"])
        rows_w.setVisible(False)
        dlg.body.addWidget(rows_w)
        dlg.add_button("OK", "primary", on_click=dlg.accept)

        class _Sig(QObject):
            done = Signal(bool, str, list)
        sig = _Sig()

        def _show(ok: bool, text: str, backups: list):
            state_lbl.setText(text)
            _fit_wrapped(state_lbl)
            state_ic.setPixmap(icons.pixmap("circle-check" if ok else "circle-x",
                                            C["green"] if ok else C["red"], 16))
            if backups:
                for c, t in enumerate(("Steam account", "Size", "Modified (UTC)")):
                    rows.addWidget(label(t, "eyebrow"), 0, c)
                for r, b in enumerate(backups, start=1):
                    when = b["modified"][:16].replace("T", " ")
                    rows.addWidget(label(str(b["steam_id"]), "mono"), r, 0)
                    rows.addWidget(label(f"{b['size'] / 1024 / 1024:.1f} MB", "mono"), r, 1)
                    rows.addWidget(label(when, "dim"), r, 2)
                rows.setColumnStretch(2, 1)
                rows_w.setVisible(True)
        sig.done.connect(_show)

        def _run():
            try:
                if not is_configured():
                    sig.done.emit(False, "No token found.\nBackup → Connect via PimpMySteam…", [])
                    return
                st = drive_status()
                if not st["authenticated"]:
                    sig.done.emit(False, st["reason"] or "Token saved, but Google Drive is not linked.", [])
                    return
                backups = list_backups()
                if not backups:
                    sig.done.emit(True, "Connected to Google Drive — no backups yet.", [])
                    return
                sig.done.emit(True, f"Connected to Google Drive — {len(backups)} backup(s).", list(backups))
            except Exception as e:
                sig.done.emit(False, f"Error: {e}", [])

        threading.Thread(target=_run, daemon=True).start()
        dlg.exec()

    # ── Backup handlers (file / USB) ──────────────────────────────────────────

    def _export_artwork_pack(self):
        """Backup → Export Artwork to File: grid (+ librarycache) → one zip."""
        import threading
        from app.services import artwork_pack as ap

        steam_id = self._pick_steam_id("Export Artwork to File")
        if not steam_id:
            return
        try:
            grid, cache = ap.steam_folders(steam_id)
        except Exception as e:
            QMessageBox.warning(self, "Export Artwork to File", str(e))
            return

        dlg = _Dialog(self, "Export artwork to a file",
                      "One zip you can keep on a USB stick and import on any PC "
                      "(Backup → Import Artwork from File…). Drive backups are the same format.",
                      min_width=520, icon="hard-drive-download")
        grid_cb  = QCheckBox("Custom artwork  —  userdata/<id>/config/grid  (counting…)")
        cache_cb = QCheckBox("Steam library cache  —  appcache/librarycache  (counting…)")
        grid_cb.setChecked(True)
        cache_cb.setChecked(True)
        dlg.body.addWidget(grid_cb)
        dlg.body.addWidget(cache_cb)
        dlg.body.addWidget(label("The cache is Steam's own copy of every cover it has shown you; Steam "
                                 "regenerates it, but importing it means the art is there before Steam "
                                 "re-downloads anything. The grid folder is what Steam treats as your choice.",
                                 "dim", wrap=True))
        dlg.add_button("Cancel", on_click=dlg.reject)
        dlg.add_button("Choose file…", "primary", on_click=dlg.accept, icon="download")

        class _Sig(QObject):
            sizes = Signal(int, int, int, int)
        sig = _Sig()

        def _show_sizes(gn, gb, cn, cb):
            grid_cb.setText(f"Custom artwork  —  userdata/<id>/config/grid  ({gn} files, {gb / 1024 / 1024:.1f} MB)")
            cache_cb.setText(f"Steam library cache  —  appcache/librarycache  ({cn} files, {cb / 1024 / 1024:.0f} MB)")
        sig.sizes.connect(_show_sizes)
        threading.Thread(target=lambda: sig.sizes.emit(*ap.folder_stats(grid), *ap.folder_stats(cache)),
                         daemon=True).start()

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if not grid_cb.isChecked() and not cache_cb.isChecked():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export artwork to a file", str(Path.home() / ap.default_pack_name(steam_id)),
            "Zip archive (*.zip)")
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"

        def _work(progress):
            return ap.export_pack(steam_id, Path(path), include_grid=grid_cb.isChecked(),
                                  include_cache=cache_cb.isChecked(), on_progress=progress)

        def _done(r):
            if not r["ok"]:
                return False, r["error"]
            return True, f"Exported {r['files']} file(s) ({r['bytes'] / 1024 / 1024:.1f} MB) to\n{path}"

        self._run_with_progress("Export artwork to a file", f"Steam account {steam_id}",
                                "hard-drive-download", _work, _done)

    def _import_artwork_pack(self, kind: str):
        """Backup → Import Artwork from File / Folder → into Steam's grid + librarycache."""
        from app.services import artwork_pack as ap

        title = "Import artwork"
        if kind == "file":
            src, _ = QFileDialog.getOpenFileName(self, title, str(Path.home()), "Zip archive (*.zip)")
        else:
            src = QFileDialog.getExistingDirectory(self, title, str(Path.home()))
        if not src:
            return
        src = Path(src)
        if kind != "file":
            found = ap.classify_folder(src)
            if not found:
                QMessageBox.warning(self, title,
                    "Could not tell what this folder holds.\n\nPick Steam's grid folder "
                    "(files like 12345p.png), its librarycache folder (one numbered folder per "
                    "game), or a folder that contains grid/ and librarycache/ side by side.")
                return
            what = " and ".join(found)
        else:
            what = "the zip"

        steam_id = self._pick_steam_id(title)
        if not steam_id:
            return
        ans = QMessageBox.question(
            self, title,
            f"Copy {what} into Steam for account {steam_id}?\n\n"
            "Files with the same name are overwritten (custom artwork in "
            "userdata/<id>/config/grid, cache in appcache/librarycache).\n"
            "Close Steam first if it is running — it locks its cache files on Windows.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return

        def _work(progress):
            return ap.import_pack(src, steam_id, on_progress=progress)

        def _done(r):
            if not r["ok"]:
                return False, r["error"]
            parts = []
            if r["grid"]:
                parts.append(f"{r['grid']} custom artwork file(s)")
            if r["librarycache"]:
                parts.append(f"{r['librarycache']} cache file(s)")
            msg = "Imported " + " and ".join(parts) + "."
            if r["skipped"]:
                msg += f" Skipped {r['skipped']} entries outside the Steam folders."
            return True, msg + "\nRestart Steam to see the artwork."

        self._run_with_progress(title, f"{src.name} → Steam account {steam_id}", "hard-drive-upload",
                                _work, _done, offer_restart=True)

    def _run_with_progress(self, title: str, subtitle: str, icon: str, work, done, offer_restart: bool = False):
        """
        A small progress dialog around a blocking job: `work(progress_cb)` runs on a
        thread and returns a result; `done(result) -> (ok, message)` formats it.
        With offer_restart, a successful job adds a "Restart Steam" button.
        """
        import threading
        dlg = _Dialog(self, title, subtitle, min_width=480, icon=icon)
        dlg.grow_with_content()
        row = hbox(spacing=SP["sm"])
        result_ic = QLabel()
        result_ic.setFixedSize(16, 16)
        result_ic.setPixmap(icons.pixmap("loader-circle", C["accent"], 16))
        row.addWidget(result_ic, 0, Qt.AlignmentFlag.AlignTop)
        status_lbl = label("Starting…", "body", wrap=True)
        row.addWidget(status_lbl, 1)
        dlg.body.addLayout(row)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setFixedHeight(6)
        bar.setTextVisible(False)
        dlg.body.addWidget(bar)
        restart_btn = None
        if offer_restart:
            restart_btn = dlg.add_button("Restart Steam", on_click=lambda: self._restart_steam_now(dlg), icon="refresh-cw")
            restart_btn.setEnabled(False)
        close_btn = dlg.add_button("Close", "primary", on_click=dlg.accept)
        close_btn.setEnabled(False)

        class _Sig(QObject):
            progress = Signal(str)
            finished = Signal(bool, str)
        sig = _Sig()
        sig.progress.connect(status_lbl.setText)

        def _on_finished(ok, msg):
            status_lbl.setText(msg)
            _fit_wrapped(status_lbl)
            result_ic.setPixmap(icons.pixmap("circle-check" if ok else "circle-x",
                                             C["green"] if ok else C["red"], 16))
            bar.setRange(0, 1)
            bar.setValue(1)
            close_btn.setEnabled(True)
            if restart_btn is not None and ok:
                restart_btn.setEnabled(True)
            self._notify(f"[{title}] {msg.splitlines()[0]}", "success" if ok else "error")
        sig.finished.connect(_on_finished)

        def _thread():
            try:
                ok, msg = done(work(sig.progress.emit))
                sig.finished.emit(bool(ok), str(msg))
            except Exception as e:
                sig.finished.emit(False, f"{e}")

        threading.Thread(target=_thread, daemon=True).start()
        dlg.exec()

    def _restart_steam_now(self, dlg=None):
        """Restart Steam so it re-reads grid + librarycache (refuses while a game runs)."""
        import threading
        from app.services.steamSync import restart_steam
        self._notify("[Steam] Restarting Steam…", "info")

        class _Sig(QObject):
            done = Signal(bool)
        sig = _Sig(self)                 # parented: must outlive this method until the thread reports

        def _done(ok: bool):
            self._notify(
                "[Steam] Restart requested — Steam shows the new artwork when it is back." if ok
                else "[Steam] Not restarted (a game is running, or Steam was not found). Restart it yourself.",
                "success" if ok else "error")
            sig.deleteLater()
        sig.done.connect(_done)
        threading.Thread(target=lambda: sig.done.emit(bool(restart_steam(silent=True))), daemon=True).start()
        if dlg is not None:
            dlg.accept()

    # ── File handlers ─────────────────────────────────────────────────────────

    def _import_image_as_layer(self):
        """File → Import Image as Layer — adds image as draggable canvas layer."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Image as Layer", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tiff)"
        )
        if not path:
            return
        tab = self.tab_manager.current_tab()
        tab.preview_canvas.add_image_layer(path, name=os.path.basename(path))
        tab.editor_panel._refresh_layer_list()
        self._notify(f"Added layer: {os.path.basename(path)}", "info")

    def _export_all_assets(self):
        """File → Export All Assets — confirms AppID once then exports all 5 templates."""
        from app.services.exportFlow import _get_or_confirm_app_id, run_export_flow
        from PySide6.QtWidgets import QProgressDialog
        tab = self.tab_manager.current_tab()

        # Confirm AppID a single time up-front
        app_id = _get_or_confirm_app_id(tab, parent_widget=self)
        if app_id is None:
            return   # user cancelled

        templates = ["cover", "wide", "hero", "logo", "icon"]
        saved = []

        progress = QProgressDialog("Preparing…", "Cancel", 0, len(templates), self)
        progress.setWindowTitle("Export All Assets")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        orig_tpl = tab.state.current_template
        try:
            for i, tpl in enumerate(templates):
                if progress.wasCanceled():
                    break
                progress.setLabelText(f"Exporting  {tpl}…")
                progress.setValue(i)
                # Process Qt events so the progress bar actually repaints
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()

                tab.state.current_template = tpl
                # AppID is already in tab.state — run_export_flow won't re-ask
                path = run_export_flow(tab, parent_widget=self)
                if path:
                    saved.append(path)
                    tab.state.export_paths[tpl] = path  # track for Sync
        finally:
            tab.state.current_template = orig_tpl
            progress.setValue(len(templates))

        if saved:
            names = "\n".join(f"  {os.path.basename(p)}" for p in saved)
            QMessageBox.information(
                self, "Export All Complete",
                f"Exported {len(saved)} of {len(templates)} asset(s):\n\n"
                f"{names}\n\n"
                "Use  Sync to Steam  in the menu bar to install them."
            )
        elif not progress.wasCanceled():
            QMessageBox.warning(self, "Export All", "Nothing was exported.\nAdd artwork to the canvas first.")

    def _import_texture_files(self):
        """File → Import Textures → Import Texture Files."""
        from app.config import USER_TEXTURES_DIR as TEXTURES_DIR
        import shutil
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Texture Files", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tiff);;All Files (*)"
        )
        if not paths:
            return
        os.makedirs(TEXTURES_DIR, exist_ok=True)
        copied = 0
        for src in paths:
            dst = os.path.join(TEXTURES_DIR, os.path.basename(src))
            if src != dst:
                shutil.copy2(src, dst); copied += 1
        self._notify(f"Imported {copied} texture(s) to {TEXTURES_DIR}", "success")

    def _open_textures_folder(self):
        """File → Import Textures → Open Textures Folder."""
        import subprocess, sys
        from app.config import USER_TEXTURES_DIR as TEXTURES_DIR
        os.makedirs(TEXTURES_DIR, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(TEXTURES_DIR)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", TEXTURES_DIR])
        else:
            subprocess.Popen(["xdg-open", TEXTURES_DIR])

    # ── Edit handlers ──────────────────────────────────────────────────────────

    def _duplicate_layer(self):
        """Edit → Duplicate Layer (Ctrl+D)."""
        tab = self.tab_manager.current_tab()
        # EditorPanel._duplicate_layer() handles selection + refresh
        tab.editor_panel._duplicate_layer()

    def _delete_layer(self):
        """Edit → Delete Layer (Delete key)."""
        tab = self.tab_manager.current_tab()
        tab.editor_panel._delete_selected_layer()

    def _open_preferences(self):
        """Edit → Preferences — paths, cache management, account, AppID registry."""
        from app.config import EXPORT_FOLDER, CACHE_FOLDER, DATA_DIR
        from app.config import USER_FONTS_DIR, USER_TEXTURES_DIR
        from app.services.steamSync import find_steam_userdata
        from app.services.steamkustom_auth import get_token, save_token, verify_async
        import json, shutil

        PREFS_FILE = os.path.join(DATA_DIR, "preferences.json")
        try:
            with open(PREFS_FILE) as f:
                prefs = json.load(f)
        except Exception:
            prefs = {}

        def _save_prefs():
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(PREFS_FILE, "w") as f:
                json.dump(prefs, f, indent=2)

        dlg = _Dialog(self, "Preferences", "", min_width=600, icon="settings")
        dlg.setMinimumHeight(600)

        # Sections live in a scroll area so the dialog never outgrows a 650 px screen
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        col = vbox(inner, (0, 0, SP["xs"], 0), SP["md"])
        scroll.setWidget(inner)
        dlg.body.addWidget(scroll, 1)

        def _path_field(text: str) -> QLineEdit:
            e = QLineEdit(text)
            e.setReadOnly(True)
            e.setCursorPosition(0)
            return e

        # ── STEAM FOLDER ──────────────────────────────────────────────────
        sec = Section("Steam folder", collapsible=False)
        sec.body.addWidget(label("Steam userdata folder used by Sync to Steam. Auto-detected; "
                                 "set it manually if detection fails.", "dim", wrap=True))
        g = grid(h=SP["md"], v=SP["sm"])
        steam_edit = _path_field(find_steam_userdata() or "")
        steam_edit.setPlaceholderText("Not found")

        def _locate():
            self._locate_steam_folder()
            steam_edit.setText(find_steam_userdata() or "")
            steam_edit.setCursorPosition(0)
        _form_row(g, 0, "userdata", steam_edit, Button("Locate…", icon="folder-open", on_click=_locate))
        sec.body.addLayout(g)
        col.addWidget(sec)

        # ── PIMPMYSTEAM ACCOUNT ───────────────────────────────────────────
        sec = Section("PimpMySteam account", collapsible=False)
        sec.body.addWidget(label("Generate a token at pimpmysteam.com → Settings → Apps and paste it "
                                 "here to enable Google Drive sync.", "dim", wrap=True))
        g = grid(h=SP["md"], v=SP["sm"])
        sk_token_edit = QLineEdit()
        sk_token_edit.setPlaceholderText("Paste your app token from pimpmysteam.com…")
        sk_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        sk_verify_btn = Button("Verify", icon="shield-check")
        _form_row(g, 0, "App token", sk_token_edit, sk_verify_btn)

        sk_row = hbox(spacing=SP["sm"])
        sk_ic = QLabel()
        sk_ic.setFixedSize(16, 16)
        sk_status = label("Not connected", "dim", elide=True)
        sk_row.addWidget(sk_ic)
        sk_row.addWidget(sk_status, 1)
        _form_row(g, 1, "Status", sk_row)
        sec.body.addLayout(g)

        def _sk_set(text, tone, icon_name, color):
            sk_status.setText(text)
            kit.set_tone(sk_status, tone)
            sk_ic.setPixmap(icons.pixmap(icon_name, color, 16))

        saved = get_token() or ""
        if saved:
            sk_token_edit.setText(saved)
            _sk_set("Token saved", "green", "circle-check", C["green"])
        else:
            _sk_set("Not connected", None, "circle-dot", C["text_muted"])

        def _verify_token():
            token = sk_token_edit.text().strip()
            if not token:
                _sk_set("Enter a token first", "gold", "triangle-alert", C["gold"])
                return
            sk_verify_btn.set_loading(True)
            _sk_set("Verifying…", "accent", "loader-circle", C["accent"])

            def _done(ok, user):
                def _upd():
                    sk_verify_btn.set_loading(False)
                    if ok and user:
                        username = user.get("username", "Connected")
                        if save_token(token):
                            _sk_set(f"Connected as {username}", "green", "circle-check", C["green"])
                        else:
                            _sk_set("Valid token but could not save it (check write permissions in data folder)",
                                    "red", "circle-x", C["red"])
                    else:
                        _sk_set("Invalid token — generate one at pimpmysteam.com", "red", "circle-x", C["red"])
                # Runs in the verify thread — hand the update to the GUI thread
                QTimer.singleShot(0, dlg, _upd)

            verify_async(token, _done)

        sk_verify_btn.clicked.connect(_verify_token)
        sec.body.addWidget(Button("Open pimpmysteam.com → Settings → Apps", "link", icon="external-link",
                                  on_click=lambda: __import__("webbrowser").open("https://pimpmysteam.com/settings")),
                           0, Qt.AlignmentFlag.AlignLeft)
        stats_cb = QCheckBox("Send anonymous usage count to PimpMySteam")
        stats_cb.setToolTip("Only the number of artworks applied is sent — nothing else.")
        stats_cb.setChecked(bool(prefs.get("send_usage_stats", False)))
        stats_cb.stateChanged.connect(
            lambda v: prefs.update({"send_usage_stats": bool(v)}) or _save_prefs())
        sec.body.addWidget(stats_cb)
        col.addWidget(sec)

        # ── APPID REGISTRY ────────────────────────────────────────────────
        sec = Section("AppID registry", collapsible=False)
        sec.body.addWidget(label("Game name → AppID pairs remembered from previous exports. "
                                 "Remove an entry if the wrong game was picked.", "dim", wrap=True))
        sec.body.addWidget(Button("Manage AppID mappings…", icon="list",
                                  on_click=lambda: self._open_appid_registry(dlg)),
                           0, Qt.AlignmentFlag.AlignLeft)
        col.addWidget(sec)

        # ── CACHE ─────────────────────────────────────────────────────────
        sec = Section("Cache", collapsible=False)
        g = grid(h=SP["md"], v=SP["sm"])
        cache_edit = _path_field(str(CACHE_FOLDER))
        cache_size_lbl = label("Calculating…", "mono")
        cache_size_lbl.setMinimumWidth(80)

        def _update_cache_size():
            try:
                total = sum(
                    os.path.getsize(os.path.join(dp, f))
                    for dp, _, files in os.walk(CACHE_FOLDER)
                    for f in files
                )
                cache_size_lbl.setText(f"{total / (1024 * 1024):.1f} MB")
            except Exception:
                cache_size_lbl.setText("—")

        _update_cache_size()
        _form_row(g, 0, "Folder", cache_edit)
        clear_cache_btn = Button("Clear cache", "danger", icon="trash")

        def _clear_cache():
            try:
                shutil.rmtree(CACHE_FOLDER, ignore_errors=True)
                os.makedirs(CACHE_FOLDER, exist_ok=True)
                _update_cache_size()
                self._notify("Cache cleared.", "success")
            except Exception as e:
                QMessageBox.warning(dlg, "Error", str(e))

        clear_cache_btn.clicked.connect(_clear_cache)
        _form_row(g, 1, "Size", cache_size_lbl, clear_cache_btn)
        sec.body.addLayout(g)
        col.addWidget(sec)

        # ── FOLDERS ───────────────────────────────────────────────────────
        sec = Section("Fonts & textures folders", collapsible=False)
        g = grid(h=SP["md"], v=SP["sm"])
        _form_row(g, 0, "Exports", _path_field(str(EXPORT_FOLDER)),
                  Button("Open", icon="folder-open", on_click=self._open_exports_folder))
        _form_row(g, 1, "Fonts", _path_field(str(USER_FONTS_DIR)),
                  Button("Open", icon="folder-open", on_click=self._open_fonts_folder))
        _form_row(g, 2, "Textures", _path_field(str(USER_TEXTURES_DIR)),
                  Button("Open", icon="folder-open", on_click=self._open_textures_folder))
        sec.body.addLayout(g)
        col.addWidget(sec)
        col.addStretch()

        dlg.add_button("Close", "primary", on_click=dlg.accept)
        dlg.exec()

    # ── Brushes handlers ───────────────────────────────────────────────────────


    def _open_appid_registry(self, parent=None):
        """Preferences → Manage AppID mappings: list + remove entries."""
        from app.services.appIdRegistry import AppIdRegistry
        reg = AppIdRegistry.shared()

        dlg = _Dialog(parent or self, "AppID mappings",
                      "Searched name → Steam game [AppID]. Remove an entry to be asked again on the next export.",
                      min_width=520, icon="list")
        dlg.setMinimumHeight(400)
        lst = QListWidget()
        dlg.body.addWidget(lst, 1)
        empty = kit.EmptyState("list", "No AppID mappings yet", "They are remembered after each export.")
        dlg.body.addWidget(empty)

        def _fill():
            lst.clear()
            for key, entry in sorted(reg.all_entries().items()):
                lst.addItem(f"{key}  →  {entry.get('canonical', key)}  [{entry.get('id')}]")
                lst.item(lst.count() - 1).setData(Qt.ItemDataRole.UserRole, key)
            has = lst.count() > 0
            lst.setVisible(has)
            empty.setVisible(not has)
        _fill()

        def _remove():
            for it in lst.selectedItems():
                reg.remove(it.data(Qt.ItemDataRole.UserRole))
            # forget it in every open tab too, so the next export re-asks
            for t in self.tab_manager.tabs():
                if reg.lookup(t.state.selected_game_name or "") is None:
                    t.state.confirmed_app_id = None
            _fill()
        rm = Button("Remove selected", "danger", icon="trash", on_click=_remove)
        dlg.buttons.insertWidget(0, rm)
        dlg.add_button("Close", "primary", on_click=dlg.accept)
        dlg.exec()

    def _reload_font_library(self):
        """Fonts → Reload Font Library — re-scans fonts folder and refreshes combo."""
        from app.config import font_dirs
        from app.ui.fontImporter import register_all_fonts
        n = sum(register_all_fonts(d) for d in font_dirs())
        self._refresh_font_combo()
        self._notify(f"Font library reloaded — {n} families registered.", "success")

    # ── Sync to Steam handlers ─────────────────────────────────────────────────

    def _locate_steam_folder(self):
        """Sync to Steam → Locate Steam Folder — manual path override."""
        from app.services.steamSync import find_steam_userdata
        import json
        from app.config import DATA_DIR

        current = find_steam_userdata() or ""
        path = QFileDialog.getExistingDirectory(
            self, "Select Steam userdata folder", current or os.path.expanduser("~")
        )
        if not path:
            return
        # Persist override to a small JSON config
        override_file = os.path.join(DATA_DIR, "steam_path_override.json")
        try:
            with open(override_file, "w") as f:
                json.dump({"userdata": path}, f)
            self._notify(f"Steam folder set to: {path}", "success")
            QMessageBox.information(self, "Steam Folder Set",
                                    f"Steam userdata folder set to:\n{path}\n\n"
                                    "This will be used for all future Sync operations.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not save path:\n{e}")

    def _rescan_steam_library(self):
        """Sync to Steam → Rescan Steam Library — re-detect Steam IDs."""
        from app.services.steamSync import find_steam_userdata, list_steam_ids
        ud = find_steam_userdata()
        if not ud:
            QMessageBox.warning(self, "Not Found",
                                "Could not locate Steam installation.\n"
                                "Use  Locate Steam Folder  to set it manually.")
            return
        ids = list_steam_ids(ud)
        self._status_label.setText(f"Steam rescan: found {len(ids)} account(s) in {ud}")
        QMessageBox.information(
            self, "Steam Library Rescanned",
            f"Found {len(ids)} Steam account(s):\n" + "\n".join(ids)
            + f"\n\nUserdata path:\n{ud}"
        )

    # ── Help handlers ──────────────────────────────────────────────────────────

    def _show_api_key_help(self):
        """Help → Getting SteamGridDB API Key."""
        import webbrowser
        url = "https://www.steamgriddb.com/profile/preferences/api"

        dlg = _Dialog(self, "SteamGridDB API key",
                      "Artwork search uses the SteamGridDB API. The key is free and stored locally — "
                      "it is never shared.", min_width=500, icon="key-round")
        steps = [
            "Open the SteamGridDB API page (button below).",
            "Log in or create a free account.",
            "Click Generate API Key and copy it.",
            "In Steam Grunge Editor, click Set API Key in the search panel (top left) and paste it.",
        ]
        g = grid(h=SP["md"], v=SP["sm"])
        for i, text in enumerate(steps):
            num = label(f"{i + 1}.", "value")
            num.setFixedWidth(22)
            g.addWidget(num, i, 0, Qt.AlignmentFlag.AlignTop)
            g.addWidget(label(text, "body", wrap=True), i, 1)
        g.setColumnStretch(1, 1)
        dlg.body.addLayout(g)
        dlg.body.addWidget(label(url, "mono", tone="accent", elide=True))

        dlg.add_button("Close", on_click=dlg.accept)
        dlg.add_button("Open SteamGridDB API page", "primary", icon="external-link",
                       on_click=lambda: webbrowser.open(url))
        dlg.exec()

    def _show_quickstart(self):
        """Help → Quick Start Tutorial."""
        dlg = _Dialog(self, "Quick start", "Seven steps from an empty canvas to custom artwork in your "
                      "Steam library.", min_width=540, icon="zap")
        dlg.setMinimumHeight(520)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        col = vbox(inner, (0, 0, SP["sm"], 0), SP["sm"])
        scroll.setWidget(inner)
        dlg.body.addWidget(scroll, 1)

        steps = [
            ("key-round", "Set your API key",
             "Click Set API Key in the top-left search panel and paste your SteamGridDB key "
             "(Help → Getting SteamGridDB API Key)."),
            ("search", "Search for a game",
             "Type a game name and press Search, then select the game from the results list."),
            ("image", "Pick artwork",
             "Click any artwork thumbnail to add it as a canvas layer. Use the Type filter "
             "(Grids / Heroes / Logos / Icons) to switch artwork types."),
            ("layout-grid", "Choose a template",
             "In the right panel, select the template you want to create: Cover, Wide Cover, "
             "Hero, Logo, or Icon."),
            ("sliders-horizontal", "Apply effects",
             "Use the Film Grain, Chromatic Aberration and Color sliders to add a distressed / grunge look."),
            ("download", "Export",
             "File → Export (Ctrl+E) saves a single asset; File → Export All Assets (Ctrl+Shift+E) "
             "saves every format at once."),
            ("upload", "Sync to Steam",
             "Use the Sync to Steam menu to copy files into your Steam custom artwork folder. "
             "Restart Steam to see them."),
        ]
        for i, (ic, title, text) in enumerate(steps):
            card = kit.Section(f"Step {i + 1} — {title}", collapsible=False)
            row = hbox(spacing=SP["md"])
            pic = QLabel()
            pic.setPixmap(icons.pixmap(ic, C["accent"], 20))
            pic.setFixedSize(24, 24)
            row.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label(text, "body", wrap=True), 1)
            card.body.addLayout(row)
            col.addWidget(card)
        col.addStretch()

        dlg.add_button("Close", "primary", on_click=dlg.accept)
        dlg.exec()

    def _show_shortcuts(self):
        """Help → Keyboard Shortcuts."""
        dlg = _Dialog(self, "Keyboard shortcuts", "", min_width=520, icon="list")

        shortcuts = [
            ("FILE", None),
            ("Ctrl+N",           "New project (new tab)"),
            ("Ctrl+O",           "Open project"),
            ("Ctrl+S",           "Save project"),
            ("Ctrl+Shift+S",     "Save project as…"),
            ("Ctrl+Shift+O",     "Import image as layer"),
            ("Ctrl+E",           "Export artwork + apply to Steam"),
            ("Ctrl+Shift+E",     "Export all assets"),
            ("Ctrl+,",           "Preferences"),
            ("Ctrl+Q",           "Quit"),
            ("EDIT", None),
            ("Ctrl+Z",           "Undo"),
            ("Ctrl+Y / Ctrl+Shift+Z", "Redo"),
            ("Ctrl+D",           "Duplicate layer"),
            ("Delete",           "Delete layer"),
            ("Ctrl+Shift+C",     "Crop layer"),
            ("Arrow keys",       "Nudge layer (Shift = 10 px)"),
            ("SYNC", None),
            ("Ctrl+Shift+A",     "Sync to Steam"),
            ("Ctrl+Shift+U",     "Back up Steam artwork to Drive"),
            ("Ctrl+Shift+D",     "Restore Steam artwork from Drive"),
            ("TABS", None),
            ("Ctrl+T",           "New tab"),
            ("Ctrl+W",           "Close tab"),
            ("Ctrl+Tab",         "Next / previous tab"),
        ]

        # Two columns of sections so the dialog stays short
        groups: list[tuple[str, list]] = []
        for key, desc in shortcuts:
            if desc is None:
                groups.append((key, []))
            else:
                groups[-1][1].append((key, desc))

        cols = hbox(spacing=SP["lg"])
        halves = (groups[:2], groups[2:])
        for half in halves:
            c = vbox(spacing=SP["md"])
            for title, rows in half:
                g = grid(h=SP["md"], v=SP["xs"])
                g.addWidget(label(title, "section"), 0, 0, 1, 2)
                for r, (key, desc) in enumerate(rows, start=1):
                    k = label(key, "mono", tone="accent")
                    k.setMinimumWidth(150)
                    g.addWidget(k, r, 0)
                    g.addWidget(label(desc, "dim"), r, 1)
                g.setColumnStretch(1, 1)
                c.addLayout(g)
            c.addStretch()
            cols.addLayout(c, 1)
        dlg.body.addLayout(cols)

        dlg.add_button("Close", "primary", on_click=dlg.accept)
        dlg.exec()

    # ── Project file management (state lives on each WorkspaceTab) ──────────

    def _mark_dirty(self):
        """Compatibility shim — tabs mark themselves dirty via their own signals."""
        self.tab_manager.current_tab().mark_dirty()

    def _update_title(self):
        """Reflect current tab's project name + dirty state in the window title."""
        tab   = self.tab_manager.current_tab()
        dirty = " *" if tab.dirty else ""
        self.setWindowTitle(f"Steam Grunge Editor — {tab.display_name()}{dirty}")

    def _confirm_discard(self, tab=None) -> bool:
        """Return True if it is safe to discard unsaved changes of *tab*."""
        tab = tab or self.tab_manager.current_tab()
        if not tab.dirty:
            return True
        dlg = _Dialog(self, "Unsaved changes",
                      f"“{tab.display_name()}” has unsaved changes. Save them before closing?",
                      min_width=460, icon="triangle-alert")
        choice = {"v": "cancel"}

        def _pick(v):
            choice["v"] = v
            dlg.accept()
        dlg.add_button("Cancel", on_click=lambda: _pick("cancel"))
        dlg.add_button("Discard", "danger", icon="trash", on_click=lambda: _pick("discard"))
        save_btn = dlg.add_button("Save", "primary", icon="save", on_click=lambda: _pick("save"))
        save_btn.setDefault(True)
        dlg.exec()
        if choice["v"] == "save":
            self._save_project(tab)
            return not tab.dirty   # False if the save dialog was cancelled
        return choice["v"] == "discard"

    def _close_tab_requested(self, idx: int):
        """Tab close button / Ctrl+W — ask before dropping unsaved work."""
        tabs = self.tab_manager.tabs()
        if not (0 <= idx < len(tabs)):
            return
        if self._confirm_discard(tabs[idx]):
            self.tab_manager.close_tab(idx)
            self._update_title()

    def _new_project(self):
        """File → New Project: a fresh tab (reuses the current one if it is empty)."""
        cur = self.tab_manager.current_tab()
        if not cur.is_empty():
            self.tab_manager.add_tab()
        self._update_title()

    def _open_project(self):
        """File → Open Project…"""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project",
            os.path.expanduser("~"),
            f"Steam Grunge Editor Projects (*{SGEPROJ_EXT});;All Files (*)",
        )
        if not path:
            return
        self._load_project_from_path(path)

    def _load_project_from_path(self, path: str):
        # Load into the current tab only if it is untouched; otherwise a new tab
        tab = self.tab_manager.current_tab()
        if not tab.is_empty():
            tab = self.tab_manager.add_tab()
        try:
            load_project(tab, path)
            tab.project_path = path
            tab.mark_clean()
            tab.set_label(tab.state.selected_game_name or
                          os.path.splitext(os.path.basename(path))[0])
            self._update_title()
            self._notify(f"Opened: {os.path.basename(path)}", "success")
        except ProjectIOError as e:
            self.toasts.show(f"Open failed: {e}", "error")
            QMessageBox.critical(self, "Open Failed", str(e))

    def _save_project(self, tab=None):
        """File → Save Project (Ctrl+S)."""
        tab = tab or self.tab_manager.current_tab()
        if not tab.project_path:
            self._save_project_as(tab)
            return
        self._write_project(tab, tab.project_path)

    def _save_project_as(self, tab=None):
        """File → Save Project As… (Ctrl+Shift+S)."""
        tab  = tab or self.tab_manager.current_tab()
        name = tab.state.selected_game_name or "untitled"
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
        default = os.path.join(os.path.expanduser("~"), f"{safe}{SGEPROJ_EXT}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As",
            tab.project_path or default,
            f"Steam Grunge Editor Projects (*{SGEPROJ_EXT});;All Files (*)",
        )
        if not path:
            return
        if not path.endswith(SGEPROJ_EXT):
            path += SGEPROJ_EXT
        self._write_project(tab, path)

    def _write_project(self, tab, path: str):
        try:
            save_project(tab, path)
            tab.project_path = path
            tab.mark_clean()
            tab.set_label(tab.state.selected_game_name or
                          os.path.splitext(os.path.basename(path))[0])
            self._update_title()
            self._notify(f"Saved: {os.path.basename(path)}", "success")
        except ProjectIOError as e:
            self.toasts.show(f"Save failed: {e}", "error")
            QMessageBox.critical(self, "Save Failed", str(e))

    def _do_autosave(self):
        """Fires every 5 min — silently writes an autosave for every dirty tab."""
        for tab in self.tab_manager.tabs():
            if tab.dirty:
                autosave(tab)

    def closeEvent(self, event):
        """Prompt to save every tab with unsaved changes before quitting."""
        for tab in self.tab_manager.tabs():
            if tab.dirty:
                self.tab_manager.switch_tab(self.tab_manager.index_of(tab))
                if not self._confirm_discard(tab):
                    event.ignore()
                    return
        # Flush artwork counter to backend before exit
        try:
            from app.services.steamSync import _session_artwork_counter
            _session_artwork_counter.flush()
        except Exception:
            pass
        event.accept()

    # ── Update checker ────────────────────────────────────────────────────────

    def _check_for_updates(self, manual: bool = True):
        """
        Help → Check for Updates (manual=True: always answers) and the quiet
        check 3 s after start (manual=False: only speaks when something is new).
        """
        import threading
        from app.services.updates import check_latest

        class _Sig(QObject):
            done = Signal(object)
        sig = _Sig()
        sig.done.connect(lambda r: self._on_update_check(r, manual))
        threading.Thread(target=lambda: sig.done.emit(check_latest(APP_VERSION)), daemon=True).start()

    def _on_update_check(self, r: dict, manual: bool):
        if r.get("error"):
            if manual:
                self._notify(f"Could not check for updates: {r['error']}", "error")
            return
        if r["available"]:
            self._release_url = r["url"]
            self._show_update_banner(r["latest"])
        elif manual:
            self._notify(f"You're up to date — {APP_VERSION} is the newest release.", "success")

    def _show_update_banner(self, latest_version: str):
        if getattr(self, "_update_banner", None) is not None:
            self._notify(f"Update available: v{latest_version} — see the status bar", "info")
            return
        btn = Button(f"Update available: v{latest_version}", "success", icon="download",
                     on_click=self._open_release_page, tooltip="Click to open the download page")
        self._update_banner = btn
        self.status_bar.insertPermanentWidget(0, btn)
        self._notify(f"Update available: v{latest_version} — see the status bar", "info")

    def _open_release_page(self):
        import webbrowser
        webbrowser.open(getattr(self, "_release_url", None) or "https://github.com/Huzzama/Steam-Grunge/releases/latest")

    def _report_issue(self):
        """Help → Report Issue — opens GitHub issues page."""
        import webbrowser
        webbrowser.open("https://github.com/Huzzama/Steam-Grunge/issues")

    def _show_about(self):
        import webbrowser
        dlg = _Dialog(self, "Steam Grunge Editor", "", min_width=460, icon="sparkles")
        g = grid(h=SP["md"], v=SP["sm"])
        _form_row(g, 0, "Version", label(f"v{APP_VERSION}", "value"))
        _form_row(g, 1, "What it does", label("Create distressed, grunge-style Steam artwork and install it "
                                              "straight into your Steam library.", "body", wrap=True))
        _form_row(g, 2, "Artwork search", label("SteamGridDB API", "body"))
        _form_row(g, 3, "Cloud backup", label("PimpMySteam + Google Drive", "body"))
        dlg.body.addLayout(g)
        dlg.body.addWidget(label("Icons: Lucide (ISC licence).", "muted"))
        dlg.add_button("GitHub", icon="external-link",
                       on_click=lambda: webbrowser.open("https://github.com/Huzzama/Steam-Grunge"))
        dlg.add_button("Close", "primary", on_click=dlg.accept)
        dlg.exec()
