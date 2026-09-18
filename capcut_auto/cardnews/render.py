"""카드 이미지 그리기 (Pillow).

카드 한 장은 이렇게 생겼다.

    ┌────────────────────────┐
    │                        │  ← 여백
    │  제목                   │
    │  ▁▁▁▁                  │  ← 강조 막대 (표지 / 마무리)
    │                        │
    │  본문 ...               │
    │                        │
    │  @계정            3/7   │  ← 꼬리말
    └────────────────────────┘

표지와 마무리는 가운데 정렬, 본문은 위쪽 정렬이다. 넘기면서 읽을 때
본문 시작 위치가 장마다 흔들리지 않는 편이 눈이 편하다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import fonts, layout as layout_mod
from .models import Card, Deck, Size
from .theme import Layout, Theme


class PillowMissing(RuntimeError):
    """Pillow가 없을 때. 카드뉴스에만 필요해서 선택 의존성으로 뒀다."""


def _require_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except ImportError as exc:  # pragma: no cover - 설치 환경에 따라 다름
        raise PillowMissing(
            "카드뉴스를 그리려면 Pillow가 필요합니다.\n"
            '  pip install "capcut-auto[cardnews]"   (또는  pip install pillow)'
        ) from exc
    return Image, ImageDraw, ImageFont


@lru_cache(maxsize=256)
def _font(path: str, size: int):
    _, _, ImageFont = _require_pillow()
    # .ttc 묶음 글꼴은 첫 번째 얼굴을 쓴다.
    return ImageFont.truetype(path, size)


def _metrics(path: str, spacing: float):
    """layout.fit 에 넘길 자. 크기마다 (폭 재는 함수, 줄 높이)."""

    def make(size: int):
        font = _font(path, size)
        ascent, descent = font.getmetrics()
        return font.getlength, (ascent + descent) * spacing

    return make


@dataclass
class Style:
    """한 벌의 카드에 공통으로 적용되는 것들."""

    theme: Theme
    size: Size
    layout: Layout
    regular: str
    bold: str
    # 꼬리말 왼쪽에 박는 계정명 등. 비우면 안 그린다.
    handle: str = ""
    # 표지에 "넘겨보세요" 힌트를 넣을지
    swipe_hint: bool = True
    # 이미지 출처 등. 마지막 장 아래에만 한 줄로 박는다.
    source: str = ""


def _px(style: Style, ratio: float) -> int:
    """짧은 변 기준 비율을 픽셀로."""
    return max(1, int(round(min(style.size.width, style.size.height) * ratio)))


def _sizes(style: Style, largest: float, smallest: float) -> list[int]:
    return layout_mod.ladder(_px(style, largest), _px(style, smallest))


def render_card(
    card: Card, style: Style, page: str = "", is_last: bool = False
) -> "object":
    """카드 한 장을 Pillow Image로. 저장은 호출부가 한다."""
    Image, ImageDraw, _ = _require_pillow()
    lay = style.layout
    width, height = style.size.width, style.size.height
    bg, fg = style.theme.colors(card.kind)
    accent, _ = style.theme.marks(card.kind)
    # 숫자 카드는 수치 자체가 강조라, 제목을 강조색으로 그리고 밑줄은 뺀다.
    title_fill = accent if card.kind == "stat" else fg

    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)

    margin = _px(style, lay.margin)
    footer_h = _px(style, lay.footer) * 3
    box_w = width - margin * 2
    top = margin
    box_h = height - margin - footer_h - top

    centered = card.kind in ("cover", "outro", "stat")
    title_range = {
        "cover": (lay.cover_title_max, lay.cover_title_min),
        "stat": (lay.stat_max, lay.stat_min),
    }.get(card.kind, (lay.title_max, lay.title_min))

    blocks: list[tuple[layout_mod.Fit, str, bool]] = []  # (맞춘 글, 글꼴 경로, 굵게)
    if card.title.strip():
        blocks.append(
            (
                layout_mod.fit(
                    card.title.strip(),
                    _metrics(style.bold, lay.title_line_spacing),
                    box_w,
                    box_h if not card.body.strip() else box_h * 0.62,
                    _sizes(style, *title_range),
                    max_lines=1 if card.kind == "stat" else None,
                ),
                style.bold,
                True,
            )
        )
    if card.body.strip():
        used = blocks[0][0].height if blocks else 0.0
        remaining = box_h - used - (_px(style, lay.gap) if blocks else 0)
        blocks.append(
            (
                layout_mod.fit(
                    card.body.strip(),
                    _metrics(style.regular, lay.body_line_spacing),
                    box_w,
                    max(remaining, _px(style, lay.body_min)),
                    _sizes(style, lay.body_max, lay.body_min),
                ),
                style.regular,
                False,
            )
        )

    gap = _px(style, lay.gap)
    rule_h = (
        _px(style, lay.rule_height)
        if card.kind in ("cover", "outro") and card.title.strip()
        else 0
    )
    rule_gap = gap if rule_h else 0
    total = sum(b[0].height for b in blocks) + gap * (len(blocks) - 1) + rule_h + rule_gap
    y = top + max(0.0, (box_h - total) / 2) if centered else float(top)

    x = width / 2 if centered else float(margin)
    anchor = "ma" if centered else "la"

    for i, (fitted, path, is_title) in enumerate(blocks):
        font = _font(path, fitted.size)
        for row, line in enumerate(fitted.lines):
            if line:
                draw.text(
                    (x, y + row * fitted.line_height),
                    line,
                    font=font,
                    fill=title_fill if is_title else fg,
                    anchor=anchor,
                )
        y += fitted.height
        # 제목 아래 강조 막대 — 표지/마무리에서 시선을 한 번 끊어 준다.
        if is_title and rule_h:
            y += rule_gap / 2
            rule_w = _px(style, lay.rule_width)
            draw.rectangle(
                [x - rule_w / 2, y, x + rule_w / 2, y + rule_h],
                fill=accent,
            )
            y += rule_h + rule_gap / 2
        if i < len(blocks) - 1:
            y += gap

    _draw_footer(draw, style, card, page, is_last)
    return image


def _draw_footer(
    draw, style: Style, card: Card, page: str, is_last: bool = False
) -> None:
    lay = style.layout
    accent, muted = style.theme.marks(card.kind)
    margin = _px(style, lay.margin)
    font = _font(style.regular, _px(style, lay.footer))
    baseline = style.size.height - margin

    # 표지의 페이지 번호는 군더더기다. 대신 넘기라는 신호를 준다.
    if card.kind == "cover":
        if style.swipe_hint and page:
            draw.text(
                (style.size.width - margin, baseline),
                "넘겨보세요 →",
                font=font,
                fill=accent,
                anchor="rs",
            )
    elif page:
        draw.text(
            (style.size.width - margin, baseline),
            page,
            font=font,
            fill=muted,
            anchor="rs",
        )

    if style.handle:
        draw.text(
            (margin, baseline), style.handle, font=font, fill=muted, anchor="ls"
        )

    # 출처는 마지막 장에만. 매 장에 넣으면 그냥 지저분하다.
    if is_last and style.source:
        small = _font(style.regular, _px(style, lay.source))
        draw.text(
            (style.size.width / 2, baseline - _px(style, lay.footer) * 1.9),
            style.source,
            font=small,
            fill=muted,
            anchor="ms",
        )


def render_deck(
    deck: Deck,
    out_dir: str | Path,
    style: Style,
    progress=None,
) -> list[Path]:
    """카드 묶음을 PNG로 떨군다. 파일 이름은 `01.png`부터.

    두 자리 숫자로 시작하게 두는 이유는 인스타 업로드 화면에서든
    `capcut-auto edit`의 슬라이드쇼 입력으로든 순서가 그대로 지켜지기
    때문이다.
    """
    say = progress or (lambda _msg: None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(deck.cards)
    paths: list[Path] = []
    for card in deck.cards:
        page = f"{card.index + 1}/{total}" if total > 1 else ""
        image = render_card(card, style, page, is_last=card.index == total - 1)
        path = out_dir / f"{card.index + 1:02d}.png"
        image.save(path, "PNG", optimize=True)
        paths.append(path)
        say(f"  {path.name}  {card.kind:<5}  {(card.title or card.body)[:28]}")
    return paths


def build_style(
    theme: Theme,
    size: Size,
    font: str | None = None,
    handle: str = "",
    source: str = "",
    layout: Layout | None = None,
) -> Style:
    regular, bold = fonts.find(font)
    return Style(
        theme=theme,
        size=size,
        layout=layout or Layout(),
        regular=str(regular),
        bold=str(bold),
        handle=handle,
        source=source,
    )


__all__ = ["render_card", "render_deck", "build_style", "Style", "PillowMissing"]
