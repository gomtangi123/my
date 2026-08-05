import pytest

from capcut_auto import disfluency
from capcut_auto.config import Config, DisfluencyConfig
from capcut_auto.models import Word
from capcut_auto.text import is_filler, normalize_word, similarity


def words(*specs):
    """('텍스트', 시작, 끝) 튜플들을 Word 목록으로."""
    return [Word(start=s, end=e, text=t) for t, s, e in specs]


def stream(texts, start=0.0, dur=0.3, gap=0.05):
    """일정한 간격으로 말한 것처럼 단어를 만든다."""
    out = []
    t = start
    for text in texts:
        out.append(Word(start=t, end=t + dur, text=text))
        t += dur + gap
    return out


FILLERS = Config().fillers


def cut_texts(cuts, reason=None):
    return [c.detail for c in cuts if reason is None or c.reason == reason]


class TestNormalize:
    def test_strips_punctuation(self):
        assert normalize_word("그래서,") == "그래서"

    def test_collapses_repeats(self):
        assert normalize_word("어어어") == "어"

    def test_lowercases_english(self):
        assert normalize_word("UM,") == "um"


class TestIsFiller:
    def test_plain_filler(self):
        assert is_filler("음", FILLERS)

    def test_filler_with_punctuation(self):
        assert is_filler("어,", FILLERS)

    def test_repeated_vowel(self):
        assert is_filler("어어어", FILLERS)

    def test_elongated_form(self):
        assert is_filler("그으", FILLERS)

    def test_real_word_is_not_filler(self):
        # '아니'가 '아'로 잘못 어간 분리되면 안 된다
        assert not is_filler("아니", FILLERS)

    def test_word_starting_with_filler_syllable(self):
        assert not is_filler("그래서", FILLERS)
        assert not is_filler("어디", FILLERS)

    def test_keep_list_removes_from_dictionary(self):
        cfg = Config()
        cfg.disfluency.keep_fillers = ("좀",)
        assert not is_filler("좀", cfg.fillers)

    def test_extra_fillers_added(self):
        cfg = Config()
        cfg.disfluency.extra_fillers = ("아무튼",)
        assert is_filler("아무튼", cfg.fillers)


class TestFillerCuts:
    def test_cuts_isolated_filler(self):
        ws = stream(["그", "제가", "오늘", "음", "말씀드릴"])
        cuts = disfluency.detect(ws, DisfluencyConfig(), FILLERS, 10)
        assert sorted(cut_texts(cuts, "filler")) == ["그", "음"]

    def test_keeps_content_words(self):
        ws = stream(["제가", "오늘", "발표를", "합니다"])
        cuts = disfluency.detect(ws, DisfluencyConfig(), FILLERS, 10)
        assert cuts == []

    def test_long_drawn_filler_is_kept(self):
        ws = words(("음", 0.0, 2.0), ("그래서", 2.1, 2.5))
        cfg = DisfluencyConfig(max_filler_duration=1.2)
        assert disfluency.detect(ws, cfg, FILLERS, 10) == []

    def test_disabled_flag(self):
        ws = stream(["음", "어", "그"])
        cfg = DisfluencyConfig(remove_fillers=False, remove_stutters=False)
        assert disfluency.detect(ws, cfg, FILLERS, 10) == []

    def test_require_isolation_skips_embedded_filler(self):
        # 앞뒤로 붙어 있는(간격 0.01초) 필러는 건드리지 않는다
        ws = words(("제가", 0.0, 0.3), ("음", 0.31, 0.5), ("갔어요", 0.51, 0.9))
        cfg = DisfluencyConfig(
            require_isolation=True, isolation_gap=0.12, remove_stutters=False
        )
        assert disfluency.detect(ws, cfg, FILLERS, 10) == []

    def test_require_isolation_still_cuts_floating_filler(self):
        ws = words(("제가", 0.0, 0.3), ("음", 0.8, 1.0), ("갔어요", 1.5, 1.9))
        cfg = DisfluencyConfig(require_isolation=True, isolation_gap=0.12)
        assert cut_texts(disfluency.detect(ws, cfg, FILLERS, 10), "filler") == ["음"]

    def test_cut_span_covers_the_word_with_padding(self):
        ws = words(("음", 1.0, 1.4), ("그래서", 2.0, 2.4))
        cfg = DisfluencyConfig(pad=0.05)
        cut = disfluency.detect(ws, cfg, FILLERS, 10)[0]
        assert cut.span.start == 0.95
        assert cut.span.end == 1.45

    def test_padding_clamped_to_media_bounds(self):
        ws = words(("음", 0.0, 0.2))
        cut = disfluency.detect(ws, DisfluencyConfig(pad=0.5), FILLERS, 0.3)[0]
        assert cut.span.start == 0.0
        assert cut.span.end == 0.3


