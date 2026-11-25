"""DB 스키마 (SQLAlchemy 2.0). SQLite(개발)·PostgreSQL(배포) 공용.

원칙
- 팀·선수는 내부 ID로 관리하고, 외부 소스 ID는 external_ids 테이블로 매핑한다.
- 팀 이름 표기 차이는 team_aliases 테이블로 흡수한다 (소스마다 'Man United' / 'Manchester United' 등).
- 시간은 모두 UTC로 저장한다 (UTCDateTime 타입이 강제). 화면 표시 때 KST로 바꾼다.
- 시즌은 '2025-26' 같은 문자열이 아니라 시작일·종료일로 판단한다. label은 표시용.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UTCDateTime(TypeDecorator):
    """시간대 없는 datetime은 거부하고, UTC로 바꿔 저장·조회한다 (SQLite는 시간대를 저장하지 못함)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("시간대 정보가 없는 datetime은 저장할 수 없습니다 (UTC로 변환해서 넣으세요)")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ── 대회·시즌 ────────────────────────────────────────────

class League(Base):
    """대회. config/leagues.yaml 의 key 와 1:1 (init_db 가 동기화)."""

    __tablename__ = "leagues"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name_ko: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(16))  # league / cup
    region: Mapped[str] = mapped_column(String(16))  # europe / asia
    timezone: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    seasons: Mapped[list[Season]] = relationship(back_populates="league")


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("league_id", "label"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id"))
    label: Mapped[str] = mapped_column(String(16))  # 표시용: "2026-27", "2026"
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    league: Mapped[League] = relationship(back_populates="seasons")


# ── 팀·선수·매핑 ──────────────────────────────────────────

class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)  # 대표 영문 표기
    name_ko: Mapped[str | None] = mapped_column(String(100))
    short_name: Mapped[str | None] = mapped_column(String(8))  # 배지에 쓰는 약칭
    country: Mapped[str | None] = mapped_column(String(64))
    color_primary: Mapped[str | None] = mapped_column(String(7))  # "#RRGGBB" — 로고 대신 원형 배지
    color_secondary: Mapped[str | None] = mapped_column(String(7))

    aliases: Mapped[list[TeamAlias]] = relationship(back_populates="team")


class TeamAlias(Base):
    """소스별 팀 이름 표기 → 내부 팀. 같은 소스 안에서 같은 별칭은 한 팀만 가리킨다."""

    __tablename__ = "team_aliases"
    __table_args__ = (UniqueConstraint("source", "alias"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    source: Mapped[str] = mapped_column(String(32))  # football_data / thesportsdb / api_football / manual
    alias: Mapped[str] = mapped_column(String(100))

    team: Mapped[Team] = relationship(back_populates="aliases")


class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    name_ko: Mapped[str | None] = mapped_column(String(100))
    position: Mapped[str | None] = mapped_column(String(16))  # GK / DF / MF / FW
    birth_date: Mapped[date | None] = mapped_column(Date)
    nationality: Mapped[str | None] = mapped_column(String(64))
    current_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))


class ExternalId(Base):
    """내부 ID ↔ 외부 소스 ID 매핑 (리그·팀·선수·경기 공용)."""

    __tablename__ = "external_ids"
    __table_args__ = (
        UniqueConstraint("entity_type", "source", "external_id"),
        UniqueConstraint("entity_type", "entity_id", "source"),
        CheckConstraint("entity_type IN ('league','team','player','match')", name="ck_external_entity_type"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(16))
    entity_id: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))


# ── 경기 ─────────────────────────────────────────────────

class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("season_id", "home_team_id", "away_team_id", "kickoff_utc"),
        CheckConstraint("home_team_id <> away_team_id", name="ck_match_distinct_teams"),
        CheckConstraint("result_90 IS NULL OR result_90 IN ('H','D','A')", name="ck_match_result_90"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    kickoff_utc: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    round: Mapped[str | None] = mapped_column(String(64))
    stage: Mapped[str | None] = mapped_column(String(32))  # regular / split_a / split_b / league_stage / knockout / playoff
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    neutral_venue: Mapped[bool] = mapped_column(Boolean, default=False)  # True면 홈 어드밴티지 끔
    venue: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default="scheduled")  # scheduled / finished / postponed / cancelled
    # 소스가 준 최종 스코어. 연장전(AET) 경기는 연장 득점이 포함될 수 있다 → decided_by 로 구분.
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    # 90분 결과 H/D/A — 승무패 예측·평가 기준. 연장·승부차기까지 간 경기는 90분 결과가 무승부(D).
    result_90: Mapped[str | None] = mapped_column(String(1))
    ht_home_goals: Mapped[int | None] = mapped_column(Integer)
    ht_away_goals: Mapped[int | None] = mapped_column(Integer)
    decided_by: Mapped[str | None] = mapped_column(String(16))  # regular / extra_time / penalties
    referee: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    season: Mapped[Season] = relationship()
    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])


