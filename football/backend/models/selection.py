"""대회별 대표 모델 선택 — '더 나은 모델만 사이트에 반영'.

기본: 리그 = Dixon-Coles, 컵 = Elo.
다른 모델은 같은 경기(모든 후보가 예측한 경기)로 비교해 Log loss 가 기본보다 MIN_GAIN 이상 낮고,
비교 경기가 MIN_MATCHES 이상일 때만 대표로 바꾼다 (작은 차이·적은 표본에 흔들리지 않게).
결과는 data/models/selection.json — 예측 작업과 API가 읽는다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from backend.config import FOOTBALL_ROOT

SELECTION_FILE = FOOTBALL_ROOT / "data" / "models" / "selection.json"
MIN_GAIN = 0.003
MIN_MATCHES = 200
CANDIDATES = ("lightgbm", "dixon_coles_xg", "elo", "dixon_coles")
OUTCOMES = np.array(["H", "D", "A"])


def _ll(sub: pd.DataFrame) -> float:
    p = sub[["pH", "pD", "pA"]].to_numpy(float)
    y = (sub["result_90"].to_numpy()[:, None] == OUTCOMES[None, :])
    return float(-np.mean(np.log(np.clip((p * y).sum(axis=1), 1e-15, None))))


def select_models(preds: pd.DataFrame, league_types: dict[str, str]) -> dict:
    """preds: match_id, model, pH, pD, pA, league_key, result_90 (끝난 경기).

    1) Dixon-Coles·Elo·LightGBM 중 그 대회에서 예측이 있는 모델들이 '모두' 예측한 같은 경기로 비교한다
       (모델 성능 페이지의 표와 같은 기준 — 화면과 선택 결과가 어긋나지 않게).
    2) xG Dixon-Coles 는 표본이 작아 기본 모델과 둘만 비교한다.
    어느 쪽이든 기본 모델보다 MIN_GAIN 이상 좋고 비교 경기가 MIN_MATCHES 이상이어야 바꾼다.
    """
    out = {}
    core = ("dixon_coles", "elo", "lightgbm")
    for lk, g in preds[preds["result_90"].isin(OUTCOMES)].groupby("league_key"):
        default = "dixon_coles" if league_types.get(lk) == "league" else "elo"
        present = [m for m in core if (g["model"] == m).any()]
        choice, reason, comparisons, best_gain = default, "기본 모델", {}, 0.0
        if default in present:
            ids = set.intersection(*[set(g.loc[g["model"] == m, "match_id"]) for m in present])
            lls = {m: _ll(g[(g["model"] == m) & g["match_id"].isin(ids)]) for m in present} if ids else {}
            for m, ll in lls.items():
                if m == default:
                    continue
                gain = lls[default] - ll
                comparisons[m] = {"matches": len(ids), "log_loss": round(ll, 4), "baseline_log_loss": round(lls[default], 4),
                                  "gain": round(gain, 4)}
                if len(ids) >= MIN_MATCHES and gain >= MIN_GAIN and gain > best_gain:
                    choice, best_gain = m, gain
                    reason = f"{len(ids)}경기 비교에서 Log loss {gain:.4f} 개선"
            base_ids = set(g.loc[g["model"] == default, "match_id"])
            xg_ids = base_ids & set(g.loc[g["model"] == "dixon_coles_xg", "match_id"])
            if xg_ids:
                ll_b = _ll(g[(g["model"] == default) & g["match_id"].isin(xg_ids)])
                ll_x = _ll(g[(g["model"] == "dixon_coles_xg") & g["match_id"].isin(xg_ids)])
                gain = ll_b - ll_x
                comparisons["dixon_coles_xg"] = {"matches": len(xg_ids), "log_loss": round(ll_x, 4),
                                                 "baseline_log_loss": round(ll_b, 4), "gain": round(gain, 4)}
                if len(xg_ids) >= MIN_MATCHES and gain >= MIN_GAIN and gain > best_gain:
                    choice, best_gain = "dixon_coles_xg", gain
                    reason = f"{len(xg_ids)}경기 비교에서 Log loss {gain:.4f} 개선 (xG 있는 경기)"
        if choice == default and comparisons:
            reason = "다른 모델이 기준(경기 {}개 이상, Log loss {} 이상 개선)을 넘지 못함".format(MIN_MATCHES, MIN_GAIN)
        out[lk] = {"main": choice, "default": default, "reason": reason, "comparisons": comparisons}
    return out


def save_selection(sel: dict) -> None:
    SELECTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SELECTION_FILE.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                          "leagues": sel}, ensure_ascii=False, indent=1), encoding="utf-8")


def load_selection() -> dict[str, str]:
    """{대회 key: 대표 모델}. 파일이 없으면 빈 dict (기본 규칙 사용)."""
    if not SELECTION_FILE.exists():
        return {}
    return {k: v["main"] for k, v in json.loads(SELECTION_FILE.read_text(encoding="utf-8"))["leagues"].items()}
