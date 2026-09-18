"""표지 포스터 배치 — 그라데이션 장막, 말머리, 제목 색 나눔, 알약, 점."""

import pytest

from capcut_auto.cardnews import colors, compose, poster, script, theme
from capcut_auto.cardnews.models import Card

pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402


def solid(color, size=(400, 600)):
    return Image.new("RGB", size, color)


def bright_at(band, size=(400, 600)):
    """`band`(0~1) 높이에만 아주 밝은 띠가 있는 사진."""
    img = Image.new("RGB", size, (20, 20, 20))
    y = int(size[1] * band)
    ImageDraw.Draw(img).rectangle([0, y, size[0], y + 60], fill=(252, 252, 252))
    return img


class TestGradientScrim:
    def test_top_is_untouched(self):
        img = solid((240, 240, 240))
        out = compose.gradient_scrim(img, "#000000", 0.9, start=0.30, hold=0.60)
        assert out.getpixel((200, 10)) == (240, 240, 240)

    def test_hold_region_gets_the_full_peak(self):
        # 여기가 두 번 깨졌다 — 맨 밑에서만 peak 에 닿으면 제목이 묻힌다.
        img = solid((240, 240, 240))
        out = compose.gradient_scrim(img, "#000000", 1.0, start=0.20, hold=0.50)
        assert out.getpixel((200, 320)) == (0, 0, 0)  # hold 지점 바로 아래
        assert out.getpixel((200, 590)) == (0, 0, 0)

    def test_ramp_is_monotonic(self):
        img = solid((240, 240, 240))
        out = compose.gradient_scrim(img, "#000000", 0.9, start=0.10, hold=0.90)
        lums = [colors.luminance_rgb(out.getpixel((200, y))) for y in range(0, 600, 40)]
        assert all(a >= b - 1e-6 for a, b in zip(lums, lums[1:]))

    def test_peak_is_clamped(self):
        img = solid((240, 240, 240))
        assert compose.gradient_scrim(img, "#000000", 5.0).getpixel((200, 590)) == (0, 0, 0)

    @pytest.mark.parametrize("band", [0.45, 0.60, 0.80])
    def test_measured_scrim_makes_the_text_area_legible(self, band):
        """밝은 띠가 글 구간 어디에 있든 흰 글씨가 읽혀야 한다."""
        img = bright_at(band)
        box = (0, int(600 * 0.40), 400, 600)
        peak = compose.scrim_alpha(img, box, "#FFFFFF", "#16181D", minimum=4.5)
        out = compose.gradient_scrim(img, "#16181D", peak, start=0.10, hold=0.40)
        worst = compose.extreme_luminance(out, box, bright=True)
        assert colors.contrast_lum(colors.luminance("#FFFFFF"), worst) >= 4.5


class TestSplitTitle:
    def test_splits_on_the_bar(self):
        assert poster.split_title("나스닥은 축포 | 코스피는 급락") == [
            "나스닥은 축포",
            "코스피는 급락",
        ]

    def test_no_bar_is_one_piece(self):
        assert poster.split_title("한 줄 제목") == ["한 줄 제목"]

    def test_ignores_empty_pieces(self):
        assert poster.split_title("가 | | 나") == ["가", "나"]

    def test_separator_only_keeps_the_raw_text(self):
        # 조용히 비우면 왜 아무것도 안 나오는지 알 수가 없다. 원문을 남긴다.
        assert poster.split_title("|") == ["|"]


class TestTextAccent:
    @pytest.mark.parametrize("name", sorted(theme.THEMES))
    def test_accent_as_text_clears_the_text_floor(self, name):
        # 마크는 3:1 이면 되지만 글씨는 4.5:1 이다.
        t = theme.THEMES[name]
        bg, _ = t.colors("cover")
        assert colors.contrast(t.text_accent("cover"), bg) >= 4.5

    def test_bold_cover_does_not_collapse_to_the_ink(self):
        # 표지 배경이 곧 강조색인 테마는 표지 전용 강조색을 써야 한다.
        t = theme.THEMES["bold"]
        _, fg = t.colors("cover")
        assert t.text_accent("cover") != fg