class TestStutterCuts:
    def test_exact_repeat_keeps_last(self):
        ws = words(("그", 0.0, 0.2), ("그", 0.3, 0.5), ("그러니까", 0.6, 1.0))
        cfg = DisfluencyConfig(remove_fillers=False)
        cuts = disfluency.detect(ws, cfg, FILLERS, 10)
        # '그'는 필러라서 한 글자 접두사여도 '그러니까'의 말막힘으로 본다.
        assert [c.reason for c in cuts] == ["stutter", "stutter"]
        assert all(c.span.end < 0.6 for c in cuts)

    def test_single_char_prefix_of_real_word_is_kept(self):
        # "이 이야기" — '이'는 더듬은 게 아니라 관형사다
        ws = words(("이", 0.0, 0.2), ("이야기는", 0.3, 0.8))
        cfg = DisfluencyConfig(remove_fillers=False)
        assert disfluency.detect(ws, cfg, FILLERS, 10) == []

    def test_single_char_prefix_allowed_when_configured(self):
        ws = words(("이", 0.0, 0.2), ("이야기는", 0.3, 0.8))
        cfg = DisfluencyConfig(remove_fillers=False, stutter_min_prefix=1)
        assert [c.reason for c in disfluency.detect(ws, cfg, FILLERS, 10)] == ["stutter"]

    def test_false_start_prefix_repeat(self):
        ws = words(("그러니", 0.0, 0.4), ("그러니까", 0.5, 1.0))
        cfg = DisfluencyConfig(remove_fillers=False)
        cuts = disfluency.detect(ws, cfg, FILLERS, 10)
        assert [c.reason for c in cuts] == ["stutter"]
        assert cuts[0].detail == "그러니 → 그러니까"

    def test_repeat_after_long_gap_is_not_a_stutter(self):
        ws = words(("정말", 0.0, 0.4), ("정말", 3.0, 3.4))
        cfg = DisfluencyConfig(remove_fillers=False, stutter_max_gap=0.7)
        assert disfluency.detect(ws, cfg, FILLERS, 10) == []

    def test_triple_repeat_leaves_only_last(self):
        ws = words(
            ("이거", 0.0, 0.2),
            ("이거", 0.3, 0.5),
            ("이거는", 0.6, 0.9),
        )
        cfg = DisfluencyConfig(remove_fillers=False)
        cuts = disfluency.detect(ws, cfg, FILLERS, 10)
        assert len(cuts) == 2
        assert all(c.span.end <= 0.55 for c in cuts)

    def test_stutter_disabled(self):
        ws = words(("그러니", 0.0, 0.4), ("그러니까", 0.5, 1.0))
        cfg = DisfluencyConfig(remove_fillers=False, remove_stutters=False)
        assert disfluency.detect(ws, cfg, FILLERS, 10) == []

    def test_no_double_cut_when_filler_also_stutters(self):
        # "그 그 그" — 더듬음으로 앞 둘, 필러로 마지막 하나. 겹쳐 잡히면 안 된다.
        ws = words(("그", 0.0, 0.2), ("그", 0.3, 0.5), ("그", 0.6, 0.8))
        cuts = disfluency.detect(ws, DisfluencyConfig(), FILLERS, 10)
        assert len(cuts) == 3
        assert [c.reason for c in cuts] == ["stutter", "stutter", "filler"]


