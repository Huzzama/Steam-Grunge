"""
Bulk Sync to Steam dialog.

Shows:
  - How many assets were found
  - How many need syncing (new / changed)
  - How many will be skipped (unchanged)
  - How many have no AppID
  - Per-asset rows with status badges
  - A progress bar during sync

Actions:
  [Sync New & Changed]   — default run, skips unchanged
  [Force Sync All]       — re-sync everything including unchanged
  [Cancel]
"""
from __future__ import annotations

import os
from typing import Optional, List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QProgressBar, QSizePolicy,
    QAbstractScrollArea,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui  import QColor, QFont

from app.services.bulkSync      import BulkSyncJob, BulkSyncPlanner, BulkSyncExecutor
from app.services.steamSync     import find_steam_userdata, list_steam_ids

# ── Style ──────────────────────────────────────────────────────────────────────

STYLE = """
QDialog {
    background: #111118;
    color: #ccc;
    font-family: 'Courier New', monospace;
    font-size: 13px;
}
QLabel           { color: #aaa; font-size: 13px; }
QLabel#title     { color: #88cc88; font-size: 15px; font-weight: bold;
                   letter-spacing: 2px; }
QLabel#section   { color: #555; font-size: 11px; letter-spacing: 2px;
                   padding-top: 4px; }
QLabel#stat_ok   { color: #88cc88; font-size: 13px; }
QLabel#stat_warn { color: #ccaa44; font-size: 13px; }
QLabel#stat_err  { color: #cc6666; font-size: 13px; }
QScrollArea      { border: none; background: transparent; }
QFrame#card      { background: #16161e; border: 1px solid #222230;
                   border-radius: 3px; }
QPushButton {
    background: #1e1e2e; border: 1px solid #3a3a5a; color: #aaa;
    font-family: 'Courier New'; font-size: 13px;
    padding: 6px 16px; border-radius: 2px; min-height: 28px;
}
QPushButton:hover   { background: #2a2a4a; color: #ddd; border-color: #5566aa; }
QPushButton:pressed { background: #111; }
QPushButton#primary {
    background: #1a2e1a; border: 1px solid #3a6e3a;
    color: #88cc88; font-weight: bold; font-size: 14px;
}
QPushButton#primary:hover { background: #223a22; border-color: #55aa55; }
QPushButton#primary:disabled { background: #1a1a1a; color: #444;
                                border-color: #2a2a2a; }
QProgressBar {
    background: #1a1a1a; border: 1px solid #333; border-radius: 2px;
    height: 6px;
}
QProgressBar::chunk { background: #3a6e3a; border-radius: 2px; }
"""

_STATUS_COLOR = {
    "new":        "#88cc88",
    "changed":    "#ccaa44",
    "unchanged":  "#555566",
    "missing_id": "#cc6666",
    "ok":         "#88cc88",
    "error":      "#cc6666",
}
_STATUS_LABEL = {
    "new":        "NEW",
    "changed":    "CHANGED",
    "unchanged":  "SKIP",
    "missing_id": "NO ID",
    "ok":         "✔ OK",
    "error":      "✖ ERR",
}
_TEMPLATE_LABELS = {
    "cover": "Cover (600×900)",
    "wide":  "Wide (920×430)",
    "hero":  "Hero (3840×1240)",
    "logo":  "Logo (1280×720)",
    "icon":  "Icon (512×512)",
}


def _hline():
    f = QFrame(); f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color:#2a2a2a; background:#2a2a2a; max-height:1px;")
    return f


# ── Background executor thread ────────────────────────────────────────────────

class _ExecutorWorker(QObject):
    job_done  = Signal(object)   # BulkSyncJob after each completion
    finished  = Signal()

    def __init__(self, jobs, steam_id, userdata_path, force):
        super().__init__()
        self._jobs          = jobs
        self._steam_id      = steam_id
        self._userdata_path = userdata_path
        self._force         = force
        self._executor      = BulkSyncExecutor()

    def run(self):
        self._executor.run(
            self._jobs,
            self._steam_id,
            self._userdata_path,
            on_progress=lambda j: self.job_done.emit(j),
            force=self._force,
        )
        self.finished.emit()


