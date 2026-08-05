"""자료화면 / 이미지 / GIF 관련 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AssetKind = Literal["image", "gif", "video"]


@dataclass(frozen=True)
class AssetRef:
    """제공자가 돌려준 후보. 아직 내려받기 전이다."""

    kind: AssetKind
    url: str
    source: str
    source_id: str
    width: int = 0
    height: int = 0
    duration: float = 0.0
    credit: str = ""
    page_url: str = ""

    @property
    def is_vertical(self) -> bool:
        return self.height > self.width > 0


@dataclass
class Asset:
    """내려받아 로컬에 있는 소재."""

    kind: AssetKind
    path: Path
    source: str
    source_id: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0
    credit: str = ""
    page_url: str = ""
    query: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "path": str(self.path),
            "source": self.source,
            "credit": self.credit,
            "page_url": self.page_url,
            "query": self.query,
            "width": self.width,
            "height": self.height,
            "duration": round(self.duration, 2),
        }


@dataclass
class Overlay:
    """출력 타임라인 위에 얹을 소재 하나."""

    start: float
    end: float
    asset: Asset
    keyword: str
    score: float = 0.0
    scale: float = 1.0
    position_y: float = 0.0
    reason: str = "keyword"

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
            "keyword": self.keyword,
            "score": round(self.score, 3),
            "scale": round(self.scale, 3),
            "reason": self.reason,
            "asset": self.asset.to_dict(),
        }


__all__ = [
    "AssetKind",
    "AssetRef",
    "Asset",
    "Overlay",
]
