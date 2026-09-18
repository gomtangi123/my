"""색 대비 계산.

표지는 배경을 뒤집는 테마가 있어서, 본문 기준으로 고른 강조색이 표지에서는
배경과 같은 색이 되어 버리는 일이 생긴다 (`bold` 테마의 파란 배경 + 파란
강조 막대). 눈으로 확인하지 않으면 그냥 안 보이는 채로 나간다.

그래서 색을 고정하지 않고, 실제 배경과의 대비를 재서 모자라면 글자색으로
물러선다. WCAG 상대 휘도 공식을 쓴다.
"""

from __future__ import annotations

RGB = tuple[int, int, int]


def parse(color: str) -> RGB:
    """`#RRGGBB` → (r, g, b)."""
    text = color.strip().lstrip("#")
    if len(text) == 3:  # #abc 축약형
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError(f"색 형식이 아닙니다: {color}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def to_hex(rgb: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(round(c)))) for c in rgb))


def _channel(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    r, g, b = (_channel(c) for c in parse(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG 대비비. 1.0(같은 색) ~ 21.0(검정 대 흰색)."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def mix(a: str, b: str, ratio: float) -> str:
    """a를 b 쪽으로 `ratio`(0~1)만큼 섞는다."""
    ra, rb = parse(a), parse(b)
    t = max(0.0, min(1.0, ratio))
    return to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def readable(color: str, bg: str, fallback: str, minimum: float) -> str:
    """배경 위에서 대비가 모자라면 대체색으로 물러선다."""
    return color if contrast(color, bg) >= minimum else fallback


__all__ = ["parse", "to_hex", "luminance", "contrast", "mix", "readable", "RGB"]
