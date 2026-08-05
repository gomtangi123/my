"""pycapcut로 실제 드래프트를 구워 보는 통합 테스트.

ffmpeg 없이 돌려야 하므로 소재는 PIL(이미지)과 wave(효과음)로 만든다.
pycapcut의 VideoMaterial은 이미지를 'photo' 소재로 받아 주기 때문에
본편 소스로 써도 타임라인 조립 로직은 그대로 검증된다.
"""

import json

import pytest

from capcut_auto.assets.models import Asset, Overlay
from capcut_auto.capcut import draft as draft_mod
from capcut_auto.config import Config
from capcut_auto.ffmpeg import MediaInfo
from capcut_auto.models import Cut, EditPlan, Span, SubtitleLine, Word
from capcut_auto.sfx import builtin
from capcut_auto.sfx.library import Sound
from capcut_auto.sfx.planner import SfxPlacement

pytest.importorskip("pycapcut")


def make_image(path, size=(640, 360), color=(20, 90, 160)):
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


@pytest.fixture
def media(tmp_path):
    """본편 소스 + 오버레이 소재 + 효과음."""
    return {
        "source": make_image(tmp_path / "src" / "talk.png"),
        "broll": make_image(tmp_path / "src" / "seoul.png", color=(200, 60, 60)),
        "sfx": builtin.ensure("pop", tmp_path / "src" / "sfx"),
    }


@pytest.fixture
def info():
    return MediaInfo(
        path="talk.png",
        duration=30.0,
        width=1920,
        height=1080,
        fps=30.0,
        has_audio=True,
        sample_rate=48000,
        channels=2,
    )


def build_plan(media, *, overlays=True, sfx=True, subs=True):
    keeps = [Span(0.0, 4.0), Span(6.0, 10.0), Span(12.0, 15.0)]
    plan = EditPlan(
        source=str(media["source"]),
        source_duration=30.0,
        keeps=keeps,
        cuts=[Cut(Span(4.0, 6.0), "silence", "2.00초")],
        subtitles=(
            [
                SubtitleLine(
                    "서울에 다녀왔습니다",
                    0.5,
                    3.0,
                    [Word(0.5, 3.0, "서울에 다녀왔습니다")],
                ),
                SubtitleLine("정말 좋았어요", 5.0, 7.5, [Word(5.0, 7.5, "정말 좋았어요")]),
            ]
            if subs
            else []
        ),
    )
    if overlays:
        plan.overlays = [
            Overlay(
                start=1.0,
                end=3.5,
                asset=Asset(
                    kind="image",
                    path=media["broll"],
                    source="test",
                    width=640,
                    height=360,
                    query="seoul",
                ),
                keyword="서울",
                scale=0.62,
                position_y=0.22,
            )
        ]
    if sfx:
        sound = Sound(
            key="pop",
            path=media["sfx"],
            tags=frozenset({"pop"}),
            duration=builtin.duration_of("pop"),
            builtin=True,
        )
        plan.sfx = [
            SfxPlacement(
                time=4.0,
                sound=sound,
                duration=sound.duration,
                volume=0.35,
                reason="transition",
            )
        ]
    return plan


def load_draft(result):
    return json.loads((result.path / "draft_content.json").read_text(encoding="utf-8"))


def tracks_by_type(content):
    grouped = {}
    for track in content["tracks"]:
        grouped.setdefault(track["type"], []).append(track)
    return grouped


