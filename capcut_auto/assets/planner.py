"""자료화면 / 이미지 / GIF를 '어디에 무엇을' 넣을지 정하고 내려받는다.

자막 한 줄을 후보 자리로 보고, 그 안에서 뽑은 키워드 점수로 줄을 세운다.
점수 높은 자리부터 채우되 간격·밀도 제한에 걸리면 건너뛴다.
그래서 영상 전체에 골고루, 그러나 과하지 않게 깔린다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import keywords as kw
from ..config import AssetsConfig
from ..models import EditPlan
from ..stockwords import merge_map
from ..timeline import TimeMap
from . import cache
from .models import Asset, AssetRef, Overlay
from .providers import Provider, ProviderError

# 이런 말이 나오면 자료화면보다 리액션 GIF가 어울린다.
REACTION_WORDS = frozenset(
    """
    웃음 웃겨 대박 헐 미쳤 실화 놀람 당황 황당 어이 눈물 슬픔 행복 신남
    박수 축하 응원 사랑 화남 짜증 최고 소름 감동 충격
    """.split()
)


@dataclass
class AssetPlanResult:
    overlays: list[Overlay]
    skipped: list[str]

    @property
    def assets(self) -> list[Asset]:
        return [o.asset for o in self.overlays]


def plan_assets(
    plan: EditPlan,
    timemap: TimeMap,
    cfg: AssetsConfig,
    providers: list[Provider],
    cache_dir: Path,
    progress=None,
) -> AssetPlanResult:
    say = progress or (lambda _m: None)
    if not cfg.enabled or not providers or not plan.subtitles:
        return AssetPlanResult([], [])

    query_map = merge_map(dict(cfg.query_map) if cfg.query_map else None)
    slots = _score_slots(plan, timemap, cfg, query_map)
    chosen = _select(slots, cfg, timemap.output_duration)
    budget = _budget(cfg, timemap.output_duration, len(chosen))
    say(f"소재 자리 {len(chosen)}개 선정 (후보 {len(slots)}개, 최대 {budget}개 채움)")

    overlays: list[Overlay] = []
    skipped: list[str] = []
    used: set[tuple[str, str]] = set()
    searched: dict[tuple[str, str], list[AssetRef]] = {}

    # 소재를 못 찾은 자리 때문에 개수 예산이 날아가면 안 된다.
    # 점수 높은 자리부터 시도하되, 실패하면 다음 자리로 넘어가서 예산을 채운다.
    for slot in sorted(chosen, key=lambda s: (-s.score, s.start)):
        if len(overlays) >= budget:
            break
        kind = _pick_kind(slot, cfg)
        ref = _first_available(
            slot, kind, cfg, providers, used, searched, skipped, say
        )
        if ref is None:
            continue
        try:
            asset = cache.fetch(ref, cache_dir, query=slot.query)
        except ProviderError as exc:
            skipped.append(f"{slot.query}: {exc}")
            continue

        used.add((ref.source, ref.source_id))
        # 영상/GIF는 소재보다 길게 깔 수 없다. 이미지는 얼마든지 늘려도 된다.
        end = slot.end
        if asset.kind in ("video", "gif") and asset.duration > 0:
            end = min(end, slot.start + asset.duration)
        if end - slot.start < cfg.min_duration * 0.6:
            skipped.append(f"{slot.query}: 소재가 너무 짧음({asset.duration:.1f}초)")
            continue

        overlays.append(
            Overlay(
                start=slot.start,
                end=end,
                asset=asset,
                keyword=slot.keyword,
                score=slot.score,
                scale=_scale_for(asset.kind, cfg),
                position_y=_position_for(asset.kind, cfg),
                reason=slot.reason,
            )
        )
        say(f"  {slot.start:7.2f}s  [{asset.kind}] {slot.keyword} → {ref.source}")

    overlays.sort(key=lambda o: o.start)
    return AssetPlanResult(overlays, skipped)


# ------------------------------------------------------------------ 자리 고르기


@dataclass
class Slot:
    start: float
    end: float
    keyword: str
    query: str
    score: float
    reason: str = "keyword"

    @property
    def duration(self) -> float:
        return self.end - self.start


def _score_slots(
    plan: EditPlan, timemap: TimeMap, cfg: AssetsConfig, query_map: dict
) -> list[Slot]:
    all_words = [w for line in plan.subtitles for w in line.words]
    frequency = kw.document_frequency(all_words, use_konlpy=cfg.use_konlpy)

    slots: list[Slot] = []
    for line in plan.subtitles:
        ranked = kw.rank(line.words, frequency, use_konlpy=cfg.use_konlpy)
        if not ranked:
            continue
        best = max(ranked, key=lambda k: k.score)
        if best.score < cfg.min_score:
            continue
        query = query_map.get(best.text) or query_map.get(best.text.lower()) or best.text
        slots.append(
            Slot(
                start=line.start,
                end=line.end,
                keyword=best.text,
                query=query,
                score=best.score,
            )
        )
    return slots


def _budget(cfg: AssetsConfig, total: float, available: int) -> int:
    """분당 개수 제한으로 계산한 최대 삽입 개수."""
    if not cfg.max_per_minute:
        return available
    return max(1, round(cfg.max_per_minute * max(total, 1.0) / 60.0))


def _select(slots: list[Slot], cfg: AssetsConfig, total: float) -> list[Slot]:
    """서로 간격이 확보되는 자리들을 점수 순으로 잡아 둔다.

    개수 제한은 여기서 걸지 않는다. 소재를 못 찾은 자리를 건너뛰고
    다음 자리로 넘어갈 수 있도록 여유분까지 남겨 둔다.
    """
    ranked = sorted(slots, key=lambda s: (-s.score, s.start))
    taken: list[Slot] = []
    for slot in ranked:
        if any(_conflicts(slot, other, cfg.min_gap) for other in taken):
            continue
        taken.append(slot)

    taken.sort(key=lambda s: s.start)
    return _fit_durations(taken, cfg, total)


def _conflicts(a: Slot, b: Slot, min_gap: float) -> bool:
    return a.start < b.end + min_gap and b.start < a.end + min_gap


def _fit_durations(slots: list[Slot], cfg: AssetsConfig, total: float) -> list[Slot]:
    """너무 짧은 자리는 늘리고, 너무 긴 자리는 자른다. 이웃은 침범하지 않는다."""
    out: list[Slot] = []
    for i, slot in enumerate(slots):
        limit = slots[i + 1].start - cfg.min_gap if i + 1 < len(slots) else total
        end = slot.end
        if slot.duration < cfg.min_duration:
            end = min(slot.start + cfg.min_duration, max(limit, slot.end))
        end = min(end, slot.start + cfg.max_duration, total)
        if end - slot.start < cfg.min_duration * 0.6:
            continue
        out.append(
            Slot(slot.start, end, slot.keyword, slot.query, slot.score, slot.reason)
        )
    return out


def _pick_kind(slot: Slot, cfg: AssetsConfig) -> str:
    if cfg.gif_for_reactions and any(
        word in slot.keyword for word in REACTION_WORDS
    ):
        return "gif"
    return cfg.prefer[0] if cfg.prefer else "video"


def _queries_for(slot: Slot, provider: Provider) -> list[str]:
    """제공자에 맞는 검색어 순서.

    스톡 사이트는 영어가 훨씬 잘 먹고, 내 소재 폴더는 파일 이름이 한국어일
    가능성이 높다. 어느 쪽이든 실패하면 나머지 하나로 한 번 더 시도한다.
    """
    korean, english = slot.keyword, slot.query
    order = [korean, english] if provider.name == "local" else [english, korean]
    seen: list[str] = []
    for query in order:
        if query and query not in seen:
            seen.append(query)
    return seen


def _first_available(
    slot: Slot,
    kind: str,
    cfg: AssetsConfig,
    providers: list[Provider],
    used: set[tuple[str, str]],
    searched: dict[tuple[str, str], list[AssetRef]],
    skipped: list[str],
    say,
) -> AssetRef | None:
    """원하는 종류부터 시도하고, 없으면 다음 종류로 물러선다."""
    order = [kind] + [k for k in cfg.prefer if k != kind]
    for want in order:
        for provider in providers:
            if not provider.supports(want):
                continue
            for query in _queries_for(slot, provider):
                key = (provider.name, f"{want}:{query}")
                if key not in searched:
                    try:
                        searched[key] = provider.search(query, want, cfg.candidates)
                    except ProviderError as exc:
                        searched[key] = []
                        skipped.append(f"{query} ({provider.name}): {exc}")
                        say(f"  경고: {provider.name} 검색 실패 — {exc}")
                for ref in searched[key]:
                    if (ref.source, ref.source_id) in used:
                        continue
                    return ref
    skipped.append(f"{slot.keyword}: 쓸 만한 소재를 못 찾음")
    return None


def _scale_for(kind: str, cfg: AssetsConfig) -> float:
    if kind == "video":
        return cfg.broll_scale
    if kind == "gif":
        return cfg.gif_scale
    return cfg.image_scale


def _position_for(kind: str, cfg: AssetsConfig) -> float:
    # 자료화면은 화면을 꽉 채우고, 이미지/GIF는 위쪽에 띄워 자막을 가리지 않게.
    return 0.0 if kind == "video" else cfg.overlay_position_y


__all__ = ["plan_assets", "AssetPlanResult", "Slot", "REACTION_WORDS"]
