"""DB에 쌓인 데이터로 기본 통계를 터미널에 보여준다 (확인용).

    python -m backend.scripts.show_stats --league eng_premier_league
    python -m backend.scripts.show_stats --league kor_k_league_1 --team "Ulsan HD"
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from backend.db.init_db import make_engine, make_session_factory
from backend.features import stats
from backend.features.data import load_matches
from backend.features.match_features import build_match_features

KST = ZoneInfo("Asia/Seoul")


def pct(v):
    return "-" if v is None else f"{v * 100:.0f}%"


def num(v, d=2):
    return "-" if v is None else f"{v:.{d}f}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    ap.add_argument("--team", help="팀 이름 (없으면 1위 팀)")
    args = ap.parse_args(argv)

    with make_session_factory(make_engine())() as s:
        df = load_matches(s)
    lg = df[df["league_key"] == args.league]
    if lg.empty:
        print("해당 대회 경기가 DB에 없습니다 — 먼저 수집(backend.jobs.collect)을 실행하세요")
        return 1
    season = lg["season_label"].max() if lg["season_label"].str.contains("-").any() else str(lg["season_label"].astype(int).max())
    now = datetime.now(timezone.utc)

    table = stats.standings(df, args.league, season)
    print(f"\n## {args.league} {season} 순위표 (현재)\n")
    print(table[["rank", "team", "played", "won", "drawn", "lost", "gf", "ga", "gd", "points", "form"]].to_string(index=False))

    team_name = args.team or table.iloc[0]["team"]
    ids = lg.loc[lg["home_name"] == team_name, "home_id"]
    if ids.empty:
        print(f"\n팀 '{team_name}' 없음")
        return 1
    tid = int(ids.iloc[0])
    p = stats.team_profile(df, tid, league_key=args.league, season_label=season)
    f5 = stats.form(df, tid, n=5)
    print(f"\n## {team_name} (이번 시즌 리그 기준)\n")
    print(f"- 최근 5경기(모든 대회): {f5['results']}  승점 {f5['points']}  득실 {f5['gf']}-{f5['ga']}")
    print(f"- 경기당 득점 {num(p['goals_for'])} / 실점 {num(p['goals_against'])}  "
          f"(전반 {num(p['first_half_goals_for'])}, 후반 {num(p['second_half_goals_for'])})")
    print(f"- 오버2.5 {pct(p['over_2_5'])}  BTTS {pct(p['btts'])}  무실점 {pct(p['clean_sheet'])}")
    print(f"- 슈팅 {num(p['shots_for'], 1)}  유효 {num(p['sot_for'], 1)}  코너 {num(p['corners_for'], 1)}  "
          f"경고 {num(p['yellow_for'], 1)}  xG {num(p['xg_for'])}"
          + (f"  (득점-xG {p['goals_minus_xg']:+.2f})" if "goals_minus_xg" in p else ""))
    rd = stats.rest_days(df, tid, now)
    print(f"- 마지막 경기 후 {num(rd, 1)}일, 최근 14일 {stats.matches_in_last(df, tid, now, 14)}경기")

    upcoming = lg[(lg["status"] == "scheduled") & (lg["kickoff_utc"] >= now)].head(5)
    if not upcoming.empty:
        feats = build_match_features(df).set_index("match_id")
        print("\n## 다가오는 경기 피처 (경기 시작 이전 데이터만)\n")
        for _, r in upcoming.iterrows():
            fr = feats.loc[r["match_id"]]
            h2h = stats.head_to_head(df, r["home_id"], r["away_id"], as_of=r["kickoff_utc"], n=5)
            print(f"- {r['kickoff_utc'].tz_convert(KST):%m/%d %H:%M} KST  {r['home_name']} vs {r['away_name']}  | "
                  f"폼5 {fr['h_form5_ppg']:.2f} vs {fr['a_form5_ppg']:.2f}  휴식 {fr['h_rest_days']:.0f}일 vs {fr['a_rest_days']:.0f}일  "
                  f"H2H {h2h['a_wins']}승 {h2h['draws']}무 {h2h['b_wins']}패")
    return 0


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    sys.exit(main())
