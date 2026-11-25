"""LightGBM 승/무/패 모델.

피처 (모두 경기 시작 '이전' 정보)
- 3단계 경기 피처: 폼(5·10경기), 평균 득실, 홈/원정 폼, xG·슈팅, 오버2.5·BTTS 비율, 휴식일, 14·30일 경기 수, H2H
- Elo: 경기 전 레이팅·차이
- Dixon-Coles 확률: walk-forward 검증에서 '그 주 시작 전' 데이터로만 만든 예측 (live 예측에서는 지금 학습한 모델)
- 대회 (범주형), 컵 대회 여부, 중립 경기
배당은 쓰지 않는다.

검증: 매달 1일에 그 날짜 이전에 끝난 경기로만 다시 학습해 그 달 경기를 예측 (확장 윈도우 walk-forward).
조기 종료용 검증 세트는 학습 데이터 중 '가장 최근' 15% (시간 순서 유지, 랜덤 분할 없음).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from backend.config import FOOTBALL_ROOT
from backend.features.match_features import build_match_features

log = logging.getLogger("ml_model")
MODEL_DIR = FOOTBALL_ROOT / "data" / "models"
MODEL_FILE = MODEL_DIR / "lgbm.txt"
META_FILE = MODEL_DIR / "lgbm_meta.json"
OUTCOMES = np.array(["H", "D", "A"])
LABEL = {"H": 0, "D": 1, "A": 2}
MIN_TRAIN = 1500

PARAMS = dict(objective="multiclass", num_class=3, learning_rate=0.03, num_leaves=15, min_child_samples=60,
              feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, seed=7)


def build_frame(df: pd.DataFrame, elo: pd.DataFrame, dc_probs: pd.DataFrame | None, league_types: dict) -> pd.DataFrame:
    """경기 한 줄 = 피처 + 정답(result_90, 끝난 경기만). dc_probs: match_id, pH, pD, pA."""
    f = build_match_features(df).drop(columns=["kickoff_utc"])
    base = df[["match_id", "kickoff_utc", "league_key", "status", "result_90"]]
    out = base.merge(f, on="match_id").merge(elo[["match_id", "elo_home", "elo_away", "elo_diff"]], on="match_id", how="left")
    if dc_probs is not None and not dc_probs.empty:
        dc = dc_probs[["match_id", "pH", "pD", "pA"]].rename(columns={"pH": "dc_pH", "pD": "dc_pD", "pA": "dc_pA"})
        out = out.merge(dc, on="match_id", how="left")
    else:
        out[["dc_pH", "dc_pD", "dc_pA"]] = np.nan
    out["is_cup"] = out["league_key"].map(lambda k: league_types.get(k) == "cup").astype(int)
    out["neutral"] = out["neutral"].astype(int)
    out["league"] = pd.Categorical(out["league_key"], categories=sorted(league_types))
    for side in ("h", "a"):  # 최근 5경기 득실차
        out[f"{side}_gd5"] = out[f"{side}_gf5"] - out[f"{side}_ga5"]
    return out.sort_values(["kickoff_utc", "match_id"]).reset_index(drop=True)


def feature_columns(frame: pd.DataFrame) -> list[str]:
    drop = {"match_id", "kickoff_utc", "league_key", "status", "result_90"}
    return [c for c in frame.columns if c not in drop]


def _fit(train: pd.DataFrame, cols: list[str], num_boost_round: int | None = None) -> lgb.Booster:
    y = train["result_90"].map(LABEL).to_numpy()
    if num_boost_round is not None:
        return lgb.train(PARAMS, lgb.Dataset(train[cols], y, categorical_feature=["league"]), num_boost_round=num_boost_round)
    cut = int(len(train) * 0.85)  # 시간 순서상 마지막 15%로 조기 종료 판단
    dtr = lgb.Dataset(train[cols].iloc[:cut], y[:cut], categorical_feature=["league"])
    dva = lgb.Dataset(train[cols].iloc[cut:], y[cut:], categorical_feature=["league"], reference=dtr)
    return lgb.train(PARAMS, dtr, num_boost_round=2000, valid_sets=[dva],
                     callbacks=[lgb.early_stopping(100, verbose=False)])


def walk_forward(frame: pd.DataFrame, test_start: pd.Timestamp, log_fn=log.info) -> tuple[pd.DataFrame, list[int]]:
    """test_start 이후 끝난 경기를 월 단위로 예측. 반환: (예측 DataFrame[match_id, pH, pD, pA], 월별 best_iteration)."""
    cols = feature_columns(frame)
    done = frame[frame["result_90"].isin(OUTCOMES)]
    test = done[done["kickoff_utc"] >= test_start]
    months = test["kickoff_utc"].dt.tz_convert("UTC").dt.to_period("M")
    out, iters = [], []
    for period, block in test.groupby(months):
        start = pd.Timestamp(period.start_time).tz_localize("UTC")
        train = done[done["kickoff_utc"] < start]  # 그 달 1일 이전에 끝난 경기만
        if len(train) < MIN_TRAIN:
            continue
        booster = _fit(train, cols)
        iters.append(booster.best_iteration)
        p = booster.predict(block[cols], num_iteration=booster.best_iteration)
        out.append(pd.DataFrame({"match_id": block["match_id"].values, "pH": p[:, 0], "pD": p[:, 1], "pA": p[:, 2]}))
        log_fn(f"  LightGBM {period}: 학습 {len(train)}경기 → {len(block)}경기 예측 (트리 {booster.best_iteration}개)")
    return (pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["match_id", "pH", "pD", "pA"])), iters


def train_final(frame: pd.DataFrame, num_boost_round: int) -> lgb.Booster:
    """사이트용 최종 모델: 지금까지 끝난 모든 경기로 학습해 저장."""
    cols = feature_columns(frame)
    done = frame[frame["result_90"].isin(OUTCOMES)]
    booster = _fit(done, cols, num_boost_round=max(num_boost_round, 50))
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(MODEL_FILE))
    META_FILE.write_text(json.dumps({"features": cols, "trained_on": int(len(done)),
                                     "last_match_utc": str(done["kickoff_utc"].max()),
                                     "leagues": list(frame["league"].cat.categories)}, ensure_ascii=False, indent=1))
    return booster


def load_final() -> tuple[lgb.Booster, dict] | None:
    if not MODEL_FILE.exists() or not META_FILE.exists():
        return None
    return lgb.Booster(model_file=str(MODEL_FILE)), json.loads(META_FILE.read_text())


def predict_frame(booster: lgb.Booster, meta: dict, frame: pd.DataFrame) -> np.ndarray:
    x = frame.copy()
    x["league"] = pd.Categorical(x["league_key"], categories=meta["leagues"])
    return booster.predict(x[meta["features"]])
