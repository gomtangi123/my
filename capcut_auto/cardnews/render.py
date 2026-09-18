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

from . import (
    backdrop as backdrop_mod,
    chart as chart_mod,
    colors,
    compose,
    fonts,
    layout as layout_mod,
    photos as photos_mod,
    poster as poster_mod,
)
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


def _brand_height(style: Style) -> float:
    """맨 위 브랜드 줄이 먹는 높이. 내용은 여기 아래에서 시작한다."""
    size = _px(style, style.layout.brand)
    return _px(style, style.layout.margin) * 0.72 + size + size * 0.9


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
    footer_h = _px(style, lay.footer) * 2
    plain_top = _brand_height(style) + margin * 0.5
    plain_h = height - margin - footer_h - plain_top

    if photo is None or mode == photos_mod.NONE:
        made = None
        if card.backdrop:
            accent, _ = style.theme.marks(card.kind)
            made = _backdrop_for(card, style, width, height, bg, fg, accent)
        return (
            made or Image.new("RGB", (width, height), bg),
            plain_top,
            plain_h,
        )

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

    # 띠 사진은 브랜드 줄 아래에서 시작한다. 그 위에 겹치면 계정명이
    # 사진에 묻힌다 — 글씨 대비를 사진마다 다시 재느니 자리를 비켜 준다.
    band_top = int(_brand_height(style))
    band_h = max(1, int(round(height * lay.band)))
    canvas = Image.new("RGB", (width, height), bg)
    canvas.paste(compose.cover_crop(source, width, band_h), (0, band_top))
    top = band_top + band_h + margin
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
    # 표지 알약 버튼의 기본 문구. `@버튼` 으로 카드마다 바꿀 수 있다.
    save_cta: str = "나중에 보려면 저장"
    # 사진이 없을 때 표지에 깔 배경. "off" 면 단색으로 둔다.
    backdrop: str = backdrop_mod.DEFAULT_STYLE


def _px(style: Style, ratio: float) -> int:
    """짧은 변 기준 비율을 픽셀로."""
    return max(1, int(round(min(style.size.width, style.size.height) * ratio)))


def _sizes(style: Style, largest: float, smallest: float) -> list[int]:
    return layout_mod.ladder(_px(style, largest), _px(style, smallest))


def _font_at(style: Style):
    """poster / chart 가 함께 쓰는 글꼴 공급자."""

    def font_at(size, bold: bool = False):
        return _font(style.bold if bold else style.regular, max(8, int(size)))

    return font_at


def _backdrop_for(card: Card, style: Style, width, height, bg, fg, accent):
    """`@배경` 또는 기본 설정으로 배경을 만든다. 꺼져 있으면 None."""
    name = card.backdrop or style.backdrop
    if not name or name == "off":
        return None
    try:
        return backdrop_mod.make(
            name,
            width,
            height,
            bg,
            fg,
            accent,
            seed=backdrop_mod.seed_of(f"{card.title}\n{card.body}\n{card.kicker}"),
        )
    except ValueError:
        return None


