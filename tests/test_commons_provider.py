"""위키미디어 커먼즈 제공자 — 자유 라이선스만 쓰고 저작자를 챙긴다."""

import pytest

from capcut_auto.assets import providers
from capcut_auto.assets.providers import CommonsProvider
from capcut_auto.config import AssetsConfig


def page(pageid, licence, width=1600, author="<a href='x'>홍길동</a>", url=True):
    info = {
        "width": width,
        "thumbwidth": width,
        "thumbheight": int(width * 0.75),
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{pageid}.jpg",
        "extmetadata": {
            "LicenseShortName": {"value": licence},
            "Artist": {"value": author},
        },
    }
    if url:
        info["thumburl"] = f"https://upload.wikimedia.org/{pageid}.jpg"
    return {"pageid": pageid, "title": f"File:{pageid}.jpg", "imageinfo": [info]}


def respond(monkeypatch, pages):
    payload = {"query": {"pages": {str(p["pageid"]): p for p in pages}}}
    monkeypatch.setattr(providers, "_get_json", lambda *a, **k: payload)


class TestLicenceFilter:
    @pytest.mark.parametrize(
        "licence", ["CC0", "CC BY 4.0", "CC BY-SA 3.0", "Public domain", "PD-US"]
    )
    def test_free_licences_pass(self, monkeypatch, licence):
        respond(monkeypatch, [page(1, licence)])
        assert len(CommonsProvider().search("은행", "image", 5)) == 1

    @pytest.mark.parametrize(
        "licence",
        ["GFDL", "Fair use", "Copyrighted free use with restrictions", "All rights reserved"],
    )
    def test_unfree_licences_are_dropped(self, monkeypatch, licence):
        # 여기서 틀리면 자유 라이선스라고 믿고 남의 사진을 쓰게 된다.
        respond(monkeypatch, [page(1, licence)])
        assert CommonsProvider().search("은행", "image", 5) == []

    def test_missing_licence_is_dropped(self, monkeypatch):
        respond(monkeypatch, [page(1, "")])
        assert CommonsProvider().search("은행", "image", 5) == []


class TestQuality:
    def test_small_images_are_dropped(self, monkeypatch):
        respond(monkeypatch, [page(1, "CC BY 4.0", width=320)])
        assert CommonsProvider().search("은행", "image", 5) == []

    def test_large_enough_passes(self, monkeypatch):
        respond(monkeypatch, [page(1, "CC BY 4.0", width=1600)])
        assert len(CommonsProvider().search("은행", "image", 5)) == 1

    def test_entry_without_a_url_is_skipped(self, monkeypatch):
        respond(monkeypatch, [page(1, "CC BY 4.0", url=False)])
        assert CommonsProvider().search("은행", "image", 5) == []


class TestCredit:
    def test_author_html_is_stripped(self, monkeypatch):
        respond(monkeypatch, [page(1, "CC BY 4.0", author='<a href="/x">Jane Doe</a>')])
        assert CommonsProvider().search("은행", "image", 1)[0].credit == "Jane Doe / CC BY 4.0"

    def test_entities_are_unescaped(self, monkeypatch):
        respond(monkeypatch, [page(1, "CC BY-SA 3.0", author="Tom &amp; Jerry")])
        assert "Tom & Jerry" in CommonsProvider().search("은행", "image", 1)[0].credit

    def test_missing_author_falls_back(self, monkeypatch):
        respond(monkeypatch, [page(1, "CC0", author="")])
        assert "Wikimedia Commons" in CommonsProvider().search("은행", "image", 1)[0].credit

    def test_page_url_is_kept(self, monkeypatch):
        # CC BY 는 출처 표시가 의무라 원본 페이지 주소가 있어야 한다.
        respond(monkeypatch, [page(7, "CC BY 4.0")])
        assert CommonsProvider().search("은행", "image", 1)[0].page_url.endswith("File:7.jpg")


