"""
layerDelegate.py  —  Layer list item delegate.

Row layout (left→right):
  [eye] [indent] [▶/▼ if group] [thumb] [kind icon] [name] [lock]
Bottom strip: thin opacity bar.
Group rows get a subtle folder tint and bold name.
Child rows are indented by INDENT_W per level.
Drop indicators: blue top-line (insert before) or blue outline (insert into group).
"""
from __future__ import annotations
from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from PySide6.QtCore    import Qt, QRect, QSize, QPoint
from PySide6.QtGui     import (
    QPainter, QColor, QPen, QFont, QFontMetrics,
    QPixmap, QBrush, QPainterPath,
)
import io


class LayerDelegate(QStyledItemDelegate):
    # ── Data roles ───────────────────────────────────────────────────────────
    EYE_ROLE       = Qt.UserRole + 1   # bool  — layer visible?
    KIND_ROLE      = Qt.UserRole + 2   # str   — layer.kind
    OPAC_ROLE      = Qt.UserRole + 3   # float — 0-1 opacity
    PIX_ROLE       = Qt.UserRole + 4   # QPixmap thumbnail
    LOCK_ROLE      = Qt.UserRole + 5   # bool  — locked?
    INDENT_ROLE    = Qt.UserRole + 6   # int   — 0 = top-level, 1 = inside group
    COLLAPSED_ROLE = Qt.UserRole + 7   # bool  — group collapsed?
    DROP_ABOVE     = Qt.UserRole + 8   # bool  — draw "insert above" line
    DROP_INTO      = Qt.UserRole + 9   # bool  — draw "drop into group" outline

    ROW_H    = 44
    THUMB_W  = 38
    THUMB_H  = 34
    EYE_W    = 22
    INDENT_W = 16   # px per indent level

    _checker: QPixmap | None = None

    @classmethod
    def _get_checker(cls, w: int, h: int) -> QPixmap:
        if cls._checker and cls._checker.width() == w and cls._checker.height() == h:
            return cls._checker
        pix = QPixmap(w, h)
        p   = QPainter(pix)
        sq  = 5
        c1, c2 = QColor(180, 180, 180), QColor(220, 220, 220)
        for ry in range(0, h, sq):
            for rx in range(0, w, sq):
                p.fillRect(rx, ry, sq, sq,
                           c1 if (rx // sq + ry // sq) % 2 == 0 else c2)
        p.end()
        cls._checker = pix
        return cls._checker

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_H)

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
            bg = QColor(30, 78, 140)
        elif is_group:
            bg = QColor(40, 38, 58)
        elif index.row() % 2 == 0:
            bg = QColor(52, 52, 60)
        else:
            bg = QColor(44, 44, 52)
        painter.fillRect(r, bg)

        if drop_into:
            painter.fillRect(r, QColor(60, 100, 200, 55))
            painter.setPen(QPen(QColor(80, 150, 255), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(r.adjusted(1, 1, -1, -1))

        # ── Indent gutter ────────────────────────────────────────────────────
        if indent > 0:
            painter.fillRect(QRect(r.x(), r.y(), indent * self.INDENT_W, r.height()),
                             QColor(28, 28, 46))
            painter.setPen(QPen(QColor(55, 55, 100), 1))
            lx = r.x() + indent * self.INDENT_W - 1
            painter.drawLine(lx, r.top(), lx, r.bottom())

        x = r.x() + 3 + indent * self.INDENT_W

        # ── Eye ──────────────────────────────────────────────────────────────
        eye_rect = QRect(x, r.y() + (self.ROW_H - 18) // 2, 18, 18)
        if visible:
            painter.setBrush(QColor(200, 220, 255) if selected else QColor(140, 190, 255))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(eye_rect.adjusted(2, 4, -2, -4))
            painter.setBrush(QColor(30, 78, 140) if selected else QColor(50, 50, 64))
            painter.drawEllipse(eye_rect.adjusted(5, 7, -5, -7))
        else:
            painter.setPen(QPen(QColor(90, 90, 100), 2))
            mid_y = eye_rect.center().y()
            painter.drawLine(eye_rect.left() + 2, mid_y, eye_rect.right() - 2, mid_y)
        x += self.EYE_W

        # ── Collapse arrow (groups only) ──────────────────────────────────────
        if is_group:
            arrow_rect = QRect(x, r.y() + (self.ROW_H - 14) // 2, 14, 14)
            painter.setFont(QFont("Segoe UI", 7))
            painter.setPen(QColor(155, 155, 195))
            painter.drawText(arrow_rect, Qt.AlignCenter, "▶" if collapsed else "▼")
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
        painter.setPen(QPen(QColor(75, 75, 88), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(thumb_rect)
        x += tw + 5

        # ── Kind icon ────────────────────────────────────────────────────────
        KIND_MAP = {
            "paint":   ("🖼", QColor(80,  140, 200)),
            "image":   ("🖼", QColor(80,  140, 200)),
            "file":    ("🖼", QColor(80,  140, 200)),
            "texture": ("🌫", QColor(160, 100, 200)),
            "text":    ("T",  QColor(200, 160,  80)),
            "bar":     ("▬",  QColor(80,  200, 140)),
            "group":   ("📁", QColor(190, 165, 100)),
            "fill":    ("🪣", QColor(100, 200, 160)),
        }
        icon_str, icon_col = KIND_MAP.get(kind, ("◻", QColor(140, 140, 140)))
        kind_rect = QRect(x, r.y() + (self.ROW_H - 18) // 2, 18, 18)
        painter.setFont(QFont("Segoe UI Emoji", 10))
        painter.setPen(icon_col)
        painter.drawText(kind_rect, Qt.AlignCenter, icon_str)
        x += 22

        # ── Name ─────────────────────────────────────────────────────────────
        name      = index.data(Qt.DisplayRole) or ""
        name_rect = QRect(x, r.y(), r.right() - x - 26, self.ROW_H)
        name_col  = (QColor(220, 230, 255) if selected else
                     QColor(205, 195, 145) if is_group else
                     QColor(185, 185, 200))
        painter.setPen(name_col)
        painter.setFont(QFont("Segoe UI", 10,
                               QFont.Bold if is_group else QFont.Normal))
        fm     = QFontMetrics(painter.font())
        elided = fm.elidedText(name, Qt.ElideRight, name_rect.width())
        painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

        # ── Opacity micro-bar ────────────────────────────────────────────────
        opacity = index.data(self.OPAC_ROLE)
        if opacity is not None:
            base_x   = r.x() + self.EYE_W + indent * self.INDENT_W + self.THUMB_W + 46
            bar_w    = max(4, r.right() - base_x - 26)
            bar_rect = QRect(base_x, r.bottom() - 3, bar_w, 2)
            painter.fillRect(bar_rect, QColor(28, 28, 38))
            filled = QRect(bar_rect.x(), bar_rect.y(),
                           int(bar_rect.width() * max(0., min(1., float(opacity)))),
                           bar_rect.height())
            painter.fillRect(filled,
                             QColor(60, 120, 220) if selected else QColor(75, 95, 155))

        # ── Lock badge ───────────────────────────────────────────────────────
        if bool(index.data(self.LOCK_ROLE)):
            lr = QRect(r.right() - 22, r.y() + (self.ROW_H - 16) // 2, 16, 16)
            painter.setFont(QFont("Segoe UI Emoji", 9))
            painter.setPen(QColor(220, 175, 75))
            painter.drawText(lr, Qt.AlignCenter, "🔒")

        # ── Drop-above indicator ──────────────────────────────────────────────
        if drop_above:
            painter.setPen(QPen(QColor(100, 175, 255), 2))
            painter.drawLine(r.left(), r.top() + 1, r.right(), r.top() + 1)

        # ── Row separator ────────────────────────────────────────────────────
        painter.setPen(QPen(QColor(28, 28, 36), 1))
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
        from PIL import Image as PILImage
        W, H = 38, 34
        try:
            if layer.kind == "text":
                img = PILImage.new("RGBA", (W, H), (45, 43, 65, 255))
            elif layer.kind == "group":
                img = PILImage.new("RGBA", (W, H), (58, 52, 36, 255))
            elif layer.kind == "fill":
                col = getattr(layer, "fill_color", (80, 80, 80))
                img = PILImage.new("RGBA", (W, H), (*col[:3], 255))
            elif layer.pil_image:
                src = layer.pil_image.copy()
                src.thumbnail((W, H), PILImage.LANCZOS)
                bg = PILImage.new("RGBA", (W, H), (200, 200, 200, 255))
                sq = 6
                from PIL import ImageDraw
                draw = ImageDraw.Draw(bg)
                for ry in range(0, H, sq):
                    for rx in range(0, W, sq):
                        if (rx // sq + ry // sq) % 2 == 0:
                            draw.rectangle([rx, ry, rx+sq, ry+sq],
                                           fill=(180, 180, 180, 255))
                ox = (W - src.width)  // 2
                oy = (H - src.height) // 2
                mask = src if src.mode == "RGBA" else None
                bg.paste(src, (ox, oy), mask)
                img = bg
            else:
                img = PILImage.new("RGBA", (W, H), (35, 35, 45, 255))

            buf = io.BytesIO()
            img.save(buf, "PNG")
            pix = QPixmap()
            pix.loadFromData(buf.getvalue())
            return pix
        except Exception:
            return QPixmap()