"""표 카드와 막대 카드."""

import pytest

from capcut_auto.cardnews import chart, colors, script, theme

pytest.importorskip("PIL")


class TestParseBars:
    def test_label_and_value(self):
        bars = chart.parse_bars("2024년 | 5000")
        assert (bars[0].label, bars[0].value) == ("2024년", 5000.0)

    def test_commas_in_the_number(self):
        assert chart.parse_bars("가 | 1,234")[0].value == 1234.0

    def test_thousands_separator_in_the_label(self):
        assert chart.parse_bars("가 | 5000", unit="만원")[0].display == "5,000만원"

    def test_third_column_overrides_the_display(self):
        # 1억을 "10,000만원"이라 쓰면 안 읽힌다.
        assert chart.parse_bars("가 | 10000 | 1억원")[0].display == "1억원"

    def test_last_row_is_emphasised_by_default(self):
        bars = chart.parse_bars("가 | 1\n나 | 2\n다 | 3")
        assert [b.emphasis for b in bars] == [False, False, True]

    def test_explicit_star_wins(self):
        bars = chart.parse_bars("가 | 1 *\n나 | 2\n다 | 3")
        assert [b.emphasis for b in bars] == [True, False, False]

    def test_skips_lines_without_a_number(self):
        assert len(chart.parse_bars("가 | 없음\n나 | 5")) == 1

    def test_skips_lines_without_a_pipe(self):
        assert chart.parse_bars("그냥 문장입니다") == []

    def test_blank_body(self):
        assert chart.parse_bars("") == []

    def test_decimals(self):
        assert chart.parse_bars("가 | 0.015")[0].value == pytest.approx(0.015)


class TestFormatNumber:
    @pytest.mark.parametrize(
        "value,text", [(5000, "5,000"), (1000000, "1,000,000"), (7, "7"), (0.5, "0.5")]
    )
    def test_formats(self, value, text):
        assert chart.format_number(value) == text


class TestParseTable:
    body = "종류 | 보호\n종금형 | O *\nRP형 | X"

    def test_first_row_is_the_header(self):
        assert chart.parse_table(self.body).header == ["종류", "보호"]

    def test_rows_exclude_the_header(self):
        assert chart.parse_table(self.body).rows == [["종금형", "O"], ["RP형", "X"]]

    def test_star_marks_the_row(self):
        assert chart.parse_table(self.body).emphasis == {0}

    def test_no_emphasis_by_default(self):
        assert chart.parse_table("가 | 나\n다 | 라").emphasis == set()

    def test_empty(self):
        table = chart.parse_table("")
        assert table.rows == [] and table.header == []


class TestDeEmphasisColor:
    @pytest.mark.parametrize("name", sorted(theme.THEMES))
    def test_grey_bar_is_visible_on_the_surface(self, name):
        # 도형은 3:1 이 기준이다. 그보다 옅으면 막대가 있는지도 모른다.
        bg, fg = theme.THEMES[name].colors("body")
        assert colors.contrast(colors.de_emphasis(fg, bg), bg) >= 3.0

    @pytest.mark.parametrize("name", sorted(theme.THEMES))
    def test_accent_bar_is_visible_too(self, name):
        bg, _ = theme.THEMES[name].colors("body")
        assert colors.contrast(theme.THEMES[name].marks("body")[0], bg) >= 3.0


