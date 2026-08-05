from capcut_auto import subtitles
from capcut_auto.config import SubtitleConfig
from capcut_auto.models import Span, SubtitleLine, Word
from capcut_auto.timeline import TimeMap


def words(*specs):
    return [Word(start=s, end=e, text=t) for t, s, e in specs]


def spans(*pairs):
    return [Span(a, b) for a, b in pairs]


class TestBuildLines:
    def test_splits_on_sentence_end(self):
        ws = words(("안녕하세요.", 0.0, 0.8), ("반갑습니다.", 0.9, 1.7))
        lines = subtitles.build_lines(ws, SubtitleConfig())
        assert [l.text for l in lines] == ["안녕하세요", "반갑습니다"]

    def test_splits_on_long_pause(self):
        ws = words(("오늘은", 0.0, 0.5), ("리액트", 2.0, 2.6))
        lines = subtitles.build_lines(ws, SubtitleConfig(split_gap=0.45))
        assert len(lines) == 2

    def test_keeps_short_pause_together(self):
        ws = words(("오늘은", 0.0, 0.5), ("리액트", 0.6, 1.2))
        lines = subtitles.build_lines(ws, SubtitleConfig(split_gap=0.45))
        assert len(lines) == 1
        assert lines[0].text == "오늘은 리액트"

    def test_splits_when_too_long(self):
        ws = words(*[(f"단어{i}", i * 0.4, i * 0.4 + 0.3) for i in range(12)])
        lines = subtitles.build_lines(ws, SubtitleConfig(max_chars=8, max_lines=1))
        assert len(lines) > 1
        assert all(len(l.text.replace("\n", "")) <= 12 for l in lines)

    def test_splits_when_too_slow(self):
        ws = words(("가", 0.0, 0.3), ("나", 0.4, 0.7), ("다", 5.0, 5.3))
        lines = subtitles.build_lines(
            ws, SubtitleConfig(max_duration=2.0, split_gap=99.0)
        )
        assert len(lines) == 2

    def test_trailing_period_stripped(self):
        lines = subtitles.build_lines(words(("끝.", 0.0, 0.5)), SubtitleConfig())
        assert lines[0].text == "끝"

    def test_question_mark_kept(self):
        lines = subtitles.build_lines(words(("맞나요?", 0.0, 0.5)), SubtitleConfig())
        assert lines[0].text == "맞나요?"

    def test_disabled(self):
        assert subtitles.build_lines(words(("가", 0, 1)), SubtitleConfig(enabled=False)) == []


class TestWrap:
    def test_no_wrap_when_short(self):
        assert subtitles.wrap("짧은 줄", 20, 2) == "짧은 줄"

    def test_wraps_into_two_lines(self):
        text = subtitles.wrap("가나다 라마바 사아자 차카타", 8, 2)
        assert text.count("\n") == 1

    def test_never_exceeds_max_lines(self):
        text = subtitles.wrap(" ".join(["단어"] * 20), 6, 2)
        assert text.count("\n") <= 1

    def test_single_line_mode(self):
        assert "\n" not in subtitles.wrap("가나다 라마바 사아자", 5, 1)


class TestRemap:
    def test_shifts_lines_past_a_cut(self):
        # 0-1 유지, 1-2 컷, 2-4 유지
        tm = TimeMap(spans((0, 1), (2, 4)))
        line = SubtitleLine("나중 문장", 2.5, 3.5, words(("나중 문장", 2.5, 3.5)))
        out = subtitles.remap([line], tm, SubtitleConfig())
        assert out[0].start == 1.5
        assert out[0].end == 2.5

    def test_drops_fully_cut_lines(self):
        tm = TimeMap(spans((0, 1), (2, 4)))
        line = SubtitleLine("사라짐", 1.2, 1.8, words(("사라짐", 1.2, 1.8)))
        assert subtitles.remap([line], tm, SubtitleConfig()) == []

    def test_removes_cut_words_from_the_text(self):
        # 필러 '음'이 잘린 자리 -> 자막에도 남으면 안 된다
        tm = TimeMap(spans((0.0, 1.0), (1.5, 3.0)))
        line = SubtitleLine(
            "제가 음 갔어요",
            0.0,
            3.0,
            words(("제가", 0.1, 0.9), ("음", 1.1, 1.4), ("갔어요", 1.6, 2.9)),
        )
        out = subtitles.remap([line], tm, SubtitleConfig())
        assert out[0].text == "제가 갔어요"

    def test_partially_cut_word_survives_if_mostly_kept(self):
        tm = TimeMap(spans((0.0, 0.9), (1.0, 3.0)))
        line = SubtitleLine(
            "단어", 0.0, 1.0, words(("단어", 0.0, 1.0))
        )
        out = subtitles.remap([line], tm, SubtitleConfig())
        assert out and out[0].text == "단어"

    def test_short_line_is_extended_to_min_duration(self):
        tm = TimeMap(spans((0, 10)))
        line = SubtitleLine("짧다", 1.0, 1.1, words(("짧다", 1.0, 1.1)))
        out = subtitles.remap([line], tm, SubtitleConfig(min_duration=0.6))
        assert out[0].end - out[0].start >= 0.6

    def test_lines_do_not_overlap_after_extension(self):
        tm = TimeMap(spans((0, 10)))
        lines = [
            SubtitleLine("하나", 1.0, 1.1, words(("하나", 1.0, 1.1))),
            SubtitleLine("둘", 1.3, 2.0, words(("둘", 1.3, 2.0))),
        ]
        out = subtitles.remap(lines, tm, SubtitleConfig(min_duration=0.9))
        assert out[0].end <= out[1].start

    def test_output_is_sorted(self):
        tm = TimeMap(spans((0, 10)))
        lines = [
            SubtitleLine("둘", 5.0, 6.0, words(("둘", 5.0, 6.0))),
            SubtitleLine("하나", 1.0, 2.0, words(("하나", 1.0, 2.0))),
        ]
        out = subtitles.remap(lines, tm, SubtitleConfig())
        assert [l.text for l in out] == ["하나", "둘"]


class TestSrt:
    def test_format_timestamp(self):
        assert subtitles.format_timestamp(0) == "00:00:00,000"
        assert subtitles.format_timestamp(3661.5) == "01:01:01,500"

    def test_negative_time_clamped(self):
        assert subtitles.format_timestamp(-5) == "00:00:00,000"

    def test_srt_structure(self):
        lines = [SubtitleLine("안녕", 0.0, 1.5), SubtitleLine("반가워", 2.0, 3.0)]
        srt = subtitles.to_srt(lines)
        assert srt.startswith("1\n00:00:00,000 --> 00:00:01,500\n안녕\n")
        assert "\n2\n00:00:02,000 --> 00:00:03,000\n반가워\n" in srt

    def test_empty(self):
        assert subtitles.to_srt([]) == ""
