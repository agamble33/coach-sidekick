"""Synthesize Coach's reaction stings from scratch (royalty-free, original).

Run: python tools/make_sounds.py -> assets/sounds/*.wav (+ .mp3 if ffmpeg exists)
"""
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "assets" / "sounds"
OUT.mkdir(parents=True, exist_ok=True)


def t(sec):
    return np.linspace(0, sec, int(SR * sec), endpoint=False)


def env(n, a=0.01, r=0.1):
    e = np.ones(n)
    ia, ir = int(SR * a), int(SR * r)
    e[:ia] = np.linspace(0, 1, ia)
    e[-ir:] *= np.linspace(1, 0, ir)
    return e


def tone(f, sec, kind="saw", vib=0.0):
    x = t(sec)
    ph = 2 * np.pi * f * x + vib * np.sin(2 * np.pi * 6 * x)
    if kind == "saw":
        y = 2 * ((ph / (2 * np.pi)) % 1) - 1
    elif kind == "square":
        y = np.sign(np.sin(ph))
    else:
        y = np.sin(ph)
    return y * env(len(y))


def lowpass(y, alpha=0.08):
    out = np.empty_like(y)
    acc = 0.0
    a = np.broadcast_to(np.asarray(alpha, dtype=float), y.shape)
    for i, v in enumerate(y):
        acc += a[i] * (v - acc)
        out[i] = acc
    return out


def womp():  # sad trombone, 4 descending notes with a wobble on the last
    notes = [(233, 0.35), (220, 0.35), (207, 0.35)]
    parts = [lowpass(tone(f, d, "saw", vib=1.5)) for f, d in notes]
    x = t(1.0)
    f = 196 - 12 * x
    ph = 2 * np.pi * np.cumsum(f) / SR + 2.5 * np.sin(2 * np.pi * 5 * x)
    last = lowpass((2 * ((ph / (2 * np.pi)) % 1) - 1)) * env(len(x), 0.02, 0.4)
    return np.concatenate(parts + [last])


def bruh():  # deep bass drop with a short sub thump
    x = t(0.9)
    f = 110 * np.exp(-2.2 * x) + 40
    y = np.sin(2 * np.pi * np.cumsum(f) / SR)
    y += 0.4 * np.sin(2 * np.pi * np.cumsum(f * 0.5) / SR)
    return y * env(len(x), 0.005, 0.5)


def scratch():  # record scratch: filtered noise with pitch sweeps
    x = t(0.55)
    noise = np.random.default_rng(7).uniform(-1, 1, len(x))
    sweep = np.sin(2 * np.pi * np.cumsum(900 + 1800 * np.abs(np.sin(2 * np.pi * 4 * x))) / SR)
    y = lowpass(noise, 0.25) * 0.8 + sweep * 0.5
    return y * env(len(x), 0.01, 0.1) * (0.6 + 0.4 * np.abs(np.sin(2 * np.pi * 8 * x)))


def airhorn():  # layered square tones with vibrato
    x = t(1.1)
    y = np.zeros(len(x))
    for f in (233, 466, 699):
        y += np.sign(np.sin(2 * np.pi * f * x + 3 * np.sin(2 * np.pi * 7 * x)))
    return lowpass(y / 3, 0.2) * env(len(x), 0.01, 0.3)


def cackle():  # staccato "ha ha ha" from noisy pulsed tones
    x = t(1.2)
    pulse = (np.sin(2 * np.pi * 5.5 * x) > 0.2).astype(float)
    f = 320 - 60 * x
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.6
    y += np.random.default_rng(3).uniform(-1, 1, len(x)) * 0.25
    return lowpass(y * pulse, 0.3) * env(len(x), 0.01, 0.2)


def boing():  # spring: fast-decaying pitch wobble
    x = t(0.7)
    f = 220 + 160 * np.exp(-4 * x) * np.sin(2 * np.pi * 14 * x)
    y = np.sin(2 * np.pi * np.cumsum(f) / SR)
    return y * np.exp(-3.5 * x) * env(len(x), 0.005, 0.1)


def dingding():  # bright success chime
    y = np.zeros(int(SR * 0.9))
    for i, f in enumerate((880, 1174, 1568)):
        s = int(SR * 0.15 * i)
        x = t(0.6)
        part = np.sin(2 * np.pi * f * x) * np.exp(-4 * x)
        y[s:s + len(x)] += part * 0.6
    return y


def gasp():  # rising breathy whoosh
    x = t(0.6)
    noise = np.random.default_rng(11).uniform(-1, 1, len(x))
    y = lowpass(noise, 0.05 + 0.4 * x)  # opens up
    return y * np.sin(np.pi * x) ** 0.5 * env(len(x), 0.05, 0.2)


SOUNDS = {
    "womp": womp,
    "bruh": bruh,
    "scratch": scratch,
    "airhorn": airhorn,
    "cackle": cackle,
    "boing": boing,
    "dingding": dingding,
    "gasp": gasp,
}


def write(name, y):
    y = y / (np.max(np.abs(y)) + 1e-9) * 0.85
    pcm = (y * 32767).astype("<i2")
    p = OUT / f"{name}.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p), "-b:a", "96k", str(p.with_suffix(".mp3"))], check=True)
    return p


if __name__ == "__main__":
    for n, fn in SOUNDS.items():
        print("wrote", write(n, fn()))
