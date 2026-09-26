# -*- coding: utf-8 -*-
"""Persistent configuration for the Desktop Pet (JSON in %APPDATA%/DesktopPet)."""

import json
import os
import sys

# 测试/自测隔离：set_config_dir() 指向临时目录后，所有读写都不再触碰
# 用户的真实配置（%APPDATA%\DesktopPet）。
_override_dir = None


def set_config_dir(path):
    """将配置目录重定向到指定路径（供测试与 --selftest 使用）。"""
    global _override_dir
    _override_dir = path


def config_dir():
    if _override_dir:
        os.makedirs(_override_dir, exist_ok=True)
        return _override_dir
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "DesktopPet")
    os.makedirs(d, exist_ok=True)
    return d


def config_path():
    return os.path.join(config_dir(), "config.json")


def app_root():
    """程序根目录。

    - 源码运行：本文件在 desktop_pet/ 下，上一级即根目录；
    - PyInstaller 打包后：exe 所在目录（数据文件与 exe 放在同一文件夹）。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_path(p):
    """把相对路径解析为程序根目录下的绝对路径（便于整个文件夹分发）。"""
    if not p:
        return p
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(app_root(), p))


DEFAULTS = {
    # startup always enters the record (idle) state; saved mode is not restored
    "mode": "idle",            # idle | pong | basketball | balloon
    "appearance": {
        "radius": 80,          # 50..200, step 10
        "skin_path": None,     # uploaded skin image (None = default face)
    },
    "record": {
        "audio_path": None,    # single audio (legacy) — playlist preferred
        "playlist": [],        # multiple songs (歌单)
        "auto_next": True,     # auto play next track when one ends
        "playback_mode": "list_loop",  # single_loop|list_loop|sequential|shuffle
        "rotate_dir": "cw",    # cw | ccw
        "rotate_speed": 90,    # degrees per second
        "vinyl_ring_r": 120.0, # 黑胶外环半径（像素，50~350，直接控制）
        "sync_external": True, # 同步外部音乐软件：仅发媒体键，不播放本地音乐
        "external_session": "auto",  # 外部播放器：auto 或应用 app_id
    },
    "pong": {
        "ball_count": 1,       # 1..10
        "ball_speed": 340,     # 100..1000, step 20
        "difficulty": "bean",  # bean | simple | normal | hell | king
        "spawn_interval": 1.0, # seconds between auto-spawns (0.25..5, step 0.25)
        "score": 0,
    },
    "basketball": {
        "score": 0,
        # 默认音效用相对路径（相对程序根目录），整个文件夹分发到任何
        # 路径都能工作；加载时会解析为绝对路径再使用
        "launch_sound": "sounds/ahiya.mp3",
        "slap_sound": "sounds/slap.wav",
        "drop_ball_file": True,  # 进球时是否在回收站生成 ball 文件（可关闭）
        # hoop target = the real Recycle Bin icon; the user calibrates it by
        # clicking the icon (auto-prompted on first interaction)
        "hoop_calibrated": False,
        "hoop_pos": None,
    },
    "balloon": {
        "water": 0,            # 0..100, step 1（切换到气球模式时默认 0%，浮顶部；100% 沉底）
        "count": 10,           # 1..10 balloons
        "score": 0,            # independent: +2 per explosion
        "explode_sound": "sounds/explode.wav",
        "explode_strength": 250.0,  # shockwave strength (0..1000, px impulse scale)
        # four-state appearance by water: 0% / 25% / 50% / 100%
        "images": [None, None, None, None],
    },
}


def load():
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            saved = json.load(f)
        _deep_merge(cfg, saved)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    # 迁移旧版「黑胶半径倍数」→ 新版「黑胶外环半径（像素）」
    rec = cfg.get("record", {})
    if "vinyl_scale" in rec:
        try:
            r = cfg["appearance"].get("radius", 80)
            scale = float(rec.pop("vinyl_scale"))
            rec["vinyl_ring_r"] = min(350.0, max(50.0, r * 1.28 * scale))
        except (TypeError, ValueError):
            rec["vinyl_ring_r"] = 120.0
    # 默认音效相对路径 → 解析为绝对路径（程序根目录），保证文件夹可移植；
    # 已保存的旧路径不存在时自动回退到默认音效（文件移动/路径变化自愈）
    for key, default in (("launch_sound", "sounds/ahiya.mp3"),
                         ("slap_sound", "sounds/slap.wav")):
        v = cfg["basketball"].get(key)
        if v and not os.path.isabs(v):
            cfg["basketball"][key] = resolve_path(v)
        elif not v or not os.path.exists(v):
            cfg["basketball"][key] = resolve_path(default)
    v = cfg["balloon"].get("explode_sound")
    if v and not os.path.isabs(v):
        cfg["balloon"]["explode_sound"] = resolve_path(v)
    elif not v or not os.path.exists(v):
        cfg["balloon"]["explode_sound"] = resolve_path("sounds/explode.wav")
    return cfg


def save(cfg):
    tmp = config_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, config_path())


def _deep_merge(base, patch):
    for k, v in patch.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
