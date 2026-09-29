"""
Search panel — SteamGridDB search, game list, artwork grid.

Layout (no scrolling, panel is 300–400 px wide):
    header   STEAM GRUNGE ······ [key status] [key]
    search   [ field ················ ] [Search]
    FILTERS  (collapsed)  2×2 grid: Type · Style · Size · NSFW
    GAMES    list (bounded) / EmptyState  + status line
    ARTWORK  (stretch) thumbnail grid, pager in the header

Everything visual comes from theme.py through kit widgets and dynamic
properties; the thumbnail cards paint themselves with theme colours.
"""
from __future__ import annotations
import os
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QListWidget, QListWidgetItem, QScrollArea,
    QFrame, QComboBox, QSizePolicy, QInputDialog, QAbstractItemView,
)
from PySide6.QtCore import Qt, Signal, QObject, QUrl, QEvent, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from PIL import Image as PILImage  # still used for _on_card_clicked full-res load

from app.services.steamgrid import client as sgdb_client
from app.services.cache     import get_cache_path, prune_cache

from app.ui import icons
from app.ui.kit import (vbox, hbox, grid, label, Button, IconButton, Section, EmptyState)
from app.ui.theme import C, R, SP, repolish
from app.ui.theme import font as theme_font   # debug placeholder pixmaps only


# ── Background work → main-thread callback ─────────────────────────────────────
class _AsyncBridge(QObject):
    """Run fn() in a daemon thread; call on_done(result) on the GUI thread."""
    _done = Signal(object)

    def __init__(self, parent, fn, on_done):
        super().__init__(parent)
        self._fn, self._on_done = fn, on_done
        self._done.connect(self._finish)

    def start(self):
        import threading
        def _run():
            try:
                res = self._fn()
            except Exception as e:
                res = e
            self._done.emit(res)
        threading.Thread(target=_run, daemon=True).start()
        return self

    def _finish(self, res):
        try:
            self._on_done(res)
        finally:
            self.deleteLater()