def _render_cover(card: Card, style: Style, page: str, total: int, photo, mode: str):
    """표지 — 글을 아래에 모으고 사진은 위를 살린다.

    기하를 **먼저** 다 계산한 뒤에 배경을 만든다. 글이 어디서 시작하는지
    알아야 장막을 딱 거기까지만 씌울 수 있기 때문이다. 장막 범위를 상수로
    박아 두면 말머리처럼 위쪽에 놓이는 줄이 범위 밖으로 삐져나가 묻힌다.
    """
    Image, ImageDraw, _ = _require_pillow()
    lay = style.layout
    width, height = style.size.width, style.size.height
    bg, fg = style.theme.colors("cover")
    accent, muted = style.theme.marks("cover")
    ink_accent = style.theme.text_accent("cover")
    margin = _px(style, lay.margin)
    px = lambda ratio: _px(style, ratio)  # noqa: E731
    box_w = width - margin * 2
    gap = px(lay.gap)

    # ---------------------------------------------------------- 1) 기하
    cursor = float(height - margin)
    cursor -= poster_mod.dots_height(style, total, px)

    cta = card.cta or (style.save_cta if total > 1 else "")
    pill_h = poster_mod.pill_height(cta, style, px)
    pill_bottom = cursor
    if pill_h:
        cursor -= pill_h + gap

    body_fit = body_bottom = None
    if card.body.strip():
        body_fit = layout_mod.fit(
            card.body.strip(),
            _metrics(style.regular, lay.body_line_spacing),
            box_w,
            height * 0.22,
            _sizes(style, lay.body_max * 0.78, lay.body_min),
        )
        body_bottom = cursor
        cursor -= body_fit.height + gap * 0.7

    title_fit = title_bottom = None
    owners: list[int] = []  # 제목 줄이 `|` 로 나눈 몇 번째 덩어리인지
    if card.title.strip():
        parts = poster_mod.split_title(card.title)
        title_fit = layout_mod.fit(
            "\n".join(parts),
            _metrics(style.bold, lay.title_line_spacing),
            box_w,
            height * 0.42,
            _sizes(style, lay.cover_title_max, lay.cover_title_min),
        )
        measure, _ = _metrics(style.bold, lay.title_line_spacing)(title_fit.size)
        for i, part in enumerate(parts):
            owners += [i] * len(layout_mod.wrap(part, measure, box_w))
        title_bottom = cursor
        cursor -= title_fit.height + gap * 0.45

    kicker_size = px(lay.kicker)
    kicker_baseline = None
    if card.kicker.strip():
        kicker_baseline = cursor
        cursor -= kicker_size * 1.4

    block_top = max(0.0, cursor - gap * 0.5)

    # ---------------------------------------------------------- 2) 배경
    image = Image.new("RGB", (width, height), bg)
    source = None
    if photo is not None and mode != photos_mod.NONE:
        try:
            source = Image.open(photo.path)
        except (OSError, ValueError):
            source = None
    if source is None:
        # 사진이 없으면 테마 색으로 배경을 만들어 쓴다. 남의 사진을 변형해
        # 쓰는 것과 달리 출처 문제가 없고, 덱이 한 벌로 보인다.
        source = _backdrop_for(card, style, width, height, bg, fg, accent)
    if source is not None:
        # 사진이든 만들어 쓴 배경이든 여기서부터는 똑같이 다룬다.
        filled = compose.cover_crop(source, width, height)
        veil = poster_mod.veil_for(fg, bg)
        hold = min(0.62, max(0.14, block_top / height))
        peak = compose.scrim_alpha(
            filled, (0, int(block_top), width, height), fg, veil
        )
        image = compose.gradient_scrim(
            filled, veil, peak, start=max(0.02, hold - 0.32), hold=hold
        )
        # 장막은 글자색(보통 흰색) 기준으로 잡았다. 강조색은 중간 밝기라
        # 같은 배경에서 훨씬 불리하므로, 실제로 잰 배경에 맞춰 다시 민다.
        worst = compose.extreme_luminance(
            image, (0, int(block_top), width, height), bright=True
        )
        ink_accent = colors.reach_contrast_lum(ink_accent, worst, fg, minimum=4.5)

    # ---------------------------------------------------------- 3) 그리기
    draw = ImageDraw.Draw(image)
    font_at = _font_at(style)
    poster_mod.draw_brand_bar(draw, style, page, fg, muted, accent, font_at, px)
    poster_mod.draw_dots(draw, style, card.index, total, fg, muted, px)

    if pill_h:
        poster_mod.draw_pill(
            draw, cta, style, pill_bottom, colors.mix(bg, fg, 0.26), fg, font_at, px
        )
    if body_fit is not None:
        poster_mod.draw_block_bottom(
            draw, body_fit, _font(style.regular, body_fit.size), margin, body_bottom, fg
        )
    if title_fit is not None:
        # 첫 덩어리는 글자색, `|` 뒤는 강조색.
        fills = [fg if owner == 0 else ink_accent for owner in owners]
        poster_mod.draw_block_bottom(
            draw, title_fit, _font(style.bold, title_fit.size), margin, title_bottom, fills
        )
    if kicker_baseline is not None:
        draw.text(
            (margin, kicker_baseline),
            card.kicker.strip(),
            font=_font(style.bold, kicker_size),
            fill=ink_accent,
            anchor="ld",
        )
    return image


def render_card(
    card: Card,
    style: Style,
    page: str = "",
    is_last: bool = False,
    photo=None,
    total: int = 0,
) -> "object":
    """카드 한 장을 Pillow Image로. 저장은 호출부가 한다."""
    Image, ImageDraw, _ = _require_pillow()
    if card.kind == "cover":
        return _render_cover(
            card, style, page, total, photo, photos_mod.mode_for(card, style.photo_mode)
        )
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
    """맨 위 브랜드 줄과, 마지막 장의 출처 한 줄."""
    lay = style.layout
    accent, muted = style.theme.marks(card.kind)
    _, fg = style.theme.colors(card.kind)
    poster_mod.draw_brand_bar(
        draw, style, page, fg, muted, accent, _font_at(style),
        lambda ratio: _px(style, ratio),
    )

    # 출처는 마지막 장에만. 매 장에 넣으면 그냥 지저분하다.
    if is_last and style.source:
        small = _font(style.regular, _px(style, lay.source))
        draw.text(
            (style.size.width / 2, style.size.height - _px(style, lay.margin) * 0.75),
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
            total=total,
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
    backdrop: str = backdrop_mod.DEFAULT_STYLE,
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
        backdrop=backdrop,
    )


__all__ = ["render_card", "render_deck", "build_style", "Style", "PillowMissing"]
