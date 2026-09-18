"""카드뉴스 자료구조."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Card:
    """카드 한 장. 제목만 있어도, 본문만 있어도 된다."""

    title: str = ""
    body: str = ""
    # "cover"(표지) / "body"(본문) / "stat"(숫자) / "outro"(마무리)
    kind: str = "body"
    index: int = 0
    # @사진 으로 직접 준 검색어. 비어 있으면 카드 글에서 뽑는다.
    image_query: str = ""
    # @사진없음 — 이 카드만 사진을 안 쓴다.
    image_off: bool = False
    # @막대 뒤에 준 단위 ("만원"). 값 뒤에 붙는다.
    unit: str = ""
    # @말머리 — 표지 제목 위에 강조색으로 붙는 한 줄.
    kicker: str = ""
    # @버튼 — 표지 아래 알약 버튼 문구. 표지는 안 주면 기본값이 붙는다.
    cta: str = ""
    # @배경 — 사진 대신 만들어 쓸 배경 (mesh/grid/rays/dots).
    backdrop: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.title.strip() and not self.body.strip()


@dataclass
class Deck:
    cards: list[Card] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.cards)

    def __iter__(self):
        return iter(self.cards)


@dataclass
class Size:
    """출력 규격. 인스타는 세로 4:5가 피드에서 가장 넓게 잡힌다."""

    width: int
    height: int


SIZES: dict[str, Size] = {
    # 피드 세로 — 같은 조회수에서 화면을 제일 많이 먹는다. 기본값.
    "post": Size(1080, 1350),
    "square": Size(1080, 1080),
    # 스토리 / 릴스 커버
    "story": Size(1080, 1920),
}


def resolve_size(name: str) -> Size:
    """이름(post/square/story) 또는 `1080x1350` 형식을 받는다."""
    key = name.strip().lower()
    if key in SIZES:
        return SIZES[key]
    if "x" in key:
        w, _, h = key.partition("x")
        try:
            size = Size(int(w), int(h))
        except ValueError:
            pass
        else:
            if size.width > 0 and size.height > 0:
                return size
    raise ValueError(
        f"모르는 규격입니다: {name} "
        f"(가능: {', '.join(SIZES)} 또는 1080x1350 형식)"
    )


__all__ = ["Card", "Deck", "Size", "SIZES", "resolve_size"]
