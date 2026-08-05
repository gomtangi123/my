"""내장 효과음 합성.

효과음 라이브러리가 없어도 기능이 돌아가야 하므로 numpy로 직접 만든다.
저작권 걱정이 없고, 없는 파일을 참조해서 CapCut이 빈 클립을 띄우는 사고도 없다.
제대로 된 소리를 쓰고 싶으면 `sfx.library`에 폴더를 지정하면 그쪽이 우선한다.
"""

from __future__ import annotations

import wave
from pathlib import Path

SAMPLE_RATE = 44100

# 편집에서 실제로 쓰는 것들만. 이름은 sfx 규칙에서 그대로 참조한다.
BUILTIN_SOUNDS = (
    "whoosh",
    "swoosh",
    "pop",
    "ding",
    "click",
    "thud",
    "riser",
    "boing",
)


def _envelope(n: int, attack: float, decay: float, curve: float = 2.0):
    import numpy as np

    attack_n = max(1, int(n * attack))
    env = np.ones(n)
    env[:attack_n] = np.linspace(0.0, 1.0, attack_n)
    decay_start = int(n * (1.0 - decay))
    if decay_start < n:
        tail = np.linspace(0.0, 1.0, n - decay_start)
        env[decay_start:] *= (1.0 - tail) ** curve
    return env


def _noise(n: int, seed: int):
    import numpy as np

    rng = np.random.default_rng(seed)
    return rng.standard_normal(n).astype("float64")


def _lowpass_sweep(signal, sample_rate: int, start_hz: float, end_hz: float):
    """시간에 따라 컷오프가 움직이는 1극 저역통과. whoosh의 핵심."""
    import numpy as np

    n = signal.size
    cutoff = np.linspace(start_hz, end_hz, n)
    alpha = 1.0 - np.exp(-2.0 * np.pi * cutoff / sample_rate)
    out = np.empty(n)
    acc = 0.0
    for i in range(n):
        acc += alpha[i] * (signal[i] - acc)
        out[i] = acc
    return out


def _sine_sweep(n: int, sample_rate: int, start_hz: float, end_hz: float):
    import numpy as np

    freq = np.linspace(start_hz, end_hz, n)
    phase = 2.0 * np.pi * np.cumsum(freq) / sample_rate
    return np.sin(phase)


def synth(name: str, sample_rate: int = SAMPLE_RATE):
    """이름에 해당하는 파형(float64, -1~1)을 만든다."""
    import numpy as np

    if name == "whoosh":
        n = int(0.45 * sample_rate)
        sig = _lowpass_sweep(_noise(n, 1), sample_rate, 400.0, 6000.0)
        sig *= _envelope(n, attack=0.35, decay=0.55, curve=2.2)
    elif name == "swoosh":
        n = int(0.40 * sample_rate)
        sig = _lowpass_sweep(_noise(n, 2), sample_rate, 6000.0, 500.0)
        sig *= _envelope(n, attack=0.08, decay=0.8, curve=1.8)
    elif name == "pop":
        n = int(0.12 * sample_rate)
        sig = _sine_sweep(n, sample_rate, 900.0, 180.0)
        sig *= _envelope(n, attack=0.02, decay=0.95, curve=3.0)
    elif name == "ding":
        n = int(0.55 * sample_rate)
        t = np.arange(n) / sample_rate
        sig = (
            np.sin(2 * np.pi * 1318.5 * t)
            + 0.5 * np.sin(2 * np.pi * 2637.0 * t)
            + 0.25 * np.sin(2 * np.pi * 3956.0 * t)
        )
        sig *= np.exp(-6.0 * t)
    elif name == "click":
        n = int(0.05 * sample_rate)
        sig = _noise(n, 3) * _envelope(n, attack=0.02, decay=0.95, curve=4.0)
        sig = _lowpass_sweep(sig, sample_rate, 8000.0, 3000.0)
    elif name == "thud":
        n = int(0.30 * sample_rate)
        t = np.arange(n) / sample_rate
        sig = np.sin(2 * np.pi * 72.0 * t) * np.exp(-9.0 * t)
        sig += 0.25 * _noise(n, 4) * np.exp(-45.0 * t)
    elif name == "riser":
        n = int(1.10 * sample_rate)
        t = np.linspace(0.0, 1.0, n)
        sig = _sine_sweep(n, sample_rate, 180.0, 2200.0) * 0.55
        sig += _lowpass_sweep(_noise(n, 5), sample_rate, 800.0, 9000.0) * 0.45
        sig *= t**2.0
    elif name == "boing":
        n = int(0.40 * sample_rate)
        t = np.arange(n) / sample_rate
        wobble = 320.0 + 180.0 * np.sin(2 * np.pi * 11.0 * t) * np.exp(-4.0 * t)
        phase = 2.0 * np.pi * np.cumsum(wobble) / sample_rate
        sig = np.sin(phase) * np.exp(-5.0 * t)
    else:
        raise KeyError(f"내장 효과음에 없습니다: {name} (가능: {', '.join(BUILTIN_SOUNDS)})")

    peak = float(np.max(np.abs(sig))) or 1.0
    return (sig / peak) * 0.92


def write_wav(path: Path, signal, sample_rate: int = SAMPLE_RATE) -> Path:
    import numpy as np

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(signal, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        fh.writeframes(pcm.tobytes())
    return path


def ensure(name: str, out_dir: Path, sample_rate: int = SAMPLE_RATE) -> Path:
    """`out_dir`에 효과음 wav를 만들어 두고 경로를 준다. 이미 있으면 재사용."""
    path = Path(out_dir) / f"{name}.wav"
    if path.exists():
        return path
    return write_wav(path, synth(name, sample_rate), sample_rate)


def duration_of(name: str, sample_rate: int = SAMPLE_RATE) -> float:
    return synth(name, sample_rate).size / sample_rate


__all__ = ["BUILTIN_SOUNDS", "synth", "write_wav", "ensure", "duration_of", "SAMPLE_RATE"]
