# Changelog

All notable changes to Steam Grunge Editor are documented here.

---

## v2.0.0 2026-03-13

### Fixed
- Fixed inconsistent Steam artwork syncing across games that use hashed `librarycache` subfolders
- Improved Steam sync reliability through recursive target discovery and safer write handling
- Fixed transparency preservation for PNG-based artwork during export and Steam sync
- Improved sync result reporting to better distinguish full, partial, and grid-only sync outcomes

### Improved
- More robust Steam `librarycache` target classification by filename
- Better handling of mixed Steam cache layouts across different games


## [2.0.0] - 2026-03-12

### Major
- Complete render pipeline stabilization
- Unified layer compositing pipeline for preview and export
- Fixed FX pipeline breaking blend modes
- Export now matches canvas rendering

### Canvas Interaction
- Restored real-time layer transforms (move, resize, rotate)
- Fixed dynamic transform rendering during interaction
- Fixed viewport pan resetting to (0,0)
- Middle mouse panning now persists correctly

### Rendering
- Unified preview and export compositing pipeline
- Fixed blend modes breaking when global FX enabled
- Fixed layer compositing with:
  - VHS
  - film grain
  - chromatic aberration

### UI
- Restored floating context toolbar original functionality
- Restored contextual color palette behavior
- Fixed toolbar integration with new canvas pipeline

### Stability
- Fixed Qt threading issues causing crashes during export
- Fixed AppState missing fields during export
- Fixed project save/load identity persistence
- Fixed cross-thread Qt warnings

### Internal
- Removed legacy compositor path
- Unified canvas and export render pipeline
- Improved render invalidation logic

## [2.0.0] — 2026-03-10

### Fixed

**Issue 1 — SteamGridDB 401 errors, broken thumbnails, and corrupt cache (`searchPanel.py`, `steamgrid.py`)**

Root cause: SteamGridDB's CDN (`cdn2.steamgriddb.com`) is a public image server that
rejects `Authorization: Bearer` headers with 401. Auth was being sent to both API
endpoints (correct) and CDN thumbnail/image URLs (wrong).

- `steamgrid.py` — `download_image()` now detects CDN URLs and uses a plain
  unauthenticated `requests.get()` for those; API calls still use the authenticated session
- `searchPanel.py` — `_fetch_thumb()` no longer attaches the Bearer header to CDN
  `QNetworkRequest`s; auth only sent to actual API endpoints
- `_fetch_thumb()` now reads `sgdb_client.api_key` live at retry time instead of
  capturing it in a closure, so mid-session key changes take effect immediately
- `_fetch_thumb()` validity check replaced: removed the broken `HttpStatusCodeAttribute == 200`
  gate (Qt returns 0 for many valid CDN responses) — now uses `_is_image_data()` (a
  `QPixmap.loadFromData()` attempt) as the single source of truth
- `_set_api_key()` now pre-fills the dialog with the current key, calls
  `_purge_corrupt_cache()` to remove zero-byte files from anonymous requests, then
  immediately calls `_load_artwork()` so broken cards refresh without a manual re-click
- `_pending_replies` changed from `list` to `set` — `.discard()` was dead code on a list;
  in-flight requests are now properly tracked and cleaned up
- `_on_card_clicked()` validates any cached file as a real image before using it (catches
  files that slipped through before this fix), and runs `PIL.verify()` after download
- `_install_combo_guards()` installs wheel-absorbing event filters on all 4 filter combos
  so scrolling over them no longer fires spurious `_load_artwork()` calls

**Issue 2 — Update checker not working (`mainWindow.py`)**

- `APP_VERSION` and `GITHUB_REPO` defined as module-level constants — previously undefined,
  causing `NameError` on lines 1774, 1779, and 1815
- `APP_VERSION` now read from the `VERSION` file at startup for single-source-of-truth versioning
- `_check_for_updates()` spawned in a daemon thread using only `urllib`; hits
  `api.github.com/repos/.../releases/latest`, compares `tag_name` against `APP_VERSION`,
  marshals back to Qt thread via `QTimer.singleShot(0, ...)` — the only safe way to touch
  widgets from a background thread; all network errors silently swallowed
- `_show_update_banner()` adds a green clickable `QPushButton` to the status bar; clicking
  opens the releases page in the browser
- `Help → Check for Updates` wired for manual re-checks
- `_show_about` now displays the version number
- Startup check fires 3 seconds after launch so it never delays window display

**Issue 3 — Bounding box loses handles after combo/wheel scroll (`previewCanvas.py`)**

- `wheelEvent` override added: `Ctrl+scroll` handled as zoom; all other wheel events get
  `e.ignore()` so parent widgets cannot steal focus
