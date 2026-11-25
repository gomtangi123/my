"""7단계: 자동 작업 파이프라인·스케줄러 테스트 (실제 수집 없이 가짜 단계)."""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from backend.jobs import daily, scheduler


@pytest.fixture
def paths(tmp_path):
    return {"status_file": tmp_path / "status.json", "lock_file": tmp_path / "daily.lock"}


def test_success_records_status(paths):
    calls = []
    steps = [("수집", lambda: calls.append("c") or 0, False), ("예측", lambda: calls.append("p"), False)]
    r = daily.run_pipeline(steps=steps, sleep=lambda s: None, **paths)
    assert r.ok and calls == ["c", "p"]
    st = json.loads(paths["status_file"].read_text())
    assert st["last_full"]["ok"] and st["last_success_full"] == r.finished_at
    assert not paths["lock_file"].exists()  # 끝나면 잠금 해제


def test_transient_failure_is_retried(paths):
    attempts, slept = [], []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("일시적 네트워크 오류")
        return 0

    r = daily.run_pipeline(steps=[("수집", flaky, False)], retries=2, retry_wait=5, sleep=slept.append, **paths)
    assert r.ok and len(attempts) == 3 and slept == [5, 5] and r.steps[0].attempts == 3


def test_final_failure_logged_next_steps_still_run(paths):
    ran = []
    steps = [("수집", lambda: 1, False), ("예측", lambda: ran.append("p"), False)]
    r = daily.run_pipeline(steps=steps, retries=1, retry_wait=0, sleep=lambda s: None, **paths)
    assert not r.ok and ran == ["p"]
    st = json.loads(paths["status_file"].read_text())
    assert "last_success_full" not in st  # 실패한 날은 성공 시각을 갱신하지 않는다 → 따라잡기 판단에 쓰임
    assert st["history"][-1]["failed_steps"] == ["수집"]
    assert r.steps[0].error == "종료 코드 1"


def test_critical_failure_skips_rest(paths):
    ran = []
    r = daily.run_pipeline(steps=[("a", lambda: 1, True), ("b", lambda: ran.append(1), False)],
                           retries=0, sleep=lambda s: None, **paths)
    assert not r.ok and ran == [] and len(r.steps) == 1


def test_lock_prevents_overlap_but_stale_lock_is_ignored(paths):
    paths["lock_file"].write_text("123")
    ran = []
    r = daily.run_pipeline(steps=[("a", lambda: ran.append(1), False)], sleep=lambda s: None, **paths)
    assert not r.ok and ran == [] and r.steps[0].name == "잠금"
    assert paths["lock_file"].exists()  # 남의 잠금은 지우지 않는다
    old = time.time() - daily.LOCK_STALE_SECONDS - 10
    os.utime(paths["lock_file"], (old, old))  # 오래된 잠금 = 죽은 작업이 남긴 것
    r = daily.run_pipeline(steps=[("a", lambda: ran.append(1), False)], sleep=lambda s: None, **paths)
    assert r.ok and ran == [1]


def test_light_mode_recorded_separately(paths):
    daily.run_pipeline(light=True, steps=[("a", lambda: 0, False)], sleep=lambda s: None, **paths)
    st = json.loads(paths["status_file"].read_text())
    assert "last_light" in st and "last_full" not in st


def test_default_steps_weekly_evaluation():
    monday = datetime(2026, 11, 30, 20, 0, tzinfo=timezone.utc) + timedelta(hours=-11)  # 11/30(월) 18:00 KST
    tuesday = monday + timedelta(days=1)
    assert [s[0] for s in daily.default_steps(False, monday)] == ["데이터 갱신", "예측 갱신", "모델 재검증"]
    assert [s[0] for s in daily.default_steps(False, tuesday)] == ["데이터 갱신", "예측 갱신"]
    assert [s[0] for s in daily.default_steps(True, monday)] == ["데이터 갱신", "예측 갱신"]


def test_catch_up_decision(tmp_path):
    f = tmp_path / "status.json"
    now = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
    assert scheduler.needs_catch_up(now, f)  # 기록 없음
    f.write_text(json.dumps({"last_success_full": (now - timedelta(hours=20)).isoformat()}))
    assert not scheduler.needs_catch_up(now, f)
    f.write_text(json.dumps({"last_success_full": (now - timedelta(hours=30)).isoformat()}))
    assert scheduler.needs_catch_up(now, f)


def test_scheduler_times_are_kst():
    s = scheduler.build_scheduler()
    jobs = {j.id: j for j in s.get_jobs()}
    assert set(jobs) == {"daily_full", "light"}
    base = datetime(2026, 11, 25, 12, 0, tzinfo=daily.KST)  # 낮 12시 KST
    nxt = jobs["daily_full"].trigger.get_next_fire_time(None, base)
    assert (nxt.hour, nxt.minute, nxt.day) == (5, 0, 26)  # 다음 날 새벽 5시 KST
    assert jobs["light"].trigger.get_next_fire_time(None, base).hour == 17
