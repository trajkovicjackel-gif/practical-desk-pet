# -*- coding: utf-8 -*-
"""Crop dialog logic test: programmatic selection -> cropped square PNG."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor


def make_test_image(path, w=640, h=360):
    img = QImage(w, h, QImage.Format_RGB32)
    for x in range(w):
        for y in range(h):
            img.setPixelColor(x, y, QColor(x * 255 // w, y * 255 // h, 0))
    return img.save(path, "PNG")


def main():
    qapp = QApplication(sys.argv)
    import tempfile
    from desktop_pet.crop_dialog import CropDialog

    tmp = tempfile.gettempdir()
    src = os.path.join(tmp, "crop_test_src.png")
    assert make_test_image(src)

    dlg = CropDialog(src)
    # simulate a circular drag: press at center, drag 150px right
    dlg.start_drag(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(300, 180))
    dlg.update_drag(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(450, 180))
    assert dlg.sel is not None, "selection not created"
    cx, cy, radius = dlg.sel
    assert radius == 150, f"expected radius 150, got {radius}"
    assert (cx, cy) == (300, 180), f"center should stay at press point: {(cx, cy)}"
    dlg.end_drag()

    # move the whole selection by dragging its center crosshair
    dlg.start_drag(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(300, 180))
    dlg.update_drag(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(360, 200))
    dlg.end_drag()
    cx2, cy2, r2 = dlg.sel
    assert (cx2, cy2) == (360, 200), f"selection should move with the center: {(cx2, cy2)}"
    assert r2 == 150, f"radius unchanged by move: {r2}"

    # right-click inside the selection resets it
    dlg.right_click(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(360, 200))
    assert dlg.sel is None, "right-click inside selection should reset it"

    # re-select and accept
    dlg.start_drag(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(300, 180))
    dlg.update_drag(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(450, 180))
    dlg.end_drag()
    dlg._accept()
    assert dlg.cropped_path and os.path.exists(dlg.cropped_path), "cropped file missing"
    from PySide6.QtGui import QPixmap
    pix = QPixmap(dlg.cropped_path)
    assert not pix.isNull(), "cropped image unreadable"
    assert pix.width() == pix.height(), f"crop not square: {pix.width()}x{pix.height()}"

    # no-selection path -> centered largest inscribed square
    dlg2 = CropDialog(src)
    dlg2._accept()
    pix2 = QPixmap(dlg2.cropped_path)
    assert pix2.width() == pix2.height() == 360, \
        f"center crop wrong: {pix2.width()}x{pix2.height()}"

    os.remove(src)
    os.remove(dlg.cropped_path)
    os.remove(dlg2.cropped_path)
    print("PASS crop dialog (selection + center-square fallback)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
