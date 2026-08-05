"""무음 구간 검출.

`ffmpeg -af silencedetect`는 임계값을 고정으로 줘야 해서
녹음 환경이 바뀌면 매번 손봐야 한다. 여기서는 프레임별 RMS를 직접 재고
소음 바닥(noise floor)에서 상대적으로 임계값을 잡은 뒤,
히스테리시스로 말끝이 잘리는 걸 막는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import SilenceConfig
from .models import Span
from . import timeline

FRAME_MS = 25.0
HOP_MS = 10.0
_EPS = 1e-10


@dataclass
class SilenceAnalysis:
    threshold_db: float
    noise_floor_db: float
    speech_level_db: float
    speech: list[Span]
    silence: list[Span]
    duration: float


def frame_db(samples, sample_rate: int) -> "tuple":
    """프레임별 dBFS 배열과 프레임 시작 시각(초)을 돌려준다."""
    import numpy as np

    frame = max(1, int(sample_rate * FRAME_MS / 1000.0))
    hop = max(1, int(sample_rate * HOP_MS / 1000.0))
    if samples.size < frame:
        rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
        return np.array([20.0 * np.log10(rms + _EPS)]), np.array([0.0])

    count = 1 + (samples.size - frame) // hop
    # 복사 없이 슬라이딩 윈도우.
    strides = (samples.strides[0] * hop, samples.strides[0])
    windows = np.lib.stride_tricks.as_strided(
        samples, shape=(count, frame), strides=strides, writeable=False
    )
    rms = np.sqrt(np.mean(np.square(windows, dtype=np.float64), axis=1))
    db = 20.0 * np.log10(rms + _EPS)
    times = np.arange(count, dtype=np.float64) * (hop / sample_rate)
    return db, times


def pick_threshold(db, cfg: SilenceConfig) -> tuple[float, float, float]:
    """(임계값, 소음 바닥, 말소리 레벨) dB."""
    import numpy as np

    noise_floor = float(np.percentile(db, 10))
    speech_level = float(np.percentile(db, 95))

    if cfg.threshold_db is not None:
        return cfg.threshold_db, noise_floor, speech_level

    threshold = noise_floor + cfg.auto_margin_db
    # 말소리 레벨과 소음 바닥이 거의 붙어 있으면(=거의 통짜 무음이거나
    # 통짜 말소리이면) 임계값이 말소리 한복판에 꽂힐 수 있다. 위쪽을 막는다.
    threshold = min(threshold, speech_level - 6.0)
    threshold = max(threshold, cfg.floor_db)
    return threshold, noise_floor, speech_level


def analyze(samples, sample_rate: int, cfg: SilenceConfig) -> SilenceAnalysis:
    import numpy as np

    duration = samples.size / float(sample_rate) if sample_rate else 0.0
    db, times = frame_db(samples, sample_rate)
    threshold, noise_floor, speech_level = pick_threshold(db, cfg)

    # 히스테리시스: 켤 땐 임계값+1.5dB, 끌 땐 임계값-1.5dB.
    # 말끝의 여린 음절이 한 프레임 튀었다고 컷이 들어가는 걸 막는다.
    on_thr = threshold + 1.5
    off_thr = threshold - 1.5

    loud = db >= on_thr
    quiet = db <= off_thr
    state = False
    speech_frames = np.empty(db.size, dtype=bool)
    for i in range(db.size):
        if state:
            if quiet[i]:
                state = False
        elif loud[i]:
            state = True
        speech_frames[i] = state

    speech = _frames_to_spans(speech_frames, times, duration)
    # 짧은 무음(숨소리, 자연스러운 띄어쓰기)은 말소리로 되돌린다.
    speech = timeline.merge(speech, gap=cfg.min_silence)
    speech = timeline.pad_all(speech, cfg.keep_padding, cfg.keep_padding, duration)

    # min_silence보다 짧은 건 무음으로 치지 않는다. 프레임 경계 반올림 때문에
    # 앞뒤 끝에 몇 밀리초짜리 조각이 남는 걸 여기서 흡수한다.
    silence = [
        s for s in timeline.invert(speech, duration) if s.duration >= cfg.min_silence
    ]
    speech = timeline.invert(silence, duration)

    return SilenceAnalysis(
        threshold_db=threshold,
        noise_floor_db=noise_floor,
        speech_level_db=speech_level,
        speech=speech,
        silence=silence,
        duration=duration,
    )


def _frames_to_spans(flags, times, duration: float) -> list[Span]:
    import numpy as np

    if flags.size == 0 or not flags.any():
        return []
    padded = np.concatenate(([False], flags, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    spans: list[Span] = []
    hop = HOP_MS / 1000.0
    for start_idx, end_idx in zip(edges[0::2], edges[1::2]):
        start = float(times[start_idx])
        # 마지막 프레임은 FRAME_MS만큼 실제로 소리를 담고 있다.
        last = min(end_idx, times.size) - 1
        end = float(times[last]) + max(hop, FRAME_MS / 1000.0)
        spans.append(Span(start, min(end, duration)))
    return spans


__all__ = ["SilenceAnalysis", "analyze", "frame_db", "pick_threshold"]
