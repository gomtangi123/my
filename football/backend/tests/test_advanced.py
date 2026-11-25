"""8단계: LightGBM walk-forward 누출 검사, 대표 모델 선택 규칙."""
import numpy as np
import pandas as pd
import pytest

from backend.models import ml_model
from backend.models.elo import run_elo
from backend.models.selection import MIN_GAIN, MIN_MATCHES, select_models
from backend.tests.test_models import simulate


@pytest.fixture
def small_train(monkeypatch):
    monkeypatch.setattr(ml_model, "MIN_TRAIN", 150)


def frame_for(df):
    return ml_model.build_frame(df, run_elo(df), None, {"L": "league"})


def test_lightgbm_month_predictions_ignore_later_results(small_train):
    df, _, _ = simulate(n_teams=12, n_rounds=60, seed=11)
    start = df["kickoff_utc"].iloc[len(df) // 3]
    full, _ = ml_model.walk_forward(frame_for(df), start, log_fn=lambda *_: None)
    assert not full.empty
    # 실제로 예측된 첫 달을 찾고, 그 다음 달부터의 결과를 모두 바꾼다
    kick = df.set_index("match_id").loc[full["match_id"], "kickoff_utc"]
    first_month = kick.min().tz_convert("UTC").to_period("M")
    month_end = (first_month + 1).start_time.tz_localize("UTC")
    t = df.copy()
    later = t["kickoff_utc"] >= month_end
    t.loc[later, ["hg", "ag", "result_90"]] = [0, 4, "A"]
    after, _ = ml_model.walk_forward(frame_for(t), start, log_fn=lambda *_: None)
    ids = kick[kick < month_end].index
    assert len(ids) > 0
    pd.testing.assert_frame_equal(full.set_index("match_id").loc[ids], after.set_index("match_id").loc[ids])
    # 반대로 바뀐 결과로 학습한 다음 달 예측은 달라져야 테스트가 의미 있다
    later_ids = kick[kick >= (first_month + 2).start_time.tz_localize("UTC")].index
    if len(later_ids):
        assert not np.allclose(full.set_index("match_id").loc[later_ids].to_numpy(),
                               after.set_index("match_id").loc[later_ids].to_numpy())
    assert np.allclose(full[["pH", "pD", "pA"]].sum(axis=1), 1)


def test_lightgbm_needs_minimum_training_data():
    df, _, _ = simulate(n_teams=8, n_rounds=10, seed=3)
    preds, iters = ml_model.walk_forward(frame_for(df), df["kickoff_utc"].iloc[20], log_fn=lambda *_: None)
    assert preds.empty and iters == []  # 학습 경기 부족(1500 미만)이면 예측하지 않는다


def _preds(model, n, p_correct, league="L", start_id=0):
    """n 경기, 실제 결과는 모두 H. 모델은 H에 p_correct 확률."""
    rest = (1 - p_correct) / 2
    return pd.DataFrame({"match_id": range(start_id, start_id + n), "model": model, "pH": p_correct, "pD": rest,
                         "pA": rest, "league_key": league, "result_90": "H"})


def test_selection_switches_only_with_enough_gain_and_matches():
    n = MIN_MATCHES + 50
    base = _preds("dixon_coles", n, 0.50)
    better = _preds("lightgbm", n, 0.53)  # log loss 차이 ≈ 0.058
    sel = select_models(pd.concat([base, better]), {"L": "league"})
    assert sel["L"]["main"] == "lightgbm" and sel["L"]["comparisons"]["lightgbm"]["gain"] >= MIN_GAIN
    tiny = _preds("lightgbm", n, 0.5005)  # 개선이 기준보다 작음
    assert select_models(pd.concat([base, tiny]), {"L": "league"})["L"]["main"] == "dixon_coles"
    few = _preds("lightgbm", MIN_MATCHES - 1, 0.6)  # 표본이 적음
    assert select_models(pd.concat([base, few]), {"L": "league"})["L"]["main"] == "dixon_coles"


def test_selection_default_for_cup_is_elo():
    sel = select_models(_preds("elo", 10, 0.5, league="C"), {"C": "cup"})
    assert sel["C"]["main"] == "elo" and sel["C"]["default"] == "elo"


def test_selection_compares_all_models_on_same_matches():
    """선택은 모든 모델이 예측한 같은 경기로 비교한다 — Elo가 그 경기들에서 가장 좋으면 Elo."""
    n = MIN_MATCHES + 100
    dc = _preds("dixon_coles", n + 300, 0.50)
    elo = _preds("elo", n + 300, 0.56)
    lgbm = _preds("lightgbm", n, 0.54, start_id=300)  # 일부 경기만 예측
    sel = select_models(pd.concat([dc, elo, lgbm]), {"L": "league"})
    assert sel["L"]["main"] == "elo"
    assert {v["matches"] for v in sel["L"]["comparisons"].values()} == {n}
