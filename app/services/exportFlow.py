"""
app/services/exportFlow.py

Central export entry point used by ALL export paths:
  - Editor panel "Export Image" button
  - File → Export menu
  - Sync to Steam button

Flow
----
1. Check if tab.state already has a confirmed_app_id for the current game.
2. If not (or if game changed), show AppIdConfirmDialog.
3. On confirm, cache app_id + canonical name in tab.state.
4. Export canvas to file using correct Steam filename convention.
5. Return the saved path (caller can then open Sync dialog if desired).

If the user cancels the confirm dialog, export is aborted (returns None).
"""
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.ui.tabManager import WorkspaceTab


# ── filename suffix map ────────────────────────────────────────────────────────
_SUFFIX: dict[str, str] = {
    "cover":        "{appid}.png",
    "vhs_cover":    "{appid}p.png",
    "wide":         "{appid}p.png",
    "vhs_pile":     "{appid}p.png",    # wide format → same p suffix
    "vhs_cassette": "{appid}p.png",    # wide format → same p suffix
    "hero":         "{appid}_hero.png",
    "logo":         "{appid}_logo.png",
    "icon":         "{appid}_icon.png",
}

from app.config import (
    EXPORT_COVER, EXPORT_WIDE, EXPORT_HERO, EXPORT_LOGO, EXPORT_ICON,
    TRANSPARENT_TEMPLATES,
)

_FOLDER: dict[str, str] = {
    "cover":        EXPORT_COVER,
    "vhs_cover":    EXPORT_COVER,
    "wide":         EXPORT_WIDE,
    "vhs_pile":     EXPORT_WIDE,
    "vhs_cassette": EXPORT_WIDE,
    "hero":         EXPORT_HERO,
    "logo":         EXPORT_LOGO,
    "icon":         EXPORT_ICON,
}


def run_export_flow(tab: "WorkspaceTab", parent_widget=None) -> Optional[str]:
    """
    Run the full export flow for the given tab.

    Returns the saved file path on success, or None if cancelled / nothing to export.
    """
    from PySide6.QtWidgets import QMessageBox, QDialog

    # 1. Compose canvas
    final = tab.preview_canvas.compose_to_pil()
    if final is None:
        QMessageBox.warning(parent_widget, "Export",
                            "Nothing to export yet.\nAdd artwork to the canvas first.")
        return None

    # 2. AppID confirmation — skip if already confirmed for this game
    app_id = _get_or_confirm_app_id(tab, parent_widget)
    if app_id is None:
        return None   # user cancelled

    # 3. Build output filename
    tpl         = tab.state.current_template
    suffix_tpl  = _SUFFIX.get(tpl, "{appid}.png")
    filename    = suffix_tpl.format(appid=app_id)
    folder      = _FOLDER.get(tpl, EXPORT_COVER)

    import os
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, filename)

    # 4. Save — RGBA for transparent templates, RGB otherwise
    try:
        if tpl in TRANSPARENT_TEMPLATES:
            final.convert("RGBA").save(out_path, "PNG")
        else:
            final.convert("RGB").save(out_path, "PNG")
    except Exception as e:
        QMessageBox.critical(parent_widget, "Export Error", f"Failed to save:\n{e}")
        return None

    return out_path


def _get_or_confirm_app_id(tab: "WorkspaceTab", parent_widget) -> Optional[int]:
    """
    Return the confirmed AppID for this tab's current game.
    Shows the confirmation dialog if:
      - No AppID has been confirmed yet, OR
      - The game has changed since last confirmation.
    """
    from PySide6.QtWidgets import QDialog
    state = tab.state

    # Cache is valid if confirmed_app_id exists AND game name hasn't changed
    current_name = (state.selected_game_name or "").strip().lower()
    cached_name  = (state.confirmed_app_name or "").strip().lower()

    if state.confirmed_app_id is not None and current_name == cached_name and current_name:
        return state.confirmed_app_id

    # Need to (re-)confirm
    game_name = state.selected_game_name or ""
    if not game_name:
        # No game loaded — ask user to search manually with empty dialog
        game_name = ""

    from app.ui.appIdConfirmDialog import AppIdConfirmDialog
    dlg = AppIdConfirmDialog(game_name=game_name, parent=parent_widget)
    if dlg.exec() != QDialog.Accepted:
        return None   # user cancelled

    # Cache result in tab state
    state.confirmed_app_id   = dlg.result_app_id
    state.confirmed_app_name = dlg.result_name
    return state.confirmed_app_id


def invalidate_app_id_cache(tab: "WorkspaceTab"):
    """
    Call this whenever the user selects a different game in the tab.
    Forces re-confirmation on next export.
    """
    tab.state.confirmed_app_id   = None
    tab.state.confirmed_app_name = ""