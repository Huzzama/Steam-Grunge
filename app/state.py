"""
app/state.py  —  Per-tab document state for Steam Grunge Editor.

Each WorkspaceTab owns one AppState instance.
This is the declarative authority for document-level settings.

PreviewCanvas owns runtime/interactive state (layers, transforms, selection).
WorkspaceTab._do_compose() bridges AppState → PreviewCanvas each tick.
"""
from __future__ import annotations
from typing import Optional, Tuple
from PIL import Image as PILImage


class AppState:
    """All document-level settings for one tab.  No Qt objects, no signals."""

    def __init__(self):
        # ── Game / project identity ───────────────────────────────────────
        self.selected_game_name: str            = ""
        self.base_image:         Optional[PILImage.Image] = None

        # Confirmed Steam identity — persisted in .sgeproj.
        # confirmed_app_id is the PRIMARY export authority once set.
        # confirmed_app_name is informational only (not used as a gate).
        self.confirmed_app_id:   Optional[int]  = None
        self.confirmed_app_name: str            = ""

        # ── Canvas / template ─────────────────────────────────────────────
        self.current_template: str              = "cover"
        self.bg_color:         Tuple[int,...]   = (0, 0, 0)

        # ── Global filter values ──────────────────────────────────────────
        self.film_grain:            float = 20.0
        self.chromatic_aberration:  float = 10.0
        self.scratches:             float = 30.0
        self.dust:                  float = 20.0
        self.edge_wear:             float = 25.0
        self.vhs_scanlines:         float = 0.0
        self.brightness:            float = 50.0
        self.contrast:              float = 50.0
        self.saturation:            float = 50.0
        self.tint_color:            Optional[Tuple[int,...]] = None
        self.deterioration_preset:  str   = "none"

        # ── Platform bar / spine ──────────────────────────────────────────
        self.show_platform_bar: bool = True
        self.platform_bar_name: str  = "none"
        self.show_spine:        bool = True
        self.spine_text:        str  = ""

        # ── Export paths (ephemeral, not persisted) ───────────────────────
        # Maps template key → absolute path of the most recently exported PNG.
        # Written by mainWindow after each successful export so the Sync
        # dialog can find the file without re-exporting.
        # Default is an empty dict; keys are added on demand.
        self.export_paths: dict = {}

        # ── Font / brush selection (ephemeral, not persisted) ─────────────
        self.font_selected: str = ""


# ── Module-level singleton ────────────────────────────────────────────────────
# Kept for backward compatibility with any code that does:
#   from app.state import state
# New code should use per-tab AppState instances (tab.state) instead.
state = AppState()