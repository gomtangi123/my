"""기본 통계 (화면 표시용). 모든 함수는 as_of 시각 '이전'에 끝난 경기만 쓴다 — as_of=None이면 지금까지 전부.

- 순위표 (전체/홈/원정), 최근 폼, 상대 전적(H2H)
- 오버/언더 2.5, 양팀득점(BTTS), 무실점 비율, 전·후반 득점, 코너·카드·슈팅·xG 평균
- 휴식일, 최근 N일 경기 수

데이터 한계: 무료 소스에는 골 시간 정보가 없어서 '15분 단위 득점'과 '선제골 시 승률'은 계산할 수 없다.
대신 전반/후반 득점을 제공한다 (하프타임 스코어가 있는 유럽 리그만). 골 시간 데이터가 생기면 추가한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend.features.data import STAT_COLS, before, team_rows

POINTS = {"W": 3, "D": 1, "L": 0}


DEFAULT_TIEBREAK = ["points", "gd", "gf"]


def _table(m: pd.DataFrame, teams, venue: str, names: dict, names_ko: dict) -> pd.DataFrame:
    rows = []
    for t in teams:
        tr = team_rows(m, t)
        if venue != "all":
            tr = tr[tr["is_home"] == (venue == "home")]
        res = pd.Series(np.where(tr["gf"] > tr["ga"], "W", np.where(tr["gf"] == tr["ga"], "D", "L")), index=tr.index)
        rows.append({
            "team_id": t, "team": names.get(t), "team_ko": names_ko.get(t), "played": len(tr),
            "won": int((res == "W").sum()), "drawn": int((res == "D").sum()), "lost": int((res == "L").sum()),
            "gf": int(tr["gf"].sum()), "ga": int(tr["ga"].sum()),
            "points": int(res.map(POINTS).sum()), "form": "".join(res.tail(5)),
        })
    table = pd.DataFrame(rows, columns=["team_id", "team", "team_ko", "played", "won", "drawn", "lost", "gf", "ga", "points", "form"])
    table["gd"] = table["gf"] - table["ga"]
    return table


def _sort(table: pd.DataFrame, tiebreak: list[str]) -> pd.DataFrame:
    keys = list(tiebreak) + ["team"]
    return table.sort_values(keys, ascending=[False] * len(tiebreak) + [True]).reset_index(drop=True)


def split_groups(season_matches: pd.DataFrame, as_of, after_games: int, top: int, tiebreak: list[str]) -> dict | None:
    """스플릿 리그: 팀마다 시즌 경기를 시간 순으로 세어 after_games 번째까지를 정규 라운드로 본다
    (소스의 라운드 번호는 믿지 않는다). 모든 팀이 정규 라운드를 마쳤으면 그 시점 상위 top 팀 = A, 나머지 = B."""
    m = season_matches.sort_values(["kickoff_utc", "match_id"])
    count: dict = {}
    regular_ids = []
    for r in m[["match_id", "home_id", "away_id"]].itertuples(index=False):
        ch, ca = count.get(r.home_id, 0), count.get(r.away_id, 0)
        if ch < after_games and ca < after_games:
            regular_ids.append(r.match_id)
        count[r.home_id], count[r.away_id] = ch + 1, ca + 1
    reg = before(m[m["match_id"].isin(regular_ids)], as_of)
    teams = pd.unique(pd.concat([m["home_id"], m["away_id"]]))
    played = {t: len(team_rows(reg, t)) for t in teams}
    if not played or min(played.values()) < after_games:
        return None  # 아직 정규 라운드가 끝나지 않음
    pre = _sort(_table(reg, teams, "all", {t: str(t) for t in teams}, {}), tiebreak)
    top_ids = set(pre["team_id"].head(top))
    return {t: ("A" if t in top_ids else "B") for t in teams}


def standings(df: pd.DataFrame, league_key: str, season_label: str, as_of=None, venue: str = "all",
              rules: dict | None = None) -> pd.DataFrame:
    """순위표. 리그 경기는 연장이 없으므로 실제 스코어로 승점 계산. venue: all/home/away.

    rules (config/leagues.yaml 의 standings): tiebreak 순서(기본 승점→득실차→다득점),
    split 이 있으면 정규 라운드 후 상위 그룹(A)이 하위 그룹(B)보다 항상 위 (venue=all 일 때만).
    """
    rules = rules or {}
    tiebreak = rules.get("tiebreak") or DEFAULT_TIEBREAK
    season = df[(df["league_key"] == league_key) & (df["season_label"] == season_label)]
    m = before(season, as_of)
    teams = pd.unique(pd.concat([season[c] for c in ("home_id", "away_id")]))
    names = dict(zip(df["home_id"], df["home_name"])) | dict(zip(df["away_id"], df["away_name"]))
    names_ko = {}
    if "home_name_ko" in df:
        names_ko = dict(zip(df["home_id"], df["home_name_ko"])) | dict(zip(df["away_id"], df["away_name_ko"]))
    table = _sort(_table(m, teams, venue, names, names_ko), tiebreak)
    table["group"] = None
    split = rules.get("split")
    if split and venue == "all":
        groups = split_groups(season, as_of, int(split["after_games"]), int(split["top"]), tiebreak)
        if groups:
            table["group"] = table["team_id"].map(groups)
            table = table.sort_values("group", kind="stable").reset_index(drop=True)  # A 먼저, 그룹 안 순서는 유지
    table.insert(0, "rank", range(1, len(table) + 1))
    return table


def form(df: pd.DataFrame, team_id: int, as_of=None, n: int = 5, venue: str = "all") -> dict:
    """최근 n경기 폼 (90분 결과 기준, 모든 대회 포함)."""
    tr = team_rows(before(df, as_of), team_id)
    if venue != "all":
        tr = tr[tr["is_home"] == (venue == "home")]
    last = tr.tail(n)
    return {
        "results": "".join(last["res"].fillna("?")),
        "points": int(last["res"].map(POINTS).fillna(0).sum()),
        "points_per_game": float(last["res"].map(POINTS).mean()) if len(last) else None,
        "gf": int(last["gf"].sum()), "ga": int(last["ga"].sum()), "games": len(last),
    }


def head_to_head(df: pd.DataFrame, team_a: int, team_b: int, as_of=None, n: int = 10) -> dict:
    tr = team_rows(before(df, as_of), team_a)
    tr = tr[tr["opp_id"] == team_b].tail(n)
    return {
        "games": len(tr), "a_wins": int((tr["res"] == "W").sum()), "draws": int((tr["res"] == "D").sum()),
        "b_wins": int((tr["res"] == "L").sum()), "a_goals": int(tr["gf"].sum()), "b_goals": int(tr["ga"].sum()),
        "matches": tr[["match_id", "kickoff_utc", "is_home", "gf", "ga"]].to_dict("records"),
    }


def _rate(mask: pd.Series) -> float | None:
    return float(mask.mean()) if len(mask) else None


def _avg(s: pd.Series) -> float | None:
    s = s.dropna()
    return float(s.mean()) if len(s) else None  # 데이터가 없으면 None → 화면에서 숨김


def team_profile(df: pd.DataFrame, team_id: int, as_of=None, last_n: int | None = None,
                 league_key: str | None = None, season_label: str | None = None) -> dict:
    """오버/언더·BTTS·무실점·전후반 득점·코너·카드·슈팅·xG 평균. 제공되지 않는 지표는 None."""
    data = before(df, as_of)
    if league_key:
        data = data[data["league_key"] == league_key]
    if season_label:
        data = data[data["season_label"] == season_label]
    tr = team_rows(data, team_id)
    if last_n:
        tr = tr.tail(last_n)
    total = tr["gf"] + tr["ga"]
    out = {
        "games": len(tr),
        "over_2_5": _rate(total > 2.5), "under_2_5": _rate(total < 2.5),
        "btts": _rate((tr["gf"] > 0) & (tr["ga"] > 0)),
        "clean_sheet": _rate(tr["ga"] == 0), "failed_to_score": _rate(tr["gf"] == 0),
        "goals_for": _avg(tr["gf"]), "goals_against": _avg(tr["ga"]),
        "first_half_goals_for": _avg(tr["ht_gf"]), "second_half_goals_for": _avg(tr["gf"] - tr["ht_gf"]),
        "first_half_goals_against": _avg(tr["ht_ga"]), "second_half_goals_against": _avg(tr["ga"] - tr["ht_ga"]),
    }
    for k in STAT_COLS:
        out[f"{k}_for"] = _avg(tr[f"{k}_for"])
        out[f"{k}_against"] = _avg(tr[f"{k}_against"])
    if out["xg_for"] is not None:
        xg_games = tr[tr["xg_for"].notna()]
        out["goals_minus_xg"] = float((xg_games["gf"] - xg_games["xg_for"]).mean())
    return out


def home_away_split(df: pd.DataFrame, team_id: int, league_key: str, season_label: str, as_of=None,
                    rules: dict | None = None) -> dict:
    return {v: standings(df, league_key, season_label, as_of, venue=v, rules=rules).set_index("team_id").loc[team_id].to_dict()
            for v in ("home", "away")}


def rest_days(df: pd.DataFrame, team_id: int, as_of) -> float | None:
    """as_of 직전 경기 이후 지난 일수 (모든 대회). 이전 경기가 없으면 None."""
    tr = team_rows(before(df, as_of), team_id)
    if tr.empty:
        return None
    return (pd.Timestamp(as_of).tz_convert("UTC") - tr["kickoff_utc"].iloc[-1]).total_seconds() / 86400


def matches_in_last(df: pd.DataFrame, team_id: int, as_of, days: int = 14) -> int:
    tr = team_rows(before(df, as_of), team_id)
    as_of = pd.Timestamp(as_of).tz_convert("UTC")
    return int((tr["kickoff_utc"] >= as_of - pd.Timedelta(days=days)).sum())
