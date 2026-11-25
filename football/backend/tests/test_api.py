"""5단계: API 테스트 (임시 SQLite 파일 + 가짜 데이터)."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from backend.app.main import create_app
from backend.collectors.base import RawMatch, RawTeamStats
from backend.collectors.store import Store
from backend.config import load_leagues
from backend.db.init_db import make_engine, make_session_factory, sync_leagues
from backend.db.schema import Base, Match, Prediction
from backend.jobs import predict

NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def raw(i, league, label, days, home, away, hg=None, ag=None, ext=None, stats=False, status=None):
    finished = hg is not None
    return RawMatch(
        source="football_data" if league != "afc_champions_league" else "thesportsdb", league_key=league,
        season_label=label, external_id=f"m{i}", kickoff_utc=NOW + timedelta(days=days), home_name=home, away_name=away,
        home_ext_id=ext and f"t-{home}", away_ext_id=ext and f"t-{away}",
        status=status or ("finished" if finished else "scheduled"), home_goals=hg, away_goals=ag,
        ht_home_goals=None if hg is None else min(hg, 1), ht_away_goals=None if ag is None else min(ag, 1),
        result_90=None if hg is None else ("H" if hg > ag else "A" if ag > hg else "D"),
        decided_by="regular" if finished else None,
        home_stats=RawTeamStats(shots=12, corners=5, xg=1.4) if stats and finished else None,
        away_stats=RawTeamStats(shots=8, corners=3, xg=0.9) if stats and finished else None)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    # 실제 data/models 의 LightGBM 모델·대표 모델 선택 파일을 읽지 않도록 임시 경로로 바꾼다 (테스트 격리)
    from backend.models import ml_model, selection
    iso = tmp_path_factory.mktemp("models")
    mp = pytest.MonkeyPatch()
    mp.setattr(ml_model, "MODEL_FILE", iso / "lgbm.txt")
    mp.setattr(ml_model, "META_FILE", iso / "lgbm_meta.json")
    mp.setattr(selection, "SELECTION_FILE", iso / "selection.json")
    db = tmp_path_factory.mktemp("api") / "test.db"
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    sf = make_session_factory(engine)
    rng = np.random.default_rng(0)
    teams = ["Arsenal", "Chelsea", "Liverpool", "Everton", "Fulham", "Leeds"]
    ms, i = [], 0
    for rnd in range(30):  # 지난 시즌 + 이번 시즌 경기 (과거)
        perm = rng.permutation(6)
        for k in range(0, 6, 2):
            i += 1
            label = "2025-26" if rnd < 20 else "2026-27"
            ms.append(raw(i, "eng_premier_league", label, -300 + rnd * 9 + k * 0.01, teams[perm[k]], teams[perm[k + 1]],
                          int(rng.poisson(1.5)), int(rng.poisson(1.1)), stats=True))
    # 다가오는 경기: UTC 11월 말 밤 경기 → KST로는 다음 날
    ms.append(raw(900, "eng_premier_league", "2026-27", 2, "Arsenal", "Chelsea"))
    ms.append(raw(901, "eng_premier_league", "2026-27", 3, "Liverpool", "Leeds"))
    ms.append(raw(902, "afc_champions_league", "2026-27", -20, "Ulsan HD", "Gamba Osaka", 1, 1, ext=True))
    ms.append(raw(903, "afc_champions_league", "2026-27", 4, "Ulsan HD", "Kawasaki", ext=True))
    with sf() as s:
        sync_leagues(s, load_leagues())
        Store(s).save_matches(ms, "England")
        s.commit()
        predict.run(days=14, now=NOW, session=s)
    app = create_app(sf)
    c = TestClient(app)
    c.sf = sf
    yield c
    mp.undo()


def test_leagues(client):
    r = client.get("/api/leagues")
    assert r.status_code == 200
    by = {x["key"]: x for x in r.json()}
    assert set(by) == {"eng_premier_league", "afc_champions_league"}
    assert by["eng_premier_league"]["has_xg"] is True and by["afc_champions_league"]["has_match_stats"] is False
    assert by["eng_premier_league"]["current_season"] == "2026-27"
    assert by["afc_champions_league"]["has_standings"] is False


def test_standings_and_averages(client):
    r = client.get("/api/leagues/eng_premier_league/standings").json()
    assert r["season"] == "2026-27" and len(r["rows"]) == 6
    assert [x["rank"] for x in r["rows"]] == list(range(1, 7))
    assert set(r["rows"][0]["form"]) <= set("승무패")
    a = r["averages"]
    assert a["matches"] == 30 and a["xg_per_team"] == pytest.approx(1.15) and a["shots_per_team"] == pytest.approx(10)
    assert abs(a["home_win_rate"] + a["draw_rate"] + a["away_win_rate"] - 1) < 1e-6
    assert client.get("/api/leagues/afc_champions_league/standings").status_code == 400
    assert client.get("/api/leagues/eng_premier_league/standings?venue=x").status_code == 422
    assert client.get("/api/leagues/nope/standings").status_code == 404


def test_matches_by_kst_date(client):
    upcoming = client.get("/api/matches", params={"from": (NOW + timedelta(days=1)).date().isoformat(),
                                                   "to": (NOW + timedelta(days=6)).date().isoformat()}).json()
    ids = {m["id"]: m for m in upcoming}
    target = next(m for m in upcoming if m["home"]["name"] == "Arsenal" and m["status"] == "scheduled")
    assert target["kickoff_kst"].endswith("+09:00")
    kst_day = target["kickoff_kst"][:10]
    same_day = client.get("/api/matches", params={"date": kst_day}).json()
    assert target["id"] in {m["id"] for m in same_day}
    p = target["prediction"]
    assert p["model"] == "dixon_coles" and abs(p["home_win"] + p["draw"] + p["away_win"] - 1) < 1e-3
    acl = next(m for m in ids.values() if m["league_key"] == "afc_champions_league")
    assert acl["prediction"]["model"] == "elo" and acl["prediction"]["over_2_5"] is None
    assert client.get("/api/matches", params={"region": "asia", "from": (NOW + timedelta(days=1)).date().isoformat()}).json()[0][
        "league_key"] == "afc_champions_league"


def test_match_detail(client):
    m = next(x for x in client.get("/api/matches", params={"from": NOW.date().isoformat()}).json()
             if x["home"]["name"] == "Arsenal" and x["status"] == "scheduled")
    d = client.get(f"/api/matches/{m['id']}").json()
    pred = d["prediction"]
    assert pred["pre_match"] is True and len(pred["score_matrix"]) == 7 and len(pred["score_matrix"][0]) == 7
    assert pred["most_likely_score"]["probability"] > 0 and pred["expected_goals"]["home"] > 0
    assert [o["model"] for o in pred["others"]] == ["elo"]
    assert d["disclaimer"].startswith("이 예측은") and "Dixon-Coles" in d["model_explanation"]
    home = d["comparison"]["home"]
    assert home["form5"]["games"] == 5 and home["elo"] is not None and home["profile"]["xg_for"] is not None
    assert client.get("/api/matches/999999").status_code == 404


def test_team_detail_and_players(client):
    arsenal = client.get("/api/leagues/eng_premier_league/standings").json()["rows"][0]["team"]
    t = client.get(f"/api/teams/{arsenal['id']}").json()
    assert t["league"]["key"] == "eng_premier_league" and t["standing"] is not None
    assert len(t["recent_matches"]) == 10 and t["injuries"] == [] and t["data_notes"]
    assert t["home"]["played"] + t["away"]["played"] == t["standing"]["played"]
    assert client.get("/api/teams/999999").status_code == 404
    r = client.get("/api/players/1")
    assert r.status_code == 404 and "선수" in r.json()["detail"]


def test_live_prediction_frozen_after_kickoff(client):
    with client.sf() as s:
        past = s.query(Match).filter(Match.status == "finished").first()
        assert predict.upsert_prediction(s, past.id, "elo", "live", NOW, p_home=0.5, p_draw=0.3, p_away=0.2) is False


def test_model_performance(client):
    assert client.get("/api/model-performance").status_code == 200  # live 예측만 있어도 동작
    with client.sf() as s:
        finished = s.query(Match).filter(Match.status == "finished").all()
        rows = [{"match_id": m.id, "model": model, "kind": "backtest", "p_home": 0.5, "p_draw": 0.25, "p_away": 0.25,
                 "made_at": NOW} for m in finished for model in ("dixon_coles", "elo")]
        s.execute(insert(Prediction), rows)
        s.commit()
    # 가짜 데이터의 종료 경기: EPL 30라운드 × 3경기 = 90 + ACL 1경기 = 91 — 모두 두 모델 백테스트 예측이 있음
    assert len(finished) == 91
    client.app.state.cache.invalidate()
    r = client.get("/api/model-performance").json()
    assert {x["model"] for x in r["overall"]} == {"Dixon-Coles", "Elo"}
    assert all(x["matches"] == len(finished) for x in r["overall"])
    # 모든 경기에 같은 확률(0.5/0.25/0.25)을 줬으므로 Log loss는 실제 결과 비율로 정확히 계산된다
    n_home = sum(m.result_90 == "H" for m in finished)
    expected_ll = -(n_home * np.log(0.5) + (len(finished) - n_home) * np.log(0.25)) / len(finished)
    assert r["overall"][0]["log_loss"] == pytest.approx(expected_ll, abs=1e-4)
    assert r["calibration"]["Elo"] and r["recent"]
    assert r["recent"][0]["actual"] in ("홈승", "무", "원정승")