- `focusOutEvent` guard added: detects focus loss during active drag/resize/rotate and
  cleanly cancels the interaction instead of leaving the canvas stuck
- `install_combo_wheel_guard()` static helper absorbs wheel events on any `QComboBox`
  before they reach the combo, preventing value changes and focus theft

**Issue 4 — Performance: slider drag freezes canvas (`previewCanvas.py`, `editorPanel.py`)**

- `update_effects_overlay()` — two-phase debounce via `_fx_commit_timer` (400 ms):
  every slider tick sets `_fx_preview_mode = True` and restarts the timer; when the slider
  stops, `_fx_commit_fullres()` fires once for a full-res repaint
- During preview mode, `_draw_with_global_fx()` composites at 25% resolution
  (e.g. 150×225 for a 600×900 doc) — 16× fewer pixels through NumPy; Qt scales up for
  display. Layer geometry scaled to match (`_scale_factor`). Swap LANCZOS → BILINEAR
  during preview (5× faster, unnoticeable at slider speed)
- FX fast path during interaction: while `_drag_active`, `_resize_active`, or
  `_rotate_active`, `paintEvent` draws the cached `_fx_cache` pixmap instead of re-running
  the full PIL + NumPy pipeline
- `_draw_with_global_fx()` now saves its result to `self._fx_cache` for the fast path
- `invalidate()` removed from rotate/move/resize drag handlers — pixel content has not
  changed during drag, only transform. Single `invalidate()` + cache clear on mouse release
- `_update_viewport()` dirty-cache check: tuple key `(W, H, dw, dh, zoom, pan_x, pan_y)`;
  returns immediately if nothing changed — was recomputing on every `paintEvent` and
  `mouseMoveEvent`
- Film grain vectorised: `arr[:, :, :3] += noise` (shape `(h, w, 1)`) broadcasts across
  all 3 channels in one SIMD op — ~3× fewer allocations
- CA via slice assignment: `arr[:, shift:, 0] = arr[:, :-shift, 0].copy()` — eliminates
  two full-frame temporary allocations that `np.roll` was creating
- `editorPanel.py` — `_on_grain()` and `_on_ca()` no longer emit `settings_changed`,
  preventing a redundant `compositor.compose()` call (compositor has no concept of
  grain/CA; those are canvas-only post-processing effects)

**Issue 5 — API key not persisted between sessions (`steamgrid.py`)**

- `_load_settings()` / `_save_settings()` added using `settings.json` in `DATA_DIR`
- On `__init__` the client loads the persisted key automatically; on `set_api_key()` the
  key is written to disk immediately. No changes needed at call sites

**Issue 6 — Wrong import paths causing startup errors (`prejectIO.py`, `mainWindow.py`)**

- `prejectIO.py` — `TYPE_CHECKING` import corrected from `app.ui.tabs.tabManager` to
  `app.ui.tabManager` (matches actual file tree)
- `mainWindow.py` line 1675 — `from app.services.state import AppState` corrected to
  `from app.state import AppState`

**Issue 7 — Film grain wipes out per-layer adjustments (`previewCanvas.py`)**

- `_draw_with_global_fx()` — was iterating `l.pil_image` directly, bypassing `_get_pix()`
  where brightness, contrast, saturation, and tint are applied and cached. Now renders all
  layers through the Qt painter pipeline into an offscreen `QPixmap` at doc resolution
  (temporarily `_scale=1, _ox=0, _oy=0`). Tints, color grades, and rotations all survive
  grain being turned up
- `compose_to_pil()` had the same bug — now calls `_get_pix(l)` and converts back to PIL
  for export, so export matches exactly what is displayed on canvas

**Issue 8 — Bounding box handle jitter (`previewCanvas.py`)**

Root cause: `int()` truncation in `_c2w`. When `l.x * scale + ox` is e.g. `147.7`,
`int()` floors it to `147`. TL and BR are truncated independently, so rect dimensions
oscillate by 1px per frame.

- `_c2w_f(x, y) → QPointF` — new sub-pixel transform with no `int()` truncation
- `_layer_wrect_f(l) → QRectF` — float bounding rect used for all drawing and hit-testing
- Handle squares drawn as `QRectF` — eliminates the last truncation point at draw time
- Integer versions kept for operations that genuinely require `QRect` (clipping regions)
- `QPointF` and `QRectF` added to top-level imports (fixes Pylance `reportUndefinedVariable`
  warnings on lines 381 and 393)

### Added

