"""글자 줄바꿈과 크기 맞추기.

Pillow에 의존하지 않는다 — 글자 폭을 재는 함수를 밖에서 받아 쓰기 때문에
테스트에서는 가짜 자로 갈아 끼울 수 있다.

한국어는 어절 사이에만 공백이 있어서 영어식 단어 단위 줄바꿈만으로는
한 어절이 통째로 상자를 넘치는 일이 흔하다. 그래서 어절로 먼저 나누되,
그래도 넘치면 글자 단위로 쪼갠다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

# 글자열 → 픽셀 폭
Measure = Callable[[str], float]


class Metrics(Protocol):
    """글꼴 크기 하나에 대한 자(尺)."""

    def __call__(self, size: int) -> tuple[Measure, float]:
        """(폭 재는 함수, 줄 높이) 를 돌려준다."""


@dataclass
class Fit:
    """맞춰 놓은 결과."""

    size: int
    lines: list[str]
    line_height: float

    @property
    def height(self) -> float:
        return self.line_height * len(self.lines)


def wrap(text: str, measure: Measure, max_width: float) -> list[str]:
    """상자 폭에 맞춰 줄을 나눈다. 원문의 줄바꿈은 그대로 지킨다."""
    out: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            out.append("")  # 빈 줄은 문단 사이 여백이라 살려 둔다
            continue
        out.extend(_wrap_paragraph(paragraph.strip(), measure, max_width))
    return out


def _wrap_paragraph(text: str, measure: Measure, max_width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if measure(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        # 어절 하나가 이미 상자보다 넓으면 글자 단위로 쪼갠다.
        if measure(word) > max_width:
            chunks = _break_word(word, measure, max_width)
            lines.extend(chunks[:-1])
            current = chunks[-1]
        else:
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _break_word(word: str, measure: Measure, max_width: float) -> list[str]:
    """긴 어절을 글자 단위로 자른다. 최소 한 글자는 남긴다."""
    chunks: list[str] = []
    current = ""
    for ch in word:
        candidate = current + ch
        if current and measure(candidate) > max_width:
            chunks.append(current)
            current = ch
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [word]


def fit(
    text: str,
    metrics: Metrics,
    max_width: float,
    max_height: float,
    sizes: list[int],
    max_lines: int | None = None,
) -> Fit:
    """상자 안에 들어가는 가장 큰 글꼴 크기를 찾는다.

    `max_lines`를 주면 줄 수까지 조건이 된다. 숫자 강조 카드의 수치처럼
    쪼개지면 못 읽는 글에 쓴다 ("2,000만원"이 "2,000만"/"원"이 되면 곤란하다).

    `sizes`는 큰 것부터 내림차순으로 준다. 어느 것도 안 들어가면 마지막
    (가장 작은) 크기로 넘치는 채 돌려준다 — 여기서 예외를 던지면 대본
    한 줄 때문에 전체 작업이 죽는다. 넘치는 건 호출부가 알아서 줄이거나
    경고하면 된다.
    """
    if not sizes:
        raise ValueError("시도할 글꼴 크기가 없습니다.")

    result: Fit | None = None
    for size in sizes:
        measure, line_height = metrics(size)
        lines = wrap(text, measure, max_width)
        result = Fit(size=size, lines=lines, line_height=line_height)
        filled = sum(1 for line in lines if line)
        if result.height <= max_height and (max_lines is None or filled <= max_lines):
            return result
    assert result is not None
    return result


def ladder(largest: int, smallest: int, step: int = 2) -> list[int]:
    """`fit`에 넘길 크기 사다리. 큰 것부터 내림차순."""
    if smallest > largest:
        largest, smallest = smallest, largest
    return list(range(largest, smallest - 1, -max(1, step))) or [smallest]


__all__ = ["wrap", "fit", "ladder", "Fit", "Measure", "Metrics"]
