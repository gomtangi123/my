"""한글이 나오는 글꼴 찾기.

`render.default_subtitle_font()` 는 ffmpeg에 넘길 **이름**을 돌려주지만
Pillow는 **파일 경로**가 필요해서 따로 찾는다.

찾는 순서는 (1) 사용자가 지정한 경로, (2) OS별로 있을 법한 자리,
(3) fontconfig(`fc-match`). 리눅스는 배포판마다 경로가 제각각이라 셋째가
사실상 본선이다.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

# (보통 굵기, 굵은 것). 굵은 게 없으면 같은 파일을 두 번 쓴다.
_CANDIDATES: dict[str, list[tuple[str, str]]] = {
    "Windows": [
        (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf"),
        (r"C:\Windows\Fonts\NanumGothic.ttf", r"C:\Windows\Fonts\NanumGothicBold.ttf"),
        (
            r"C:\Windows\Fonts\NotoSansKR-Regular.otf",
            r"C:\Windows\Fonts\NotoSansKR-Bold.otf",
        ),
    ],
    "Darwin": [
        (
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        ),
        ("/Library/Fonts/AppleGothic.ttf", "/Library/Fonts/AppleGothic.ttf"),
    ],
    "Linux": [
        (
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        ),
        (
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        ),
        (
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        ),
    ],
}


class FontMissing(RuntimeError):
    """한글을 그릴 수 있는 글꼴을 못 찾았을 때."""


def _fc_match(pattern: str) -> Path | None:
    """fontconfig에게 물어본다. 리눅스/맥에만 있다."""
    if not shutil.which("fc-match"):
        return None
    try:
        out = subprocess.run(
            ["fc-match", "-f", "%{file}", pattern],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    path = Path(out) if out else None
    return path if path and path.is_file() else None


def find(explicit: str | None = None) -> tuple[Path, Path]:
    """(보통, 굵게) 글꼴 파일 경로. 못 찾으면 FontMissing."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FontMissing(f"글꼴 파일이 없습니다: {path}")
        return path, path

    for regular, bold in _CANDIDATES.get(platform.system(), []):
        reg_path, bold_path = Path(regular), Path(bold)
        if reg_path.is_file():
            return reg_path, bold_path if bold_path.is_file() else reg_path

    regular = _fc_match("sans:lang=ko")
    if regular is not None:
        return regular, _fc_match("sans:lang=ko:weight=bold") or regular

    raise FontMissing(
        "한글 글꼴을 찾지 못했습니다. --font 으로 .ttf/.otf 경로를 직접 주세요.\n"
        "  (리눅스: apt install fonts-nanum · 나눔고딕을 받아 두면 가장 무난합니다)"
    )


__all__ = ["find", "FontMissing"]
