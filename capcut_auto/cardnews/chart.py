"""표 카드와 막대 카드.

스톡 사진은 누구나 쓴다. 내가 만든 표와 그래프는 나만 쓴다 — 경제 카드뉴스에서
이게 계정을 구분짓는 거의 유일한 시각 요소다.

형태를 고를 때 지킨 것:

- **값이 하나면 막대가 아니라 숫자 카드다**(`@숫자`). 막대 하나짜리 그래프는
  숫자를 크게 쓴 것만 못하다.
- **항목이 여러 개면 강조형**으로 그린다. 전부 색칠하면 정작 하고 싶은 말이
  묻힌다. 하나만 강조색, 나머지는 회색이다.
- **가로 막대**다. 한국어 항목명은 길어서 세로 막대의 가로축에 안 들어간다.
- **범례를 넣지 않는다.** 계열이 하나뿐이라 제목이 이미 무엇을 그린 건지
  말하고 있다. 칸 하나짜리 범례는 제목을 두 번 쓰는 것이다.
- **눈금선과 축을 그리지 않는다.** 값을 막대 끝에 직접 붙이므로 필요가 없다.
- **글씨는 데이터 색을 입지 않는다.** 막대만 색을 갖고, 라벨과 값은 글자색을
  쓴다. 강조한 줄은 진한 잉크, 나머지는 흐린 잉크 — 그래서 강조가 색깔
  하나에만 걸려 있지 않다.

정지 이미지라 툴팁도 표도 따로 없다. 그래서 값은 전부 막대 끝에 적는다
(대시보드였다면 선택적으로만 적었을 것이다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import colors

# 줄 끝의 `*` 는 "이 줄을 강조하라"는 뜻.
_EMPHASIS_RE = re.compile(r"\s*\*\s*$")
# 값에서 숫자만 남기기 위해 떼어낼 것들.
_NUMBER_RE = re.compile(r"-?[\d.]+")

# 막대 끝 둥글리기 (굵기 대비)
BAR_RADIUS = 0.30


@dataclass
class Bar:
    label: str
    value: float
    display: str
    emphasis: bool = False


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]
    emphasis: set[int]


def _split(line: str) -> tuple[list[str], bool]:
    """`가 | 나 | 다 *` → (["가","나","다"], True)."""
    emphasis = bool(_EMPHASIS_RE.search(line))
    if emphasis:
        line = _EMPHASIS_RE.sub("", line)
    return [cell.strip() for cell in line.split("|")], emphasis


def format_number(value: float) -> str:
    """천 단위 쉼표. 카드에서 "5000"과 "5,000"은 읽는 속도가 다르다."""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def parse_bars(body: str, unit: str = "") -> list[Bar]:
    """`라벨 | 숫자` 줄들을 막대로. 아무 줄도 `*` 가 없으면 마지막 줄을 강조한다.

    카드뉴스는 마지막에 하고 싶은 말이 오기 때문이다. 다른 줄을 강조하려면
    그 줄 끝에 `*` 를 붙이면 된다.
    """
    bars: list[Bar] = []
    for line in body.split("\n"):
        if not line.strip():
            continue
        cells, emphasis = _split(line)
        if len(cells) < 2:
            continue
        match = _NUMBER_RE.search(cells[1].replace(",", ""))
        if match is None:
            continue
        value = float(match.group())
        # 셋째 칸을 주면 그걸 그대로 쓴다 ("1억원" 처럼 직접 쓰고 싶을 때).
        display = cells[2].strip() if len(cells) > 2 else f"{format_number(value)}{unit}"
        bars.append(
            Bar(label=cells[0], value=value, display=display, emphasis=emphasis)
        )
    if bars and not any(b.emphasis for b in bars):
        bars[-1].emphasis = True
    return bars


def parse_table(body: str) -> Table:
    """첫 줄이 머리글, 나머지가 본문. 줄 끝 `*` 는 그 줄을 강조한다."""
    header: list[str] = []
    rows: list[list[str]] = []
    emphasis: set[int] = set()
    for line in body.split("\n"):
        if not line.strip():
            continue
        cells, marked = _split(line)
        if not header:
            header = cells
            continue
        if marked:
            emphasis.add(len(rows))
        rows.append(cells)
    return Table(header=header, rows=rows, emphasis=emphasis)


def _fit_font(font_at, text, max_width, largest, smallest, bold=False):
    """한 줄이 폭에 들어가는 가장 큰 글꼴. `font_at(size, bold)` 를 쓴다."""
    size = largest
    while size > smallest and font_at(size, bold).getlength(text) > max_width:
        size -= 2
    return font_at(size, bold)


def draw_bars(
    draw,
    bars: list[Bar],
    box: tuple[int, int, int, int],
    font_at,
    ink: str,
    muted: str,
    accent: str,
    grey: str,
    unit: int,
) -> None:
    """가로 막대를 그린다.

    `font_at(size, bold)` 는 그 크기의 글꼴을, `unit` 은 카드의 짧은 변을 받는다.
    굵기와 글씨를 자기 칸(band)에만 비례시키면 줄이 두 개일 때 막대가 손바닥만
    해진다 — 두꺼운 채색 블록은 카드가 유치해 보이는 가장 빠른 길이다.
    그래서 칸 비례와 카드 비례 중 **작은 쪽**을 쓴다.
    """
    left, top, width, height = box
    if not bars:
        return

    band = height / len(bars)
    thickness = max(6, int(min(band * 0.30, unit * 0.045)))
    label_size = max(10, int(min(band * 0.24, unit * 0.038)))
    radius = max(2, int(thickness * BAR_RADIUS))
    pad = max(8, int(thickness * 0.45))
    biggest = max((b.value for b in bars), default=0.0) or 1.0

    label_gap = int(label_size * 0.45)
    row_h = label_size * 1.2 + label_gap + thickness
    spacing = max(thickness * 0.9, unit * 0.022)
    # 줄이 적어도 칸을 늘려 채우지 않는다 — 굵기는 위에서 이미 정해졌고,
    # 남는 자리는 본문 카드와 마찬가지로 아래쪽 여백으로 둔다. 제목 바로
    # 밑에서 시작해야 장을 넘길 때 시작 위치가 흔들리지 않는다.
    y = float(top)

    label_font = font_at(label_size, False)
    for bar in bars:
        row_ink = ink if bar.emphasis else muted
        draw.text((left, y), bar.label, font=label_font, fill=row_ink, anchor="la")

        bar_top = y + label_size * 1.2 + label_gap
        # 숫자는 굵게. 카드에서 실제로 읽히는 건 이 값이다.
        value_font = _fit_font(
            font_at, bar.display, width * 0.42, int(thickness * 0.95), 12, bold=True
        )
        value_w = value_font.getlength(bar.display)
        plot_w = max(1.0, width - value_w - pad * 2)
        # 굵기를 최소 길이로 쓰면 작은 값이 부풀어 길이 비례가 깨진다.
        bar_w = max(float(radius * 2), plot_w * (bar.value / biggest))

        fill = accent if bar.emphasis else grey
        _rounded_end(draw, left, bar_top, bar_w, thickness, radius, fill)

        # 막대 끝 바깥에 값을 적는다. 자리가 없으면 막대 안쪽 끝에 적는다.
        if bar_w + pad + value_w <= width:
            draw.text(
                (left + bar_w + pad, bar_top + thickness / 2),
                bar.display,
                font=value_font,
                fill=row_ink,
                anchor="lm",
            )
        else:
            # 채움색 위에 얹히므로 밝기를 보고 흰 글씨/검은 글씨를 고른다.
            on_fill = "#FFFFFF" if colors.luminance(fill) < 0.4 else "#111111"
            draw.text(
                (left + bar_w - pad, bar_top + thickness / 2),
                bar.display,
                font=value_font,
                fill=on_fill,
                anchor="rm",
            )
        y += row_h + spacing


def _rounded_end(draw, x: float, y: float, w: float, h: float, r: int, fill: str) -> None:
    """값이 끝나는 쪽만 둥글고, 시작하는 쪽은 각진 막대."""
    right = x + w
    if w <= r * 2:
        draw.rectangle([x, y, right, y + h], fill=fill)
        return
    draw.rounded_rectangle(
        [x, y, right, y + h], radius=r, fill=fill, corners=(False, True, True, False)
    )


def draw_table(
    draw,
    table: Table,
    box: tuple[int, int, int, int],
    font_at,
    ink: str,
    muted: str,
    accent: str,
    rule: str,
) -> None:
    left, top, width, height = box
    if not table.rows:
        return

    lines = len(table.rows) + (1 if table.header else 0)
    row_h = height / lines
    cell_size = max(14, int(row_h * 0.40))
    columns = max(len(table.header), max(len(r) for r in table.rows))
    # 첫 칸은 항목 이름이라 길다. 나머지를 고르게 나눈다.
    first_w = width * (0.46 if columns > 1 else 1.0)
    other_w = (width - first_w) / max(1, columns - 1) if columns > 1 else 0.0
    xs = [left] + [left + first_w + other_w * i for i in range(columns - 1)]

    y = top
    if table.header:
        _row(draw, table.header, xs, y, row_h, font_at, cell_size, muted, width, first_w, other_w)
        y += row_h
        draw.rectangle([left, y - 1, left + width, y], fill=rule)

    for index, row in enumerate(table.rows):
        marked = index in table.emphasis
        if marked:
            # 강조는 왼쪽 막대 + 진한 잉크. 색 하나에만 기대지 않는다.
            draw.rectangle(
                [left - max(6, cell_size // 3), y + row_h * 0.18,
                 left - max(2, cell_size // 8), y + row_h * 0.82],
                fill=accent,
            )
        _row(
            draw, row, xs, y, row_h, font_at, cell_size,
            ink if marked else muted, width, first_w, other_w, bold=marked,
        )
        y += row_h
        if index < len(table.rows) - 1:
            draw.rectangle([left, y - 1, left + width, y], fill=rule)


def _row(draw, cells, xs, y, row_h, font_at, size, fill, width, first_w, other_w, bold=False) -> None:
    for i, cell in enumerate(cells[: len(xs)]):
        limit = (first_w if i == 0 else other_w) * 0.92
        font = _fit_font(font_at, cell, limit, size, 12, bold=bold)
        draw.text((xs[i], y + row_h / 2), cell, font=font, fill=fill, anchor="lm")


__all__ = [
    "Bar",
    "format_number",
    "Table",
    "parse_bars",
    "parse_table",
    "draw_bars",
    "draw_table",
]
