import pytest

from capcut_auto import keywords as kw
from capcut_auto.assets.models import AssetRef
from capcut_auto.assets.planner import plan_assets
from capcut_auto.assets.providers import LocalProvider, Provider
from capcut_auto.config import AssetsConfig
from capcut_auto.models import EditPlan, Span, SubtitleLine, Word
from capcut_auto.timeline import TimeMap
from pathlib import Path


def words(*specs):
    return [Word(start=s, end=e, text=t) for t, s, e in specs]


def make_plan(subtitle_specs, total=60.0):
    subs = [
        SubtitleLine(text, start, end, words(*ws))
        for text, start, end, ws in subtitle_specs
    ]
    return EditPlan(
        source="dummy.mp4",
        source_duration=total,
        keeps=[Span(0, total)],
        cuts=[],
        subtitles=subs,
    )


# --------------------------------------------------------------------- 키워드


class TestParticleStripping:
    @pytest.mark.parametrize(
        "token,expected",
        [
            ("서울에서", "서울"),
            ("리액트를", "리액트"),
            ("파이썬은", "파이썬"),
            ("공부를", "공부"),
            # 사전에 '친구'가 있으므로 '들과'까지 떨어져 나간다 (검색어로는 이쪽이 낫다)
            ("친구들과", "친구"),
        ],
    )
    def test_strips(self, token, expected):
        assert kw.strip_particle(token) == expected

    @pytest.mark.parametrize("token", ["갔어요", "마셨어요", "했습니다", "그랬거든"])
    def test_verb_conjugations_are_not_keywords(self, token):
        assert kw.extract(token, use_konlpy=False) == []

    @pytest.mark.parametrize("token", ["고양이", "어린이", "아이", "우유"])
    def test_leaves_nouns_ending_in_particle_letters(self, token):
        assert kw.strip_particle(token) == token

    def test_dictionary_prefix_wins(self):
        # '고양이가' 는 '가'를 떼서 '고양이'가 되어야지 '고양'이 되면 안 된다
        assert kw.strip_particle("고양이가") == "고양이"

    def test_english_untouched(self):
        assert kw.strip_particle("python") == "python"


class TestExtract:
    def test_pulls_content_words(self):
        found = kw.extract("서울에서 커피를 마셨어요", use_konlpy=False)
        assert "서울" in found and "커피" in found

    def test_drops_stopwords(self):
        found = kw.extract("그것은 정말 진짜 이런 것", use_konlpy=False)
        assert found == []

    def test_drops_single_characters(self):
        assert kw.extract("이 그 저", use_konlpy=False) == []

    def test_deduplicates(self):
        found = kw.extract("커피 커피 커피", use_konlpy=False)
        assert found.count("커피") == 1

    def test_empty(self):
        assert kw.extract("", use_konlpy=False) == []


class TestQueryMapping:
    def test_maps_known_korean_to_english(self):
        assert kw.to_query("인공지능") == "artificial intelligence"
        assert kw.to_query("고양이") == "cat"

    def test_unknown_passes_through(self):
        assert kw.to_query("김치찌개") == "김치찌개"


class TestRanking:
    def test_rare_words_outrank_common_ones(self):
        ws = words(("반도체", 0.0, 0.5), ("회사", 0.6, 1.0))
        frequency = kw.document_frequency(
            words(*[("회사", i, i + 0.3) for i in range(8)]) + ws, use_konlpy=False
        )
        ranked = {k.text: k.score for k in kw.rank(ws, frequency, use_konlpy=False)}
        assert ranked["반도체"] > ranked["회사"]



# -------------------------------------------------------------------- 제공자


