"""설정 파일(config/leagues.yaml, config/settings.yaml) 로더.

리그 목록은 이 모듈을 통해서만 읽는다 — 코드에 리그 ID를 하드코딩하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

FOOTBALL_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = FOOTBALL_ROOT / "config"

VALID_TYPES = {"league", "cup"}
VALID_REGIONS = {"europe", "asia"}
VALID_SEASON_FORMATS = {"cross_year", "calendar_year"}


@dataclass(frozen=True)
class LeagueConfig:
    key: str
    name_ko: str
    enabled: bool
    type: str
    region: str
    timezone: str
    season_format: str
    priority: int
    sources: dict = field(default_factory=dict)  # {"football_data": {...}, "thesportsdb": {...}, "api_football": {...}}
    standings: dict = field(default_factory=dict)  # 순위 규칙 {"tiebreak": [...], "split": {...}}


def load_leagues(path: Path = CONFIG_DIR / "leagues.yaml", enabled_only: bool = False) -> list[LeagueConfig]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["leagues"]
    out: list[LeagueConfig] = []
    seen: set[str] = set()
    for item in raw:
        key = item["key"]
        if key in seen:
            raise ValueError(f"leagues.yaml: 중복된 key {key}")
        seen.add(key)
        for name, allowed in (("type", VALID_TYPES), ("region", VALID_REGIONS), ("season_format", VALID_SEASON_FORMATS)):
            if item.get(name) not in allowed:
                raise ValueError(f"leagues.yaml: {key}.{name} 값 {item.get(name)!r} 은 {sorted(allowed)} 중 하나여야 함")
        tb = (item.get("standings") or {}).get("tiebreak")
        if tb and (tb[0] != "points" or not set(tb) <= {"points", "gd", "gf"}):
            raise ValueError(f"leagues.yaml: {key}.standings.tiebreak 은 points 로 시작하고 points/gd/gf 만 쓸 수 있음")
        sources = {s: item[s] for s in ("football_data", "thesportsdb", "api_football") if item.get(s)}
        lc = LeagueConfig(
            key=key,
            name_ko=item["name_ko"],
            enabled=bool(item.get("enabled", False)),
            type=item["type"],
            region=item["region"],
            timezone=item["timezone"],
            season_format=item["season_format"],
            priority=int(item.get("priority", 9)),
            sources=sources,
            standings=item.get("standings") or {},
        )
        if not enabled_only or lc.enabled:
            out.append(lc)
    return out


def load_settings(path: Path = CONFIG_DIR / "settings.yaml") -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
