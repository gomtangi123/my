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
from backend.models.dixon_coles import DCParams, DixonColes, summarize_matrix
from backend.models.ml_model import build_frame, load_final, predict_frame
from backend.models.selection import load_selection
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


def predict_lightgbm(session, df, elo, dc_live: pd.DataFrame, target: pd.DataFrame, leagues: dict, now) -> int:
    """저장된 최종 LightGBM 모델로 예측 (없으면 건너뜀). 피처는 모두 지금 이전 정보."""
    loaded = load_final()
    if loaded is None:
        return 0
    booster, meta = loaded
    types = {k: l.type for k, l in leagues.items()}
    frame = build_frame(df, elo, dc_live if not dc_live.empty else None, types)
    rows = frame[frame["match_id"].isin(set(target["match_id"]))]
    if rows.empty:
        return 0
    p = predict_frame(booster, meta, rows)
    n = 0
    for mid, (ph, pdraw, pa) in zip(rows["match_id"], p):
        n += upsert_prediction(session, int(mid), "lightgbm", "live", now, p_home=ph, p_draw=pdraw, p_away=pa)
    return n


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
        counts = {"dixon_coles": 0, "elo": 0, "lightgbm": 0, "dixon_coles_xg": 0}
        selection = load_selection()
        dc_live = []  # LightGBM 피처로 쓸 이번 Dixon-Coles 확률
        if target.empty:
            log.info("예측할 경기 없음")
            return counts
        elo = run_elo(df, EloParams()).set_index("match_id")
        conv = fit_elo_converters(df, elo.reset_index(), leagues, now)
        for key, group in target.groupby("league_key"):
            lg = leagues[key]
            dc = dc_xg = None
            if lg.type == "league":
                try:
                    dc = DixonColes().fit(df[df["league_key"] == key], as_of=now)
                except ValueError as e:
                    log.warning("[%s] Dixon-Coles 학습 불가: %s", lg.name_ko, e)
                if selection.get(key) == "dixon_coles_xg":  # 대표 모델로 선택된 리그만
                    try:
                        dc_xg = DixonColes(DCParams(target="xg", min_matches=60)).fit(df[df["league_key"] == key], as_of=now)
                    except ValueError as e:
                        log.warning("[%s] xG Dixon-Coles 학습 불가: %s", lg.name_ko, e)
            for _, r in group.iterrows():
                e = elo.loc[r["match_id"]]
                ph, pdraw, pa = conv[key].predict([e["elo_diff"]])[0]
                counts["elo"] += upsert_prediction(session, r["match_id"], "elo", "live", now, p_home=ph, p_draw=pdraw,
                                                   p_away=pa, elo_home=e["elo_home"], elo_away=e["elo_away"])
                for model, name in ((dc, "dixon_coles"), (dc_xg, "dixon_coles_xg")):
                    if model is None:
                        continue
                    neutral = bool(r["neutral"])
                    s = summarize_matrix(model.score_matrix(r["home_id"], r["away_id"], neutral))
                    lam, mu = model.expected_goals(r["home_id"], r["away_id"], neutral)
                    counts[name] += upsert_prediction(
                        session, r["match_id"], name, "live", now, p_home=s["home_win"], p_draw=s["draw"],
                        p_away=s["away_win"], p_over_2_5=s["over_2_5"], p_btts=s["btts"], exp_home_goals=lam,
                        exp_away_goals=mu, rho=model.rho)
                    if name == "dixon_coles":
                        dc_live.append({"match_id": r["match_id"], "pH": s["home_win"], "pD": s["draw"], "pA": s["away_win"]})
            log.info("[%s] %d경기 예측", lg.name_ko, len(group))
        counts["lightgbm"] = predict_lightgbm(session, df, elo.reset_index(), pd.DataFrame(dc_live), target, leagues, now)
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
    log.info("저장: %s", ", ".join(f"{k} {v}경기" for k, v in c.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
