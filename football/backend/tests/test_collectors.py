"""2단계: 수집기 테스트 (네트워크 없이 가짜 응답)."""
import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select

from backend.collectors import football_data as fd
from backend.collectors import thesportsdb as ts
from backend.collectors.base import current_season_start_year, season_label
from backend.collectors.http_cache import HttpCache
from backend.collectors.store import Store
from backend.config import LeagueConfig
from backend.db.init_db import make_engine, make_session_factory, sync_leagues
from backend.db.schema import Base, ExternalId, Match, MatchOdds, MatchTeamStats, Team, TeamAlias

EPL = LeagueConfig("eng_premier_league", "EPL", True, "league", "europe", "Europe/London", "cross_year", 1,
                   {"football_data": {"code": "E0"}})
J1 = LeagueConfig("jpn_j1_league", "J1", True, "league", "asia", "Asia/Tokyo", "calendar_year", 1,
                  {"football_data": {"extra_file": "JPN", "league_name": "J1 League"}})
ACL = LeagueConfig("afc_champions_league", "ACL", True, "cup", "asia", "Asia/Seoul", "cross_year", 1,
                   {"thesportsdb": {"id": 4719}})

E0_CSV = (
    "﻿Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,Referee,HxG,AxG,HS,AS,HST,AST,HF,AF,HC,AC,HY,AY,HR,AR,"
    "AvgH,AvgD,AvgA,AvgCH,AvgCD,AvgCA\n"
    "E0,07/08/2022,14:00,Man United,Brighton,1,2,A,0,2,A,P Tierney,,,18,7,5,3,10,12,5,3,1,2,0,0,1.6,4.0,5.5,1.55,4.1,6.0\n"
    "E0,23/11/2026,20:00,Brentford,Everton,4,0,H,2,0,H,C Pawson,2.77,0.23,21,4,7,2,9,11,6,3,0,1,0,1,2.12,3.51,3.26,,,\n"
    ",,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,\n"
)


# ── 시즌·시간 ──

def test_season_labels_and_current_season():
    assert season_label(2026, "cross_year") == "2026-27"
    assert season_label(2026, "calendar_year") == "2026"
    assert fd.season_code(2026) == "2627" and fd.season_code(1999) == "9900"
    assert current_season_start_year("cross_year", date(2026, 11, 25)) == 2026
    assert current_season_start_year("cross_year", date(2027, 3, 1)) == 2026
    assert current_season_start_year("calendar_year", date(2026, 11, 25)) == 2026


def test_football_data_time_is_uk_local():
    # 여름(BST, UTC+1): 영국 14:00 = UTC 13:00 / 겨울(GMT): 영국 20:00 = UTC 20:00
    assert fd.parse_kickoff("07/08/2022", "14:00") == datetime(2022, 8, 7, 13, 0, tzinfo=timezone.utc)
    assert fd.parse_kickoff("23/11/2026", "20:00") == datetime(2026, 11, 23, 20, 0, tzinfo=timezone.utc)
    assert fd.parse_kickoff("23/11/26", "") == datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


def test_football_data_rows_parse_stats_xg_odds():
    rows = fd.decode_csv(E0_CSV.encode("utf-8"))
    assert len(rows) == 2  # 빈 줄 제거
    m = fd.row_to_match(rows[1], EPL, "2026-27")
    assert (m.home_name, m.away_name, m.home_goals, m.away_goals, m.result_90) == ("Brentford", "Everton", 4, 0, "H")
    assert m.home_stats.shots == 21 and m.home_stats.xg == 2.77 and m.away_stats.red_cards == 1
    assert {(o.bookmaker, o.kind) for o in m.odds} == {("avg", "pre")}  # 비어 있는 마감 배당은 건너뜀
    old = fd.row_to_match(rows[0], EPL, "2022-23")
    assert old.home_stats.xg is None and {(o.kind) for o in old.odds} == {"pre", "closing"}


def test_football_data_cp1252_fallback():
    raw = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nT1,01/09/2024,Beşiktaş,Fenerbahçe,1,1\n"
    rows = fd.decode_csv(raw.replace("ş", "s").encode("cp1252"))
    assert rows[0]["AwayTeam"] == "Fenerbahçe"


class FakeHttp:
    def __init__(self, mapping):
        self.mapping, self.requested = mapping, []

    def get(self, url, cache_rel, max_age=None):
        self.requested.append(url)
        for key, body in self.mapping.items():
            if key in url:
                if body is None:
                    raise FileNotFoundError(url)
                return body.encode("utf-8") if isinstance(body, str) else body
        return b'{"events": null}'


