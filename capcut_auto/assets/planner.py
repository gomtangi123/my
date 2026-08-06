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

# 한 장이 이보다 짧게 스치면 깜빡이는 것처럼 보인다. 막지는 않고 알려만 준다.
COMFORTABLE_MIN = 1.2

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
    if not cfg.enabled or not providers:
        return AssetPlanResult([], [])

    query_map = merge_map(dict(cfg.query_map) if cfg.query_map else None)

    # 전체 채우기는 자막이 없어도 된다. 자막은 그림이 바뀌는 지점과 검색어를
    # 정하는 데만 쓰이고, 없으면 일정한 길이로 끊어서 채운다.
    if cfg.coverage == "full":
        return _plan_full_coverage(
            plan, timemap, cfg, providers, cache_dir, query_map, say
        )

    if not plan.subtitles:
        return AssetPlanResult([], [])

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


# --------------------------------------------------------- 전체 채우기 모드


def _plan_full_coverage(
    plan: EditPlan,
    timemap: TimeMap,
    cfg: AssetsConfig,
    providers: list[Provider],
    cache_dir: Path,
    query_map: dict,
    say,
) -> AssetPlanResult:
    """처음부터 끝까지 소재로 덮는다. 빈 구간을 남기지 않는다.

    자막 줄 경계에서 그림이 바뀌도록 맞추되, 소재가 짧으면(영상·GIF) 거기서
    끊고 바로 다음 소재를 이어 붙인다. 소재 개수가 모자라면 돌려 쓴다.
    """
    total = timemap.output_duration
    boundaries = _boundaries(plan, cfg, total)

    overlays: list[Overlay] = []
    skipped: list[str] = []
    searched: dict[tuple[str, str], list[AssetRef]] = {}
    fetched: set[tuple[str, str]] = set()
    pool = _preload(providers, cfg, cache_dir, fetched, skipped)

    if pool and not cfg.reuse:
        # 한 장씩 한 번만. 영상 길이를 장수로 나눠 고르게 배분한다.
        return _spread_once(pool, plan, cfg, total, query_map, skipped, say)

    if pool:
        say(f"내 소재 {len(pool)}개를 전체 구간에 돌려 씁니다")
    cursor = 0.0
    guard = 0

    while cursor < total - 0.05 and guard < 2000:
        guard += 1
        slot_end = min(_next_boundary(boundaries, cursor, cfg), total)
        slot = _slot_at(plan, cursor, slot_end, cfg, query_map)

        asset = _next_asset(
            slot, cfg, providers, cache_dir, searched, fetched, pool,
            turn=len(overlays),
            last=overlays[-1].asset if overlays else None,
            skipped=skipped, say=say,
        )
        if asset is None:
            break  # 쓸 수 있는 소재가 하나도 없다

        end = slot_end
        if asset.kind in ("video", "gif") and asset.duration > 0:
            end = min(end, cursor + asset.duration)
        if end - cursor < 0.3:  # 너무 짧게 스치는 건 보기 사납다
            end = min(cursor + 0.3, total)

        overlays.append(
            Overlay(
                start=cursor,
                end=end,
                asset=asset,
                keyword=slot.keyword,
                score=slot.score,
                scale=_scale_for(asset.kind, cfg),
                position_y=_position_for(asset.kind, cfg),
                reason="coverage",
            )
        )
        cursor = end

    say(f"전체 채우기: {len(overlays)}개 구간, 소재 {len(pool)}종")
    if not overlays:
        skipped.append("쓸 수 있는 소재가 없어 전체 채우기를 못 했습니다.")
    return AssetPlanResult(overlays, skipped)


def _spread_once(
    pool: list[Asset],
    plan: EditPlan,
    cfg: AssetsConfig,
    total: float,
    query_map: dict,
    skipped: list[str],
    say,
) -> AssetPlanResult:
    """가진 소재를 한 장씩 한 번만 써서 전체를 덮는다."""
    durations = share_durations(pool, total)

    overlays: list[Overlay] = []
    cursor = 0.0
    for asset, duration in zip(pool, durations):
        if duration <= 0.05:
            continue
        slot = _slot_at(plan, cursor, cursor + duration, cfg, query_map)
        overlays.append(
            Overlay(
                start=cursor,
                end=cursor + duration,
                asset=asset,
                keyword=slot.keyword,
                score=slot.score,
                scale=_scale_for(asset.kind, cfg),
                position_y=_position_for(asset.kind, cfg),
                reason="coverage",
            )
        )
        cursor += duration

    covered = sum(o.duration for o in overlays)
    average = covered / max(len(overlays), 1)
    say(f"소재 {len(overlays)}개를 한 번씩만 사용 — 한 개당 평균 {average:.1f}초")

    if average < COMFORTABLE_MIN and overlays:
        # 장수에 비해 영상이 짧으면 그림이 깜빡이듯 지나간다. 막지는 않되
        # 몇 장이 알맞은지는 알려 준다.
        fits = max(1, int(total / COMFORTABLE_MIN))
        note = (
            f"이미지가 많아 한 장이 {average:.1f}초만 보입니다. "
            f"이 길이({total:.0f}초)에는 {fits}장 정도가 알맞습니다."
        )
        skipped.append(note)
        say(f"  주의: {note}")
    if total - covered > 0.2:
        # 영상 소재가 짧아서 다 채우지 못한 경우
        skipped.append(
            f"소재 길이가 모자라 {total - covered:.1f}초가 비었습니다. "
            "이미지를 더 올리거나 '반복해서 쓰기'를 켜세요."
        )
        say(f"  주의: {total - covered:.1f}초가 비었습니다")
    return AssetPlanResult(overlays, skipped)


