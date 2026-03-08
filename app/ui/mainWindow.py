import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QStatusBar, QMenuBar, QMenu, QFileDialog,
    QMessageBox, QToolBar, QPushButton, QLabel, QSlider
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QAction, QKeySequence, QFont
from app.ui.canvas.previewCanvas import PreviewCanvas
from app.ui.searchPanel import SearchPanel
from app.ui.editorPanel import EditorPanel
from app.ui.brushPanel import BrushPanel
from app.ui.floatingContextTb import FloatingContextTb
from app.ui.tabManager import TabManager
from app.state import state
from app.editor import compositor
from app.editor import exports as exporter


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Steam Grunge Editor")
        self.setMinimumSize(1600, 900)
        self.resize(1800, 1000)

        self._build_menu()
        self._build_status_bar()
        self._build_ui()

        # Compose timer (debounce re-renders)
        self._compose_timer = QTimer()
        self._compose_timer.setSingleShot(True)
        self._compose_timer.setInterval(120)
        self._compose_timer.timeout.connect(self._do_compose)

    def _build_toolbar(self):
        tb = QToolBar("Tools")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setStyleSheet("""
            QToolBar {
                background: #111;
                border-bottom: 1px solid #2a2a2a;
                spacing: 4px;
                padding: 4px 8px;
            }
            QPushButton {
                background: #1e1e1e;
                color: #aaa;
                border: 1px solid #333;
                border-radius: 3px;
                font-family: 'Courier New';
                font-size: 13px;
                padding: 4px 12px;
                min-width: 36px;
            }
            QPushButton:hover  { background: #2a2a3a; color: #ddd; border-color: #555; }
            QPushButton:pressed { background: #1a1a2a; }
            QPushButton#crop_btn[active="true"] {
                background: #1a2e1a;
                color: #88cc88;
                border-color: #3a6e3a;
            }
            QLabel#sep { color: #333; font-size: 18px; padding: 0 4px; }
        """)
        self.addToolBar(Qt.TopToolBarArea, tb)

        # App title
        title = QLabel("✦ STEAM GRUNGE")
        title.setStyleSheet("color:#3a6e3a; font-family:'Courier New'; "
                            "font-size:13px; font-weight:bold; padding-right:12px;")
        tb.addWidget(title)

        sep1 = QLabel("|"); sep1.setObjectName("sep"); tb.addWidget(sep1)

        # Undo / Redo
        self._btn_undo = QPushButton("↩ Undo")
        self._btn_undo.setToolTip("Undo  (Ctrl+Z)")
        self._btn_undo.clicked.connect(self._undo)
        tb.addWidget(self._btn_undo)

        self._btn_redo = QPushButton("↪ Redo")
        self._btn_redo.setToolTip("Redo  (Ctrl+Y)")
        self._btn_redo.clicked.connect(self._redo)
        tb.addWidget(self._btn_redo)

        sep2 = QLabel("|"); sep2.setObjectName("sep"); tb.addWidget(sep2)

        # Crop tool
        self._btn_crop = QPushButton("✂ Crop")
        self._btn_crop.setObjectName("crop_btn")
        self._btn_crop.setToolTip("Crop selected layer  (select image layer first)")
        self._btn_crop.setCheckable(True)
        self._btn_crop.clicked.connect(self._toggle_crop)
        tb.addWidget(self._btn_crop)

        # Crop apply / cancel (hidden until crop active)
        self._btn_crop_apply = QPushButton("✔ Apply Crop")
        self._btn_crop_apply.setStyleSheet(
            "background:#1a2e1a; color:#88cc88; border-color:#3a6e3a;")
        self._btn_crop_apply.setToolTip("Apply crop  (Enter)")
        self._btn_crop_apply.clicked.connect(lambda: self._end_crop(True))
        self._btn_crop_apply.setVisible(False)
        tb.addWidget(self._btn_crop_apply)

        self._btn_crop_cancel = QPushButton("✖ Cancel")
        self._btn_crop_cancel.setStyleSheet(
            "background:#2e1a1a; color:#cc8888; border-color:#6e3a3a;")
        self._btn_crop_cancel.setToolTip("Cancel crop  (Esc)")
        self._btn_crop_cancel.clicked.connect(lambda: self._end_crop(False))
        self._btn_crop_cancel.setVisible(False)
        tb.addWidget(self._btn_crop_cancel)

    # ── Safe widget helper ─────────────────────────────────────────────────────
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

    def _toggle_brush_panel(self, checked: bool = None):
        """B key / toolbar button — show or hide the brush panel of the active tab."""
        tab = self.tab_manager.current_tab()
        if checked is None:
            checked = not tab.brush_panel.isVisible()
        tab.toggle_brush_panel(checked)
        if hasattr(self, '_brush_menu_act'):
            self._brush_menu_act.setChecked(checked)
        if hasattr(self, '_btn_brush') and self._widget_alive(self._btn_brush):
            self._btn_brush.blockSignals(True)
            self._btn_brush.setChecked(checked)
            self._btn_brush.blockSignals(False)

    def _activate_brush_tool(self):
        """Select Brush tool inside panel (also shows panel)."""
        self._toggle_brush_panel(True)
        if hasattr(self, 'brush_panel'):
            self.brush_panel._on_tool_selected("brush")

    def _activate_eraser_tool(self):
        """Select Eraser tool inside panel (also shows panel)."""
        self._toggle_brush_panel(True)
        if hasattr(self, 'brush_panel'):
            self.brush_panel._on_tool_selected("eraser")

    def _toggle_brush(self, checked: bool = False):
        """Legacy compatibility."""
        self._toggle_brush_panel(checked)

    def _import_brushes_zip(self):
        """File → Import Brushes → From ZIP Pack…"""
        from app.ui.brushImporter import run_zip_import_dialog
        result = run_zip_import_dialog(self)
        if result and result.imported:
            self.brush_panel._load_brushes()
            self._status_label.setText(
                f"Imported {len(result.imported)} brush(es) from '{result.pack_name}'")

    def _import_brushes_files(self):
        """File → Import Brushes → Individual Files…"""
        from PySide6.QtWidgets import QFileDialog
        from app.config import ASSETS_DIR
        import os, shutil
        brushes_dir = os.path.join(ASSETS_DIR, "brushes")
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Brush Files", "",
            "Brush Files (*.gbr *.gih *.vbr *.png *.jpg *.jpeg);;All Files (*)")
        if not paths:
            return
        os.makedirs(brushes_dir, exist_ok=True)
        copied = 0
        for src in paths:
            dst = os.path.join(brushes_dir, os.path.basename(src))
            if src != dst:
                shutil.copy2(src, dst)
                copied += 1
        self.brush_panel._load_brushes()
        self._status_label.setText(f"Imported {copied} brush file(s)")

    # ── Font menu handlers ───────────────────────────────────────────────────────

    def _import_font_zip(self):
        """Fonts → Import Font Pack (ZIP)…"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from app.ui.fontImporter import import_fonts
        from app.config import FONTS_DIR
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Font Pack", "",
            "ZIP Font Pack (*.zip)"
        )
        if not path:
            return
        result = import_fonts([path], FONTS_DIR)
        self._refresh_font_combo()
        QMessageBox.information(self, "Font Import", result.summary())

    def _import_font_files(self):
        """Fonts → Import Font Files…"""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from app.ui.fontImporter import import_fonts
        from app.config import FONTS_DIR
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Fonts", "",
            "Font Files (*.ttf *.otf *.woff *.woff2)"
        )
        if not paths:
            return
        result = import_fonts(paths, FONTS_DIR)
        self._refresh_font_combo()
        msg = result.summary()
        if result.failed:
            msg += "\n\nFailed:\n" + "\n".join(result.failed)
        QMessageBox.information(self, "Font Import", msg)

    def _open_fonts_folder(self):
        """Fonts → Open Fonts Folder…"""
        import subprocess, sys
        from app.config import FONTS_DIR
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

    def _clear_brush_cache(self):
        """Brushes → Clear Thumbnail Cache + Reload."""
        try:
            from app.ui.brushImporter import clear_gih_cache
            n = clear_gih_cache()
            self.brush_panel._load_brushes()
            if hasattr(self, '_status_label'):
                self._status_label.setText(f"Cache cleared ({n} entries) — brushes reloaded")
        except Exception as e:
            if hasattr(self, '_status_label'):
                self._status_label.setText(f"Cache clear failed: {e}")

    def _open_brushes_folder(self):
        """Open the brushes directory in the OS file manager."""
        from app.config import ASSETS_DIR
        import os, subprocess, sys
        brushes_dir = os.path.join(ASSETS_DIR, "brushes")
        os.makedirs(brushes_dir, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(brushes_dir)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", brushes_dir])
        else:
            subprocess.Popen(["xdg-open", brushes_dir])

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

    def _build_toolbar(self):
        pass  # toolbar merged into menubar

    def _build_menu(self):
        menubar = self.menuBar()
        menubar.setStyleSheet("""
            QMenuBar {
                background: #111;
                color: #bbb;
                font-family: 'Courier New';
                font-size: 13px;
                border-bottom: 1px solid #2a2a2a;
                padding: 2px 4px;
                spacing: 2px;
            }
            QMenuBar::item {
                padding: 4px 10px;
                border-radius: 3px;
            }
            QMenuBar::item:selected { background: #222; color: #fff; }
            QMenu {
                background: #1a1a1a;
                border: 1px solid #333;
                color: #ccc;
                font-family: 'Courier New';
                font-size: 13px;
            }
            QMenu::item:selected { background: #2a2a4a; color: #fff; }
            QMenu::separator { height: 1px; background: #333; margin: 3px 8px; }
        """)

        # ═══════════════════════════════════════════════════════════════════
        # FILE
        # ═══════════════════════════════════════════════════════════════════
        file_menu = menubar.addMenu("File")

        open_act = QAction("Open Image…", self)
        open_act.setShortcut(QKeySequence("Ctrl+O"))
        open_act.triggered.connect(self._open_image)
        file_menu.addAction(open_act)

        import_layer_act = QAction("Import Image as Layer…", self)
        import_layer_act.setShortcut(QKeySequence("Ctrl+Shift+O"))
        import_layer_act.setToolTip("Add an image as a draggable layer without replacing the canvas")
        import_layer_act.triggered.connect(self._import_image_as_layer)
        file_menu.addAction(import_layer_act)

        file_menu.addSeparator()

        export_act = QAction("Export…", self)
        export_act.setShortcut(QKeySequence("Ctrl+E"))
        export_act.triggered.connect(self._export)
        file_menu.addAction(export_act)

        export_all_act = QAction("Export All Assets…", self)
        export_all_act.setShortcut(QKeySequence("Ctrl+Shift+E"))
        export_all_act.setToolTip("Generate cover, wide, hero, logo and icon from the current project")
        export_all_act.triggered.connect(self._export_all_assets)
        file_menu.addAction(export_all_act)

        file_menu.addSeparator()

        open_exports_act = QAction("Open Exports Folder", self)
        open_exports_act.triggered.connect(self._open_exports_folder)
        file_menu.addAction(open_exports_act)

        file_menu.addSeparator()

        import_brushes_menu = file_menu.addMenu("Import Brushes")
        imp_brush_zip_act = QAction("From ZIP Pack…", self)
        imp_brush_zip_act.setShortcut(QKeySequence("Ctrl+Shift+B"))
        imp_brush_zip_act.triggered.connect(self._import_brushes_zip)
        import_brushes_menu.addAction(imp_brush_zip_act)
        imp_brush_files_act = QAction("Individual Files…", self)
        imp_brush_files_act.triggered.connect(self._import_brushes_files)
        import_brushes_menu.addAction(imp_brush_files_act)

        import_textures_menu = file_menu.addMenu("Import Textures")
        imp_tex_files_act = QAction("Import Texture Files…", self)
        imp_tex_files_act.triggered.connect(self._import_texture_files)
        import_textures_menu.addAction(imp_tex_files_act)
        imp_tex_folder_act = QAction("Open Textures Folder…", self)
        imp_tex_folder_act.triggered.connect(self._open_textures_folder)
        import_textures_menu.addAction(imp_tex_folder_act)

        file_menu.addSeparator()

        quit_act = QAction("Quit", self)
        quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        # ═══════════════════════════════════════════════════════════════════
        # EDIT
        # ═══════════════════════════════════════════════════════════════════
        edit_menu = menubar.addMenu("Edit")

        undo_act = QAction("Undo", self)
        undo_act.setShortcut(QKeySequence("Ctrl+Z"))
        undo_act.triggered.connect(self._undo)
        edit_menu.addAction(undo_act)

        redo_act = QAction("Redo", self)
        redo_act.setShortcut(QKeySequence("Ctrl+Y"))
        redo_act.triggered.connect(self._redo)
        edit_menu.addAction(redo_act)

        edit_menu.addSeparator()

        dup_layer_act = QAction("Duplicate Layer", self)
        dup_layer_act.setShortcut(QKeySequence("Ctrl+D"))
        dup_layer_act.triggered.connect(self._duplicate_layer)
        edit_menu.addAction(dup_layer_act)

        del_layer_act = QAction("Delete Layer", self)
        del_layer_act.setShortcut(QKeySequence("Delete"))
        del_layer_act.triggered.connect(self._delete_layer)
        edit_menu.addAction(del_layer_act)

        edit_menu.addSeparator()

        crop_act = QAction("Crop Layer", self)
        crop_act.setShortcut(QKeySequence("Ctrl+Shift+C"))
        crop_act.triggered.connect(lambda: self._toggle_crop(True))
        edit_menu.addAction(crop_act)

        edit_menu.addSeparator()

        reset_act = QAction("Reset Filters", self)
        reset_act.triggered.connect(self._reset_filters)
        edit_menu.addAction(reset_act)

        edit_menu.addSeparator()

        prefs_act = QAction("Preferences…", self)
        prefs_act.triggered.connect(self._open_preferences)
        edit_menu.addAction(prefs_act)

        # ═══════════════════════════════════════════════════════════════════
        # BRUSHES
        # ═══════════════════════════════════════════════════════════════════
        brushes_menu = menubar.addMenu("Brushes")

        toggle_brush_act = QAction("Toggle Brush Panel", self)
        toggle_brush_act.setShortcut(QKeySequence("B"))
        toggle_brush_act.setCheckable(True)
        toggle_brush_act.triggered.connect(self._toggle_brush_panel)
        self._brush_menu_act = toggle_brush_act
        brushes_menu.addAction(toggle_brush_act)

        eraser_act = QAction("Eraser Tool", self)
        eraser_act.setShortcut(QKeySequence("E"))
        eraser_act.triggered.connect(self._activate_eraser_tool)
        brushes_menu.addAction(eraser_act)

        brushes_menu.addSeparator()

        create_brush_act = QAction("Create Brush From Image…", self)
        create_brush_act.setToolTip("Convert a texture or image file into a custom brush")
        create_brush_act.triggered.connect(self._create_brush_from_image)
        brushes_menu.addAction(create_brush_act)

        brushes_menu.addSeparator()

        brush_zip_act = QAction("Import ZIP Pack…", self)
        brush_zip_act.setShortcut(QKeySequence("Ctrl+Shift+B"))
        brush_zip_act.triggered.connect(self._import_brushes_zip)
        brushes_menu.addAction(brush_zip_act)

        brush_files_act = QAction("Import Individual Files…", self)
        brush_files_act.triggered.connect(self._import_brushes_files)
        brushes_menu.addAction(brush_files_act)

        brushes_menu.addSeparator()

        reload_brushes_act = QAction("Reload Brush Library", self)
        reload_brushes_act.triggered.connect(lambda: self.brush_panel._load_brushes())
        brushes_menu.addAction(reload_brushes_act)

        clear_cache_act = QAction("Clear Thumbnail Cache + Reload", self)
        clear_cache_act.triggered.connect(self._clear_brush_cache)
        brushes_menu.addAction(clear_cache_act)

        open_brushes_dir_act = QAction("Open Brushes Folder…", self)
        open_brushes_dir_act.triggered.connect(self._open_brushes_folder)
        brushes_menu.addAction(open_brushes_dir_act)

        # ═══════════════════════════════════════════════════════════════════
        # FONTS
        # ═══════════════════════════════════════════════════════════════════
        fonts_menu = menubar.addMenu("Fonts")

        import_font_zip_act = QAction("Import Font Pack (ZIP)…", self)
        import_font_zip_act.triggered.connect(self._import_font_zip)
        fonts_menu.addAction(import_font_zip_act)

        import_font_files_act = QAction("Import Font Files…", self)
        import_font_files_act.triggered.connect(self._import_font_files)
        fonts_menu.addAction(import_font_files_act)

        fonts_menu.addSeparator()

        reload_fonts_act = QAction("Reload Font Library", self)
        reload_fonts_act.triggered.connect(self._reload_font_library)
        fonts_menu.addAction(reload_fonts_act)

        open_fonts_dir_act = QAction("Open Fonts Folder…", self)
        open_fonts_dir_act.triggered.connect(self._open_fonts_folder)
        fonts_menu.addAction(open_fonts_dir_act)

        # ═══════════════════════════════════════════════════════════════════
        # SYNC TO STEAM
        # ═══════════════════════════════════════════════════════════════════
        sync_menu = menubar.addMenu("Sync to Steam")

        sync_now_act = QAction("⇪  Sync to Steam…", self)
        sync_now_act.setShortcut(QKeySequence("Ctrl+Shift+S"))
        sync_now_act.triggered.connect(self._open_sync_dialog)
        sync_menu.addAction(sync_now_act)

        sync_menu.addSeparator()

        locate_steam_act = QAction("Locate Steam Folder…", self)
        locate_steam_act.setToolTip("Manually set Steam installation path if auto-detection fails")
        locate_steam_act.triggered.connect(self._locate_steam_folder)
        sync_menu.addAction(locate_steam_act)

        rescan_act = QAction("Rescan Steam Library", self)
        rescan_act.setToolTip("Re-check Steam folders and available user accounts")
        rescan_act.triggered.connect(self._rescan_steam_library)
        sync_menu.addAction(rescan_act)

        sync_menu.addSeparator()

        open_exports_sync_act = QAction("Open Exports Folder…", self)
        open_exports_sync_act.triggered.connect(self._open_exports_folder)
        sync_menu.addAction(open_exports_sync_act)

        # ═══════════════════════════════════════════════════════════════════
        # HELP
        # ═══════════════════════════════════════════════════════════════════
        help_menu = menubar.addMenu("Help")

        api_key_act = QAction("Getting SteamGridDB API Key", self)
        api_key_act.triggered.connect(self._show_api_key_help)
        help_menu.addAction(api_key_act)

        quickstart_act = QAction("Quick Start Tutorial", self)
        quickstart_act.triggered.connect(self._show_quickstart)
        help_menu.addAction(quickstart_act)

        shortcuts_act = QAction("Keyboard Shortcuts", self)
        shortcuts_act.triggered.connect(self._show_shortcuts)
        help_menu.addAction(shortcuts_act)

        help_menu.addSeparator()

        report_act = QAction("Report Issue", self)
        report_act.triggered.connect(self._report_issue)
        help_menu.addAction(report_act)

        help_menu.addSeparator()

        about_act = QAction("About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

        # ── Inline action buttons (right of menu items) ───────────────────────
        # Spacer to push buttons to the left but after menu items
        sep_label = QLabel("  |  ")
        sep_label.setStyleSheet("color:#333; font-size:16px; padding: 0 2px;")
        menubar.setCornerWidget(None)  # clear any corner widget

        btn_style = """
            QPushButton {
                background: transparent;
                color: #999;
                border: 1px solid #333;
                border-radius: 3px;
                font-family: 'Courier New';
                font-size: 12px;
                padding: 2px 10px;
                margin: 1px 2px;
            }
            QPushButton:hover  { background: #222; color: #ddd; border-color: #555; }
            QPushButton:pressed { background: #1a1a2a; }
            QPushButton:checked {
                background: #1a2e1a; color: #88cc88;
                border-color: #3a6e3a;
            }
        """

        # We add them as a corner widget container
        corner = QWidget()
        corner.setStyleSheet("background: #111;")
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 6, 0)
        corner_layout.setSpacing(3)

        divider = QLabel("|")
        divider.setStyleSheet("color:#333; font-size:15px; padding: 0 4px;")
        corner_layout.addWidget(divider)

        self._btn_undo = QPushButton("↩ Undo")
        self._btn_undo.setToolTip("Undo  (Ctrl+Z)")
        self._btn_undo.setStyleSheet(btn_style)
        self._btn_undo.clicked.connect(self._undo)
        corner_layout.addWidget(self._btn_undo)

        self._btn_redo = QPushButton("↪ Redo")
        self._btn_redo.setToolTip("Redo  (Ctrl+Y)")
        self._btn_redo.setStyleSheet(btn_style)
        self._btn_redo.clicked.connect(self._redo)
        corner_layout.addWidget(self._btn_redo)

        divider2 = QLabel("|")
        divider2.setStyleSheet("color:#333; font-size:15px; padding: 0 4px;")
        corner_layout.addWidget(divider2)

        self._btn_crop = QPushButton("✂ Crop")
        self._btn_crop.setToolTip("Crop selected layer  (select image layer first)")
        self._btn_crop.setCheckable(True)
        self._btn_crop.setStyleSheet(btn_style)
        self._btn_crop.clicked.connect(self._toggle_crop)
        corner_layout.addWidget(self._btn_crop)

        self._btn_crop_apply = QPushButton("✔ Apply")
        self._btn_crop_apply.setStyleSheet(
            btn_style + "QPushButton { background:#1a2e1a; color:#88cc88; border-color:#3a6e3a; }")
        self._btn_crop_apply.setToolTip("Apply crop  (Enter)")
        self._btn_crop_apply.clicked.connect(lambda: self._end_crop(True))
        self._btn_crop_apply.setVisible(False)
        corner_layout.addWidget(self._btn_crop_apply)

        self._btn_crop_cancel = QPushButton("✖")
        self._btn_crop_cancel.setStyleSheet(
            btn_style + "QPushButton { background:#2e1a1a; color:#cc8888; border-color:#6e3a3a; }")
        self._btn_crop_cancel.setToolTip("Cancel crop  (Esc)")
        self._btn_crop_cancel.clicked.connect(lambda: self._end_crop(False))
        self._btn_crop_cancel.setVisible(False)
        corner_layout.addWidget(self._btn_crop_cancel)

        divider3 = QLabel("|")
        divider3.setStyleSheet("color:#333; font-size:15px; padding: 0 4px;")
        corner_layout.addWidget(divider3)

        self._btn_brush = QPushButton("🖌 Brush")
        self._btn_brush.setToolTip("Toggle Brush Panel  [B]")
        self._btn_brush.setCheckable(True)
        self._btn_brush.setStyleSheet(btn_style)
        self._btn_brush.clicked.connect(lambda checked: self._toggle_brush_panel(checked))
        corner_layout.addWidget(self._btn_brush)

        divider_sync = QLabel("|")
        divider_sync.setStyleSheet("color:#333; font-size:15px; padding: 0 4px;")
        corner_layout.addWidget(divider_sync)

        self._btn_sync = QPushButton("⇪ Sync to Steam")
        self._btn_sync.setToolTip("Install artwork into Steam\'s custom grid folder")
        self._btn_sync.setStyleSheet(btn_style + """
            QPushButton { color: #88cc88; border-color: #3a5a3a; }
            QPushButton:hover { background: #1a2e1a; color: #aaffaa; border-color: #55aa55; }
        """)
        self._btn_sync.clicked.connect(self._open_sync_dialog)
        corner_layout.addWidget(self._btn_sync)

        menubar.setCornerWidget(corner, Qt.TopRightCorner)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Tab manager owns the tab bar + all workspaces
        self.tab_manager = TabManager()
        self.tab_manager.status_changed.connect(self._status_label.setText)

        # Periodically refresh the API key status indicator (every 3s)
        # so it updates immediately after the user sets their key without
        # requiring a dedicated signal from SearchPanel.
        from PySide6.QtCore import QTimer
        self._api_status_timer = QTimer(self)
        self._api_status_timer.setInterval(3000)
        self._api_status_timer.timeout.connect(self._refresh_api_key_status)
        self._api_status_timer.start()
        root_layout.addWidget(self.tab_manager, 1)

        # Ctrl+T → new tab,  Ctrl+W → close tab
        from PySide6.QtGui import QShortcut
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(self.tab_manager.add_tab)
        QShortcut(QKeySequence("Ctrl+W"), self).activated.connect(
            lambda: self.tab_manager.close_tab(self.tab_manager._stack.currentIndex()))

    # ── proxy properties so all existing slot code keeps working ──────────────
    @property
    def preview_canvas(self) -> PreviewCanvas:
        return self.tab_manager.preview_canvas

    @property
    def editor_panel(self) -> EditorPanel:
        return self.tab_manager.editor_panel

    @property
    def brush_panel(self) -> BrushPanel:
        return self.tab_manager.brush_panel

    def _build_status_bar(self):
        bar_style = """
            QStatusBar {
                background: #0e0e0e;
                color: #555;
                font-size: 11px;
                font-family: 'Courier New', monospace;
                border-top: 1px solid #2a2a2a;
                padding: 0px;
            }
            QStatusBar::item { border: none; }
        """
        btn_style = """
            QPushButton {
                background: transparent;
                color: #777;
                border: 1px solid #2a2a2a;
                border-radius: 3px;
                font-family: 'Courier New';
                font-size: 11px;
                padding: 2px 8px;
                margin: 2px 2px;
            }
            QPushButton:hover  { background: #1e1e2e; color: #bbb; border-color: #444; }
            QPushButton:pressed { background: #111; }
            QPushButton:checked { background: #1a2e1a; color: #88cc88; border-color: #3a6e3a; }
        """

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.setStyleSheet(bar_style)

        # ── Left side: action buttons ──────────────────────────────────────────
        left_w = QWidget()
        left_w.setStyleSheet("background:transparent;")
        left_lay = QHBoxLayout(left_w)
        left_lay.setContentsMargins(4, 0, 4, 0)
        left_lay.setSpacing(2)

        for label, tip, slot in [
            ("↩", "Undo  (Ctrl+Z)",      self._undo),
            ("↪", "Redo  (Ctrl+Y)",       self._redo),
        ]:
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setStyleSheet(btn_style)
            b.setFixedSize(28, 22)
            b.clicked.connect(slot)
            left_lay.addWidget(b)

        sep = QLabel("|")
        sep.setStyleSheet("color:#2a2a2a; padding:0 3px;")
        left_lay.addWidget(sep)

        self._sb_btn_crop = QPushButton("✂")
        self._sb_btn_crop.setToolTip("Crop layer  (Ctrl+Shift+C)")
        self._sb_btn_crop.setStyleSheet(btn_style)
        self._sb_btn_crop.setFixedSize(28, 22)
        self._sb_btn_crop.setCheckable(True)
        self._sb_btn_crop.clicked.connect(self._toggle_crop)
        left_lay.addWidget(self._sb_btn_crop)

        self._sb_crop_apply = QPushButton("✔")
        self._sb_crop_apply.setToolTip("Apply crop  (Enter)")
        self._sb_crop_apply.setStyleSheet(
            btn_style + "QPushButton{color:#88cc88;border-color:#3a6e3a;}")
        self._sb_crop_apply.setFixedSize(28, 22)
        self._sb_crop_apply.setVisible(False)
        self._sb_crop_apply.clicked.connect(lambda: self._end_crop(True))
        left_lay.addWidget(self._sb_crop_apply)

        self._sb_crop_cancel = QPushButton("✖")
        self._sb_crop_cancel.setToolTip("Cancel crop  (Esc)")
        self._sb_crop_cancel.setStyleSheet(
            btn_style + "QPushButton{color:#cc8888;border-color:#6e3a3a;}")
        self._sb_crop_cancel.setFixedSize(28, 22)
        self._sb_crop_cancel.setVisible(False)
        self._sb_crop_cancel.clicked.connect(lambda: self._end_crop(False))
        left_lay.addWidget(self._sb_crop_cancel)

        self.status_bar.addWidget(left_w)

        # ── Center: status message ─────────────────────────────────────────────
        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet(
            "color:#555; font-size:11px; font-family:'Courier New'; padding:0 8px;")
        self.status_bar.addWidget(self._status_label, 1)

        # ── Right side: zoom slider ────────────────────────────────────────────
        right_w = QWidget()
        right_w.setStyleSheet("background:transparent;")
        right_lay = QHBoxLayout(right_w)
        right_lay.setContentsMargins(4, 0, 8, 0)
        right_lay.setSpacing(4)

        zoom_lbl = QLabel("🔍")
        zoom_lbl.setStyleSheet("color:#555; font-size:12px;")
        right_lay.addWidget(zoom_lbl)

        self._zoom_slider = QSlider(Qt.Horizontal)
        self._zoom_slider.setRange(25, 300)   # 25% – 300%
        self._zoom_slider.setValue(100)
        self._zoom_slider.setFixedWidth(120)
        self._zoom_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 3px; background: #2a2a2a; border-radius: 1px;
            }
            QSlider::handle:horizontal {
                width: 10px; height: 10px;
                background: #666; border-radius: 5px; margin: -4px 0;
            }
            QSlider::handle:horizontal:hover { background: #aaa; }
            QSlider::sub-page:horizontal { background: #3a6e3a; border-radius: 1px; }
        """)
        self._zoom_slider.valueChanged.connect(self._on_zoom_changed)
        right_lay.addWidget(self._zoom_slider)

        self._zoom_pct_label = QLabel("100%")
        self._zoom_pct_label.setStyleSheet(
            "color:#555; font-size:11px; font-family:'Courier New'; min-width:36px;")
        right_lay.addWidget(self._zoom_pct_label)

        btn_zoom_reset = QPushButton("⊡")
        btn_zoom_reset.setToolTip("Reset zoom to fit")
        btn_zoom_reset.setStyleSheet(btn_style)
        btn_zoom_reset.setFixedSize(24, 22)
        btn_zoom_reset.clicked.connect(self._zoom_reset)
        right_lay.addWidget(btn_zoom_reset)

        # ── Separator ─────────────────────────────────────────────────────────
        sep2 = QLabel("|")
        sep2.setStyleSheet("color:#2a2a2a; padding:0 3px;")
        right_lay.addWidget(sep2)

        # ── Canvas rotation dial ───────────────────────────────────────────────
        btn_rot_ccw = QPushButton("↺")
        btn_rot_ccw.setToolTip("Rotate canvas −15°")
        btn_rot_ccw.setStyleSheet(btn_style)
        btn_rot_ccw.setFixedSize(24, 22)
        btn_rot_ccw.clicked.connect(lambda: self._rotate_canvas(-15))
        right_lay.addWidget(btn_rot_ccw)

        self._rot_label = QLabel("• 0.00°")
        self._rot_label.setStyleSheet(
            "color:#666; font-size:11px; font-family:'Courier New';"
            " min-width:56px; padding:0 2px;")
        self._rot_label.setToolTip("Canvas view rotation (double-click to reset)")
        self._rot_label.mouseDoubleClickEvent = lambda _: self._rotate_canvas_reset()
        right_lay.addWidget(self._rot_label)

        btn_rot_cw = QPushButton("↻")
        btn_rot_cw.setToolTip("Rotate canvas +15°")
        btn_rot_cw.setStyleSheet(btn_style)
        btn_rot_cw.setFixedSize(24, 22)
        btn_rot_cw.clicked.connect(lambda: self._rotate_canvas(+15))
        right_lay.addWidget(btn_rot_cw)

        # ── API Key status indicator ──────────────────────────────────────────
        self._api_key_lbl = QLabel("⬤  API Key: Not Set")
        self._api_key_lbl.setObjectName("api_key_status")
        self._api_key_lbl.setStyleSheet(
            "color:#664444; font-family:'Courier New'; font-size:11px;"
            " padding:2px 8px; margin-right:8px;"
        )
        self._api_key_lbl.setToolTip("SteamGridDB API key status — use Help → Getting SteamGridDB API Key")
        self.status_bar.addPermanentWidget(self._api_key_lbl)
        # Sync initial state
        self._refresh_api_key_status()

        self.status_bar.addPermanentWidget(right_w)

    def _on_zoom_changed(self, val: int):
        self._zoom_pct_label.setText(f"{val}%")
        if hasattr(self, 'preview_canvas'):
            self.preview_canvas.set_zoom(val / 100.0)

    def _zoom_reset(self):
        self._zoom_slider.setValue(100)

    def _refresh_api_key_status(self):
        """Update the API key status pill in the status bar."""
        try:
            from app.services.steamgrid import client as sgdb_client
            has_key = bool(sgdb_client.api_key and sgdb_client.api_key.strip())
        except Exception:
            has_key = False
        if has_key:
            self._api_key_lbl.setText("⬤  API Key: Connected")
            self._api_key_lbl.setStyleSheet(
                "color:#3a7a3a; font-family:'Courier New'; font-size:11px;"
                " padding:2px 8px; margin-right:8px;"
            )
        else:
            self._api_key_lbl.setText("⬤  API Key: Not Set")
            self._api_key_lbl.setStyleSheet(
                "color:#664444; font-family:'Courier New'; font-size:11px;"
                " padding:2px 8px; margin-right:8px;"
            )
        if hasattr(self, 'preview_canvas'):
            self.preview_canvas.reset_pan()

    def _rotate_canvas(self, delta: float):
        """Rotate the canvas view by delta degrees."""
        if not hasattr(self, 'preview_canvas'): return
        current = getattr(self.preview_canvas, '_view_angle', 0.0)
        new_angle = (current + delta) % 360
        self.preview_canvas.set_view_angle(new_angle)
        # Format: show negative as −, keep it in (−180, 180] range for readability
        display = new_angle if new_angle <= 180 else new_angle - 360
        self._rot_label.setText(f"• {display:.2f}°")
        # Highlight label when not at 0
        if abs(new_angle) > 0.01:
            self._rot_label.setStyleSheet(
                "color:#88aacc; font-size:11px; font-family:'Courier New';"
                " min-width:56px; padding:0 2px;")
        else:
            self._rot_label.setStyleSheet(
                "color:#666; font-size:11px; font-family:'Courier New';"
                " min-width:56px; padding:0 2px;")

    def _rotate_canvas_reset(self):
        """Reset canvas view rotation to 0°."""
        if not hasattr(self, 'preview_canvas'): return
        self.preview_canvas.set_view_angle(0.0)
        self._rot_label.setText("• 0.00°")
        self._rot_label.setStyleSheet(
            "color:#666; font-size:11px; font-family:'Courier New';"
            " min-width:56px; padding:0 2px;")

    def showMessage(self, msg: str):
        """Compatibility shim — update the status label."""
        self._status_label.setText(msg)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_artwork_selected(self, pil_image, game_name: str):
        self.tab_manager.current_tab()._on_artwork_selected(pil_image, game_name)
        self.tab_manager.rename_current(game_name)

    def _on_artwork_layer_ready(self, local_path: str, game_name: str):
        self.tab_manager.current_tab()._on_artwork_layer_ready(local_path, game_name)
        self.tab_manager.rename_current(game_name)

    def _on_settings_changed(self):
        self.tab_manager.current_tab().schedule_compose()

    def _on_template_changed(self, template: str):
        self.tab_manager.current_tab().state.current_template = template
        self.tab_manager.current_tab().schedule_compose()

    def schedule_compose(self):
        self.tab_manager.current_tab().schedule_compose()

    def _do_compose(self):
        self.tab_manager.current_tab().schedule_compose()

    def _open_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if path:
            from PIL import Image
            tab = self.tab_manager.current_tab()
            img = Image.open(path).convert("RGB")
            tab.state.base_image = img
            tab.state.selected_game_name = ""
            tab.schedule_compose()
            self._status_label.setText(f"Opened: {path}")

    def _export(self):
        """Export: AppID confirm (once per game) → save with Steam filename → show path."""
        tab  = self.tab_manager.current_tab()
        path = tab.export(parent_widget=self)
        if path:
            self._status_label.setText(f"Exported: {path}")
            QMessageBox.information(
                self, "Export Complete",
                f"Artwork saved to:\n{path}\n\n"
                "Use  Sync to Steam  in the menu bar to install it into Steam."
            )

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
        """Open the Sync to Steam dialog for the active tab."""
        from app.ui.steamSyncDialog import SteamSyncDialog
        from app.config import EXPORT_COVER, EXPORT_WIDE, EXPORT_HERO, EXPORT_LOGO, EXPORT_ICON
        import glob, os

        tab       = self.tab_manager.current_tab()
        game_name = tab.state.selected_game_name or ""
        tpl       = tab.state.current_template

        # Find the most recently exported file for each template type
        def _latest(folder, pattern):
            files = glob.glob(os.path.join(folder, pattern))
            return max(files, key=os.path.getmtime) if files else ""

        exports = {
            "cover":     _latest(EXPORT_COVER, "*.png"),
            "vhs_cover": _latest(EXPORT_COVER, "*vhs*.png"),
            "wide":      _latest(EXPORT_WIDE,  "*.png"),
            "hero":      _latest(EXPORT_HERO,  "*.png"),
            "logo":      _latest(EXPORT_LOGO,  "*.png"),
            "icon":      _latest(EXPORT_ICON,  "*.png"),
        }
        # Keep only templates that have a file
        exports = {k: v for k, v in exports.items() if v}

        dlg = SteamSyncDialog(game_name=game_name, exports=exports, parent=self)
        dlg.exec()

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
        self._status_label.setText(f"Added layer: {os.path.basename(path)}")

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
        from app.config import TEXTURES_DIR
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
        self._status_label.setText(f"Imported {copied} texture(s) to {TEXTURES_DIR}")

    def _open_textures_folder(self):
        """File → Import Textures → Open Textures Folder."""
        import subprocess, sys
        from app.config import TEXTURES_DIR
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
        """Edit → Preferences — paths, cache management, performance options."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QLineEdit, QPushButton, QCheckBox, QFrame, QSpacerItem, QSizePolicy
        )
        from app.config import EXPORT_FOLDER, CACHE_FOLDER, DATA_DIR
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

        dlg = QDialog(self)
        dlg.setWindowTitle("Preferences")
        dlg.setMinimumWidth(520)
        dlg.setStyleSheet("""
            QDialog { background:#111118; color:#ccc; font-family:'Courier New'; font-size:13px; }
            QLabel  { color:#aaa; }
            QLabel#section { color:#3a6e3a; font-size:11px; letter-spacing:2px; padding-top:10px; }
            QLineEdit { background:#1a1a22; border:1px solid #2a2a3a; color:#aaa;
                        padding:5px 8px; border-radius:2px; }
            QPushButton { background:#1a1a28; border:1px solid #333; color:#aaa;
                          padding:6px 14px; border-radius:2px; font-size:12px; }
            QPushButton:hover { background:#222238; color:#ddd; border-color:#5566aa; }
            QPushButton#danger { border-color:#6e3a3a; color:#cc8888; }
            QPushButton#danger:hover { background:#2e1a1a; color:#ffaaaa; }
            QCheckBox { color:#aaa; }
            QCheckBox::indicator { width:14px; height:14px;
                                   border:1px solid #444; background:#1a1a22; }
            QCheckBox::indicator:checked { background:#3a6e3a; border-color:#55aa55; }
            QFrame#line { background:#222232; max-height:1px; }
        """)

        root = QVBoxLayout(dlg)
        root.setSpacing(6)
        root.setContentsMargins(24, 18, 24, 18)

        def _section(text):
            lbl = QLabel(text); lbl.setObjectName("section"); return lbl

        def _hline():
            f = QFrame(); f.setObjectName("line"); f.setFrameShape(QFrame.HLine); return f

        def _folder_row(label_text, path_value, on_browse):
            lbl = QLabel(label_text)
            row = QHBoxLayout()
            edit = QLineEdit(path_value)
            edit.setReadOnly(True)
            btn  = QPushButton("Browse…")
            btn.setFixedWidth(90)
            btn.clicked.connect(lambda: on_browse(edit))
            row.addWidget(edit, 1)
            row.addWidget(btn)
            return lbl, row

        # ── PATHS ─────────────────────────────────────────────────────────
        root.addWidget(_section("PATHS"))

        def _browse_export(edit_w):
            p = QFileDialog.getExistingDirectory(dlg, "Select Export Folder", EXPORT_FOLDER)
            if p:
                prefs["export_folder"] = p
                edit_w.setText(p)
                _save_prefs()
                self._status_label.setText(f"Export folder set: {p}")

        lbl_e, row_e = _folder_row(
            "Export Folder",
            prefs.get("export_folder", EXPORT_FOLDER),
            _browse_export,
        )
        root.addWidget(lbl_e); root.addLayout(row_e)

        root.addWidget(_hline())

        # ── CACHE ─────────────────────────────────────────────────────────
        root.addWidget(_section("CACHE"))

        cache_size_lbl = QLabel("Calculating…")
        cache_size_lbl.setStyleSheet("color:#555; font-size:11px;")

        def _update_cache_size():
            try:
                total = sum(
                    os.path.getsize(os.path.join(dp, f))
                    for dp, _, files in os.walk(CACHE_FOLDER)
                    for f in files
                )
                mb = total / (1024 * 1024)
                cache_size_lbl.setText(f"Cache size: {mb:.1f} MB  ({CACHE_FOLDER})")
            except Exception:
                cache_size_lbl.setText(f"Cache: {CACHE_FOLDER}")

        _update_cache_size()
        root.addWidget(cache_size_lbl)

        cache_row = QHBoxLayout()
        clear_cache_btn = QPushButton("Clear Cache")
        clear_cache_btn.setObjectName("danger")
        clear_cache_btn.setFixedWidth(120)

        def _clear_cache():
            try:
                shutil.rmtree(CACHE_FOLDER, ignore_errors=True)
                os.makedirs(CACHE_FOLDER, exist_ok=True)
                _update_cache_size()
                self._status_label.setText("Cache cleared.")
            except Exception as e:
                QMessageBox.warning(dlg, "Error", str(e))

        clear_cache_btn.clicked.connect(_clear_cache)
        cache_row.addWidget(clear_cache_btn)
        cache_row.addStretch()
        root.addLayout(cache_row)

        root.addWidget(_hline())

        # ── PERFORMANCE ────────────────────────────────────────────────────
        root.addWidget(_section("PERFORMANCE"))

        hw_cb = QCheckBox("Enable hardware acceleration (requires restart)")
        hw_cb.setChecked(prefs.get("hw_accel", True))
        hw_cb.stateChanged.connect(lambda v: prefs.update({"hw_accel": bool(v)}) or _save_prefs())
        root.addWidget(hw_cb)

        compose_cb = QCheckBox("High-quality compose (slower, better output)")
        compose_cb.setChecked(prefs.get("hq_compose", False))
        compose_cb.stateChanged.connect(lambda v: prefs.update({"hq_compose": bool(v)}) or _save_prefs())
        root.addWidget(compose_cb)

        root.addWidget(_hline())

        # ── BUTTONS ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        dlg.exec()

    # ── Brushes handlers ───────────────────────────────────────────────────────

    def _create_brush_from_image(self):
        """Brushes → Create Brush From Image — converts a PNG/JPEG to a brush file."""
        import shutil
        from app.config import ASSETS_DIR
        brushes_dir = os.path.join(ASSETS_DIR, "brushes")
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image to Convert to Brush", "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if not path:
            return
        os.makedirs(brushes_dir, exist_ok=True)
        name = os.path.splitext(os.path.basename(path))[0] + ".png"
        dst  = os.path.join(brushes_dir, name)
        # Convert to grayscale PNG for use as brush stamp
        try:
            from PIL import Image as PILImage, ImageOps
            img = PILImage.open(path).convert("L")  # grayscale
            img = ImageOps.invert(img)               # dark areas = brush density
            img.save(dst, "PNG")
            if hasattr(self, 'brush_panel'):
                self.brush_panel._load_brushes()
            self._status_label.setText(f"Brush created: {name}")
            QMessageBox.information(self, "Brush Created",
                                    f"Brush saved as:\n{dst}\n\nIt is now available in the Brush Panel.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not create brush:\n{e}")

    # ── Fonts handlers ─────────────────────────────────────────────────────────

    def _reload_font_library(self):
        """Fonts → Reload Font Library — re-scans fonts folder and refreshes combo."""
        from app.config import FONTS_DIR
        from app.ui.fontImporter import register_all_fonts
        n = register_all_fonts(FONTS_DIR)
        self._refresh_font_combo()
        self._status_label.setText(f"Font library reloaded — {n} families registered.")

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
            self._status_label.setText(f"Steam folder set to: {path}")
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
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        from PySide6.QtCore import Qt
        import webbrowser

        dlg = QDialog(self)
        dlg.setWindowTitle("Getting Your SteamGridDB API Key")
        dlg.setMinimumWidth(460)
        dlg.setStyleSheet("background:#111118; color:#ccc; font-family:'Courier New'; font-size:13px;")
        root = QVBoxLayout(dlg)
        root.setSpacing(10)
        root.setContentsMargins(24, 20, 24, 20)

        title = QLabel("HOW TO GET YOUR STEAMGRIDDB API KEY")
        title.setStyleSheet("color:#88cc88; font-size:14px; font-weight:bold; letter-spacing:1px;")
        root.addWidget(title)

        steps = QLabel(
            "1.  Go to:\n"
            "    https://www.steamgriddb.com/profile/preferences/api\n\n"
            "2.  Log in or create a free account.\n\n"
            "3.  Click  Generate API Key.\n\n"
            "4.  Copy the key.\n\n"
            "5.  In Steam Grunge Editor, click  Set API Key\n"
            "    in the search panel (top left) and paste it."
        )
        steps.setStyleSheet("color:#aaa; font-size:13px; line-height:160%;")
        steps.setWordWrap(True)
        root.addWidget(steps)

        note = QLabel("Your key is stored locally and never shared.")
        note.setStyleSheet("color:#555; font-size:11px;")
        root.addWidget(note)

        btn_row = QVBoxLayout()
        open_btn = QPushButton("Open SteamGridDB API Page")
        open_btn.setStyleSheet("background:#1a2e1a; border:1px solid #3a6e3a; color:#88cc88; padding:8px 16px;")
        open_btn.clicked.connect(lambda: webbrowser.open(
            "https://www.steamgriddb.com/profile/preferences/api"))
        btn_row.addWidget(open_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)
        dlg.exec()

    def _show_quickstart(self):
        """Help → Quick Start Tutorial."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QScrollArea, QWidget
        dlg = QDialog(self)
        dlg.setWindowTitle("Quick Start Tutorial")
        dlg.setMinimumSize(500, 480)
        dlg.setStyleSheet("background:#111118; color:#ccc; font-family:'Courier New'; font-size:13px;")
        root = QVBoxLayout(dlg)
        root.setContentsMargins(0, 0, 0, 12)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none; background:#111118;")
        inner = QWidget(); inner.setStyleSheet("background:#111118;")
        il = QVBoxLayout(inner); il.setContentsMargins(24, 20, 24, 10); il.setSpacing(10)

        title = QLabel("✦  QUICK START GUIDE")
        title.setStyleSheet("color:#88cc88; font-size:15px; font-weight:bold; letter-spacing:2px;")
        il.addWidget(title)

        steps_text = (
            "<b style='color:#ddd'>Step 1 — Set your API Key</b><br>"
            "Click  <i>Set API Key</i>  in the top-left search panel.<br>"
            "Paste your SteamGridDB key (Help → Getting SteamGridDB API Key).<br><br>"
            "<b style='color:#ddd'>Step 2 — Search for a game</b><br>"
            "Type a game name and press  Search.<br>"
            "Select the game from the results list.<br><br>"
            "<b style='color:#ddd'>Step 3 — Pick artwork</b><br>"
            "Click any artwork thumbnail to add it as a canvas layer.<br>"
            "Use the Type filter (Grids / Heroes / Logos / Icons) to switch artwork types.<br><br>"
            "<b style='color:#ddd'>Step 4 — Choose a template</b><br>"
            "In the right panel, select the template you want to create:<br>"
            "Cover, Wide Cover, Hero, Logo, or Icon.<br><br>"
            "<b style='color:#ddd'>Step 5 — Apply effects</b><br>"
            "Use the Film Grain, Chromatic Aberration, and Color sliders<br>"
            "to add a distressed / grunge look.<br><br>"
            "<b style='color:#ddd'>Step 6 — Export</b><br>"
            "File → Export (Ctrl+E) to save a single asset,  or<br>"
            "File → Export All Assets (Ctrl+Shift+E) for all formats at once.<br><br>"
            "<b style='color:#ddd'>Step 7 — Sync to Steam</b><br>"
            "Use the  Sync to Steam  menu to copy files into your<br>"
            "Steam custom artwork folder.  Restart Steam to see them."
        )
        lbl = QLabel(steps_text)
        lbl.setTextFormat(Qt.RichText)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#aaa; font-size:13px; line-height:170%;")
        il.addWidget(lbl)
        il.addStretch()

        scroll.setWidget(inner)
        root.addWidget(scroll)
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(dlg.accept)
        root.addWidget(close_btn, 0, Qt.AlignCenter)
        dlg.exec()

    def _show_shortcuts(self):
        """Help → Keyboard Shortcuts."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        dlg = QDialog(self)
        dlg.setWindowTitle("Keyboard Shortcuts")
        dlg.setMinimumWidth(420)
        dlg.setStyleSheet("background:#111118; color:#ccc; font-family:'Courier New'; font-size:13px;")
        root = QVBoxLayout(dlg)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(4)

        title = QLabel("KEYBOARD SHORTCUTS")
        title.setStyleSheet("color:#88cc88; font-size:14px; font-weight:bold; letter-spacing:2px;")
        root.addWidget(title)
        root.addSpacing(8)

        shortcuts = [
            ("FILE", None),
            ("Ctrl+O",           "Open image"),
            ("Ctrl+Shift+O",     "Import image as layer"),
            ("Ctrl+E",           "Export artwork"),
            ("Ctrl+Shift+E",     "Export all assets"),
            ("Ctrl+Q",           "Quit"),
            ("EDIT", None),
            ("Ctrl+Z",           "Undo"),
            ("Ctrl+Y",           "Redo"),
            ("Ctrl+D",           "Duplicate layer"),
            ("Delete",           "Delete layer"),
            ("Ctrl+Shift+C",     "Crop layer"),
            ("BRUSHES", None),
            ("B",                "Toggle brush panel"),
            ("E",                "Eraser tool"),
            ("Ctrl+Shift+B",     "Import brush ZIP"),
            ("SYNC", None),
            ("Ctrl+Shift+S",     "Sync to Steam"),
            ("TABS", None),
            ("Ctrl+T",           "New tab"),
            ("Ctrl+W",           "Close tab"),
        ]

        for key, desc in shortcuts:
            if desc is None:
                lbl = QLabel(key)
                lbl.setStyleSheet("color:#3a6e3a; font-size:11px; letter-spacing:2px; padding-top:8px;")
                root.addWidget(lbl)
            else:
                row_w = QLabel(f"  <span style='color:#88aacc; min-width:160px'>{key}</span>"
                               f"  <span style='color:#888'>{desc}</span>")
                row_w.setTextFormat(Qt.RichText)
                root.addWidget(row_w)

        root.addSpacing(10)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        root.addWidget(close_btn)
        dlg.exec()

    def _report_issue(self):
        """Help → Report Issue — opens GitHub issues page."""
        import webbrowser
        webbrowser.open("https://github.com/your-repo/steam-grunge-editor/issues")

    def _show_about(self):
        QMessageBox.about(
            self, "Steam Grunge Editor",
            "Steam Grunge Editor\n\nCreate distressed Steam artwork.\n\n"
            "Supports SteamGridDB API for artwork search."
        )