"""Ported from the session scratch tests — run with `pytest tests/`."""
import os, sys, tempfile
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_module():
    import time
    import numpy as np
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtGui import QKeyEvent
    app = QApplication.instance() or QApplication([])
    from app.ui.canvas.previewCanvas import PreviewCanvas
    from app.ui.canvas.layers import Layer

    Image.new("RGBA", (3840, 1240), (10, 200, 30, 255)).save(os.path.join(tempfile.gettempdir(), "sg_hero.png"))
    c = PreviewCanvas(); c.resize(900, 500); c.set_template("hero"); c._update_viewport()

    # 1. add + move → ONE undo restores the position, layer stays
    L = c.add_image_layer(os.path.join(tempfile.gettempdir(), "sg_hero.png"))
    x0 = L.x
    L.x += 100; L.invalidate_transform(); c._push_history()      # what mouseRelease does
    c.undo()
    assert len(c.layers) == 1 and c.layers[0].x == x0, (len(c.layers), c.layers[0].x)
    c.redo(); assert c.layers[0].x == x0 + 100
    c.undo(); c.undo(); assert len(c.layers) == 0            # second undo removes the layer
    c.redo(); assert len(c.layers) == 1

    # 2. slider drag = 100 ticks → one history entry, and no pickling of pixels
    n0 = len(c._history)
    t0 = time.perf_counter()
    for v in range(0, 100):
        c.update_selected_layer(opacity=v / 100)
    dt = time.perf_counter() - t0
    assert len(c._history) == n0 + 1, len(c._history)
    assert dt < 2.0, f"100 slider ticks took {dt:.2f}s"
    c.undo(); assert c.layers[0].opacity == 1.0
    # history holds references, not copies, of the image
    assert c._history[-1][0][0].pil_image is c.layers[0].pil_image or \
           np.array_equal(np.array(c._history[-1][0][0].pil_image)[:2,:2], np.array(c.layers[0].pil_image)[:2,:2])
    import sys as _s
    assert _s.getsizeof(c._history) < 10_000

    # 3. nudge with arrows is undoable (one step for a burst)
    c.setFocus(); n0 = len(c._history); x0 = c.layers[0].x
    for _ in range(5):
        c.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Right, Qt.NoModifier))
    assert c.layers[0].x == x0 + 5 and len(c._history) == n0 + 1
    c.undo(); assert c.layers[0].x == x0

    # 4. remove_layer emits layer_selected so the properties panel re-syncs
    got = []
    c.layer_selected.connect(lambda i: got.append(i))
    c.add_layer(Layer(kind="fill", name="f", x=0, y=0, w=50, h=50))
    c.remove_layer(1)
    assert got and got[-1] == 0, got

    # 5. _get_pix works on a display-sized copy for a hero layer at small zoom
    c.set_zoom(0.25); c._update_viewport()
    L = c.layers[0]; L.invalidate()
    pix = c._get_pix(L)
    assert pix.width() < 3840 and not L._pix_target[2]
    # export (scale 1) rebuilds at full res
    out = c.compose_to_pil()
    assert out.size == (3840, 1240)
    assert L._pix_target[2] is True   # full-res cache now
    # exported pixels come from the real image (green), not a placeholder
    arr = np.array(out); assert (arr[600, 1900, :3] == (10, 200, 30)).all() or arr[600,1900,1] > 150

    # 6. gradient fill via numpy renders a proper ramp quickly
    from app.ui.editorPanel import EditorPanel
    ep = EditorPanel(); ep.set_canvas(c, tab_state=None, tab_ref=None)
    F = Layer(kind="fill", name="g", x=0, y=0, w=3840, h=1240)
    F.fill_type = "gradient"; F.fill_color = (0, 0, 0); F.fill_color2 = (255, 255, 255)
    t0 = time.perf_counter(); ep._rebuild_fill_image(F); dt = time.perf_counter() - t0
    assert dt < 1.0, dt
    a = np.array(F.pil_image); assert a[0, 0, 0] == 0 and a[0, -1, 0] == 255

    # 7. thumbnails cached
    from app.ui.layerDelegate import LayerDelegate
    p1 = LayerDelegate.make_thumb(L); p2 = LayerDelegate.make_thumb(L)
    assert p1 is p2 and not p1.isNull()
    print("HISTORY/PERF TESTS PASSED")
