from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from PIL import Image


@dataclass
class AppState:
    # Search state
    search_query: str = ""
    search_results: List[Dict] = field(default_factory=list)

    # Selection state
    selected_game_id: Optional[int] = None
    selected_game_name: str = ""
    selected_artwork_url: Optional[str] = None
    base_image: Optional[Image.Image] = None

    # Template state
    current_template: str = "cover"  # "cover" | "vhs_cover" | "wide" | "hero" | "logo" | "icon"

    # Cover layout options
    show_platform_bar: bool = True
    platform_bar_name: str = "none"
    show_spine: bool = True
    spine_text: str = ""

    # Filter values (0-100)
    film_grain: float = 20.0
    chromatic_aberration: float = 10.0
    scratches: float = 30.0
    dust: float = 20.0
    edge_wear: float = 25.0
    vhs_scanlines: float = 0.0

    # Color adjustments
    brightness: float = 50.0
    contrast: float = 50.0
    saturation: float = 50.0
    tint_color: Optional[tuple] = None

    # Deterioration preset
    deterioration_preset: str = "none"

    # Layers
    layers: List[Dict[str, Any]] = field(default_factory=list)

    # Background color (RGB tuple)
    bg_color: tuple = (0, 0, 0)

    # Composed output
    composed_image: Optional[Image.Image] = None

    # Steam AppID cache — confirmed once per session per game
    confirmed_app_id:   Optional[int] = None   # set after user confirms
    confirmed_app_name: str = ""               # canonical name that was confirmed
    # If confirmed_app_name != selected_game_name → cache is stale, re-confirm

    def reset_filters(self):
        self.film_grain = 20.0
        self.chromatic_aberration = 10.0
        self.scratches = 30.0
        self.dust = 20.0
        self.edge_wear = 25.0
        self.vhs_scanlines = 0.0
        self.brightness = 50.0
        self.contrast = 50.0
        self.saturation = 50.0

    def to_dict(self) -> dict:
        return {
            "template": self.current_template,
            "platform_bar": self.platform_bar_name,
            "show_spine": self.show_spine,
            "spine_text": self.spine_text,
            "film_grain": self.film_grain,
            "chromatic_aberration": self.chromatic_aberration,
            "scratches": self.scratches,
            "dust": self.dust,
            "edge_wear": self.edge_wear,
            "vhs_scanlines": self.vhs_scanlines,
            "brightness": self.brightness,
            "contrast": self.contrast,
            "saturation": self.saturation,
            "deterioration_preset": self.deterioration_preset,
        }

    def from_dict(self, data: dict):
        self.current_template = data.get("template", "cover")
        self.platform_bar_name = data.get("platform_bar", "none")
        self.show_spine = data.get("show_spine", True)
        self.spine_text = data.get("spine_text", "")
        self.film_grain = data.get("film_grain", 20.0)
        self.chromatic_aberration = data.get("chromatic_aberration", 10.0)
        self.scratches = data.get("scratches", 30.0)
        self.dust = data.get("dust", 20.0)
        self.edge_wear = data.get("edge_wear", 25.0)
        self.vhs_scanlines = data.get("vhs_scanlines", 0.0)
        self.brightness = data.get("brightness", 50.0)
        self.contrast = data.get("contrast", 50.0)
        self.saturation = data.get("saturation", 50.0)
        self.deterioration_preset = data.get("deterioration_preset", "none")


# Singleton global state
state = AppState()