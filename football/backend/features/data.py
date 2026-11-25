"""DB → pandas DataFrame (경기 한 줄에 홈·원정 통계까지).

통계·피처 계산은 모두 이 DataFrame 위에서 한다. 컬럼:
  match_id, league_key, league_type, region, season_label, kickoff_utc(UTC, tz-aware),
  home_id, away_id, home_name, away_name, home_name_ko, away_name_ko, status, hg, ag, ht_hg, ht_ag, result_90, decided_by, neutral,
  h_shots, a_shots, h_sot, a_sot, h_corners, a_corners, h_yellow, a_yellow, h_red, a_red, h_xg, a_xg
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from backend.db.schema import League, Match, MatchTeamStats, Season, Team

STAT_COLS = {"shots": "shots", "sot": "shots_on_target", "corners": "corners", "yellow": "yellow_cards",
             "red": "red_cards", "xg": "xg"}


def load_matches(session: Session, league_keys: list[str] | None = None) -> pd.DataFrame:
    H, A = aliased(Team), aliased(Team)
    q = (select(Match.id.label("match_id"), League.key.label("league_key"), League.type.label("league_type"),
                League.region, Season.label.label("season_label"), Match.kickoff_utc,
                Match.home_team_id.label("home_id"), Match.away_team_id.label("away_id"),
                H.name.label("home_name"), A.name.label("away_name"),
                H.name_ko.label("home_name_ko"), A.name_ko.label("away_name_ko"), Match.status,
                Match.home_goals.label("hg"), Match.away_goals.label("ag"),
                Match.ht_home_goals.label("ht_hg"), Match.ht_away_goals.label("ht_ag"),
                Match.result_90, Match.decided_by, Match.neutral_venue.label("neutral"))
         .join(Season, Match.season_id == Season.id).join(League, Season.league_id == League.id)
         .join(H, Match.home_team_id == H.id).join(A, Match.away_team_id == A.id))
    if league_keys:
        q = q.where(League.key.in_(league_keys))
    df = pd.DataFrame(session.execute(q).mappings().all())
    if df.empty:
        return df
    st = pd.DataFrame(session.execute(select(
        MatchTeamStats.match_id, MatchTeamStats.is_home, *[getattr(MatchTeamStats, c) for c in STAT_COLS.values()]
    ).where(MatchTeamStats.match_id.in_(df["match_id"].tolist()))).mappings().all())
    for side, flag in (("h", True), ("a", False)):
        part = st[st["is_home"] == flag] if not st.empty else pd.DataFrame(columns=["match_id", *STAT_COLS.values()])
        part = part.rename(columns={v: f"{side}_{k}" for k, v in STAT_COLS.items()}).drop(columns=["is_home"], errors="ignore")
        df = df.merge(part, on="match_id", how="left")
    return prepare(df)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """형 변환·정렬. 테스트에서 손으로 만든 DataFrame에도 같은 처리를 한다."""
    df = df.copy()
    df["kickoff_utc"] = pd.to_datetime(df["kickoff_utc"], utc=True)
    for c in ["hg", "ag", "ht_hg", "ht_ag"] + [f"{s}_{k}" for s in "ha" for k in STAT_COLS]:
        if c not in df:
            df[c] = pd.NA
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c, default in (("neutral", False), ("decided_by", None), ("league_type", "league"), ("region", None)):
        if c not in df:
            df[c] = default
    return df.sort_values(["kickoff_utc", "match_id"]).reset_index(drop=True)


def finished(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["status"] == "finished") & df["hg"].notna() & df["ag"].notna()]


def before(df: pd.DataFrame, as_of) -> pd.DataFrame:
    """as_of '이전'에 시작해 끝난 경기만. 같은 시각에 시작한 경기는 포함하지 않는다 (미래 정보 누출 방지)."""
    if as_of is None:
        return finished(df)
    as_of = pd.Timestamp(as_of)
    as_of = as_of.tz_localize("UTC") if as_of.tzinfo is None else as_of.tz_convert("UTC")
    f = finished(df)
    return f[f["kickoff_utc"] < as_of]


def team_rows(df: pd.DataFrame, team_id: int) -> pd.DataFrame:
    """한 팀 관점으로 펼친 경기 목록: gf, ga, ht_gf, ht_ga, is_home, opp_id, res(W/D/L, 90분 기준), 통계 for/against."""
    home = df[df["home_id"] == team_id]
    away = df[df["away_id"] == team_id]

    def side(part, me, op, is_home):
        out = pd.DataFrame({
            "match_id": part["match_id"], "kickoff_utc": part["kickoff_utc"], "league_key": part["league_key"],
            "season_label": part["season_label"], "is_home": is_home, "opp_id": part[f"{op[0]}_id_"],
            "gf": part[f"{me[1]}g"], "ga": part[f"{op[1]}g"],
            "ht_gf": part[f"ht_{me[1]}g"], "ht_ga": part[f"ht_{op[1]}g"],
            "neutral": part["neutral"],
        })
        r90 = part["result_90"]
        win, loss = ("H", "A") if is_home else ("A", "H")
        out["res"] = r90.map({win: "W", "D": "D", loss: "L"})
        for k in STAT_COLS:
            out[f"{k}_for"] = part[f"{me[0]}_{k}"]
            out[f"{k}_against"] = part[f"{op[0]}_{k}"]
        return out

    h = home.assign(**{"a_id_": home["away_id"]})
    a = away.assign(**{"h_id_": away["home_id"]})
    rows = pd.concat([side(h, ("h", "h"), ("a", "a"), True), side(a, ("a", "a"), ("h", "h"), False)])
    return rows.sort_values(["kickoff_utc", "match_id"]).reset_index(drop=True)
