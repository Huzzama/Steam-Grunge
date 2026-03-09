# Changelog

All notable changes to Steam Grunge Editor are documented here.

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