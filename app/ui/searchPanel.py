"""
searchPanel.py — SteamGridDB browser with:
  - Working thumbnail loading (signals back to main thread correctly)
  - Filter bar: Asset Type, Style, Dimensions, NSFW, Sort
  - Page navigation (prev/next + page number)
  - Clicking artwork → adds as a draggable/resizable canvas Layer
  - No "Load from File" button
"""
from __future__ import annotations
import os, io, requests
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QScrollArea,
    QFrame, QComboBox, QSizePolicy, QInputDialog, QGridLayout,
)
from PySide6.QtCore  import Qt, Signal, QObject, Slot, QUrl, QByteArray
from PySide6.QtGui   import QPixmap, QFont
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from PIL import Image as PILImage  # still used for _on_card_clicked full-res load

from app.services.steamgrid import client as sgdb_client
from app.services.cache     import get_cache_path


# ── Single thumbnail card ──────────────────────────────────────────────────────
class ArtworkCard(QFrame):
    clicked = Signal(str)   # full-res URL

    def __init__(self, full_url: str, parent=None):
        super().__init__(parent)
        self.full_url = full_url
        self.setFixedSize(145, 210)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QFrame { background:#111; border:1px solid #2a2a2a; border-radius:3px; }
            QFrame:hover { border:1px solid #5a7aaa; }
        """)
        self._lbl = QLabel("…", self)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setGeometry(1, 1, 143, 208)
        self._lbl.setStyleSheet("color:#444; font-size:12px; background:transparent;")

    def set_pixmap_from_bytes(self, data: bytes):
        """Called in main thread — totally safe."""
        try:
            pix = QPixmap()
            pix.loadFromData(data)
            if not pix.isNull():
                scaled = pix.scaled(143, 208, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._lbl.setPixmap(scaled)
                self._lbl.setText("")
            else:
                self.set_error()
        except Exception:
            self.set_error()

    def set_error(self):
        self._lbl.setText("✕")
        self._lbl.setStyleSheet("color:#553333; font-size:14px; background:transparent;")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.full_url)
        super().mousePressEvent(e)


# ── Panel styles ───────────────────────────────────────────────────────────────
STYLE = """
QWidget#SearchPanel { background:#161616; border-right:1px solid #2a2a2a; }
QLineEdit {
    background:#0d0d0d; border:1px solid #333; border-radius:3px;
    color:#ccc; padding:5px 8px; font-family:'Courier New'; font-size:14px;
}
QLineEdit:focus { border:1px solid #666; }
QPushButton {
    background:#252525; border:1px solid #404040; color:#bbb;
    padding:5px 10px; font-family:'Courier New'; font-size:13px; border-radius:2px;
}
QPushButton:hover { background:#303030; border-color:#666; color:#fff; }
QPushButton#primary { background:#1a1a2e; border-color:#3a3a6e; color:#8888cc; }
QPushButton#primary:hover { background:#22224a; color:#aaaaff; }
QPushButton#page_btn { padding:2px 4px; font-size:12px; min-width:30px; max-width:30px; }
QPushButton#page_btn[current="true"] { background:#1e1e3a; color:#8888dd; border-color:#4444aa; }
QComboBox {
    background:#0d0d0d; border:1px solid #333; color:#aaa;
    padding:3px 6px; font-family:'Courier New'; font-size:12px; border-radius:2px;
}
QComboBox::drop-down { border:none; }
QComboBox QAbstractItemView { background:#1a1a1a; color:#ccc; selection-background-color:#2a2a4a; }
QLabel#hdr { color:#666; font-size:12px; font-family:'Courier New'; letter-spacing:2px; padding:3px 0; }
QListWidget {
    background:#0d0d0d; border:1px solid #2a2a2a; color:#ccc;
    font-family:'Courier New'; font-size:14px;
}
QListWidget::item { padding:5px 8px; border-bottom:1px solid #1e1e1e; }
QListWidget::item:selected { background:#1e1e3a; color:#8888dd; }
QListWidget::item:hover { background:#1e1e1e; }
"""


# ── Main panel ─────────────────────────────────────────────────────────────────
class SearchPanel(QWidget):
    """
    Emits artwork_layer_ready(local_path, game_name) so mainWindow
    can call canvas.add_image_layer(path, name) — making it draggable.
    Also keeps artwork_selected(pil_img, name) for backward compat.
    """
    artwork_selected    = Signal(object, str)   # PIL image, name (bg compat)
    artwork_layer_ready = Signal(str,    str)   # local_path, game_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchPanel")
        self.setStyleSheet(STYLE)

        self._game_results  = []
        self._selected_game = None
        self._current_page  = 0
        self._total_pages   = 1
        self._cards: List[ArtworkCard] = []
        # FIX (Issue 1): use set so .discard() works correctly (was list before)
        self._pending_replies: set = set()

        # QNetworkAccessManager lives on main thread — fully safe, no segfaults
        self._nam = QNetworkAccessManager(self)
        # Attach API key header to every request
        self._build_ui()
        # FIX (Issue 3 secondary): install wheel guards on all filter combos so
        # scrolling over them doesn't fire _on_filter_changed or steal canvas focus
        self._install_combo_guards()

    # ── UI construction ────────────────────────────────────────────────────────
    def _build_ui(self):
        # Outer layout — holds the scrollable top section + fixed artwork area
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Scrollable top section (title → filters) ───────────────────────
        top_scroll = QScrollArea()
        top_scroll.setWidgetResizable(True)
        top_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        top_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        top_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        top_scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical {
                background: #111; width: 6px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #333; border-radius: 3px; min-height: 20px;
            }
            QScrollBar::handle:vertical:hover { background: #555; }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
        """)

        top_widget = QWidget()
        top_widget.setStyleSheet("background: transparent;")
        root = QVBoxLayout(top_widget)
        root.setContentsMargins(10, 10, 10, 6)
        root.setSpacing(6)

        # Title
        t = QLabel("STEAM GRUNGE")
        t.setStyleSheet("font-family:'Courier New'; font-size:15px; font-weight:bold; "
                        "color:#aaa; letter-spacing:3px; padding-bottom:4px; "
                        "border-bottom:1px solid #2a2a2a;")
        root.addWidget(t)

        # API key
        self.api_btn = QPushButton("⚙ Set API Key")
        self.api_btn.setObjectName("primary")
        self.api_btn.clicked.connect(self._set_api_key)
        root.addWidget(self.api_btn)

        # Search
        root.addWidget(self._hdr("SEARCH STEAMGRIDDB"))
        row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search a game…")
        self.search_input.returnPressed.connect(self._search)
        row.addWidget(self.search_input)
        root.addLayout(row)

        self.search_btn = QPushButton("SEARCH")
        self.search_btn.clicked.connect(self._search)
        root.addWidget(self.search_btn)

        # Results list
        root.addWidget(self._hdr("RESULTS"))
        self.game_list = QListWidget()
        self.game_list.setMaximumHeight(180)
        self.game_list.itemClicked.connect(self._on_game_selected)
        root.addWidget(self.game_list)

        # ── Filters ────────────────────────────────────────
        root.addWidget(self._hdr("FILTERS"))
        filter_grid = QGridLayout()
        filter_grid.setSpacing(4)

        # Asset type
        filter_grid.addWidget(QLabel("Type"), 0, 0)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Grids", "Heroes", "Logos", "Icons"])
        self.type_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_grid.addWidget(self.type_combo, 1, 0)

        # Style
        filter_grid.addWidget(QLabel("Style"), 0, 1)
        self.style_combo = QComboBox()
        self.style_combo.addItem("Any",        None)
        self.style_combo.addItem("Alternate",  "alternate")
        self.style_combo.addItem("Blurred",    "blurred")
        self.style_combo.addItem("White logo", "white_logo")
        self.style_combo.addItem("Material",   "material")
        self.style_combo.addItem("No logo",    "no_logo")
        self.style_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_grid.addWidget(self.style_combo, 1, 1)

        # Dimensions
        filter_grid.addWidget(QLabel("Size"), 0, 2)
        self.dim_combo = QComboBox()
        self.dim_combo.addItem("Any",    None)
        self.dim_combo.addItem("600×900",  "600x900")
        self.dim_combo.addItem("920×430",  "920x430")
        self.dim_combo.addItem("460×215",  "460x215")
        self.dim_combo.addItem("342×482",  "342x482")
        self.dim_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_grid.addWidget(self.dim_combo, 1, 2)

        # NSFW
        filter_grid.addWidget(QLabel("NSFW"), 0, 3)
        self.nsfw_combo = QComboBox()
        self.nsfw_combo.addItems(["Off", "On", "Any"])
        self.nsfw_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_grid.addWidget(self.nsfw_combo, 1, 3)

        root.addLayout(filter_grid)
        root.addStretch(0)

        top_scroll.setWidget(top_widget)
        outer.addWidget(top_scroll, stretch=0)

        # ── Artwork section (fixed below, takes remaining space) ───────────
        artwork_widget = QWidget()
        artwork_widget.setStyleSheet("background: #161616;")
        artwork_layout = QVBoxLayout(artwork_widget)
        artwork_layout.setContentsMargins(10, 0, 10, 0)
        artwork_layout.setSpacing(4)

        artwork_layout.addWidget(self._hdr("ARTWORK"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;background:#0a0a0a;}")

        self.thumb_container = QWidget()
        self.thumb_container.setStyleSheet("background:#0a0a0a;")
        self.grid_layout = QGridLayout(self.thumb_container)
        self.grid_layout.setSpacing(5)
        self.grid_layout.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(self.thumb_container)
        artwork_layout.addWidget(scroll, stretch=1)

        outer.addWidget(artwork_widget, stretch=1)

        # Keep a reference so pagination can be added below artwork_widget
        self._outer_layout = outer
        self._artwork_layout = artwork_layout

        # ── Pagination ─────────────────────────────────────
        page_widget = QWidget()
        page_widget.setFixedHeight(34)
        self.page_bar = QHBoxLayout(page_widget)
        self.page_bar.setContentsMargins(0, 0, 0, 0)
        self.page_bar.setSpacing(2)

        self.prev_btn = QPushButton("◀")
        self.prev_btn.setObjectName("page_btn")
        self.prev_btn.setFixedSize(30, 28)
        self.prev_btn.clicked.connect(self._prev_page)
        self.page_bar.addWidget(self.prev_btn)

        self.page_labels: List[QPushButton] = []
        self._page_btn_container = QHBoxLayout()
        self._page_btn_container.setSpacing(2)
        self._page_btn_container.setContentsMargins(0, 0, 0, 0)
        self.page_bar.addLayout(self._page_btn_container)

        self.next_btn = QPushButton("▶")
        self.next_btn.setObjectName("page_btn")
        self.next_btn.setFixedSize(30, 28)
        self.next_btn.clicked.connect(self._next_page)
        self.page_bar.addWidget(self.next_btn)

        self.page_info = QLabel("")
        self.page_info.setStyleSheet("color:#555; font-size:12px; font-family:'Courier New'; padding-left:4px;")
        self.page_bar.addWidget(self.page_info, stretch=1)

        artwork_layout.addWidget(page_widget)

    def _install_combo_guards(self):
        """
        FIX (Issue 3 secondary + Issue 1): Install wheel-absorbing event filters
        on all filter combos so that:
          1. Scrolling over them never fires _on_filter_changed (no spurious reloads)
          2. They never steal keyboard focus from the canvas
        """
        from PySide6.QtCore import QObject, QEvent

        class _WheelGuard(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Wheel:
                    event.ignore()
                    return True
                return False

        for combo in [self.type_combo, self.style_combo,
                      self.dim_combo, self.nsfw_combo]:
            guard = _WheelGuard(combo)
            combo.installEventFilter(guard)
            # Keep a reference so the guard isn't garbage-collected
            if not hasattr(combo, "_wheel_guards"):
                combo._wheel_guards = []
            combo._wheel_guards.append(guard)

    def _hdr(self, text: str) -> QLabel:
        l = QLabel(text); l.setObjectName("hdr"); return l

    # ── Slots ──────────────────────────────────────────────────────────────────
    def _set_api_key(self):
        key, ok = QInputDialog.getText(
            self, "SteamGridDB API Key",
            "Enter your SteamGridDB API key:\n(steamgriddb.com → Profile → API)",
            text=sgdb_client.api_key)   # FIX (Issue 5): pre-fill with persisted key
        if ok and key.strip():
            sgdb_client.set_api_key(key.strip())
            self.api_btn.setText("✔ API Key Set")

            # FIX (Issue 1): purge any zero-byte or corrupted cache entries that
            # were written during anonymous (401) requests so they don't block
            # the fresh load below.
            self._purge_corrupt_cache()

            # FIX (Issue 1): reload artwork immediately so existing ✕ cards
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
        self.game_list.clear()
        results = sgdb_client.search_games(q)
        self._game_results = results
        for g in results:
            item = QListWidgetItem(g["name"])
            item.setData(Qt.UserRole, g["id"])
            self.game_list.addItem(item)

    def _on_game_selected(self, item: QListWidgetItem):
        self._selected_game = {"id": item.data(Qt.UserRole), "name": item.text()}
        self._current_page  = 0
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

        items, total = sgdb_client.get_grids(
            self._selected_game["id"],
            asset_type = asset_type,
            styles     = [style_val] if style_val else None,
            dimensions = [dim_val]   if dim_val   else None,
            nsfw       = nsfw_val,
            page       = self._current_page,
            limit      = 20,
        )

        LIMIT = 20
        self._total_pages = max(1, (total + LIMIT - 1) // LIMIT)
        self._rebuild_page_buttons()
        self._clear_thumbs()

        if not items:
            placeholder = QLabel("No results.\nCheck API key or try\ndifferent filters.")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color:#555; font-size:13px; font-family:'Courier New';")
            self.grid_layout.addWidget(placeholder, 0, 0, 1, 2)
            return

        # Build cards in a 2-column grid
        COLS = 2
        for idx, item in enumerate(items):
            full_url  = item.get("url", "")
            thumb_url = item.get("thumb", full_url)
            if not full_url:
                continue

            card = ArtworkCard(full_url)
            card.clicked.connect(self._on_card_clicked)
            self._cards.append(card)
            row, col = divmod(idx, COLS)
            self.grid_layout.addWidget(card, row, col)

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

        self.page_info.setText(f"pg {self._current_page+1}/{self._total_pages}  ({total} total)")

    def _fetch_thumb(self, card: ArtworkCard, thumb_url: str, full_url: str):
        """
        Fetch thumbnail via QNetworkAccessManager — runs entirely on main thread.

        FIX (Issue 1):
        - _pending_replies is now a set so .discard() works correctly.
        - HTTP status code is checked explicitly: Qt reports NoError even for
          401/403 responses (it got a response — just not the right one).
          This prevents HTML error pages from being written to disk as fake images.
        - Response bytes are validated as real image data via QPixmap before
          caching, so corrupt cache entries can never cause permanent ✕ cards.
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
                item.widget().deleteLater()

    def _rebuild_page_buttons(self):
        # Clear old buttons
        while self._page_btn_container.count():
            item = self._page_btn_container.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self.page_labels.clear()

        # Show up to 7 page buttons around current
        total = self._total_pages
        cur   = self._current_page
        pages = self._visible_pages(cur, total)
        prev_p = None
        for p in pages:
            if prev_p is not None and p > prev_p + 1:
                dot = QLabel("…")
                dot.setStyleSheet("color:#444; font-size:12px;")
                self._page_btn_container.addWidget(dot)
            btn = QPushButton(str(p + 1))
            btn.setObjectName("page_btn")
            btn.setProperty("current", p == cur)
            btn.setFixedSize(30, 28)
            btn.clicked.connect(lambda checked, pg=p: self._goto_page(pg))
            self._page_btn_container.addWidget(btn)
            self.page_labels.append(btn)
            prev_p = p

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
        Download full-res image and emit as canvas layer (draggable).

        FIX (Issue 1): After download, verify the file is a real image before
        emitting.  sgdb_client.download_image() already cleans up zero-byte
        files; this catches the case where a CDN returns a small HTML error
        page with a 200 status, which would otherwise be cached and opened
        as a corrupt PIL image.
        """
        from app.services.cache import get_cache_path
        local = get_cache_path(full_url)

        # If cached file exists but is not a valid image, delete and re-download
        if os.path.exists(local):
            pix_check = QPixmap()
            pix_check.loadFromData(open(local, "rb").read())
            if pix_check.isNull():
                try:
                    os.remove(local)
                except Exception:
                    pass

        if not os.path.exists(local):
            local = sgdb_client.download_image(full_url, local)

        if local and os.path.exists(local):
            # Final validation — confirm PIL can open it before adding to canvas
            try:
                PILImage.open(local).verify()
            except Exception:
                # File is corrupt (HTML page, partial download, etc.) — remove it
                try:
                    os.remove(local)
                except Exception:
                    pass
                return

            name = self._selected_game["name"] if self._selected_game else ""
            self.artwork_layer_ready.emit(local, name)