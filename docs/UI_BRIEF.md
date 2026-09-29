# Steam Grunge Editor — UI polish brief (read before touching a panel)

Goal: keep the "cyber-sigil" identity (near-black blue-tinted surfaces, sky
accent `#38bdf8`, Courier New, tight radii) but make it feel finished: nothing
overlaps, nothing is clipped, every control is the same height, side panels
open fully extended, no emoji / unicode glyph icons.

## Hard rules

1. **No `setStyleSheet` in panels/dialogs.** Everything comes from
   `app/ui/theme.py` through dynamic properties:
   - `QLabel` → `setProperty("role", …)`: `title · section · eyebrow · body ·
     dim · muted · value · mono`; optional `tone`: `accent · green · red · gold`.
   - `QPushButton` → `variant`: `default · primary · success · danger · ghost ·
     link · icon · tool · chip · template`; `active="true"` for the selected one.
   - `QFrame` → `surface`: `panel · card · inset · divider · strip`.
   After changing a property at runtime call `theme.repolish(widget)`.
   Use `app.ui.kit` (`label`, `Button`, `IconButton`, `Section`, `SubHeader`,
   `SliderRow`, `ColorSwatch`, `SpinRow`, `ChipRow`, `EmptyState`, `Divider`,
   `vbox/hbox/grid`) instead of raw widgets wherever it fits.
   Colours only via `theme.C[...]` (for QPainter code); spacing via `SP`.
2. **No `QFont(...)` / `setFont` / `setBold`** in panels — roles handle it.
   `QGroupBox` is legacy: replace with `kit.Section`.
3. **No emoji or glyph icons** (`✦ ⚙ ✓ ✗ ▲ ▼ ◀ ▶ ⟲ ↔ ↕ ✎ ⚠ ● ★ ☁ 🔒 📁 💾 …`).
   Use `app.ui.icons` (`icons.icon(name, color, size)` for buttons,
   `icons.pixmap(...)` for labels; 165 Lucide names — see `ICONS`/`ALIASES`
   in `app/ui/icons.py`; e.g. `type, brush, paintbrush, folder, save,
   flip-horizontal, flip-vertical, rotate-cw, rotate-ccw, lock, lock-open, copy,
   trash, eye, eye-off, arrow-up, arrow-down, undo-2, redo-2, move, layers,
   image, image-plus, palette, pipette, text-align-start/center/end, bold,
   italic, zoom-in, zoom-out, cloud-upload, cloud-download, key-round, search,
   settings, upload, download, check, x, plus, minus, chevron-*, external-link,
   refresh-cw, loader-circle, triangle-alert, circle-check, info`).
4. **Every control is `theme.CONTROL_H` (28 px) tall**; rows are `hbox` with
   `SP["sm"]` spacing; sections are `kit.Section` (collapsible) with
   `SubHeader` inside for sub-groups; sliders are `SliderRow` (label · value ·
   reset in one row, slider below — never label/value on the same line as the
   slider).
5. **Widths are responsive.** The panels are 300–400 px (search) and 360–500 px
   (editor). Nothing may use `setFixedWidth` larger than ~120 px; use
   `QGridLayout` / `FlowLayout`-style rows that wrap instead of a single row of
   4 combos; long labels use `kit.label(..., elide=True)`.
6. **Keep every signal, slot, attribute name and public method** the rest of
   the app uses (`grep -rn "editor_panel\.\|search_panel\." app/ui app/main.py`
   before renaming anything). Behaviour must not change — this is a layout /
   styling pass, plus the bugs listed below.
7. Screenshot check before you finish:
   `QT_QPA_PLATFORM=offscreen python3 tools/shot.py <target> /tmp/gshots/x.png`
   targets: `window · search · editor · editor-text · editor-image · editor-paint ·
   dialog:preferences · dialog:about · dialog:sync · dialog:appid · dialog:drive ·
   dialog:shortcuts`. Open the PNG with the Read tool and fix what is clipped,
   overlapping or misaligned. Test at `--size 1200x700` too (the minimum is
   1000×650).
8. Files stay LF. `python3 -m compileall -q app` must pass, and
   `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` must stay green.

## Known layout bugs (from the screenshots)

- Search panel: the top block (title, API key, search field, results,
  filters) sits in a fixed-height area and gets cut off at ~330 px; the
  4-column filter row (Type / Style / Size / NSFW) is clipped and overlapped
  by the ARTWORK label; the title/labels render pseudo-bold and blurry.
- Editor panel: contents wider than the panel at 400 px (combo arrows and
  the right border clipped), one giant `_build_ui` with QGroupBoxes; the
  TEMPLATES list takes 380 px of height; "APPLY TO STEAM" and "Export PNG
  only" are lost at the bottom of a very long scroll.
- Glyph icons everywhere (`✦`, `⚙`, `↔ Flip H`, `↕ Flip V`, `⟲`, `▲ ▼`,
  `DUP VIS 🔒 DEL` text buttons, `◀ ▶` pager, `✓`/`✗` status).