# ── Per-job row widget ────────────────────────────────────────────────────────

class _JobRow(QWidget):
    def __init__(self, job: BulkSyncJob, parent=None):
        super().__init__(parent)
        self._job = job
        self._status_lbl: Optional[QLabel] = None
        self._build()

    def _build(self):
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(10)

        # Status badge
        self._status_lbl = QLabel(_STATUS_LABEL.get(self._job.status, self._job.status))
        self._status_lbl.setFixedWidth(64)
        self._status_lbl.setAlignment(Qt.AlignCenter)
        self._status_lbl.setFont(QFont("Courier New", 10, QFont.Bold))
        self._update_status_color()
        row.addWidget(self._status_lbl)

        # Template
        tpl_lbl = QLabel(_TEMPLATE_LABELS.get(self._job.template, self._job.template))
        tpl_lbl.setFixedWidth(170)
        row.addWidget(tpl_lbl)

        # Filename
        fname = os.path.basename(self._job.file_path)
        fname_lbl = QLabel(fname)
        fname_lbl.setStyleSheet("color:#556; font-size:12px;")
        fname_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row.addWidget(fname_lbl, 1)

        # AppID
        appid_str = str(self._job.app_id) if self._job.app_id else "—"
        appid_lbl = QLabel(appid_str)
        appid_lbl.setFixedWidth(80)
        appid_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        appid_lbl.setStyleSheet("color:#445; font-size:11px;")
        row.addWidget(appid_lbl)

    def update_job(self, job: BulkSyncJob):
        """Called by dialog after executor updates the job."""
        self._job = job
        self._status_lbl.setText(_STATUS_LABEL.get(job.status, job.status))
        self._update_status_color()
        if job.error:
            self.setToolTip(job.error)

    def _update_status_color(self):
        color = _STATUS_COLOR.get(self._job.status, "#888")
        self._status_lbl.setStyleSheet(f"color:{color}; font-size:10px;")


# ── Main dialog ───────────────────────────────────────────────────────────────

