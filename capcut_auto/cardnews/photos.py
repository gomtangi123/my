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
# 사진의 색만 남기고 형태를 지운 그라데이션. 표·그래프 뒤에 쓴다.
WASH = "wash"
NONE = "none"

# 모든 카드에 사진을 깐다. 글이 읽히는 건 장막이 책임진다 —
# 카드마다 사진 픽셀을 재서 필요한 만큼만 덮는다.
DEFAULT_MODES: dict[str, str] = {
    "cover": FULL,
    "body": FULL,
    "stat": FULL,
    "outro": FULL,
    # 표와 그래프 뒤에 사진을 그대로 깔면 가는 선과 작은 글씨가 묻힌다.
    # 사진의 색만 남긴 그라데이션을 쓰면 덱의 흐름은 잇고 글씨는 산다.
    "bars": WASH,
    "table": WASH,
}

# 카드 종류별 장막 목표 대비. 표·그래프는 마크가 가늘어 더 높게 잡는다.
SCRIM_MINIMUM: dict[str, float] = {
    "bars": 7.0,
    "table": 7.0,
}
DEFAULT_SCRIM_MINIMUM = 4.5


def scrim_minimum(kind: str) -> float:
    return SCRIM_MINIMUM.get(kind, DEFAULT_SCRIM_MINIMUM)

# 검색어에 쓸 키워드 개수. 너무 많이 넣으면 스톡 검색이 0건이 된다.
QUERY_WORDS = 2
# 제공자당 후보 개수. 앞쪽이 이미 쓰인 사진이면 다음 걸 쓴다.
CANDIDATES = 8


def mode_for(card: Card, override: str = "auto") -> str:
    """이 카드에 사진을 어떻게 깔지."""
    if card.image_off or override == "off":
        return NONE
    if override in (FULL, BAND, WASH):
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
    broken: dict[str, str] | None = None,
) -> Asset | None:
    """제공자들을 차례로 뒤져 아직 안 쓴 사진 하나를 내려받는다.

    제공자가 죽으면 나머지로 계속하되, 무슨 일이 있었는지는 `broken` 에
    적어 둔다. 망이 막혔는데 "결과 없음"만 뜨면 원인을 알 수가 없다.
    """
    for provider in providers:
        if not provider.supports("image"):
            continue
        try:
            candidates = provider.search(query, "image", limit=CANDIDATES)
        except ProviderError as exc:
            if broken is not None:
                broken.setdefault(provider.name, str(exc))
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
    broken: dict[str, str] = {}
    for card in deck:
        if mode_for(card, override) == NONE:
            continue
        query = query_for(card, use_konlpy)
        if not query:
            say(f"  {card.index + 1:02d}  검색어를 못 뽑아 글만 씁니다")
            missed += 1
            continue
        asset = _search_one(providers, query, cache_dir, used, broken)
        if asset is None:
            say(f"  {card.index + 1:02d}  '{query}' 결과 없음 — 글만 씁니다")
            missed += 1
            continue
        found[card.index] = asset
        say(f"  {card.index + 1:02d}  '{query}' → {asset.source}")

    for name, reason in broken.items():
        say(f"  ! {name} 제공자에 접속하지 못했습니다 — {reason}")

    if missed:
        # 사진을 못 찾으면 만들어 쓰는 배경으로 떨어진다. 그걸 사진인 줄
        # 알면 곤란하니 분명히 말해 준다.
        say(
            f"  ({missed}장은 사진 대신 만들어 쓰는 배경으로 나갑니다.\n"
            "   대본에 `@사진 <영어 검색어>` 를 넣으면 직접 지정할 수 있습니다)"
        )
    return found


# 카드에 박을 때 쓰는 이름.
_SOURCE_NAMES = {
    "commons": "위키미디어 커먼즈",
    "pexels": "Pexels",
    "pixabay": "Pixabay",
    "local": "직접 촬영",
}


def credits(found: dict[int, Asset]) -> str:
    """사진 출처 한 줄. 카드 맨 아래 `--source` 에 들어간다.

    한 줄에는 이름만 싣는다. 저작자까지 넣으면 다섯 명이 넘어가 안 들어간다.
    CC BY 가 요구하는 저작자 표시는 `attribution_file` 이 따로 뽑아 준다.
    """
    names = sorted({_SOURCE_NAMES.get(a.source, a.source) for a in found.values()})
    return f"사진: {' · '.join(names)}" if names else ""


def attribution(found: dict[int, Asset]) -> str:
    """저작자·라이선스·원본 주소를 모은 글. 캡션에 붙여 넣을 용도.

    CC BY / CC BY-SA 는 **표시가 의무**다. 자유 라이선스라고 그냥 쓰면
    라이선스 위반이 된다. 그래서 카드와 같이 파일로 떨군다.
    """
    if not found:
        return ""
    lines = ["사진 출처", ""]
    seen: set[str] = set()
    for index in sorted(found):
        asset = found[index]
        key = f"{asset.source}:{asset.source_id}"
        if key in seen:
            continue
        seen.add(key)
        where = f" — {asset.page_url}" if asset.page_url else ""
        lines.append(f"- {index + 1:02d}번 카드: {asset.credit or asset.source}{where}")
    return "\n".join(lines) + "\n"


__all__ = [
    "FULL",
    "BAND",
    "WASH",
    "NONE",
    "DEFAULT_MODES",
    "scrim_minimum",
    "mode_for",
    "query_for",
    "collect",
    "credits",
    "attribution",
]
