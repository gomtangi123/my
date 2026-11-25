"""0단계 조사 스크립트·API 클라이언트 테스트 (네트워크 없이 가짜 응답 사용)."""
from datetime import date

import pytest

from backend.collectors.api_football import ApiError, ApiFootballClient, QuotaGuardError
from backend.scripts import survey_api_football as sv


def season(year, start, end, stats=True, injuries=True):
    return {"year": year, "start": start, "end": end, "current": False,
            "coverage": {"fixtures": {"events": True, "lineups": True, "statistics_fixtures": stats,
                                      "statistics_players": stats},
                         "standings": True, "players": True, "injuries": injuries, "odds": False}}


LEAGUES = [
    {"league": {"id": 71, "name": "Serie A", "type": "League"}, "country": {"name": "Brazil"}, "seasons": []},
    {"league": {"id": 135, "name": "Serie A", "type": "League"}, "country": {"name": "Italy"},
     "seasons": [season(2023, "2023-08-19", "2024-05-26"), season(2024, "2024-08-17", "2025-05-25")]},
    {"league": {"id": 203, "name": "Süper Lig", "type": "League"}, "country": {"name": "Turkey"}, "seasons": []},
    {"league": {"id": 999, "name": "Premiership Cup", "type": "Cup"}, "country": {"name": "Scotland"}, "seasons": []},
]


def cfg(country, names, type_="league"):
    return {"type": type_, "api_football": {"match": {"country": country, "names": names}}}


def test_match_uses_country_to_disambiguate():
    found, _ = sv.match_league(LEAGUES, cfg("Italy", ["Serie A"]))
    assert found["league"]["id"] == 135


def test_match_ignores_accents_and_case():
    found, _ = sv.match_league(LEAGUES, cfg("turkey", ["Super Lig"]))
    assert found["league"]["id"] == 203


def test_no_match_returns_candidates_not_guess():
    found, cands = sv.match_league(LEAGUES, cfg("Scotland", ["Premiership"]))
    assert found is None
    assert cands == ["Premiership Cup"]


def test_future_season_not_used_for_sampling():
    seasons = LEAGUES[1]["seasons"] + [season(2099, "2099-08-01", "2100-05-01")]
    s = sv.summarize_seasons(seasons, date(2025, 1, 1))
    assert s["count"] == 3
    assert s["latest_started"]["year"] == 2024
    assert s["stats_years"] == [2023, 2024]


class FakeResp:
    def __init__(self, body, remaining=50, status=200):
        self.body, self.status_code = body, status
        self.headers = {"x-ratelimit-requests-remaining": str(remaining), "x-ratelimit-requests-limit": "100"}
        self.text = str(body)

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_SLEEP", "0")


def test_client_caches_and_does_not_recall(tmp_path):
    sess = FakeSession([FakeResp({"errors": [], "response": [1]})])
    c = ApiFootballClient(api_key="k", data_dir=tmp_path, session=sess)
    assert c.get("leagues", {"id": 1})["response"] == [1]
    assert c.get("leagues", {"id": 1})["response"] == [1]
    assert len(sess.calls) == 1
    assert (tmp_path / "api_calls.log").read_text().count("\n") == 1
    assert sess.calls[0][2]["x-apisports-key"] == "k"


def test_client_stops_near_quota(tmp_path):
    sess = FakeSession([FakeResp({"errors": [], "response": []}, remaining=5)])
    c = ApiFootballClient(api_key="k", data_dir=tmp_path, session=sess, reserve=5)
    c.get("a")
    with pytest.raises(QuotaGuardError):
        c.get("b")


def test_client_raises_on_api_errors_field(tmp_path):
    sess = FakeSession([FakeResp({"errors": {"token": "Missing application key"}, "response": []})])
    c = ApiFootballClient(api_key="", data_dir=tmp_path, session=sess)
    with pytest.raises(ApiError):
        c.get("leagues")
    assert not list((tmp_path / "raw").iterdir())  # 오류 응답은 캐시하지 않음


def test_sample_detects_xg(tmp_path):
    fixtures = {"errors": [], "response": [
        {"fixture": {"id": 1, "date": "2024-08-17T18:45:00+00:00", "status": {"short": "FT"}, "venue": {"name": "V"}},
         "league": {"round": "Regular Season - 1"}, "teams": {"home": {"name": "A"}, "away": {"name": "B"}},
         "goals": {"home": 2, "away": 1}},
        {"fixture": {"id": 2, "date": "2025-05-25T18:45:00+00:00", "status": {"short": "NS"}, "venue": {}},
         "league": {}, "teams": {"home": {"name": "C"}, "away": {"name": "D"}}, "goals": {"home": None, "away": None}},
    ]}
    stats = {"errors": [], "response": [
        {"statistics": [{"type": "Total Shots", "value": 12}, {"type": "expected_goals", "value": "1.84"}]},
        {"statistics": [{"type": "Total Shots", "value": 7}, {"type": "expected_goals", "value": "0.66"}]},
    ]}
    c = ApiFootballClient(api_key="k", data_dir=tmp_path, session=FakeSession([FakeResp(fixtures), FakeResp(stats)]))
    out = sv.sample_fixture_stats(c, 135, {"year": 2024})
    assert out["finished"] == 1 and out["sample_fixture"]["id"] == 1
    assert out["xg"] is True and out["xg_value_example"] == "1.84"


def test_render_and_readme_section_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "README", tmp_path / "README.md")
    (tmp_path / "README.md").write_text("# 제목\n\n" + sv.BEGIN + "\n옛날\n" + sv.END + "\n\n## 뒤\n", encoding="utf-8")
    results = [{"name_ko": "세리에 A", "found": True, "id": 135, "api_name": "Serie A",
                "seasons": sv.summarize_seasons(LEAGUES[1]["seasons"], date(2025, 1, 1)),
                "sample": {"season": 2024, "fixtures": 380, "span_days": 280, "sample_fixture": None,
                           "stat_types": [], "xg": None}},
               {"name_ko": "없는 리그", "found": False, "candidates": ["X"]}]
    sv.write_readme(sv.render(results, None, date(2025, 1, 1)))
    text = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "옛날" not in text and "## 뒤" in text and text.count(sv.BEGIN) == 1
    assert "| 세리에 A | 135 | Serie A | 2 | 2023~2024 |" in text
    assert "**찾지 못함**" in text
