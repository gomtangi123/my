"""Dixon-Coles 포아송 모델 (메인 모델).

  홈 득점 ~ Poisson(λ),  λ = exp(home + 공격[홈] + 수비[원정])
  원정 득점 ~ Poisson(μ), μ = exp(공격[원정] + 수비[홈])        (수비 값이 클수록 많이 실점)
  저득점 보정 τ(x, y; λ, μ, ρ): 0-0, 1-0, 0-1, 1-1 확률을 ρ로 조정 (Dixon & Coles 1997)
  시간 감쇠: 경기 가중치 w = exp(-ξ · 경과일수) — 최근 경기를 더 중요하게

학습은 두 단계로 한다 (빠르고 안정적):
  1) 가중 포아송 우도로 공격·수비·홈 어드밴티지 추정 (해석적 기울기 + L-BFGS)
     식별을 위해 공격 합 = 0 제약을 벌점항으로 걸고, 데이터 적은 팀이 튀지 않게 약한 L2 정규화
  2) 1)의 λ, μ를 고정하고 ρ를 1차원 최적화

학습 데이터는 반드시 '예측 시점 이전'에 끝난 경기만 넣는다 (fit 의 as_of 인자로 강제).
출력: 0~10골 스코어 확률 행렬 → 승/무/패, 오버/언더 2.5, 양팀득점, 가장 가능성 높은 스코어
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

MAX_GOALS = 10


@dataclass
class DCParams:
    xi: float = 0.0019  # 시간 감쇠 (반감기 약 365일)
    window_days: int = 730  # 이보다 오래된 경기는 쓰지 않음
    l2: float = 0.5  # 정규화 세기 (가중치 합 대비가 아니라 절대값)
    rho_bounds: tuple[float, float] = (-0.25, 0.25)


def tau(x, y, lam, mu, rho):
    """저득점 보정 계수 (배열 지원)."""
    t = np.ones(np.broadcast(x, y, lam, mu).shape)
    t = np.where((x == 0) & (y == 0), 1 - lam * mu * rho, t)
    t = np.where((x == 0) & (y == 1), 1 + lam * rho, t)
    t = np.where((x == 1) & (y == 0), 1 + mu * rho, t)
    t = np.where((x == 1) & (y == 1), 1 - rho, t)
    return t


class DixonColes:
    def __init__(self, params: DCParams = DCParams()) -> None:
        self.p = params
        self.teams: dict[int, int] = {}
        self.attack = self.defence = np.zeros(0)
        self.home = 0.0
        self.rho = 0.0
        self.fitted_at = None
        self.n_matches = 0

    # ── 학습 ──
    def fit(self, matches: pd.DataFrame, as_of) -> "DixonColes":
        """as_of 이전에 끝난 경기(정규 시간 결과)만으로 학습."""
        as_of = pd.Timestamp(as_of)
        m = matches[(matches["status"] == "finished") & matches["hg"].notna() & (matches["kickoff_utc"] < as_of)]
        m = m[m["decided_by"].isna() | (m["decided_by"] == "regular")]  # 연장 득점이 섞인 경기는 제외
        age = (as_of - m["kickoff_utc"]).dt.total_seconds() / 86400
        m = m[age <= self.p.window_days]
        age = age[age <= self.p.window_days]
        if len(m) < 20:
            raise ValueError(f"학습 경기가 너무 적음 ({len(m)}경기)")
        teams = pd.unique(pd.concat([m["home_id"], m["away_id"]]))
        self.teams = {int(t): i for i, t in enumerate(teams)}
        n = len(teams)
        hi = m["home_id"].map(self.teams).to_numpy()
        ai = m["away_id"].map(self.teams).to_numpy()
        x = m["hg"].to_numpy(float)
        y = m["ag"].to_numpy(float)
        neutral = m["neutral"].fillna(False).to_numpy(bool) if "neutral" in m else np.zeros(len(m), bool)
        hflag = (~neutral).astype(float)
        w = np.exp(-self.p.xi * age.to_numpy())
        l2, pen = self.p.l2, 100.0

        def f(theta):
            att, dfn, home = theta[:n], theta[n:2 * n], theta[2 * n]
            ll = home * hflag + att[hi] + dfn[ai]
            lm = att[ai] + dfn[hi]
            lam, mu = np.exp(ll), np.exp(lm)
            nll = np.sum(w * (lam - x * ll + mu - y * lm))
            s = att.sum()
            nll += l2 * (att @ att + dfn @ dfn) + pen * s * s
            r1, r2 = w * (lam - x), w * (mu - y)  # d nll / d log λ, d nll / d log μ
            g_att = np.bincount(hi, r1, n) + np.bincount(ai, r2, n) + 2 * l2 * att + 2 * pen * s
            g_def = np.bincount(ai, r1, n) + np.bincount(hi, r2, n) + 2 * l2 * dfn
            g_home = np.sum(r1 * hflag)
            return nll, np.concatenate([g_att, g_def, [g_home]])

        res = minimize(f, np.zeros(2 * n + 1), jac=True, method="L-BFGS-B")
        self.attack, self.defence, self.home = res.x[:n], res.x[n:2 * n], float(res.x[2 * n])
        lam = np.exp(self.home * hflag + self.attack[hi] + self.defence[ai])
        mu = np.exp(self.attack[ai] + self.defence[hi])

        def rho_nll(rho):
            t = tau(x, y, lam, mu, rho)
            return -np.sum(w * np.log(np.clip(t, 1e-10, None)))

        lo, hi_b = self.p.rho_bounds
        self.rho = float(minimize_scalar(rho_nll, bounds=(lo, hi_b), method="bounded").x)
        self.fitted_at, self.n_matches = as_of, len(m)
        # 학습 데이터에 없는 팀(승격팀 등)은 하위 25% 팀의 평균 전력으로 둔다
        strength = self.attack - self.defence
        weak = strength <= np.quantile(strength, 0.25)
        self._unseen = (float(self.attack[weak].mean()), float(self.defence[weak].mean()))
        return self

    def team_params(self, team_id: int) -> tuple[float, float, bool]:
        i = self.teams.get(int(team_id))
        if i is None:
            return self._unseen[0], self._unseen[1], False
        return float(self.attack[i]), float(self.defence[i]), True

    # ── 예측 ──
    def expected_goals(self, home_id: int, away_id: int, neutral: bool = False) -> tuple[float, float]:
        ah, dh, _ = self.team_params(home_id)
        aa, da, _ = self.team_params(away_id)
        home = 0.0 if neutral else self.home
        return float(np.exp(home + ah + da)), float(np.exp(aa + dh))

    def score_matrix(self, home_id: int, away_id: int, neutral: bool = False) -> np.ndarray:
        """[홈 득점, 원정 득점] 확률 행렬 (0~MAX_GOALS), 합 1로 정규화."""
        lam, mu = self.expected_goals(home_id, away_id, neutral)
        g = np.arange(MAX_GOALS + 1)
        mat = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
        xs, ys = np.meshgrid(g, g, indexing="ij")
        mat *= tau(xs, ys, lam, mu, self.rho)
        mat = np.clip(mat, 0, None)
        return mat / mat.sum()


def summarize_matrix(mat: np.ndarray) -> dict:
    """스코어 행렬 → 승/무/패, 오버/언더 2.5, 양팀득점, 가장 가능성 높은 스코어."""
    g = np.arange(mat.shape[0])
    total = g[:, None] + g[None, :]
    i, j = np.unravel_index(np.argmax(mat), mat.shape)
    return {
        "home_win": float(np.tril(mat, -1).sum()), "draw": float(np.trace(mat)), "away_win": float(np.triu(mat, 1).sum()),
        "over_2_5": float(mat[total > 2.5].sum()), "under_2_5": float(mat[total < 2.5].sum()),
        "btts": float(mat[1:, 1:].sum()),
        "most_likely_score": (int(i), int(j)), "most_likely_prob": float(mat[i, j]),
        "exp_home_goals": float((mat.sum(1) * g).sum()), "exp_away_goals": float((mat.sum(0) * g).sum()),
    }
