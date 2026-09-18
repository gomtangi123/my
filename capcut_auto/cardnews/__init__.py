"""대본 한 편 → 인스타 카드뉴스 이미지 세트.

같은 대본으로 `capcut-auto edit` 의 슬라이드쇼 경로를 태우면 릴스까지
한 번에 나온다 — 캐러셀은 저장을 먹고 릴스는 도달을 먹는다.
"""

from .fonts import FontMissing
from .models import Card, Deck, Size, SIZES, resolve_size
from .render import PillowMissing, Style, build_style, render_card, render_deck
from .script import parse
from .theme import DEFAULT_THEME, THEMES, Layout, Theme, resolve as resolve_theme

__all__ = [
    "Card",
    "Deck",
    "Size",
    "SIZES",
    "resolve_size",
    "Theme",
    "Layout",
    "THEMES",
    "DEFAULT_THEME",
    "resolve_theme",
    "parse",
    "Style",
    "build_style",
    "render_card",
    "render_deck",
    "PillowMissing",
    "FontMissing",
]
