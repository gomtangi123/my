import numpy as np
import pytest

from capcut_auto import silence
from capcut_auto.config import SilenceConfig

SR = 16000


def tone(seconds, amplitude=0.5, freq=220.0):
    t = np.arange(int(seconds * SR)) / SR
    return (np.sin(2 * np.pi * freq * t) * amplitude).astype(np.float32)


def quiet(seconds, amplitude=0.0005):
    rng = np.random.default_rng(0)
    return (rng.standard_normal(int(seconds * SR)) * amplitude).astype(np.float32)


def build(*chunks):
    return np.concatenate(chunks).astype(np.float32)


class TestFrameDb:
    def test_loud_is_higher_than_quiet(self):
        loud, _ = silence.frame_db(tone(0.5), SR)
        soft, _ = silence.frame_db(quiet(0.5), SR)
        assert loud.mean() > soft.mean() + 30

    def test_times_are_monotonic(self):
        _db, times = silence.frame_db(tone(1.0), SR)
        assert np.all(np.diff(times) > 0)

    def test_handles_signal_shorter_than_a_frame(self):
        db, times = silence.frame_db(np.zeros(10, dtype=np.float32), SR)
        assert db.size == 1 and times.size == 1


class TestThreshold:
    def test_auto_sits_between_floor_and_speech(self):
        db, _ = silence.frame_db(build(tone(1.0), quiet(1.0)), SR)
        threshold, floor, speech = silence.pick_threshold(db, SilenceConfig())
        assert floor < threshold < speech

    def test_explicit_threshold_wins(self):
        db, _ = silence.frame_db(build(tone(0.5), quiet(0.5)), SR)
        threshold, _f, _s = silence.pick_threshold(
            db, SilenceConfig(threshold_db=-33.0)
        )
        assert threshold == -33.0

    def test_never_below_configured_floor(self):
        db, _ = silence.frame_db(quiet(1.0, amplitude=1e-6), SR)
        threshold, _f, _s = silence.pick_threshold(
            db, SilenceConfig(floor_db=-55.0, auto_margin_db=1.0)
        )
        assert threshold >= -55.0


class TestAnalyze:
    def test_finds_the_silent_middle(self):
        samples = build(tone(1.0), quiet(1.5), tone(1.0))
        result = silence.analyze(samples, SR, SilenceConfig(keep_padding=0.0))
        assert len(result.silence) == 1
        gap = result.silence[0]
        assert gap.start == pytest.approx(1.0, abs=0.12)
        assert gap.end == pytest.approx(2.5, abs=0.12)

    def test_speech_spans_cover_the_tones(self):
        samples = build(tone(1.0), quiet(1.5), tone(1.0))
        result = silence.analyze(samples, SR, SilenceConfig(keep_padding=0.0))
        assert len(result.speech) == 2

    def test_short_gaps_are_not_cut(self):
        # 0.15초짜리 틈은 min_silence(0.35) 아래라 말소리로 되돌아간다
        samples = build(tone(0.8), quiet(0.15), tone(0.8))
        result = silence.analyze(samples, SR, SilenceConfig(min_silence=0.35))
        assert len(result.speech) == 1

    def test_long_gaps_are_cut(self):
        samples = build(tone(0.8), quiet(0.6), tone(0.8))
        result = silence.analyze(samples, SR, SilenceConfig(min_silence=0.35))
        assert len(result.speech) == 2

    def test_padding_widens_speech(self):
        samples = build(quiet(1.0), tone(1.0), quiet(1.0))
        tight = silence.analyze(samples, SR, SilenceConfig(keep_padding=0.0))
        padded = silence.analyze(samples, SR, SilenceConfig(keep_padding=0.2))
        assert padded.speech[0].duration > tight.speech[0].duration

    def test_all_silence_yields_no_speech(self):
        result = silence.analyze(quiet(2.0), SR, SilenceConfig())
        assert result.speech == []
        assert len(result.silence) == 1

    def test_all_speech_yields_no_silence(self):
        result = silence.analyze(tone(2.0), SR, SilenceConfig())
        assert result.silence == []
        assert len(result.speech) == 1

    def test_spans_stay_inside_the_media(self):
        samples = build(tone(0.5), quiet(0.8), tone(0.5))
        result = silence.analyze(samples, SR, SilenceConfig(keep_padding=0.5))
        for span in result.speech + result.silence:
            assert 0.0 <= span.start <= result.duration
            assert 0.0 <= span.end <= result.duration

    def test_speech_and_silence_partition_the_timeline(self):
        samples = build(tone(0.7), quiet(0.9), tone(0.7))
        result = silence.analyze(samples, SR, SilenceConfig())
        total = sum(s.duration for s in result.speech + result.silence)
        assert total == pytest.approx(result.duration, abs=0.02)

    def test_quiet_speech_still_detected_above_a_low_noise_floor(self):
        # 조용히 말해도 소음 바닥 대비로 임계값을 잡으므로 잡혀야 한다
        samples = build(quiet(0.5, 1e-4), tone(1.0, amplitude=0.02), quiet(0.5, 1e-4))
        result = silence.analyze(samples, SR, SilenceConfig())
        assert len(result.speech) == 1
