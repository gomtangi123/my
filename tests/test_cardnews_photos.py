"""사진 깔기 — 검색어 만들기, 어느 카드에 깔지, 사진 위 글씨 대비."""

import pytest

from capcut_auto.assets.models import AssetRef
from capcut_auto.cardnews import colors, compose, photos, script
from capcut_auto.cardnews.models import Card

pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402


def solid(color, size=(400, 300)):
    return Image.new("RGB", size, color)


def speckled(base, spot, size=(400, 300)):
    """대체로 어둡지만 밝은 얼룩이 있는 사진 — 평균만 재면 속는 경우."""
    img = Image.new("RGB", size, base)
    ImageDraw.Draw(img).ellipse([40, 40, 200, 200], fill=spot)
    return img


class TestCoverCrop:
    def test_returns_exact_size(self):
        out = compose.cover_crop(solid((10, 20, 30), (800, 200)), 300, 300)
        assert out.size == (300, 300)

    def test_fills_without_letterbox(self):
        # 가로로 긴 사진을 세로 카드에 넣어도 빈 띠가 생기면 안 된다.
        out = compose.cover_crop(solid((200, 30, 30), (1000, 100)), 200, 500)
        assert out.getpixel((0, 0)) == out.getpixel((199, 499)) == (200, 30, 30)

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            compose.cover_crop(Image.new("RGB", (0, 0)), 10, 10)


class TestExtremeLuminance:
    box = (0, 0, 400, 300)

    def test_white_is_bright(self):
        assert compose.extreme_luminance(solid((255, 255, 255)), self.box, True) > 0.9

    def test_black_is_dark(self):
        assert compose.extreme_luminance(solid((0, 0, 0)), self.box, False) < 0.05

    def test_bright_flag_finds_the_spot(self):
        img = speckled((20, 20, 20), (250, 250, 250))
        bright = compose.extreme_luminance(img, self.box, True)
        dark = compose.extreme_luminance(img, self.box, False)
        assert bright > 0.5 > dark

    def test_box_outside_image_is_safe(self):
        assert compose.extreme_luminance(solid((0, 0, 0)), (900, 900, 950, 950), True)


class TestScrimAlpha:
    box = (0, 0, 400, 300)

    def test_bright_photo_needs_a_heavier_scrim(self):
        light = compose.scrim_alpha(solid((250, 250, 250)), self.box, "#FFFFFF", "#16181D")
        dark = compose.scrim_alpha(solid((20, 22, 26)), self.box, "#FFFFFF", "#16181D")
        assert light > dark

    def test_dark_photo_stays_visible(self):
        # 어두운 사진까지 새까맣게 덮으면 사진을 깐 의미가 없다.
        alpha = compose.scrim_alpha(solid((20, 22, 26)), self.box, "#FFFFFF", "#16181D")
        assert alpha <= 0.45

    def test_a_bright_spot_drives_the_scrim(self):
        # 평균으로 쟀다면 옅은 장막이 걸리고 얼룩 위에서 글씨가 사라진다.
        img = speckled((20, 20, 20), (252, 252, 252))
        assert compose.scrim_alpha(img, self.box, "#FFFFFF", "#16181D") >= 0.65

    @pytest.mark.parametrize("fill", [(255, 255, 255), (128, 130, 135), (5, 5, 5)])
    def test_result_actually_meets_the_target(self, fill):
        img = solid(fill)
        alpha = compose.scrim_alpha(img, self.box, "#FFFFFF", "#16181D", minimum=4.5)
        worst = compose.extreme_luminance(img, self.box, bright=True)
        mixed = compose._blend_luminance(worst, colors.parse("#16181D"), alpha)
        assert colors.contrast_lum(colors.luminance("#FFFFFF"), mixed) >= 4.5

    def test_falls_back_to_the_heaviest_when_impossible(self):
        # 흰 장막 + 흰 글씨는 어떤 진하기로도 안 된다. 그래도 카드는 나와야 한다.
        assert compose.scrim_alpha(
            solid((255, 255, 255)), self.box, "#FFFFFF", "#FFFFFF"
        ) == compose.ALPHAS[-1]


