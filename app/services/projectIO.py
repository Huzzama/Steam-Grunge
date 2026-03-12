"""
projectIO.py  —  Save / Load for the .sgeproj project format.

.sgeproj is a ZIP archive containing:
  project.json          — all state, layer metadata, canvas settings, version tag
  assets/layer_N.png    — pixel data for each layer that carries a PIL image
                          (image, paint, texture, file, fill, mask_* kinds)

The canvas runtime state (Qt pixmap cache, undo history, selection index) is
NOT persisted — it is cheap to rebuild on load.

Public API
──────────
  save_project(tab, path)   → None   raises ProjectIOError on failure
  load_project(tab, path)   → None   raises ProjectIOError on failure

  SGEPROJ_EXT  = ".sgeproj"
  FORMAT_VER   = 2
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from typing import TYPE_CHECKING, Optional

from PIL import Image as PILImage

if TYPE_CHECKING:
    from app.ui.tabManager import WorkspaceTab

# ── Constants ─────────────────────────────────────────────────────────────────
SGEPROJ_EXT = ".sgeproj"
FORMAT_VER  = 2          # bump when the schema changes in a breaking way

# Layer fields that are purely metadata (no pixel data) — serialised as-is
_META_FIELDS = [
    "kind", "name", "visible", "locked",
    "x", "y", "w", "h",
    "rotation", "flip_h", "flip_v", "blend_mode",
    "crop_l", "crop_t", "crop_r", "crop_b",
    "text", "font_name", "font_size", "font_color",
    "font_bold", "font_italic", "font_uppercase",
    "text_align", "letter_spacing", "text_orientation",
    "outline_size", "outline_color",
    "shadow_offset", "shadow_color",
    "opacity", "brightness", "contrast", "saturation",
    "tint_color", "tint_strength",
    "group_collapsed", "children", "clone_source_idx",
    "vector_paths", "vector_stroke", "vector_fill", "vector_stroke_w",
    "filter_type", "filter_params",
    "fill_type", "fill_color", "fill_color2", "fill_angle",
    "mask_target_idx", "mask_mode", "mask_color", "mask_feather",
    "transform_scale_x", "transform_scale_y", "transform_rotate",
    "transform_tx", "transform_ty",
    "source_path",
]


class ProjectIOError(Exception):
    """Raised when save or load fails for any expected reason."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _layer_to_dict(layer, asset_key: Optional[str]) -> dict:
    """Serialise one Layer to a plain dict.  asset_key is stored when there is pixel data."""
    d: dict = {}
    for field in _META_FIELDS:
        val = getattr(layer, field, None)
        # Tuples aren't JSON-native but lists round-trip fine
        if isinstance(val, tuple):
            val = list(val)
        d[field] = val
    d["asset_key"] = asset_key   # None for text/group/vector/fill layers
    return d


def _dict_to_layer(d: dict, pil_image: Optional[PILImage.Image]):
    """Rebuild a Layer from a serialised dict + optional PIL image."""
    from app.ui.canvas.layers import Layer

    # Convert list-encoded tuples back to proper tuples
    _tuple_fields = {
        "font_color", "outline_color", "shadow_color",
        "tint_color", "vector_stroke", "vector_fill",
        "fill_color", "fill_color2", "mask_color",
    }

    kwargs: dict = {}
    for field in _META_FIELDS:
        if field not in d:
            continue
        val = d[field]
        if field in _tuple_fields and isinstance(val, list):
            val = tuple(val)
        kwargs[field] = val

    layer = Layer(**{k: v for k, v in kwargs.items() if v is not None or k in (
        "tint_color",)})
    layer.pil_image = pil_image
    layer._pix = None   # rebuilt on next paintEvent
    return layer


# ── Public API ────────────────────────────────────────────────────────────────

