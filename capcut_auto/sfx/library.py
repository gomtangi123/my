"""효과음 소스 관리.

사용자가 가진 효과음 폴더를 우선 쓰고, 없으면 내장 합성음으로 채운다.
폴더 안 파일 이름이 곧 태그다: `whoosh_transition_01.wav` -> {whoosh, transition, 01}
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import builtin

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".aiff", ".aif"}
_SPLIT_RE = re.compile(r"[^a-z0-9가-힣]+")


@dataclass
class Sound:
    key: str
    path: Path
    tags: frozenset[str]
    duration: float = 0.0
    builtin: bool = False


@dataclass
class Library:
    """태그로 효과음을 찾아 주는 색인. 같은 태그는 돌아가며 쓴다(반복감 방지)."""

    sounds: list[Sound] = field(default_factory=list)
    scratch_dir: Path | None = None
    _cursor: dict[str, int] = field(default_factory=dict, repr=False)
    _cache: dict[str, Sound] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, folder: str | Path | None, scratch_dir: Path) -> "Library":
        sounds: list[Sound] = []
        if folder:
            root = Path(folder).expanduser()
            if not root.is_dir():
                raise FileNotFoundError(f"효과음 폴더가 없습니다: {root}")
            for path in sorted(root.rglob("*")):
                if path.suffix.lower() not in AUDIO_EXTS or not path.is_file():
                    continue
                tags = _tags_from(path, root)
                sounds.append(Sound(key=path.stem, path=path, tags=tags))
        return cls(sounds=sounds, scratch_dir=Path(scratch_dir))

    def find(self, key: str) -> Sound | None:
        """`key`(예: "whoosh")에 맞는 소리. 없으면 내장음으로 만들어서라도 준다."""
        key = key.strip().lower()
        if not key:
            return None

        matches = [s for s in self.sounds if key in s.tags]
        if not matches:
            matches = [s for s in self.sounds if key in s.key.lower()]

        if matches:
            index = self._cursor.get(key, 0)
            self._cursor[key] = index + 1
            return matches[index % len(matches)]

        return self._builtin(key)

    def _builtin(self, key: str) -> Sound | None:
        if key in self._cache:
            return self._cache[key]
        if key not in builtin.BUILTIN_SOUNDS or self.scratch_dir is None:
            return None
        path = builtin.ensure(key, self.scratch_dir)
        sound = Sound(
            key=key,
            path=path,
            tags=frozenset({key}),
            duration=builtin.duration_of(key),
            builtin=True,
        )
        self._cache[key] = sound
        return sound

    def resolve_duration(self, sound: Sound) -> float:
        """길이를 모르면 ffprobe로 읽는다."""
        if sound.duration > 0:
            return sound.duration
        from ..ffmpeg import probe

        try:
            sound.duration = probe(sound.path).duration
        except Exception:
            sound.duration = 0.5
        return sound.duration

    def describe(self) -> str:
        if not self.sounds:
            return "효과음: 내장 합성음 사용 (라이브러리 없음)"
        return f"효과음 라이브러리: {len(self.sounds)}개 파일"


def _tags_from(path: Path, root: Path) -> frozenset[str]:
    """파일 이름 + 상위 폴더 이름을 전부 태그로 삼는다."""
    parts: list[str] = []
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = Path(path.name)
    for piece in relative.parts[:-1]:
        parts.extend(_SPLIT_RE.split(piece.lower()))
    parts.extend(_SPLIT_RE.split(path.stem.lower()))
    return frozenset(p for p in parts if p and not p.isdigit())


__all__ = ["Library", "Sound", "AUDIO_EXTS"]
