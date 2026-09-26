# -*- coding: utf-8 -*-
"""Windows desktop facts for the pet — READ-ONLY and crash-safe.

Taskbar rules (basketball mode, per user spec):
  - side taskbars (left/top/right) are IGNORED — the field is the full
    display area on those sides;
  - a VISIBLE bottom taskbar raises the bottom edge to the taskbar's top;
  - a HIDDEN (auto-hide) taskbar does NOT count — the bottom edge is the
    display area's bottom edge.

Recycle Bin presence is read from the Explorer icon-visibility registry
(never sends window messages — the desktop listview does not respond to
them safely from foreign processes, and malformed calls can crash it).

The hoop POSITION is user-calibrated (click the real Recycle Bin icon once
in the settings panel); the value persists in config.
"""

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

user32.FindWindowW.restype = wintypes.HWND
user32.GetWindowRect.restype = wintypes.BOOL
user32.IsWindowVisible.restype = wintypes.BOOL


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


# ------------------------------------------------------------------- taskbar
def bottom_visible_taskbar_top(screen_height):
    """Top edge y of a VISIBLE bottom taskbar, or None.

    Returns None when the taskbar is hidden (auto-hide) or on another side.
    """
    hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    if not hwnd:
        return None
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    if not user32.IsWindowVisible(hwnd):
        return None                      # auto-hidden taskbar: ignored
    # bottom taskbar: its bottom edge reaches the screen bottom
    if rect.bottom >= screen_height - 4 and rect.top > 0:
        return rect.top
    return None


def basketball_field(screen_geometry, work_geometry):
    """Field rect for basketball mode.

    screen_geometry: full display (x, y, w, h) — the field starts here.
    The bottom edge is raised to a visible bottom taskbar; side taskbars and
    hidden taskbars are ignored.
    """
    x, y, w, h = screen_geometry
    bottom = bottom_visible_taskbar_top(y + h)
    if bottom is not None:
        h = bottom - y
    return (x, y, w, h)