class TestNativeDraft:
    def test_creates_draft_files(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "drafts"
        )
        assert (result.path / "draft_content.json").exists()
        assert (result.path / "draft_meta_info.json").exists()
        assert result.mode == "native"

    def test_draft_name_defaults_to_source_stem(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        assert result.name == "talk"
        assert result.path.name == "talk"

    def test_main_track_has_one_segment_per_keep(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        content = load_draft(result)
        video_tracks = tracks_by_type(content)["video"]
        main = video_tracks[0]
        assert len(main["segments"]) == 3
        assert result.clip_count == 3

    def test_clips_are_laid_end_to_end(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        main = tracks_by_type(load_draft(result))["video"][0]
        targets = [s["target_timerange"] for s in main["segments"]]
        # 결과 타임라인에는 빈틈이 없어야 한다
        assert targets[0]["start"] == 0
        for previous, current in zip(targets, targets[1:]):
            assert current["start"] == previous["start"] + previous["duration"]

    def test_source_timeranges_point_at_the_kept_spans(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        main = tracks_by_type(load_draft(result))["video"][0]
        sources = [(s["source_timerange"]["start"], s["source_timerange"]["duration"])
                   for s in main["segments"]]
        assert sources == [(0, 4_000_000), (6_000_000, 4_000_000), (12_000_000, 3_000_000)]

    def test_total_duration_is_sum_of_keeps(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        assert load_draft(result)["duration"] == 11_000_000
        assert result.duration == pytest.approx(11.0)

    def test_canvas_matches_source_resolution(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        canvas = load_draft(result)["canvas_config"]
        assert (canvas["width"], canvas["height"]) == (1920, 1080)

    def test_canvas_override_from_config(self, tmp_path, media, info):
        cfg = Config()
        cfg.output.width, cfg.output.height = 1080, 1920
        result = draft_mod.build(
            build_plan(media), info, cfg, drafts_root=tmp_path / "d"
        )
        canvas = load_draft(result)["canvas_config"]
        assert (canvas["width"], canvas["height"]) == (1080, 1920)


class TestSubtitleTrack:
    def test_text_segments_created(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        text_tracks = tracks_by_type(load_draft(result))["text"]
        assert len(text_tracks[0]["segments"]) == 2
        assert result.text_count == 2

    def test_subtitle_text_survives_into_the_draft(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        content = load_draft(result)
        texts = [json.loads(m["content"])["text"] for m in content["materials"]["texts"]]
        assert "서울에 다녀왔습니다" in texts

    def test_no_text_track_when_disabled(self, tmp_path, media, info):
        cfg = Config()
        cfg.subtitle.enabled = False
        result = draft_mod.build(
            build_plan(media), info, cfg, drafts_root=tmp_path / "d"
        )
        assert "text" not in tracks_by_type(load_draft(result))
        assert result.text_count == 0


class TestOverlayTrack:
    def test_overlay_goes_on_a_second_video_track(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        video_tracks = tracks_by_type(load_draft(result))["video"]
        assert len(video_tracks) == 2
        assert len(video_tracks[1]["segments"]) == 1
        assert result.overlay_count == 1

    def test_overlay_is_scaled_and_positioned(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        segment = tracks_by_type(load_draft(result))["video"][1]["segments"][0]
        assert segment["clip"]["scale"]["x"] == pytest.approx(0.62)
        assert segment["clip"]["transform"]["y"] == pytest.approx(0.22)

    def test_overlay_audio_is_muted(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        segment = tracks_by_type(load_draft(result))["video"][1]["segments"][0]
        assert segment["volume"] == 0.0

    def test_overlay_timing(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        segment = tracks_by_type(load_draft(result))["video"][1]["segments"][0]
        assert segment["target_timerange"]["start"] == 1_000_000
        assert segment["target_timerange"]["duration"] == 2_500_000

    def test_missing_asset_is_skipped_not_fatal(self, tmp_path, media, info):
        plan = build_plan(media)
        plan.overlays[0].asset.path = tmp_path / "does-not-exist.png"
        result = draft_mod.build(plan, info, Config(), drafts_root=tmp_path / "d")
        assert result.overlay_count == 0
        assert len(tracks_by_type(load_draft(result))["video"]) == 1


class TestSfxTrack:
    def test_audio_track_created(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        audio_tracks = tracks_by_type(load_draft(result))["audio"]
        assert len(audio_tracks[0]["segments"]) == 1
        assert result.sfx_count == 1

    def test_sfx_volume_and_placement(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media), info, Config(), drafts_root=tmp_path / "d"
        )
        segment = tracks_by_type(load_draft(result))["audio"][0]["segments"][0]
        assert segment["volume"] == pytest.approx(0.35)
        assert segment["target_timerange"]["start"] == 4_000_000

    def test_no_audio_track_without_sfx(self, tmp_path, media, info):
        result = draft_mod.build(
            build_plan(media, sfx=False), info, Config(), drafts_root=tmp_path / "d"
        )
        assert "audio" not in tracks_by_type(load_draft(result))


class TestOverwriteAndTemplate:
    def test_second_build_without_overwrite_fails(self, tmp_path, media, info):
        root = tmp_path / "d"
        draft_mod.build(build_plan(media), info, Config(), drafts_root=root)
        with pytest.raises(FileExistsError):
            draft_mod.build(build_plan(media), info, Config(), drafts_root=root)

    def test_overwrite_replaces(self, tmp_path, media, info):
        root = tmp_path / "d"
        draft_mod.build(build_plan(media), info, Config(), drafts_root=root)
        result = draft_mod.build(
            build_plan(media, overlays=False, sfx=False),
            info,
            Config(),
            drafts_root=root,
            overwrite=True,
        )
        assert result.overlay_count == 0
        assert "audio" not in tracks_by_type(load_draft(result))

    def test_missing_template_raises(self, tmp_path, media, info):
        with pytest.raises(draft_mod.TemplateError):
            draft_mod.build(
                build_plan(media),
                info,
                Config(),
                drafts_root=tmp_path / "d",
                template="없는드래프트",
            )

    def test_template_mode_reuses_project_and_clears_old_content(
        self, tmp_path, media, info
    ):
        root = tmp_path / "d"
        draft_mod.build(
            build_plan(media), info, Config(), drafts_root=root, project_name="base"
        )
        result = draft_mod.build(
            build_plan(media, overlays=False, sfx=False, subs=False),
            info,
            Config(),
            drafts_root=root,
            project_name="derived",
            template="base",
        )
        assert result.mode == "template"
        content = load_draft(result)
        # 템플릿에 있던 자막/오버레이/효과음이 딸려오면 안 된다
        assert "text" not in tracks_by_type(content)
        assert "audio" not in tracks_by_type(content)
        assert len(tracks_by_type(content)["video"]) == 1
        assert len(tracks_by_type(content)["video"][0]["segments"]) == 3
