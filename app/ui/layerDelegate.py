from __future__ import annotations
from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from PySide6.QtCore    import Qt, QRect, QSize
from PySide6.QtGui     import QPainter, QColor, QPen, QFontMetrics, QPixmap

from app.ui import icons, theme
from app.ui.theme import C


def _rgb(hexv: str) -> tuple[int, int, int]:
    c = QColor(hexv)
    return (c.red(), c.green(), c.blue())


# layer kind -> (icon, colour)
KIND_ICONS: dict[str, tuple[str, str]] = {
    "paint":   ("paintbrush", C["accent"]),
    "image":   ("image",      C["accent"]),
    "file":    ("file-image", C["accent"]),
    "texture": ("sparkles",   C["violet"]),
    "text":    ("type",       C["gold"]),
    "bar":     ("gamepad-2",  C["green"]),
    "group":   ("folder",     C["gold"]),
    "fill":    ("droplet",    C["green"]),
}


class LayerDelegate(QStyledItemDelegate):
    # ── Data roles ───────────────────────────────────────────────────────────
    EYE_ROLE       = Qt.UserRole + 1
    KIND_ROLE      = Qt.UserRole + 2
    OPAC_ROLE      = Qt.UserRole + 3
    PIX_ROLE       = Qt.UserRole + 4
    LOCK_ROLE      = Qt.UserRole + 5
    INDENT_ROLE    = Qt.UserRole + 6
    COLLAPSED_ROLE = Qt.UserRole + 7
    DROP_ABOVE     = Qt.UserRole + 8
    DROP_INTO      = Qt.UserRole + 9

    ROW_H    = 44
    THUMB_W  = 38
    THUMB_H  = 34
    EYE_W    = 22
    INDENT_W = 16

    _checker_pix: QPixmap | None = None

    @classmethod
    def _get_checker(cls, w: int, h: int) -> QPixmap:
        if cls._checker_pix and cls._checker_pix.width() == w and cls._checker_pix.height() == h:
            return cls._checker_pix
        pix = QPixmap(w, h)
        p   = QPainter(pix)
        sq  = 5
        c1, c2 = QColor(C["text_muted"]), QColor(C["border_strong"])
        for ry in range(0, h, sq):
            for rx in range(0, w, sq):
                p.fillRect(rx, ry, sq, sq,
                           c1 if (rx // sq + ry // sq) % 2 == 0 else c2)
        p.end()
        cls._checker_pix = pix
        return cls._checker_pix

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_H)

    @staticmethod
    def _draw_icon(painter: QPainter, rect: QRect, name: str, color: str, size: int):
        pm = icons.pixmap(name, color, size)
        painter.drawPixmap(rect.x() + (rect.width() - size) // 2,
                           rect.y() + (rect.height() - size) // 2, pm)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        r          = option.rect
        selected   = bool(option.state & QStyle.State_Selected)
        visible    = bool(index.data(self.EYE_ROLE))
        kind       = (index.data(self.KIND_ROLE) or "paint").lower()
        indent     = int(index.data(self.INDENT_ROLE) or 0)
        is_group   = (kind == "group")
        collapsed  = bool(index.data(self.COLLAPSED_ROLE))
        drop_into  = bool(index.data(self.DROP_INTO))
        drop_above = bool(index.data(self.DROP_ABOVE))

        # ── Background ───────────────────────────────────────────────────────
        if selected:
            bg = QColor(C["accent_dim"])
        elif is_group:
            bg = QColor(C["gold_dim"])
        elif index.row() % 2 == 0:
            bg = QColor(C["bg_deep"])
        else:
            bg = QColor(C["bg"])
        painter.fillRect(r, bg)

        if drop_into:
            tint = QColor(C["accent"]); tint.setAlpha(50)
            painter.fillRect(r, tint)
            painter.setPen(QPen(QColor(C["accent"]), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(r.adjusted(1, 1, -1, -1))

        # ── Indent gutter ────────────────────────────────────────────────────
        if indent > 0:
            painter.fillRect(QRect(r.x(), r.y(), indent * self.INDENT_W, r.height()),
                             QColor(C["surface"]))
            painter.setPen(QPen(QColor(C["border_strong"]), 1))
            lx = r.x() + indent * self.INDENT_W - 1
            painter.drawLine(lx, r.top(), lx, r.bottom())

        x = r.x() + 3 + indent * self.INDENT_W

        # ── Eye ──────────────────────────────────────────────────────────────
        eye_rect = QRect(x, r.y() + (self.ROW_H - 18) // 2, 18, 18)
        if visible:
            self._draw_icon(painter, eye_rect, "eye", C["text"] if selected else C["text_2"], 14)
        else:
            self._draw_icon(painter, eye_rect, "eye-off", C["text_muted"], 14)
        x += self.EYE_W

        # ── Collapse arrow (groups only) ──────────────────────────────────────
        if is_group:
            arrow_rect = QRect(x, r.y() + (self.ROW_H - 14) // 2, 14, 14)
            self._draw_icon(painter, arrow_rect, "chevron-right" if collapsed else "chevron-down",
                            C["text_dim"], 12)
            x += 16
        else:
            x += 4

        # ── Thumbnail ────────────────────────────────────────────────────────
        tw, th     = self.THUMB_W, self.THUMB_H
        thumb_rect = QRect(x, r.y() + (self.ROW_H - th) // 2, tw, th)
        painter.drawPixmap(thumb_rect, self._get_checker(tw, th))
        thumb: QPixmap = index.data(self.PIX_ROLE)
        if thumb and not thumb.isNull():
            scaled = thumb.scaled(thumb_rect.size(), Qt.KeepAspectRatio,
                                  Qt.SmoothTransformation)
            px = thumb_rect.x() + (tw - scaled.width())  // 2
            py = thumb_rect.y() + (th - scaled.height()) // 2
            painter.drawPixmap(px, py, scaled)
        painter.setPen(QPen(QColor(C["accent"] if selected else C["border_strong"]), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(thumb_rect)
        x += tw + 5

        # ── Kind icon ────────────────────────────────────────────────────────
        icon_name, icon_col = KIND_ICONS.get(kind, ("square", C["text_dim"]))
        kind_rect = QRect(x, r.y() + (self.ROW_H - 18) // 2, 18, 18)
        self._draw_icon(painter, kind_rect, icon_name, icon_col, 14)
        x += 22

        # ── Name ─────────────────────────────────────────────────────────────
        name      = index.data(Qt.DisplayRole) or ""
        name_rect = QRect(x, r.y(), r.right() - x - 26, self.ROW_H)
        name_col  = (QColor(C["text"]) if selected else
                     QColor(C["gold"]) if is_group else
                     QColor(C["text_2"]))
        painter.setPen(name_col)
        painter.setFont(theme.font("base", bold=is_group))
        fm     = QFontMetrics(painter.font())
        elided = fm.elidedText(name, Qt.ElideRight, name_rect.width())
        painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

        # ── Opacity micro-bar ────────────────────────────────────────────────
        opacity = index.data(self.OPAC_ROLE)
        if opacity is not None:
            base_x   = r.x() + self.EYE_W + indent * self.INDENT_W + self.THUMB_W + 46
            bar_w    = max(4, r.right() - base_x - 26)
            bar_rect = QRect(base_x, r.bottom() - 3, bar_w, 2)
            painter.fillRect(bar_rect, QColor(C["border"]))
            filled = QRect(bar_rect.x(), bar_rect.y(),
                           int(bar_rect.width() * max(0., min(1., float(opacity)))),
                           bar_rect.height())
            painter.fillRect(filled, QColor(C["accent"] if selected else C["border_strong"]))

        # ── Lock badge ───────────────────────────────────────────────────────
        if bool(index.data(self.LOCK_ROLE)):
            lr = QRect(r.right() - 22, r.y() + (self.ROW_H - 16) // 2, 16, 16)
            self._draw_icon(painter, lr, "lock", C["gold"], 12)

        # ── Drop-above indicator ──────────────────────────────────────────────
        if drop_above:
            painter.setPen(QPen(QColor(C["accent"]), 2))
            painter.drawLine(r.left(), r.top() + 1, r.right(), r.top() + 1)

        # ── Row separator ────────────────────────────────────────────────────
        painter.setPen(QPen(QColor(C["border"]), 1))
        painter.drawLine(r.bottomLeft(), r.bottomRight())
        painter.restore()

    # ── Hit-test helpers ─────────────────────────────────────────────────────
    def eye_rect_for_row(self, row_rect: QRect, indent: int = 0) -> QRect:
        x = row_rect.x() + 3 + indent * self.INDENT_W
        return QRect(x, row_rect.y() + (self.ROW_H - 18) // 2, 18, 18)

    def arrow_rect_for_row(self, row_rect: QRect, indent: int = 0) -> QRect:
        x = row_rect.x() + 3 + indent * self.INDENT_W + self.EYE_W
        return QRect(x, row_rect.y() + (self.ROW_H - 14) // 2, 14, 14)

    # ── Thumbnail generator ───────────────────────────────────────────────────
    @staticmethod
    def make_thumb(layer) -> QPixmap:
        """
        38×34 thumbnail for the layer list. Cached on the layer object and
        only rebuilt when the image object or fill colour changes — the list
        is rebuilt on every layers_changed (every slider tick), so this must
        be cheap.
        """
        from PIL import Image as PILImage
        import numpy as np
        from PySide6.QtGui import QImage
        W, H = 38, 34
        key = (layer.kind, id(layer.pil_image),
               tuple(getattr(layer, "fill_color", ()) or ()))
        cached = getattr(layer, "_thumb_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        try:
            if layer.kind == "text":
                img = PILImage.new("RGBA", (W, H), (*_rgb(C["surface_3"]), 255))
            elif layer.kind == "group":
                img = PILImage.new("RGBA", (W, H), (*_rgb(C["gold_dim"]), 255))
            elif layer.kind == "fill":
                col = getattr(layer, "fill_color", (80, 80, 80))
                img = PILImage.new("RGBA", (W, H), (*col[:3], 255))
            elif layer.pil_image:
                src = layer.pil_image.copy()
                src.thumbnail((W, H), PILImage.LANCZOS)
                img = LayerDelegate._checker(W, H).copy()
                ox = (W - src.width)  // 2
                oy = (H - src.height) // 2
                mask = src if src.mode == "RGBA" else None
                img.paste(src, (ox, oy), mask)
            else:
                img = PILImage.new("RGBA", (W, H), (*_rgb(C["surface"]), 255))

            arr = np.ascontiguousarray(np.array(img.convert("RGBA"), dtype=np.uint8))
            qi  = QImage(arr.data, W, H, W * 4, QImage.Format.Format_RGBA8888).copy()
            pix = QPixmap.fromImage(qi)
        except Exception:
            pix = QPixmap()
        try:
            layer._thumb_cache = (key, pix)
        except Exception:
            pass
        return pix

    _CHECKER = None

    @staticmethod
    def _checker(W: int, H: int):
        """Shared checkerboard backdrop for image thumbnails (built once)."""
        if LayerDelegate._CHECKER is None:
            from PIL import Image as PILImage, ImageDraw
            c1, c2 = _rgb(C["border_strong"]), _rgb(C["text_muted"])
            bg = PILImage.new("RGBA", (W, H), (*c1, 255))
            draw = ImageDraw.Draw(bg)
            sq = 6
            for ry in range(0, H, sq):
                for rx in range(0, W, sq):
                    if (rx // sq + ry // sq) % 2 == 0:
                        draw.rectangle([rx, ry, rx + sq, ry + sq], fill=(*c2, 255))
            LayerDelegate._CHECKER = bg
        return LayerDelegate._CHECKER
