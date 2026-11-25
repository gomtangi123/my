"""RawMatch → DB 저장. 어떤 소스에서 왔든 같은 규칙으로 넣는다.

팀 찾기 순서
1) 외부 ID 매핑 (source, 외부 팀 ID)
2) 같은 소스의 별칭 (source, 팀 이름)
3) 이름 정규화 후 다른 소스 별칭·대표 이름과 정확히 일치 → 같은 팀으로 연결 (예: J1 팀이 ACL에도 나올 때)
4) 없으면 새 팀 생성
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.collectors.base import STATUS_FINISHED, STATUS_POSTPONED, STATUS_SCHEDULED, RawMatch, RawTeamStats
from backend.db.schema import ExternalId, League, Match, MatchOdds, MatchTeamStats, Season, Team, TeamAlias


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return "".join(c for c in s if c.isalnum())


@dataclass
class StoreReport:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    teams_created: list[str] = field(default_factory=list)
    teams_linked: list[str] = field(default_factory=list)  # 다른 소스 팀과 이름으로 연결된 경우 (확인용)

    def merge(self, o: "StoreReport") -> None:
        self.inserted += o.inserted
        self.updated += o.updated
        self.unchanged += o.unchanged
        self.teams_created += o.teams_created
        self.teams_linked += o.teams_linked


class Store:
    def __init__(self, session: Session) -> None:
        self.s = session
        self._team_cache: dict[tuple[str, str], int] = {}

    # ── 시즌 ──
    def season(self, league_key: str, label: str) -> Season:
        lg = self.s.scalar(select(League).where(League.key == league_key))
        if lg is None:
            raise ValueError(f"DB에 없는 대회 {league_key} — 먼저 python -m backend.db.init_db 실행")
        se = self.s.scalar(select(Season).where(Season.league_id == lg.id, Season.label == label))
        if se is None:
            se = Season(league_id=lg.id, label=label)
            self.s.add(se)
            self.s.flush()
        return se

    def _touch_season_dates(self, se: Season, kickoffs: list[datetime]) -> None:
        if not kickoffs:
            return
        lo, hi = min(kickoffs).date(), max(kickoffs).date()
        se.start_date = min(filter(None, [se.start_date, lo]))
        se.end_date = max(filter(None, [se.end_date, hi]))

    # ── 팀 ──
    def team(self, source: str, name: str, ext_id: str | None, country: str | None, report: StoreReport) -> int:
        ck = (source, ext_id or f"name:{name}")
        if ck in self._team_cache:
            return self._team_cache[ck]
        team_id = None
        if ext_id:
            team_id = self.s.scalar(select(ExternalId.entity_id).where(
                ExternalId.entity_type == "team", ExternalId.source == source, ExternalId.external_id == ext_id))
        if team_id is None:
            team_id = self.s.scalar(select(TeamAlias.team_id).where(TeamAlias.source == source, TeamAlias.alias == name))
        if team_id is None:
            key = norm_name(name)
            for tid, alias in self.s.execute(select(TeamAlias.team_id, TeamAlias.alias)):
                if norm_name(alias) == key:
                    team_id = tid
                    report.teams_linked.append(f"{source}:{name} → 기존 팀 #{tid} ({alias})")
                    break
        if team_id is None:
            display = name
            if self.s.scalar(select(Team.id).where(Team.name == display)) is not None:
                display = f"{name} ({country or source})"
            t = Team(name=display, country=country)
            self.s.add(t)
            self.s.flush()
            team_id = t.id
            report.teams_created.append(display)
        if self.s.scalar(select(TeamAlias.id).where(TeamAlias.source == source, TeamAlias.alias == name)) is None:
            self.s.add(TeamAlias(team_id=team_id, source=source, alias=name))
        if ext_id and self.s.scalar(select(ExternalId.id).where(
                ExternalId.entity_type == "team", ExternalId.source == source, ExternalId.external_id == ext_id)) is None:
            self.s.add(ExternalId(entity_type="team", entity_id=team_id, source=source, external_id=ext_id))
        self.s.flush()
        self._team_cache[ck] = team_id
        return team_id

    # ── 경기 ──
    def save_matches(self, matches: list[RawMatch], country: str | None = None) -> StoreReport:
        report = StoreReport()
        by_season: dict[tuple[str, str], list[RawMatch]] = {}
        for m in matches:
            by_season.setdefault((m.league_key, m.season_label), []).append(m)
        for (league_key, label), ms in by_season.items():
            se = self.season(league_key, label)
            for m in ms:
                self._save_one(se, m, country, report)
            self._touch_season_dates(se, [m.kickoff_utc for m in ms])
        self.s.flush()
        return report

    def _save_one(self, se: Season, m: RawMatch, country: str | None, report: StoreReport) -> None:
        home = self.team(m.source, m.home_name, m.home_ext_id, country, report)
        away = self.team(m.source, m.away_name, m.away_ext_id, country, report)
        match_id = self.s.scalar(select(ExternalId.entity_id).where(
            ExternalId.entity_type == "match", ExternalId.source == m.source, ExternalId.external_id == m.external_id))
        row = self.s.get(Match, match_id) if match_id else None
        if row is None:  # 다른 소스로 이미 들어온 같은 경기인지
            row = self.s.scalar(select(Match).where(Match.season_id == se.id, Match.home_team_id == home,
                                                    Match.away_team_id == away, Match.kickoff_utc == m.kickoff_utc))
        fields = dict(
            season_id=se.id, kickoff_utc=m.kickoff_utc, round=m.round, stage=m.stage, home_team_id=home,
            away_team_id=away, neutral_venue=m.neutral_venue, venue=m.venue, status=m.status,
            home_goals=m.home_goals, away_goals=m.away_goals, ht_home_goals=m.ht_home_goals,
            ht_away_goals=m.ht_away_goals, result_90=m.result_90, decided_by=m.decided_by, referee=m.referee,
        )
        if row is None:
            row = Match(**fields)
            self.s.add(row)
            self.s.flush()
            report.inserted += 1
        else:
            if row.status == STATUS_FINISHED and m.status != STATUS_FINISHED:
                fields = {}  # 이미 끝난 경기를 일정 데이터로 덮어쓰지 않는다
            changed = {k: v for k, v in fields.items() if v is not None and getattr(row, k) != v}
            for k, v in changed.items():
                setattr(row, k, v)
            if changed:
                report.updated += 1
            else:
                report.unchanged += 1
        if self.s.scalar(select(ExternalId.id).where(ExternalId.entity_type == "match", ExternalId.source == m.source,
                                                     ExternalId.external_id == m.external_id)) is None:
            self.s.add(ExternalId(entity_type="match", entity_id=row.id, source=m.source, external_id=m.external_id))
        self._save_stats(row.id, home, True, m.home_stats, m.source)
        self._save_stats(row.id, away, False, m.away_stats, m.source)
        for o in m.odds:
            od = self.s.scalar(select(MatchOdds).where(MatchOdds.match_id == row.id, MatchOdds.bookmaker == o.bookmaker,
                                                       MatchOdds.kind == o.kind))
            if od is None:
                self.s.add(MatchOdds(match_id=row.id, bookmaker=o.bookmaker, kind=o.kind, home=o.home, draw=o.draw,
                                     away=o.away, source=m.source))
            else:
                od.home, od.draw, od.away = o.home, o.draw, o.away

    def _save_stats(self, match_id: int, team_id: int, is_home: bool, st: RawTeamStats | None, source: str) -> None:
        if st is None:
            return
        row = self.s.scalar(select(MatchTeamStats).where(MatchTeamStats.match_id == match_id,
                                                         MatchTeamStats.team_id == team_id))
        if row is None:
            row = MatchTeamStats(match_id=match_id, team_id=team_id, is_home=is_home, source=source)
            self.s.add(row)
        for k, v in vars(st).items():
            if v is not None:
                setattr(row, k, v)

    # ── 정리 ──
    def mark_stale_scheduled(self, now: datetime | None = None, grace: timedelta = timedelta(days=3)) -> int:
        """시작 시간이 한참 지났는데 결과가 없는 일정은 연기된 것으로 표시한다 (일정이 바뀐 경기)."""
        now = now or datetime.now(timezone.utc)
        rows = self.s.scalars(select(Match).where(Match.status == STATUS_SCHEDULED, Match.kickoff_utc < now - grace)).all()
        for r in rows:
            r.status = STATUS_POSTPONED
        return len(rows)


def summarize(report: StoreReport) -> str:
    created = Counter(report.teams_created)
    return (f"신규 {report.inserted} / 갱신 {report.updated} / 변화 없음 {report.unchanged} 경기, "
            f"새 팀 {len(created)}개, 이름으로 연결된 팀 {len(report.teams_linked)}개")
