# -*- coding: utf-8 -*-
"""生成内置音效（纯 Python，无第三方依赖）。

仓库不含二进制音频，首次克隆后运行一次即可：
    python tools/make_sounds.py

生成：sounds/slap.wav（拍球）、sounds/explode.wav（爆炸）
发射音效（sounds/ahiya.mp3）为可选项：把任意 mp3 放到 sounds/ahiya.mp3
即可，或在 设置 → 篮球模式 中选择自己的音效文件。
"""

import math
import os
import random
import struct
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "sounds")
RATE = 44100


def _write_wav(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        frames = bytearray()
        for s in samples:
            v = int(max(-1.0, min(1.0, s)) * 32767)
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def make_slap():
    """短促拍球声：噪声脉冲 + 低频闷响，快速衰减。"""
    dur = 0.18
    n = int(RATE * dur)
    out = []
    for i in range(n):
        t = i / RATE
        env = math.exp(-t * 34.0)
        noise = random.uniform(-1.0, 1.0)
        thump = math.sin(2 * math.pi * 150 * t)
        out.append((noise * 0.55 + thump * 0.45) * env)
    return out


def make_explode():
    """爆炸声：宽频噪声 + 低频冲击，较长衰减。"""
    dur = 0.9
    n = int(RATE * dur)
    out = []
    for i in range(n):
        t = i / RATE
        env = math.exp(-t * 4.2)
        noise = random.uniform(-1.0, 1.0)
        boom = math.sin(2 * math.pi * (70 - 30 * t) * t)
        out.append((noise * 0.7 + boom * 0.6) * env)
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, gen in (("slap.wav", make_slap), ("explode.wav", make_explode)):
        p = os.path.join(OUT_DIR, name)
        _write_wav(p, gen())
        print("generated:", p)


if __name__ == "__main__":
    random.seed(7)
    main()
