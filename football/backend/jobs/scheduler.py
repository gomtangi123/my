"""자동 실행 스케줄러 (APScheduler). 한국 시간 기준.

    python -m backend.jobs.scheduler          # 계속 실행되며 정해진 시각에 작업을 돌린다

일정 (KST)
- 매일 05:00  전체 작업: 모든 대회 갱신 → 예측 → (월요일) 모델 재검증
- 11:00, 17:00, 23:00  가벼운 갱신: 유럽 리그 일정·결과 파일 + 예측
  (Football-Data.co.uk 일정 파일이 주중에 늦게 채워지므로 주말 경기 예측을 경기 전에 만들기 위함)

- 서버가 꺼져 있다 켜졌을 때 마지막 전체 작업 성공이 26시간보다 오래됐으면 바로 한 번 따라잡는다.
- 실패한 작업은 로그·상태 파일에 남고, 다음 날 같은 시각에 다시 돈다 (진행 중 시즌 전체를 다시 확인).
- cron 을 쓰고 싶으면 README 의 crontab 예시 참고 (둘 중 하나만 쓴다).
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.jobs.daily import KST, STATUS_FILE, run_pipeline, setup_logging

log = logging.getLogger("scheduler")
CATCH_UP_AFTER = timedelta(hours=26)


def needs_catch_up(now: datetime, status_file=STATUS_FILE) -> bool:
    if not status_file.exists():
        return True
    last = json.loads(status_file.read_text(encoding="utf-8")).get("last_success_full")
    return last is None or now - datetime.fromisoformat(last) > CATCH_UP_AFTER


def job(light: bool) -> None:
    setup_logging(datetime.now(timezone.utc))
    try:
        run_pipeline(light=light)
    except Exception:  # 스케줄러 자체는 죽지 않게
        log.exception("작업 실행 중 예상하지 못한 오류")


def build_scheduler() -> BlockingScheduler:
    sched = BlockingScheduler(timezone=KST, job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    sched.add_job(job, CronTrigger(hour=5, minute=0, timezone=KST), kwargs={"light": False}, id="daily_full",
                  name="매일 전체 작업")
    sched.add_job(job, CronTrigger(hour="11,17,23", minute=0, timezone=KST), kwargs={"light": True}, id="light",
                  name="가벼운 갱신")
    return sched


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sched = build_scheduler()
    if needs_catch_up(datetime.now(timezone.utc)):
        log.info("마지막 전체 작업이 오래됨 → 지금 한 번 실행")
        sched.add_job(job, kwargs={"light": False}, id="catch_up", name="따라잡기")
    for j in sched.get_jobs():
        log.info("예약: %s", j.name)
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("스케줄러 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
