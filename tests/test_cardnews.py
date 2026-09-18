import pytest

from capcut_auto.cardnews import colors, layout, script, theme
from capcut_auto.cardnews.models import Card, resolve_size


class TestParse:
    def test_splits_on_separator(self):
        deck = script.parse("첫 장\n\n---\n\n둘째 장\n\n---\n\n셋째 장")
        assert len(deck) == 3

    def test_accepts_equals_and_stars_as_separator(self):
        deck = script.parse("가\n===\n나\n***\n다")
        assert len(deck) == 3

    def test_heading_becomes_title(self):
        card = script.parse("## 제목입니다\n본문입니다").cards[0]
        assert card.title == "제목입니다"
        assert card.body == "본문입니다"

    def test_single_line_block_is_a_title(self):
        # 한 줄짜리는 문단이 아니라 한마디다 — 크게 박혀야 한다.
        card = script.parse("# 표지\n\n---\n\n딱 한 줄").cards[1]
        assert card.title == "딱 한 줄"
        assert card.body == ""

    def test_multiline_without_heading_is_all_body(self):
        card = script.parse("# 표지\n\n---\n\n첫 줄\n둘째 줄").cards[1]
        assert card.title == ""
        assert card.body == "첫 줄\n둘째 줄"

    def test_first_card_is_cover(self):
        deck = script.parse("가\n---\n나")
        assert [c.kind for c in deck] == ["cover", "body"]

    def test_directive_overrides_kind(self):
        deck = script.parse("가\n---\n@마무리\n## 끝\n안녕")
        assert deck.cards[1].kind == "outro"
        assert deck.cards[1].title == "끝"

    def test_english_directive(self):
        assert script.parse("@outro\n끝").cards[0].kind == "outro"

    def test_blank_blocks_are_dropped(self):
        deck = script.parse("가\n---\n\n\n---\n나")
        assert len(deck) == 2

    def test_inner_blank_line_survives_as_paragraph_break(self):
        card = script.parse("# 표지\n---\n첫 문단\n\n둘째 문단").cards[1]
        assert card.body == "첫 문단\n\n둘째 문단"

    def test_empty_script_raises(self):
        with pytest.raises(ValueError):
            script.parse("   \n\n  ")

    def test_index_is_assigned(self):
        deck = script.parse("가\n---\n나\n---\n다")
        assert [c.index for c in deck] == [0, 1, 2]


class TestWrap:
    # 글자 하나를 10px로 치는 가짜 자.
    measure = staticmethod(lambda s: len(s) * 10.0)

    def test_wraps_on_spaces(self):
        lines = layout.wrap("가나 다라 마바", self.measure, 50.0)
        assert lines == ["가나 다라", "마바"]

    def test_breaks_long_word_by_character(self):
        # 공백 없는 긴 어절은 글자 단위로 쪼개야 상자를 안 넘는다.
        lines = layout.wrap("가나다라마바사", self.measure, 30.0)
        assert lines == ["가나다", "라마바", "사"]
        assert all(self.measure(l) <= 30.0 for l in lines)

    def test_keeps_hard_newlines(self):
        lines = layout.wrap("가\n나", self.measure, 100.0)
        assert lines == ["가", "나"]

    def test_keeps_blank_line_as_spacer(self):
        assert layout.wrap("가\n\n나", self.measure, 100.0) == ["가", "", "나"]

    def test_fits_exactly_at_boundary(self):
        assert layout.wrap("가나다", self.measure, 30.0) == ["가나다"]


class TestFit:
    @staticmethod
    def metrics(size):
        # 글꼴 크기에 비례하는 자와 줄 높이.
        return (lambda s: len(s) * size), float(size)

    def test_picks_largest_that_fits(self):
        # 20이면 폭 30에 안 맞아 세 줄로 쪼개지고 높이 60이 되어 상자를 넘는다.
        result = layout.fit("가나다", self.metrics, 30.0, 50.0, [20, 10, 5])
        assert result.size == 10
        assert result.lines == ["가나다"]

    def test_uses_a_bigger_size_when_the_box_is_tall_enough(self):
        # 같은 폭이라도 높이가 넉넉하면 쪼개서라도 큰 글씨를 쓴다.
        result = layout.fit("가나다", self.metrics, 30.0, 100.0, [20, 10, 5])
        assert result.size == 20
        assert result.lines == ["가", "나", "다"]

    def test_falls_back_to_smallest_when_nothing_fits(self):
        # 여기서 예외가 나면 대본 한 줄 때문에 전체 작업이 죽는다.
        result = layout.fit("가나다라마", self.metrics, 10.0, 1.0, [8, 4])
        assert result.size == 4
        assert result.lines

    def test_height_counts_every_line(self):
        result = layout.fit("가나다라", self.metrics, 20.0, 100.0, [10])
        assert result.height == result.line_height * len(result.lines)

    def test_empty_ladder_raises(self):
        with pytest.raises(ValueError):
            layout.fit("가", self.metrics, 10.0, 10.0, [])