class TestSearch:
    def test_only_images(self):
        p = CommonsProvider()
        assert p.supports("image") and not p.supports("video")

    def test_video_search_returns_nothing(self, monkeypatch):
        respond(monkeypatch, [page(1, "CC0")])
        assert CommonsProvider().search("은행", "video", 5) == []

    def test_respects_the_limit(self, monkeypatch):
        respond(monkeypatch, [page(i, "CC0") for i in range(1, 11)])
        assert len(CommonsProvider().search("은행", "image", 3)) == 3

    def test_empty_response(self, monkeypatch):
        monkeypatch.setattr(providers, "_get_json", lambda *a, **k: {})
        assert CommonsProvider().search("은행", "image", 5) == []


class TestWiring:
    def test_enabled_without_any_key(self):
        # 키가 필요 없다는 게 핵심이다 — 아무 설정 없이도 사진이 붙어야 한다.
        names = [p.name for p in providers.build_providers(AssetsConfig())]
        assert "commons" in names

    def test_can_be_turned_off(self):
        names = [p.name for p in providers.build_providers(AssetsConfig(use_commons=False))]
        assert "commons" not in names


class TestEndToEnd:
    """검색 → 내려받기 → 카드까지. 실제 망을 타지 않고 경로만 확인한다."""

    @pytest.fixture
    def style(self):
        from capcut_auto.cardnews import build_style, fonts, resolve_size, resolve_theme

        try:
            return build_style(
                resolve_theme("light"), resolve_size("post"), handle="@내계정"
            )
        except fonts.FontMissing:
            pytest.skip("한글 글꼴이 없는 환경")

    @pytest.fixture
    def fake_download(self, monkeypatch, tmp_path):
        """커먼즈에서 받아온 척하고 진짜 이미지 파일을 돌려준다."""
        from PIL import Image

        from capcut_auto.assets import cache
        from capcut_auto.assets.models import Asset

        def fetch(ref, cache_dir, query=""):
            path = tmp_path / f"{ref.source_id}.png"
            Image.new("RGB", (1600, 1200), (40, 60, 90)).save(path)
            return Asset(
                kind="image",
                path=path,
                source=ref.source,
                source_id=ref.source_id,
                width=1600,
                height=1200,
                credit=ref.credit,
                page_url=ref.page_url,
                query=query,
            )

        monkeypatch.setattr(cache, "fetch", fetch)
        import capcut_auto.cardnews.photos as photos_mod

        monkeypatch.setattr(photos_mod.asset_cache, "fetch", fetch)

    def test_deck_gets_photos_without_any_api_key(
        self, monkeypatch, fake_download, style, tmp_path
    ):
        from capcut_auto.cardnews import collect_photos, parse, render_deck

        respond(monkeypatch, [page(i, "CC BY 4.0") for i in range(1, 6)])
        deck = parse("# 은행 예금\n통장\n---\n## 월세 계약서\n영수증")
        found = collect_photos(
            deck, providers.build_providers(AssetsConfig()), tmp_path / "cache"
        )
        assert found, "키 없이도 사진이 붙어야 한다"
        paths = render_deck(deck, tmp_path / "out", style, photos=found)
        assert all(p.stat().st_size > 0 for p in paths)

    def test_attribution_lists_every_photo(
        self, monkeypatch, fake_download, style, tmp_path
    ):
        from capcut_auto.cardnews import collect_photos, parse, photo_attribution

        respond(monkeypatch, [page(i, "CC BY 4.0", author=f"작가{i}") for i in range(1, 6)])
        deck = parse("# 은행 예금\n통장\n---\n## 월세 계약서\n영수증")
        found = collect_photos(
            deck, providers.build_providers(AssetsConfig()), tmp_path / "cache"
        )
        notes = photo_attribution(found)
        # CC BY 는 저작자 표시가 의무다. 빠지면 자유 라이선스라도 위반이다.
        for asset in found.values():
            assert asset.credit in notes
            assert asset.page_url in notes

    def test_unfree_results_never_reach_the_card(
        self, monkeypatch, fake_download, tmp_path
    ):
        from capcut_auto.cardnews import collect_photos, parse

        respond(monkeypatch, [page(i, "Fair use") for i in range(1, 6)])
        deck = parse("# 은행 예금\n통장")
        assert collect_photos(
            deck, providers.build_providers(AssetsConfig()), tmp_path / "cache"
        ) == {}
