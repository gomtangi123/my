"""구간(Span) 집합 연산과 컷 전/후 타임라인 매핑.

컷편집의 뼈대. 여기가 틀리면 자막 싱크가 통째로 밀리므로
전부 순수 함수로 두고 테스트로 고정한다.
"""

from __future__ import annotations

from bisect import bisect_right

from .models import Span


def merge(spans: list[Span], gap: float = 0.0) -> list[Span]:
    """겹치거나 `gap` 이내로 붙어있는 구간을 합친다."""
    ordered = sorted(s for s in spans if s.duration > 0)
    if not ordered:
        return []
    merged = [ordered[0]]
    for span in ordered[1:]:
        last = merged[-1]
        if span.start - last.end <= gap:
            if span.end > last.end:
                merged[-1] = Span(last.start, span.end)
        else:
            merged.append(span)
    return merged


def invert(spans: list[Span], total: float, start: float = 0.0) -> list[Span]:
    """[start, total) 안에서 `spans`의 여집합."""
    result: list[Span] = []
    cursor = start
    for span in merge(spans):
        clipped = span.clamp(start, total)
        if clipped.start > cursor:
            result.append(Span(cursor, clipped.start))
        cursor = max(cursor, clipped.end)
    if cursor < total:
        result.append(Span(cursor, total))
    return result


def subtract(base: list[Span], holes: list[Span]) -> list[Span]:
    """`base`에서 `holes`를 파낸다."""
    holes = merge(holes)
    result: list[Span] = []
    for span in merge(base):
        cursor = span.start
        for hole in holes:
            if hole.end <= cursor:
                continue
            if hole.start >= span.end:
                break
            if hole.start > cursor:
                result.append(Span(cursor, hole.start))
            cursor = max(cursor, hole.end)
        if cursor < span.end:
            result.append(Span(cursor, span.end))
    return result


def drop_short(spans: list[Span], min_duration: float) -> list[Span]:
    """너무 짧은 구간을 버린다 (한 프레임짜리 클립 방지)."""
    return [s for s in spans if s.duration >= min_duration]


def pad_all(spans: list[Span], before: float, after: float, total: float) -> list[Span]:
    """각 구간을 앞뒤로 늘린 뒤 다시 병합한다."""
    padded = [s.padded(before, after).clamp(0.0, total) for s in spans]
    return merge(padded)



class TimeMap:
    """원본 시간 -> 컷 후 시간 변환기.

    `keeps`는 정렬·병합된 유지 구간 목록이어야 한다.
    """

    def __init__(self, keeps: list[Span]):
        self.keeps = merge(keeps)
        self._starts = [s.start for s in self.keeps]
        self._offsets: list[float] = []
        acc = 0.0
        for span in self.keeps:
            self._offsets.append(acc)
            acc += span.duration
        self.output_duration = acc

    def is_kept(self, t: float) -> bool:
        idx = bisect_right(self._starts, t) - 1
        if idx < 0:
            return False
        span = self.keeps[idx]
        return span.start <= t < span.end

    def to_output(self, t: float) -> float | None:
        """잘려나간 시각이면 None."""
        idx = bisect_right(self._starts, t) - 1
        if idx < 0:
            return None
        span = self.keeps[idx]
        if t > span.end:
            return None
        return self._offsets[idx] + (t - span.start)

    def snap_to_output(self, t: float, prefer: str = "forward") -> float:
        """잘린 시각이면 가장 가까운 살아있는 지점으로 붙여서 항상 값을 준다.

        prefer="forward": 다음 유지 구간의 시작으로 (자막 시작점용)
        prefer="back":    이전 유지 구간의 끝으로   (자막 종료점용)
        """
        exact = self.to_output(t)
        if exact is not None:
            return exact
        if not self.keeps:
            return 0.0
        if t < self.keeps[0].start:
            return 0.0
        if t >= self.keeps[-1].end:
            return self.output_duration
        idx = bisect_right(self._starts, t) - 1
        if prefer == "back":
            span = self.keeps[idx]
            return self._offsets[idx] + span.duration
        return self._offsets[idx + 1]

    def map_span(self, span: Span) -> Span | None:
        """구간을 컷 후 타임라인으로 옮긴다. 완전히 잘렸으면 None.

        구간 중간이 잘려나간 경우엔 살아남은 부분들을 하나로 이어 붙인
        범위를 돌려준다 (자막 한 줄이 컷을 가로지르는 경우).
        """
        pieces = []
        for keep in self.keeps:
            hit = keep.intersection(span)
            if hit is not None and hit.duration > 0:
                pieces.append(hit)
        if not pieces:
            return None
        start = self.to_output(pieces[0].start)
        last = pieces[-1]
        end = self.to_output(last.start)
        assert start is not None and end is not None
        return Span(start, end + last.duration)


__all__ = [
    "merge",
    "invert",
    "subtract",
    "drop_short",
    "pad_all",
    "TimeMap",
]
