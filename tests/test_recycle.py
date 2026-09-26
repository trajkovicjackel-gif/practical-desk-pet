# -*- coding: utf-8 -*-
"""Recycle-bin detection test: flip the desktop-icon registry value, verify
the detector sees both states, then restore. Runs in <1s; explorer does not
notice a fast flip."""

import os
import sys
import winreg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desktop_pet.recycle import recycle_bin_visible_on_desktop, RECYCLE_BIN_CLSID

KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel"


def set_hidden(value):
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as k:
            winreg.SetValueEx(k, RECYCLE_BIN_CLSID, 0, winreg.REG_DWORD, 1 if value else 0)
    except OSError as e:
        print(f"FAIL cannot write registry: {e}")
        sys.exit(2)


def read_raw():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
            return winreg.QueryValueEx(k, RECYCLE_BIN_CLSID)[0]
    except FileNotFoundError:
        return None


original = read_raw()
ok = True

# visible path (whatever the current state is, force visible=0)
set_hidden(False)
if not recycle_bin_visible_on_desktop():
    ok = False
    print("FAIL visible-path: detector said hidden while value=0")

# hidden path
set_hidden(True)
if recycle_bin_visible_on_desktop():
    ok = False
    print("FAIL hidden-path: detector said visible while value=1")

# restore
if original is None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RECYCLE_BIN_CLSID)
    except OSError:
        pass
else:
    set_hidden(original)

if ok:
    print("PASS recycle-bin detection (visible & hidden paths)")
else:
    print("FAIL recycle-bin detection")
    sys.exit(1)
