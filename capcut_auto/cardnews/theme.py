"""카드 테마 — 색과 여백 비율.

색은 `#RRGGBB` 문자열로 둔다 (Pillow가 그대로 받는다). 비율은 전부 짧은 변
기준이라, 1080x1080이든 1080x1920이든 같은 테마가 같은 인상으로 나온다.

표지는 본문과 색을 뒤집는 테마가 많다. 피드에서 넘기는 손가락을 멈추게 하는
건 첫 장 한 장뿐이라, 나머지와 달라 보이는 편이 낫다.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import colors


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    fg: str
    # 표지 제목 밑줄, 페이지 번호, 강조에 쓰는 색
    accent: str
    # 본문보다 한 단계 약한 글자 (페이지 번호, 계정명)
    muted: str
    # 표지 전용. 비우면 본문과 같은 색을 쓴다.
    cover_bg: str = ""
    cover_fg: str = ""

    def colors(self, kind: str) -> tuple[str, str]:
        """카드 종류에 맞는 (배경, 글자) 색."""
        if kind == "cover" and self.cover_bg and self.cover_fg:
            return self.cover_bg, self.cover_fg
        return self.bg, self.fg

    def marks(self, kind: str) -> tuple[str, str]:
        """그 카드 배경 위에서 실제로 보이는 (강조, 약한 글자) 색.

        표지에서 배경을 뒤집는 테마는 본문 기준으로 고른 강조색이 배경과
        같은 색이 되어 버린다. 대비를 재서 모자라면 글자색 쪽으로 물러선다.
        """
        bg, fg = self.colors(kind)
        accent = colors.readable(self.accent, bg, fg, minimum=3.0)
        muted = colors.readable(self.muted, bg, colors.mix(fg, bg, 0.40), minimum=2.5)
        return accent, muted


@dataclass(frozen=True)
class Layout:
    """짧은 변에 대한 비율. 전부 0~1."""

    margin: float = 0.085
    # 제목 글꼴 크기 사다리 (표지 / 본문)
    cover_title_max: float = 0.135
    cover_title_min: float = 0.070
    title_max: float = 0.082
    title_min: float = 0.046
    body_max: float = 0.052
    body_min: float = 0.030
    # 숫자 강조 카드 — 수치 하나만 크게 박는다. 제목보다 훨씬 크다.
    stat_max: float = 0.230
    stat_min: float = 0.090
    # 큰 제목을 본문과 같은 간격으로 벌리면 한 덩어리로 안 읽힌다.
    title_line_spacing: float = 1.16
    body_line_spacing: float = 1.38
    # 제목과 본문 사이
    gap: float = 0.045
    # 표지 제목 밑에 깔리는 강조 막대
    rule_height: float = 0.010
    rule_width: float = 0.150
    footer: float = 0.026
    # 출처 한 줄 (마지막 장에만)
    source: float = 0.019
    # 띠 사진이 먹는 카드 높이 비율 (짧은 변이 아니라 세로 기준)
    band: float = 0.42


THEMES: dict[str, Theme] = {
    "light": Theme(
        name="light",
        bg="#FFFFFF",
        fg="#16181D",
        accent="#2F6BFF",
        muted="#6E7480",
        cover_bg="#16181D",
        cover_fg="#FFFFFF",
    ),
    "dark": Theme(
        name="dark",
        bg="#101317",
        fg="#F5F6F7",
        accent="#6EA8FF",
        muted="#9AA1AC",
    ),
    "bold": Theme(
        name="bold",
        bg="#FFFFFF",
        fg="#16181D",
        accent="#1B4DFF",
        muted="#6E7480",
        cover_bg="#1B4DFF",
        cover_fg="#FFFFFF",
    ),
    "paper": Theme(
        name="paper",
        bg="#F4F1EA",
        fg="#23201B",
        accent="#B3541E",
        muted="#7A736A",
        cover_bg="#23201B",
        cover_fg="#F4F1EA",
    ),
}

DEFAULT_THEME = "light"


def resolve(name: str) -> Theme:
    key = name.strip().lower()
    if key not in THEMES:
        raise ValueError(
            f"모르는 테마입니다: {name} (가능: {', '.join(THEMES)})"
        )
    return THEMES[key]


__all__ = ["Theme", "Layout", "THEMES", "DEFAULT_THEME", "resolve"]
