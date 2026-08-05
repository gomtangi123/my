"""CapCut 없이 ffmpeg로 바로 뽑기.

CapCut에 넣기 전에 결과를 빠르게 확인하거나, 그냥 완성본이 필요할 때 쓴다.
컷 / 자료화면 오버레이 / 효과음 / 자막까지 드래프트와 같은 내용을 렌더한다.

필터 그래프가 길어지므로 `-filter_complex_script`로 파일에서 읽힌다
(명령줄 길이 제한 회피).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg
from .config import Config
from .models import EditPlan


@dataclass
class RenderInputs:
    """ffmpeg 입력 순서: 0번은 항상 원본, 그다음 오버레이, 그다음 효과음."""

    args: list[str]
    overlay_indices: list[int]
    sfx_indices: list[int]


def _build_inputs(plan: EditPlan) -> RenderInputs:
    args: list[str] = ["-i", plan.source]
    overlay_indices: list[int] = []
    sfx_indices: list[int] = []
    index = 1

    for overlay in plan.overlays:
        if overlay.asset.kind == "image":
            # 정지 이미지는 필요한 길이만큼 루프시켜야 프레임이 생긴다.
            args += ["-loop", "1", "-t", f"{overlay.duration:.6f}"]
        args += ["-i", str(overlay.asset.path)]
        overlay_indices.append(index)
        index += 1

    for placement in plan.sfx:
        args += ["-i", str(placement.sound.path)]
        sfx_indices.append(index)
        index += 1

    return RenderInputs(args, overlay_indices, sfx_indices)


def build_filter_script(
    plan: EditPlan,
    inputs: RenderInputs,
    width: int,
    height: int,
    with_audio: bool,
    subtitles_path: Path | None = None,
) -> tuple[str, str, str | None]:
    """(필터 스크립트, 비디오 출력 라벨, 오디오 출력 라벨)."""
    parts: list[str] = []

    # 1) 남길 구간만 잘라서 이어 붙인다.
    for i, span in enumerate(plan.keeps):
        parts.append(
            f"[0:v]trim=start={span.start:.6f}:end={span.end:.6f},"
            f"setpts=PTS-STARTPTS[v{i}]"
        )
        if with_audio:
            parts.append(
                f"[0:a]atrim=start={span.start:.6f}:end={span.end:.6f},"
                f"asetpts=PTS-STARTPTS[a{i}]"
            )

    n = len(plan.keeps)
    if with_audio:
        ordered = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{ordered}concat=n={n}:v=1:a=1[basev][basea]")
    else:
        ordered = "".join(f"[v{i}]" for i in range(n))
        parts.append(f"{ordered}concat=n={n}:v=1:a=0[basev]")

    video_label = "[basev]"
    audio_label = "[basea]" if with_audio else None

    # 2) 자료화면 / 이미지 / GIF 를 얹는다.
    for slot, (overlay, input_index) in enumerate(
        zip(plan.overlays, inputs.overlay_indices)
    ):
        target_w = max(2, int(round(width * overlay.scale)))
        parts.append(
            f"[{input_index}:v]scale={target_w}:-2,setsar=1,"
            f"setpts=PTS-STARTPTS+{overlay.start:.6f}/TB[ov{slot}]"
        )
        # CapCut의 transform_y는 +가 위쪽인 -1~1 좌표. 픽셀 y로 옮긴다.
        y_expr = f"(H-h)/2*(1-({overlay.position_y:.4f}))"
        parts.append(
            f"{video_label}[ov{slot}]overlay=x=(W-w)/2:y={y_expr}"
            f":enable='between(t,{overlay.start:.6f},{overlay.end:.6f})'"
            f":eof_action=pass[ovout{slot}]"
        )
        video_label = f"[ovout{slot}]"

    # 3) 효과음을 섞는다.
    if with_audio and inputs.sfx_indices:
        labels = [audio_label]
        for slot, (placement, input_index) in enumerate(
            zip(plan.sfx, inputs.sfx_indices)
        ):
            delay_ms = int(round(max(0.0, placement.time) * 1000))
            parts.append(
                f"[{input_index}:a]atrim=0:{max(placement.duration, 0.05):.6f},"
                f"asetpts=PTS-STARTPTS,"
                f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                f"volume={placement.volume:.4f},"
                f"adelay={delay_ms}|{delay_ms}[sfx{slot}]"
            )
            labels.append(f"[sfx{slot}]")
        parts.append(
            "".join(labels)
            + f"amix=inputs={len(labels)}:normalize=0:duration=first"
            ":dropout_transition=0[mixa]"
        )
        audio_label = "[mixa]"

    # 4) 자막 태우기
    if subtitles_path is not None:
        parts.append(
            f"{video_label}subtitles='{_escape_for_filter(subtitles_path)}'[burned]"
        )
        video_label = "[burned]"

    return ";\n".join(parts), video_label, audio_label


def _escape_for_filter(path: Path) -> str:
    """subtitles= 필터 안에 넣을 경로 이스케이프 (윈도우 드라이브 문자 포함)."""
    text = str(path.resolve()).replace("\\", "/")
    return text.replace("'", r"\'").replace(":", r"\:")


def render(
    plan: EditPlan,
    cfg: Config,
    out_path: str | Path,
    width: int,
    height: int,
    srt_path: Path | None = None,
    work_dir: Path | None = None,
    has_audio: bool = True,
    progress=None,
) -> Path:
    say = progress or (lambda _msg: None)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(work_dir or out_path.parent)
    work_dir.mkdir(parents=True, exist_ok=True)

    inputs = _build_inputs(plan)
    burn = srt_path if (cfg.output.burn_subtitles and srt_path is not None) else None
    script, video_label, audio_label = build_filter_script(
        plan, inputs, width, height, has_audio, burn
    )

    script_path = work_dir / "filter_graph.txt"
    script_path.write_text(script, encoding="utf-8")

    args = [ffmpeg.require("ffmpeg"), "-v", "error", "-stats", "-y"]
    args += inputs.args
    args += ["-filter_complex_script", str(script_path), "-map", video_label]
    if audio_label:
        args += ["-map", audio_label, "-c:a", cfg.output.audio_codec, "-b:a", "192k"]
    args += [
        "-c:v",
        cfg.output.video_codec,
        "-crf",
        str(cfg.output.crf),
        "-preset",
        cfg.output.preset,
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out_path),
    ]

    say(
        f"렌더링: 클립 {len(plan.keeps)}개 / 오버레이 {len(plan.overlays)}개 / "
        f"효과음 {len(plan.sfx)}개 → {out_path.name}"
    )
    ffmpeg.run(args, capture=False)
    return out_path


__all__ = ["render", "build_filter_script", "RenderInputs"]
