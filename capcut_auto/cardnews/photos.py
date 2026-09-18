"""카드에 깔 사진 찾아오기.

새로 만들 게 없다. 이 저장소에는 이미 자료화면 파이프라인이 있다 —
한국어 키워드 추출(`keywords`), 영어 검색어 변환(`to_query`), 제공자
(Pexels·Pixabay·내 폴더), 내려받기 캐시(`assets.cache`). 그대로 쓴다.

어떤 카드에 사진을 깔지는 종류가 정한다. 표지는 스크롤을 멈춰야 하니 꽉
채우고, 본문은 글이 주인이라 위쪽 띠로만 넣는다. 숫자 카드는 수치 자체가
그림이라 사진을 깔면 오히려 지저분해진다.
"""

from __future__ import annotations

from pathlib import Path

from .. import keywords
from ..assets import cache as asset_cache
from ..assets.models import Asset
from ..assets.providers import Provider, ProviderError
from .models import Card, Deck

# 사진을 어떻게 깔지. render가 이 이름을 보고 그린다.
FULL = "full"
BAND = "band"
NONE = "none"

DEFAULT_MODES: dict[str, str] = {
    "cover": FULL,
    "body": BAND,
    "stat": NONE,
    "outro": NONE,
    # 표·그래프 위에 사진을 깔면 둘 다 안 읽힌다.
    "bars": NONE,
    "table": NONE,
}

# 검색어에 쓸 키워드 개수. 너무 많이 넣으면 스톡 검색이 0건이 된다.
QUERY_WORDS = 2
# 제공자당 후보 개수. 앞쪽이 이미 쓰인 사진이면 다음 걸 쓴다.
CANDIDATES = 8


def mode_for(card: Card, override: str = "auto") -> str:
    """이 카드에 사진을 어떻게 깔지."""
    if card.image_off or override == "off":
        return NONE
    if override in (FULL, BAND):
        return override
    return DEFAULT_MODES.get(card.kind, BAND)


def _dedupe(tokens: list[str]) -> list[str]:
    """순서를 지키며 같은 낱말을 접는다 ("bank vault safe bank" → 뒤의 bank를 뺀다)."""
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        key = token.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(token)
    return out


def query_for(card: Card, use_konlpy: bool = True) -> str:
    """카드 글에서 스톡 검색어를 만든다. `@사진`으로 준 게 있으면 그걸 쓴다.

    사전에 있는 말이 하나라도 있으면 **그것만** 쓴다. 영어에 한국어를 섞으면
    스톡 검색 결과가 영어만 넣었을 때보다 오히려 나빠지기 때문이다.
    """
    if card.image_query:
        return card.image_query

    words = keywords.extract(f"{card.title}\n{card.body}", use_konlpy=use_konlpy)
    pairs = [(w, keywords.to_query(w)) for w in words]
    translated = [q for w, q in pairs if q != w]
    pool = translated or [q for _, q in pairs]
    return " ".join(_dedupe(" ".join(pool[:QUERY_WORDS]).split()))


def _search_one(
    providers: list[Provider],
    query: str,
    cache_dir: Path,
    used: set[str],
) -> Asset | None:
    """제공자들을 차례로 뒤져 아직 안 쓴 사진 하나를 내려받는다."""
    for provider in providers:
        if not provider.supports("image"):
            continue
        try:
            candidates = provider.search(query, "image", limit=CANDIDATES)
        except ProviderError:
            continue  # 한 제공자가 죽어도 나머지로 계속한다
        for ref in candidates:
            key = f"{ref.source}:{ref.source_id}"
            if key in used:
                continue
            try:
                asset = asset_cache.fetch(ref, cache_dir, query)
            except ProviderError:
                continue
            used.add(key)
            return asset
    return None


def collect(
    deck: Deck,
    providers: list[Provider],
    cache_dir: str | Path,
    override: str = "auto",
    use_konlpy: bool = True,
    progress=None,
) -> dict[int, Asset]:
    """카드 번호 → 사진. 못 찾은 카드는 그냥 빠진다 (글만 나온다)."""
    say = progress or (lambda _m: None)
    if not providers:
        return {}

    cache_dir = Path(cache_dir)
    used: set[str] = set()
    found: dict[int, Asset] = {}

    missed = 0
    for card in deck:
        if mode_for(card, override) == NONE:
            continue
        query = query_for(card, use_konlpy)
        if not query:
            say(f"  {card.index + 1:02d}  검색어를 못 뽑아 글만 씁니다")
            missed += 1
            continue
        asset = _search_one(providers, query, cache_dir, used)
        if asset is None:
            say(f"  {card.index + 1:02d}  '{query}' 결과 없음 — 글만 씁니다")
            missed += 1
            continue
        found[card.index] = asset
        say(f"  {card.index + 1:02d}  '{query}' → {asset.source}")

    if missed:
        # 카드 글에서 뽑은 검색어가 늘 좋을 수는 없다. 손으로 주는 길을 알려 준다.
        say(
            f"  ({missed}장은 사진 없이 나갑니다 — 대본에 `@사진 <검색어>` 를 "
            "넣으면 직접 지정할 수 있습니다)"
        )
    return found


def credits(found: dict[int, Asset]) -> str:
    """사진 출처 한 줄. 카드 맨 아래 `--source` 에 덧붙일 용도."""
    sources = sorted({asset.source for asset in found.values()})
    return f"사진: {' · '.join(sources)}" if sources else ""


__all__ = [
    "FULL",
    "BAND",
    "NONE",
    "DEFAULT_MODES",
    "mode_for",
    "query_for",
    "collect",
    "credits",
]
