"""수집 작업.

    # 과거 시즌 일괄 수집 (기본: 최근 5시즌, 진행 중 시즌 포함)
    python -m backend.jobs.collect backfill --league eng_premier_league --seasons 5
    python -m backend.jobs.collect backfill --all

    # 매일 갱신: 진행 중 시즌 결과 + 다가오는 일정
    python -m backend.jobs.collect daily

받은 원본은 data/raw 에 캐시되고, 종료된 시즌은 다시 받지 않는다.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from sqlalchemy import func, select

from backend.collectors.base import current_season_start_year
from backend.collectors.football_data import FootballDataAdapter
from backend.collectors.http_cache import HttpCache
from backend.collectors.store import Store, StoreReport, summarize
from backend.collectors.thesportsdb import TheSportsDbAdapter
from backend.config import LeagueConfig, load_leagues
from backend.db.init_db import init_db, make_session_factory
from backend.db.schema import League, Match, MatchTeamStats, Season
from backend.db.team_names import apply_korean_names

log = logging.getLogger("collect")

HOST_INTERVALS = {"football-data.co.uk": 1.5, "www.football-data.co.uk": 1.5, "www.thesportsdb.com": 6.0}  # 무료 키: 30초에 약 12회를 넘으면 2분 차단됨


def adapters_for(league: LeagueConfig, http: HttpCache, today: date):
    out = []
    if league.sources.get("football_data"):
        out.append(FootballDataAdapter(http, today))
    if league.sources.get("thesportsdb"):
        out.append(TheSportsDbAdapter(http, today=today))
    return out


def league_country(league: LeagueConfig) -> str | None:
    c = ((league.sources.get("api_football") or {}).get("match") or {}).get("country")
    return None if c in (None, "World") else c


def collect_league(store: Store, league: LeagueConfig, http: HttpCache, years: list[int], today: date,
                   include_upcoming: bool) -> StoreReport:
    total = StoreReport()
    current = current_season_start_year(league.season_format, today)
    for ad in adapters_for(league, http, today):
        for y in years:
            ms = ad.fetch_season(league, y, is_current=(y >= current))
            rep = store.save_matches(ms, league_country(league))
            log.info("  %s %s %d: %d경기 → %s", league.key, ad.source, y, len(ms), summarize(rep))
            total.merge(rep)
        if include_upcoming:
            ms = ad.fetch_upcoming(league)
            if ms:
                rep = store.save_matches(ms, league_country(league))
                log.info("  %s %s 다가오는 경기: %d → %s", league.key, ad.source, len(ms), summarize(rep))
                total.merge(rep)
    return total


def run(command: str, league_keys: list[str] | None, seasons: int, today: date | None = None) -> int:
    today = today or date.today()
    leagues = [l for l in load_leagues(enabled_only=True) if not league_keys or l.key in league_keys]
    if league_keys and len(leagues) != len(set(league_keys)):
        missing = set(league_keys) - {l.key for l in leagues}
        log.error("설정에 없거나 꺼진 대회: %s", ", ".join(sorted(missing)))
        return 2
    leagues.sort(key=lambda l: l.priority)

    engine = init_db()
    http = HttpCache(min_interval=HOST_INTERVALS)
    failed = []
    with make_session_factory(engine)() as session:
        store = Store(session)
        for lg in leagues:
            current = current_season_start_year(lg.season_format, today)
            years = list(range(current - seasons + 1, current + 1)) if command == "backfill" else [current]
            log.info("[%s] %s 시즌 %s", lg.name_ko, command, years)
            try:
                rep = collect_league(store, lg, http, years, today, include_upcoming=True)
                session.commit()
                log.info("[%s] 완료: %s", lg.name_ko, summarize(rep))
                for line in rep.teams_linked:
                    log.info("    팀 연결 확인 필요: %s", line)
                for line in rep.duplicates_skipped:
                    log.info("    중복 경기 제외: %s", line)
            except Exception:  # 한 대회가 실패해도 나머지는 계속
                session.rollback()
                log.exception("[%s] 실패", lg.name_ko)
                failed.append(lg.key)
        dups = store.remove_swapped_duplicates()
        if dups:
            log.info("홈/원정만 바뀐 중복 경기 %d개 삭제 (소스 데이터 오류): %s", len(dups), dups)
        stale = store.mark_stale_scheduled()
        named = apply_korean_names(session)
        session.commit()
        if named:
            log.info("한글 팀 이름 %d개 반영", named)
        if stale:
            log.info("시작 시간이 지났는데 결과 없는 경기 %d개 → postponed 처리", stale)
        print_summary(session)
    log.info("실제 다운로드 %d회 (나머지는 캐시)", http.calls)
    if failed:
        log.error("실패한 대회: %s", ", ".join(failed))
        return 1
    return 0


def print_summary(session) -> None:
    rows = session.execute(
        select(League.name_ko, Season.label, Match.status, func.count(Match.id))
        .join(Season, Season.league_id == League.id).join(Match, Match.season_id == Season.id)
        .group_by(League.name_ko, Season.label, Match.status).order_by(League.name_ko, Season.label)
    ).all()
    detail = session.execute(
        select(League.name_ko, Season.label, func.count(MatchTeamStats.id), func.count(MatchTeamStats.xg))
        .join(Season, Season.league_id == League.id).join(Match, Match.season_id == Season.id)
        .join(MatchTeamStats, MatchTeamStats.match_id == Match.id).group_by(League.name_ko, Season.label)
    ).all()
    det = {(a, b): (c, d) for a, b, c, d in detail}
    table: dict[tuple[str, str], dict[str, int]] = {}
    for name, label, status, n in rows:
        table.setdefault((name, label), {})[status] = n
    print("\n| 대회 | 시즌 | 종료 | 예정 | 연기·취소 | 팀 통계 행 | xG 있는 행 |")
    print("|---|---|---|---|---|---|---|")
    for (name, label), st in table.items():
        s_rows, xg_rows = det.get((name, label), (0, 0))
        print(f"| {name} | {label} | {st.get('finished', 0)} | {st.get('scheduled', 0)} | "
              f"{st.get('postponed', 0) + st.get('cancelled', 0)} | {s_rows} | {xg_rows} |")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["backfill", "daily"])
    ap.add_argument("--league", action="append", help="대회 key (여러 번 가능). 없으면 활성 대회 전체")
    ap.add_argument("--all", action="store_true", help="활성 대회 전체 (--league 없을 때와 같음)")
    ap.add_argument("--seasons", type=int, default=5, help="backfill 시즌 수 (진행 중 시즌 포함)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return run(args.command, None if args.all else args.league, args.seasons)


if __name__ == "__main__":
    sys.exit(main())