def save_project(tab: "WorkspaceTab", path: str) -> None:
    """
    Serialise the WorkspaceTab's canvas layers + AppState into a .sgeproj ZIP.

    Raises ProjectIOError on any failure so callers can show a dialog instead
    of crashing.
    """
    if not path.endswith(SGEPROJ_EXT):
        path += SGEPROJ_EXT

    canvas = tab.preview_canvas
    st     = tab.state

    # ── Build layer metadata + collect pixel assets ────────────────────────
    layers_meta = []
    assets: dict[str, bytes] = {}     # asset_key → PNG bytes

    for idx, layer in enumerate(canvas.layers):
        has_pixels = (layer.pil_image is not None)
        asset_key  = f"assets/layer_{idx:04d}.png" if has_pixels else None

        if has_pixels:
            buf = io.BytesIO()
            # Always save as RGBA so we never lose transparency
            layer.pil_image.convert("RGBA").save(buf, "PNG", optimize=False)
            assets[asset_key] = buf.getvalue()

        layers_meta.append(_layer_to_dict(layer, asset_key))

    # ── Build project.json ─────────────────────────────────────────────────
    bg = getattr(st, "bg_color", (0, 0, 0))
    doc_size = canvas.doc_size()

    project: dict = {
        "format_version":  FORMAT_VER,
        "sge_version":     _get_app_version(),
        "game_name":       st.selected_game_name,
        "template":        st.current_template,
        "doc_size":        [doc_size.width(), doc_size.height()],
        "bg_color":        list(bg) if isinstance(bg, tuple) else bg,
        # Confirmed Steam identity — persisted so load → export skips re-confirmation
        "confirmed_app_id":   getattr(st, "confirmed_app_id",   None),
        "confirmed_app_name": getattr(st, "confirmed_app_name", ""),
        # AppState filter / colour settings
        "film_grain":           st.film_grain,
        "chromatic_aberration": st.chromatic_aberration,
        "scratches":            st.scratches,
        "dust":                 st.dust,
        "edge_wear":            st.edge_wear,
        "vhs_scanlines":        st.vhs_scanlines,
        "brightness":           st.brightness,
        "contrast":             st.contrast,
        "saturation":           st.saturation,
        "tint_color":           list(st.tint_color) if st.tint_color else None,
        "deterioration_preset": st.deterioration_preset,
        "show_platform_bar":    st.show_platform_bar,
        "platform_bar_name":    st.platform_bar_name,
        "show_spine":           st.show_spine,
        "spine_text":           st.spine_text,
        # Canvas layer stack
        "layers":               layers_meta,
        # Selection index — nice-to-have, non-critical
        "selected_layer_idx":   canvas.selected_layer_index(),
    }

    # ── Write ZIP ──────────────────────────────────────────────────────────
    try:
        tmp_path = path + ".tmp"
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr("project.json",
                        json.dumps(project, indent=2, ensure_ascii=False))
            for key, data in assets.items():
                zf.writestr(key, data)
        # Atomic replace — never leave a corrupt file if we crash mid-write
        os.replace(tmp_path, path)
    except Exception as exc:
        # Clean up temp file if it exists
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except OSError: pass
        raise ProjectIOError(f"Could not write project file:\n{exc}") from exc