- **`.sgeproj` project format** (`app/services/projectIO.py`) — new save/load system:
  - ZIP archive containing `project.json` (all state + layer metadata) and
    `assets/layer_NNNN.png` (lossless RGBA PNG per image-bearing layer)
  - Text, group, vector, fill, and clone layers carry no asset file — metadata only
  - Atomic write: saves to `.tmp` then `os.replace()` — crash mid-save never corrupts
    the existing file
  - `save_project(tab, path)` — serialises canvas layers and `AppState` into the ZIP
  - `load_project(tab, path)` — validates `format_version`, rebuilds layers, restores
    `AppState`, refreshes all UI controls, clears undo history and caches
  - `autosave(tab)` — writes to `DATA_DIR/autosave/<game>_autosave.sgeproj` silently;
    never raises
  - Format version `2`; files from future versions rejected with a clear error message

- **Project file management in File menu** (`mainWindow.py`):
  - New Project (`Ctrl+N`), Open Project… (`Ctrl+O`), Save Project (`Ctrl+S`),
    Save Project As… (`Ctrl+Shift+S`)
  - "Open Image" shortcut moved to `Ctrl+Shift+O` to free `Ctrl+O`
  - `_project_path` and `_project_dirty` track current file state
  - `_mark_dirty()` connected to `canvas.layers_changed` and
    `editor_panel.settings_changed` — any edit sets the dirty flag
  - `_update_title()` shows `Steam Grunge Editor — project.sgeproj •` (bullet when unsaved)
  - `_confirm_discard()` shows Save / Discard / Cancel before any destructive action
  - `closeEvent()` guards against quitting with unsaved work
  - Autosave timer fires every 5 minutes, but only writes when `_project_dirty` is true

---

## [1.1.0] — 2026-03-09

### Fixed

**Steam Sync — artwork now appears immediately without restarting Steam**

The sync pipeline was rewritten from scratch after a multi-stage debugging process.
The root cause was that Steam's new CEF-based library UI (introduced ~2022) renders
covers from `appcache/librarycache/<appid>/` and ignores `userdata/.../grid/` until
that cache is replaced. Previous versions only wrote to `grid/`.

Changes made:
- Sync now writes to **both** `userdata/<steamid>/config/grid/` (permanent PNG override)
  and `appcache/librarycache/<appid>/` (JPEG, forces immediate UI refresh)
- Correct Steam librarycache filenames used: `library_600x900.jpg`, `header.jpg`,
  `library_hero.jpg`, `logo.png`, `icon.jpg` (new subfolder structure)
- Steam root detection resolves symlinks to avoid writing to the wrong path
- Steam IPC reload now uses `O_NONBLOCK` pipe write in a daemon thread with a 2s
  timeout — prevents the app from freezing/crashing if Steam's pipe is not ready
- Sync dialog now **always re-exports the current canvas** before syncing,
  so edits made after a previous export are never missed
- Fixed `ddef` typo in `_open_sync_dialog` that caused a syntax error on some runs
- All sync operations now use `tab.state` instead of the global `state` singleton,
  so multi-tab workflows work correctly
- `_export_all_assets` now also stores each template path in `tab.state.export_paths`
  so Export All → Sync works without manual re-export
- Clarified `vhs_cover` filename — it maps to `{id}.png` (portrait cover slot),
  same as `cover`, not `{id}p.png` (wide slot). Both files now agree on this.
- Fixed stale "Found" label in sync dialog — now updates correctly when the user
  picks a different game from the candidate dropdown
- Success message updated: no longer says "restart Steam" since artwork appears
  immediately via the librarycache write

### Added

- **Left panel scrollbar** — the search/results/filters section of the left panel
  now lives in a `QScrollArea` and shows a slim scrollbar when the window is too
  short to display all controls (laptop-friendly). The artwork grid remains fixed
  below and is always fully visible.
- `state.export_paths` dict tracks the exact file path of every export per template,
  scoped per tab. Used by Sync to always install the correct file.
- Debug logging in sync: prints exact source path and destination path for every
  file copied, making mismatches easy to spot.

---

## [1.0.0] — 2026-03-08

### Initial release

- Visual editor for Steam library artwork (cover, wide, hero, logo, icon)
- SteamGridDB integration with search, filters, and pagination
- Layer system with blend modes, opacity, drag/resize, crop
- Templates: Cover (600×900), Wide (920×430), VHS Cover, VHS Pile, VHS Cassette,
  Hero (3840×1240), Logo (1280×720), Icon (512×512)
- Film grain, chromatic aberration, VHS scanlines, color grading effects
- Brush and eraser tools with custom brush import (ZIP packs, individual files)
- Font import and text layers
- Multi-tab workflow
- Export single asset or all assets at once
- Sync to Steam dialog with automatic AppID lookup via Steam Store API
- Packages: AppImage, .deb, Windows installer (.exe), macOS .dmg