"""CapCut 없이 ffmpeg로 바로 뽑기.

CapCut에 넣기 전에 결과를 빠르게 확인하거나, 그냥 완성본이 필요할 때 쓴다.
컷 / 자료화면 오버레이 / 효과음 / 자막까지 드래프트와 같은 내용을 렌더한다.

필터 그래프가 길어지므로 `-filter_complex_script`로 파일에서 읽힌다
(명령줄 길이 제한 회피).
"""

from __future__ import annotations

import platform
import shutil
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
    # ffmpeg은 자막 파일이 있는 폴더에서 실행되므로(아래 render 참고)
    # 나머지 경로는 전부 절대경로로 넘겨야 한다.
    args: list[str] = ["-i", str(Path(plan.source).resolve())]
    overlay_indices: list[int] = []
    sfx_indices: list[int] = []
    index = 1

    for overlay in plan.overlays:
        if overlay.asset.kind == "image":
            # 정지 이미지는 필요한 길이만큼 루프시켜야 프레임이 생긴다.
            args += ["-loop", "1", "-t", f"{overlay.duration:.6f}"]
        args += ["-i", str(Path(overlay.asset.path).resolve())]
        overlay_indices.append(index)
        index += 1

    for placement in plan.sfx:
        args += ["-i", str(Path(placement.sound.path).resolve())]
        sfx_indices.append(index)
        index += 1

    return RenderInputs(args, overlay_indices, sfx_indices)


def build_filter_script(
    plan: EditPlan,
    inputs: RenderInputs,
    width: int,
    height: int,
    with_audio: bool,
    subtitles_name: str | None = None,
    font: str = "",
    slideshow: bool = False,
) -> tuple[str, str, str | None]:
    """(필터 스크립트, 비디오 출력 라벨, 오디오 출력 라벨)."""
    parts: list[str] = []

    if slideshow:
        return _slideshow_script(plan, inputs, width, height, subtitles_name, font)

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
    #
    # 경로는 절대경로로 주지 않는다. 윈도우의 "C:" 콜론이 필터 문법의
    # 구분자와 겹쳐서, 어떻게 이스케이프해도 파서가 걸고 넘어진다.
    # 대신 ffmpeg을 자막 파일이 있는 폴더에서 실행하고 파일 이름만 넘긴다.
    if subtitles_name:
        style = f":force_style='FontName={font}'" if font else ""
        parts.append(f"{video_label}subtitles={subtitles_name}{style}[burned]")
        video_label = "[burned]"

    return ";\n".join(parts), video_label, audio_label


def _slideshow_script(
    plan: EditPlan,
    inputs: RenderInputs,
    width: int,
    height: int,
    subtitles_name: str | None,
    font: str,
) -> tuple[str, str, str | None]:
    """이미지를 이어 붙여 화면을 만들고, 대본 음성을 컷대로 잘라 깐다.

    영상 트랙이 없는 입력(대본 음성 파일)에서 쓴다.
    """
    parts: list[str] = []

    # 1) 이미지들을 화면 크기에 맞춰 레터박스로 채우고 차례로 잇는다.
    for slot, (overlay, index) in enumerate(zip(plan.overlays, inputs.overlay_indices)):
        parts.append(
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps=30,trim=duration={overlay.duration:.6f},"
            f"setpts=PTS-STARTPTS[s{slot}]"
        )
    n = len(plan.overlays)
    parts.append("".join(f"[s{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[basev]")

    # 2) 대본 음성은 남긴 구간만 이어 붙인다.
    for i, span in enumerate(plan.keeps):
        parts.append(
            f"[0:a]atrim=start={span.start:.6f}:end={span.end:.6f},"
            f"asetpts=PTS-STARTPTS[a{i}]"
        )
    k = len(plan.keeps)
    parts.append("".join(f"[a{i}]" for i in range(k)) + f"concat=n={k}:v=0:a=1[basea]")

    video_label, audio_label = "[basev]", "[basea]"

    # 3) 효과음
    if inputs.sfx_indices:
        labels = [audio_label]
        for slot, (placement, index) in enumerate(zip(plan.sfx, inputs.sfx_indices)):
            delay_ms = int(round(max(0.0, placement.time) * 1000))
            parts.append(
                f"[{index}:a]atrim=0:{max(placement.duration, 0.05):.6f},"
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

    if subtitles_name:
        style = f":force_style='FontName={font}'" if font else ""
        parts.append(f"{video_label}subtitles={subtitles_name}{style}[burned]")
        video_label = "[burned]"

    return ";\n".join(parts), video_label, audio_label


def default_subtitle_font() -> str:
    """자막을 태울 때 쓸 기본 글꼴. 한글이 네모로 나오는 걸 막는다."""
    system = platform.system()
    if system == "Windows":
        return "Malgun Gothic"
    if system == "Darwin":
        return "AppleSDGothicNeo"
    return ""  # 리눅스는 fontconfig에 맡긴다


def render(
    plan: EditPlan,
    cfg: Config,
    out_path: str | Path,
    width: int,
    height: int,
    srt_path: Path | None = None,
    work_dir: Path | None = None,
    has_audio: bool = True,
    slideshow: bool = False,
    show_stats: bool = True,
    progress=None,
) -> Path:
    say = progress or (lambda _msg: None)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path = out_path.resolve()
    work_dir = Path(work_dir or out_path.parent)
    work_dir.mkdir(parents=True, exist_ok=True)
    work_dir = work_dir.resolve()

    inputs = _build_inputs(plan)

    burn_name = None
    if cfg.output.burn_subtitles and srt_path is not None:
        # 필터에 넘길 이름은 ASCII 짧은 이름으로 통일한다 (경로 문제 회피).
        burn_name = "subs.srt"
        shutil.copyfile(srt_path, work_dir / burn_name)

    script, video_label, audio_label = build_filter_script(
        plan, inputs, width, height, has_audio, burn_name,
        default_subtitle_font(), slideshow,
    )

    script_path = work_dir / "filter_graph.txt"
    script_path.write_text(script, encoding="utf-8")

    args = [ffmpeg.require("ffmpeg"), "-v", "error", "-y"]
    if show_stats:
        # 터미널에서는 진행률이 보이는 게 낫고, 웹 UI에서는 서버 콘솔만 더럽힌다.
        args.insert(3, "-stats")
    args += inputs.args
    args += ["-filter_complex_script", str(script_path.resolve()), "-map", video_label]
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
    # 자막 필터가 상대 경로를 찾을 수 있도록 작업 폴더에서 실행한다.
    ffmpeg.run(args, capture=not show_stats, cwd=work_dir)
    return out_path


__all__ = ["render", "build_filter_script", "RenderInputs"]
