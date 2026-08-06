"""ffmpeg 렌더 필터 그래프 조립 테스트."""

import pytest

from capcut_auto import render as render_mod
from capcut_auto.assets.models import Asset, Overlay
from capcut_auto.config import Config
from capcut_auto.models import EditPlan, Span
from capcut_auto.sfx import builtin
from capcut_auto.sfx.library import Sound
from capcut_auto.sfx.planner import SfxPlacement


def make_plan(tmp_path, overlays=0, sfx=0):
    plan = EditPlan(
        source=str(tmp_path / "in.mp4"),
        source_duration=30.0,
        keeps=[Span(0, 4), Span(6, 10)],
        cuts=[],
        subtitles=[],
    )
    for i in range(overlays):
        plan.overlays.append(
            Overlay(
                start=1.0 + i,
                end=3.0 + i,
                asset=Asset(kind="image", path=tmp_path / f"a{i}.png", source="t"),
                keyword="k",
                scale=0.6,
                position_y=0.2,
            )
        )
    for i in range(sfx):
        plan.sfx.append(
            SfxPlacement(
                time=2.0 + i,
                sound=Sound("pop", tmp_path / "pop.wav", frozenset(), 0.12, True),
                duration=0.12,
                volume=0.35,
                reason="transition",
            )
        )
    return plan


def build(plan, **kwargs):
    inputs = render_mod._build_inputs(plan)
    return render_mod.build_filter_script(plan, inputs, 1920, 1080, True, **kwargs)


class TestFilterGraph:
    def test_one_trim_per_kept_span(self, tmp_path):
        script, _v, _a = build(make_plan(tmp_path))
        assert script.count("[0:v]trim=start=") == 2
        assert script.count("[0:a]atrim=start=") == 2

    def test_concat_joins_all_clips(self, tmp_path):
        script, video, audio = build(make_plan(tmp_path))
        assert "concat=n=2:v=1:a=1[basev][basea]" in script
        assert (video, audio) == ("[basev]", "[basea]")

    def test_no_audio_mode(self, tmp_path):
        inputs = render_mod._build_inputs(make_plan(tmp_path))
        script, video, audio = render_mod.build_filter_script(
            make_plan(tmp_path), inputs, 1920, 1080, False
        )
        assert "concat=n=2:v=1:a=0[basev]" in script
        assert audio is None and video == "[basev]"

    def test_overlays_chain_in_order(self, tmp_path):
        script, video, _a = build(make_plan(tmp_path, overlays=2))
        assert "[ov0]" in script and "[ov1]" in script
        assert video == "[ovout1]"

    def test_overlay_is_scaled_from_width(self, tmp_path):
        script, _v, _a = build(make_plan(tmp_path, overlays=1))
        assert "scale=1152:-2" in script  # 1920 * 0.6

    def test_sfx_mixed_with_base_audio(self, tmp_path):
        script, _v, audio = build(make_plan(tmp_path, sfx=2))
        assert "amix=inputs=3" in script
        assert audio == "[mixa]"

    def test_sfx_delay_matches_placement(self, tmp_path):
        script, _v, _a = build(make_plan(tmp_path, sfx=1))
        assert "adelay=2000|2000" in script


class TestBurnedSubtitles:
    def test_uses_a_relative_name_not_a_drive_path(self, tmp_path):
        """윈도우의 'C:' 콜론이 필터 문법과 충돌해서 절대경로는 못 쓴다."""
        script, video, _a = build(make_plan(tmp_path), subtitles_name="subs.srt")
        assert "subtitles=subs.srt" in script
        assert ":\\" not in script and "C\\:" not in script
        assert video == "[burned]"

    def test_font_is_forced_when_given(self, tmp_path):
        script, _v, _a = build(
            make_plan(tmp_path), subtitles_name="subs.srt", font="Malgun Gothic"
        )
        assert "force_style='FontName=Malgun Gothic'" in script

    def test_no_style_when_font_blank(self, tmp_path):
        script, _v, _a = build(make_plan(tmp_path), subtitles_name="subs.srt", font="")
        assert "force_style" not in script

    def test_absent_when_not_burning(self, tmp_path):
        script, video, _a = build(make_plan(tmp_path))
        assert "subtitles=" not in script
        assert video == "[basev]"

    @pytest.mark.parametrize("system,expected", [("Windows", "Malgun Gothic"), ("Linux", "")])
    def test_default_font_per_platform(self, monkeypatch, system, expected):
        monkeypatch.setattr(render_mod.platform, "system", lambda: system)
        assert render_mod.default_subtitle_font() == expected


class TestInputs:
    def test_source_is_input_zero(self, tmp_path):
        inputs = render_mod._build_inputs(make_plan(tmp_path))
        assert inputs.args[:2] == ["-i", str(tmp_path / "in.mp4")]

    def test_images_are_looped(self, tmp_path):
        inputs = render_mod._build_inputs(make_plan(tmp_path, overlays=1))
        assert "-loop" in inputs.args

    def test_index_order_is_source_overlays_sfx(self, tmp_path):
        inputs = render_mod._build_inputs(make_plan(tmp_path, overlays=2, sfx=3))
        assert inputs.overlay_indices == [1, 2]
        assert inputs.sfx_indices == [3, 4, 5]
