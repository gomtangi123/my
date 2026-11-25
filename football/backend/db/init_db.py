"""DB 연결과 초기화.

DATABASE_URL 환경변수가 있으면 그걸 쓰고 (배포: postgresql+psycopg://...),
없으면 football/data/football.db (SQLite) 를 쓴다.

사용법 (football 폴더에서):
    python -m backend.db.init_db
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import FOOTBALL_ROOT, LeagueConfig, load_leagues
from backend.db.schema import Base, ExternalId, League


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    (FOOTBALL_ROOT / "data").mkdir(exist_ok=True)
    return f"sqlite:///{FOOTBALL_ROOT / 'data' / 'football.db'}"


def make_engine(url: str | None = None) -> Engine:
    engine = create_engine(url or database_url())
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite는 외래키 검사가 기본으로 꺼져 있다
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def sync_leagues(session: Session, leagues: list[LeagueConfig]) -> None:
    """leagues.yaml 내용을 leagues 테이블과 외부 ID 매핑에 반영 (추가·수정. 삭제는 enabled=False로)."""
    existing = {lg.key: lg for lg in session.scalars(select(League))}
    for cfg in leagues:
        lg = existing.get(cfg.key) or League(key=cfg.key)
        lg.name_ko, lg.type, lg.region, lg.timezone, lg.enabled = cfg.name_ko, cfg.type, cfg.region, cfg.timezone, cfg.enabled
        session.add(lg)
        session.flush()
        for source, ext in _external_league_ids(cfg).items():
            row = session.scalar(select(ExternalId).where(
                ExternalId.entity_type == "league", ExternalId.entity_id == lg.id, ExternalId.source == source))
            if row is None:
                session.add(ExternalId(entity_type="league", entity_id=lg.id, source=source, external_id=ext))
            else:
                row.external_id = ext
    configured = {c.key for c in leagues}
    for key, lg in existing.items():
        if key not in configured:
            lg.enabled = False  # 설정에서 빠진 대회는 지우지 않고 끈다 (과거 경기 데이터 보존)


def _external_league_ids(cfg: LeagueConfig) -> dict[str, str]:
    out = {}
    fd = cfg.sources.get("football_data") or {}
    if fd.get("code"):
        out["football_data"] = fd["code"]
    elif fd.get("extra_file"):
        out["football_data"] = f"{fd['extra_file']}:{fd.get('league_name', '')}"
    if (cfg.sources.get("thesportsdb") or {}).get("id"):
        out["thesportsdb"] = str(cfg.sources["thesportsdb"]["id"])
    if (cfg.sources.get("api_football") or {}).get("id"):
        out["api_football"] = str(cfg.sources["api_football"]["id"])
    return out


def init_db(url: str | None = None) -> Engine:
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as session:
        sync_leagues(session, load_leagues())
        session.commit()
    return engine


def main() -> int:
    engine = init_db()
    with make_session_factory(engine)() as s:
        leagues = s.scalars(select(League).order_by(League.region, League.id)).all()
        print(f"DB 초기화 완료: {engine.url.render_as_string(hide_password=True)}")
        print(f"테이블 {len(Base.metadata.tables)}개: {', '.join(sorted(Base.metadata.tables))}")
        print(f"대회 {len(leagues)}개 (활성 {sum(l.enabled for l in leagues)}개)")
        for lg in leagues:
            print(f"  [{'O' if lg.enabled else ' '}] {lg.region:6} {lg.type:6} {lg.name_ko}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
