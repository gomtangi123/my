"""config/team_names_ko.yaml 의 한글 팀 이름을 teams.name_ko 에 반영한다."""
from __future__ import annotations

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import CONFIG_DIR
from backend.db.schema import Team, TeamAlias


def load_korean_names(path=CONFIG_DIR / "team_names_ko.yaml") -> dict[str, str]:
    if not path.exists():
        return {}
    return {str(k): str(v) for k, v in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).items()}


def apply_korean_names(session: Session, names: dict[str, str] | None = None) -> int:
    """별칭(어느 소스든) 또는 대표 이름이 표에 있으면 한글 이름을 채운다. 바뀐 팀 수를 돌려준다."""
    names = load_korean_names() if names is None else names
    changed = 0
    for team in session.scalars(select(Team)):
        candidates = [team.name] + [a for (a,) in session.execute(select(TeamAlias.alias).where(TeamAlias.team_id == team.id))]
        ko = next((names[c] for c in candidates if c in names), None)
        if ko and team.name_ko != ko:
            team.name_ko = ko
            changed += 1
    return changed


def display_name(name: str, name_ko: str | None) -> str:
    """화면 표기: 한글 이름이 있으면 '한글 (영문)', 없으면 영문."""
    if isinstance(name_ko, str) and name_ko.strip():  # pandas 결측값(NaN)도 '없음'으로 처리
        return f"{name_ko} ({name})"
    return name
