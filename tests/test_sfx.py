import numpy as np
import pytest

from capcut_auto.config import SfxConfig
from capcut_auto.models import EditPlan, Span, SubtitleLine, Word
from capcut_auto.sfx import builtin
from capcut_auto.sfx.library import Library
from capcut_auto.sfx.planner import plan_sfx
from capcut_auto.timeline import TimeMap


def words(*specs):
    return [Word(start=s, end=e, text=t) for t, s, e in specs]


def make_plan(keeps, subtitle_specs=()):
    subs = []
    for text, start, end, ws in subtitle_specs:
        subs.append(SubtitleLine(text, start, end, words(*ws)))
    return EditPlan(
        source="dummy.mp4",
        source_duration=keeps[-1].end,
        keeps=list(keeps),
        cuts=[],
        subtitles=subs,
    )


@pytest.fixture
def library(tmp_path):
    return Library.load(None, tmp_path / "sfx")


class TestBuiltinSynthesis:
    @pytest.mark.parametrize("name", builtin.BUILTIN_SOUNDS)
    def test_every_builtin_renders(self, name):
        signal = builtin.synth(name)
        assert signal.size > 0
        assert np.max(np.abs(signal)) <= 1.0

    @pytest.mark.parametrize("name", builtin.BUILTIN_SOUNDS)
    def test_every_builtin_is_audible(self, name):
        assert float(np.sqrt(np.mean(builtin.synth(name) ** 2))) > 0.01

    def test_unknown_name_raises(self):
        with pytest.raises(KeyError):
            builtin.synth("없는소리")

    def test_writes_a_readable_wav(self, tmp_path):
        import wave

        path = builtin.ensure("pop", tmp_path)
        assert path.exists()
        with wave.open(str(path)) as fh:
            assert fh.getnchannels() == 1
            assert fh.getframerate() == builtin.SAMPLE_RATE
            assert fh.getnframes() > 0

    def test_ensure_is_cached(self, tmp_path):
        first = builtin.ensure("ding", tmp_path)
        stamp = first.stat().st_mtime_ns
        assert builtin.ensure("ding", tmp_path).stat().st_mtime_ns == stamp


class TestLibrary:
    def test_falls_back_to_builtin(self, library):
        sound = library.find("whoosh")
        assert sound is not None and sound.builtin

    def test_unknown_key_returns_none(self, library):
        assert library.find("존재하지않는소리") is None

    def test_user_folder_wins(self, tmp_path):
        folder = tmp_path / "mysfx"
        folder.mkdir()
        builtin.write_wav(folder / "whoosh_swipe_01.wav", builtin.synth("pop"))
        lib = Library.load(folder, tmp_path / "scratch")
        sound = lib.find("whoosh")
        assert sound is not None and not sound.builtin

    def test_rotates_between_matching_files(self, tmp_path):
        folder = tmp_path / "mysfx"
        folder.mkdir()
        for i in (1, 2):
            builtin.write_wav(folder / f"whoosh_{i}.wav", builtin.synth("pop"))
        lib = Library.load(folder, tmp_path / "scratch")
        picks = {lib.find("whoosh").path.name for _ in range(4)}
        assert len(picks) == 2

    def test_missing_folder_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Library.load(tmp_path / "nope", tmp_path / "scratch")


class TestTransitions:
    def test_places_sound_at_each_cut_seam(self, library):
        # 0.8초씩 두 번 잘렸으니(= section_gap 미만) 전환음이 이음매 두 곳에
        plan = make_plan([Span(0, 3), Span(3.8, 6.8), Span(7.6, 10.6)])
        tm = TimeMap(plan.keeps)
        out = plan_sfx(plan, tm, SfxConfig(emphasis=False, lead=0.0), library)
        assert [p.reason for p in out] == ["transition", "transition"]
        assert [round(p.time, 2) for p in out] == [3.0, 6.0]

    def test_seam_times_are_on_the_output_timeline(self, library):
        plan = make_plan([Span(0, 3), Span(3.8, 6.8)])
        tm = TimeMap(plan.keeps)
        out = plan_sfx(plan, tm, SfxConfig(emphasis=False, lead=0.0), library)
        # 원본의 3.8초 지점이 아니라 결과물의 3.0초 지점
        assert out[0].time == pytest.approx(3.0)
        assert out[0].time < tm.output_duration

    def test_tiny_gaps_get_no_transition(self, library):
        # 0.1초만 잘린 자리(필러 하나 제거)에는 전환음을 넣지 않는다
        plan = make_plan([Span(0, 3), Span(3.1, 6)])
        out = plan_sfx(
            plan,
            TimeMap(plan.keeps),
            SfxConfig(emphasis=False, transition_min_gap=0.35),
            library,
        )
        assert out == []

    def test_large_gap_uses_the_section_sound(self, library):
        plan = make_plan([Span(0, 3), Span(8, 11)])
        out = plan_sfx(
            plan,
            TimeMap(plan.keeps),
            SfxConfig(emphasis=False, section_gap=1.5),
            library,
        )
        assert [p.reason for p in out] == ["section"]
        assert out[0].sound.key == "riser"

    def test_riser_ends_on_the_seam(self, library):
        plan = make_plan([Span(0, 5), Span(10, 15)])
        out = plan_sfx(plan, TimeMap(plan.keeps), SfxConfig(emphasis=False), library)
        assert out[0].time + out[0].duration == pytest.approx(5.0, abs=0.01)

    def test_transitions_disabled(self, library):
        plan = make_plan([Span(0, 3), Span(5, 8)])
        out = plan_sfx(
            plan, TimeMap(plan.keeps), SfxConfig(transition=False, emphasis=False), library
        )
        assert out == []