class TestLocalProvider:
    @pytest.fixture
    def folder(self, tmp_path):
        root = tmp_path / "broll"
        (root / "도시").mkdir(parents=True)
        (root / "도시" / "서울_야경.mp4").write_bytes(b"x")
        (root / "커피_클로즈업.jpg").write_bytes(b"x")
        (root / "웃음.gif").write_bytes(b"x")
        return root

    def test_finds_by_filename_tag(self, folder):
        hits = LocalProvider(folder=folder).search("서울", "video")
        assert len(hits) == 1 and hits[0].kind == "video"

    def test_finds_by_parent_folder_tag(self, folder):
        hits = LocalProvider(folder=folder).search("도시", "video")
        assert len(hits) == 1

    def test_kind_filter(self, folder):
        assert LocalProvider(folder=folder).search("커피", "video") == []
        assert len(LocalProvider(folder=folder).search("커피", "image")) == 1

    def test_gif_detected(self, folder):
        assert LocalProvider(folder=folder).search("웃음", "gif")[0].kind == "gif"

    def test_no_match(self, folder):
        assert LocalProvider(folder=folder).search("존재하지않음", "video") == []

    def test_missing_folder_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            LocalProvider(folder=tmp_path / "nope")


# --------------------------------------------------------------------- 배치


class FakeProvider(Provider):
    """검색 결과를 흉내 내는 제공자. 실제 파일을 가리킨다."""

    def __init__(self, path, kinds=("video", "image")):
        self.name = "fake"
        self.path = path
        self.kinds = kinds
        self.calls = []
        self.counter = 0

    def supports(self, kind):
        return kind in self.kinds

    def search(self, query, kind, limit=5):
        self.calls.append((query, kind))
        self.counter += 1
        return [
            AssetRef(
                kind=kind,
                url=str(self.path),
                source="local",  # 로컬 취급 -> 다운로드 없이 그대로 사용
                source_id=f"{query}-{kind}-{self.counter}",
                width=1920,
                height=1080,
                duration=8.0,
            )
        ]


@pytest.fixture
def asset_file(tmp_path):
    from PIL import Image

    path = tmp_path / "stock.png"
    Image.new("RGB", (320, 180), (10, 10, 10)).save(path)
    return path


