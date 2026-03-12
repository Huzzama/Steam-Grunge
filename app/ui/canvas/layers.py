"""
canvas/layers.py  —  Single canonical Layer definition for Steam Grunge Editor.

ALL other files must import Layer from here:
    from app.ui.canvas.layers import Layer

Do NOT define a Layer class anywhere else (especially not in previewCanvas.py).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

from PySide6.QtCore import QRect
from PySide6.QtGui  import QPixmap


@dataclass
class Layer:
    """
    Unified layer dataclass.
    kind: "paint" | "group" | "clone" | "vector" | "filter" | "fill" |
          "file" | "mask_transparency" | "mask_filter" | "mask_colorize" |
          "mask_transform" | "mask_selection" | "image" | "texture" | "text"
    (image/texture/text kept for back-compat)
    """
    kind:        str
    name:        str   = "Layer"
    visible:     bool  = True
    locked:      bool  = False
    x:           int   = 0
    y:           int   = 0
    w:           int   = 200
    h:           int   = 200

    # Image / paint / file / texture
    pil_image:   Optional[object] = None        # PIL Image
    source_path: str   = ""
    rotation:    float = 0.0
    flip_h:      bool  = False
    flip_v:      bool  = False
    blend_mode:  str   = "normal"
    crop_l:      int   = 0
    crop_t:      int   = 0
    crop_r:      int   = 0
    crop_b:      int   = 0

    # Text
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

    # Shared color adjustments
    opacity:        float = 1.0
    brightness:     float = 50.0
    contrast:       float = 50.0
    saturation:     float = 50.0
    tint_color:     Optional[Tuple[int,int,int]] = None
    tint_strength:  float = 0.0

    # Group
    group_collapsed: bool = False
    children:        List[int] = field(default_factory=list)

    # Clone
    clone_source_idx: int = -1

    # Vector
    vector_paths:    List[dict] = field(default_factory=list)
    vector_stroke:   Tuple[int,int,int] = (255, 255, 255)
    vector_fill:     Tuple[int,int,int] = (255, 255, 255)
    vector_stroke_w: float = 2.0

    # Filter
    filter_type:     str   = ""
    filter_params:   dict  = field(default_factory=dict)

    # Fill
    fill_type:       str   = "solid"
    fill_color:      Tuple[int,int,int] = (0, 0, 0)
    fill_color2:     Tuple[int,int,int] = (255, 255, 255)
    fill_angle:      float = 0.0

    # Mask
    mask_target_idx: int   = -1
    mask_mode:       str   = "alpha"
    mask_color:      Tuple[int,int,int] = (255, 255, 255)
    mask_feather:    float = 0.0

    # Transform mask
    transform_scale_x: float = 1.0
    transform_scale_y: float = 1.0
    transform_rotate:  float = 0.0
    transform_tx:      int   = 0
    transform_ty:      int   = 0

    # QPixmap render cache
    _pix: Optional[QPixmap] = field(default=None, repr=False, compare=False)

    # Granular dirty flags:
    #   _pix_dirty       — pixel content/colour adjustments changed; needs PIL rebuild.
    #   _transform_dirty — position/size/rotation changed; _pix is still valid.
    _pix_dirty:       bool = field(default=True,  repr=False, compare=False)
    _transform_dirty: bool = field(default=False, repr=False, compare=False)

    # ── Cache management ────────────────────────────────────────────────────

    def invalidate(self):
        """Full pixel rebuild — clears _pix and marks both dirty flags."""
        self._pix             = None
        self._pix_dirty       = True
        self._transform_dirty = True

    def invalidate_transform(self):
        """
        Geometry-only invalidation (move/resize/rotate).
        Keeps _pix intact — no expensive PIL rebuild needed.
        """
        self._transform_dirty = True

    def mark_clean(self):
        """Called by _get_pix after successfully rebuilding the QPixmap cache."""
        self._pix_dirty       = False
        self._transform_dirty = False

    # ── Convenience properties ──────────────────────────────────────────────

    @property
    def rect(self) -> QRect:
        return QRect(self.x, self.y, self.w, self.h)

    @property
    def is_image_like(self) -> bool:
        return self.kind in (
            "paint", "image", "texture", "file", "fill",
            "mask_transparency", "mask_colorize", "mask_selection",
        )

    def clone_for_duplicate(self, offset: int = 20) -> "Layer":
        """
        Return a safe duplicate suitable for the Duplicate Layer action.

        Rules:
        - Every logical / data field is copied by value.
        - PIL image content is cloned via .copy() so the two layers share no
          pixel buffer.  list/dict fields get shallow copies.
        - Runtime-only Qt state (_pix, dirty flags) is deliberately NOT copied;
          the clone starts fresh and rebuilds on first paint.
        - Position is offset by `offset` px in both axes so the copy is
          immediately visible and distinguishable from its source.
        """
        import copy as _copy

        new = Layer(
            kind=self.kind, name=self.name + " copy",
            visible=self.visible, locked=False,
            x=self.x + offset, y=self.y + offset,
            w=self.w, h=self.h,
            source_path=self.source_path,
            rotation=self.rotation, flip_h=self.flip_h, flip_v=self.flip_v,
            blend_mode=self.blend_mode,
            crop_l=self.crop_l, crop_t=self.crop_t,
            crop_r=self.crop_r, crop_b=self.crop_b,
            text=self.text, font_name=self.font_name, font_size=self.font_size,
            font_color=self.font_color, font_bold=self.font_bold,
            font_italic=self.font_italic, font_uppercase=self.font_uppercase,
            text_align=self.text_align, letter_spacing=self.letter_spacing,
            text_orientation=self.text_orientation,
            outline_size=self.outline_size, outline_color=self.outline_color,
            shadow_offset=self.shadow_offset, shadow_color=self.shadow_color,
            opacity=self.opacity,
            brightness=self.brightness, contrast=self.contrast,
            saturation=self.saturation,
            tint_color=self.tint_color, tint_strength=self.tint_strength,
            group_collapsed=self.group_collapsed,
            children=list(self.children),
            clone_source_idx=self.clone_source_idx,
            vector_paths=[_copy.copy(p) for p in self.vector_paths],
            vector_stroke=self.vector_stroke, vector_fill=self.vector_fill,
            vector_stroke_w=self.vector_stroke_w,
            filter_type=self.filter_type, filter_params=dict(self.filter_params),
            fill_type=self.fill_type, fill_color=self.fill_color,
            fill_color2=self.fill_color2, fill_angle=self.fill_angle,
            mask_target_idx=self.mask_target_idx, mask_mode=self.mask_mode,
            mask_color=self.mask_color, mask_feather=self.mask_feather,
            transform_scale_x=self.transform_scale_x,
            transform_scale_y=self.transform_scale_y,
            transform_rotate=self.transform_rotate,
            transform_tx=self.transform_tx, transform_ty=self.transform_ty,
        )
        # Clone PIL pixel data so buffers are independent
        if self.pil_image is not None:
            try:
                new.pil_image = self.pil_image.copy()
            except Exception:
                new.pil_image = None
        else:
            new.pil_image = None
        # Qt cache rebuilt fresh — never copy _pix
        new._pix = None
        new._pix_dirty = True
        new._transform_dirty = True
        return new