def load_project(tab: "WorkspaceTab", path: str) -> None:
    """
    Load a .sgeproj file into an existing WorkspaceTab.

    Replaces the canvas layer stack, AppState, and refreshes all UI controls.
    Raises ProjectIOError on any failure.
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())

            if "project.json" not in names:
                raise ProjectIOError("Not a valid .sgeproj file: missing project.json")

            project = json.loads(zf.read("project.json"))

            # ── Validate format version ────────────────────────────────────
            ver = project.get("format_version", 1)
            if ver > FORMAT_VER:
                raise ProjectIOError(
                    f"This project was saved with a newer version of Steam Grunge Editor "
                    f"(format v{ver}).  Please update the app to open it."
                )

            # ── Rebuild layers ─────────────────────────────────────────────
            rebuilt_layers = []
            for ldata in project.get("layers", []):
                asset_key  = ldata.get("asset_key")
                pil_image  = None
                if asset_key and asset_key in names:
                    raw = zf.read(asset_key)
                    pil_image = PILImage.open(io.BytesIO(raw)).convert("RGBA")
                    pil_image.load()   # detach from BytesIO before it closes
                rebuilt_layers.append(_dict_to_layer(ldata, pil_image))

    except zipfile.BadZipFile as exc:
        raise ProjectIOError(f"File is not a valid .sgeproj archive:\n{exc}") from exc
    except ProjectIOError:
        raise
    except Exception as exc:
        raise ProjectIOError(f"Failed to load project:\n{exc}") from exc

    # ── Apply to canvas ────────────────────────────────────────────────────
    canvas = tab.preview_canvas
    st     = tab.state

    # Load the layer stack directly into the canvas internals here because
    # this is an I/O bootstrap operation (not a user action), and reorder_layers()
    # guards against count mismatches.  We do NOT push undo during load.
    # Interaction flags are reset first so no stale drag/resize state leaks.
    canvas._drag_active      = False
    canvas._resize_active    = False
    canvas._rotate_active    = False
    canvas._pan_active       = False
    canvas._hand_active      = False
    canvas._guides_active    = False
    canvas._crop_mode        = False
    canvas._crop_rect        = None
    canvas._crop_drag_handle = -1
    canvas._shape_drawing    = False

    # Clear caches before replacing layer stack
    canvas._fx_cache      = None
    canvas._fx_cache_key  = ()
    canvas._history.clear()
    canvas._redo_stack.clear()

    # Replace layer stack — direct assignment is acceptable here because
    # this is a project load (not a UI action). Push one clean history entry
    # after so undo doesn't go below the loaded state.
    canvas._layers = rebuilt_layers
    sel = project.get("selected_layer_idx", 0)
    canvas._sel = max(0, min(sel, len(rebuilt_layers) - 1)) if rebuilt_layers else -1

    # Invalidate per-layer pix caches so they rebuild from the freshly
    # loaded PIL images, not from any stale previous session data
    for layer in canvas._layers:
        layer._pix = None
        layer._pix_dirty = True
        layer._transform_dirty = False

    # ── Apply AppState ─────────────────────────────────────────────────────
    st.selected_game_name      = project.get("game_name", "")
    st.current_template        = project.get("template", "cover")
    # Restore confirmed Steam identity so load → export reuses the saved AppID
    # without forcing the user through the confirmation dialog again.
    st.confirmed_app_id        = project.get("confirmed_app_id",   None)
    st.confirmed_app_name      = project.get("confirmed_app_name", "")
    st.film_grain              = project.get("film_grain", 20.0)
    st.chromatic_aberration    = project.get("chromatic_aberration", 10.0)
    st.scratches               = project.get("scratches", 30.0)
    st.dust                    = project.get("dust", 20.0)
    st.edge_wear               = project.get("edge_wear", 25.0)
    st.vhs_scanlines           = project.get("vhs_scanlines", 0.0)
    st.brightness              = project.get("brightness", 50.0)
    st.contrast                = project.get("contrast", 50.0)
    st.saturation              = project.get("saturation", 50.0)
    st.deterioration_preset    = project.get("deterioration_preset", "none")
    st.show_platform_bar       = project.get("show_platform_bar", True)
    st.platform_bar_name       = project.get("platform_bar_name", "none")
    st.show_spine              = project.get("show_spine", True)
    st.spine_text              = project.get("spine_text", "")

    # export_paths is ephemeral — always start empty on load so stale
    # paths from a previous session are never accidentally reused.
    st.export_paths = {}

    tc = project.get("tint_color")
    st.tint_color = tuple(tc) if tc else None

    bg = project.get("bg_color", [0, 0, 0])
    st.bg_color = tuple(bg)

    # ── Refresh canvas visual settings ────────────────────────────────────
    from PySide6.QtGui import QColor
    canvas.set_template(st.current_template)
    canvas.set_background_color(QColor(*st.bg_color))
    canvas.update_effects_overlay(st.film_grain, st.chromatic_aberration)

    # ── Refresh editor panel UI controls ──────────────────────────────────
    ep = tab.editor_panel
    ep.refresh_from_state()
    ep._refresh_layer_list()
    if rebuilt_layers and canvas._sel >= 0:
        ep._on_canvas_layer_selected(canvas._sel)

    # ── Wipe FX cache SYNCHRONOUSLY before the first paint ────────────────
    # update_effects_overlay() above may have queued a new FX cache rebuild.
    # We must clear it here — before canvas.update() — so the very first
    # repaint after load starts clean and the selection overlay is never
    # hidden by a stale composite from the previous session.
    canvas._fx_cache     = None
    canvas._fx_cache_key = ()

    # ── Trigger a recompose + immediate repaint ────────────────────────────
    tab.schedule_compose()
    canvas.layers_changed.emit()
    canvas.update()

    # ── Deferred: restore focus + re-emit selection ───────────────────────
    # A zero-delay QTimer fires after the current event loop cycle, by which
    # point all panel refreshes and the first repaint have settled.  We then
    # emit layer_selected again so the editor panel and floating toolbar
    # update their state to match the freshly painted canvas.
    from PySide6.QtCore import QTimer

    def _restore_focus_and_selection():
        canvas.setFocus()
        # Clear FX cache once more in case schedule_compose() rebuilt it
        # during the event-loop cycle between the synchronous update and now.
        canvas._fx_cache     = None
        canvas._fx_cache_key = ()
        # Clamp sel in case a concurrent remove_layer() fired during load
        if canvas._layers:
            canvas._sel = max(0, min(canvas._sel, len(canvas._layers) - 1))
        else:
            canvas._sel = -1
        if canvas._sel >= 0:
            canvas.layer_selected.emit(canvas._sel)
        canvas.update()

    QTimer.singleShot(0, _restore_focus_and_selection)


# ── Autosave ──────────────────────────────────────────────────────────────────

def autosave_path(tab: "WorkspaceTab") -> str:
    """Return the autosave path for this tab (based on game name or tab id)."""
    from app.config import DATA_DIR
    autosave_dir = os.path.join(DATA_DIR, "autosave")
    os.makedirs(autosave_dir, exist_ok=True)
    name = tab.state.selected_game_name or f"tab_{tab.tab_id}"
    # Sanitise to a safe filename
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
    safe = safe.strip().replace(" ", "_")[:48] or "untitled"
    return os.path.join(autosave_dir, f"{safe}_autosave{SGEPROJ_EXT}")


def autosave(tab: "WorkspaceTab") -> None:
    """Silently write an autosave.  Never raises — errors are printed only."""
    try:
        save_project(tab, autosave_path(tab))
    except Exception as exc:
        print(f"[autosave] warning: {exc}")


# ── Internal ──────────────────────────────────────────────────────────────────

def _get_app_version() -> str:
    """Best-effort: read APP_VERSION from mainWindow module without importing Qt."""
    try:
        import importlib
        mw = importlib.import_module("app.ui.mainWindow")
        return getattr(mw, "APP_VERSION", "unknown")
    except Exception:
        return "unknown"