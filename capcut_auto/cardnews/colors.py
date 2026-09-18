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


def luminance_rgb(rgb: RGB) -> float:
    """픽셀 하나의 상대 휘도. 사진 위 글씨 대비를 잴 때 쓴다."""
    r, g, b = (_channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_lum(a: float, b: float) -> float:
    """휘도 두 개로 바로 대비비를 낸다."""
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


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


# 회색 막대를 만들 때 글자색을 배경 쪽으로 얼마나 밀지. 뒤로 갈수록 진해진다.
_RECEDE = (0.72, 0.66, 0.60, 0.54, 0.48, 0.42, 0.36, 0.30)


def de_emphasis(fg: str, bg: str, minimum: float = 3.0) -> str:
    """강조하지 않는 마크(회색 막대)의 색.

    글자색을 배경 쪽으로 최대한 밀되, 배경과의 대비가 `minimum` 밑으로는
    안 내려가게 한다. 도형은 3:1 이 기준이다 — 그보다 옅으면 막대가 있는지
    조차 안 보인다. 테마마다 배경이 달라서 비율을 상수로 박을 수 없다.
    """
    for ratio in _RECEDE:
        candidate = mix(fg, bg, ratio)
        if contrast(candidate, bg) >= minimum:
            return candidate
    return mix(fg, bg, _RECEDE[-1])


def reach_contrast(
    color: str, bg: str, toward: str, minimum: float = 4.5, steps: int = 10
) -> str:
    """색을 `toward` 쪽으로 밀어 배경과의 대비를 `minimum` 까지 끌어올린다.

    강조색을 **글씨로** 쓸 때 필요하다. 마크(막대·밑줄)는 3:1 이면 되지만
    글씨는 4.5:1 이라, 표지처럼 배경이 뒤집히는 자리에서는 같은 강조색이
    마크로는 통과하고 글씨로는 안 읽히는 일이 생긴다. 색상은 유지한 채
    밝기만 옮기려고 글자색 쪽으로 섞는다.
    """
    if contrast(color, bg) >= minimum:
        return color
    for i in range(1, steps + 1):
        candidate = mix(color, toward, i / steps * 0.9)
        if contrast(candidate, bg) >= minimum:
            return candidate
    return toward


def readable(color: str, bg: str, fallback: str, minimum: float) -> str:
    """배경 위에서 대비가 모자라면 대체색으로 물러선다."""
    return color if contrast(color, bg) >= minimum else fallback


__all__ = [
    "parse",
    "to_hex",
    "luminance",
    "luminance_rgb",
    "contrast",
    "contrast_lum",
    "mix",
    "readable",
    "de_emphasis",
    "reach_contrast",
    "RGB",
]
