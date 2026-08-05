"""자막 줄 만들기 + 컷 이후 타임라인으로 옮기기 + SRT 출력."""

from __future__ import annotations

from .config import SubtitleConfig
from .models import SubtitleLine, Word
from .timeline import TimeMap
from . import text as textutil

# 이 비율 이상 살아남아야 그 단어를 자막에 남긴다.
_SURVIVE_RATIO = 0.5


def build_lines(words: list[Word], cfg: SubtitleConfig) -> list[SubtitleLine]:
    """원본 타임라인 기준 자막 줄 목록."""
    if not cfg.enabled or not words:
        return []

    lines: list[SubtitleLine] = []
    budget = max(1, cfg.max_chars * max(1, cfg.max_lines))

    for sentence in textutil.group_sentences(
        words, max_gap=cfg.split_gap, use_punctuation=cfg.split_punctuation
    ):
        chunk: list[Word] = []
        for word in sentence:
            candidate = chunk + [word]
            too_long = len(textutil.join_words(candidate)) > budget
            too_slow = candidate[-1].end - candidate[0].start > cfg.max_duration
            if chunk and (too_long or too_slow):
                lines.append(_make_line(chunk, cfg))
                chunk = [word]
            else:
                chunk = candidate
        if chunk:
            lines.append(_make_line(chunk, cfg))

    return [line for line in lines if line.text]


def _make_line(words: list[Word], cfg: SubtitleConfig) -> SubtitleLine:
    raw = textutil.join_words(words)
    if cfg.strip_trailing_period:
        raw = raw.rstrip().rstrip(".。")
    return SubtitleLine(
        text=wrap(raw, cfg.max_chars, cfg.max_lines),
        start=words[0].start,
        end=words[-1].end,
        words=list(words),
    )


def wrap(text: str, max_chars: int, max_lines: int) -> str:
    """공백 기준으로 최대 `max_lines`줄까지 접는다. 마지막 줄은 넘쳐도 그냥 둔다."""
    if max_lines <= 1 or len(text) <= max_chars:
        return text
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars and len(lines) < max_lines - 1:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines[:max_lines])


def remap(
    lines: list[SubtitleLine], timemap: TimeMap, cfg: SubtitleConfig
) -> list[SubtitleLine]:
    """컷을 반영해 자막을 새 타임라인으로 옮긴다.

    - 잘려나간 단어는 자막 문구에서도 빠진다 (필러를 지웠으면 자막에도 없어야 한다)
    - 한 줄이 통째로 잘렸으면 그 줄은 사라진다
    """
    out: list[SubtitleLine] = []
    for line in lines:
        survivors = [w for w in line.words if _survives(w, timemap)]
        if not survivors:
            continue
        raw = textutil.join_words(survivors)
        if cfg.strip_trailing_period:
            raw = raw.rstrip().rstrip(".。")
        if not raw:
            continue

        start = timemap.snap_to_output(survivors[0].start, prefer="forward")
        end = timemap.snap_to_output(survivors[-1].end, prefer="back")
        if end <= start:
            end = start + cfg.min_duration
        out.append(
            SubtitleLine(
                text=wrap(raw, cfg.max_chars, cfg.max_lines),
                start=start,
                end=end,
                words=survivors,
            )
        )

    return _tidy(out, timemap.output_duration, cfg)


def _survives(word: Word, timemap: TimeMap) -> bool:
    span = word.span
    if span.duration <= 0:
        return timemap.is_kept(span.start)
    kept = 0.0
    for keep in timemap.keeps:
        hit = keep.intersection(span)
        if hit:
            kept += hit.duration
    return kept / span.duration >= _SURVIVE_RATIO


def _tidy(
    lines: list[SubtitleLine], total: float, cfg: SubtitleConfig
) -> list[SubtitleLine]:
    """너무 짧은 자막은 늘리고, 겹치면 앞의 것을 뒤로 밀지 않게 끊는다."""
    lines.sort(key=lambda l: (l.start, l.end))
    for i, line in enumerate(lines):
        limit = lines[i + 1].start if i + 1 < len(lines) else total
        if line.end - line.start < cfg.min_duration:
            line.end = min(line.start + cfg.min_duration, max(limit, line.end))
        if line.end > limit:
            line.end = limit
    return [l for l in lines if l.end > l.start]


def format_timestamp(seconds: float, sep: str = ",") -> str:
    seconds = max(0.0, seconds)
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(lines: list[SubtitleLine]) -> str:
    blocks = []
    for i, line in enumerate(lines, start=1):
        blocks.append(
            f"{i}\n"
            f"{format_timestamp(line.start)} --> {format_timestamp(line.end)}\n"
            f"{line.text}\n"
        )
    return "\n".join(blocks)


__all__ = ["build_lines", "remap", "to_srt", "wrap", "format_timestamp"]
