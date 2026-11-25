"""매일 자동 작업 파이프라인: 데이터 갱신 → (중복 정리·한글 이름) → 예측 갱신 → (월요일) 모델 재검증.

    python -m backend.jobs.daily              # 전체 (매일 새벽)
    python -m backend.jobs.daily --light      # 가벼운 갱신: 유럽 일정·결과 파일 + 예측 (하루 몇 번)

- 단계마다 실패해도 로그를 남기고, 일시적 오류에 대비해 몇 분 뒤 다시 시도한다.
- 그래도 실패하면 상태 파일에 기록하고 종료 코드 1 — 다음 실행(다음 날)이 처음부터 다시 받는다
  (진행 중 시즌은 매번 전체를 다시 확인하므로 하루 이틀 빠져도 따라잡는다).
- 같은 작업이 겹쳐 돌지 않게 잠금 파일을 쓴다.
- 로그: data/logs/daily_YYYYMMDD.log, 상태: data/jobs/status.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from backend.config import FOOTBALL_ROOT, load_leagues

KST = ZoneInfo("Asia/Seoul")
DATA = FOOTBALL_ROOT / "data"
STATUS_FILE = DATA / "jobs" / "status.json"
LOCK_FILE = DATA / "jobs" / "daily.lock"
LOG_DIR = DATA / "logs"
LOCK_STALE_SECONDS = 6 * 3600  # 이보다 오래된 잠금은 죽은 작업이 남긴 것으로 본다

log = logging.getLogger("daily")


class AlreadyRunning(RuntimeError):
    pass


@dataclass
class StepResult:
    name: str
    ok: bool
    attempts: int
    seconds: float
    error: str | None = None


@dataclass
class RunResult:
    mode: str
    started_at: str
    finished_at: str | None = None
    ok: bool = False
    steps: list[StepResult] = field(default_factory=list)


@contextmanager
def single_instance(lock_file: Path = LOCK_FILE):
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    if lock_file.exists() and time.time() - lock_file.stat().st_mtime < LOCK_STALE_SECONDS:
        raise AlreadyRunning(f"다른 작업이 실행 중 (잠금 파일: {lock_file})")
    lock_file.write_text(f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}")
    try:
        yield
    finally:
        lock_file.unlink(missing_ok=True)


def run_step(name: str, fn: Callable[[], int | None], retries: int, retry_wait: float, sleep=time.sleep) -> StepResult:
    """fn 이 예외를 내거나 0이 아닌 값을 돌려주면 실패. retries 번까지 retry_wait 초 쉬고 다시 시도."""
    start = time.monotonic()
    err = None
    for attempt in range(1, retries + 2):
        try:
            code = fn()
            if code in (None, 0):
                log.info("[%s] 성공 (%d번째 시도, %.0f초)", name, attempt, time.monotonic() - start)
                return StepResult(name, True, attempt, round(time.monotonic() - start, 1))
            err = f"종료 코드 {code}"
        except Exception as e:  # noqa: BLE001 — 어떤 오류든 기록하고 다음 단계/다음 날로
            err = f"{type(e).__name__}: {e}"
            log.error("[%s] 오류\n%s", name, traceback.format_exc())
        if attempt <= retries:
            log.warning("[%s] 실패 (%s) — %d초 뒤 다시 시도 (%d/%d)", name, err, retry_wait, attempt, retries)
            sleep(retry_wait)
    log.error("[%s] 최종 실패: %s — 다음 실행에서 다시 시도합니다", name, err)
    return StepResult(name, False, retries + 1, round(time.monotonic() - start, 1), err)


def default_steps(light: bool, now: datetime) -> list[tuple[str, Callable[[], int | None], bool]]:
    """(이름, 함수, 실패하면 뒤 단계를 건너뛸지)"""
    from backend.jobs import collect, predict
    from backend.models import evaluate

    if light:
        # TheSportsDB(느림) 대회는 빼고 Football-Data.co.uk 대회만: 일정 파일 6시간, 시즌 파일 12시간 캐시
        keys = [l.key for l in load_leagues(enabled_only=True) if "thesportsdb" not in l.sources]
        collect_fn = lambda: collect.run("daily", keys, seasons=1)  # noqa: E731
    else:
        collect_fn = lambda: collect.run("daily", None, seasons=1)  # noqa: E731
    steps = [
        ("데이터 갱신", collect_fn, False),  # 일부 대회만 실패해도 예측은 진행 (있는 데이터로)
        ("예측 갱신", lambda: (predict.run(days=14), 0)[1], False),
    ]
    if not light and now.astimezone(KST).weekday() == 0:  # 월요일: 모델 재검증 + REPORT.md 갱신 (약 3분)
        steps.append(("모델 재검증", lambda: evaluate.main([]), False))
    return steps


def save_status(result: RunResult, status_file: Path = STATUS_FILE) -> None:
    status_file.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else {}
    data[f"last_{result.mode}"] = asdict(result)
    if result.ok:
        data[f"last_success_{result.mode}"] = result.finished_at
    history = data.get("history", [])
    history.append({"mode": result.mode, "started_at": result.started_at, "ok": result.ok,
                    "failed_steps": [s.name for s in result.steps if not s.ok]})
    data["history"] = history[-60:]
    tmp = status_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(status_file)


def setup_logging(now: datetime) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"daily_{now.astimezone(KST):%Y%m%d}.log"
    root = logging.getLogger()
    if not any(isinstance(h, logging.FileHandler) and Path(h.baseFilename) == path for h in root.handlers):
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(fh)
    root.setLevel(logging.INFO)
    return path


def run_pipeline(light: bool = False, steps=None, retries: int = 2, retry_wait: float = 600,
                 status_file: Path = STATUS_FILE, lock_file: Path = LOCK_FILE, sleep=time.sleep) -> RunResult:
    now = datetime.now(timezone.utc)
    mode = "light" if light else "full"
    result = RunResult(mode=mode, started_at=now.isoformat(timespec="seconds"))
    try:
        with single_instance(lock_file):
            log.info("===== %s 작업 시작 (%s KST) =====", "가벼운 갱신" if light else "매일", now.astimezone(KST).strftime("%Y-%m-%d %H:%M"))
            for name, fn, critical in (steps if steps is not None else default_steps(light, now)):
                r = run_step(name, fn, retries, retry_wait, sleep)
                result.steps.append(r)
                if not r.ok and critical:
                    log.error("[%s] 실패로 남은 단계를 건너뜁니다", name)
                    break
    except AlreadyRunning as e:
        log.warning("%s — 이번 실행은 건너뜀", e)
        result.steps.append(StepResult("잠금", False, 0, 0.0, str(e)))
    result.ok = bool(result.steps) and all(s.ok for s in result.steps)
    result.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_status(result, status_file)
    log.info("===== 작업 %s =====", "완료" if result.ok else "일부 실패 (다음 실행에서 다시 시도)")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="매일 자동 작업 (수집 → 예측 → 주간 재검증)")
    ap.add_argument("--light", action="store_true", help="가벼운 갱신 (유럽 리그 파일 + 예측)")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--retry-wait", type=float, default=600, help="재시도 전 대기(초)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    setup_logging(datetime.now(timezone.utc))
    r = run_pipeline(light=args.light, retries=args.retries, retry_wait=args.retry_wait)
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