class TestApplyScrim:
    def test_full_alpha_is_the_veil(self):
        out = compose.apply_scrim(solid((250, 10, 10)), "#000000", 1.0)
        assert out.getpixel((0, 0)) == (0, 0, 0)

    def test_zero_alpha_keeps_the_photo(self):
        assert compose.apply_scrim(solid((250, 10, 10)), "#000000", 0.0).getpixel((0, 0)) == (250, 10, 10)

    def test_alpha_is_clamped(self):
        assert compose.apply_scrim(solid((250, 10, 10)), "#000000", 5.0).getpixel((0, 0)) == (0, 0, 0)


class TestModeFor:
    def test_defaults_by_kind(self):
        assert photos.mode_for(Card(kind="cover")) == photos.FULL
        assert photos.mode_for(Card(kind="body")) == photos.BAND
        # 숫자 카드는 수치가 그림이다 — 사진을 깔면 지저분해진다.
        assert photos.mode_for(Card(kind="stat")) == photos.NONE
        assert photos.mode_for(Card(kind="outro")) == photos.NONE

    def test_override_wins(self):
        assert photos.mode_for(Card(kind="stat"), "full") == photos.FULL
        assert photos.mode_for(Card(kind="cover"), "off") == photos.NONE

    def test_card_can_opt_out_even_against_an_override(self):
        assert photos.mode_for(Card(kind="cover", image_off=True), "full") == photos.NONE

    def test_unknown_kind_falls_back_to_band(self):
        assert photos.mode_for(Card(kind="무엇")) == photos.BAND


class TestQueryFor:
    def test_explicit_query_wins(self):
        card = Card(title="아무 말", image_query="piggy bank")
        assert photos.query_for(card) == "piggy bank"

    def test_translates_korean_to_english(self):
        assert "savings" in photos.query_for(Card(title="예금", body="통장"))

    def test_drops_untranslated_words_when_english_exists(self):
        # 영어에 한국어를 섞으면 스톡 검색이 오히려 나빠진다.
        query = photos.query_for(Card(title="월세", body="왕왕왕 둠둠둠"))
        assert "왕왕왕" not in query and "apartment" in query

    def test_keeps_korean_when_nothing_translates(self):
        # 내 사진 폴더를 한글 이름으로 쓰는 사람도 있다.
        assert photos.query_for(Card(title="왕왕왕 둠둠둠"))

    def test_folds_duplicate_words(self):
        query = photos.query_for(Card(title="은행", body="예금자보호"))
        assert query.split().count("bank") == 1

    def test_empty_card_gives_no_query(self):
        assert photos.query_for(Card()) == ""

    def test_numbers_are_not_keywords(self):
        assert "5,000" not in photos.query_for(Card(title="5,000만원", body="예금"))


class FakeProvider:
    """로컬 파일을 그대로 돌려주는 제공자. 네트워크를 타지 않는다."""

    def __init__(self, paths):
        self.paths = paths
        self.queries = []

    def supports(self, kind):
        return kind == "image"

    def search(self, query, kind, limit=5):
        self.queries.append(query)
        return [
            AssetRef(kind="image", url=str(p), source="local", source_id=p.name)
            for p in self.paths
        ]


