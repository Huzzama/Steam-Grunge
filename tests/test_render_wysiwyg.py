"""Ported from the session scratch tests — run with `pytest tests/`."""
import os, sys, tempfile
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_module():
    import numpy as np
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    app = QApplication.instance() or QApplication([])

    from app.ui.canvas.previewCanvas import PreviewCanvas
    from app.ui.canvas.layers import Layer

    def doc_render_via_preview_path(c):
        """Render through the live-preview scene path at doc resolution."""
        dw, dh = c._doc_size.width(), c._doc_size.height()
        c._scale, c._ox, c._oy = 1.0, 0, 0
        pix = c._render_scene_to_pixmap(QRect(0, 0, dw, dh))
        qi = pix.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        return np.frombuffer(qi.bits(), dtype=np.uint8).reshape((dh, dw, 4)).copy()

    c = PreviewCanvas(); c.resize(800, 600)
    c.set_template("wide")                       # 920x430
    dw, dh = c._doc_size.width(), c._doc_size.height()

    # image layer with rotation, flip, crop, colour tweaks, blend
    img = Image.new("RGBA", (300, 200), (200, 40, 40, 255))
    Image.fromarray((np.random.default_rng(1).integers(0, 255, (200, 300, 4), dtype=np.uint8))).save(os.path.join(tempfile.gettempdir(), "sg_l.png"))
    L = c.add_image_layer(os.path.join(tempfile.gettempdir(), "sg_l.png"), name="img")
    L.x, L.y, L.w, L.h = 100, 50, 400, 250; L.rotation = 23; L.flip_h = True
    L.brightness = 70; L.opacity = 0.8; L.blend_mode = "multiply"; L.crop_l = 10; L.invalidate()

    # text layer: vertical, centred, outline + shadow, letter spacing
    T = c.add_text_layer("GRUNGE\nTEST") if hasattr(c, "add_text_layer") else None
    if T is None:
        T = Layer(kind="text", name="t", x=0, y=0, w=1, h=1); c._layers.append(T)
    T.x, T.y, T.w, T.h = 500, 40, 120, 350
    T.font_size = 60; T.text_orientation = "vertical"; T.text_align = "center"
    T.letter_spacing = 4; T.outline_size = 3; T.outline_color = (0, 0, 255)
    T.shadow_offset = 6; T.shadow_color = (0, 255, 0); T.font_color = (255, 255, 0)

    # gradient fill
    F = Layer(kind="fill", name="f", x=600, y=300, w=300, h=100)
    F.fill_type = "gradient"; F.fill_color = (0, 0, 0); F.fill_color2 = (255, 255, 255); F.fill_angle = 0
    c._layers.append(F)

    # vector path
    V = Layer(kind="vector", name="v", x=20, y=300, w=200, h=100)
    V.vector_paths = [{"points": [(0, 0), (200, 0), (100, 100)], "closed": True}]
    V.vector_stroke = (255, 0, 255); V.vector_fill = (0, 255, 255)
    c._layers.append(V)

    # placeholder-only mask (must NOT appear in export)
    M = Layer(kind="mask_filter", name="m", x=700, y=20, w=150, h=100)
    c._layers.append(M)

    # ── no FX: preview path (export flag) vs compose_to_pil must be identical ────
    c.update_effects_overlay(0, 0)
    exp = np.array(c.compose_to_pil())
    assert exp.shape == (dh, dw, 4)

    c._scale, c._ox, c._oy = 1.0, 0, 0
    qi = QImage(dw, dh, QImage.Format.Format_RGBA8888); qi.fill(0)
    p = QPainter(qi); p.setRenderHint(QPainter.SmoothPixmapTransform); p.setRenderHint(QPainter.Antialiasing)
    c._render_scene(p, QRect(0, 0, dw, dh), export=True); p.end()
    ref = np.frombuffer(qi.bits(), dtype=np.uint8).reshape((dh, dw, 4)).copy()
    assert np.array_equal(exp, ref), "export differs from scene render"

    # preview path (export=False) differs ONLY where the placeholder mask sits
    prev = doc_render_via_preview_path(c)
    diff = np.abs(prev.astype(int) - exp.astype(int)).sum(axis=2) > 0
    # (mask placeholder box and the vector layer's translucent editor backdrop)
    assert diff.any()
    diff[20:122, 700:852] = False      # mask_filter placeholder
    diff[300:402, 20:222]  = False     # vector editor backdrop
    assert not diff.any(), np.argwhere(diff)[:5]

    # text really has outline (blue) + shadow (green) + fill (yellow) pixels
    def has(col, tol=40):
        d = np.abs(exp[:, :, :3].astype(int) - np.array(col)).sum(axis=2)
        return (d < tol).any()
    assert has((0, 0, 255)) and has((0, 255, 0)) and has((255, 255, 0)), "text outline/shadow/fill missing"
    # gradient: left of fill is dark, right is light
    row = exp[350, 600:900, 0].astype(int)
    assert row[5] < 40 and row[-5] > 215 and row[150] > 90 and row[150] < 170, (row[5], row[150], row[-5])
    # vector fill colour present
    assert has((0, 255, 255))
    # transparent template stays transparent + no checkerboard
    c2 = PreviewCanvas(); c2.set_template("logo"); a = np.array(c2.compose_to_pil())
    assert a[..., 3].max() == 0, "logo export should be fully transparent"

    # ── grain is deterministic and equal in preview + export ──────────────────────
    c.update_effects_overlay(40, 0)
    e1 = np.array(c.compose_to_pil()); e2 = np.array(c.compose_to_pil())
    assert np.array_equal(e1, e2), "grain not deterministic"
    assert not np.array_equal(e1, exp), "grain not applied"
    print("RENDER TESTS PASSED")
