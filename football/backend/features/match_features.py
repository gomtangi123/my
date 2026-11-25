"""예측 모델용 경기별 피처. 경기 시작 시점 '이전' 데이터만 쓴다.

구현 방식 (누출 방지가 구조적으로 보장되게):
  경기를 킥오프 시각 순서로 훑으면서, 같은 시각에 시작하는 경기 묶음마다
    1) 먼저 그 묶음의 모든 경기 피처를 '지금까지 쌓인 기록'으로 계산하고
    2) 그 다음에야 묶음 안의 끝난 경기 결과를 기록에 추가한다.
  → 어떤 경기의 피처도 자기 자신이나 같은 시각·이후 경기의 결과를 볼 수 없다.

피처 (홈 h_, 원정 a_ 접두어)
  form5_ppg, form10_ppg      최근 5·10경기 경기당 승점 (모든 대회, 90분 결과)
  gf5, ga5, gf10, ga10       최근 5·10경기 평균 득점·실점
  venue_form5_ppg            홈팀은 최근 홈 5경기, 원정팀은 최근 원정 5경기
  xg5_for, xg5_against       최근 5경기 평균 xG (xG 있는 경기만, 없으면 NaN)
  shots5_for, sot5_for       최근 5경기 평균 슈팅·유효슈팅
  over25_10, btts_10         최근 10경기 오버 2.5·양팀득점 비율
  rest_days                  직전 경기 이후 일수
  games_14d, games_30d       최근 14·30일 경기 수
  n_prev                     이전 경기 수 (데이터가 적은 팀 구분용)
공통: h2h_n, h2h_home_ppg (최근 5번 맞대결에서 홈팀 관점 경기당 승점), neutral
"""
from __future__ import annotations

from collections import defaultdict, deque

import numpy as np
import pandas as pd

from backend.features.data import finished

PTS = {"W": 3, "D": 1, "L": 0}
HIST = 30  # 팀별로 보관하는 최근 경기 수


def _mean(vals) -> float:
    vals = [v for v in vals if v is not None and not (isinstance(v, float) and np.isnan(v))]
    return float(np.mean(vals)) if vals else np.nan


class _TeamHistory:
    def __init__(self) -> None:
        self.games: deque = deque(maxlen=HIST)  # dict: t, res, gf, ga, home, xgf, xga, shots, sot
        self.count = 0

    def add(self, g: dict) -> None:
        self.games.append(g)
        self.count += 1

    def last(self, n: int, home: bool | None = None) -> list[dict]:
        gs = [g for g in self.games if home is None or g["home"] == home]
        return gs[-n:]


def _team_feats(h: _TeamHistory, t: pd.Timestamp, is_home: bool) -> dict:
    l5, l10 = h.last(5), h.last(10)
    prev_t = h.games[-1]["t"] if h.games else None
    return {
        "form5_ppg": _mean([PTS[g["res"]] for g in l5]),
        "form10_ppg": _mean([PTS[g["res"]] for g in l10]),
        "gf5": _mean([g["gf"] for g in l5]), "ga5": _mean([g["ga"] for g in l5]),
        "gf10": _mean([g["gf"] for g in l10]), "ga10": _mean([g["ga"] for g in l10]),
        "venue_form5_ppg": _mean([PTS[g["res"]] for g in h.last(5, home=is_home)]),
        "xg5_for": _mean([g["xgf"] for g in l5]), "xg5_against": _mean([g["xga"] for g in l5]),
        "shots5_for": _mean([g["shots"] for g in l5]), "sot5_for": _mean([g["sot"] for g in l5]),
        "over25_10": _mean([float(g["gf"] + g["ga"] > 2.5) for g in l10]),
        "btts_10": _mean([float(g["gf"] > 0 and g["ga"] > 0) for g in l10]),
        "rest_days": (t - prev_t).total_seconds() / 86400 if prev_t is not None else np.nan,
        "games_14d": sum(1 for g in h.games if t - g["t"] <= pd.Timedelta(days=14)),
        "games_30d": sum(1 for g in h.games if t - g["t"] <= pd.Timedelta(days=30)),
        "n_prev": h.count,
    }


def _val(row, col):
    v = row.get(col)
    return None if v is None or pd.isna(v) else float(v)


def build_match_features(df: pd.DataFrame) -> pd.DataFrame:
    """df(load_matches 결과)의 모든 경기(끝난 경기·예정 경기)에 대해 피처를 만든다."""
    hist: dict[int, _TeamHistory] = defaultdict(_TeamHistory)
    h2h: dict[tuple[int, int], deque] = defaultdict(lambda: deque(maxlen=5))  # (작은 id, 큰 id) → (홈id, 결과90)
    done_ids = set(finished(df)["match_id"])
    out = []
    for t, group in df.sort_values(["kickoff_utc", "match_id"]).groupby("kickoff_utc", sort=True):
        rows = group.to_dict("records")
        # 1) 피처 계산 — 이 시각 이전 기록만 사용
        for r in rows:
            hid, aid = r["home_id"], r["away_id"]
            feat = {"match_id": r["match_id"], "kickoff_utc": t, "neutral": bool(r.get("neutral") or False)}
            feat |= {f"h_{k}": v for k, v in _team_feats(hist[hid], t, True).items()}
            feat |= {f"a_{k}": v for k, v in _team_feats(hist[aid], t, False).items()}
            past = h2h[(min(hid, aid), max(hid, aid))]
            pts = []
            for home_of_that, r90 in past:
                res_for_home = {"H": "W", "A": "L", "D": "D"}[r90] if home_of_that == hid else {"H": "L", "A": "W", "D": "D"}[r90]
                pts.append(PTS[res_for_home])
            feat["h2h_n"] = len(pts)
            feat["h2h_home_ppg"] = _mean(pts)
            out.append(feat)
        # 2) 그 다음에 이 시각 경기 결과를 기록에 추가
        for r in rows:
            if r["match_id"] not in done_ids or r.get("result_90") not in ("H", "D", "A"):
                continue
            r90 = r["result_90"]
            for me, op, is_home in (("h", "a", True), ("a", "h", False)):
                res = "D" if r90 == "D" else ("W" if (r90 == "H") == is_home else "L")
                team_id = r["home_id"] if is_home else r["away_id"]
                hist[team_id].add({
                    "t": t, "res": res, "home": is_home,
                    "gf": float(r["hg"] if is_home else r["ag"]), "ga": float(r["ag"] if is_home else r["hg"]),
                    "xgf": _val(r, f"{me}_xg"), "xga": _val(r, f"{op}_xg"),
                    "shots": _val(r, f"{me}_shots"), "sot": _val(r, f"{me}_sot"),
                })
            h2h[(min(r["home_id"], r["away_id"]), max(r["home_id"], r["away_id"]))].append((r["home_id"], r90))
    return pd.DataFrame(out)
