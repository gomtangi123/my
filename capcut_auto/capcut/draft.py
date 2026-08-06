"""편집안(EditPlan)을 CapCut 드래프트로 굽는다. 백엔드는 `pycapcut`.

draft_content.json을 직접 조립하지 않고 pycapcut에 맡긴다.
CapCut 버전이 올라가도 라이브러리만 갱신하면 되고,
전환/애니메이션/페이드 같은 것도 공짜로 딸려온다.

트랙 구성:

  video "main"     잘라낸 본편 클립들
  video "overlay"  자료화면 / 이미지 / GIF  (본편 위에 얹힘)
  text  "sub"      자막
  audio "sfx"      효과음
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pycapcut as cc
from pycapcut import (
    AudioMaterial,
    AudioSegment,
    ClipSettings,
    DraftFolder,
    ScriptFile,
    TextBorder,
    TextSegment,
    TextStyle,
    Timerange,
    TrackType,
    VideoMaterial,
    VideoSegment,
)

from ..config import Config
from ..ffmpeg import MediaInfo
from ..models import EditPlan

MAIN_TRACK = "main"
OVERLAY_TRACK = "overlay"
TEXT_TRACK = "sub"
SFX_TRACK = "sfx"
NARRATION_TRACK = "narration"

CONTENT_FILE = "draft_content.json"


class TemplateError(RuntimeError):
    pass


@dataclass
class DraftResult:
    path: Path
    name: str
    mode: str
    clip_count: int
    text_count: int
    overlay_count: int
    sfx_count: int
    duration: float


def us(seconds: float) -> int:
    """초 -> 마이크로초. pycapcut은 전부 마이크로초 정수를 쓴다."""
    return int(round(seconds * cc.SEC))


def trange(start: float, duration: float) -> Timerange:
    return Timerange(us(start), us(max(duration, 0.001)))


def build(
    plan: EditPlan,
    info: MediaInfo,
    cfg: Config,
    drafts_root: Path,
    project_name: str | None = None,
    template: str | None = None,
    overwrite: bool = False,
) -> DraftResult:
    """`drafts_root` 아래에 드래프트를 만든다.

    `drafts_root`를 CapCut의 실제 드래프트 폴더로 주면 곧바로 앱에 뜬다.
    `template`을 주면 그 드래프트를 복제해서 시작한다(스타일 물려받기).
    """
    drafts_root = Path(drafts_root)
    drafts_root.mkdir(parents=True, exist_ok=True)
    name = project_name or cfg.output.project_name or Path(plan.source).stem

    folder = DraftFolder(str(drafts_root))
    width = cfg.output.width or info.width
    height = cfg.output.height or info.height
    if not (width and height) and plan.overlays:
        # 오디오만 들어온 경우엔 첫 이미지 크기를 화면 크기로 삼는다.
        first = plan.overlays[0].asset
        width, height = width or first.width, height or first.height
    width, height = width or 1920, height or 1080
    fps = int(round(cfg.output.fps or info.fps or 30))

    if template:
        if not folder.has_draft(template):
            raise TemplateError(
                f"템플릿 드래프트가 없습니다: {template}\n"
                f"쓸 수 있는 것: {', '.join(folder.list_drafts()) or '(없음)'}"
            )
        script = folder.duplicate_as_template(template, name, allow_replace=overwrite)
        _clear_tracks(script)
        mode = "template"
    else:
        script = folder.create_draft(
            name, width, height, fps=fps, allow_replace=overwrite
        )
        mode = "native"

    if info.is_audio_only:
        # 대본 음성 + 이미지 = 슬라이드쇼. 이미지가 본편이 되고 음성이 깔린다.
        overlays = _add_slideshow_track(script, plan)
        _add_narration_track(script, plan)
    else:
        _add_main_track(script, plan, cfg)
        overlays = _add_overlay_track(script, plan)
    texts = _add_text_track(script, plan, cfg)
    sfx = _add_sfx_track(script, plan)

    script.save()

    return DraftResult(
        path=drafts_root / name,
        name=name,
        mode=mode,
        clip_count=len(plan.keeps),
        text_count=texts,
        overlay_count=overlays,
        sfx_count=sfx,
        duration=plan.output_duration,
    )


def _clear_tracks(script: ScriptFile) -> None:
    """복제한 템플릿의 내용물을 비운다.

    캔버스 크기·fps 같은 프로젝트 설정만 물려받고 타임라인은 새로 깐다.
    템플릿의 세그먼트를 남겨두면 우리 타임코드와 뒤엉킨다.
    """
    script.imported_tracks.clear()
    for track in script.tracks.values():
        track.segments.clear()
    script.duration = 0


def _ensure_track(script: ScriptFile, track_type: TrackType, name: str, index: int):
    if name not in script.tracks:
        script.add_track(track_type, name, relative_index=index)


# ------------------------------------------------------------------ 본편 트랙


def _add_main_track(script: ScriptFile, plan: EditPlan, cfg: Config) -> None:
    _ensure_track(script, TrackType.video, MAIN_TRACK, 0)
    material = VideoMaterial(plan.source)
    script.add_material(material)

    # ffprobe와 pycapcut(pymediainfo)이 재는 길이가 몇 밀리초씩 다를 수 있다.
    # 컷 구간은 ffprobe 기준으로 잡혔으므로, 소재 밖으로 삐져나온 꼬리를
    # 여기서 잘라 준다. 안 그러면 pycapcut이 세그먼트를 통째로 거부한다.
    limit = material.duration / cc.SEC

    cursor = 0.0
    for span in plan.keeps:
        start = min(span.start, limit)
        end = min(span.end, limit)
        duration = end - start
        if duration < 1.0 / max(script.fps, 1):  # 한 프레임도 안 되면 버린다
            continue
        segment = VideoSegment(
            material,
            target_timerange=trange(cursor, duration),
            source_timerange=trange(start, duration),
        )
        script.add_segment(segment, MAIN_TRACK)
        cursor += duration


# -------------------------------------------------------------- 슬라이드쇼


def _add_slideshow_track(script: ScriptFile, plan: EditPlan) -> int:
    """이미지를 본편 트랙에 깐다 (영상 없이 음성만 있을 때).

    오버레이가 아니라 화면 그 자체이므로 크기 조절 없이 꽉 채운다.
    """
    if not plan.overlays:
        raise TemplateError(
            "화면에 쓸 이미지가 없습니다 — 음성만으로는 영상을 만들 수 없습니다. "
            "「자료 이미지 넣기」에 사진을 올려 주세요."
        )

    _ensure_track(script, TrackType.video, MAIN_TRACK, 0)
    added = 0
    cursor = 0.0

    for overlay in plan.overlays:
        try:
            material = VideoMaterial(str(overlay.asset.path))
        except (FileNotFoundError, ValueError):
            continue

        duration = overlay.duration
        if material.material_type == "video":
            duration = min(duration, material.duration / cc.SEC)
        if duration <= 0.05:
            continue

        script.add_segment(
            VideoSegment(
                material,
                target_timerange=trange(cursor, duration),
                source_timerange=trange(0.0, duration),
                volume=0.0,  # 이미지 소재에 붙은 소리는 내레이션을 방해한다
            ),
            MAIN_TRACK,
        )
        cursor += duration
        added += 1
    return added


def _add_narration_track(script: ScriptFile, plan: EditPlan) -> None:
    """대본 음성을 컷 구간대로 잘라 오디오 트랙에 올린다."""
    material = AudioMaterial(plan.source)
    script.add_material(material)
    limit = material.duration / cc.SEC

    _ensure_track(script, TrackType.audio, NARRATION_TRACK, 0)
    cursor = 0.0
    for span in plan.keeps:
        start = min(span.start, limit)
        end = min(span.end, limit)
        duration = end - start
        if duration <= 0.02:
            continue
        script.add_segment(
            AudioSegment(
                material,
                trange(cursor, duration),
                source_timerange=trange(start, duration),
            ),
            NARRATION_TRACK,
        )
        cursor += duration


# ---------------------------------------------------------------- 오버레이 트랙


def _add_overlay_track(script: ScriptFile, plan: EditPlan) -> int:
    """자료화면 / 이미지 / GIF."""
    if not plan.overlays:
        return 0

    segments = []
    for overlay in plan.overlays:
        try:
            material = VideoMaterial(str(overlay.asset.path))
        except (FileNotFoundError, ValueError):
            # 소재가 사라졌거나 읽을 수 없으면 그 자리만 건너뛴다.
            continue

        # 이미지는 원하는 만큼 늘릴 수 있지만 영상/GIF는 원본 길이를 못 넘는다.
        duration = overlay.duration
        source_limit = material.duration / cc.SEC
        if material.material_type == "video":
            duration = min(duration, source_limit)
        if duration <= 0.05:
            continue

        segments.append(
            VideoSegment(
                material,
                target_timerange=trange(overlay.start, duration),
                source_timerange=trange(0.0, duration),
                # 자료화면 원본 소리는 죽인다. 내레이션을 덮으면 안 된다.
                volume=0.0,
                clip_settings=ClipSettings(
                    scale_x=overlay.scale,
                    scale_y=overlay.scale,
                    transform_y=overlay.position_y,
                ),
            )
        )

    if not segments:
        return 0

    _ensure_track(script, TrackType.video, OVERLAY_TRACK, 1)
    for segment in segments:
        script.add_segment(segment, OVERLAY_TRACK)
    return len(segments)


# ------------------------------------------------------------------ 자막 트랙


def _add_text_track(script: ScriptFile, plan: EditPlan, cfg: Config) -> int:
    if not cfg.subtitle.enabled or not plan.subtitles:
        return 0

    _ensure_track(script, TrackType.text, TEXT_TRACK, 0)
    style = TextStyle(
        size=cfg.subtitle.font_size,
        color=tuple(cfg.subtitle.font_color),
        align=1,  # 가운데 정렬
        auto_wrapping=True,
        max_line_width=0.82,
    )
    border = (
        TextBorder(
            color=tuple(cfg.subtitle.stroke_color),
            width=cfg.subtitle.stroke_width,
        )
        if cfg.subtitle.stroke
        else None
    )

    for line in plan.subtitles:
        segment = TextSegment(
            line.text,
            trange(line.start, max(line.end - line.start, 0.1)),
            style=style,
            border=border,
            clip_settings=ClipSettings(transform_y=cfg.subtitle.position_y),
        )
        script.add_segment(segment, TEXT_TRACK)
    return len(plan.subtitles)


# ---------------------------------------------------------------- 효과음 트랙


def _add_sfx_track(script: ScriptFile, plan: EditPlan) -> int:
    if not plan.sfx:
        return 0

    materials: dict[str, AudioMaterial] = {}
    pending: list[tuple[AudioMaterial, AudioSegment]] = []

    for placement in plan.sfx:
        path = str(placement.sound.path)
        material = materials.get(path)
        if material is None:
            try:
                material = AudioMaterial(path)
            except (FileNotFoundError, ValueError):
                continue
            materials[path] = material

        duration = min(placement.duration, material.duration / cc.SEC)
        if duration <= 0.02:
            continue

        pending.append(
            (
                material,
                AudioSegment(
                    material,
                    trange(placement.time, duration),
                    source_timerange=trange(0.0, duration),
                    volume=placement.volume,
                ),
            )
        )

    if not pending:
        return 0

    _ensure_track(script, TrackType.audio, SFX_TRACK, 0)
    for material in materials.values():
        script.add_material(material)
    for _material, segment in pending:
        script.add_segment(segment, SFX_TRACK)
    return len(pending)


__all__ = [
    "build",
    "DraftResult",
    "TemplateError",
    "CONTENT_FILE",
    "MAIN_TRACK",
    "OVERLAY_TRACK",
    "NARRATION_TRACK",
    "TEXT_TRACK",
    "SFX_TRACK",
]
