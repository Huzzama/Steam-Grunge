"""
canvas/layers.py  —  Layer dataclass definition.
All layer kinds, fields, and convenience properties live here.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

from PySide6.QtCore import QRect
from PySide6.QtGui  import QPixmap


# ── Layer ──────────────────────────────────────────────────────────────────────
@dataclass
class Layer:
    """
    Unified layer dataclass.
    kind: "paint" | "group" | "clone" | "vector" | "filter" | "fill" |
          "file" | "mask_transparency" | "mask_filter" | "mask_colorize" |
          "mask_transform" | "mask_selection" | "image" | "texture" | "text"
    (image/texture/text kept for back-compat)
    """
    kind:        str                            # see above
    name:        str   = "Layer"
    visible:     bool  = True
    locked:      bool  = False
    x:           int   = 0
    y:           int   = 0
    w:           int   = 200
    h:           int   = 200

    # ── Image / paint / file / texture ──────────────────────────────────────
    pil_image:   Optional[object] = None        # PIL Image
    source_path: str   = ""
    rotation:    float = 0.0        # degrees
    flip_h:      bool  = False
    flip_v:      bool  = False
    blend_mode:  str   = "normal"
    crop_l:      int   = 0
    crop_t:      int   = 0
    crop_r:      int   = 0
    crop_b:      int   = 0

    # ── Text ────────────────────────────────────────────────────────────────
    text:              str   = ""
    font_name:         str   = "default"
    font_size:         int   = 48
    font_color:        Tuple[int,int,int] = (255, 255, 255)
    font_bold:         bool  = False
    font_italic:       bool  = False
    font_uppercase:    bool  = False
    text_align:        str   = "left"
    letter_spacing:    int   = 0
    text_orientation:  str   = "horizontal"
    outline_size:      int   = 0
    outline_color:     Tuple[int,int,int] = (0, 0, 0)
    shadow_offset:     int   = 0
    shadow_color:      Tuple[int,int,int] = (0, 0, 0)

    # ── Shared color adjustments ─────────────────────────────────────────────
    opacity:        float = 1.0
    brightness:     float = 50.0
    contrast:       float = 50.0
    saturation:     float = 50.0
    tint_color:     Optional[Tuple[int,int,int]] = None
    tint_strength:  float = 0.0

    # ── Group layer ─────────────────────────────────────────────────────────
    group_collapsed: bool = False
    children:        List[int] = field(default_factory=list)

    # ── Clone layer ─────────────────────────────────────────────────────────
    clone_source_idx: int = -1

    # ── Vector layer ────────────────────────────────────────────────────────
    vector_paths:    List[dict] = field(default_factory=list)
    vector_stroke:   Tuple[int,int,int] = (255, 255, 255)
    vector_fill:     Tuple[int,int,int] = (255, 255, 255)
    vector_stroke_w: float = 2.0

    # ── Filter layer ────────────────────────────────────────────────────────
    filter_type:     str   = ""
    filter_params:   dict  = field(default_factory=dict)

    # ── Fill layer ──────────────────────────────────────────────────────────
    fill_type:       str   = "solid"
    fill_color:      Tuple[int,int,int] = (0, 0, 0)
    fill_color2:     Tuple[int,int,int] = (255, 255, 255)
    fill_angle:      float = 0.0

    # ── Mask layers ─────────────────────────────────────────────────────────
    mask_target_idx: int   = -1
    mask_mode:       str   = "alpha"
    mask_color:      Tuple[int,int,int] = (255, 255, 255)
    mask_feather:    float = 0.0

    # ── Transform mask ─────────────────────────────────────────────────────
    transform_scale_x: float = 1.0
    transform_scale_y: float = 1.0
    transform_rotate:  float = 0.0
    transform_tx:      int   = 0
    transform_ty:      int   = 0

    _pix: Optional[QPixmap] = field(default=None, repr=False, compare=False)

    def invalidate(self): self._pix = None

    @property
    def rect(self): return QRect(self.x, self.y, self.w, self.h)

    @property
    def is_image_like(self) -> bool:
        return self.kind in ("paint", "image", "texture", "file", "fill",
                             "mask_transparency", "mask_colorize", "mask_selection")