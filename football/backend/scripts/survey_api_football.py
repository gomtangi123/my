"""0단계: API-Football 데이터 조사.

config/leagues.yaml 의 대회마다 API-Football 지원 여부, 시즌 수, 커버리지 플래그,
실제 경기 통계 응답의 xG 유무를 확인하고 football/README.md 의 조사 결과 표를 만든다.

사용법 (football 폴더에서):
    python -m backend.scripts.survey_api_football            # 활성화된 대회만
    python -m backend.scripts.survey_api_football --all      # 후보 대회까지

예상 호출 수: /status 1 + /leagues 1 + 대회당 최대 2 (경기 목록 + 경기 통계 샘플)
+ 묶음 조회 확인 1 → 기본 13개 대회 기준 약 29회. 무료 요금제(하루 100회)로도 충분하다.
캐시가 있으므로 다시 실행하면 호출하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

import yaml

from backend.collectors.api_football import FOOTBALL_ROOT, ApiError, ApiFootballClient, QuotaGuardError

CONFIG = FOOTBALL_ROOT / "config" / "leagues.yaml"
README = FOOTBALL_ROOT / "README.md"
SURVEY_JSON = FOOTBALL_ROOT / "data" / "survey" / "survey_result.json"
BEGIN = "<!-- SURVEY:BEGIN -->"
END = "<!-- SURVEY:END -->"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.casefold() if c.isalnum())


def match_league(all_leagues: list[dict], cfg: dict) -> tuple[dict | None, list[str]]:
    """설정의 국가·이름 후보로 /leagues 응답에서 대회를 찾는다. (찾은 항목, 같은 국가 후보 이름들)"""
    m = cfg["api_football"]["match"]
    country = norm(m["country"])
    names = [norm(n) for n in m["names"]]
    want_type = "cup" if cfg.get("type") == "cup" else "league"
    in_country = [x for x in all_leagues if norm((x.get("country") or {}).get("name", "")) == country]
    exact = [x for x in in_country if norm(x["league"]["name"]) in names]
    if exact:
        exact.sort(key=lambda x: (norm(x["league"].get("type", "")) != want_type, names.index(norm(x["league"]["name"]))))
        return exact[0], []
    return None, sorted(x["league"]["name"] for x in in_country)[:15]


def season_started(s: dict, today: date) -> bool:
    try:
        return date.fromisoformat(s["start"]) <= today
    except (KeyError, TypeError, ValueError):
        return False


def summarize_seasons(seasons: list[dict], today: date) -> dict:
    seasons = sorted(seasons, key=lambda s: s.get("year", 0))
    started = [s for s in seasons if season_started(s, today)]

    def cov(s: dict) -> dict:
        c = s.get("coverage") or {}
        fx = c.get("fixtures") or {}
        return {
            "events": fx.get("events"),
            "lineups": fx.get("lineups"),
            "statistics_fixtures": fx.get("statistics_fixtures"),
            "statistics_players": fx.get("statistics_players"),
            "standings": c.get("standings"),
            "players": c.get("players"),
            "injuries": c.get("injuries"),
            "odds": c.get("odds"),
        }

    with_stats = [s for s in started if cov(s)["statistics_fixtures"]]
    return {
        "count": len(seasons),
        "first_year": seasons[0]["year"] if seasons else None,
        "last_year": seasons[-1]["year"] if seasons else None,
        "seasons": [
            {"year": s.get("year"), "start": s.get("start"), "end": s.get("end"), "current": s.get("current"), "coverage": cov(s)}
            for s in seasons
        ],
        "stats_years": [s["year"] for s in with_stats],
        "latest_started": started[-1] if started else None,
    }


def sample_fixture_stats(client: ApiFootballClient, league_id: int, season: dict) -> dict:
    """해당 시즌의 가장 최근 종료 경기 하나의 통계를 받아 어떤 항목이 있는지 본다."""
    fx = client.get("fixtures", {"league": league_id, "season": season["year"]})["response"]
    finished = [f for f in fx if (f["fixture"]["status"] or {}).get("short") in ("FT", "AET", "PEN")]
    span_days = None
    if fx:
        ds = sorted(datetime.fromisoformat(f["fixture"]["date"]) for f in fx)
        span_days = max((ds[-1] - ds[0]).days, 1)
    out = {"season": season["year"], "fixtures": len(fx), "finished": len(finished), "span_days": span_days,
           "sample_fixture": None, "stat_types": [], "xg": None,
           "finished_ids": [f["fixture"]["id"] for f in sorted(finished, key=lambda f: f["fixture"]["date"])][-20:]}
    if not finished:
        return out
    # 시즌 마지막 경기는 승강 플레이오프인 경우가 많아 통계가 빠질 수 있다 → 정규 라운드 중간 경기를 샘플로 쓴다
    regular = [f for f in finished if "regular season" in str(f["league"].get("round", "")).casefold()] or finished
    regular.sort(key=lambda f: f["fixture"]["date"])
    last = regular[len(regular) // 2]
    out["sample_fixture"] = {
        "id": last["fixture"]["id"],
        "date_utc": last["fixture"]["date"],
        "home": last["teams"]["home"]["name"],
        "away": last["teams"]["away"]["name"],
        "score": f'{last["goals"]["home"]}-{last["goals"]["away"]}',
        "round": last["league"].get("round"),
        "venue": (last["fixture"].get("venue") or {}).get("name"),
    }
    stats = client.get("fixtures/statistics", {"fixture": last["fixture"]["id"]})["response"]
    types: dict[str, object] = {}
    for team in stats:
        for st in team.get("statistics", []):
            types.setdefault(st["type"], st["value"])
    out["stat_types"] = list(types)
    xg_val = types.get("expected_goals")
    out["xg"] = None if not stats else (xg_val is not None)
    out["xg_value_example"] = xg_val
    return out


def check_batch_fetch(client: ApiFootballClient, ids: list[int]) -> dict:
    """fixtures?ids= 로 여러 경기를 한 번에 받을 때 통계·이벤트·라인업·선수 기록이 함께 오는지 확인 (1회 호출)."""
    resp = client.get("fixtures", {"ids": "-".join(map(str, ids))})["response"]

    def share(field: str) -> float:
        return sum(1 for f in resp if f.get(field)) / len(resp) if resp else 0.0

    return {"requested": len(ids), "returned": len(resp),
            "with_statistics": share("statistics"), "with_events": share("events"),
            "with_lineups": share("lineups"), "with_players": share("players")}


def yn(v) -> str:
    return {True: "O", False: "X", None: "?"}.get(v, str(v))


def estimate_daily_calls(results: list[dict]) -> tuple[int, int]:
    """매일 갱신 예상 호출 수 (하한, 상한).

    하한: 대회당 [일정·결과 1 + 부상 1] + 종료 경기당 통계 1
    상한: 하한 + 종료 경기당 [선수 기록 1 + 이벤트 1 + 라인업 1]
    """
    low = high = 0
    for r in results:
        s = r.get("sample") or {}
        if not r.get("found"):
            continue
        per_day = (s.get("fixtures") or 0) / (s.get("span_days") or 300)
        low += 2 + per_day
        high += 2 + per_day * 4
    return round(low), round(high)


def render(results: list[dict], status: dict | None, today: date, batch: dict | None = None) -> str:
    lines = [BEGIN, "", f"_자동 생성: {today.isoformat()} — `python -m backend.scripts.survey_api_football`_", ""]
    if status:
        sub = status.get("subscription") or {}
        req = status.get("requests") or {}
        lines += [f"- 현재 키의 요금제: **{sub.get('plan', '?')}**, 하루 한도 {req.get('limit_day', '?')}회, "
                  f"오늘 사용 {req.get('current', '?')}회", ""]

    lines += ["### 대회별 지원 여부·시즌 수", "",
              "| 대회 | API ID | API 대회명 | 시즌 수 | 범위 | 경기통계 있는 시즌 | 이벤트 | 라인업 | 선수기록 | 부상 | 배당 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        if not r["found"]:
            cands = ", ".join(r.get("candidates", [])) or "-"
            lines.append(f"| {r['name_ko']} | - | **찾지 못함** (같은 국가 후보: {cands}) | - | - | - | - | - | - | - | - |")
            continue
        se = r["seasons"]
        c = (se["latest_started"] or {}).get("coverage") or {}
        fx = c.get("fixtures") or {}
        stats_years = se["stats_years"]
        stats_range = f"{stats_years[0]}~{stats_years[-1]} ({len(stats_years)})" if stats_years else "없음"
        lines.append(
            f"| {r['name_ko']} | {r['id']} | {r['api_name']} | {se['count']} | {se['first_year']}~{se['last_year']} | "
            f"{stats_range} | {yn(fx.get('events'))} | {yn(fx.get('lineups'))} | {yn(fx.get('statistics_players'))} | "
            f"{yn(c.get('injuries'))} | {yn(c.get('odds'))} |")
    lines += ["", "> 이벤트~배당 열은 가장 최근에 시작한 시즌의 커버리지 플래그(`/leagues` 응답)입니다.", ""]

    lines += ["### 실제 경기 통계 응답 확인 (xG 포함 여부)", "",
              "| 대회 | 시즌 | 경기 수 | 샘플 경기 (UTC) | xG | 받은 통계 항목 |", "|---|---|---|---|---|---|"]
    for r in results:
        s = r.get("sample")
        if not r["found"] or not s:
            continue
        sf = s.get("sample_fixture")
        game = f"{sf['home']} {sf['score']} {sf['away']} ({sf['date_utc'][:10]})" if sf else "종료 경기 없음"
        xg = yn(s.get("xg")) + (f" ({s['xg_value_example']})" if s.get("xg") else "")
        lines.append(f"| {r['name_ko']} | {s['season']} | {s['fixtures']} | {game} | {xg} | "
                     f"{', '.join(s['stat_types']) or '없음'} |")
    lines += ["", "### 여러 경기 묶음 조회 (`fixtures?ids=`)", ""]
    if batch is None:
        lines.append("- 확인하지 못함 (종료 경기 샘플 없음)")
    elif "error" in batch:
        lines.append(f"- 사용 불가 — API 응답: `{batch['error']}` → 과거 경기 통계는 경기마다 1회씩 호출해야 함")
    else:
        pct = lambda v: f"{v * 100:.0f}%"
        ok = batch["returned"] == batch["requested"] and batch["with_statistics"] > 0.9
        lines += [f"- 경기 {batch['requested']}개 요청 → {batch['returned']}개 응답 ({batch.get('league', '')})",
                  f"- 함께 온 데이터: 통계 {pct(batch['with_statistics'])}, 이벤트 {pct(batch['with_events'])}, "
                  f"라인업 {pct(batch['with_lineups'])}, 선수 기록 {pct(batch['with_players'])}",
                  f"- 결론: {'묶음 조회 가능 — 과거 데이터는 경기 20개당 1회로 수집' if ok else '묶음 조회로 통계를 받을 수 없음 — 경기마다 따로 호출해야 함'}"]
    lo, hi = estimate_daily_calls(results)
    lines += ["", "### 매일 갱신 예상 호출 수", "",
              f"- 활성 대회 기준 하루 약 **{lo}~{hi}회** (경기 통계만 받으면 하한, 선수 기록·이벤트·라인업까지 받으면 상한)",
              "- 과거 시즌 일괄 수집은 경기 1개당 1~4회가 들어가므로 무료 요금제로는 여러 날에 나눠야 한다.", "", END]
    return "\n".join(lines)


def write_readme(section: str) -> None:
    text = README.read_text(encoding="utf-8") if README.exists() else ""
    if BEGIN in text and END in text:
        pre, rest = text.split(BEGIN, 1)
        post = rest.split(END, 1)[1]
        text = pre + section + post
    else:
        text = text.rstrip() + "\n\n## API-Football 조사 결과\n\n" + section + "\n"
    README.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="enabled: false 후보 대회도 조사")
    ap.add_argument("--season", type=int, help="샘플을 받을 시즌 연도 (무료 요금제는 접근 가능한 시즌만 됨)")
    ap.add_argument("--no-sample", action="store_true", help="경기 통계 샘플 호출 생략")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["leagues"]
    targets = [c for c in cfg if args.all or c.get("enabled")]
    today = date.today()
    client = ApiFootballClient()

    status = None
    try:
        status = client.get("status", use_cache=False)["response"]
        if isinstance(status, list):  # 오류 시 빈 리스트
            status = None
    except ApiError as e:
        print(f"[경고] /status 실패: {e}", file=sys.stderr)

    try:
        all_leagues = client.get("leagues")["response"]
    except ApiError as e:
        print(f"[중단] /leagues 호출 실패: {e}\n"
              "API 키를 확인하세요: football/.env 의 API_FOOTBALL_KEY (또는 클라우드 환경의 네트워크 시크릿).",
              file=sys.stderr)
        return 2
    print(f"/leagues: {len(all_leagues)}개 대회")

    results = []
    for c in targets:
        found, cands = match_league(all_leagues, c)
        r = {"key": c["key"], "name_ko": c["name_ko"], "found": bool(found), "candidates": cands}
        if found:
            r.update(id=found["league"]["id"], api_name=found["league"]["name"], api_type=found["league"].get("type"),
                     seasons=summarize_seasons(found.get("seasons", []), today))
            latest = r["seasons"]["latest_started"]
            if args.season is not None:
                latest = next((x for x in found.get("seasons", []) if x.get("year") == args.season), None)
                if latest is None:
                    r["sample_error"] = f"{args.season} 시즌 없음"
            if latest and not args.no_sample:
                try:
                    r["sample"] = sample_fixture_stats(client, r["id"], latest)
                except (ApiError, QuotaGuardError) as e:
                    r["sample_error"] = str(e)
                    print(f"[경고] {c['name_ko']} 샘플 실패: {e}", file=sys.stderr)
        print(f"- {c['name_ko']}: {'ID ' + str(r.get('id')) if found else '찾지 못함'}")
        results.append(r)

    batch = None
    sampled = [r for r in results if len((r.get("sample") or {}).get("finished_ids", [])) >= 2]
    if sampled and not args.no_sample:
        try:
            batch = check_batch_fetch(client, sampled[0]["sample"]["finished_ids"])
            batch["league"] = sampled[0]["name_ko"]
        except (ApiError, QuotaGuardError) as e:
            batch = {"error": str(e), "league": sampled[0]["name_ko"]}
            print(f"[경고] 묶음 조회 확인 실패: {e}", file=sys.stderr)

    SURVEY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SURVEY_JSON.write_text(json.dumps({"date": today.isoformat(), "status": status, "results": results, "batch": batch},
                                      ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    write_readme(render(results, status, today, batch))
    print(f"이번 실행 실제 호출 {client.calls_made}회, 남은 일일 호출 {client.remaining}")
    print(f"README 갱신: {README}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