class TestCollect:
    @pytest.fixture
    def images(self, tmp_path):
        out = []
        for i, shade in enumerate([(30, 30, 30), (200, 200, 200)]):
            path = tmp_path / f"p{i}.png"
            solid(shade).save(path)
            out.append(path)
        return out

    def test_no_providers_means_no_photos(self, tmp_path):
        deck = script.parse("# 예금\n---\n## 통장\n은행")
        assert photos.collect(deck, [], tmp_path) == {}

    def test_assigns_to_cards_that_want_photos(self, tmp_path, images):
        deck = script.parse("# 예금 통장\n---\n## 은행 계좌\n저축\n---\n@숫자\n1억원\n한도")
        found = photos.collect(deck, [FakeProvider(images)], tmp_path)
        assert set(found) == {0, 1}  # 숫자 카드(2번)는 빠진다

    def test_never_reuses_the_same_photo(self, tmp_path, images):
        deck = script.parse("# 예금 통장\n---\n## 은행 계좌\n저축\n---\n## 월세 계약서\n영수증")
        found = photos.collect(deck, [FakeProvider(images)], tmp_path)
        ids = [a.source_id for a in found.values()]
        assert len(ids) == len(set(ids))

    def test_runs_out_of_photos_gracefully(self, tmp_path, images):
        deck = script.parse("\n---\n".join(f"## 예금 통장 {i}\n은행" for i in range(5)))
        found = photos.collect(deck, [FakeProvider(images)], tmp_path)
        assert 0 < len(found) <= len(images)

    def test_credits_lists_each_source_once(self, tmp_path, images):
        deck = script.parse("# 예금 통장\n---\n## 은행 계좌\n저축")
        found = photos.collect(deck, [FakeProvider(images)], tmp_path)
        assert photos.credits(found) == "사진: local"

    def test_credits_empty_without_photos(self):
        assert photos.credits({}) == ""


class TestRenderWithPhoto:
    @pytest.fixture
    def style(self):
        from capcut_auto.cardnews import build_style, fonts, resolve_size, resolve_theme

        try:
            return build_style(resolve_theme("light"), resolve_size("post"))
        except fonts.FontMissing:
            pytest.skip("한글 글꼴이 없는 환경")

    @pytest.fixture
    def asset(self, tmp_path):
        from capcut_auto.assets.models import Asset

        path = tmp_path / "photo.png"
        speckled((30, 40, 60), (240, 240, 240), (900, 700)).save(path)
        return Asset(kind="image", path=path, source="local", source_id="photo")

    def test_full_mode_changes_the_card(self, style, asset):
        from dataclasses import replace

        from capcut_auto.cardnews import render_card

        card = Card(title="제목", body="본문", kind="cover")
        plain = render_card(card, style, "1/3")
        withphoto = render_card(
            card, replace(style, photo_mode="full"), "1/3", photo=asset
        )
        assert plain.tobytes() != withphoto.tobytes()

    def test_band_mode_puts_the_photo_on_top(self, style, asset):
        from dataclasses import replace

        from capcut_auto.cardnews import render_card

        image = render_card(
            Card(title="제목", body="본문", kind="body"),
            replace(style, photo_mode="band"),
            "2/3",
            photo=asset,
        )
        band_h = int(round(style.size.height * style.layout.band))
        # 띠 안쪽은 사진이고, 띠 바로 아래는 테마 바탕색이어야 한다.
        assert image.getpixel((540, band_h // 2)) != colors.parse(style.theme.bg)
        assert image.getpixel((540, band_h + 5)) == colors.parse(style.theme.bg)

    def test_a_broken_photo_still_renders(self, style, tmp_path):
        from dataclasses import replace

        from capcut_auto.assets.models import Asset
        from capcut_auto.cardnews import render_card

        broken = tmp_path / "broken.png"
        broken.write_bytes(b"not an image")
        asset = Asset(kind="image", path=broken, source="local", source_id="x")
        image = render_card(
            Card(title="제목", kind="cover"),
            replace(style, photo_mode="full"),
            "1/1",
            photo=asset,
        )
        assert image.size == (1080, 1350)

    def test_stat_card_ignores_a_photo_in_auto(self, style, asset):
        from capcut_auto.cardnews import render_card

        card = Card(title="1억원", body="한도", kind="stat")
        assert render_card(card, style, "2/3").tobytes() == render_card(
            card, style, "2/3", photo=asset
        ).tobytes()