class TestEmphasis:
    def test_number_gets_a_sound(self, library):
        plan = make_plan(
            [Span(0, 20)],
            [("무려 3배입니다", 1.0, 3.0, (("무려", 1.0, 1.4), ("3배입니다", 1.5, 2.5)))],
        )
        out = plan_sfx(
            plan, TimeMap(plan.keeps), SfxConfig(transition=False), library
        )
        assert [p.reason for p in out] == ["emphasis"]
        assert "숫자" in out[0].detail

    def test_emphasis_word_gets_a_sound(self, library):
        plan = make_plan(
            [Span(0, 20)],
            [("가장 중요한 건", 1.0, 3.0, (("가장", 1.0, 1.4), ("중요한", 1.5, 2.0)))],
        )
        out = plan_sfx(plan, TimeMap(plan.keeps), SfxConfig(transition=False), library)
        assert out and out[0].reason == "emphasis"

    def test_question_uses_question_sound(self, library):
        plan = make_plan(
            [Span(0, 20)], [("왜 그럴까요?", 1.0, 3.0, (("그럴까요?", 1.0, 2.0),))]
        )
        out = plan_sfx(plan, TimeMap(plan.keeps), SfxConfig(transition=False), library)
        assert out[0].sound.key == "pop"

    def test_plain_words_get_nothing(self, library):
        plan = make_plan(
            [Span(0, 20)],
            [("오늘 날씨 좋네요", 1.0, 3.0, (("오늘", 1.0, 1.4), ("날씨", 1.5, 2.0)))],
        )
        out = plan_sfx(plan, TimeMap(plan.keeps), SfxConfig(transition=False), library)
        assert out == []


class TestDensity:
    def test_min_interval_thins_out_neighbours(self, library):
        specs = [
            (f"{i}번", i * 0.3, i * 0.3 + 0.2, ((f"{i}번", i * 0.3, i * 0.3 + 0.2),))
            for i in range(1, 12)
        ]
        plan = make_plan([Span(0, 20)], specs)
        out = plan_sfx(
            plan,
            TimeMap(plan.keeps),
            SfxConfig(transition=False, min_interval=1.0, max_per_minute=0),
            library,
        )
        times = sorted(p.time for p in out)
        assert all(b - a >= 1.0 for a, b in zip(times, times[1:]))

    def test_max_per_minute_caps_the_count(self, library):
        specs = [
            (f"{i}번", i * 2.0, i * 2.0 + 0.5, ((f"{i}번", i * 2.0, i * 2.0 + 0.5),))
            for i in range(1, 25)
        ]
        plan = make_plan([Span(0, 60)], specs)
        out = plan_sfx(
            plan,
            TimeMap(plan.keeps),
            SfxConfig(transition=False, min_interval=0.1, max_per_minute=5),
            library,
        )
        assert len(out) <= 5

    def test_results_are_sorted_by_time(self, library):
        plan = make_plan(
            [Span(0, 5), Span(8, 13)],
            [("무려 100배", 1.0, 2.0, (("100배", 1.0, 2.0),))],
        )
        out = plan_sfx(plan, TimeMap(plan.keeps), SfxConfig(), library)
        assert [p.time for p in out] == sorted(p.time for p in out)

    def test_sfx_never_lands_past_the_end(self, library):
        plan = make_plan(
            [Span(0, 3)], [("끝 100", 2.9, 3.0, (("100", 2.9, 3.0),))]
        )
        out = plan_sfx(plan, TimeMap(plan.keeps), SfxConfig(), library)
        for placement in out:
            assert placement.time < 3.0

    def test_disabled(self, library):
        plan = make_plan([Span(0, 3), Span(5, 8)])
        assert plan_sfx(plan, TimeMap(plan.keeps), SfxConfig(enabled=False), library) == []


class TestUserRules:
    def test_rule_matches_and_wins_over_transition(self, library):
        plan = make_plan(
            [Span(0, 10)], [("하하 웃겨", 1.0, 2.0, (("하하", 1.0, 1.5),))]
        )
        cfg = SfxConfig(
            transition=False,
            emphasis=False,
            rules=({"match": "하하", "sound": "boing"},),
        )
        out = plan_sfx(plan, TimeMap(plan.keeps), cfg, library)
        assert [p.sound.key for p in out] == ["boing"]
        assert out[0].reason == "rule"

    def test_rule_with_unknown_sound_is_ignored(self, library):
        plan = make_plan([Span(0, 10)], [("하하", 1.0, 2.0, (("하하", 1.0, 1.5),))])
        cfg = SfxConfig(
            transition=False, emphasis=False, rules=({"match": "하하", "sound": "없음"},)
        )
        assert plan_sfx(plan, TimeMap(plan.keeps), cfg, library) == []
