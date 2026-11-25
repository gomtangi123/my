"""API 응답 형식 (/docs 에 그대로 표시된다). 시간은 모두 한국 시간(KST, +09:00) ISO 문자열."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TeamRef(BaseModel):
    id: int
    name: str = Field(description="영문 표기")
    name_ko: str | None = Field(None, description="한글 표기 (없으면 null)")
    short_name: str = Field(description="배지에 쓰는 약칭")
    color: str = Field(description="배지 색 #RRGGBB (로고 대신 사용)")


class LeagueOut(BaseModel):
    key: str
    name_ko: str
    type: str = Field(description="league / cup")
    region: str = Field(description="europe / asia")
    seasons: list[str]
    current_season: str | None
    has_match_stats: bool = Field(description="슈팅·코너 등 경기 통계 제공 여부 — false면 화면에서 숨김")
    has_xg: bool = Field(description="xG 제공 여부 — false면 화면에서 숨김")
    has_standings: bool


class StandingRow(BaseModel):
    rank: int
    team: TeamRef
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_diff: int
    points: int
    form: str = Field(description="최근 5경기, 예: '승승무패승'")


class LeagueAverages(BaseModel):
    matches: int
    goals_per_match: float | None
    home_win_rate: float | None
    draw_rate: float | None
    away_win_rate: float | None
    over_2_5_rate: float | None
    btts_rate: float | None
    shots_per_team: float | None
    corners_per_team: float | None
    xg_per_team: float | None


class StandingsOut(BaseModel):
    league: LeagueOut
    season: str
    venue: str
    rows: list[StandingRow]
    averages: LeagueAverages
    top_scorers: list | None = Field(None, description="득점 순위 — 선수 데이터가 없어 현재 null")


class Probabilities(BaseModel):
    model: str = Field(description="dixon_coles / elo")
    home_win: float
    draw: float
    away_win: float
    over_2_5: float | None = None
    btts: float | None = None


class MatchItem(BaseModel):
    id: int
    league_key: str
    league_name_ko: str
    season: str
    kickoff_kst: str
    status: str = Field(description="scheduled / finished / postponed / cancelled")
    home: TeamRef
    away: TeamRef
    home_goals: int | None
    away_goals: int | None
    decided_by: str | None
    prediction: Probabilities | None = Field(None, description="대표 예측 (리그: Dixon-Coles, 컵: Elo)")


class FormOut(BaseModel):
    results: str
    points: int
    games: int
    goals_for: int
    goals_against: int


class TeamComparisonSide(BaseModel):
    team: TeamRef
    form5: FormOut
    form10: FormOut
    profile: dict = Field(description="경기 시작 전 기준 이번 시즌 리그 지표 (없는 지표는 null)")
    rest_days: float | None
    matches_last_14d: int
    elo: float | None


class H2HOut(BaseModel):
    games: int
    home_team_wins: int
    draws: int
    away_team_wins: int
    matches: list[dict]


class PredictionDetail(BaseModel):
    main: Probabilities
    others: list[Probabilities]
    expected_goals: dict | None = Field(None, description="{'home': λ, 'away': μ}")
    most_likely_score: dict | None = None
    score_matrix: list[list[float]] | None = Field(None, description="[홈 득점][원정 득점] 확률 0~6골 (히트맵용)")
    made_at_kst: str
    pre_match: bool = Field(description="경기 시작 전에 만든 예측인지")


class MatchDetailOut(BaseModel):
    match: MatchItem
    venue: str | None
    neutral_venue: bool
    prediction: PredictionDetail | None
    comparison: dict[str, TeamComparisonSide]
    head_to_head: H2HOut
    model_explanation: str
    disclaimer: str


class TeamDetailOut(BaseModel):
    team: TeamRef
    league: LeagueOut | None
    season: str | None
    standing: StandingRow | None
    form5: FormOut
    form10: FormOut
    home: dict | None
    away: dict | None
    profile: dict
    goals_by_half: dict
    recent_matches: list[MatchItem]
    upcoming_matches: list[MatchItem]
    injuries: list = Field(default_factory=list, description="부상·결장 — 데이터 소스가 없어 현재 비어 있음")
    players: list = Field(default_factory=list, description="주요 선수 — 데이터 소스가 없어 현재 비어 있음")
    data_notes: list[str]


class PerformanceRow(BaseModel):
    model: str
    matches: int
    log_loss: float
    brier: float
    accuracy: float


class ModelPerformanceOut(BaseModel):
    overall: list[PerformanceRow]
    by_league: dict[str, list[PerformanceRow]]
    calibration: dict[str, list[dict]]
    recent: list[dict] = Field(description="최근 끝난 경기의 예측 vs 실제")
    notes: list[str]