def share_durations(assets: list[Asset], total: float) -> list[float]:
    """전체 길이를 소재들에게 고르게 나눈다.

    이미지는 얼마든지 늘릴 수 있지만 영상·GIF는 제 길이를 넘지 못한다.
    한계에 걸린 소재를 먼저 확정하고, 남는 시간을 나머지가 다시 나눠 갖는다.
    """
    count = len(assets)
    if count == 0 or total <= 0:
        return []

    limits = [
        asset.duration
        if asset.kind in ("video", "gif") and asset.duration > 0
        else float("inf")
        for asset in assets
    ]
    durations = [0.0] * count
    settled = [False] * count
    remaining, free = total, count

    while free > 0:
        share = remaining / free
        capped = [i for i in range(count) if not settled[i] and limits[i] < share]
        if not capped:
            for i in range(count):
                if not settled[i]:
                    durations[i] = share
            break
        for i in capped:
            durations[i] = limits[i]
            settled[i] = True
            remaining -= limits[i]
            free -= 1

    return durations


def _boundaries(plan: EditPlan, cfg: AssetsConfig, total: float) -> list[float]:
    """그림이 바뀌기 좋은 지점들. 자막 줄 시작에 맞춘다."""
    marks = sorted({line.start for line in plan.subtitles if 0 < line.start < total})
    return marks + [total]


def _next_boundary(boundaries: list[float], cursor: float, cfg: AssetsConfig) -> float:
    """`cursor`에서 시작해 적당한 길이가 되는 다음 경계."""
    earliest = cursor + cfg.min_duration
    latest = cursor + cfg.max_duration
    for mark in boundaries:
        if mark >= earliest:
            return min(mark, latest)
    return latest


def _slot_at(
    plan: EditPlan, start: float, end: float, cfg: AssetsConfig, query_map: dict
) -> Slot:
    """그 구간에서 말하는 내용의 대표 키워드를 뽑는다."""
    words = [
        w
        for line in plan.subtitles
        if line.start < end and line.end > start
        for w in line.words
    ]
    ranked = kw.rank(words, use_konlpy=cfg.use_konlpy) if words else []
    if ranked:
        best = max(ranked, key=lambda k: k.score)
        query = query_map.get(best.text) or query_map.get(best.text.lower()) or best.text
        return Slot(start, end, best.text, query, best.score, "coverage")
    return Slot(start, end, "", "", 0.0, "coverage")


def _preload(
    providers: list[Provider],
    cfg: AssetsConfig,
    cache_dir: Path,
    fetched: set,
    skipped: list[str],
) -> list[Asset]:
    """내 소재 폴더에 있는 것들을 미리 다 받아 둔다.

    전체 채우기에서는 올려 둔 이미지를 하나도 남김없이 쓰는 게 자연스럽다.
    키워드가 안 맞는 구간도 이 목록에서 돌려 쓰면 빈틈이 안 생긴다.
    """
    pool: list[Asset] = []
    for provider in providers:
        for ref in provider.inventory():
            try:
                asset = cache.fetch(ref, cache_dir, query=ref.source_id)
            except ProviderError as exc:
                skipped.append(f"{ref.source_id}: {exc}")
                continue
            fetched.add((ref.source, ref.source_id))
            pool.append(asset)
    return pool


def _next_asset(
    slot: Slot,
    cfg: AssetsConfig,
    providers: list[Provider],
    cache_dir: Path,
    searched: dict,
    fetched: set,
    pool: list[Asset],
    turn: int,
    last: Asset | None,
    skipped: list[str],
    say,
) -> Asset | None:
    """키워드에 맞는 새 소재를 먼저, 없으면 가진 것 중에서 돌려 쓴다."""
    if slot.query:
        ref = _first_available(
            slot, _pick_kind(slot, cfg), cfg, providers, fetched, searched, skipped, say
        )
        if ref is not None:
            try:
                asset = cache.fetch(ref, cache_dir, query=slot.query)
            except ProviderError as exc:
                skipped.append(f"{slot.query}: {exc}")
            else:
                fetched.add((ref.source, ref.source_id))
                pool.append(asset)
                return asset

    if not pool or not cfg.reuse:
        return None  # 한 번씩만 쓰기로 했으면 여기서 멈춘다

    # 돌려 쓰기 — 목록을 순서대로 한 바퀴씩 돈다.
    # 앞에 나온 것과 겹치면 한 칸 밀되, 후보에서 아예 빼면 안 된다.
    # (빼고 나머지에서 고르면 3개일 때 두 개만 번갈아 나오고 하나가 죽는다)
    index = turn % len(pool)
    asset = pool[index]
    if last is not None and asset.path == last.path and len(pool) > 1:
        asset = pool[(index + 1) % len(pool)]
    return asset


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
