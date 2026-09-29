from __future__ import annotations
from typing import Optional, Tuple


class AppState:
    """All document-level settings for one tab.  No Qt objects, no signals."""

    def __init__(self):
        # ── Game / project identity ───────────────────────────────────────
        self.selected_game_name: str            = ""

        self.confirmed_app_id:   Optional[int]  = None
        self.confirmed_app_name: str            = ""

        # ── Canvas / template ─────────────────────────────────────────────
        self.current_template: str              = "cover"
        self.bg_color:         Tuple[int,...]   = (0, 0, 0)

        # ── Global effects (post-processing on the whole composite) ───────
        self.film_grain:            float = 20.0
        self.chromatic_aberration:  float = 10.0

        # ── Platform bar ──────────────────────────────────────────────────
        self.show_platform_bar: bool = True
        self.platform_bar_name: str  = "none"

        # ── Export paths (ephemeral, not persisted) ───────────────────────
        self.export_paths: dict = {}

        # ── Font / brush selection (ephemeral, not persisted) ─────────────
        self.font_selected: str = ""

    def reset_filters(self):
        """Return every global effect / colour value to its default."""
        d = AppState()
        for k in ("film_grain", "chromatic_aberration"):
            setattr(self, k, getattr(d, k))