class TestLadder:
    def test_descends(self):
        assert layout.ladder(10, 6, 2) == [10, 8, 6]

    def test_swaps_reversed_bounds(self):
        assert layout.ladder(6, 10, 2) == [10, 8, 6]

    def test_never_empty(self):
        assert layout.ladder(5, 5) == [5]


class TestColors:
    def test_parses_shorthand(self):
        assert colors.parse("#abc") == colors.parse("#aabbcc")

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            colors.parse("파랑")

    def test_contrast_is_symmetric(self):
        a = colors.contrast("#FFFFFF", "#000000")
        assert a == pytest.approx(colors.contrast("#000000", "#FFFFFF"))
        assert a == pytest.approx(21.0, abs=0.01)

    def test_same_color_has_no_contrast(self):
        assert colors.contrast("#1B4DFF", "#1B4DFF") == pytest.approx(1.0)

    def test_mix_endpoints(self):
        assert colors.mix("#000000", "#FFFFFF", 0.0) == "#000000"
        assert colors.mix("#000000", "#FFFFFF", 1.0) == "#FFFFFF"

    def test_readable_keeps_color_with_enough_contrast(self):
        assert colors.readable("#2F6BFF", "#16181D", "#FFFFFF", 3.0) == "#2F6BFF"

    def test_readable_falls_back_when_invisible(self):
        # bold 테마 표지: 강조색이 곧 배경색이라 그냥 안 보인다.
        assert colors.readable("#1B4DFF", "#1B4DFF", "#FFFFFF", 3.0) == "#FFFFFF"


class TestThemeMarks:
    @pytest.mark.parametrize("name", sorted(theme.THEMES))
    @pytest.mark.parametrize("kind", ["cover", "body", "outro"])
    def test_marks_are_visible_on_every_background(self, name, kind):
        t = theme.THEMES[name]
        bg, _ = t.colors(kind)
        accent, muted = t.marks(kind)
        assert colors.contrast(accent, bg) >= 3.0
        assert colors.contrast(muted, bg) >= 2.5

    @pytest.mark.parametrize("name", sorted(theme.THEMES))
    @pytest.mark.parametrize("kind", ["cover", "body"])
    def test_body_text_is_legible(self, name, kind):
        # WCAG AA 본문 기준(4.5:1). 카드 글씨는 이보다 훨씬 커서 여유가 있다.
        bg, fg = theme.THEMES[name].colors(kind)
        assert colors.contrast(fg, bg) >= 4.5

    def test_unknown_theme_raises(self):
        with pytest.raises(ValueError):
            theme.resolve("없는테마")


class TestSize:
    def test_named(self):
        assert (resolve_size("post").width, resolve_size("post").height) == (1080, 1350)

    def test_explicit(self):
        size = resolve_size("800x600")
        assert (size.width, size.height) == (800, 600)

    def test_rejects_unknown(self):
        with pytest.raises(ValueError):
            resolve_size("가로로긴거")

    def test_rejects_zero(self):
        with pytest.raises(ValueError):
            resolve_size("0x100")


class TestRender:
    """실제로 그려 보는 연기 테스트. Pillow/글꼴이 없으면 건너뛴다."""

    @pytest.fixture
    def style(self):
        pytest.importorskip("PIL")
        from capcut_auto.cardnews import build_style, fonts

        try:
            return build_style(theme.resolve("light"), resolve_size("post"))
        except fonts.FontMissing:
            pytest.skip("한글 글꼴이 없는 환경")

    def test_card_has_requested_size(self, style):
        from capcut_auto.cardnews import render_card

        image = render_card(Card(title="제목", body="본문", kind="cover"), style, "1/3")
        assert image.size == (1080, 1350)

    def test_deck_files_are_numbered_in_order(self, style, tmp_path):
        from capcut_auto.cardnews import render_deck

        deck = script.parse("# 표지\n---\n둘째\n---\n셋째")
        paths = render_deck(deck, tmp_path, style)
        assert [p.name for p in paths] == ["01.png", "02.png", "03.png"]
        assert all(p.stat().st_size > 0 for p in paths)

    def test_long_text_still_renders(self, style):
        from capcut_auto.cardnews import render_card

        card = Card(title="아주" * 60, body="긴본문" * 200, kind="body")
        assert render_card(card, style, "2/9").size == (1080, 1350)

    def test_body_only_card(self, style):
        from capcut_auto.cardnews import render_card

        assert render_card(Card(body="제목 없는 카드"), style, "").size == (1080, 1350)
