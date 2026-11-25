"""Football-Data.co.uk 어댑터 (무료 CSV, 키 없음).

- 주요 리그: https://football-data.co.uk/mmz4281/{시즌코드}/{리그코드}.csv  (예: 2627/E0) — 종료된 경기만 들어 있음
- 다가오는 경기: https://football-data.co.uk/fixtures.csv  (그 주 경기만)
- 추가 리그(J1 등): https://football-data.co.uk/new/{파일}.csv  — 모든 시즌이 한 파일에, 결과·배당만
- 경기 시간은 영국 현지 시간(Europe/London) → UTC로 바꾼다 (0단계에서 실제 데이터로 확인)
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.collectors.base import (
    STATUS_FINISHED,
    STATUS_SCHEDULED,
    RawMatch,
    RawOdds,
    RawTeamStats,
    result_from_goals,
    season_label,
)
from backend.collectors.http_cache import HttpCache
from backend.config import LeagueConfig

SOURCE = "football_data"
BASE = "https://football-data.co.uk"
UK = ZoneInfo("Europe/London")
CURRENT_MAX_AGE = timedelta(hours=12)
FIXTURES_MAX_AGE = timedelta(hours=6)


def season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def decode_csv(raw: bytes) -> list[dict]:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = csv.DictReader(io.StringIO(text))
    return [r for r in rows if any((v or "").strip() for k, v in r.items() if k)]


def parse_kickoff(d: str, t: str | None) -> datetime:
    d = d.strip()
    fmt = "%d/%m/%Y" if len(d.split("/")[-1]) == 4 else "%d/%m/%y"
    day = datetime.strptime(d, fmt).date()
    hhmm = time(12, 0)  # 오래된 시즌은 시간 정보가 없다 → 정오로 둔다 (같은 날 경기의 앞뒤 관계는 알 수 없음)
    if t and t.strip():
        hhmm = datetime.strptime(t.strip(), "%H:%M").time()
    return datetime.combine(day, hhmm, tzinfo=UK).astimezone(timezone.utc)


def _int(v) -> int | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _float(v) -> float | None:
    v = (v or "").strip()
    try:
        return float(v) if v else None
    except ValueError:
        return None


def _stats(r: dict, side: str) -> RawTeamStats | None:
    s = RawTeamStats(
        shots=_int(r.get(f"{side}S")), shots_on_target=_int(r.get(f"{side}ST")), corners=_int(r.get(f"{side}C")),
        fouls=_int(r.get(f"{side}F")), yellow_cards=_int(r.get(f"{side}Y")), red_cards=_int(r.get(f"{side}R")),
        xg=_float(r.get(f"{side}xG")),
    )
    return None if s.is_empty() else s


def _odds(r: dict) -> list[RawOdds]:
    out = []
    for book, prefix in (("avg", "Avg"), ("max", "Max"), ("pinnacle", "PS"), ("bet365", "B365")):
        for kind, mid in (("pre", ""), ("closing", "C")):
            h, d, a = (_float(r.get(f"{prefix}{mid}{x}")) for x in "HDA")
            if h and d and a:
                out.append(RawOdds(book, kind, h, d, a))
    return out


def row_to_match(r: dict, league: LeagueConfig, label: str) -> RawMatch | None:
    home = (r.get("HomeTeam") or r.get("Home") or "").strip()
    away = (r.get("AwayTeam") or r.get("Away") or "").strip()
    if not home or not away or not (r.get("Date") or "").strip():
        return None
    kickoff = parse_kickoff(r["Date"], r.get("Time"))
    hg = _int(r.get("FTHG") if "FTHG" in r else r.get("HG"))
    ag = _int(r.get("FTAG") if "FTAG" in r else r.get("AG"))
    finished = hg is not None and ag is not None
    res = (r.get("FTR") or r.get("Res") or "").strip() or None
    div = (r.get("Div") or league.sources["football_data"].get("code") or league.key).strip()
    return RawMatch(
        source=SOURCE, league_key=league.key, season_label=label,
        # 같은 시즌에 같은 홈·원정 조합이 두 번 나올 수 있으므로(스코틀랜드 스플릿 등) 날짜까지 넣는다
        external_id=f"{div}:{label}:{kickoff.date().isoformat()}:{home}:{away}",
        kickoff_utc=kickoff, home_name=home, away_name=away,
        status=STATUS_FINISHED if finished else STATUS_SCHEDULED,
        home_goals=hg, away_goals=ag,
        ht_home_goals=_int(r.get("HTHG")), ht_away_goals=_int(r.get("HTAG")),
        result_90=(res if res in ("H", "D", "A") else result_from_goals(hg, ag)) if finished else None,
        decided_by="regular" if finished else None,
        referee=(r.get("Referee") or "").strip() or None,
        home_stats=_stats(r, "H"), away_stats=_stats(r, "A"),
        odds=_odds(r),
    )


class FootballDataAdapter:
    source = SOURCE

    def __init__(self, http: HttpCache, today: date | None = None) -> None:
        self.http = http
        self.today = today or date.today()

    def fetch_season(self, league: LeagueConfig, start_year: int, is_current: bool) -> list[RawMatch]:
        fd = league.sources.get("football_data") or {}
        if fd.get("code"):
            return self._main_league(league, fd["code"], start_year, is_current)
        if fd.get("extra_file"):
            return self._extra_league(league, fd["extra_file"], fd.get("league_name"), start_year)
        return []

    def fetch_upcoming(self, league: LeagueConfig) -> list[RawMatch]:
        code = (league.sources.get("football_data") or {}).get("code")
        if not code:
            return []
        rows = decode_csv(self.http.get(f"{BASE}/fixtures.csv", "football_data/fixtures.csv", FIXTURES_MAX_AGE))
        out = []
        for r in rows:
            if (r.get("Div") or "").strip() != code:
                continue
            kickoff = parse_kickoff(r["Date"], r.get("Time"))
            start = kickoff.year if (league.season_format != "cross_year" or kickoff.month >= 7) else kickoff.year - 1
            m = row_to_match(r, league, season_label(start, league.season_format))
            if m:
                out.append(m)
        return out

    def _main_league(self, league, code, start_year, is_current) -> list[RawMatch]:
        sc = season_code(start_year)
        try:
            raw = self.http.get(f"{BASE}/mmz4281/{sc}/{code}.csv", f"football_data/{sc}/{code}.csv",
                                CURRENT_MAX_AGE if is_current else None)
        except FileNotFoundError:
            return []
        label = season_label(start_year, league.season_format)
        return [m for r in decode_csv(raw) if (m := row_to_match(r, league, label))]

    def _extra_league(self, league, file, league_name, start_year) -> list[RawMatch]:
        # 한 파일에 모든 시즌 → 하루에 한 번만 새로 받는다
        raw = self.http.get(f"{BASE}/new/{file}.csv", f"football_data/new/{file}.csv", CURRENT_MAX_AGE)
        out = []
        for r in decode_csv(raw):
            if league_name and (r.get("League") or "").strip() != league_name:
                continue
            season = (r.get("Season") or "").strip()  # "2024" 또는 "2026/2027"
            first = int(season.split("/")[0]) if season[:4].isdigit() else None
            if first != start_year:
                continue
            label = season_label(first, "cross_year" if "/" in season else "calendar_year")
            if (m := row_to_match(r, league, label)):
                out.append(m)
        return out