class TestDirectives:
    def test_kicker(self):
        assert script.parse("@말머리 그 후 사흘\n# 제목").cards[0].kicker == "그 후 사흘"

    def test_cta(self):
        assert script.parse("@버튼 저장!\n# 제목").cards[0].cta == "저장!"

    def test_english_names(self):
        card = script.parse("@kicker 하나\n@cta 둘\n# 제목").cards[0]
        assert (card.kicker, card.cta) == ("하나", "둘")

    def test_directives_stack_with_the_kind(self):
        card = script.parse("@말머리 앞\n@사진 bank\n# 제목\n부제").cards[0]
        assert card.kind == "cover" and card.kicker == "앞" and card.image_query == "bank"


class TestDotsAndPill:
    def px(self, ratio):
        return int(1080 * ratio)

    @pytest.fixture
    def style(self):
        from capcut_auto.cardnews import build_style, fonts, resolve_size, resolve_theme

        try:
            return build_style(resolve_theme("light"), resolve_size("post"))
        except fonts.FontMissing:
            pytest.skip("한글 글꼴이 없는 환경")

    def test_no_dots_for_a_single_card(self, style):
        assert poster.dots_height(style, 1, self.px) == 0.0

    def test_no_dots_when_there_are_too_many(self, style):
        # 점이 뭉개지면 없느니만 못하다.
        assert poster.dots_height(style, 20, self.px) == 0.0

    def test_dots_for_a_normal_deck(self, style):
        assert poster.dots_height(style, 7, self.px) > 0

    def test_pill_height_zero_without_text(self, style):
        assert poster.pill_height("", style, self.px) == 0.0

    def test_pill_height_positive(self, style):
        assert poster.pill_height("저장", style, self.px) > 0


class TestCoverRender:
    @pytest.fixture
    def style(self):
        from capcut_auto.cardnews import build_style, fonts, resolve_size, resolve_theme

        try:
            return build_style(
                resolve_theme("light"), resolve_size("post"), handle="@myshop"
            )
        except fonts.FontMissing:
            pytest.skip("한글 글꼴이 없는 환경")

    def card(self):
        return script.parse(
            "@말머리 그 후 사흘\n@버튼 저장!\n# 나스닥은 축포 | 코스피는 급락\n부제입니다"
        ).cards[0]

    def test_renders_at_size(self, style):
        from capcut_auto.cardnews import render_card

        assert render_card(self.card(), style, "1/4", total=4).size == (1080, 1350)

    def test_accent_line_uses_the_text_accent(self, style):
        from capcut_auto.cardnews import render_card

        image = render_card(self.card(), style, "1/4", total=4)
        wanted = bytes(colors.parse(style.theme.text_accent("cover")))
        assert image.tobytes().count(wanted) > 0

    def test_dots_change_with_the_index(self, style):
        from capcut_auto.cardnews import render_card

        first = render_card(self.card(), style, "1/4", total=4)
        card = self.card()
        card.index = 2
        assert first.tobytes() != render_card(card, style, "3/4", total=4).tobytes()

    def test_survives_a_broken_photo(self, style, tmp_path):
        from capcut_auto.assets.models import Asset
        from capcut_auto.cardnews import render_card

        broken = tmp_path / "x.png"
        broken.write_bytes(b"nope")
        asset = Asset(kind="image", path=broken, source="local", source_id="x")
        assert render_card(
            self.card(), style, "1/4", photo=asset, total=4
        ).size == (1080, 1350)

    def test_cover_without_any_extras(self, style):
        from capcut_auto.cardnews import render_card

        assert render_card(Card(title="제목만", kind="cover"), style, "").size == (
            1080,
            1350,
        )
