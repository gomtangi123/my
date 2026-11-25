"""다가오는 경기 예측을 만들어 predictions 테이블(kind='live')에 저장한다.

    python -m backend.jobs.predict              # 앞으로 14일 경기
    python -m backend.jobs.predict --days 7

- 리그 경기: Dixon-Coles(메인, 스코어 행렬) + Elo
- 컵 대회(ACL): Elo만 (리그 간 경기라 Dixon-Coles 적용 불가)
- 모델은 '지금' 이전에 끝난 경기로만 학습한다.
- 이미 시작한 경기의 예측은 절대 고치지 않는다 (경기 전 예측 기록 보존).
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import load_leagues
from backend.db.init_db import init_db, make_session_factory
from backend.db.schema import Match, Prediction
from backend.features.data import load_matches
from backend.models.dixon_coles import DixonColes, summarize_matrix
from backend.models.elo import EloParams, OrderedLogit, run_elo

log = logging.getLogger("predict")
OUTCOMES = ("H", "D", "A")
ELO_BURN_IN = pd.Timedelta(days=180)


def upsert_prediction(session: Session, match_id: int, model: str, kind: str, now: datetime, **values) -> bool:
    m = session.get(Match, match_id)
    if kind == "live" and m.kickoff_utc <= now:
        return False  # 시작한 경기의 경기 전 예측은 고정
    row = session.scalar(select(Prediction).where(Prediction.match_id == match_id, Prediction.model == model,
                                                  Prediction.kind == kind))
    if row is None:
        row = Prediction(match_id=match_id, model=model, kind=kind)
        session.add(row)
    for k, v in values.items():
        setattr(row, k, None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v))
    row.made_at = now
    return True


def fit_elo_converters(df: pd.DataFrame, elo: pd.DataFrame, leagues: dict, now) -> dict[str, OrderedLogit]:
    d = df.merge(elo, on="match_id")
    fin = d[d["result_90"].isin(OUTCOMES) & (d["kickoff_utc"] < now)]
    fin = fin[fin["kickoff_utc"] >= fin["kickoff_utc"].min() + ELO_BURN_IN]
    pooled = OrderedLogit().fit(fin["elo_diff"], fin["result_90"])
    out = {}
    for key, lg in leagues.items():
        part = fin[fin["league_key"] == key]
        out[key] = OrderedLogit().fit(part["elo_diff"], part["result_90"]) if lg.type == "league" and len(part) >= 300 else pooled
    return out


def run(days: int = 14, now: datetime | None = None, session: Session | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    leagues = {l.key: l for l in load_leagues(enabled_only=True)}
    own = session is None
    if own:
        session = make_session_factory(init_db())()
    try:
        df = load_matches(session, list(leagues))
        target = df[(df["status"] == "scheduled") & (df["kickoff_utc"] > now) &
                    (df["kickoff_utc"] <= now + timedelta(days=days))]
        counts = {"dixon_coles": 0, "elo": 0}
        if target.empty:
            log.info("예측할 경기 없음")
            return counts
        elo = run_elo(df, EloParams()).set_index("match_id")
        conv = fit_elo_converters(df, elo.reset_index(), leagues, now)
        for key, group in target.groupby("league_key"):
            lg = leagues[key]
            dc = None
            if lg.type == "league":
                try:
                    dc = DixonColes().fit(df[df["league_key"] == key], as_of=now)
                except ValueError as e:
                    log.warning("[%s] Dixon-Coles 학습 불가: %s", lg.name_ko, e)
            for _, r in group.iterrows():
                e = elo.loc[r["match_id"]]
                ph, pdraw, pa = conv[key].predict([e["elo_diff"]])[0]
                counts["elo"] += upsert_prediction(session, r["match_id"], "elo", "live", now, p_home=ph, p_draw=pdraw,
                                                   p_away=pa, elo_home=e["elo_home"], elo_away=e["elo_away"])
                if dc is not None:
                    neutral = bool(r["neutral"])
                    s = summarize_matrix(dc.score_matrix(r["home_id"], r["away_id"], neutral))
                    lam, mu = dc.expected_goals(r["home_id"], r["away_id"], neutral)
                    counts["dixon_coles"] += upsert_prediction(
                        session, r["match_id"], "dixon_coles", "live", now, p_home=s["home_win"], p_draw=s["draw"],
                        p_away=s["away_win"], p_over_2_5=s["over_2_5"], p_btts=s["btts"], exp_home_goals=lam,
                        exp_away_goals=mu, rho=dc.rho)
            log.info("[%s] %d경기 예측", lg.name_ko, len(group))
        session.commit()
        return counts
    finally:
        if own:
            session.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="다가오는 경기 예측 생성")
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    c = run(args.days)
    log.info("저장: Dixon-Coles %d경기, Elo %d경기", c["dixon_coles"], c["elo"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
