"""효과음을 '어디에' 넣을지 정한다.

세 종류를 깐다.

transition : 컷이 들어간 자리 (무음/버벅임을 잘라낸 이음매)
section    : 크게 잘려 화제가 바뀌는 자리 -> 라이저로 넘어가는 느낌
emphasis   : 숫자, 강조어, 물음표처럼 귀를 끌어야 하는 지점

너무 많이 깔면 촌스러워지므로 최소 간격과 분당 개수로 밀도를 제한한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import SfxConfig
from ..models import EditPlan
from ..timeline import TimeMap
from .library import Library, Sound

# 이런 말이 나오면 귀를 세우게 만든다.
EMPHASIS_WORDS = frozenset(
    """
    가장 제일 최고 최악 최대 최소 유일 처음 마지막 절대 무조건 반드시
    진짜 정말 완전 대박 엄청 놀라운 충격 비밀 핵심 결론 중요 주의 경고
    무료 공짜 신기 대단 역대급 미친 레전드 실화 사실은 근데 하지만 그런데
    """.split()
)
_NUMBER_RE = re.compile(r"\d")
_QUESTION_RE = re.compile(r"[?？]")
_EXCLAIM_RE = re.compile(r"[!！]")

# 큰 값이 이긴다. 자리가 겹치면 높은 쪽만 남는다.
_PRIORITY = {"rule": 4, "section": 3, "emphasis": 2, "transition": 1}


@dataclass
class SfxPlacement:
    """출력 타임라인 기준 효과음 하나."""

    time: float
    sound: Sound
    duration: float
    volume: float
    reason: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "time": round(self.time, 3),
            "duration": round(self.duration, 3),
            "sound": self.sound.key,
            "builtin": self.sound.builtin,
            "volume": round(self.volume, 3),
            "reason": self.reason,
            "detail": self.detail,
        }


def plan_sfx(
    plan: EditPlan, timemap: TimeMap, cfg: SfxConfig, library: Library
) -> list[SfxPlacement]:
    if not cfg.enabled:
        return []

    total = timemap.output_duration
    found: list[SfxPlacement] = []
    found += _transitions(plan, cfg, library, total)
    if cfg.emphasis:
        found += _emphasis(plan, timemap, cfg, library, total)
    found += _rules(plan, timemap, cfg, library, total)

    return _thin_out(found, cfg, total)


def _transitions(
    plan: EditPlan, cfg: SfxConfig, library: Library, total: float
) -> list[SfxPlacement]:
    """컷 이음매마다. 잘려나간 길이에 따라 전환음/라이저를 고른다."""
    if not cfg.transition:
        return []

    out: list[SfxPlacement] = []
    cursor = 0.0
    for previous, current in zip(plan.keeps, plan.keeps[1:]):
        cursor += previous.duration
        removed = current.start - previous.end
        if removed < cfg.transition_min_gap:
            continue

        is_section = removed >= cfg.section_gap
        key = cfg.section_sound if is_section else cfg.transition_sound
        sound = library.find(key)
        if sound is None:
            continue
        duration = library.resolve_duration(sound)

        # 라이저는 이음매에서 '끝나야' 넘어가는 맛이 산다.
        at = cursor - duration if is_section else cursor - cfg.lead
        at = max(0.0, min(at, max(0.0, total - 0.05)))
        out.append(
            SfxPlacement(
                time=at,
                sound=sound,
                duration=duration,
                volume=cfg.volume,
                reason="section" if is_section else "transition",
                detail=f"{removed:.2f}초 제거",
            )
        )
    return out


def _emphasis(
    plan: EditPlan, timemap: TimeMap, cfg: SfxConfig, library: Library, total: float
) -> list[SfxPlacement]:
    out: list[SfxPlacement] = []
    for line in plan.subtitles:
        for word in line.words:
            key, why = _emphasis_kind(word.text, cfg)
            if key is None:
                continue
            sound = library.find(key)
            if sound is None:
                continue
            at = timemap.snap_to_output(word.start, prefer="forward") - cfg.lead
            at = max(0.0, min(at, max(0.0, total - 0.05)))
            out.append(
                SfxPlacement(
                    time=at,
                    sound=sound,
                    duration=library.resolve_duration(sound),
                    volume=cfg.volume,
                    reason="emphasis",
                    detail=f"{word.text.strip()} ({why})",
                )
            )
    return out


def _emphasis_kind(text: str, cfg: SfxConfig) -> tuple[str | None, str]:
    stripped = text.strip()
    bare = re.sub(r"[^\w가-힣]", "", stripped)
    if _QUESTION_RE.search(stripped):
        return cfg.question_sound, "물음표"
    if _EXCLAIM_RE.search(stripped):
        return cfg.emphasis_sound, "느낌표"
    if _NUMBER_RE.search(stripped):
        return cfg.number_sound, "숫자"
    if bare in EMPHASIS_WORDS:
        return cfg.emphasis_sound, "강조어"
    return None, ""


def _rules(
    plan: EditPlan, timemap: TimeMap, cfg: SfxConfig, library: Library, total: float
) -> list[SfxPlacement]:
    """설정에서 준 사용자 규칙: [{"match": "웃|하하", "sound": "boing"}]"""
    if not cfg.rules:
        return []
    compiled = []
    for rule in cfg.rules:
        pattern = rule.get("match")
        sound_key = rule.get("sound")
        if not pattern or not sound_key:
            continue
        compiled.append((re.compile(pattern), sound_key))
    if not compiled:
        return []

    out: list[SfxPlacement] = []
    for line in plan.subtitles:
        for word in line.words:
            for pattern, sound_key in compiled:
                if not pattern.search(word.text):
                    continue
                sound = library.find(sound_key)
                if sound is None:
                    continue
                at = timemap.snap_to_output(word.start, prefer="forward") - cfg.lead
                at = max(0.0, min(at, max(0.0, total - 0.05)))
                out.append(
                    SfxPlacement(
                        time=at,
                        sound=sound,
                        duration=library.resolve_duration(sound),
                        volume=cfg.volume,
                        reason="rule",
                        detail=f"{word.text.strip()} ~ /{pattern.pattern}/",
                    )
                )
                break
    return out


def _thin_out(
    items: list[SfxPlacement], cfg: SfxConfig, total: float
) -> list[SfxPlacement]:
    """겹치거나 너무 촘촘한 것들을 쳐낸다. 우선순위가 높은 쪽이 살아남는다."""
    if not items:
        return []

    # 우선순위 높은 순 -> 같은 순위면 앞선 시간 순으로 자리를 선점한다.
    ranked = sorted(
        items, key=lambda p: (-_PRIORITY.get(p.reason, 0), p.time)
    )
    budget = int(cfg.max_per_minute * max(total, 1.0) / 60.0) if cfg.max_per_minute else None

    kept: list[SfxPlacement] = []
    for item in ranked:
        if budget is not None and len(kept) >= max(1, budget):
            break
        if any(abs(item.time - other.time) < cfg.min_interval for other in kept):
            continue
        kept.append(item)

    kept.sort(key=lambda p: p.time)
    return kept


__all__ = ["SfxPlacement", "plan_sfx", "EMPHASIS_WORDS"]
