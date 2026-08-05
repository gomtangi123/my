"""설치된 CapCut의 드래프트 폴더 찾기."""

from __future__ import annotations

import os
import platform
from pathlib import Path

DRAFT_SUBPATH = Path("User Data") / "Projects" / "com.lveditor.draft"


def candidates() -> list[Path]:
    """OS별로 있을 법한 드래프트 폴더 후보. 존재 여부는 확인하지 않는다."""
    system = platform.system()
    out: list[Path] = []

    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            base = Path(local)
            for app in ("CapCut", "JianyingPro"):
                out.append(base / app / DRAFT_SUBPATH)
    elif system == "Darwin":
        home = Path.home()
        out.append(home / "Movies" / "CapCut" / DRAFT_SUBPATH)
        out.append(home / "Movies" / "JianyingPro" / DRAFT_SUBPATH)
        out.append(
            home
            / "Library"
            / "Containers"
            / "com.lemon.lvpro"
            / "Data"
            / "Movies"
            / "CapCut"
            / DRAFT_SUBPATH
        )
    else:
        # 리눅스에는 CapCut 데스크톱이 없다. Wine 경로만 형식적으로.
        home = Path.home()
        out.append(
            home
            / ".wine"
            / "drive_c"
            / "users"
            / os.environ.get("USER", "user")
            / "AppData"
            / "Local"
            / "CapCut"
            / DRAFT_SUBPATH
        )

    env = os.environ.get("CAPCUT_DRAFTS_DIR")
    if env:
        out.insert(0, Path(env))
    return out


def find() -> Path | None:
    """실제로 존재하는 첫 번째 드래프트 폴더."""
    for path in candidates():
        if path.is_dir():
            return path
    return None


def describe() -> str:
    found = find()
    if found:
        return f"CapCut 드래프트 폴더: {found}"
    lines = ["CapCut 드래프트 폴더를 찾지 못했습니다. 확인한 위치:"]
    lines += [f"  - {p}" for p in candidates()]
    lines.append("직접 지정하려면 --drafts-dir 또는 CAPCUT_DRAFTS_DIR 환경변수를 쓰세요.")
    return "\n".join(lines)


def list_drafts(root: Path | None = None) -> list[Path]:
    root = root or find()
    if root is None or not root.is_dir():
        return []
    return sorted(
        p for p in root.iterdir() if p.is_dir() and (p / "draft_content.json").exists()
    )


__all__ = ["find", "candidates", "describe", "list_drafts", "DRAFT_SUBPATH"]