class TestAssetPlanning:
    def test_places_an_overlay_per_selected_slot(self, tmp_path, asset_file):
        plan = make_plan(
            [
                ("서울에 갔어요", 0.0, 3.0, (("서울에", 0.0, 1.0), ("갔어요", 1.1, 3.0))),
                ("커피를 마셨어요", 10.0, 13.0, (("커피를", 10.0, 11.0), ("마셨어요", 11.1, 13.0))),
            ]
        )
        provider = FakeProvider(asset_file)
        result = plan_assets(
            plan, TimeMap(plan.keeps), AssetsConfig(), [provider], tmp_path / "cache"
        )
        assert len(result.overlays) == 2
        assert {o.keyword for o in result.overlays} == {"서울", "커피"}

    def test_translates_query_to_english(self, tmp_path, asset_file):
        plan = make_plan(
            [("고양이가 귀여워요", 0.0, 3.0, (("고양이가", 0.0, 1.0), ("귀여워요", 1.1, 3.0)))]
        )
        provider = FakeProvider(asset_file)
        plan_assets(
            plan, TimeMap(plan.keeps), AssetsConfig(), [provider], tmp_path / "cache"
        )
        assert provider.calls[0][0] == "cat"

    def test_respects_min_gap(self, tmp_path, asset_file):
        specs = [
            (f"서울{i} 이야기", i * 1.0, i * 1.0 + 0.8, ((f"서울{i}", i * 1.0, i * 1.0 + 0.8),))
            for i in range(10)
        ]
        plan = make_plan(specs)
        cfg = AssetsConfig(min_gap=2.5, max_per_minute=0)
        result = plan_assets(
            plan, TimeMap(plan.keeps), cfg, [FakeProvider(asset_file)], tmp_path / "c"
        )
        starts = sorted(o.start for o in result.overlays)
        assert all(b - a >= 2.5 for a, b in zip(starts, starts[1:]))

    def test_respects_max_per_minute(self, tmp_path, asset_file):
        specs = [
            (f"주제{i} 이야기", i * 4.0, i * 4.0 + 2.0, ((f"주제{i}", i * 4.0, i * 4.0 + 2.0),))
            for i in range(15)
        ]
        plan = make_plan(specs)
        cfg = AssetsConfig(max_per_minute=4, min_gap=0.1)
        result = plan_assets(
            plan, TimeMap(plan.keeps), cfg, [FakeProvider(asset_file)], tmp_path / "c"
        )
        assert len(result.overlays) <= 4

    def test_overlays_do_not_overlap(self, tmp_path, asset_file):
        specs = [
            (f"주제{i} 이야기", i * 3.0, i * 3.0 + 2.0, ((f"주제{i}", i * 3.0, i * 3.0 + 2.0),))
            for i in range(8)
        ]
        plan = make_plan(specs)
        result = plan_assets(
            plan,
            TimeMap(plan.keeps),
            AssetsConfig(),
            [FakeProvider(asset_file)],
            tmp_path / "c",
        )
        ordered = sorted(result.overlays, key=lambda o: o.start)
        assert all(a.end <= b.start for a, b in zip(ordered, ordered[1:]))

    def test_image_gets_pip_scale_video_fills_frame(self, tmp_path, asset_file):
        plan = make_plan([("서울 이야기", 0.0, 3.0, (("서울", 0.0, 1.0),))])
        video = plan_assets(
            plan,
            TimeMap(plan.keeps),
            AssetsConfig(prefer=("video",)),
            [FakeProvider(asset_file, kinds=("video",))],
            tmp_path / "c1",
        )
        image = plan_assets(
            plan,
            TimeMap(plan.keeps),
            AssetsConfig(prefer=("image",)),
            [FakeProvider(asset_file, kinds=("image",))],
            tmp_path / "c2",
        )
        assert video.overlays[0].scale == 1.0
        assert image.overlays[0].scale < 1.0

    def test_falls_back_to_second_kind(self, tmp_path, asset_file):
        plan = make_plan([("서울 이야기", 0.0, 3.0, (("서울", 0.0, 1.0),))])
        provider = FakeProvider(asset_file, kinds=("image",))
        result = plan_assets(
            plan,
            TimeMap(plan.keeps),
            AssetsConfig(prefer=("video", "image")),
            [provider],
            tmp_path / "c",
        )
        assert result.overlays[0].asset.kind == "image"

    def test_no_providers_yields_nothing(self, tmp_path):
        plan = make_plan([("서울 이야기", 0.0, 3.0, (("서울", 0.0, 1.0),))])
        result = plan_assets(
            plan, TimeMap(plan.keeps), AssetsConfig(), [], tmp_path / "c"
        )
        assert result.overlays == []

    def test_disabled(self, tmp_path, asset_file):
        plan = make_plan([("서울 이야기", 0.0, 3.0, (("서울", 0.0, 1.0),))])
        result = plan_assets(
            plan,
            TimeMap(plan.keeps),
            AssetsConfig(enabled=False),
            [FakeProvider(asset_file)],
            tmp_path / "c",
        )
        assert result.overlays == []

    def test_no_subtitles_yields_nothing(self, tmp_path, asset_file):
        plan = make_plan([])
        result = plan_assets(
            plan,
            TimeMap(plan.keeps),
            AssetsConfig(),
            [FakeProvider(asset_file)],
            tmp_path / "c",
        )
        assert result.overlays == []

    def test_same_asset_is_not_reused(self, tmp_path, asset_file):
        specs = [
            (f"서울 이야기{i}", i * 6.0, i * 6.0 + 2.0, (("서울", i * 6.0, i * 6.0 + 2.0),))
            for i in range(3)
        ]
        plan = make_plan(specs)
        # 같은 검색어라 캐시된 후보 1개뿐 -> 첫 자리만 채워진다
        result = plan_assets(
            plan,
            TimeMap(plan.keeps),
            AssetsConfig(),
            [FakeProvider(asset_file)],
            tmp_path / "c",
        )
        ids = [o.asset.source_id for o in result.overlays]
        assert len(ids) == len(set(ids))

    def test_budget_skips_over_slots_with_no_asset(self, tmp_path, asset_file):
        """소재를 못 찾은 자리가 개수 예산을 잡아먹으면 안 된다."""

        class PickyProvider(FakeProvider):
            def search(self, query, kind, limit=5):
                # '인공지능'만 결과가 없다
                if query in ("artificial intelligence", "인공지능"):
                    return []
                return super().search(query, kind, limit)

        plan = make_plan(
            [
                # 점수가 가장 높은(사전 등재 + 긴) 단어를 앞에 둔다
                ("인공지능 이야기", 0.0, 3.0, (("인공지능", 0.0, 2.0),)),
                ("서울 이야기", 10.0, 13.0, (("서울", 10.0, 12.0),)),
            ]
        )
        cfg = AssetsConfig(max_per_minute=1)
        result = plan_assets(
            plan, TimeMap(plan.keeps), cfg, [PickyProvider(asset_file)], tmp_path / "c"
        )
        assert [o.keyword for o in result.overlays] == ["서울"]

    def test_overlays_come_back_in_time_order(self, tmp_path, asset_file):
        specs = [
            (f"주제{i} 이야기", i * 5.0, i * 5.0 + 2.0, ((f"주제{i}", i * 5.0, i * 5.0 + 2.0),))
            for i in range(6)
        ]
        plan = make_plan(specs)
        result = plan_assets(
            plan,
            TimeMap(plan.keeps),
            AssetsConfig(max_per_minute=100),
            [FakeProvider(asset_file)],
            tmp_path / "c",
        )
        starts = [o.start for o in result.overlays]
        assert starts == sorted(starts)