def test_extra_file_filters_league_and_season():
    jpn = ("Country,League,Season,Date,Time,Home,Away,HG,AG,Res,PSCH,PSCD,PSCA\n"
           "Japan,J1 League,2024,08/12/2024,05:00,Sapporo,Kashiwa,1,0,H,2,3,4\n"
           "Japan,J1 League,2026/2027,21/11/2026,06:00,Kawasaki Frontale,Avispa Fukuoka,1,0,H,,,\n"
           "Japan,J2 League,2024,08/12/2024,05:00,X,Y,0,0,D,,,\n")
    ad = fd.FootballDataAdapter(FakeHttp({"new/JPN.csv": jpn}))
    ms24 = ad.fetch_season(J1, 2024, is_current=False)
    assert [m.home_name for m in ms24] == ["Sapporo"] and ms24[0].season_label == "2024"
    ms26 = ad.fetch_season(J1, 2026, is_current=True)
    assert [m.season_label for m in ms26] == ["2026-27"]  # 추계·춘계제 전환 후 시즌


def test_missing_season_file_returns_empty():
    ad = fd.FootballDataAdapter(FakeHttp({"mmz4281": None}))
    assert ad.fetch_season(EPL, 1980, is_current=False) == []


# ── TheSportsDB ──

def ev(i, home, away, hs, as_, status, ts_, rnd="1"):
    return {"idEvent": str(i), "strHomeTeam": home, "strAwayTeam": away, "idHomeTeam": f"h{home}",
            "idAwayTeam": f"a{away}", "intHomeScore": hs, "intAwayScore": as_, "strStatus": status,
            "strTimestamp": ts_, "intRound": rnd, "strVenue": "V", "strPostponed": "no"}


def test_tsdb_status_and_extra_time():
    fin = ts.event_to_match(ev(1, "A", "B", "2", "1", "FT", "2026-08-11T10:00:00"), ACL, "2026-27")
    assert fin.status == "finished" and fin.result_90 == "H" and fin.decided_by == "regular"
    assert fin.kickoff_utc == datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)
    aet = ts.event_to_match(ev(2, "Gangwon FC", "Gamba Osaka", "0", "1", "AET", "2026-08-11T10:00:00"), ACL, "2026-27")
    assert aet.result_90 == "D" and aet.decided_by == "extra_time" and aet.away_goals == 1
    ns = ts.event_to_match(ev(3, "A", "B", "", "", "NS", "2026-12-01T10:00:00"), ACL, "2026-27")
    assert ns.status == "scheduled" and ns.home_goals is None and ns.result_90 is None
    pst = ts.event_to_match({**ev(4, "A", "B", "", "", "NS", "2026-12-01T10:00:00"), "strPostponed": "yes"}, ACL, "x")
    assert pst.status == "postponed"


def test_tsdb_round_loop_stops_after_empty_rounds():
    pages = {f"&r={r}&": json.dumps({"events": [ev(r * 10 + k, f"H{k}", f"A{k}", "1", "0", "FT",
                                                  "2026-09-01T10:00:00", str(r)) for k in range(2)]})
             for r in (1, 2, 3)}
    http = FakeHttp(pages)
    ms = ts.TheSportsDbAdapter(http, api_key="k").fetch_season(ACL, 2026, is_current=True)
    assert len(ms) == 6
    assert "s=2026-2027" in http.requested[0]
    assert len(http.requested) == 3 + ts.EMPTY_ROUNDS_TO_STOP


# ── DB 저장 ──

@pytest.fixture
def store():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with make_session_factory(engine)() as s:
        sync_leagues(s, [EPL, J1, ACL])
        s.commit()
        yield Store(s)


def test_store_is_idempotent_and_saves_stats_odds(store):
    ms = [fd.row_to_match(r, EPL, "2026-27") for r in fd.decode_csv(E0_CSV.encode())]
    rep1 = store.save_matches(ms, "England")
    rep2 = store.save_matches(ms, "England")
    s = store.s
    assert (rep1.inserted, rep2.inserted, rep2.unchanged) == (2, 0, 2)
    assert s.scalar(select(func.count(Match.id))) == 2
    assert s.scalar(select(func.count(MatchTeamStats.id))) == 4
    assert s.scalar(select(func.count(MatchOdds.id))) == 3
    assert s.scalar(select(func.count(Team.id))) == 4


def test_scheduled_then_finished_updates_same_row(store):
    sched = ts.event_to_match(ev(9, "Ulsan HD", "FC Seoul", "", "", "NS", "2026-11-28T05:00:00"), ACL, "2026-27")
    store.save_matches([sched])
    done = ts.event_to_match(ev(9, "Ulsan HD", "FC Seoul", "2", "2", "FT", "2026-11-28T05:00:00"), ACL, "2026-27")
    rep = store.save_matches([done])
    m = store.s.scalars(select(Match)).one()
    assert rep.updated == 1 and m.status == "finished" and (m.home_goals, m.away_goals, m.result_90) == (2, 2, "D")
    # 늦게 온 '예정' 데이터가 끝난 경기를 되돌리지 않는다
    store.save_matches([sched])
    assert store.s.scalars(select(Match)).one().status == "finished"


