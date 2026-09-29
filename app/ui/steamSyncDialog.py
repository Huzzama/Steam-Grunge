from __future__ import annotations

import os
import threading
from typing import Optional, List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QFrame, QScrollArea, QWidget,
    QProgressBar, QMessageBox, QSizePolicy, QGridLayout,
)
from PySide6.QtCore import Qt, Signal, QObject, QThread

from app.services.appIdGetter import search_candidates, NetworkError
from app.services.steamSync   import (
    find_steam_userdata, list_steam_ids,
    get_grid_folder, sync_artwork, SyncResult,
)
from app.ui        import icons
from app.ui.kit    import Button, Divider, Section, label, hbox, vbox, grid, set_tone
from app.ui.theme  import C, SP


# ── Async worker ──────────────────────────────────────────────────────────────
class _AppIdWorker(QObject):
    finished = Signal(list, str)   # (candidates, error_message)

    def __init__(self, game_name: str):
        super().__init__()
        self._name = game_name

    def run(self):
        try:
            results = search_candidates(self._name, limit=8)
            self.finished.emit(results, "")
        except NetworkError as e:
            self.finished.emit([], str(e))
        except Exception as e:
            self.finished.emit([], str(e))


# ── Status line helper (icon + text, tone-coloured) ───────────────────────────
_TONE_ICON = {"green": ("circle-check", C["green"]), "red": ("circle-x", C["red"]),
              "gold": ("triangle-alert", C["gold"]), "accent": ("loader-circle", C["accent"]),
              None: ("info", C["text_dim"])}


class _StatusLine(QWidget):
    def __init__(self, text: str = "", tone=None, parent=None):
        super().__init__(parent)
        lay = hbox(self, spacing=SP["sm"])
        self._ic = QLabel()
        self._ic.setFixedSize(16, 16)
        lay.addWidget(self._ic, 0, Qt.AlignmentFlag.AlignTop)
        self._lbl = label("", "dim", wrap=True)
        lay.addWidget(self._lbl, 1)
        self.set(text, tone)

    def set(self, text: str, tone=None):
        name, color = _TONE_ICON[tone]
        self._ic.setPixmap(icons.pixmap(name, color, 16))
        self._lbl.setText(text)
        set_tone(self._lbl, tone)