# ── Single thumbnail card ──────────────────────────────────────────────────────
class ArtworkCard(QFrame):
    """
    Self-painted thumbnail: 1 px border (hover → border_strong, busy → accent),
    pixmap centred and scaled to fit, placeholder / error icon otherwise.
    Size is set by the panel from the viewport width (see _relayout_cards).
    """
    clicked = Signal(str)   # full-res URL

    ASPECT = 1.45           # h / w  (600×900 grids ≈ 1.5, keeps heroes readable)

    def __init__(self, full_url: str, parent=None):
        super().__init__(parent)
        self.full_url = full_url
        self._pix: Optional[QPixmap] = None
        self._error = False
        self._busy = False
        self._hover = False
        self.setProperty("surface", "card")
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.set_card_width(120)

    # ── geometry ──
    def set_card_width(self, w: int):
        self.setFixedSize(w, int(w * self.ASPECT))

    # ── content ──
    def set_pixmap_from_bytes(self, data: bytes):
        """Called in main thread — totally safe."""
        try:
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                self._pix = pix
                self._error = False
                self.setToolTip("")
                self.update()
            else:
                self.set_error()
        except Exception:
            self.set_error()

    def set_error(self):
        self._error = True
        self._pix = None
        self.setToolTip("Image could not be loaded")
        self.update()

    def set_busy(self, busy: bool):
        """Dim the card while its full-res image is downloading."""
        self._busy = busy
        self.setEnabled(not busy)
        self.setProperty("active", "true" if busy else "false")
        repolish(self)

    # ── events ──
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.full_url)
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
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        if self._busy:
            border = C["accent"]
        elif self._hover:
            border = C["border_strong"]
        elif self._error:
            border = C["red_dim"]
        else:
            border = C["border"]
        p.setPen(QPen(QColor(border), 1))
        p.setBrush(QColor(C["surface"]))
        p.drawRoundedRect(r, R["md"], R["md"])

        inner = r.adjusted(2, 2, -1, -1)
        if self._pix is not None:
            scaled = self._pix.scaled(inner.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = inner.x() + (inner.width() - scaled.width()) // 2
            y = inner.y() + (inner.height() - scaled.height()) // 2
            if self._busy:
                p.setOpacity(0.45)
            p.drawPixmap(x, y, scaled)
        else:
            name, color = ("circle-x", C["red"]) if self._error else ("image", C["text_muted"])
            pm = icons.pixmap(name, color, 20)
            w, h = int(pm.width() / pm.devicePixelRatio()), int(pm.height() / pm.devicePixelRatio())
            p.drawPixmap(inner.x() + (inner.width() - w) // 2, inner.y() + (inner.height() - h) // 2, pm)
        p.end()


class _StatusDot(QWidget):
    """8 px filled circle in a theme colour (API-key indicator)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = C["red"]
        self.setFixedSize(8, 8)

    def set_color(self, hexv: str):
        self._color = hexv
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._color))
        p.drawEllipse(self.rect())
        p.end()


class _WheelGuard(QObject):
    """Absorbs wheel events so scrolling over a combo never changes it."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            event.ignore()
            return True
        return False


# ── Main panel ─────────────────────────────────────────────────────────────────
class SearchPanel(QWidget):
    """
    Emits artwork_layer_ready(local_path, game_name) so the tab can call
    canvas.add_image_layer(path, name) — making it draggable.
    """
    artwork_layer_ready = Signal(str,    str)   # local_path, game_name
    game_selected       = Signal(str)           # game name picked in the list

    LIMIT = 20                 # artwork per page
    CARD_MIN_W = 108           # → 2 columns at 300 px, 3 columns at ≥ ~390 px
    CARD_MAX_COLS = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchPanel")

        self._game_results  = []
        self._selected_game = None
        self._current_page  = 0
        self._total_pages   = 1
        self._cards: List[ArtworkCard] = []
        # FIX (Issue 1): use set so .discard() works correctly (was list before)
        self._pending_replies: set = set()
        self._cols = 2

        # QNetworkAccessManager lives on main thread — fully safe, no segfaults
        self._nam = QNetworkAccessManager(self)
        self._build_ui()
        # FIX (Issue 3 secondary): install wheel guards on all filter combos so
        # scrolling over them doesn't fire _on_filter_changed or steal canvas focus
        self._install_combo_guards()
        self._refresh_key_status()
        self._show_art_placeholder("image", "No game selected", "Pick a game to browse its artwork")

    # ── UI construction ────────────────────────────────────────────────────────
    def _build_ui(self):
        root = vbox(self, (SP["md"], SP["md"], SP["md"], SP["md"]), SP["sm"])

        # ── Header: title · key status · key button ────────────────────────
        head = hbox(spacing=SP["sm"])
        head.addWidget(label("STEAM GRUNGE", "title"), 1)
        self.api_dot = _StatusDot()
        head.addWidget(self.api_dot)
        self.api_status = label("NO KEY", "muted")
        head.addWidget(self.api_status)
        self.api_btn = IconButton("key-round", "Set SteamGridDB API key", on_click=self._set_api_key)
        head.addWidget(self.api_btn)
        root.addLayout(head)

        # ── Search row ─────────────────────────────────────────────────────
        row = hbox(spacing=SP["sm"])
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search a game…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self._search)
        row.addWidget(self.search_input, 1)
        self.search_btn = Button("Search", "default", icon="search", on_click=self._search)
        self.search_btn.setFixedWidth(96)
        row.addWidget(self.search_btn)
        root.addLayout(row)

        # ── Filters (collapsed by default) ─────────────────────────────────
        self.filters_section = Section("Filters", expanded=False)
        fg = grid(h=SP["sm"], v=SP["sm"])
        fg.setColumnStretch(0, 1)
        fg.setColumnStretch(1, 1)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Grids", "Heroes", "Logos", "Icons"])
        self.type_combo.currentIndexChanged.connect(self._on_filter_changed)

        self.style_combo = QComboBox()
        self.style_combo.addItem("Any",        None)
        self.style_combo.addItem("Alternate",  "alternate")
        self.style_combo.addItem("Blurred",    "blurred")
        self.style_combo.addItem("White logo", "white_logo")
        self.style_combo.addItem("Material",   "material")
        self.style_combo.addItem("No logo",    "no_logo")
        self.style_combo.currentIndexChanged.connect(self._on_filter_changed)

        self.dim_combo = QComboBox()
        self.dim_combo.addItem("Any",    None)
        self.dim_combo.addItem("600×900",  "600x900")
        self.dim_combo.addItem("920×430",  "920x430")
        self.dim_combo.addItem("460×215",  "460x215")
        self.dim_combo.addItem("342×482",  "342x482")
        self.dim_combo.currentIndexChanged.connect(self._on_filter_changed)

        self.nsfw_combo = QComboBox()
        self.nsfw_combo.addItems(["Off", "On", "Any"])
        self.nsfw_combo.currentIndexChanged.connect(self._on_filter_changed)

        cells = [("Type", self.type_combo), ("Style", self.style_combo),
                 ("Size", self.dim_combo), ("NSFW", self.nsfw_combo)]
        for i, (title, combo) in enumerate(cells):
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            combo.setMinimumWidth(0)
            cell = QWidget()
            cl = vbox(cell, (0, 0, 0, 0), SP["xs"])
            cl.addWidget(label(title.upper(), "eyebrow"))
            cl.addWidget(combo)
            fg.addWidget(cell, i // 2, i % 2)
        self.filters_section.body.addLayout(fg)
        root.addWidget(self.filters_section)

        # ── Games ──────────────────────────────────────────────────────────
        self.games_section = Section("Games", collapsible=False)
        self.game_list = QListWidget()
        self.game_list.setMinimumHeight(88)           # ~4 rows when space is tight
        self.game_list.setMaximumHeight(136)          # ~6 rows
        self.game_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.game_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.game_list.setTextElideMode(Qt.ElideRight)
        self.game_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.game_list.itemClicked.connect(self._on_game_selected)
        self.game_list.setVisible(False)

        self.game_empty = QFrame()
        self.game_empty.setProperty("surface", "inset")
        self.game_empty.setMinimumHeight(88)
        self.game_empty.setMaximumHeight(136)
        ge = vbox(self.game_empty, (0, 0, 0, 0), 0)
        self._game_empty_state = EmptyState("search", "Search a game", "Results appear here")
        ge.addWidget(self._game_empty_state)

        self.games_section.body.addWidget(self.game_empty)
        self.games_section.body.addWidget(self.game_list)
        self.status_lbl = label("", "muted", elide=True)
        self.status_lbl.setVisible(False)
        self.games_section.body.addWidget(self.status_lbl)
        root.addWidget(self.games_section)

        # ── Artwork (takes the remaining height) ───────────────────────────
        pager = QWidget()
        pl = hbox(pager, (0, 0, 0, 0), SP["xs"])
        self.prev_btn = IconButton("chevron-left", "Previous page", on_click=self._prev_page)
        pl.addWidget(self.prev_btn)
        self.page_info = label("", "mono", align=Qt.AlignCenter)
        self.page_info.setMinimumWidth(44)
        pl.addWidget(self.page_info)
        self.next_btn = IconButton("chevron-right", "Next page", on_click=self._next_page)
        pl.addWidget(self.next_btn)

        self.artwork_section = Section("Artwork", collapsible=False, trailing=pager)
        self.artwork_section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._thumb_scroll = QScrollArea()
        self._thumb_scroll.setWidgetResizable(True)
        self._thumb_scroll.setFrameShape(QFrame.NoFrame)
        self._thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._thumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._thumb_scroll.setMinimumHeight(110)
        self._thumb_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.thumb_container = QWidget()
        self.grid_layout = grid(self.thumb_container, (0, 0, SP["xs"], 0), SP["sm"], SP["sm"])
        self.grid_layout.setAlignment(Qt.AlignTop)
        self._thumb_scroll.setWidget(self.thumb_container)
        self._thumb_scroll.viewport().installEventFilter(self)
        self.artwork_section.body.addWidget(self._thumb_scroll, 1)

        self.art_status = label("", "muted", elide=True)
        self.art_status.setVisible(False)
        self.artwork_section.body.addWidget(self.art_status)
        root.addWidget(self.artwork_section, 1)

        self._rebuild_page_buttons()

    def _install_combo_guards(self):
        """
        FIX (Issue 3 secondary + Issue 1): Install wheel-absorbing event filters
        on all filter combos so that:
          1. Scrolling over them never fires _on_filter_changed (no spurious reloads)
          2. They never steal keyboard focus from the canvas
        """
        for combo in [self.type_combo, self.style_combo,
                      self.dim_combo, self.nsfw_combo]:
            guard = _WheelGuard(combo)
            combo.installEventFilter(guard)
            combo.setFocusPolicy(Qt.StrongFocus)
            # Keep a reference so the guard isn't garbage-collected
            if not hasattr(combo, "_wheel_guards"):
                combo._wheel_guards = []
            combo._wheel_guards.append(guard)

    # ── small state helpers ────────────────────────────────────────────────────
    def _refresh_key_status(self):
        has_key = bool(sgdb_client.api_key and str(sgdb_client.api_key).strip())
        self.api_dot.set_color(C["green"] if has_key else C["red"])
        self.api_status.setText("KEY SET" if has_key else "NO KEY")
        self.api_status.setProperty("tone", "green" if has_key else "red")
        repolish(self.api_status)
        self.api_btn.setToolTip("Change SteamGridDB API key" if has_key else "Set SteamGridDB API key")

    def _set_status(self, text: str, tone: Optional[str] = None):
        """Muted line under the games list ("Searching…", "No results", errors)."""
        self.status_lbl.setText(text)
        self.status_lbl.setProperty("tone", tone or "")
        repolish(self.status_lbl)
        self.status_lbl.setVisible(bool(text))

    def _set_art_status(self, text: str, tone: Optional[str] = None):
        self.art_status.setText(text)
        self.art_status.setProperty("tone", tone or "")
        repolish(self.art_status)
        self.art_status.setVisible(bool(text))

    def _show_game_list(self, show: bool):
        self.game_list.setVisible(show)
        self.game_empty.setVisible(not show)

    def _show_art_placeholder(self, icon: str, title: str, subtitle: str = ""):
        ph = EmptyState(icon, title, subtitle)
        ph.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        cols = max(1, self._cols)
        for c in range(cols):
            self.grid_layout.setColumnStretch(c, 1)
        self.grid_layout.addWidget(ph, 0, 0, 1, cols)

    # ── Slots ──────────────────────────────────────────────────────────────────
    def _set_api_key(self):
        key, ok = QInputDialog.getText(
            self, "SteamGridDB API Key",
            "Enter your SteamGridDB API key:\n(steamgriddb.com → Profile → API)",
            text=sgdb_client.api_key)   # FIX (Issue 5): pre-fill with persisted key
        if ok and key.strip():
            sgdb_client.set_api_key(key.strip())
            self._refresh_key_status()
            if self.status_lbl.property("tone") == "red":
                self._set_status("")

            # FIX (Issue 1): purge any zero-byte or corrupted cache entries that
            # were written during anonymous (401) requests so they don't block
            # the fresh load below.
            self._purge_corrupt_cache()

            # FIX (Issue 1): reload artwork immediately so existing error cards
            # are replaced without requiring the user to click the game again.
            if self._selected_game:
                self._current_page = 0
                self._load_artwork()

    @staticmethod
    def _purge_corrupt_cache():
        """
        Remove zero-byte cache files that were written when a request returned
        a 401/error page instead of image data.  Non-zero files are left alone
        (a future load will detect isNull() and call set_error() safely).
        """
        try:
            from app.config import CACHE_FOLDER
            for fname in os.listdir(CACHE_FOLDER):
                fp = os.path.join(CACHE_FOLDER, fname)
                if os.path.isfile(fp) and os.path.getsize(fp) == 0:
                    try:
                        os.remove(fp)
                    except Exception:
                        pass
        except Exception:
            pass

    def _search(self):
        q = self.search_input.text().strip()
        if not q: return
        if not sgdb_client.api_key:
            self.game_list.clear()
            self._show_game_list(False)
            self._set_status("Set your SteamGridDB API key first (key button above)", "red")
            return
        self.game_list.clear()
        self._show_game_list(False)
        self.game_list.setEnabled(False)
        self.search_btn.set_loading(True)
        self._set_status("Searching…", "accent")
        self._search_gen = getattr(self, "_search_gen", 0) + 1
        gen = self._search_gen

        def _done(results):
            if gen != self._search_gen:
                return                      # a newer search superseded this one
            self.search_btn.set_loading(False)
            self.game_list.setEnabled(True)
            self.game_list.clear()
            if isinstance(results, Exception):
                self._set_status(f"Search failed: {results}", "red")
                return
            self._game_results = results
            if not results:
                self._set_status("No results", None)
                return
            for g in results:
                item = QListWidgetItem(g["name"])
                item.setData(Qt.UserRole, g["id"])
                item.setToolTip(g["name"])
                self.game_list.addItem(item)
            self._set_status(f"{len(results)} game{'s' if len(results) != 1 else ''}")
            self._show_game_list(True)

        _AsyncBridge(self, lambda: sgdb_client.search_games(q), _done).start()

    def _on_game_selected(self, item: QListWidgetItem):
        if item.data(Qt.UserRole) is None:
            return                          # placeholder row (never happens now, kept for safety)
        self._selected_game = {"id": item.data(Qt.UserRole), "name": item.text()}
        self._current_page  = 0
        self.game_selected.emit(item.text())
        self._load_artwork()

    def _on_filter_changed(self):
        if self._selected_game:
            self._current_page = 0
            self._load_artwork()

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._load_artwork()

    def _next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._load_artwork()

    def _goto_page(self, p: int):
        self._current_page = p
        self._load_artwork()

    # ── Core loader ────────────────────────────────────────────────────────────
    def _load_artwork(self):
        if not self._selected_game:
            return

        # Gather filters
        asset_type = ["grids", "heroes", "logos", "icons"][self.type_combo.currentIndex()]
        style_val  = self.style_combo.currentData()
        dim_val    = self.dim_combo.currentData()
        nsfw_map   = {"Off": "false", "On": "true", "Any": "any"}
        nsfw_val   = nsfw_map.get(self.nsfw_combo.currentText(), "false")

        game_id = self._selected_game["id"]
        page    = self._current_page
        self._load_gen = getattr(self, "_load_gen", 0) + 1
        gen = self._load_gen

        self._clear_thumbs()
        self._set_art_status("")
        self._show_art_placeholder("loader-circle", "Loading artwork…", self._selected_game["name"])

        def _fetch():
            return sgdb_client.get_grids(
                game_id,
                asset_type = asset_type,
                styles     = [style_val] if style_val else None,
                dimensions = [dim_val]   if dim_val   else None,
                nsfw       = nsfw_val,
                page       = page,
                limit      = self.LIMIT,
            )

        _AsyncBridge(self, _fetch,
                     lambda res: self._on_artwork_loaded(res, gen)).start()

    def _on_artwork_loaded(self, res, gen: int):
        if gen != getattr(self, "_load_gen", 0):
            return                          # user moved on to another page/game
        if isinstance(res, Exception):
            items, total = [], 0
        else:
            items, total = res

        self._total_pages = max(1, (total + self.LIMIT - 1) // self.LIMIT)
        self._rebuild_page_buttons()
        self._clear_thumbs()
        prune_cache()   # keep data/cache bounded — thumbnails are re-fetched on demand

        if not items:
            self._show_art_placeholder("image", "No artwork", "Check the API key or try other filters")
            return

        self._populate_cards(items)
        self.page_info.setToolTip(f"Page {self._current_page + 1} of {self._total_pages} · {total} total")

    def _populate_cards(self, items) -> None:
        """Create cards for `items`, lay them out, and start thumbnail fetches."""
        for item in items:
            full_url  = item.get("url", "")
            thumb_url = item.get("thumb", full_url)
            if not full_url:
                continue
            card = ArtworkCard(full_url)
            card.clicked.connect(self._on_card_clicked)
            self._cards.append(card)

            # Check disk cache first — instant display
            local = get_cache_path(thumb_url)
            if os.path.exists(local) and os.path.getsize(local) > 0:
                try:
                    with open(local, "rb") as f:
                        card.set_pixmap_from_bytes(f.read())
                    continue
                except Exception:
                    pass

            # Fetch via QNetworkAccessManager (main thread, no threads, no segfault)
            self._fetch_thumb(card, thumb_url, full_url)
        self._relayout_cards()

    # ── responsive grid ───────────────────────────────────────────────────────
    def eventFilter(self, obj, event):
        if obj is self._thumb_scroll.viewport() and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._relayout_cards)
        return super().eventFilter(obj, event)

    def _grid_metrics(self) -> tuple[int, int]:
        """(columns, card width) for the current viewport width."""
        # Always reserve the scrollbar width so the column count does not
        # flip-flop when the bar appears/disappears.
        vw = self._thumb_scroll.viewport().width()
        vbar = self._thumb_scroll.verticalScrollBar()
        if not vbar.isVisible():
            vw -= vbar.sizeHint().width()
        m = self.grid_layout.contentsMargins()
        avail = max(0, vw - m.left() - m.right())
        sp = self.grid_layout.horizontalSpacing()
        cols = max(2, min(self.CARD_MAX_COLS, (avail + sp) // (self.CARD_MIN_W + sp)))
        card_w = max(60, (avail - sp * (cols - 1)) // cols)
        return cols, card_w

    def _relayout_cards(self):
        cols, card_w = self._grid_metrics()
        self._cols = cols
        if not self._cards:
            return
        # detach every card, then re-add in the new column count
        for c in self._cards:
            self.grid_layout.removeWidget(c)
        for idx, c in enumerate(self._cards):
            c.set_card_width(card_w)
            row, col = divmod(idx, cols)
            self.grid_layout.addWidget(c, row, col)
        for c in range(cols):
            self.grid_layout.setColumnStretch(c, 1)
        for c in range(cols, self.CARD_MAX_COLS + 1):
            self.grid_layout.setColumnStretch(c, 0)

    def _fetch_thumb(self, card: ArtworkCard, thumb_url: str, full_url: str):
        """
        Fetch thumbnail via QNetworkAccessManager — runs entirely on main thread.

        FIX (Issue 1):
        - _pending_replies is now a set so .discard() works correctly.
        - HTTP status code is checked explicitly: Qt reports NoError even for
          401/403 responses (it got a response — just not the right one).
          This prevents HTML error pages from being written to disk as fake images.
        - Response bytes are validated as real image data via QPixmap before
          caching, so corrupt cache entries can never cause permanent error cards.
        """
        # FIX: SteamGridDB CDN (cdn2.steamgriddb.com) returns 401 if Bearer auth
        # is sent — CDN images are public and must be fetched without auth headers.
        # Auth is only needed for API endpoints (steamgriddb.com/api/...).
        req = QNetworkRequest(QUrl(thumb_url))
        _is_cdn = "cdn" in thumb_url or "/api/" not in thumb_url
        if not _is_cdn and sgdb_client.api_key:
            req.setRawHeader(b"Authorization", f"Bearer {sgdb_client.api_key}".encode())

        reply = self._nam.get(req)
        self._pending_replies.add(reply)

        def _is_image_data(data: bytes) -> bool:
            """Return True only if data decodes as a valid image."""
            if not data or len(data) < 8:
                return False
            pix = QPixmap()
            pix.loadFromData(data)
            return not pix.isNull()

        def _cache_bytes(url: str, data: bytes):
            local = get_cache_path(url)
            try:
                with open(local, "wb") as f:
                    f.write(data)
            except Exception:
                pass

        def on_finished(r=reply, c=card, tu=thumb_url, fu=full_url):
            self._pending_replies.discard(r)

            # Read response bytes first — we use _is_image_data as the sole
            # truth rather than HTTP status, because Qt's HttpStatusCodeAttribute
            # returns 0/None for many CDN responses even when the image arrives.
            # A real 401 returns an HTML body that _is_image_data rejects.
            if r.error() == QNetworkReply.NetworkError.NoError:
                data = bytes(r.readAll())
                if _is_image_data(data):
                    _cache_bytes(tu, data)
                    if not c.isHidden() and c.parent() is not None:
                        c.set_pixmap_from_bytes(data)
                    r.deleteLater()
                    return
                # Got a response but it's not an image (HTML 401 page, redirect, etc.)
                # Fall through to retry with full_url + fresh key from sgdb_client

            # Thumb failed — retry with full URL. CDN URLs must NOT have auth header.
            req2 = QNetworkRequest(QUrl(fu))
            _is_cdn2 = "cdn" in fu or "/api/" not in fu
            if not _is_cdn2 and sgdb_client.api_key:
                req2.setRawHeader(b"Authorization", f"Bearer {sgdb_client.api_key}".encode())
            reply2 = self._nam.get(req2)
            self._pending_replies.add(reply2)

            def on_finished2(r2=reply2, c2=c, fu2=fu):
                self._pending_replies.discard(r2)
                if r2.error() == QNetworkReply.NetworkError.NoError:
                    data2 = bytes(r2.readAll())
                    if _is_image_data(data2) and c2.parent() is not None:
                        _cache_bytes(fu2, data2)
                        c2.set_pixmap_from_bytes(data2)
                        r2.deleteLater()
                        return
                if c2.parent() is not None:
                    c2.set_error()
                r2.deleteLater()

            reply2.finished.connect(on_finished2)
            r.deleteLater()

        reply.finished.connect(on_finished)

    def _clear_thumbs(self):
        # Abort all in-flight network requests first to prevent callbacks to dead widgets
        for reply in list(self._pending_replies):
            try:
                reply.abort()
                reply.deleteLater()
            except Exception:
                pass
        self._pending_replies.clear()
        self._cards.clear()
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item and item.widget():
                w = item.widget()
                w.hide()                    # so late replies see isHidden()
                w.setParent(None)
                w.deleteLater()

    def _rebuild_page_buttons(self):
        """Update the pager (chevrons + 'cur/total' label) for the current page."""
        total = self._total_pages
        cur   = self._current_page
        self.page_info.setText(f"{cur + 1}/{total}")
        self.page_info.setToolTip(f"Page {cur + 1} of {total}")
        self.prev_btn.setEnabled(cur > 0)
        self.next_btn.setEnabled(cur < total - 1)

    @staticmethod
    def _visible_pages(cur: int, total: int) -> List[int]:
        """Return page indices to show (always first, last, and window around current)."""
        pages = set()
        pages.add(0)
        pages.add(total - 1)
        for d in range(-2, 3):
            p = cur + d
            if 0 <= p < total:
                pages.add(p)
        return sorted(pages)

    # ── Artwork click → canvas layer ──────────────────────────────────────────
    def _on_card_clicked(self, full_url: str):
        """
        Download the full-res image in the background, validate it, then emit
        it as a canvas layer. The card is highlighted while downloading.
        """
        card = next((c for c in self._cards if c.full_url == full_url), None)
        name = self._selected_game["name"] if self._selected_game else ""
        if card:
            card.set_busy(True)

        def _work():
            local = get_cache_path(full_url)
            # A cached file that is not a valid image → delete and re-download
            if os.path.exists(local):
                try:
                    PILImage.open(local).verify()
                except Exception:
                    try: os.remove(local)
                    except Exception: pass
            if not os.path.exists(local):
                local = sgdb_client.download_image(full_url, local)
            if not local or not os.path.exists(local):
                raise RuntimeError("download failed")
            try:
                PILImage.open(local).verify()
            except Exception:
                try: os.remove(local)
                except Exception: pass
                raise RuntimeError("file is not a valid image")
            return local

        def _done(res):
            if card is not None:
                try:
                    card.set_busy(False)
                except RuntimeError:
                    pass                    # card was deleted (page changed)
            if isinstance(res, Exception):
                if card is not None:
                    try: card.set_error()
                    except RuntimeError: pass
                self._set_art_status(f"Could not load image: {res}", "red")
                return
            self.artwork_layer_ready.emit(res, name)

        _AsyncBridge(self, _work, _done).start()

    # ── Screenshot helper (tools/shot.py search-results) ──────────────────────
    def debug_fill_results(self):
        """Populate list + grid with 9 placeholder entries (no network)."""
        names = ["Elden Ring", "Hades", "Hollow Knight", "Celeste", "Outer Wilds",
                 "Disco Elysium", "Stardew Valley", "Portal 2", "Half-Life: Alyx"]
        colours = [C["accent_dim"], C["surface_3"], C["green_dim"], C["gold_dim"], C["red_dim"],
                   C["border_strong"], C["surface_2"], C["accent_dim"], C["surface_3"]]
        self.search_input.setText("elden")
        self.game_list.clear()
        for i, n in enumerate(names):
            it = QListWidgetItem(n)
            it.setData(Qt.UserRole, 1000 + i)
            self.game_list.addItem(it)
        self.game_list.setCurrentRow(0)
        self._show_game_list(True)
        self._set_status(f"{len(names)} games")
        self._selected_game = {"id": 1000, "name": names[0]}
        self._total_pages = 3
        self._current_page = 0
        self._rebuild_page_buttons()
        self._clear_thumbs()
        for i, n in enumerate(names):
            card = ArtworkCard(f"debug://{i}")
            pm = QPixmap(300, 450)
            pm.fill(QColor(colours[i % len(colours)]))
            p = QPainter(pm)
            p.setFont(theme_font("2xl", bold=True))
            p.setPen(QColor(C["text_2"]))
            p.drawText(pm.rect(), Qt.AlignCenter | Qt.TextWordWrap, n)
            p.end()
            card._pix = pm
            self._cards.append(card)
        self._relayout_cards()
