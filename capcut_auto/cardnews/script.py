"""카드뉴스 대본 파싱.

입력은 메모장에서 바로 쓸 수 있는 평문이다. 카드 사이는 `---` 한 줄로 나누고,
`#`으로 시작하는 첫 줄은 그 카드의 제목이 된다.

    # 월 30만원 아끼는 법
    아무도 안 알려주는 것

    ---

    ## 1. 통신비
    알뜰폰으로 바꾸면 끝이다.

첫 카드는 표지(cover)로 본다 — 인스타에서 넘길지 말지는 사실상 이 한 장이
결정하므로 렌더러가 따로 크게 잡는다. `@표지` / `@마무리` 지시어로 직접
지정할 수도 있다.
"""

from __future__ import annotations

import re

from .models import Card, Deck

# 구분선: `-`, `=`, `*` 를 3개 이상 늘어놓은 줄. 마크다운을 쓰던 습관 그대로.
_SEPARATOR_RE = re.compile(r"^\s*([-=*])\1{2,}\s*$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s*(.*)$")
# 지시어는 블록 맨 위에 여러 줄 올 수 있다: `@숫자` 다음 줄에 `@사진 piggy bank`.
_DIRECTIVE_RE = re.compile(r"^\s*@([^\s]+)(?:\s+(.*))?\s*$")

# 지시어 → 카드 종류. 한글/영문을 모두 받는다.
_KINDS = {
    "표지": "cover",
    "cover": "cover",
    "마무리": "outro",
    "outro": "outro",
    "숫자": "stat",
    "stat": "stat",
    "막대": "bars",
    "bars": "bars",
    "표": "table",
    "table": "table",
}

# `@사진 <검색어>` — 검색어를 비우면 카드 글에서 알아서 뽑는다.
_IMAGE = frozenset({"사진", "photo", "image"})
_NO_IMAGE = frozenset({"사진없음", "nophoto", "noimage"})


def split_blocks(text: str) -> list[list[str]]:
    """구분선을 기준으로 줄 묶음을 나눈다. 빈 묶음은 버린다."""
    blocks: list[list[str]] = [[]]
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _SEPARATOR_RE.match(line):
            blocks.append([])
        else:
            blocks[-1].append(line)
    return [b for b in (_trim(block) for block in blocks) if b]


def _trim(lines: list[str]) -> list[str]:
    """앞뒤 빈 줄을 걷어낸다. 가운데 빈 줄은 문단 구분이라 남긴다."""
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return [line.rstrip() for line in lines[start:end]]


def parse_block(lines: list[str], index: int) -> Card:
    kind, image_query, image_off, unit = "", "", False, ""
    while lines and (m := _DIRECTIVE_RE.match(lines[0])):
        name, argument = m.group(1), (m.group(2) or "").strip()
        if name in _NO_IMAGE:
            image_off = True
        elif name in _IMAGE:
            image_query = argument
        elif name in _KINDS:
            kind = _KINDS[name]
            unit = argument  # `@막대 만원` 처럼 단위를 함께 줄 수 있다
        else:
            break  # 모르는 지시어는 본문으로 취급한다 — 조용히 삼키면 곤란하다
        lines = _trim(lines[1:])

    title, body_lines = "", lines
    if lines and (m := _HEADING_RE.match(lines[0])):
        title, body_lines = m.group(1).strip(), _trim(lines[1:])
    elif kind == "stat" and lines:
        # 숫자 카드는 첫 줄이 곧 수치다. `#` 없이 써도 크게 박혀야 한다.
        title, body_lines = lines[0].strip(), _trim(lines[1:])
    elif len(lines) == 1:
        # 한 줄짜리 카드는 문단이 아니라 한마디다. 크게 박아야 읽힌다.
        title, body_lines = lines[0].strip(), []

    if not kind:
        kind = "cover" if index == 0 else "body"
    return Card(
        title=title,
        body="\n".join(body_lines),
        kind=kind,
        index=index,
        image_query=image_query,
        image_off=image_off,
        unit=unit,
    )


def parse(text: str) -> Deck:
    """대본 전문을 카드 묶음으로. 내용이 하나도 없으면 ValueError."""
    blocks = split_blocks(text)
    if not blocks:
        raise ValueError("대본이 비어 있습니다.")
    return Deck(cards=[parse_block(block, i) for i, block in enumerate(blocks)])


__all__ = ["parse", "parse_block", "split_blocks"]
