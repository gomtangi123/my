"""API-Football (api-sports.io) 클라이언트.

- 키는 환경변수 API_FOOTBALL_KEY 에서만 읽는다 (football/.env 자동 로드).
- 모든 응답 원본을 data/raw 에 캐시하고, 캐시가 있으면 다시 호출하지 않는다.
- 호출마다 data/api_calls.log 에 기록하고, 남은 일일 호출 수가 여유분 이하면 멈춘다.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

FOOTBALL_ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://v3.football.api-sports.io"


class QuotaGuardError(RuntimeError):
    """남은 호출 수가 여유분 이하라 호출을 멈춤."""


class ApiError(RuntimeError):
    pass


def load_dotenv(path: Path = FOOTBALL_ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cache_path(raw_dir: Path, endpoint: str, params: dict) -> Path:
    name = endpoint.strip("/").replace("/", "_") or "root"
    query = urlencode(sorted(params.items()))
    if query:
        safe = query.replace("&", "_").replace("=", "-")
        if len(safe) > 80:
            safe = hashlib.sha1(query.encode()).hexdigest()[:16]
        name = f"{name}__{safe}"
    return raw_dir / f"{name}.json"


class ApiFootballClient:
    def __init__(
        self,
        api_key: str | None = None,
        data_dir: Path = FOOTBALL_ROOT / "data",
        reserve: int = 5,
        session: requests.Session | None = None,
    ) -> None:
        if api_key is None:
            load_dotenv()
            api_key = os.environ.get("API_FOOTBALL_KEY", "")
        # 키가 비어 있어도 진행한다: 클라우드 환경에서는 프록시가 헤더에 키를 넣어준다.
        self.api_key = api_key
        self.raw_dir = data_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = data_dir / "api_calls.log"
        self.reserve = reserve
        self.session = session or requests.Session()
        self.remaining: int | None = None
        self.limit: int | None = None
        self.calls_made = 0

    def get(self, endpoint: str, params: dict | None = None, use_cache: bool = True) -> dict:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        path = cache_path(self.raw_dir, endpoint, params)
        if use_cache and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))

        if self.remaining is not None and self.remaining <= self.reserve:
            raise QuotaGuardError(f"남은 호출 {self.remaining}회 — 여유분 {self.reserve}회 이하라 중단")

        headers = {"x-apisports-key": self.api_key or "proxy-injected"}
        resp = self.session.get(f"{BASE_URL}/{endpoint.strip('/')}", params=params, headers=headers, timeout=30)
        self.calls_made += 1
        rem = resp.headers.get("x-ratelimit-requests-remaining")
        lim = resp.headers.get("x-ratelimit-requests-limit")
        if rem is not None:
            self.remaining = int(rem)
        if lim is not None:
            self.limit = int(lim)
        self._log(endpoint, params, resp.status_code)

        if resp.status_code != 200:
            raise ApiError(f"{endpoint} HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        errors = body.get("errors")
        if errors:  # API-Football은 오류도 200으로 주고 errors 필드에 담는다
            raise ApiError(f"{endpoint} 오류: {errors}")

        path.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        # 분당 제한(무료 요금제는 낮음)을 넘지 않도록 약간 쉰다
        time.sleep(float(os.environ.get("API_FOOTBALL_SLEEP", "6.5")))
        return body

    def _log(self, endpoint: str, params: dict, status: int) -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"{ts}\t{status}\t{endpoint}\t{urlencode(params)}\tremaining={self.remaining}\n")
