"""API 공통: DB 세션, 경기 DataFrame 캐시, 팀 표기(배지 색·약칭), KST 변환."""
from __future__ import annotations

import colorsys
import hashlib
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.db.schema import Prediction, Team
from backend.features.data import load_matches

KST = ZoneInfo("Asia/Seoul")
DISCLAIMER = ("이 예측은 과거 경기 기록을 바탕으로 한 통계 모델의 계산 결과이며, 참고용 정보입니다. "
              "경기 결과를 보장하지 않습니다.")
CACHE_TTL_SECONDS = 120


def to_kst(dt) -> str | None:
    if dt is None or (isinstance(dt, float) and pd.isna(dt)) or dt is pd.NaT:
        return None
    return pd.Timestamp(dt).tz_convert(KST).isoformat()


def badge_color(team_id: int, stored: str | None) -> str:
    """팀 컬러가 없으면 팀 ID로 정해지는 색을 만든다 (로고 대신 원형 배지)."""
    if stored:
        return stored
    h = int(hashlib.md5(str(team_id).encode()).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hls_to_rgb(h, 0.42, 0.55)
    return "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))


def short_name(name: str, stored: str | None) -> str:
    if stored:
        return stored
    skip = {"FC", "CF", "AFC", "SC", "FK", "SK", "CD", "AC", "AL", "EL", "1.", "SV"}
    cleaned = "".join(ch if ch.isalnum() else " " for ch in name)
    words = [w for w in cleaned.split() if w.upper() not in skip and not w.isdigit()] or cleaned.split() or [name]
    if len(words) >= 2:
        return (words[0][0] + words[1][:2]).upper()
    return words[0][:3].upper()


class DataCache:
    """경기·팀·예측 데이터를 메모리에 두고 일정 시간마다 다시 읽는다 (요청마다 DB 전체를 읽지 않도록)."""

    def __init__(self, session_factory: sessionmaker, ttl: float = CACHE_TTL_SECONDS) -> None:
        self.session_factory = session_factory
        self.ttl = ttl
        self._lock = threading.Lock()
        self._loaded_at = 0.0
        self.matches = pd.DataFrame()
        self.teams: dict[int, dict] = {}
        self.predictions = pd.DataFrame()
        self.pred_by_match: dict[int, list[dict]] = {}

    def get(self) -> "DataCache":
        with self._lock:
            if time.monotonic() - self._loaded_at > self.ttl:
                self._reload()
        return self

    def invalidate(self) -> None:
        self._loaded_at = 0.0

    def _reload(self) -> None:
        with self.session_factory() as s:
            self.matches = load_matches(s)
            self.teams = {
                t.id: {"id": t.id, "name": t.name, "name_ko": t.name_ko, "short_name": short_name(t.name, t.short_name),
                       "color": badge_color(t.id, t.color_primary), "country": t.country}
                for t in s.scalars(select(Team))
            }
            rows = s.execute(select(Prediction.match_id, Prediction.model, Prediction.kind, Prediction.p_home,
                                    Prediction.p_draw, Prediction.p_away, Prediction.p_over_2_5, Prediction.p_btts,
                                    Prediction.exp_home_goals, Prediction.exp_away_goals, Prediction.rho,
                                    Prediction.elo_home, Prediction.elo_away, Prediction.made_at)).mappings().all()
            self.predictions = pd.DataFrame(rows)
            self.pred_by_match = {}
            for r in rows:  # 경기별로 바로 찾을 수 있게 색인
                self.pred_by_match.setdefault(r["match_id"], []).append(dict(r))
        self._loaded_at = time.monotonic()

    def team(self, team_id: int) -> dict:
        return self.teams.get(int(team_id)) or {"id": int(team_id), "name": "?", "name_ko": None, "short_name": "?",
                                               "color": badge_color(int(team_id), None), "country": None}


def get_session(session_factory: sessionmaker):
    def _dep():
        s: Session = session_factory()
        try:
            yield s
        finally:
            s.close()
    return _dep


def now_utc() -> datetime:
    return datetime.now(tz=ZoneInfo("UTC"))
