"""표지 카드의 포스터 배치.

인스타에서 스크롤을 멈추게 하는 건 표지 한 장이고, 그 한 장은 이렇게 생겼다.

    ┌──────────────────────────┐
    │ ▣ MY ACCOUNT        1/7  │  ← 브랜드 바 (위)
    │                          │
    │          사진             │  ← 위쪽은 장막을 안 씌운다
    │                          │
    │  말머리                   │  ← 여기부터 아래로 정렬
    │  제목 첫 줄               │
    │  제목 둘째 줄 (강조색)     │
    │  부제                     │
    │  ( 🔖 저장 )              │
    │        ● ○ ○ ○ ○         │
    └──────────────────────────┘

글을 아래에 모으는 이유는 두 가지다. 사진의 주인공은 보통 가운데나 위에
있어서 아래가 비고, 장막도 아래만 씌우면 되니 사진이 덜 탁해진다.

가운데 정렬 대신 왼쪽 정렬인 것은 제목이 두 줄 이상일 때 읽기 시작점이
흔들리지 않기 때문이다.
"""

from __future__ import annotations

from . import colors, layout as layout_mod

# 제목 안의 `|` 는 줄바꿈이고, 뒷줄은 강조색으로 그린다.
TITLE_SPLIT = "|"


def split_title(title: str) -> list[str]:
    """`앞 | 뒤` → ["앞", "뒤"]. 구분자가 없으면 한 덩어리."""
    parts = [p.strip() for p in title.split(TITLE_SPLIT)]
    return [p for p in parts if p] or [title.strip()]


def letterspaced(draw, text: str, xy, font, fill, spacing: float) -> float:
    """자간을 벌려 그린다. Pillow에는 자간 옵션이 없다. 그린 폭을 돌려준다."""
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill, anchor="ls")
        x += font.getlength(char) + spacing
    return x - xy[0] - spacing


def spaced_width(text: str, font, spacing: float) -> float:
    if not text:
        return 0.0
    return sum(font.getlength(c) for c in text) + spacing * (len(text) - 1)


def draw_brand_bar(
    draw, style, page: str, ink: str, muted: str, accent: str, font_at, px
) -> float:
    """맨 위 줄: 표시 색 네모 + 계정명(대문자·자간) + 쪽 번호.

    아래쪽 꼬리말 대신 위로 올렸다. 인스타는 화면 아래를 자기 UI로 덮는
    경우가 있어서, 정체를 밝히는 자리로는 위가 안전하다.
    """
    lay = style.layout
    margin = px(lay.margin)
    size = px(lay.brand)
    font = font_at(size, True)
    y = margin * 0.72 + size

    x = float(margin)
    if style.handle:
        # 계정 표시 네모. 로고 대신 쓰는 최소한의 표식이다.
        box = size * 0.95
        top = y - box
        draw.rounded_rectangle(
            [x, top, x + box, top + box], radius=box * 0.26, fill=accent
        )
        x += box + size * 0.45
        letterspaced(
            draw,
            style.handle.lstrip("@").upper(),
            (x, y),
            font,
            ink,
            size * 0.14,
        )

    if page:
        draw.text(
            (style.size.width - margin, y), page, font=font, fill=muted, anchor="rs"
        )
    return y + size * 0.9  # 아래 내용이 여기부터 시작하면 된다


def dots_height(style, total: int, px) -> float:
    """점들이 먹는 높이. 0이면 안 그린다."""
    if total < 2 or total > 10:
        return 0.0
    return max(2.0, px(style.layout.dots) / 2) * 2 + px(style.layout.margin) * 0.55


def draw_dots(draw, style, index: int, total: int, ink: str, muted: str, px) -> float:
    """캐러셀 점. 너무 많으면 뭉개지므로 그때는 그리지 않는다."""
    lay = style.layout
    if total < 2 or total > 10:
        return 0.0
    radius = max(2.0, px(lay.dots) / 2)
    gap = radius * 3.2
    span = gap * (total - 1)
    cx = style.size.width / 2 - span / 2
    cy = style.size.height - px(lay.margin) * 0.85
    for i in range(total):
        x = cx + gap * i
        draw.ellipse(
            [x - radius, cy - radius, x + radius, cy + radius],
            fill=ink if i == index else muted,
        )
    return dots_height(style, total, px)


def pill_height(text: str, style, px) -> float:
    """알약 버튼이 먹는 높이. 0이면 안 그린다."""
    if not text:
        return 0.0
    size = px(style.layout.pill)
    return size + size * 0.62 * 2


def draw_pill(draw, text: str, style, bottom: float, fill: str, ink: str, font_at, px):
    """저장을 유도하는 알약 버튼. 돌려주는 값은 버튼이 차지한 높이."""
    lay = style.layout
    if not text:
        return 0.0
    margin = px(lay.margin)
    size = px(lay.pill)
    font = font_at(size, True)
    text_w = font.getlength(text)
    pad_x, pad_y = size * 0.95, size * 0.62
    height = size + pad_y * 2
    top = bottom - height
    draw.rounded_rectangle(
        [margin, top, margin + text_w + pad_x * 2, bottom],
        radius=height / 2,
        fill=fill,
    )
    draw.text(
        (margin + pad_x, top + height / 2), text, font=font, fill=ink, anchor="lm"
    )
    return height


def fit_lines(text: str, metrics, max_width: float, max_height: float, sizes):
    """layout.fit 을 그대로 쓴다 — 표지라고 다른 규칙을 쓸 이유가 없다."""
    return layout_mod.fit(text, metrics, max_width, max_height, sizes)


def draw_block_bottom(draw, fitted, font, x: float, bottom: float, fill) -> float:
    """줄 묶음을 아래쪽 기준으로 그린다. 돌려주는 값은 묶음의 맨 윗 y."""
    top = bottom - fitted.height
    for row, line in enumerate(fitted.lines):
        if line:
            draw.text(
                (x, top + row * fitted.line_height),
                line,
                font=font,
                fill=fill if not isinstance(fill, list) else fill[min(row, len(fill) - 1)],
                anchor="la",
            )
    return top


def veil_for(fg: str, bg: str) -> str:
    """장막 색. 표지 배경색을 그대로 쓰되, 글자와 같은 쪽이면 반대로 뒤집는다."""
    return bg if colors.contrast(fg, bg) >= 4.5 else ("#000000" if colors.luminance(fg) > 0.5 else "#FFFFFF")


__all__ = [
    "split_title",
    "letterspaced",
    "spaced_width",
    "draw_brand_bar",
    "draw_dots",
    "dots_height",
    "pill_height",
    "draw_pill",
    "fit_lines",
    "draw_block_bottom",
    "veil_for",
    "TITLE_SPLIT",
]