def _form_row(g: QGridLayout, row: int, text: str, widget, trailing=None):
    l = label(text, "dim")
    l.setMinimumWidth(110)
    g.addWidget(l, row, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    span = 1 if trailing is not None else 2      # no trailing button → field spans both columns
    if isinstance(widget, QWidget):
        g.addWidget(widget, row, 1, 1, span)
    else:
        g.addLayout(widget, row, 1, 1, span)
    if trailing is not None:
        g.addWidget(trailing, row, 2)
    g.setColumnStretch(1, 1)


# ── Dialog ────────────────────────────────────────────────────────────────────
class SteamSyncDialog(QDialog):
    def __init__(self, game_name: str, exports: dict[str, str], parent=None):
        """
        Parameters
        ----------
        game_name : the name currently in state (used for AppID lookup)
        exports   : {template_name: absolute_path_to_png}
                    only templates with a real file will be synced
        """
        super().__init__(parent)
        self.setWindowTitle("Sync to Steam")
        self.setMinimumWidth(580)

        self._game_name  = game_name
        self._exports    = {k: v for k, v in exports.items()
                            if v and os.path.isfile(v)}
        self._candidates: List[dict] = []
        self._userdata   = find_steam_userdata()
        self._steam_ids  = list_steam_ids(self._userdata) if self._userdata else []
        self._worker_thread: Optional[QThread] = None
        self._worker = None

        self._build()
        self._start_lookup()

    # ── UI construction ───────────────────────────────────────────────────────
    def _build(self):
        root = vbox(self, (SP["xl"], SP["lg"], SP["xl"], SP["lg"]), SP["md"])

        head = hbox(spacing=SP["sm"])
        ic = QLabel()
        ic.setPixmap(icons.pixmap("upload", C["accent"], 18))
        head.addWidget(ic)
        head.addWidget(label("SYNC TO STEAM", "title"), 1)
        root.addLayout(head)
        root.addWidget(label("Installs the exported PNGs into Steam's custom grid folder for the "
                             "selected account. Steam picks them up within a few seconds.", "dim", wrap=True))

        # ── GAME / APP ID ─────────────────────────────────────────────────────
        sec1 = Section("Game identification", collapsible=False)
        g = grid(h=SP["md"], v=SP["sm"])
        self._name_edit = QLineEdit(self._game_name)
        self._name_edit.setPlaceholderText("Enter game name…")
        self._name_edit.textChanged.connect(self._on_name_changed)
        btn_search = Button("Search", icon="search", on_click=self._start_lookup)
        _form_row(g, 0, "Game name", self._name_edit, btn_search)

        appid_row = hbox(spacing=SP["sm"])
        self._appid_edit = QLineEdit()
        self._appid_edit.setPlaceholderText("Looking up…")
        self._appid_edit.setFixedWidth(120)
        appid_row.addWidget(self._appid_edit)
        self._candidate_combo = QComboBox()
        self._candidate_combo.setPlaceholderText("— choose from results —")
        self._candidate_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._candidate_combo.currentIndexChanged.connect(self._on_candidate_picked)
        appid_row.addWidget(self._candidate_combo, 1)
        _form_row(g, 1, "AppID", appid_row)
        sec1.body.addLayout(g)

        self._lookup_label = _StatusLine("Searching Steam Store…", "accent")
        sec1.body.addWidget(self._lookup_label)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)   # indeterminate
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        sec1.body.addWidget(self._progress)
        root.addWidget(sec1)

        # ── STEAM ACCOUNT ─────────────────────────────────────────────────────
        sec2 = Section("Steam account", collapsible=False)
        if self._userdata and self._steam_ids:
            g = grid(h=SP["md"], v=SP["sm"])
            self._id_combo = QComboBox()
            for sid in self._steam_ids:
                self._id_combo.addItem(sid)
            _form_row(g, 0, "SteamID", self._id_combo)
            self._folder_label = label("", "muted", elide=True)
            _form_row(g, 1, "Grid folder", self._folder_label)
            self._id_combo.currentTextChanged.connect(self._update_folder_label)
            self._update_folder_label(self._steam_ids[0])
            sec2.body.addLayout(g)
        else:
            sec2.body.addWidget(_StatusLine("Steam installation not found. Make sure Steam is installed "
                                            "and has been launched at least once.", "gold"))
            self._id_combo = None
        root.addWidget(sec2)

        # ── FILES TO INSTALL ─────────────────────────────────────────────────
        sec3 = Section("Files to install", collapsible=False)
        self._files_widget = QWidget()
        self._files_layout = grid(self._files_widget, h=SP["md"], v=SP["xs"])
        self._rebuild_files_list()
        sec3.body.addWidget(self._files_widget)
        root.addWidget(sec3)

        # Result area (hidden until sync runs)
        self._result_widget = QWidget()
        self._result_layout = vbox(self._result_widget, spacing=SP["xs"])
        self._result_widget.setVisible(False)
        root.addWidget(self._result_widget)
        # kept for compatibility with older callers that poke the label directly
        self._result_label = label("", "dim", wrap=True)
        self._result_label.setVisible(False)

        root.addWidget(Divider())

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = hbox(spacing=SP["sm"])
        btn_row.addStretch()
        btn_cancel = Button("Cancel", on_click=self.reject)
        btn_cancel.setMinimumWidth(90)
        btn_row.addWidget(btn_cancel)
        self._sync_btn = Button("Sync to Steam", "primary", icon="upload", on_click=self._do_sync)
        self._sync_btn.setMinimumWidth(180)
        btn_row.addWidget(self._sync_btn)
        root.addLayout(btn_row)

    def _rebuild_files_list(self):
        # Clear
        while self._files_layout.count():
            item = self._files_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        _LABELS = {
            "cover":     ("Cover",      "600×900"),
            "vhs_cover": ("VHS Cover",  "600×900"),
            "wide":      ("Wide Cover", "920×430"),
            "hero":      ("Hero/BG",    "3840×1240"),
            "logo":      ("Logo",       "1280×720"),
            "icon":      ("Icon",       "512×512"),
        }
        from app.config import grid_filename
        app_id = self._appid_edit.text().strip() or "???"

        if not self._exports:
            self._files_layout.addWidget(
                _StatusLine("No exported files found. Export at least one template first.", "gold"), 0, 0, 1, 4)
            return

        for r, (tpl, src) in enumerate(self._exports.items()):
            name, size = _LABELS.get(tpl, (tpl, ""))
            ic = QLabel()
            ic.setPixmap(icons.pixmap("file-image", C["text_dim"], 14))
            ic.setFixedSize(16, 16)
            self._files_layout.addWidget(ic, r, 0)
            self._files_layout.addWidget(label(name, "body"), r, 1)
            self._files_layout.addWidget(label(size, "muted"), r, 2)
            arrow = QLabel()
            arrow.setPixmap(icons.pixmap("arrow-right", C["accent"], 14))
            arrow.setFixedSize(16, 16)
            self._files_layout.addWidget(arrow, r, 3)
            self._files_layout.addWidget(label(grid_filename(app_id, tpl), "mono", elide=True), r, 4)
        self._files_layout.setColumnStretch(4, 1)

    # ── AppID lookup ──────────────────────────────────────────────────────────
    def _start_lookup(self):
        name = self._name_edit.text().strip()
        if not name:
            return
        self._lookup_label.set("Searching Steam Store…", "accent")
        self._progress.setVisible(True)
        self._sync_btn.setEnabled(False)

        # Stop a lookup that is still running before starting a new one
        if self._worker_thread and self._worker_thread.isRunning():
            self._worker_thread.quit()
            self._worker_thread.wait(200)

        worker = _AppIdWorker(name)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_lookup_done, Qt.QueuedConnection)
        worker.finished.connect(thread.quit, Qt.QueuedConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._worker, self._worker_thread = worker, thread
        thread.start()

    def closeEvent(self, event):
        # Don't let a still-running lookup call back into a destroyed dialog
        if self._worker_thread and self._worker_thread.isRunning():
            if self._worker:
                try: self._worker.finished.disconnect()
                except RuntimeError: pass
            self._worker_thread.quit()
            self._worker_thread.wait(500)
        super().closeEvent(event)

    def _on_lookup_done(self, candidates: list, error: str):
        if self.sender() is not self._worker:
            return                          # stale result from a superseded lookup
        self._progress.setVisible(False)
        self._candidates = candidates
        self._candidate_combo.blockSignals(True)
        self._candidate_combo.clear()

        if error:
            self._candidate_combo.blockSignals(False)
            short = error[:100] + ("…" if len(error) > 100 else "")
            self._lookup_label.set(f"Network error — enter AppID manually.\n({short})", "gold")
            self._sync_btn.setEnabled(True)   # allow manual AppID entry
            self._rebuild_files_list()
            return

        if candidates:
            for c in candidates:
                self._candidate_combo.addItem(
                    f"{c['name']}  [{c['id']}]", userData=c)
            self._candidate_combo.blockSignals(False)
            from app.services.appIdGetter import match_confidence, CONFIDENT_SCORE
            best, score = match_confidence(candidates, self._name_edit.text())
            if best is not None and score >= CONFIDENT_SCORE:
                self._appid_edit.setText(str(best["id"]))
                self._lookup_label.set(f"Found: {best['name']}  (AppID {best['id']})", "green")
                self._sync_btn.setEnabled(True)
            else:
                self._appid_edit.clear()
                self._lookup_label.set(f"Not sure — closest is {best['name']}. Pick the game "
                                       "from the list or type the AppID.", "gold")
                self._sync_btn.setEnabled(False)
        else:
            self._candidate_combo.blockSignals(False)
            self._lookup_label.set("No results — enter the AppID manually.", "red")
            self._sync_btn.setEnabled(True)

        self._rebuild_files_list()

    def _on_candidate_picked(self, idx: int):
        data = self._candidate_combo.itemData(idx)
        if data and isinstance(data, dict):
            self._appid_edit.setText(str(data["id"]))
            # Update label to reflect the actually selected result (fixes stale label bug)
            self._lookup_label.set(f"Selected: {data['name']}  (AppID {data['id']})", "green")
            self._rebuild_files_list()

    def _on_name_changed(self, _text: str):
        self._appid_edit.clear()
        self._candidate_combo.clear()

    def _update_folder_label(self, steam_id: str):
        if self._userdata:
            path = get_grid_folder(self._userdata, steam_id)
            self._folder_label.setText(str(path))
            self._folder_label.setToolTip(str(path))

    # ── Sync ─────────────────────────────────────────────────────────────────

    def _do_sync(self):
        # Validate AppID
        appid_txt = self._appid_edit.text().strip()
        if not appid_txt.isdigit():
            QMessageBox.warning(self, "Missing AppID",
                                "Please enter a valid numeric Steam AppID.")
            return

        app_id = int(appid_txt)

        if not self._userdata:
            QMessageBox.critical(self, "Steam Not Found",
                                 "Could not locate your Steam installation.")
            return

        steam_id = self._id_combo.currentText() if self._id_combo else None
        if not steam_id:
            QMessageBox.warning(self, "No Account",
                                "No Steam account folder found.")
            return

        # Run the sync (PNG re-encode of up to 5 files + Steam reload signal)
        # off the GUI thread; the dialog stays responsive and can't be re-clicked.
        self._sync_btn.set_loading(True, "Syncing…")
        exports = dict(self._exports)
        userdata = self._userdata

        from PySide6.QtCore import QObject, Signal
        class _Bridge(QObject):
            done = Signal(object)
        bridge = _Bridge(self)
        bridge.done.connect(self._on_sync_done)

        import threading
        def _work():
            try:
                res = sync_artwork(app_id=app_id, steam_id=steam_id,
                                   userdata_path=userdata, exports=exports,
                                   overwrite=True)
            except Exception as e:
                res = e
            bridge.done.emit(res)
        threading.Thread(target=_work, daemon=True).start()

    def _on_sync_done(self, result):
        if isinstance(result, Exception):
            self._sync_btn.set_loading(False)
            QMessageBox.critical(self, "Sync Failed", str(result))
            return

        # Show result rows: circle-check / circle-x pixmaps instead of glyph text
        while self._result_layout.count():
            item = self._result_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rows = [("circle-check", C["green"], os.path.basename(p), None) for p in result.installed]
        rows += [("minus", C["text_dim"], f"{tpl}  (skipped)", None) for tpl in result.skipped]
        rows += [("circle-x", C["red"], err, "red") for err in result.errors]
        for icon_name, color, text, tone in rows:
            row = hbox(spacing=SP["sm"])
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icon_name, color, 14))
            ic.setFixedSize(16, 16)
            row.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label(text, "body", tone=tone, wrap=True), 1)
            w = QWidget(); w.setLayout(row)
            self._result_layout.addWidget(w)
        self._result_label.setText("\n".join(r[2] for r in rows))
        self._result_widget.setVisible(True)

        if result.success:
            self._sync_btn.set_loading(False)
            self._sync_btn.setText("Synced")
            self._sync_btn.set_icon("check")
            self._sync_btn.setEnabled(False)
            # Show reminder to restart Steam
            QMessageBox.information(
                self, "Sync Complete",
                f"Installed {len(result.installed)} file(s) to:\n{result.grid_folder}\n\n"
                "Your artwork should appear in Steam within a few seconds.\n"
                "If it doesn't, try scrolling the library or switching views."
            )
        else:
            self._sync_btn.set_loading(False)
            QMessageBox.warning(
                self, "Sync Failed",
                "Nothing was installed:\n" + ("\n".join(result.errors) or "unknown error"))