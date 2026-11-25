"""1단계: 설정 로더·DB 스키마 테스트 (메모리 SQLite)."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.config import load_leagues
from backend.db.init_db import make_engine, make_session_factory, sync_leagues
from backend.db.schema import Base, ExternalId, League, Match, MatchTeamStats, Season, Team, TeamAlias

KST = timezone(timedelta(hours=9))


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        yield s


def _season_with_teams(s):
    lg = League(key="test", name_ko="테스트", type="league", region="asia", timezone="Asia/Seoul")
    se = Season(league=lg, label="2026", start_date=date(2026, 2, 28), end_date=date(2026, 12, 6))
    a, b = Team(name="Ulsan HD"), Team(name="FC Seoul")
    s.add_all([lg, se, a, b])
    s.flush()
    return se, a, b


# ── 설정 ──

def test_leagues_yaml_loads_and_is_valid():
    leagues = load_leagues()
    keys = [l.key for l in leagues]
    assert len(keys) == len(set(keys))
    enabled = load_leagues(enabled_only=True)
    assert len(enabled) == 13
    assert {l.region for l in enabled} == {"europe", "asia"}


def test_every_enabled_league_has_a_results_source():
    for l in load_leagues(enabled_only=True):
        assert "football_data" in l.sources or "thesportsdb" in l.sources, l.key


def test_invalid_league_config_rejected(tmp_path):
    p = tmp_path / "leagues.yaml"
    p.write_text("leagues:\n  - {key: x, name_ko: x, type: tournament, region: asia, timezone: UTC, season_format: cross_year}\n")
    with pytest.raises(ValueError):
        load_leagues(p)


# ── 리그 동기화 ──

def test_sync_leagues_creates_rows_and_external_ids(session):
    sync_leagues(session, load_leagues())
    session.commit()
    k = session.scalar(select(League).where(League.key == "kor_k_league_1"))
    assert k.type == "league" and k.region == "asia"
    ext = {e.source: e.external_id for e in session.scalars(
        select(ExternalId).where(ExternalId.entity_type == "league", ExternalId.entity_id == k.id))}
    assert ext == {"thesportsdb": "4689", "api_football": "292"}


def test_sync_is_idempotent_and_disables_removed(session):
    leagues = load_leagues()
    sync_leagues(session, leagues)
    sync_leagues(session, leagues)
    session.commit()
    assert session.query(League).count() == len(leagues)
    sync_leagues(session, [l for l in leagues if l.key != "eng_premier_league"])
    session.commit()
    epl = session.scalar(select(League).where(League.key == "eng_premier_league"))
    assert epl is not None and epl.enabled is False


# ── 시간 ──

def test_kickoff_stored_as_utc(session):
    se, a, b = _season_with_teams(session)
    m = Match(season=se, home_team_id=a.id, away_team_id=b.id, kickoff_utc=datetime(2026, 3, 1, 14, 0, tzinfo=KST))
    session.add(m)
    session.commit()
    session.expire_all()
    got = session.get(Match, m.id).kickoff_utc
    assert got == datetime(2026, 3, 1, 5, 0, tzinfo=timezone.utc)
    assert got.tzinfo is not None


def test_naive_datetime_rejected(session):
    se, a, b = _season_with_teams(session)
    session.add(Match(season=se, home_team_id=a.id, away_team_id=b.id, kickoff_utc=datetime(2026, 3, 1, 14, 0)))
    with pytest.raises(Exception, match="시간대"):
        session.commit()


# ── 제약 조건 ──

def test_team_cannot_play_itself(session):
    se, a, _ = _season_with_teams(session)
    session.add(Match(season=se, home_team_id=a.id, away_team_id=a.id, kickoff_utc=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        session.commit()


def test_alias_unique_per_source(session):
    _, a, b = _season_with_teams(session)
    session.add_all([TeamAlias(team=a, source="football_data", alias="Ulsan"),
                     TeamAlias(team=a, source="thesportsdb", alias="Ulsan")])  # 소스가 다르면 허용
    session.commit()
    session.add(TeamAlias(team=b, source="football_data", alias="Ulsan"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_external_id_maps_one_to_one(session):
    session.add(ExternalId(entity_type="team", entity_id=1, source="thesportsdb", external_id="134000"))
    session.commit()
    session.add(ExternalId(entity_type="team", entity_id=2, source="thesportsdb", external_id="134000"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_one_stats_row_per_team_per_match(session):
    se, a, b = _season_with_teams(session)
    m = Match(season=se, home_team_id=a.id, away_team_id=b.id, kickoff_utc=datetime.now(timezone.utc))
    session.add(m)
    session.flush()
    session.add(MatchTeamStats(match_id=m.id, team_id=a.id, is_home=True, shots=10, source="football_data"))
    session.commit()
    session.add(MatchTeamStats(match_id=m.id, team_id=a.id, is_home=True, shots=11, source="football_data"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_foreign_keys_enforced_on_sqlite(session):
    session.add(Season(league_id=999, label="2026"))
    with pytest.raises(IntegrityError):
        session.commit()