class TestRetakeCuts:
    def test_similar_sentence_drops_the_earlier_one(self):
        ws = (
            words(("오늘은", 0.0, 0.4), ("리액트를", 0.5, 1.0), ("배워봅니다.", 1.1, 1.8))
            + words(("오늘은", 3.0, 3.4), ("리액트를", 3.5, 4.0), ("배워봅시다.", 4.1, 4.8))
        )
        cfg = DisfluencyConfig(
            remove_fillers=False, remove_stutters=False, remove_retakes=True
        )
        cuts = disfluency.detect(ws, cfg, FILLERS, 10)
        assert [c.reason for c in cuts] == ["retake"]
        assert cuts[0].span.start <= 0.0
        assert cuts[0].span.end >= 1.8

    def test_different_sentences_are_kept(self):
        ws = (
            words(("오늘은", 0.0, 0.4), ("리액트를", 0.5, 1.0), ("배웁니다.", 1.1, 1.8))
            + words(("내일은", 3.0, 3.4), ("파이썬을", 3.5, 4.0), ("합니다.", 4.1, 4.8))
        )
        cfg = DisfluencyConfig(
            remove_fillers=False, remove_stutters=False, remove_retakes=True
        )
        assert disfluency.detect(ws, cfg, FILLERS, 10) == []

    def test_short_sentences_are_ignored(self):
        ws = words(("네.", 0.0, 0.3)) + words(("네.", 2.0, 2.3))
        cfg = DisfluencyConfig(
            remove_fillers=False, remove_stutters=False, remove_retakes=True
        )
        assert disfluency.detect(ws, cfg, FILLERS, 10) == []

    def test_far_apart_repeats_are_kept(self):
        first = words(("이건", 0.0, 0.4), ("정말로", 0.5, 1.0), ("중요합니다.", 1.1, 1.9))
        second = words(
            ("이건", 90.0, 90.4), ("정말로", 90.5, 91.0), ("중요합니다.", 91.1, 91.9)
        )
        cfg = DisfluencyConfig(
            remove_fillers=False,
            remove_stutters=False,
            remove_retakes=True,
            retake_window=25.0,
        )
        assert disfluency.detect(first + second, cfg, FILLERS, 120) == []

    def test_off_by_default(self):
        ws = (
            words(("오늘은", 0.0, 0.4), ("리액트를", 0.5, 1.0), ("배워봅니다.", 1.1, 1.8))
            + words(("오늘은", 3.0, 3.4), ("리액트를", 3.5, 4.0), ("배워봅시다.", 4.1, 4.8))
        )
        cfg = DisfluencyConfig(remove_fillers=False, remove_stutters=False)
        assert disfluency.detect(ws, cfg, FILLERS, 10) == []


class TestSimilarity:
    def test_identical(self):
        assert similarity("안녕하세요", "안녕하세요") == 1.0

    def test_unrelated(self):
        assert similarity("안녕하세요", "파이썬") < 0.4

    def test_ignores_punctuation_and_spacing(self):
        assert similarity("안녕 하세요.", "안녕하세요") == 1.0


def test_cuts_are_sorted_by_time():
    ws = stream(["음", "제가", "어", "오늘", "그", "발표를"])
    cuts = disfluency.detect(ws, DisfluencyConfig(), FILLERS, 10)
    starts = [c.span.start for c in cuts]
    assert starts == sorted(starts)


def test_empty_input():
    assert disfluency.detect([], DisfluencyConfig(), FILLERS, 10) == []


class TestFillerTiers:
    def test_meaningful_connective_is_kept_by_default(self):
        # "그러니까 이게 핵심입니다" — 접속사까지 날리면 뜻이 상한다
        ws = words(("그러니까", 0.0, 0.6), ("이게", 0.7, 1.0), ("핵심입니다", 1.1, 1.9))
        cfg = DisfluencyConfig(remove_stutters=False)
        assert disfluency.detect(ws, cfg, FILLERS, 10) == []

    def test_aggressive_mode_cuts_it(self):
        cfg = Config()
        cfg.disfluency.aggressive_fillers = True
        ws = words(("그러니까", 0.0, 0.6), ("이게", 0.7, 1.0), ("핵심입니다", 1.1, 1.9))
        cuts = disfluency.detect(ws, cfg.disfluency, cfg.fillers, 10)
        assert [c.detail for c in cuts] == ["그러니까"]

    @pytest.mark.parametrize("word", ["그러니까", "이제", "좀", "약간", "진짜"])
    def test_risky_words_not_in_default_dictionary(self, word):
        assert not is_filler(word, Config().fillers)

    @pytest.mark.parametrize("word", ["음", "어", "그", "저기", "흠"])
    def test_core_fillers_always_cut(self, word):
        assert is_filler(word, Config().fillers)

    def test_aggressive_still_respects_keep_list(self):
        cfg = Config()
        cfg.disfluency.aggressive_fillers = True
        cfg.disfluency.keep_fillers = ("그러니까",)
        assert not is_filler("그러니까", cfg.fillers)
