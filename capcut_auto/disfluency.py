"""'버벅거리는 구간' 검출.

세 가지를 잡는다.

1. 필러(간투사)  : "음", "어", "그", "이제" 같이 의미 없이 끼는 말
2. 더듬음        : 같은 말을 바로 다시 하거나("그 그 그"),
                   말을 끊고 다시 시작하는 경우("그러니 그러니까")
3. 재촬영(retake): 같은 문장을 통째로 다시 말한 경우 -> 앞의 것을 버림

전부 단어 단위 타임스탬프 위에서 돈다. 결과는 잘라낼 구간 목록.
"""

from __future__ import annotations

from .config import DisfluencyConfig
from .models import Cut, Span, Word
from . import text as textutil


def detect(
    words: list[Word], cfg: DisfluencyConfig, fillers: frozenset[str], total: float
) -> list[Cut]:
    if not cfg.enabled or not words:
        return []

    cuts: list[Cut] = []
    protected: set[int] = set()  # 재촬영으로 이미 통째로 잘린 단어 인덱스

    if cfg.remove_retakes:
        retake_cuts, retake_indices = _detect_retakes(words, cfg)
        cuts.extend(retake_cuts)
        protected |= retake_indices

    if cfg.remove_stutters:
        stutter_cuts, stutter_indices = _detect_stutters(words, cfg, fillers, protected)
        cuts.extend(stutter_cuts)
        protected |= stutter_indices

    if cfg.remove_fillers:
        cuts.extend(_detect_fillers(words, cfg, fillers, protected))

    # 패딩을 붙이고 영상 밖으로 넘어가지 않게 자른다.
    padded = []
    for cut in cuts:
        span = cut.span.padded(cfg.pad, cfg.pad).clamp(0.0, total)
        if span.duration > 0:
            padded.append(Cut(span, cut.reason, cut.detail))
    return sorted(padded, key=lambda c: (c.span.start, c.span.end))


def _detect_fillers(
    words: list[Word],
    cfg: DisfluencyConfig,
    fillers: frozenset[str],
    protected: set[int],
) -> list[Cut]:
    cuts: list[Cut] = []
    for i, word in enumerate(words):
        if i in protected:
            continue
        if not textutil.is_filler(word.text, fillers):
            continue
        duration = word.end - word.start
        if duration > cfg.max_filler_duration:
            continue
        if cfg.require_isolation and not _is_isolated(words, i, cfg.isolation_gap):
            continue
        cuts.append(Cut(Span(word.start, word.end), "filler", word.text.strip()))
    return cuts


def _is_isolated(words: list[Word], i: int, gap: float) -> bool:
    before = words[i].start - words[i - 1].end if i > 0 else float("inf")
    after = words[i + 1].start - words[i].end if i + 1 < len(words) else float("inf")
    return before >= gap or after >= gap


def _detect_stutters(
    words: list[Word],
    cfg: DisfluencyConfig,
    fillers: frozenset[str],
    protected: set[int],
) -> tuple[list[Cut], set[int]]:
    """같은 말 반복 / 말 끊고 다시 시작 -> 마지막 것만 남긴다."""
    cuts: list[Cut] = []
    removed: set[int] = set()

    i = 0
    while i < len(words) - 1:
        if i in protected:
            i += 1
            continue
        # i부터 시작해서 '같은 말'이 이어지는 만큼 묶는다.
        run_end = i
        while run_end + 1 < len(words):
            a, b = words[run_end], words[run_end + 1]
            if run_end + 1 in protected:
                break
            if b.start - a.end > cfg.stutter_max_gap:
                break
            if not _is_repeat(a.text, b.text, fillers, cfg.stutter_min_prefix):
                break
            run_end += 1

        if run_end > i:
            # 마지막(가장 완전한) 발화만 남기고 앞의 것들을 버린다.
            for j in range(i, run_end):
                cuts.append(
                    Cut(
                        Span(words[j].start, words[j].end),
                        "stutter",
                        f"{words[j].text.strip()} → {words[run_end].text.strip()}",
                    )
                )
                removed.add(j)
            i = run_end + 1
        else:
            i += 1

    return cuts, removed


def _is_repeat(a: str, b: str, fillers: frozenset[str], min_prefix: int) -> bool:
    na, nb = textutil.normalize_word(a), textutil.normalize_word(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # 말을 끊고 더 긴 형태로 다시 시작: "그러니" → "그러니까"
    if len(na) < len(nb) and nb.startswith(na):
        # 한 글자 접두사는 위험하다. "이 이야기"의 '이', "내 내일"의 '내'는
        # 더듬은 게 아니라 멀쩡한 관형사다. 필러일 때만 예외로 허용한다.
        return len(na) >= min_prefix or textutil.is_filler(na, fillers)
    return False


def _detect_retakes(
    words: list[Word], cfg: DisfluencyConfig
) -> tuple[list[Cut], set[int]]:
    """비슷한 문장이 가까이서 두 번 나오면 앞의 것을 버린다."""
    sentences = textutil.group_sentences(words, max_gap=cfg.sentence_gap)
    # 각 문장의 단어 인덱스 범위를 함께 들고 다닌다.
    index_of: dict[int, int] = {id(w): i for i, w in enumerate(words)}

    cuts: list[Cut] = []
    removed: set[int] = set()
    dropped_sentences: set[int] = set()

    for a_idx, earlier in enumerate(sentences):
        if a_idx in dropped_sentences:
            continue
        a_text = textutil.join_words(earlier)
        if len(textutil.normalize_text(a_text)) < cfg.retake_min_chars:
            continue
        for b_idx in range(a_idx + 1, len(sentences)):
            later = sentences[b_idx]
            if later[0].start - earlier[-1].end > cfg.retake_window:
                break
            if b_idx in dropped_sentences:
                continue
            b_text = textutil.join_words(later)
            if len(textutil.normalize_text(b_text)) < cfg.retake_min_chars:
                continue
            if textutil.similarity(a_text, b_text) < cfg.retake_similarity:
                continue
            # 뒤 문장이 앞 문장보다 지나치게 짧으면 다시 말한 게 아니라
            # 요약/인용일 수 있으니 건드리지 않는다.
            if len(textutil.normalize_text(b_text)) < 0.7 * len(
                textutil.normalize_text(a_text)
            ):
                continue
            cuts.append(
                Cut(
                    Span(earlier[0].start, earlier[-1].end),
                    "retake",
                    f"{a_text} → {b_text}",
                )
            )
            dropped_sentences.add(a_idx)
            for w in earlier:
                removed.add(index_of[id(w)])
            break

    return cuts, removed


__all__ = ["detect"]
