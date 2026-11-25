"""3단계: 기본 통계·피처 테스트. 핵심은 '미래 정보가 섞이지 않는가'."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from backend.features import stats
from backend.features.data import prepare
from backend.features.match_features import build_match_features

T0 = datetime(2025, 8, 1, 14, 0, tzinfo=timezone.utc)


def mk(rows):
    """(id, 일차, 홈, 원정, 홈골, 원정골[, 상태, xg_h, xg_a, 리그]) → DataFrame"""
    recs = []
    for r in rows:
        mid, day, h, a, hg, ag, *rest = r
        status = rest[0] if len(rest) > 0 else ("finished" if hg is not None else "scheduled")
        xh, xa = (rest[1], rest[2]) if len(rest) > 2 else (None, None)
        res = None if hg is None else ("H" if hg > ag else "A" if ag > hg else "D")
        recs.append({"match_id": mid, "league_key": rest[3] if len(rest) > 3 else "L", "season_label": "2025-26",
                     "kickoff_utc": T0 + timedelta(days=day), "home_id": h, "away_id": a,
                     "home_name": f"T{h}", "away_name": f"T{a}", "status": status, "hg": hg, "ag": ag,
                     "ht_hg": None if hg is None else min(hg, 1), "ht_ag": None if ag is None else min(ag, 1),
                     "result_90": res, "h_xg": xh, "a_xg": xa})
    return prepare(pd.DataFrame(recs))


def random_league(seed=0, n_teams=6, n_rounds=12):
    rng = np.random.default_rng(seed)
    rows, mid = [], 1
    for rnd in range(n_rounds):
        teams = rng.permutation(n_teams) + 1
        for k in range(0, n_teams, 2):
            day = rnd * 7 + (k // 4)  # 같은 날 같은 시각 경기가 여러 개 생기게
            rows.append((mid, day, int(teams[k]), int(teams[k + 1]), int(rng.poisson(1.5)), int(rng.poisson(1.1)),
                         "finished", float(rng.uniform(0, 3)), float(rng.uniform(0, 3))))
            mid += 1
    return mk(rows)


# ── 미래 정보 누출 ──

@pytest.mark.parametrize("seed", [0, 1, 2])
def test_features_do_not_change_when_future_results_change(seed):
    df = random_league(seed)
    full = build_match_features(df).set_index("match_id")
    cutoff = df["kickoff_utc"].iloc[len(df) // 2]
    tampered = df.copy()
    future = tampered["kickoff_utc"] >= cutoff  # 같은 시각 경기 결과도 바꾼다
    rng = np.random.default_rng(99)
    tampered.loc[future, "hg"] = rng.integers(0, 9, future.sum())
    tampered.loc[future, "ag"] = rng.integers(0, 9, future.sum())
    tampered.loc[future, "result_90"] = np.where(tampered.loc[future, "hg"] > tampered.loc[future, "ag"], "H",
                                                 np.where(tampered.loc[future, "hg"] < tampered.loc[future, "ag"], "A", "D"))
    tampered.loc[future, "h_xg"] = 9.9
    after = build_match_features(tampered).set_index("match_id")
    past_ids = df.loc[df["kickoff_utc"] <= cutoff, "match_id"]
    pd.testing.assert_frame_equal(full.loc[past_ids], after.loc[past_ids])
    # 반대로 미래 경기 피처는 실제로 달라져야 테스트가 의미 있다
    later_ids = df.loc[df["kickoff_utc"] > cutoff, "match_id"]
    assert not full.loc[later_ids].equals(after.loc[later_ids])


def test_features_do_not_change_when_future_matches_removed():
    df = random_league(3)
    full = build_match_features(df).set_index("match_id")
    cutoff = df["kickoff_utc"].iloc[30]
    part = build_match_features(df[df["kickoff_utc"] <= cutoff]).set_index("match_id")
    pd.testing.assert_frame_equal(full.loc[part.index], part)


def test_same_kickoff_matches_do_not_see_each_other():
    df = mk([(1, 0, 1, 2, 3, 0), (2, 0, 1, 3, 3, 0)])  # 데이터 오류로 같은 팀이 같은 시각 두 경기여도
    f = build_match_features(df).set_index("match_id")
    assert f.loc[2, "h_n_prev"] == 0 and np.isnan(f.loc[2, "h_form5_ppg"])


def test_own_result_not_in_own_features():
    df = mk([(1, 0, 1, 2, 5, 0), (2, 7, 1, 2, 0, 5)])
    f = build_match_features(df).set_index("match_id")
    assert np.isnan(f.loc[1, "h_gf5"])  # 첫 경기: 이전 기록 없음
    assert f.loc[2, "h_gf5"] == 5 and f.loc[2, "a_ga5"] == 5  # 둘째 경기는 첫 경기만 본다


def test_features_match_naive_recomputation():
    """빠른 누적 계산 결과가, 매 경기마다 '그 시각 이전 경기만 걸러서' 다시 계산한 값과 같아야 한다."""
    df = random_league(5)
    f = build_match_features(df).set_index("match_id")
    for _, r in df.iloc[::7].iterrows():
        for side, team in (("h", r["home_id"]), ("a", r["away_id"])):
            naive = stats.form(df, team, as_of=r["kickoff_utc"], n=5)
            got = f.loc[r["match_id"], f"{side}_form5_ppg"]
            assert (naive["points_per_game"] is None and np.isnan(got)) or got == pytest.approx(naive["points_per_game"])
            rd = stats.rest_days(df, team, r["kickoff_utc"])
            assert (rd is None and np.isnan(f.loc[r["match_id"], f"{side}_rest_days"])) or \
                f.loc[r["match_id"], f"{side}_rest_days"] == pytest.approx(rd)


def test_standings_as_of_ignores_later_and_same_time_matches():
    df = mk([(1, 0, 1, 2, 2, 0), (2, 7, 2, 1, 3, 0), (3, 7, 3, 4, 1, 1)])
    t = stats.standings(df, "L", "2025-26", as_of=T0 + timedelta(days=7)).set_index("team_id")
    assert t.loc[1, "points"] == 3 and t.loc[1, "played"] == 1 and t.loc[3, "played"] == 0


# ── 통계 값 ──

def test_standings_order_and_venue_split():
    df = mk([(1, 0, 1, 2, 2, 0), (2, 1, 3, 1, 1, 1), (3, 2, 2, 3, 0, 4), (4, 3, 4, 1, None, None)])
    t = stats.standings(df, "L", "2025-26")
    assert list(t["team_id"]) == [3, 1, 4, 2]  # 승점 4(득실+4), 4(득실+2), 0(득실 0, 경기 없음), 0(득실 -6)
    assert t.set_index("team_id").loc[4, "played"] == 0  # 예정 경기만 있는 팀도 표에 나온다
    home = stats.standings(df, "L", "2025-26", venue="home").set_index("team_id")
    assert home.loc[1, "points"] == 3 and home.loc[1, "played"] == 1


def test_form_uses_result_90_for_extra_time():
    df = mk([(1, 0, 1, 2, 2, 1)])
    df.loc[0, "result_90"] = "D"  # 연장 끝에 2-1 승리 → 90분 기준 무승부
    assert stats.form(df, 1)["results"] == "D"


def test_head_to_head():
    df = mk([(1, 0, 1, 2, 2, 0), (2, 7, 2, 1, 1, 1), (3, 14, 1, 3, 0, 1), (4, 21, 2, 1, 3, 1)])
    h = stats.head_to_head(df, 1, 2, as_of=T0 + timedelta(days=21))
    assert (h["games"], h["a_wins"], h["draws"], h["b_wins"], h["a_goals"], h["b_goals"]) == (2, 1, 1, 0, 3, 1)


def test_team_profile_rates_and_missing_xg():
    df = mk([(1, 0, 1, 2, 2, 1), (2, 7, 3, 1, 0, 0), (3, 14, 1, 4, 3, 2)])
    p = stats.team_profile(df, 1)
    assert p["games"] == 3
    assert p["over_2_5"] == pytest.approx(2 / 3) and p["btts"] == pytest.approx(2 / 3)
    assert p["clean_sheet"] == pytest.approx(1 / 3)
    assert p["xg_for"] is None and "goals_minus_xg" not in p  # xG 없는 리그 → None (화면에서 숨김)
    with_xg = mk([(1, 0, 1, 2, 2, 1, "finished", 1.5, 0.5)])
    assert stats.team_profile(with_xg, 1)["goals_minus_xg"] == pytest.approx(0.5)


def test_rest_days_and_congestion():
    df = mk([(1, 0, 1, 2, 1, 0), (2, 3, 1, 3, 1, 0, "finished", None, None, "CUP"), (3, 10, 1, 4, None, None)])
    as_of = T0 + timedelta(days=10)
    assert stats.rest_days(df, 1, as_of) == pytest.approx(7)  # 다른 대회 경기도 센다
    assert stats.matches_in_last(df, 1, as_of, days=14) == 2
    f = build_match_features(df).set_index("match_id")
    assert f.loc[3, "h_rest_days"] == pytest.approx(7) and f.loc[3, "h_games_14d"] == 2
