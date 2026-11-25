"""TheSportsDB 어댑터 — K리그1·AFC 챔피언스리그 일정·결과.

- 무료 테스트 키는 시즌 전체 조회가 15경기로 잘리므로 라운드별(eventsround.php)로 받는다.
- strTimestamp 는 UTC (0단계에서 경기장 현지 시간과 비교해 확인).
- 키는 환경변수 THESPORTSDB_KEY (없으면 공개 테스트 키 '123').
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

from backend.collectors.base import (
    STATUS_CANCELLED,
    STATUS_FINISHED,
    STATUS_POSTPONED,
    STATUS_SCHEDULED,
    RawMatch,
    result_from_goals,
    season_label,
)
from backend.collectors.http_cache import HttpCache
from backend.config import LeagueConfig

SOURCE = "thesportsdb"
HOST = "https://www.thesportsdb.com"
CURRENT_MAX_AGE = timedelta(hours=12)
MAX_ROUND = 60
EMPTY_ROUNDS_TO_STOP = 4

FINISHED = {"FT", "AET", "PEN", "AP", "Match Finished"}
POSTPONED = {"PST", "Postponed"}
CANCELLED = {"CANC", "ABD", "AWD", "WO", "Cancelled", "Abandoned"}


def tsdb_season(start_year: int, season_format: str) -> str:
    return f"{start_year}-{start_year + 1}" if season_format == "cross_year" else str(start_year)


def parse_kickoff(e: dict) -> datetime | None:
    ts = (e.get("strTimestamp") or "").strip()
    if ts:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    d, t = (e.get("dateEvent") or "").strip(), (e.get("strTime") or "00:00:00").strip() or "00:00:00"
    if not d:
        return None
    return datetime.fromisoformat(f"{d}T{t[:8]}").replace(tzinfo=timezone.utc)


def _int(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def event_to_match(e: dict, league: LeagueConfig, label: str) -> RawMatch | None:
    kickoff = parse_kickoff(e)
    home, away = (e.get("strHomeTeam") or "").strip(), (e.get("strAwayTeam") or "").strip()
    if not kickoff or not home or not away or not e.get("idEvent"):
        return None
    status_raw = (e.get("strStatus") or "").strip()
    hg, ag = _int(e.get("intHomeScore")), _int(e.get("intAwayScore"))
    if (e.get("strPostponed") or "").lower() == "yes" or status_raw in POSTPONED:
        status = STATUS_POSTPONED
    elif status_raw in CANCELLED:
        status = STATUS_CANCELLED
    elif status_raw in FINISHED and hg is not None and ag is not None:
        status = STATUS_FINISHED
    else:
        status = STATUS_SCHEDULED

    decided_by = result_90 = None
    if status == STATUS_FINISHED:
        if status_raw == "AET":
            decided_by, result_90 = "extra_time", "D"  # 연장까지 갔다면 90분은 무승부
        elif status_raw in ("PEN", "AP"):
            decided_by, result_90 = "penalties", "D"
        else:
            decided_by, result_90 = "regular", result_from_goals(hg, ag)
    else:
        hg = ag = None

    rnd = (e.get("intRound") or "").strip() or None
    return RawMatch(
        source=SOURCE, league_key=league.key, season_label=label, external_id=str(e["idEvent"]),
        kickoff_utc=kickoff, home_name=home, away_name=away,
        home_ext_id=str(e["idHomeTeam"]) if e.get("idHomeTeam") else None,
        away_ext_id=str(e["idAwayTeam"]) if e.get("idAwayTeam") else None,
        status=status, home_goals=hg, away_goals=ag, result_90=result_90, decided_by=decided_by,
        round=rnd, venue=(e.get("strVenue") or "").strip() or None,
        # 중립 경기 여부는 이 소스로 알 수 없다 → 기본 False, 필요하면 수동 보정 (ACL 집중 개최 라운드)
        neutral_venue=False,
    )


class TheSportsDbAdapter:
    source = SOURCE

    def __init__(self, http: HttpCache, api_key: str | None = None, today: date | None = None) -> None:
        self.http = http
        self.key = api_key or os.environ.get("THESPORTSDB_KEY") or "123"
        self.today = today or date.today()

    def _round(self, league_id: int, season: str, rnd: int, is_current: bool) -> list[dict]:
        url = f"{HOST}/api/v1/json/{self.key}/eventsround.php?id={league_id}&r={rnd}&s={season}"
        raw = self.http.get(url, f"thesportsdb/{league_id}/{season}/round_{rnd:03d}.json",
                            CURRENT_MAX_AGE if is_current else None)
        body = json.loads(raw.decode("utf-8") or "{}")
        return body.get("events") or []

    def fetch_season(self, league: LeagueConfig, start_year: int, is_current: bool) -> list[RawMatch]:
        ts = league.sources.get("thesportsdb") or {}
        if not ts.get("id"):
            return []
        season = tsdb_season(start_year, league.season_format)
        label = season_label(start_year, league.season_format)
        out, seen, empty_streak, found_any = [], set(), 0, False
        for rnd in range(1, MAX_ROUND + 1):
            events = self._round(int(ts["id"]), season, rnd, is_current)
            if not events:
                empty_streak += 1
                if found_any and empty_streak >= EMPTY_ROUNDS_TO_STOP:
                    break
                if not found_any and rnd >= EMPTY_ROUNDS_TO_STOP:
                    break  # 시즌 자체가 없음
                continue
            empty_streak, found_any = 0, True
            for e in events:
                m = event_to_match(e, league, label)
                if m and m.external_id not in seen:
                    seen.add(m.external_id)
                    out.append(m)
        return out

    def fetch_upcoming(self, league: LeagueConfig) -> list[RawMatch]:
        return []  # 진행 중 시즌을 라운드별로 다시 받으면 다가오는 경기도 포함된다