class TestBarGeometry:
    """길이가 값에 비례하는지 실제 픽셀로 잰다 — 여기가 깨지면 그래프가 거짓말을 한다."""

    @pytest.fixture
    def style(self):
        from capcut_auto.cardnews import build_style, fonts, resolve_size, resolve_theme

        try:
            return build_style(resolve_theme("light"), resolve_size("post"))
        except fonts.FontMissing:
            pytest.skip("한글 글꼴이 없는 환경")

    @staticmethod
    def widths(image, style):
        """강조 막대와 회색 막대 각각의 가장 긴 가로 길이 (픽셀).

        색으로 구분한다 — 행 단위로 세면 안티앨리어싱 때문에 같은 막대가
        여러 값으로 잡힌다.
        """
        bg, fg = style.theme.colors("body")
        targets = {
            "accent": bytes(colors.parse(style.theme.marks("body")[0])),
            "grey": bytes(colors.parse(colors.de_emphasis(fg, bg))),
        }
        raw, w, h = image.tobytes(), image.width, image.height
        out = {}
        for name, pattern in targets.items():
            best = 0
            for y in range(h):
                row = raw[y * w * 3 : (y + 1) * w * 3]
                best = max(best, row.count(pattern))
            out[name] = best
        return out

    def test_half_the_value_is_half_the_bar(self, style):
        from capcut_auto.cardnews import render_card
        from capcut_auto.cardnews.models import Card

        # 마지막 줄이 기본 강조라 "지금"(10000)이 강조색이다.
        card = Card(title="한도", body="예전 | 5000\n지금 | 10000", kind="bars")
        w = self.widths(render_card(card, style, "1/2"), style)
        assert w["accent"] > 0 and w["grey"] > 0
        assert w["grey"] / w["accent"] == pytest.approx(0.5, abs=0.04)

    def test_a_small_value_is_not_inflated(self, style):
        from capcut_auto.cardnews import render_card
        from capcut_auto.cardnews.models import Card

        # 굵기를 최소 길이로 쓰던 시절엔 작은 값이 굵기만큼 부풀어 올랐다.
        card = Card(title="비교", body="큰 값 | 1000 *\n작은 값 | 50", kind="bars")
        w = self.widths(render_card(card, style, "1/2"), style)
        assert w["grey"] / w["accent"] < 0.12

    def test_equal_values_are_equal_bars(self, style):
        from capcut_auto.cardnews import render_card
        from capcut_auto.cardnews.models import Card

        card = Card(title="같음", body="가 | 700\n나 | 700", kind="bars")
        w = self.widths(render_card(card, style, "1/2"), style)
        assert w["grey"] / w["accent"] == pytest.approx(1.0, abs=0.02)

    def test_bars_stay_thin(self, style):
        from capcut_auto.cardnews import render_card
        from capcut_auto.cardnews.models import Card

        # 두꺼운 채색 블록은 카드가 유치해 보이는 가장 빠른 길이다.
        card = Card(title="한도", body="가 | 1\n나 | 2", kind="bars")
        image = render_card(card, style, "1/2")
        pattern = bytes(colors.parse(style.theme.marks("body")[0]))
        raw, w = image.tobytes(), image.width
        rows = sum(
            1
            for y in range(image.height)
            if raw[y * w * 3 : (y + 1) * w * 3].count(pattern)
        )
        assert rows <= style.size.height * 0.06


class TestChartCardsRender:
    @pytest.fixture
    def style(self):
        from capcut_auto.cardnews import build_style, fonts, resolve_size, resolve_theme

        try:
            return build_style(resolve_theme("dark"), resolve_size("post"))
        except fonts.FontMissing:
            pytest.skip("한글 글꼴이 없는 환경")

    def test_table_card(self, style):
        from capcut_auto.cardnews import render_card

        deck = script.parse("@표\n## 비교\n종류 | 보호\n가 | O *\n나 | X")
        assert render_card(deck.cards[0], style, "1/1").size == (1080, 1350)

    def test_bar_card(self, style):
        from capcut_auto.cardnews import render_card

        deck = script.parse("@막대 만원\n## 한도\n가 | 5000\n나 | 10000")
        assert render_card(deck.cards[0], style, "1/1").size == (1080, 1350)

    def test_directive_sets_kind_and_unit(self):
        card = script.parse("@막대 만원\n## 한도\n가 | 5000").cards[0]
        assert (card.kind, card.unit) == ("bars", "만원")

    def test_table_directive(self):
        assert script.parse("@표\n## 비교\n가 | 나").cards[0].kind == "table"

    def test_chart_cards_never_get_a_photo(self):
        from capcut_auto.cardnews import photos
        from capcut_auto.cardnews.models import Card

        # 표·그래프 위에 사진을 깔면 둘 다 안 읽힌다.
        assert photos.mode_for(Card(kind="bars")) == photos.NONE
        assert photos.mode_for(Card(kind="table")) == photos.NONE

    def test_empty_chart_body_still_renders(self, style):
        from capcut_auto.cardnews import render_card
        from capcut_auto.cardnews.models import Card

        assert render_card(Card(title="빈 표", kind="table"), style, "").size == (1080, 1350)
