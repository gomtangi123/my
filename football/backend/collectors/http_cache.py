"""키 없는 공개 데이터 소스용 HTTP 다운로드 + 원본 캐시.

- 원본 응답을 data/raw/<source>/... 에 그대로 저장한다.
- max_age=None 이면 한 번 받은 파일은 다시 받지 않는다 (종료된 시즌).
- max_age 가 있으면 그 시간보다 오래된 캐시만 다시 받는다 (진행 중인 시즌, 다가오는 일정).
- 모든 실제 호출은 data/http_calls.log 에 남기고, 호스트별로 간격을 둔다 (상대 서버 배려).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from backend.config import FOOTBALL_ROOT

DATA_DIR = FOOTBALL_ROOT / "data"
MAX_RETRIES = 3
USER_AGENT = "football-stats-study/0.1 (personal project)"


class HttpCache:
    def __init__(self, data_dir: Path = DATA_DIR, min_interval: dict[str, float] | None = None,
                 session: requests.Session | None = None, sleep=time.sleep) -> None:
        self.raw_dir = data_dir / "raw"
        self.log_path = data_dir / "http_calls.log"
        self.min_interval = min_interval or {}
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self._last_call: dict[str, float] = {}
        self._sleep = sleep
        self.calls = 0

    def get(self, url: str, cache_rel: str, max_age: timedelta | None = None) -> bytes:
        path = self.raw_dir / cache_rel
        if path.exists():
            age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if max_age is None or age < max_age:
                return path.read_bytes()

        host = urlparse(url).netloc
        for attempt in range(1, MAX_RETRIES + 2):
            wait = self.min_interval.get(host, 1.0) - (time.monotonic() - self._last_call.get(host, -1e9))
            if wait > 0:
                self._sleep(wait)
            resp = self.session.get(url, timeout=60)
            self._last_call[host] = time.monotonic()
            self.calls += 1
            self._log(url, resp.status_code, len(resp.content))
            if resp.status_code != 429 or attempt > MAX_RETRIES:
                break
            # 호출 제한에 걸림 → 서버가 알려준 시간(없으면 점점 길게) 쉬고 다시 시도
            retry_after = resp.headers.get("Retry-After", "")
            self._sleep(float(retry_after) if retry_after.isdigit() else 30.0 * attempt)
        if resp.status_code == 404:
            raise FileNotFoundError(url)
        resp.raise_for_status()

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(resp.content)
        tmp.replace(path)  # 받다가 끊겨도 깨진 캐시가 남지 않게
        return resp.content

    def _log(self, url: str, status: int, size: int) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"{ts}\t{status}\t{size}\t{url}\n")
