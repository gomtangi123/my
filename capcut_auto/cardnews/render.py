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

from . import chart as chart_mod, colors, compose, fonts, layout as layout_mod, photos as photos_mod
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


def _background(card: Card, style: Style, photo, mode: str, bg: str, fg: str):
    """(배경 이미지, 글이 시작할 y, 글이 쓸 수 있는 높이).

    꽉 채우기(full)는 사진 위에 장막을 씌우고 그 위에 글을 쓴다. 장막 진하기는
    사진의 실제 픽셀을 재서 정한다 — `compose.scrim_alpha` 참고.
    띠(band)는 위쪽에 사진, 아래쪽 단색 바탕에 글이라 장막이 필요 없다.
    """
    Image, _, _ = _require_pillow()
    lay = style.layout
    width, height = style.size.width, style.size.height
    margin = _px(style, lay.margin)
    footer_h = _px(style, lay.footer) * 3
    plain_top = margin
    plain_h = height - margin - footer_h - plain_top

    if photo is None or mode == photos_mod.NONE:
        return Image.new("RGB", (width, height), bg), plain_top, plain_h

    try:
        source = Image.open(photo.path)
    except (OSError, ValueError):
        # 사진이 깨졌다고 카드까지 못 만들 이유는 없다.
        return Image.new("RGB", (width, height), bg), plain_top, plain_h

    if mode == photos_mod.FULL:
        filled = compose.cover_crop(source, width, height)
        # 글은 카드 전체에 흩어져 있다(꼬리말 포함)이라 전면을 기준으로 잰다.
        alpha = compose.scrim_alpha(filled, (0, 0, width, height), fg, bg)
        return compose.apply_scrim(filled, bg, alpha), plain_top, plain_h

    band_h = max(1, int(round(height * lay.band)))
    canvas = Image.new("RGB", (width, height), bg)
    canvas.paste(compose.cover_crop(source, width, band_h), (0, 0))
    top = band_h + margin
    return canvas, top, height - margin - footer_h - top


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
    # "auto" / "full" / "band" / "off". auto면 카드 종류가 정한다.
    photo_mode: str = "auto"


def _px(style: Style, ratio: float) -> int:
    """짧은 변 기준 비율을 픽셀로."""
    return max(1, int(round(min(style.size.width, style.size.height) * ratio)))


def _sizes(style: Style, largest: float, smallest: float) -> list[int]:
    return layout_mod.ladder(_px(style, largest), _px(style, smallest))


def render_card(
    card: Card,
    style: Style,
    page: str = "",
    is_last: bool = False,
    photo=None,
) -> "object":
    """카드 한 장을 Pillow Image로. 저장은 호출부가 한다."""
    Image, ImageDraw, _ = _require_pillow()
    lay = style.layout
    width, height = style.size.width, style.size.height
    bg, fg = style.theme.colors(card.kind)
    accent, _ = style.theme.marks(card.kind)
    # 숫자 카드는 수치 자체가 강조라, 제목을 강조색으로 그리고 밑줄은 뺀다.
    title_fill = accent if card.kind == "stat" else fg

    mode = photos_mod.mode_for(card, style.photo_mode)
    image, top, box_h = _background(card, style, photo, mode, bg, fg)
    draw = ImageDraw.Draw(image)

    margin = _px(style, lay.margin)
    box_w = width - margin * 2

    is_chart = card.kind in ("bars", "table")
    centered = (
        card.kind in ("cover", "outro", "stat")
        and mode != photos_mod.BAND
    )
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
    if card.body.strip() and not is_chart:
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

    if is_chart:
        _draw_chart(draw, card, style, margin, y + gap, box_w, top + box_h - (y + gap))

    _draw_footer(draw, style, card, page, is_last)
    return image


def _draw_chart(draw, card: Card, style: Style, left, top, width, height) -> None:
    """표 / 막대 카드의 알맹이. 제목을 그리고 남은 자리에 들어간다."""
    if height <= 0:
        return
    bg, fg = style.theme.colors(card.kind)
    accent, muted = style.theme.marks(card.kind)
    box = (int(left), int(top), int(width), int(height))

    def font_at(size: int, bold: bool = False):
        return _font(style.bold if bold else style.regular, max(8, int(size)))

    if card.kind == "bars":
        chart_mod.draw_bars(
            draw,
            chart_mod.parse_bars(card.body, card.unit),
            box,
            font_at,
            ink=fg,
            muted=muted,
            accent=accent,
            grey=colors.de_emphasis(fg, bg),
            unit=min(style.size.width, style.size.height),
        )
    else:
        chart_mod.draw_table(
            draw,
            chart_mod.parse_table(card.body),
            box,
            font_at,
            ink=fg,
            muted=muted,
            accent=accent,
            # 칸 구분선은 바탕에서 한 단계만 벗어난 실선.
            rule=colors.mix(fg, bg, 0.86),
        )


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
    photos: dict[int, object] | None = None,
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
        image = render_card(
            card,
            style,
            page,
            is_last=card.index == total - 1,
            photo=(photos or {}).get(card.index),
        )
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
    photo_mode: str = "auto",
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
        photo_mode=photo_mode,
    )


__all__ = ["render_card", "render_deck", "build_style", "Style", "PillowMissing"]