class BulkSyncDialog(QDialog):
    """
    Bulk sync dialog.  Pass *jobs* from BulkSyncPlanner.plan() — the dialog
    shows the plan then executes it on user confirmation.
    """

    def __init__(self, jobs: List[BulkSyncJob], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bulk Sync to Steam")
        self.setMinimumWidth(680)
        self.setStyleSheet(STYLE)

        self._all_jobs: List[BulkSyncJob] = jobs
        self._rows:     List[_JobRow]     = []
        self._thread:   Optional[QThread] = None

        self._userdata  = find_steam_userdata()
        self._steam_ids = list_steam_ids(self._userdata) if self._userdata else []

        self._build()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 16, 20, 16)

        title = QLabel("⇪  BULK SYNC TO STEAM")
        title.setObjectName("title")
        root.addWidget(title)
        root.addWidget(_hline())

        # ── Summary stats ─────────────────────────────────────────────────
        n_new       = sum(1 for j in self._all_jobs if j.status == "new")
        n_changed   = sum(1 for j in self._all_jobs if j.status == "changed")
        n_unchanged = sum(1 for j in self._all_jobs if j.status == "unchanged")
        n_noid      = sum(1 for j in self._all_jobs if j.status == "missing_id")

        stats_row = QHBoxLayout()
        def _stat(label, value, obj_name):
            col = QVBoxLayout()
            v = QLabel(str(value)); v.setObjectName(obj_name)
            v.setFont(QFont("Courier New", 22, QFont.Bold))
            v.setAlignment(Qt.AlignCenter)
            l = QLabel(label); l.setAlignment(Qt.AlignCenter)
            col.addWidget(v); col.addWidget(l)
            return col
        stats_row.addLayout(_stat("NEW",       n_new,       "stat_ok"))
        stats_row.addLayout(_stat("CHANGED",   n_changed,   "stat_warn"))
        stats_row.addLayout(_stat("UNCHANGED", n_unchanged, "section"))
        stats_row.addLayout(_stat("NO APPID",  n_noid,      "stat_err"))
        root.addLayout(stats_row)
        root.addWidget(_hline())

        # ── Steam account ─────────────────────────────────────────────────
        if self._userdata and self._steam_ids:
            acc_row = QHBoxLayout()
            acc_row.addWidget(QLabel("Steam account:"))
            from PySide6.QtWidgets import QComboBox
            self._id_combo = QComboBox()
            for sid in self._steam_ids:
                self._id_combo.addItem(sid)
            acc_row.addWidget(self._id_combo, 1)
            root.addLayout(acc_row)
        else:
            self._id_combo = None
            warn = QLabel("⚠  Steam installation not found.")
            warn.setObjectName("stat_err")
            root.addWidget(warn)

        # ── Job list ──────────────────────────────────────────────────────
        sec = QLabel("ASSETS TO SYNC")
        sec.setObjectName("section")
        root.addWidget(sec)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        scroll.setMaximumHeight(320)

        inner = QWidget()
        self._list_layout = QVBoxLayout(inner)
        self._list_layout.setSpacing(2)
        self._list_layout.setContentsMargins(0, 0, 0, 0)

        for job in self._all_jobs:
            row = _JobRow(job)
            self._rows.append(row)
            self._list_layout.addWidget(row)

        if not self._all_jobs:
            self._list_layout.addWidget(QLabel("No exported assets found."))

        scroll.setWidget(inner)
        root.addWidget(scroll)

        # ── Progress bar ──────────────────────────────────────────────────
        self._progress = QProgressBar()
        n_active = n_new + n_changed
        self._progress.setRange(0, max(n_active, 1))
        self._progress.setValue(0)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        # ── Status label ──────────────────────────────────────────────────
        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self._status_lbl)

        root.addWidget(_hline())

        # ── Buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_row.addStretch()

        self._force_btn = QPushButton("Force Sync All")
        self._force_btn.clicked.connect(lambda: self._start(force=True))
        btn_row.addWidget(self._force_btn)

        self._sync_btn = QPushButton("⇪  Sync New & Changed")
        self._sync_btn.setObjectName("primary")
        self._sync_btn.setEnabled(n_new + n_changed > 0)
        self._sync_btn.clicked.connect(lambda: self._start(force=False))
        btn_row.addWidget(self._sync_btn)

        root.addLayout(btn_row)

    # ── Execution ─────────────────────────────────────────────────────────────

    def _start(self, force: bool = False):
        if self._thread and self._thread.isRunning():
            return

        steam_id = self._id_combo.currentText() if self._id_combo else None
        if not steam_id:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Account",
                                "No Steam account found.")
            return

        jobs_to_run = self._all_jobs if force else [
            j for j in self._all_jobs if j.status in ("new", "changed")
        ]
        if not jobs_to_run:
            self._status_lbl.setText("Nothing to sync.")
            return

        self._sync_btn.setEnabled(False)
        self._force_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(jobs_to_run))
        self._progress.setValue(0)
        self._status_lbl.setText("Syncing…")

        worker = _ExecutorWorker(jobs_to_run, steam_id, self._userdata, force)
        self._thread = QThread()
        worker.moveToThread(self._thread)

        self._thread.started.connect(worker.run)
        worker.job_done.connect(self._on_job_done)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(self._thread.quit)

        self._thread.start()

    def _on_job_done(self, job: BulkSyncJob):
        # Find the row widget for this job and update it
        for row in self._rows:
            if row._job is job or (
                row._job.game_name == job.game_name and
                row._job.template  == job.template
            ):
                row.update_job(job)
                break
        self._progress.setValue(self._progress.value() + 1)

    def _on_finished(self):
        ok    = sum(1 for j in self._all_jobs if j.status == "ok")
        errs  = sum(1 for j in self._all_jobs if j.status == "error")
        skips = sum(1 for j in self._all_jobs if j.status in ("unchanged", "skipped"))
        self._status_lbl.setText(
            f"Done — {ok} synced, {errs} errors, {skips} skipped."
        )
        self._sync_btn.setText("✔  Done")
        self._sync_btn.setEnabled(False)
        self._force_btn.setEnabled(False)