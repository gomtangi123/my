"""Elo 레이팅 모델.

- 모든 대회를 하나의 레이팅 풀로 계산한다 (ACL처럼 다른 리그 팀끼리 만나는 경기도 같은 척도로 비교).
- 홈 어드밴티지: 홈팀 레이팅에 home_adv 점을 더해 기대 승률 계산 (중립 경기는 0).
- 시즌 간 평균 회귀: 팀이 새 시즌 첫 경기를 치를 때 레이팅을 그 대회 평균 쪽으로 season_regression 비율만큼 당긴다.
- 골 차 가중치: 큰 점수 차 승리는 레이팅을 더 많이 움직인다 (log(골차+1) 배수).
- 승/무/패 확률: 경기 전 레이팅 차이를 순서형 로지스틱 모델(ordered logit)로 H/D/A 확률로 바꾼다.
  이 변환의 계수는 '학습 기간' 경기의 경기 전 레이팅 차이로만 맞춘다 (평가 기간 정보 사용 금지).

경기 전 레이팅은 항상 그 경기 결과를 반영하기 '전' 값이다 → 미래 정보 누출 없음.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit


@dataclass
class EloParams:
    k: float = 20.0
    home_adv: float = 60.0
    init: float = 1500.0
    season_regression: float = 0.3
    goal_diff_weight: bool = True


def run_elo(df: pd.DataFrame, p: EloParams = EloParams()) -> pd.DataFrame:
    """시간 순서대로 레이팅을 갱신하며, 각 경기의 '경기 전' 레이팅과 차이를 돌려준다.

    반환 컬럼: match_id, elo_home, elo_away, elo_diff(홈 어드밴티지 포함, 홈 관점)
    같은 시각 경기들은 모두 계산한 뒤에 한꺼번에 갱신한다.
    """
    rating: dict[int, float] = {}
    last_season: dict[int, tuple[str, str]] = {}  # 팀 → (대회, 시즌) 마지막으로 뛴
    out = []
    for t, group in df.sort_values(["kickoff_utc", "match_id"]).groupby("kickoff_utc", sort=True):
        rows = group.to_dict("records")
        pre = {}
        for r in rows:
            for side in ("home_id", "away_id"):
                team = r[side]
                if team not in rating:
                    rating[team] = _league_mean(rating, last_season, r["league_key"], p.init)
                key = (r["league_key"], r["season_label"])
                prev = last_season.get(team)
                if prev is not None and prev[0] == r["league_key"] and prev[1] != r["season_label"]:
                    mean = _league_mean(rating, last_season, r["league_key"], p.init)
                    rating[team] = rating[team] + p.season_regression * (mean - rating[team])
                if r.get("league_type", "league") == "league" or team not in last_season:
                    last_season[team] = key
            ha = 0.0 if r.get("neutral") else p.home_adv
            pre[r["match_id"]] = (rating[r["home_id"]], rating[r["away_id"]], ha)
            out.append({"match_id": r["match_id"], "elo_home": rating[r["home_id"]], "elo_away": rating[r["away_id"]],
                        "elo_diff": rating[r["home_id"]] + ha - rating[r["away_id"]]})
        for r in rows:  # 결과 반영은 같은 시각 경기 계산이 모두 끝난 뒤
            if r.get("status") != "finished" or r.get("result_90") not in ("H", "D", "A"):
                continue
            rh, ra, ha = pre[r["match_id"]]
            expected = 1.0 / (1.0 + 10 ** (-(rh + ha - ra) / 400))
            score = {"H": 1.0, "D": 0.5, "A": 0.0}[r["result_90"]]
            mult = 1.0
            if p.goal_diff_weight and r.get("decided_by") in (None, "regular") and pd.notna(r.get("hg")):
                mult = float(np.log(abs(r["hg"] - r["ag"]) + 1) + 1) if r["hg"] != r["ag"] else 1.0
            delta = p.k * mult * (score - expected)
            rating[r["home_id"]] += delta
            rating[r["away_id"]] -= delta
    return pd.DataFrame(out)


def _league_mean(rating, last_season, league_key, default) -> float:
    vals = [rating[t] for t, (lg, _) in last_season.items() if lg == league_key and t in rating]
    return float(np.mean(vals)) if vals else default


class OrderedLogit:
    """레이팅 차이 d → P(원정승), P(무), P(홈승).  y* = b·d + e,  A: y*<c1,  D: c1≤y*<c2,  H: y*≥c2"""

    def __init__(self) -> None:
        self.b, self.c1, self.c2 = 0.005, -0.5, 0.5

    def fit(self, diff: np.ndarray, result: np.ndarray) -> "OrderedLogit":
        diff = np.asarray(diff, float)
        y = np.asarray(result)

        def nll(theta):
            b, c1, gap = theta
            c2 = c1 + np.exp(gap)
            pa = expit(c1 - b * diff)
            ph = 1 - expit(c2 - b * diff)
            pd_ = 1 - pa - ph
            p = np.where(y == "H", ph, np.where(y == "A", pa, pd_))
            return -np.sum(np.log(np.clip(p, 1e-12, None)))

        res = minimize(nll, x0=[0.005, -0.5, 0.0], method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-7, "fatol": 1e-9})
        b, c1, gap = res.x
        self.b, self.c1, self.c2 = b, c1, c1 + np.exp(gap)
        return self

    def predict(self, diff) -> np.ndarray:
        """[P(홈승), P(무), P(원정승)] (n, 3)"""
        diff = np.asarray(diff, float)
        pa = expit(self.c1 - self.b * diff)
        ph = 1 - expit(self.c2 - self.b * diff)
        return np.column_stack([ph, 1 - ph - pa, pa])
