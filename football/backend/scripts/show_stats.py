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

from backend.config import load_leagues
from backend.db.init_db import make_engine, make_session_factory
from backend.db.team_names import display_name
from backend.features import stats
from backend.features.data import load_matches
from backend.features.match_features import build_match_features

KST = ZoneInfo("Asia/Seoul")
WDL_KO = str.maketrans({"W": "승", "D": "무", "L": "패"})


def pct(v):
    return "-" if v is None else f"{v * 100:.0f}%"


def num(v, d=2):
    return "-" if v is None else f"{v:.{d}f}"


def latest_season(labels: pd.Series) -> str:
    return max(labels.unique(), key=lambda s: int(str(s)[:4]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="대회 순위표와 팀 통계를 보여준다")
    ap.add_argument("--league", required=True, help="대회 key (config/leagues.yaml)")
    ap.add_argument("--team", help="팀 영문 이름 (없으면 1위 팀)")
    args = ap.parse_args(argv)
    league_name = {l.key: l.name_ko for l in load_leagues()}.get(args.league, args.league)

    with make_session_factory(make_engine())() as s:
        df = load_matches(s)
    lg = df[df["league_key"] == args.league] if not df.empty else df
    if lg.empty:
        print("해당 대회 경기가 DB에 없습니다 — 먼저 수집(python -m backend.jobs.collect)을 실행하세요")
        return 1
    season = latest_season(lg["season_label"])
    now = datetime.now(timezone.utc)

    table = stats.standings(df, args.league, season)
    view = pd.DataFrame({
        "순위": table["rank"],
        "팀": [display_name(n, k) for n, k in zip(table["team"], table["team_ko"])],
        "경기": table["played"], "승": table["won"], "무": table["drawn"], "패": table["lost"],
        "득점": table["gf"], "실점": table["ga"], "득실": table["gd"], "승점": table["points"],
        "최근5경기": table["form"].str.translate(WDL_KO),
    })
    print(f"\n## {league_name} {season} 시즌 순위표 (현재)\n")
    print(view.to_string(index=False))

    team_name = args.team or table.iloc[0]["team"]
    row = table[table["team"] == team_name]
    if row.empty:
        print(f"\n팀 '{team_name}' 을(를) 찾을 수 없습니다")
        return 1
    tid, label = int(row.iloc[0]["team_id"]), display_name(team_name, row.iloc[0]["team_ko"])
    p = stats.team_profile(df, tid, league_key=args.league, season_label=season)
    f5 = stats.form(df, tid, n=5)
    print(f"\n## {label} — 이번 시즌 리그 기준\n")
    print(f"- 최근 5경기(수집된 모든 대회): {f5['results'].translate(WDL_KO)}  승점 {f5['points']}  득실 {f5['gf']}-{f5['ga']}")
    print(f"- 경기당 득점 {num(p['goals_for'])} / 실점 {num(p['goals_against'])}  "
          f"(전반 득점 {num(p['first_half_goals_for'])}, 후반 득점 {num(p['second_half_goals_for'])})")
    print(f"- 2.5골 초과 {pct(p['over_2_5'])}  양팀 득점 {pct(p['btts'])}  무실점 {pct(p['clean_sheet'])}")
    extra = []
    for key, name, d in (("shots_for", "슈팅", 1), ("sot_for", "유효슈팅", 1), ("corners_for", "코너킥", 1),
                         ("yellow_for", "경고", 1), ("xg_for", "xG", 2)):
        if p[key] is not None:  # 제공되지 않는 지표는 표시하지 않는다
            extra.append(f"{name} {num(p[key], d)}")
    if "goals_minus_xg" in p:
        extra.append(f"득점−xG {p['goals_minus_xg']:+.2f}")
    print(f"- 경기당 {'  '.join(extra)}" if extra else "- 경기 통계: 이 대회는 제공되지 않음")
    rd = stats.rest_days(df, tid, now)
    print(f"- 마지막 경기 후 {num(rd, 1)}일 휴식, 최근 14일 {stats.matches_in_last(df, tid, now, 14)}경기")

    upcoming = lg[(lg["status"] == "scheduled") & (lg["kickoff_utc"] >= now)].head(6)
    if not upcoming.empty:
        feats = build_match_features(df).set_index("match_id")
        print("\n## 다가오는 경기 (경기 시작 이전 데이터만 사용한 피처)\n")
        for _, r in upcoming.iterrows():
            fr = feats.loc[r["match_id"]]
            h2h = stats.head_to_head(df, r["home_id"], r["away_id"], as_of=r["kickoff_utc"], n=5)
            home = display_name(r["home_name"], r.get("home_name_ko"))
            away = display_name(r["away_name"], r.get("away_name_ko"))
            print(f"- {r['kickoff_utc'].tz_convert(KST):%m월 %d일 %H:%M} (한국 시간)  {home} vs {away}\n"
                  f"    최근 5경기 경기당 승점 {fr['h_form5_ppg']:.2f} vs {fr['a_form5_ppg']:.2f} | "
                  f"휴식 {fr['h_rest_days']:.0f}일 vs {fr['a_rest_days']:.0f}일 | "
                  f"최근 맞대결 {h2h['games']}경기: 홈팀 {h2h['a_wins']}승 {h2h['draws']}무 {h2h['b_wins']}패")
    return 0


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    pd.set_option("display.unicode.east_asian_width", True)
    sys.exit(main())
