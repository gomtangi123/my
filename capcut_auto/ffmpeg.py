"""ffmpeg / ffprobe 얇은 래퍼."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FFmpegMissing(RuntimeError):
    pass


class FFmpegFailed(RuntimeError):
    pass


def require(tool: str = "ffmpeg") -> str:
    path = shutil.which(tool)
    if not path:
        raise FFmpegMissing(
            f"`{tool}`를 찾을 수 없습니다.\n"
            "  macOS : brew install ffmpeg\n"
            "  Windows: winget install Gyan.FFmpeg\n"
            "  Ubuntu : sudo apt install ffmpeg"
        )
    return path


def run(
    args: list[str], *, capture: bool = True, cwd: str | Path | None = None
) -> subprocess.CompletedProcess:
    # 인코딩을 명시한다. 안 그러면 윈도우에서 로케일 코드페이지(한국어면 cp949)로
    # 해석하는데 ffmpeg은 UTF-8로 뱉는다. 경로에 한글이 있으면 깨지거나 터진다.
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=capture,
        encoding="utf-8" if capture else None,
        errors="replace" if capture else None,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-2000:] if capture else ""
        raise FFmpegFailed(f"{args[0]} 실패 (exit {proc.returncode})\n{tail}")
    return proc


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    sample_rate: int
    channels: int

    @property
    def is_vertical(self) -> bool:
        return self.height > self.width


def _parse_fraction(value: str | None, default: float) -> float:
    if not value:
        return default
    if "/" in value:
        num, _, den = value.partition("/")
        try:
            n, d = float(num), float(den)
        except ValueError:
            return default
        return n / d if d else default
    try:
        return float(value)
    except ValueError:
        return default


def probe(path: str | Path) -> MediaInfo:
    ffprobe = require("ffprobe")
    proc = run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    if not duration:
        for stream in (video, audio):
            if stream and stream.get("duration"):
                duration = float(stream["duration"])
                break

    return MediaInfo(
        path=str(path),
        duration=duration,
        width=int(video.get("width", 0)) if video else 0,
        height=int(video.get("height", 0)) if video else 0,
        fps=_parse_fraction(video.get("avg_frame_rate") if video else None, 30.0),
        has_audio=audio is not None,
        sample_rate=int(audio.get("sample_rate", 48000)) if audio else 0,
        channels=int(audio.get("channels", 0)) if audio else 0,
    )


def decode_audio(path: str | Path, sample_rate: int = 16000):
    """모노 float32 PCM으로 디코딩해서 numpy 배열로 돌려준다."""
    import numpy as np

    ffmpeg = require("ffmpeg")
    proc = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise FFmpegFailed(
            "오디오 디코딩 실패 — 오디오 트랙이 없는 파일일 수 있습니다.\n"
            + proc.stderr.decode("utf-8", "replace")[-2000:]
        )
    return np.frombuffer(proc.stdout, dtype=np.float32)



__all__ = [
    "MediaInfo",
    "FFmpegMissing",
    "FFmpegFailed",
    "require",
    "run",
    "probe",
    "decode_audio",
]
