"""핵심 데이터 모델.

시간 단위는 전부 '초(float)'로 통일한다.
CapCut 드래프트로 나갈 때만 마이크로초 정수로 변환한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CutReason = Literal["silence", "filler", "stutter", "retake", "manual"]


@dataclass(frozen=True, order=True)
class Span:
    """[start, end) 구간. 초 단위."""

    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"end({self.end}) < start({self.start})")

    @property
    def duration(self) -> float:
        return self.end - self.start

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end

    def intersection(self, other: "Span") -> "Span | None":
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        return Span(start, end) if end > start else None

    def clamp(self, lo: float, hi: float) -> "Span":
        return Span(min(max(self.start, lo), hi), min(max(self.end, lo), hi))

    def padded(self, before: float, after: float) -> "Span":
        return Span(self.start - before, self.end + after)


@dataclass(frozen=True)
class Word:
    """Whisper 등에서 나온 단어 단위 타임스탬프."""

    start: float
    end: float
    text: str
    probability: float = 1.0

    @property
    def span(self) -> Span:
        return Span(self.start, self.end)


@dataclass(frozen=True)
class Cut:
    """잘라낼 구간 하나와 그 이유."""

    span: Span
    reason: CutReason
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "start": round(self.span.start, 3),
            "end": round(self.span.end, 3),
            "duration": round(self.span.duration, 3),
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class SubtitleLine:
    """자막 한 줄. `words`는 원본(컷 전) 타임라인 기준."""

    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)

    @property
    def span(self) -> Span:
        return Span(self.start, self.end)


@dataclass
class EditPlan:
    """분석 결과 전체. 렌더러/드래프트 생성기가 이걸 소비한다."""

    source: str
    source_duration: float
    keeps: list[Span]
    cuts: list[Cut]
    subtitles: list[SubtitleLine]
    # 순환 import를 피하려고 타입을 느슨하게 뒀다.
    # sfx: list[sfx.planner.SfxPlacement], overlays: list[assets.models.Overlay]
    sfx: list = field(default_factory=list)
    overlays: list = field(default_factory=list)

    @property
    def output_duration(self) -> float:
        return sum(s.duration for s in self.keeps)

    @property
    def removed_duration(self) -> float:
        return self.source_duration - self.output_duration

    def summary(self) -> dict:
        by_reason: dict[str, float] = {}
        counts: dict[str, int] = {}
        for cut in self.cuts:
            by_reason[cut.reason] = by_reason.get(cut.reason, 0.0) + cut.span.duration
            counts[cut.reason] = counts.get(cut.reason, 0) + 1
        return {
            "source": self.source,
            "source_duration": round(self.source_duration, 2),
            "output_duration": round(self.output_duration, 2),
            "removed_duration": round(self.removed_duration, 2),
            "removed_ratio": (
                round(self.removed_duration / self.source_duration, 4)
                if self.source_duration
                else 0.0
            ),
            "clip_count": len(self.keeps),
            "subtitle_count": len(self.subtitles),
            "sfx_count": len(self.sfx),
            "overlay_count": len(self.overlays),
            "removed_by_reason": {k: round(v, 2) for k, v in sorted(by_reason.items())},
            "cut_count_by_reason": dict(sorted(counts.items())),
        }

    def to_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "keeps": [
                {"start": round(s.start, 3), "end": round(s.end, 3)} for s in self.keeps
            ],
            "cuts": [c.to_dict() for c in self.cuts],
            "subtitles": [
                {
                    "text": s.text,
                    "start": round(s.start, 3),
                    "end": round(s.end, 3),
                }
                for s in self.subtitles
            ],
            "sfx": [s.to_dict() for s in self.sfx],
            "overlays": [o.to_dict() for o in self.overlays],
        }



__all__ = [
    "Span",
    "Word",
    "Cut",
    "CutReason",
    "SubtitleLine",
    "EditPlan",
]