class MatchTeamStats(Base):
    """경기 통계 (팀별 한 줄). 소스가 주지 않는 항목은 NULL — 화면에서 숨긴다."""

    __tablename__ = "match_team_stats"
    __table_args__ = (UniqueConstraint("match_id", "team_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    is_home: Mapped[bool] = mapped_column(Boolean)
    shots: Mapped[int | None] = mapped_column(Integer)
    shots_on_target: Mapped[int | None] = mapped_column(Integer)
    corners: Mapped[int | None] = mapped_column(Integer)
    fouls: Mapped[int | None] = mapped_column(Integer)
    yellow_cards: Mapped[int | None] = mapped_column(Integer)
    red_cards: Mapped[int | None] = mapped_column(Integer)
    possession: Mapped[float | None] = mapped_column(Float)  # %
    passes: Mapped[int | None] = mapped_column(Integer)
    pass_accuracy: Mapped[float | None] = mapped_column(Float)  # %
    xg: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))


class MatchOdds(Base):
    """배당 (모델 평가의 '배당 내재 확률' 기준선 전용 — 사이트에 표시하지 않는다)."""

    __tablename__ = "match_odds"
    __table_args__ = (UniqueConstraint("match_id", "bookmaker", "kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    bookmaker: Mapped[str] = mapped_column(String(32))  # 예: avg, max, pinnacle
    kind: Mapped[str] = mapped_column(String(16), default="pre")  # pre(경기 전) / closing(마감)
    home: Mapped[float | None] = mapped_column(Float)
    draw: Mapped[float | None] = mapped_column(Float)
    away: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))


class PlayerMatchStats(Base):
    """선수 경기 기록."""

    __tablename__ = "player_match_stats"
    __table_args__ = (UniqueConstraint("match_id", "player_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    minutes: Mapped[int | None] = mapped_column(Integer)
    goals: Mapped[int | None] = mapped_column(Integer)
    assists: Mapped[int | None] = mapped_column(Integer)
    shots: Mapped[int | None] = mapped_column(Integer)
    shots_on_target: Mapped[int | None] = mapped_column(Integer)
    key_passes: Mapped[int | None] = mapped_column(Integer)
    yellow_cards: Mapped[int | None] = mapped_column(Integer)
    red_cards: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)
    xg: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))


class Injury(Base):
    """부상·결장. reported_at 은 '언제 알려졌는지' — 예측 피처는 경기 시작 전에 알려진 것만 쓴다."""

    __tablename__ = "injuries"
    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    kind: Mapped[str | None] = mapped_column(String(32))  # injury / suspension / other
    reason: Mapped[str | None] = mapped_column(Text)
    reported_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expected_return: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32))


class Prediction(Base):
    """경기 예측. kind='live'는 경기 전에 만든 실제 예측, 'backtest'는 walk-forward 검증에서 만든 예측.

    Dixon-Coles는 λ·μ·ρ를 저장해 두면 API가 스코어 확률 행렬(히트맵)을 다시 계산할 수 있다.
    made_at 은 예측을 만든 시각 — 경기 시작 전이어야 '경기 전 예측'으로 인정한다 (모델 성능 페이지).
    """

    __tablename__ = "predictions"
    __table_args__ = (UniqueConstraint("match_id", "model", "kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    model: Mapped[str] = mapped_column(String(32))  # dixon_coles / elo
    kind: Mapped[str] = mapped_column(String(16), default="live")
    p_home: Mapped[float] = mapped_column(Float)
    p_draw: Mapped[float] = mapped_column(Float)
    p_away: Mapped[float] = mapped_column(Float)
    p_over_2_5: Mapped[float | None] = mapped_column(Float)
    p_btts: Mapped[float | None] = mapped_column(Float)
    exp_home_goals: Mapped[float | None] = mapped_column(Float)  # λ
    exp_away_goals: Mapped[float | None] = mapped_column(Float)  # μ
    rho: Mapped[float | None] = mapped_column(Float)
    elo_home: Mapped[float | None] = mapped_column(Float)
    elo_away: Mapped[float | None] = mapped_column(Float)
    made_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