class TestFullCoverage:
    """처음부터 끝까지 이미지로 덮는 모드."""

    @pytest.fixture
    def talky_plan(self):
        specs = [
            (f"주제{i} 이야기입니다", i * 4.0, i * 4.0 + 3.0,
             ((f"주제{i}", i * 4.0, i * 4.0 + 3.0),))
            for i in range(10)
        ]
        return make_plan(specs, total=40.0)

    def cfg(self, **kwargs):
        # 이 묶음은 '돌려 쓰기' 동작을 검증한다
        kwargs.setdefault("reuse", True)
        return AssetsConfig(coverage="full", **kwargs)

    def test_covers_the_whole_timeline_without_gaps(self, tmp_path, asset_file, talky_plan):
        result = plan_assets(
            talky_plan, TimeMap(talky_plan.keeps), self.cfg(),
            [FakeProvider(asset_file)], tmp_path / "c",
        )
        overlays = sorted(result.overlays, key=lambda o: o.start)
        assert overlays[0].start == pytest.approx(0.0)
        assert overlays[-1].end == pytest.approx(40.0, abs=0.35)
        for a, b in zip(overlays, overlays[1:]):
            assert b.start == pytest.approx(a.end)  # 빈틈 없음

    def test_uses_uploaded_assets_even_without_keyword_matches(self, tmp_path, talky_plan):
        """내 소재 폴더만 있고 키워드가 하나도 안 맞아도 전부 덮어야 한다."""
        from capcut_auto.assets.providers import LocalProvider
        from PIL import Image

        folder = tmp_path / "lib"
        folder.mkdir()
        for name in ("aaa.png", "bbb.png", "ccc.png"):
            Image.new("RGB", (320, 180), (5, 5, 5)).save(folder / name)

        result = plan_assets(
            talky_plan, TimeMap(talky_plan.keeps), self.cfg(),
            [LocalProvider(folder=folder)], tmp_path / "c",
        )
        assert result.overlays
        assert result.overlays[-1].end == pytest.approx(40.0, abs=0.35)
        # 올린 3개가 모두 쓰였는지
        used = {o.asset.path.name for o in result.overlays}
        assert used == {"aaa.png", "bbb.png", "ccc.png"}

    def test_does_not_repeat_the_same_asset_back_to_back(self, tmp_path, talky_plan):
        from capcut_auto.assets.providers import LocalProvider
        from PIL import Image

        folder = tmp_path / "lib"
        folder.mkdir()
        for name in ("a.png", "b.png"):
            Image.new("RGB", (320, 180), (5, 5, 5)).save(folder / name)

        result = plan_assets(
            talky_plan, TimeMap(talky_plan.keeps), self.cfg(),
            [LocalProvider(folder=folder)], tmp_path / "c",
        )
        paths = [o.asset.path for o in sorted(result.overlays, key=lambda o: o.start)]
        assert all(a != b for a, b in zip(paths, paths[1:]))

    def test_each_piece_respects_max_duration(self, tmp_path, asset_file, talky_plan):
        cfg = self.cfg(max_duration=3.0)
        result = plan_assets(
            talky_plan, TimeMap(talky_plan.keeps), cfg,
            [FakeProvider(asset_file)], tmp_path / "c",
        )
        assert all(o.duration <= 3.0 + 1e-6 for o in result.overlays)

    def test_video_asset_shorter_than_slot_is_not_stretched(self, tmp_path, asset_file, talky_plan):
        """8초짜리 영상 소재를 10초 구간에 억지로 늘리지 않는다."""
        provider = FakeProvider(asset_file, kinds=("video",))
        result = plan_assets(
            talky_plan, TimeMap(talky_plan.keeps), self.cfg(max_duration=30.0),
            [provider], tmp_path / "c",
        )
        for overlay in result.overlays:
            if overlay.asset.kind == "video" and overlay.asset.duration > 0:
                assert overlay.duration <= overlay.asset.duration + 1e-6

    def test_no_providers_yields_nothing(self, tmp_path, talky_plan):
        result = plan_assets(
            talky_plan, TimeMap(talky_plan.keeps), self.cfg(), [], tmp_path / "c"
        )
        assert result.overlays == []

    def test_spots_mode_is_still_sparse(self, tmp_path, asset_file, talky_plan):
        sparse = plan_assets(
            talky_plan, TimeMap(talky_plan.keeps), AssetsConfig(),
            [FakeProvider(asset_file)], tmp_path / "c1",
        )
        full = plan_assets(
            talky_plan, TimeMap(talky_plan.keeps), self.cfg(),
            [FakeProvider(asset_file)], tmp_path / "c2",
        )
        assert len(full.overlays) > len(sparse.overlays)

    def test_works_without_subtitles_using_my_own_images(self, tmp_path):
        """자막을 꺼도 내가 올린 이미지로 영상 전체를 덮을 수 있어야 한다."""
        from capcut_auto.assets.providers import LocalProvider
        from PIL import Image

        folder = tmp_path / "lib"
        folder.mkdir()
        for name in ("a.png", "b.png", "c.png"):
            Image.new("RGB", (320, 180), (5, 5, 5)).save(folder / name)

        plan = make_plan([], total=30.0)
        result = plan_assets(
            plan, TimeMap(plan.keeps), AssetsConfig(coverage="full"),
            [LocalProvider(folder=folder)], tmp_path / "c",
        )
        overlays = sorted(result.overlays, key=lambda o: o.start)
        assert overlays
        assert overlays[0].start == pytest.approx(0.0)
        assert overlays[-1].end == pytest.approx(30.0, abs=0.35)
        for a, b in zip(overlays, overlays[1:]):
            assert b.start == pytest.approx(a.end)

    def test_remote_provider_alone_cannot_fill_without_keywords(self, tmp_path, asset_file):
        """자막이 없으면 스톡 사이트에 던질 검색어가 없다 — 이건 어쩔 수 없다."""
        plan = make_plan([], total=30.0)
        result = plan_assets(
            plan, TimeMap(plan.keeps), AssetsConfig(coverage="full"),
            [FakeProvider(asset_file)], tmp_path / "c",
        )
        assert result.overlays == []
        assert any("소재가 없어" in note for note in result.skipped)

    def test_spots_mode_still_needs_subtitles(self, tmp_path, asset_file):
        plan = make_plan([], total=30.0)
        result = plan_assets(
            plan, TimeMap(plan.keeps), AssetsConfig(),
            [FakeProvider(asset_file)], tmp_path / "c",
        )
        assert result.overlays == []