def test_team_linked_across_sources_by_name(store):
    j1 = fd.row_to_match({"Date": "21/11/2026", "Time": "06:00", "Home": "Gamba Osaka", "Away": "Kashima",
                          "HG": "1", "AG": "0", "Res": "H"}, J1, "2026-27")
    store.save_matches([j1], "Japan")
    acl = ts.event_to_match(ev(5, "Gangwon FC", "Gamba Osaka", "0", "1", "AET", "2026-08-11T10:00:00"), ACL, "2026-27")
    rep = store.save_matches([acl])
    gamba = store.s.scalars(select(TeamAlias).where(TeamAlias.alias == "Gamba Osaka")).all()
    assert {a.source for a in gamba} == {"football_data", "thesportsdb"}
    assert len({a.team_id for a in gamba}) == 1 and len(rep.teams_linked) == 1
    assert store.s.scalar(select(ExternalId.entity_id).where(
        ExternalId.entity_type == "team", ExternalId.external_id == "aGamba Osaka")) == gamba[0].team_id


def test_stale_scheduled_marked_postponed(store):
    m = ts.event_to_match(ev(7, "A", "B", "", "", "NS", "2026-11-01T05:00:00"), ACL, "2026-27")
    store.save_matches([m])
    assert store.mark_stale_scheduled(now=datetime(2026, 11, 25, tzinfo=timezone.utc)) == 1
    assert store.s.scalars(select(Match)).one().status == "postponed"


# ── HTTP 캐시 ──

class Resp:
    def __init__(self, status, body=b"ok", headers=None):
        self.status_code, self.content, self.headers = status, body, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class Sess:
    def __init__(self, resps):
        self.resps, self.headers, self.n = list(resps), {}, 0

    def get(self, url, timeout=None):
        self.n += 1
        return self.resps.pop(0)


def test_http_cache_reuses_file_and_retries_429(tmp_path):
    slept = []
    sess = Sess([Resp(429, headers={"Retry-After": "7"}), Resp(200, b"data")])
    http = HttpCache(data_dir=tmp_path, session=sess, sleep=slept.append, min_interval={"x.test": 0})
    assert http.get("https://x.test/a", "x/a.csv") == b"data"
    assert 7.0 in slept and sess.n == 2
    assert http.get("https://x.test/a", "x/a.csv") == b"data" and sess.n == 2  # 캐시 사용
    assert (tmp_path / "http_calls.log").read_text().count("\n") == 2


def test_http_cache_retries_connection_errors(tmp_path):
    import requests

    class Flaky:
        headers = {}

        def __init__(self):
            self.n = 0

        def get(self, url, timeout=None):
            self.n += 1
            if self.n == 1:
                raise requests.ConnectionError("Connection reset by peer")
            return Resp(200, b"ok")

    slept, sess = [], Flaky()
    http = HttpCache(data_dir=tmp_path, session=sess, sleep=slept.append, min_interval={"x.test": 0})
    assert http.get("https://x.test/b", "x/b.csv") == b"ok" and sess.n == 2 and 10.0 in slept
    assert "ConnectionError" in (tmp_path / "http_calls.log").read_text()


def test_swapped_duplicate_skipped_and_removed(store, tmp_path):
    a = ts.event_to_match(ev(31, "Pohang Steelers", "Suwon FC", "1", "1", "FT", "2024-10-06T06:00:00"), ACL, "2026-27")
    b = ts.event_to_match(ev(32, "Suwon FC", "Pohang Steelers", "1", "1", "FT", "2024-10-06T06:00:00"), ACL, "2026-27")
    rep = store.save_matches([a, b])
    assert rep.inserted == 1 and len(rep.duplicates_skipped) == 1
    assert store.s.scalar(select(func.count(Match.id))) == 1
    # 이미 DB에 들어가 있던 중복(과거 수집분)도 정리된다
    from backend.db.schema import Match as M
    first = store.s.scalars(select(M)).one()
    store.s.add(M(season_id=first.season_id, kickoff_utc=first.kickoff_utc, home_team_id=first.away_team_id,
                  away_team_id=first.home_team_id, status="finished", home_goals=1, away_goals=1, result_90="D"))
    store.s.flush()
    log = tmp_path / "dq.log"
    assert len(store.remove_swapped_duplicates(log_path=log)) == 1
    assert "중복 경기 삭제" in log.read_text()
    assert store.s.scalar(select(func.count(Match.id))) == 1 and store.s.scalars(select(M)).one().id == first.id
