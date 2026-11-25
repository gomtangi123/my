"""축구 분석·예측 API (FastAPI).

실행 (football 폴더에서):
    uvicorn backend.app.main:app --reload --port 8000
문서: http://localhost:8000/docs

시간은 모두 한국 시간(KST)으로 내려준다. 데이터가 없는 지표는 null — 화면에서 숨긴다.
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import sessionmaker

from backend.app import schemas as S
from backend.app.deps import DISCLAIMER, KST, DataCache, now_utc, to_kst
from backend.config import load_leagues
from backend.db.init_db import init_db, make_session_factory
from backend.db.schema import Player
from backend.features import stats
from backend.models.dixon_coles import MAX_GOALS, summarize_matrix, tau
from backend.models.evaluate import OUTCOMES, accuracy, brier, calibration_table, log_loss

WDL_KO = str.maketrans({"W": "승", "D": "무", "L": "패"})
MODEL_KO = {"dixon_coles": "Dixon-Coles", "elo": "Elo"}
HEATMAP_GOALS = 6


def create_app(session_factory: sessionmaker | None = None) -> FastAPI:
    session_factory = session_factory or make_session_factory(init_db())
    cache = DataCache(session_factory)
    leagues_cfg = {l.key: l for l in load_leagues()}

    app = FastAPI(title="축구 분석·예측 API", version="0.1.0",
                  description="유럽·아시아 리그 통계와 경기 예측. 시간은 모두 한국 시간(KST). " + DISCLAIMER)
    app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("FRONTEND_ORIGINS", "http://localhost:3000").split(","),
                       allow_methods=["GET"], allow_headers=["*"])
    app.state.cache = cache

    # ── 공통 변환 ──
    def data() -> DataCache:
        return cache.get()

    def enabled_keys(c: DataCache) -> list[str]:
        keys = set(c.matches["league_key"]) if not c.matches.empty else set()
        return [k for k, l in leagues_cfg.items() if l.enabled and k in keys]

    def team_ref(c: DataCache, team_id) -> S.TeamRef:
        t = c.team(int(team_id))
        return S.TeamRef(id=t["id"], name=t["name"], name_ko=t["name_ko"], short_name=t["short_name"], color=t["color"])

    def league_out(c: DataCache, key: str) -> S.LeagueOut:
        lg = leagues_cfg[key]
        m = c.matches[c.matches["league_key"] == key]
        seasons = sorted(m["season_label"].unique(), key=lambda s: int(str(s)[:4]))
        return S.LeagueOut(key=key, name_ko=lg.name_ko, type=lg.type, region=lg.region, seasons=seasons,
                           current_season=seasons[-1] if seasons else None,
                           has_match_stats=bool(m["h_shots"].notna().any()), has_xg=bool(m["h_xg"].notna().any()),
                           has_standings=lg.type == "league",
                           tiebreak=lg.standings.get("tiebreak") or stats.DEFAULT_TIEBREAK,
                           has_split=bool(lg.standings.get("split")))

    def preds_for(c: DataCache, match_id: int) -> list[dict]:
        return c.pred_by_match.get(int(match_id), [])

    def choose_main(c: DataCache, r) -> dict | None:
        """대표 예측: 경기 전 live 예측 우선, 없으면 검증(backtest) 예측. 리그는 Dixon-Coles, 컵은 Elo."""
        ps = preds_for(c, r["match_id"])
        order = ["dixon_coles", "elo"] if leagues_cfg[r["league_key"]].type == "league" else ["elo"]
        for kind in ("live", "backtest"):
            for model in order:
                for p in ps:
                    if p["model"] == model and p["kind"] == kind:
                        return p
        return None

    def prob_out(p: dict) -> S.Probabilities:
        f = lambda v: None if v is None or pd.isna(v) else round(float(v), 4)  # noqa: E731
        return S.Probabilities(model=p["model"], home_win=f(p["p_home"]), draw=f(p["p_draw"]), away_win=f(p["p_away"]),
                               over_2_5=f(p.get("p_over_2_5")), btts=f(p.get("p_btts")))

    def int_or_none(v):
        return None if v is None or pd.isna(v) else int(v)

    def match_item(c: DataCache, r) -> S.MatchItem:
        main = choose_main(c, r)
        return S.MatchItem(
            id=int(r["match_id"]), league_key=r["league_key"], league_name_ko=leagues_cfg[r["league_key"]].name_ko,
            season=str(r["season_label"]), kickoff_kst=to_kst(r["kickoff_utc"]), status=r["status"],
            home=team_ref(c, r["home_id"]), away=team_ref(c, r["away_id"]),
            home_goals=int_or_none(r["hg"]), away_goals=int_or_none(r["ag"]),
            decided_by=None if pd.isna(r.get("decided_by")) else r.get("decided_by"),
            prediction=prob_out(main) if main else None)

    def form_out(f: dict) -> S.FormOut:
        return S.FormOut(results=f["results"].translate(WDL_KO), points=f["points"], games=f["games"],
                         goals_for=f["gf"], goals_against=f["ga"])

    def clean(d: dict) -> dict:
        return {k: (None if v is None or (isinstance(v, float) and np.isnan(v)) else (round(v, 4) if isinstance(v, float) else v))
                for k, v in d.items()}

    def get_match_row(c: DataCache, match_id: int):
        m = c.matches[c.matches["match_id"] == match_id]
        if m.empty:
            raise HTTPException(404, "경기를 찾을 수 없습니다")
        return m.iloc[0]

    # ── 1. 리그 ──
    @app.get("/api/leagues", response_model=list[S.LeagueOut], summary="리그 목록", tags=["리그"])
    def leagues():
        c = data()
        return [league_out(c, k) for k in enabled_keys(c)]

    @app.get("/api/leagues/{key}/standings", response_model=S.StandingsOut, summary="순위표 + 리그 평균 지표", tags=["리그"])
    def standings(key: str, season: str | None = None,
                  venue: str = Query("all", pattern="^(all|home|away)$", description="all / home / away")):
        c = data()
        if key not in enabled_keys(c):
            raise HTTPException(404, "리그를 찾을 수 없습니다")
        lo = league_out(c, key)
        if not lo.has_standings:
            raise HTTPException(400, "컵 대회는 순위표를 제공하지 않습니다. 경기 목록(/api/matches)을 이용하세요")
        season = season or lo.current_season
        if season not in lo.seasons:
            raise HTTPException(404, "해당 시즌이 없습니다")
        t = stats.standings(c.matches, key, season, venue=venue, rules=leagues_cfg[key].standings)
        rows = [S.StandingRow(rank=r["rank"], team=team_ref(c, r["team_id"]), played=r["played"], won=r["won"],
                              drawn=r["drawn"], lost=r["lost"], goals_for=r["gf"], goals_against=r["ga"],
                              goal_diff=r["gd"], points=r["points"], form=r["form"].translate(WDL_KO),
                              group=r.get("group"))
                for r in t.to_dict("records")]
        m = c.matches[(c.matches["league_key"] == key) & (c.matches["season_label"] == season) & (c.matches["status"] == "finished")]
        n = len(m)

        def rate(mask):
            return round(float(mask.mean()), 4) if n else None

        def per_team(col):
            v = pd.concat([m[f"h_{col}"], m[f"a_{col}"]]).dropna()
            return round(float(v.mean()), 2) if len(v) else None

        avg = S.LeagueAverages(
            matches=n, goals_per_match=round(float((m["hg"] + m["ag"]).mean()), 3) if n else None,
            home_win_rate=rate(m["result_90"] == "H"), draw_rate=rate(m["result_90"] == "D"),
            away_win_rate=rate(m["result_90"] == "A"), over_2_5_rate=rate((m["hg"] + m["ag"]) > 2.5),
            btts_rate=rate((m["hg"] > 0) & (m["ag"] > 0)), shots_per_team=per_team("shots"),
            corners_per_team=per_team("corners"), xg_per_team=per_team("xg"))
        return S.StandingsOut(league=lo, season=season, venue=venue, rows=rows, averages=avg)

    # ── 2. 경기 목록 ──
    @app.get("/api/matches", response_model=list[S.MatchItem], summary="경기 목록 (날짜별, KST 기준)", tags=["경기"])
    def matches(date_: date | None = Query(None, alias="date", description="KST 날짜 YYYY-MM-DD (하루)"),
                from_: date | None = Query(None, alias="from", description="KST 시작 날짜 (기본: 오늘)"),
                to: date | None = Query(None, description="KST 끝 날짜 (기본: 시작+6일)"),
                league: str | None = None, region: str | None = Query(None, pattern="^(europe|asia)$"),
                limit: int = Query(300, le=1000)):
        c = data()
        if date_:
            start, end = date_, date_
        else:
            start = from_ or now_utc().astimezone(KST).date()
            end = to or start + timedelta(days=6)
        if end < start:
            raise HTTPException(400, "끝 날짜가 시작 날짜보다 빠릅니다")
        lo = pd.Timestamp(datetime.combine(start, time(0), tzinfo=KST))
        hi = pd.Timestamp(datetime.combine(end + timedelta(days=1), time(0), tzinfo=KST))
        m = c.matches[(c.matches["kickoff_utc"] >= lo) & (c.matches["kickoff_utc"] < hi)
                      & c.matches["league_key"].isin(enabled_keys(c))]
        if league:
            m = m[m["league_key"] == league]
        if region:
            m = m[m["region"] == region]
        return [match_item(c, r) for r in m.head(limit).to_dict("records")]

    # ── 3. 경기 예측 상세 ──
    @app.get("/api/matches/{match_id}", response_model=S.MatchDetailOut, summary="경기 상세 (예측)", tags=["경기"])
    def match_detail(match_id: int):
        c = data()
        r = get_match_row(c, match_id)
        df, ko = c.matches, r["kickoff_utc"]
        lg = leagues_cfg[r["league_key"]]
        ps = preds_for(c, match_id)
        main = choose_main(c, r)
        pred = None
        if main:
            same_kind = [p for p in ps if p["kind"] == main["kind"]]
            others = [prob_out(p) for p in same_kind if p["model"] != main["model"]]
            matrix = ml = eg = None
            if main["model"] == "dixon_coles" and pd.notna(main.get("exp_home_goals")):
                lam, mu, rho = float(main["exp_home_goals"]), float(main["exp_away_goals"]), float(main["rho"])
                g = np.arange(MAX_GOALS + 1)
                from scipy.stats import poisson
                mat = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
                xs, ys = np.meshgrid(g, g, indexing="ij")
                mat = np.clip(mat * tau(xs, ys, lam, mu, rho), 0, None)
                mat /= mat.sum()
                s = summarize_matrix(mat)
                matrix = np.round(mat[:HEATMAP_GOALS + 1, :HEATMAP_GOALS + 1], 4).tolist()
                ml = {"home": s["most_likely_score"][0], "away": s["most_likely_score"][1],
                      "probability": round(s["most_likely_prob"], 4)}
                eg = {"home": round(lam, 3), "away": round(mu, 3)}
            pred = S.PredictionDetail(main=prob_out(main), others=others, expected_goals=eg, most_likely_score=ml,
                                      score_matrix=matrix, made_at_kst=to_kst(main["made_at"]),
                                      pre_match=bool(pd.Timestamp(main["made_at"]) < ko))
        elo = {p["model"]: p for p in ps}.get("elo") or {}

        def side(team_id, is_home):
            prof = (stats.team_profile(df, team_id, as_of=ko, league_key=r["league_key"], season_label=r["season_label"])
                    if lg.type == "league" else stats.team_profile(df, team_id, as_of=ko, last_n=10))
            if prof.get("games", 0) < 3 and lg.type == "league":  # 시즌 초반이면 최근 10경기 기준
                prof = stats.team_profile(df, team_id, as_of=ko, last_n=10)
            ev = elo.get("elo_home" if is_home else "elo_away")
            return S.TeamComparisonSide(
                team=team_ref(c, team_id), form5=form_out(stats.form(df, team_id, as_of=ko, n=5)),
                form10=form_out(stats.form(df, team_id, as_of=ko, n=10)), profile=clean(prof),
                rest_days=None if (rd := stats.rest_days(df, team_id, ko)) is None else round(rd, 1),
                matches_last_14d=stats.matches_in_last(df, team_id, ko, 14),
                elo=None if ev is None or pd.isna(ev) else round(float(ev), 1))

        h2h = stats.head_to_head(df, r["home_id"], r["away_id"], as_of=ko, n=10)
        h2h_out = S.H2HOut(games=h2h["games"], home_team_wins=h2h["a_wins"], draws=h2h["draws"],
                           away_team_wins=h2h["b_wins"],
                           matches=[{"match_id": int(x["match_id"]), "kickoff_kst": to_kst(x["kickoff_utc"]),
                                     "home_team_was_home": bool(x["is_home"]), "home_team_goals": int(x["gf"]),
                                     "away_team_goals": int(x["ga"])} for x in reversed(h2h["matches"])])
        if lg.type == "league":
            expl = ("대표 예측은 Dixon-Coles 모델입니다. 최근 2년간 리그 경기 결과로 팀별 공격력·수비력과 홈 어드밴티지를 추정하고 "
                    "(최근 경기일수록 가중치 큼), 두 팀의 예상 득점으로 0~10골 스코어 확률을 계산합니다. 저득점 경기(0-0, 1-0 등) "
                    "보정이 들어갑니다. 함께 표시하는 Elo는 모든 대회 결과로 갱신되는 팀 레이팅 차이로 승무패 확률을 구합니다.")
        else:
            expl = ("컵 대회(서로 다른 리그 팀끼리 경기)라서 리그별 공격·수비력을 비교할 수 없어, 모든 대회 결과로 갱신되는 "
                    "Elo 레이팅 차이로 승무패 확률을 구합니다. 스코어·오버/언더 확률은 제공하지 않습니다.")
        return S.MatchDetailOut(match=match_item(c, r), venue=None, neutral_venue=bool(r["neutral"]), prediction=pred,
                                comparison={"home": side(r["home_id"], True), "away": side(r["away_id"], False)},
                                head_to_head=h2h_out, model_explanation=expl, disclaimer=DISCLAIMER)

    # ── 4. 팀 ──
    @app.get("/api/teams/{team_id}", response_model=S.TeamDetailOut, summary="팀 상세", tags=["팀"])
    def team_detail(team_id: int):
        c = data()
        df = c.matches
        if team_id not in c.teams:
            raise HTTPException(404, "팀을 찾을 수 없습니다")
        mine = df[(df["home_id"] == team_id) | (df["away_id"] == team_id)]
        league_m = mine[mine["league_key"].map(lambda k: leagues_cfg.get(k) is not None and leagues_cfg[k].type == "league")]
        lkey = season = None
        standing = home = away = None
        prof: dict = {}
        if not league_m.empty:
            last = league_m.sort_values("kickoff_utc").iloc[-1]
            lkey, season = last["league_key"], str(last["season_label"])
            t = stats.standings(df, lkey, season, rules=leagues_cfg[lkey].standings)
            row = t[t["team_id"] == team_id]
            if not row.empty:
                x = row.iloc[0]
                standing = S.StandingRow(rank=int(x["rank"]), team=team_ref(c, team_id), played=int(x["played"]),
                                         won=int(x["won"]), drawn=int(x["drawn"]), lost=int(x["lost"]),
                                         goals_for=int(x["gf"]), goals_against=int(x["ga"]), goal_diff=int(x["gd"]),
                                         points=int(x["points"]), form=x["form"].translate(WDL_KO),
                                         group=x.get("group"))
            split = stats.home_away_split(df, team_id, lkey, season, rules=leagues_cfg[lkey].standings)
            home, away = clean(split["home"]), clean(split["away"])
            for d in (home, away):
                d.pop("team_id", None)
                d.pop("group", None)
                d["form"] = str(d.get("form", "")).translate(WDL_KO)
            prof = stats.team_profile(df, team_id, league_key=lkey, season_label=season)
        else:
            prof = stats.team_profile(df, team_id, last_n=10)
        now = pd.Timestamp(now_utc())
        recent = mine[mine["status"] == "finished"].sort_values("kickoff_utc").tail(10).iloc[::-1]
        upcoming = mine[(mine["status"] == "scheduled") & (mine["kickoff_utc"] > now)].sort_values("kickoff_utc").head(5)
        notes = ["부상·결장과 선수 기록은 무료 데이터 소스에 없어 아직 제공하지 않습니다.",
                 "골 시간 정보가 없어 15분 단위 득점 대신 전반·후반 득점을 보여줍니다."]
        if lkey and not league_out(c, lkey).has_match_stats:
            notes.append("이 리그는 슈팅·코너 등 경기 통계를 제공하지 않습니다.")
        return S.TeamDetailOut(
            team=team_ref(c, team_id), league=league_out(c, lkey) if lkey else None, season=season, standing=standing,
            form5=form_out(stats.form(df, team_id, n=5)), form10=form_out(stats.form(df, team_id, n=10)),
            home=home, away=away, profile=clean(prof),
            goals_by_half=clean({k: prof.get(k) for k in ("first_half_goals_for", "second_half_goals_for",
                                                          "first_half_goals_against", "second_half_goals_against")}),
            recent_matches=[match_item(c, r) for r in recent.to_dict("records")],
            upcoming_matches=[match_item(c, r) for r in upcoming.to_dict("records")], data_notes=notes)

    # ── 5. 선수 ──
    @app.get("/api/players/{player_id}", summary="선수 상세", tags=["선수"])
    def player_detail(player_id: int):
        with session_factory() as s:
            p = s.get(Player, player_id)
            if p is None:
                raise HTTPException(404, "선수 데이터가 아직 없습니다 (무료 데이터 소스에 선수 기록이 없음)")
            return {"id": p.id, "name": p.name, "name_ko": p.name_ko, "position": p.position,
                    "nationality": p.nationality, "current_team_id": p.current_team_id}

    # ── 6. 모델 성능 ──
    @app.get("/api/model-performance", response_model=S.ModelPerformanceOut, summary="모델 성능 (예측 vs 실제)", tags=["모델"])
    def model_performance():
        c = data()
        p, df = c.predictions, c.matches
        if p.empty:
            raise HTTPException(404, "아직 예측 기록이 없습니다 — python -m backend.models.evaluate 실행 필요")
        res = df[["match_id", "league_key", "result_90", "kickoff_utc", "home_id", "away_id", "hg", "ag"]]
        bt = p[p["kind"] == "backtest"].merge(res, on="match_id")
        bt = bt[bt["result_90"].isin(OUTCOMES)]
        common = set(bt.loc[bt["model"] == "dixon_coles", "match_id"]) & set(bt.loc[bt["model"] == "elo", "match_id"])

        def rows(sub):
            out = []
            for model in ("dixon_coles", "elo"):
                s_ = sub[sub["model"] == model]
                if s_.empty:
                    continue
                pr, y = s_[["p_home", "p_draw", "p_away"]].to_numpy(float), s_["result_90"].to_numpy()
                out.append(S.PerformanceRow(model=MODEL_KO[model], matches=len(s_), log_loss=round(log_loss(pr, y), 4),
                                            brier=round(brier(pr, y), 4), accuracy=round(accuracy(pr, y), 4)))
            return out

        overall = rows(bt[bt["match_id"].isin(common)])
        by_league = {leagues_cfg[k].name_ko: rows(g) for k, g in bt.groupby("league_key") if k in leagues_cfg}
        calib = {}
        for model in ("dixon_coles", "elo"):
            s_ = bt[(bt["model"] == model) & bt["match_id"].isin(common)]
            t = calibration_table(s_[["p_home", "p_draw", "p_away"]].to_numpy(float), s_["result_90"].to_numpy())
            calib[MODEL_KO[model]] = [{"bin": x["구간"], "predicted": round(x["예측 평균"], 4),
                                       "observed": round(x["실제 비율"], 4), "count": x["건수"]} for x in t.to_dict("records")]
        # 최근 끝난 경기: 경기 전 live 예측이 있으면 그것, 없으면 검증 예측
        done = df[df["result_90"].isin(OUTCOMES)].sort_values("kickoff_utc").tail(400)
        recent = []
        for r in done.iloc[::-1].to_dict("records"):
            main = choose_main(c, r)
            if not main:
                continue
            probs = [main["p_home"], main["p_draw"], main["p_away"]]
            pick = OUTCOMES[int(np.argmax(probs))]
            recent.append({"match": match_item(c, r).model_dump(), "kind": main["kind"],
                           "predicted_pick": {"H": "홈승", "D": "무", "A": "원정승"}[pick],
                           "actual": {"H": "홈승", "D": "무", "A": "원정승"}[r["result_90"]], "hit": pick == r["result_90"]})
            if len(recent) >= 30:
                break
        notes = ["backtest: 각 경기 이전 데이터로만 학습한 모델로 다시 계산한 예측 (walk-forward 검증)",
                 "live: 실제로 경기 시작 전에 만들어 저장한 예측 — 경기 시작 후에는 고치지 않음",
                 "Log loss·Brier는 낮을수록 좋음. 정답은 90분 결과 (연장·승부차기 경기는 무승부)"]
        return S.ModelPerformanceOut(overall=overall, by_league=by_league, calibration=calib, recent=recent, notes=notes)

    @app.get("/api/health", include_in_schema=False)
    def health():
        c = data()
        return {"ok": True, "matches": len(c.matches), "predictions": len(c.predictions)}

    return app


app = create_app() if os.environ.get("FOOTBALL_API_NO_AUTOCREATE") != "1" else None
