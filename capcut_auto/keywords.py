"""한국어 키워드 추출 + 스톡 검색어 변환.

konlpy 같은 형태소 분석기 없이 돌아가야 해서(설치 장벽이 크다)
조사 제거 + 불용어 + 사전 매칭으로 처리한다. 완벽하진 않지만
"이 문장에 어떤 자료화면을 붙일까"를 정하는 데는 충분하다.

konlpy가 설치돼 있으면 명사 추출에 그걸 쓴다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .models import Word
from .stockwords import KEYWORD_MAP, STOPWORDS

# 긴 조사부터 떼어내야 한다 ("에서는"을 "는"으로 떼면 "에서"가 남는다).
_PARTICLES_LONG = (
    "에서는", "에게서", "으로는", "이라고", "라고는", "께서는", "에서도", "으로도",
    "까지도", "부터는", "에게는", "한테는", "이라는", "이라도", "이나마",
    "에서", "으로", "에게", "한테", "께서", "부터", "까지", "만큼", "처럼",
    "보다", "하고", "이랑", "라고", "이나", "라는", "조차", "마저", "든지",
    "이란", "이든", "밖에", "대로", "이야", "예요", "이며", "이고",
)
_PARTICLES_SHORT = ("은", "는", "이", "가", "을", "를", "에", "의", "와", "과",
                    "도", "만", "로", "랑", "야", "께", "든")

_TOKEN_RE = re.compile(r"[가-힣]+|[A-Za-z][A-Za-z'\-]*|\d+(?:[.,]\d+)*")
_HANGUL_RE = re.compile(r"^[가-힣]+$")

# 용언(동사·형용사) 활용형은 자료화면 검색어로 쓸모가 없다. "갔어요"로
# 스톡 사이트를 검색할 일은 없으므로 걸러낸다. 명사가 잘못 걸리지 않도록
# 두 글자 이상인 어미만 쓴다(한 글자 '자'를 넣으면 감자·의자가 날아간다).
_VERB_ENDING_RE = re.compile(
    r"(?:어요|아요|여요|예요|에요|세요|네요|셔요|어라|아라|았어|었어|겠어|"
    r"습니다|ㅂ니다|입니다|는데|지만|면서|니까|는다|았다|었다|한다|하다|되다|"
    r"거든|잖아|더라|더군|구나|군요|해서|해도|하고|하면|되면|이라|라고)$"
)


@dataclass(frozen=True)
class Keyword:
    """추출된 키워드 하나."""

    text: str  # 조사를 뗀 한국어 형태
    query: str  # 스톡 사이트에 던질 검색어
    score: float
    start: float
    end: float


def strip_particle(token: str) -> str:
    """조사를 뗀다. 확실하지 않으면 건드리지 않는다."""
    if not _HANGUL_RE.match(token):
        return token

    # 사전에 있는 단어가 앞에 붙어 있으면 그게 정답이다. 조사 규칙보다 우선.
    for length in range(len(token), 1, -1):
        if token[:length] in KEYWORD_MAP:
            return token[:length]

    for particle in _PARTICLES_LONG:
        if token.endswith(particle) and len(token) - len(particle) >= 2:
            return token[: -len(particle)]

    for particle in _PARTICLES_SHORT:
        if not token.endswith(particle):
            continue
        # '이'로 끝나는 명사가 워낙 많아서(고양이, 어린이, 종이…) 더 보수적으로.
        minimum = 4 if particle == "이" else 3
        if len(token) >= minimum:
            return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _konlpy_nouns(text: str) -> list[str] | None:
    try:
        from konlpy.tag import Okt  # type: ignore
    except Exception:
        return None
    global _OKT
    try:
        _OKT
    except NameError:
        try:
            _OKT = Okt()
        except Exception:  # JVM 없음 등
            return None
    try:
        return [n for n in _OKT.nouns(text) if len(n) >= 2]
    except Exception:
        return None


def extract(text: str, use_konlpy: bool = True) -> list[str]:
    """문장에서 의미 있는 단어들을 뽑는다 (등장 순서 유지, 중복 제거)."""
    nouns = _konlpy_nouns(text) if use_konlpy else None
    if nouns is None:
        # 조사를 떼기 *전에* 활용형을 걸러야 한다. "그랬거든"에서 '든'을 먼저
        # 떼면 "그랬거"가 남아 어미 판정을 빠져나간다.
        nouns = [
            strip_particle(token)
            for token in tokenize(text)
            if token in KEYWORD_MAP or not _VERB_ENDING_RE.search(token.lower())
        ]

    seen: set[str] = set()
    out: list[str] = []
    for word in nouns:
        norm = word.strip().lower()
        if len(norm) < 2 or norm in STOPWORDS or norm in seen:
            continue
        if norm.isdigit():
            continue
        # 사전에 있는 단어는 활용형 필터를 건너뛴다 ("하다"로 끝나는 명사 보호).
        if norm not in KEYWORD_MAP and _VERB_ENDING_RE.search(norm):
            continue
        seen.add(norm)
        out.append(word.strip())
    return out


def to_query(word: str) -> str:
    """스톡 사이트용 검색어. 사전에 있으면 영어로 바꾼다."""
    mapped = KEYWORD_MAP.get(word) or KEYWORD_MAP.get(word.lower())
    return mapped or word


def rank(
    words: list[Word],
    idf: Counter | None = None,
    use_konlpy: bool = True,
) -> list[Keyword]:
    """단어 목록(타임스탬프 포함)에서 키워드를 뽑고 점수를 매긴다.

    점수는 '이 구간을 대표하는 정도'다.
    - 흔한 단어일수록 낮게 (idf)
    - 길수록 조금 높게 (구체적인 명사일 확률)
    - 사전에 영어 매핑이 있으면 가산점 (스톡 검색이 잘 될 단어)
    """
    results: list[Keyword] = []
    for w in words:
        for token in extract(w.text, use_konlpy=use_konlpy):
            norm = token.lower()
            frequency = idf.get(norm, 1) if idf else 1
            score = 1.0 / (1.0 + 0.35 * (frequency - 1))
            score *= min(1.4, 0.7 + 0.2 * len(token))
            if norm in KEYWORD_MAP or token in KEYWORD_MAP:
                score *= 1.5
            results.append(
                Keyword(
                    text=token,
                    query=to_query(token),
                    score=score,
                    start=w.start,
                    end=w.end,
                )
            )
    return results


def document_frequency(words: list[Word], use_konlpy: bool = True) -> Counter:
    """영상 전체에서 각 단어가 몇 번 나왔는지."""
    counter: Counter = Counter()
    for w in words:
        for token in extract(w.text, use_konlpy=use_konlpy):
            counter[token.lower()] += 1
    return counter



__all__ = [
    "Keyword",
    "extract",
    "tokenize",
    "strip_particle",
    "to_query",
    "rank",
    "document_frequency",
]
