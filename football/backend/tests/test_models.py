"""4단계: Elo·Dixon-Coles·평가 지표 테스트."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from backend.features.data import prepare
from backend.models.dixon_coles import DixonColes, summarize_matrix, tau
from backend.models.elo import EloParams, OrderedLogit, run_elo
from backend.models.evaluate import accuracy, brier, calibration_table, log_loss

T0 = datetime(2023, 8, 1, 14, 0, tzinfo=timezone.utc)


def simulate(n_teams=16, n_rounds=40, home=0.3, seed=0, rho=0.0):
    """알려진 공격·수비력으로 가짜 리그를 만든다."""
    rng = np.random.default_rng(seed)
    att = rng.normal(0, 0.3, n_teams)
    att -= att.mean()
    dfn = rng.normal(0, 0.25, n_teams)
    rows, mid = [], 1
    for rnd in range(n_rounds):
        perm = rng.permutation(n_teams)
        for k in range(0, n_teams, 2):
            h, a = perm[k], perm[k + 1]
            lam, mu = np.exp(home + att[h] + dfn[a]), np.exp(att[a] + dfn[h])
            hg, ag = rng.poisson(lam), rng.poisson(mu)
            res = "H" if hg > ag else "A" if ag > hg else "D"
            rows.append({"match_id": mid, "league_key": "L", "league_type": "league", "season_label": "2023-24",
                         "kickoff_utc": T0 + timedelta(days=4 * rnd, hours=k), "home_id": int(h) + 1,
                         "away_id": int(a) + 1, "home_name": f"T{h}", "away_name": f"T{a}", "status": "finished",
                         "hg": hg, "ag": ag, "result_90": res, "decided_by": "regular", "neutral": False})
            mid += 1
    return prepare(pd.DataFrame(rows)), att, dfn


# ── Dixon-Coles ──

def test_dc_recovers_known_strengths():
    df, att, dfn = simulate()
    m = DixonColes().fit(df, as_of=df["kickoff_utc"].max() + timedelta(days=1))
    est_att = np.array([m.team_params(t + 1)[0] for t in range(len(att))])
    est_def = np.array([m.team_params(t + 1)[1] for t in range(len(att))])
    assert np.corrcoef(att, est_att)[0, 1] > 0.85
    assert np.corrcoef(dfn, est_def)[0, 1] > 0.75
    assert m.home == pytest.approx(0.3, abs=0.1)


def test_dc_score_matrix_and_summary_consistent():
    df, _, _ = simulate(seed=1)
    m = DixonColes().fit(df, as_of=df["kickoff_utc"].max() + timedelta(days=1))
    mat = m.score_matrix(1, 2)
    assert mat.shape == (11, 11) and mat.sum() == pytest.approx(1.0) and (mat >= 0).all()
    s = summarize_matrix(mat)
    assert s["home_win"] + s["draw"] + s["away_win"] == pytest.approx(1.0)
    assert s["over_2_5"] + s["under_2_5"] == pytest.approx(1.0)
    assert mat[s["most_likely_score"]] == pytest.approx(mat.max())
    # 중립 경기는 홈 어드밴티지가 없어 홈팀 기대 득점이 줄어든다
    assert m.expected_goals(1, 2, neutral=True)[0] < m.expected_goals(1, 2)[0]


def test_dc_ignores_matches_after_as_of():
    df, _, _ = simulate(seed=2)
    cut = df["kickoff_utc"].iloc[len(df) // 2]
    a = DixonColes().fit(df, as_of=cut)
    tampered = df.copy()
    later = tampered["kickoff_utc"] >= cut
    tampered.loc[later, "hg"] = 9
    tampered.loc[later, "ag"] = 0
    b = DixonColes().fit(tampered, as_of=cut)
    assert np.allclose(a.attack, b.attack) and a.rho == pytest.approx(b.rho) and a.n_matches == b.n_matches


def test_dc_unseen_team_gets_weak_prior():
    df, _, _ = simulate(seed=3)
    m = DixonColes().fit(df, as_of=df["kickoff_utc"].max() + timedelta(days=1))
    att, dfn, seen = m.team_params(999)
    assert not seen and att - dfn < np.median(m.attack - m.defence)


def test_tau_matches_paper():
    assert tau(0, 0, 1.2, 0.8, 0.1) == pytest.approx(1 - 1.2 * 0.8 * 0.1)
    assert tau(1, 1, 1.2, 0.8, 0.1) == pytest.approx(0.9)
    assert tau(2, 1, 1.2, 0.8, 0.1) == 1.0


# ── Elo ──

def test_elo_pre_match_ratings_ignore_future():
    df, _, _ = simulate(seed=4, n_rounds=20)
    full = run_elo(df).set_index("match_id")
    cut = df["kickoff_utc"].iloc[100]
    t = df.copy()
    later = t["kickoff_utc"] >= cut
    t.loc[later, "result_90"] = "A"
    t.loc[later, "hg"], t.loc[later, "ag"] = 0, 5
    after = run_elo(t).set_index("match_id")
    ids = df.loc[df["kickoff_utc"] <= cut, "match_id"]
    pd.testing.assert_frame_equal(full.loc[ids], after.loc[ids])


def test_elo_zero_sum_home_adv_and_neutral():
    df = prepare(pd.DataFrame([
        {"match_id": 1, "league_key": "L", "season_label": "s", "kickoff_utc": T0, "home_id": 1, "away_id": 2,
         "home_name": "a", "away_name": "b", "status": "finished", "hg": 1, "ag": 0, "result_90": "H", "neutral": False},
        {"match_id": 2, "league_key": "L", "season_label": "s", "kickoff_utc": T0 + timedelta(days=7), "home_id": 1,
         "away_id": 2, "home_name": "a", "away_name": "b", "status": "scheduled", "hg": None, "ag": None,
         "result_90": None, "neutral": True},
    ]))
    r = run_elo(df, EloParams(k=20, home_adv=60)).set_index("match_id")
    assert r.loc[1, "elo_diff"] == pytest.approx(60)  # 첫 경기: 동일 레이팅 + 홈 어드밴티지
    assert r.loc[2, "elo_home"] + r.loc[2, "elo_away"] == pytest.approx(3000)  # 주고받은 점수 합 0
    assert r.loc[2, "elo_home"] > 1500
    assert r.loc[2, "elo_diff"] == pytest.approx(r.loc[2, "elo_home"] - r.loc[2, "elo_away"])  # 중립: 홈 이점 없음


def test_ordered_logit_fits_and_is_monotonic():
    rng = np.random.default_rng(0)
    d = rng.normal(0, 150, 3000)
    latent = 0.006 * d + rng.logistic(size=d.size)
    y = np.where(latent > 0.6, "H", np.where(latent < -0.6, "A", "D"))
    ol = OrderedLogit().fit(d, y)
    assert ol.b == pytest.approx(0.006, rel=0.15)
    p = ol.predict([-300, 0, 300])
    assert np.allclose(p.sum(axis=1), 1) and p[0, 0] < p[1, 0] < p[2, 0] and p[0, 2] > p[2, 2]


# ── 지표 ──

def test_metrics():
    y = np.array(["H", "D", "A"])
    perfect = np.eye(3)
    assert log_loss(perfect, y) == pytest.approx(0) and brier(perfect, y) == 0 and accuracy(perfect, y) == 1
    home_always = np.tile([1.0, 0, 0], (3, 1))
    assert np.isinf(log_loss(home_always, y)) and brier(home_always, y) == pytest.approx(4 / 3)
    uniform = np.full((3, 3), 1 / 3)
    assert log_loss(uniform, y) == pytest.approx(np.log(3)) and brier(uniform, y) == pytest.approx(2 / 3)
    t = calibration_table(uniform, y, bins=10)
    assert len(t) == 1 and t.iloc[0]["실제 비율"] == pytest.approx(1 / 3) and t.iloc[0]["건수"] == 9