class TestUseEachOnce:
    """이미지를 반복하지 않고 한 장씩 한 번만 쓰는 모드 (기본값)."""

    def images(self, tmp_path, count=4):
        from PIL import Image

        folder = tmp_path / "lib"
        folder.mkdir(exist_ok=True)
        for i in range(count):
            Image.new("RGB", (320, 180), (i * 20, 5, 5)).save(folder / f"img{i}.png")
        return folder

    def run(self, tmp_path, folder, total=40.0, **cfg_kwargs):
        from capcut_auto.assets.providers import LocalProvider

        plan = make_plan([], total=total)
        return plan_assets(
            plan, TimeMap(plan.keeps),
            AssetsConfig(coverage="full", **cfg_kwargs),
            [LocalProvider(folder=folder)], tmp_path / "c",
        )

    def test_each_image_appears_exactly_once(self, tmp_path):
        result = self.run(tmp_path, self.images(tmp_path, 4))
        names = [o.asset.path.name for o in result.overlays]
        assert len(names) == 4
        assert len(set(names)) == 4

    def test_timeline_is_split_evenly(self, tmp_path):
        result = self.run(tmp_path, self.images(tmp_path, 4), total=40.0)
        for overlay in result.overlays:
            assert overlay.duration == pytest.approx(10.0)

    def test_still_covers_everything_without_gaps(self, tmp_path):
        result = self.run(tmp_path, self.images(tmp_path, 3), total=30.0)
        overlays = sorted(result.overlays, key=lambda o: o.start)
        assert overlays[0].start == pytest.approx(0.0)
        assert overlays[-1].end == pytest.approx(30.0)
        for a, b in zip(overlays, overlays[1:]):
            assert b.start == pytest.approx(a.end)

    def test_one_image_fills_the_whole_thing(self, tmp_path):
        result = self.run(tmp_path, self.images(tmp_path, 1), total=25.0)
        assert len(result.overlays) == 1
        assert result.overlays[0].duration == pytest.approx(25.0)

    def test_reuse_flag_brings_repeats_back(self, tmp_path):
        result = self.run(tmp_path, self.images(tmp_path, 2), total=40.0, reuse=True)
        names = [o.asset.path.name for o in result.overlays]
        assert len(names) > len(set(names))   # 반복이 생긴다


