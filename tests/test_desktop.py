# -*- coding: utf-8 -*-
"""Desktop-facts smoke tests (run on the live Windows desktop):
taskbar field rules + real Recycle Bin icon detection."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desktop_pet import desktop_icons as desk

failures = []


def check(name, cond, detail=""):
    if not cond:
        failures.append(f"{name}: {detail}")
        print(f"FAIL {name} {detail}")
    else:
        print(f"ok   {name}")


# taskbar field rules
def test_basketball_field():
    # simulate a 1920x1080 display with a visible bottom taskbar (top=1040)
    field = desk.basketball_field((0, 0, 1920, 1080), (0, 0, 1920, 1040))
    # with the real taskbar visible at the bottom, bottom edge == taskbar top
    bottom = desk.bottom_visible_taskbar_top(1080)
    if bottom is not None:
        check("visible bottom taskbar raises field bottom",
              field[3] == bottom, f"field={field} bottom={bottom}")
        check("field bottom <= screen height", field[3] <= 1080)
    else:
        # taskbar hidden or on another side -> full display
        check("no visible bottom taskbar -> full display bottom",
              field[3] == 1080, f"field={field}")
        check("side/hidden taskbar keeps full width",
              field[2] == 1920, f"field={field}")


def test_recycle_bin_detection():
    # presence detection must be registry-based and crash-safe (no window msgs)
    from desktop_pet import recycle as recycle_mod
    visible = recycle_mod.recycle_bin_visible_on_desktop()
    print(f"    recycle bin icon visible on this desktop: {visible}")
    check("presence detector returns a bool", isinstance(visible, bool))
    # no listview window messages are sent by the module (crash safety)
    import inspect
    src = inspect.getsource(desk)
    check("no SendMessage in desktop_icons", "SendMessage" not in src,
          "desktop_icons must not send window messages")


if __name__ == "__main__":
    test_basketball_field()
    test_recycle_bin_detection()
    if failures:
        print(f"\n{len(failures)} FAILURES")
        sys.exit(1)
    print("\nALL DESKTOP TESTS PASSED")
