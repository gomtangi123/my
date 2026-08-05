"""텍스트 정규화 / 문장 묶기. 더듬음 검출과 자막 생성이 함께 쓴다."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import Word

SENTENCE_END = ".?!…。？！"
_PUNCT_RE = re.compile(r"[^\w가-힣]+", re.UNICODE)
_REPEAT_RE = re.compile(r"(.)\1{1,}")

# "그으", "어어~", "에에" 같은 늘임형 간투사.
# 뒤에 붙을 수 있는 글자를 [으어아~ㅡ]로 좁혀 둔 이유는 '아이', '아니'처럼
# 멀쩡한 단어가 필러로 오인되는 걸 막기 위해서다.
_ELONGATED_FILLER_RE = re.compile(r"^(?:음|흠|어|에|아|그|저|으)[으어아~ㅡ]*$")


def normalize_word(text: str) -> str:
    """비교용 정규화: 문장부호·공백 제거, 소문자화, 반복 문자 축약."""
    text = unicodedata.normalize("NFC", text).strip().lower()
    text = _PUNCT_RE.sub("", text)
    return _REPEAT_RE.sub(r"\1", text)


def normalize_text(text: str) -> str:
    """문장 비교용: 공백까지 전부 제거한 문자열."""
    return _PUNCT_RE.sub("", unicodedata.normalize("NFC", text).lower())


def is_filler(text: str, fillers: frozenset[str]) -> bool:
    norm = normalize_word(text)
    if not norm:
        return False
    if norm in fillers:
        return True
    # 사전에 없더라도 늘임형이고, 그 어간이 사전에 있으면 필러로 본다.
    if _ELONGATED_FILLER_RE.match(norm):
        return norm[0] in fillers or norm in fillers
    return False


def ends_sentence(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and stripped[-1] in SENTENCE_END


def similarity(a: str, b: str) -> float:
    """0.0~1.0. 한국어는 어절보다 글자 단위 비교가 잘 맞는다."""
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def group_sentences(
    words: list[Word], max_gap: float = 0.6, use_punctuation: bool = True
) -> list[list[Word]]:
    """단어들을 문장 단위로 묶는다. 문장부호 또는 긴 침묵에서 끊는다."""
    if not words:
        return []
    groups: list[list[Word]] = [[words[0]]]
    for prev, word in zip(words, words[1:]):
        gap = word.start - prev.end
        boundary = gap > max_gap or (use_punctuation and ends_sentence(prev.text))
        if boundary:
            groups.append([word])
        else:
            groups[-1].append(word)
    return groups


def join_words(words: list[Word]) -> str:
    """단어 목록을 사람이 읽을 문자열로. 한국어는 어절 사이에 공백을 넣는다."""
    return " ".join(w.text.strip() for w in words if w.text.strip()).strip()


__all__ = [
    "normalize_word",
    "normalize_text",
    "is_filler",
    "ends_sentence",
    "similarity",
    "group_sentences",
    "join_words",
    "SENTENCE_END",
]