class TestShareDurations:
    """길이를 나누는 계산. 영상 소재는 제 길이를 넘지 못한다."""

    def asset(self, kind, duration=0.0):
        from capcut_auto.assets.models import Asset

        return Asset(kind=kind, path=Path("x"), source="t", duration=duration)

    def test_images_split_evenly(self):
        from capcut_auto.assets.planner import share_durations

        assets = [self.asset("image") for _ in range(4)]
        assert share_durations(assets, 40.0) == [10.0] * 4

    def test_short_video_is_capped_and_rest_absorb_it(self):
        from capcut_auto.assets.planner import share_durations

        # 30초를 셋이 나누면 10초씩인데, 영상 하나가 4초뿐이면
        # 남은 26초를 이미지 둘이 13초씩 가져간다
        assets = [self.asset("video", 4.0), self.asset("image"), self.asset("image")]
        assert share_durations(assets, 30.0) == pytest.approx([4.0, 13.0, 13.0])

    def test_all_short_videos_cannot_fill(self):
        from capcut_auto.assets.planner import share_durations

        assets = [self.asset("video", 2.0), self.asset("video", 3.0)]
        assert share_durations(assets, 30.0) == pytest.approx([2.0, 3.0])

    def test_long_video_is_not_capped(self):
        from capcut_auto.assets.planner import share_durations

        assets = [self.asset("video", 100.0), self.asset("image")]
        assert share_durations(assets, 20.0) == pytest.approx([10.0, 10.0])

    def test_empty(self):
        from capcut_auto.assets.planner import share_durations

        assert share_durations([], 10.0) == []
