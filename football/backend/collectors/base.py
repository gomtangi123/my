"""수집기 공통 형식. 소스별 어댑터는 경기를 RawMatch 로 바꿔서 넘기고, DB 저장은 store.py 가 맡는다.
→ 새 데이터 소스를 붙일 때는 RawMatch 를 만들어 내는 어댑터만 추가하면 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

STATUS_SCHEDULED = "scheduled"
STATUS_FINISHED = "finished"
STATUS_POSTPONED = "postponed"
STATUS_CANCELLED = "cancelled"


@dataclass
class RawTeamStats:
    shots: int | None = None
    shots_on_target: int | None = None
    corners: int | None = None
    fouls: int | None = None
    yellow_cards: int | None = None
    red_cards: int | None = None
    possession: float | None = None
    passes: int | None = None
    pass_accuracy: float | None = None
    xg: float | None = None

    def is_empty(self) -> bool:
        return all(v is None for v in vars(self).values())


@dataclass
class RawOdds:
    bookmaker: str
    kind: str  # pre / closing
    home: float | None
    draw: float | None
    away: float | None


@dataclass
class RawMatch:
    source: str
    league_key: str
    season_label: str
    external_id: str
    kickoff_utc: datetime  # 반드시 시간대 포함 (UTC)
    home_name: str
    away_name: str
    status: str = STATUS_SCHEDULED
    home_ext_id: str | None = None
    away_ext_id: str | None = None
    home_goals: int | None = None
    away_goals: int | None = None
    ht_home_goals: int | None = None
    ht_away_goals: int | None = None
    result_90: str | None = None
    decided_by: str | None = None
    round: str | None = None
    stage: str | None = None
    venue: str | None = None
    neutral_venue: bool = False
    referee: str | None = None
    home_stats: RawTeamStats | None = None
    away_stats: RawTeamStats | None = None
    odds: list[RawOdds] = field(default_factory=list)


def season_label(start_year: int, season_format: str) -> str:
    """시즌 표시 라벨: cross_year → '2026-27', calendar_year → '2026'."""
    if season_format == "cross_year":
        return f"{start_year}-{(start_year + 1) % 100:02d}"
    return str(start_year)


def current_season_start_year(season_format: str, today: date) -> int:
    """오늘 기준 진행 중(또는 막 끝난) 시즌의 시작 연도. 유럽식은 7월에 새 시즌으로 넘어간다고 본다."""
    if season_format == "cross_year":
        return today.year if today.month >= 7 else today.year - 1
    return today.year


def result_from_goals(home: int | None, away: int | None) -> str | None:
    if home is None or away is None:
        return None
    return "H" if home > away else "A" if away > home else "D"
