"""웹 UI가 굴리는 편집 작업 관리.

브라우저는 요청을 던져 놓고 바로 돌아가야 하므로 편집은 백그라운드
스레드에서 돌린다. 진행 메시지는 리스트에 쌓아 두고 Condition으로 깨워서
SSE 스트림이 흘려보낸다.
"""

from __future__ import annotations

import shutil
import threading
import time
import traceback
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .. import pipeline, render as render_mod, subtitles
from ..assets import cache as asset_cache
from ..capcut import draft as draft_mod, paths as capcut_paths
from ..config import Config

# 브라우저가 한 번에 올릴 수 있는 최대 크기.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024

State = str  # queued | running | done | error


@dataclass
class Job:
    id: str
    source: Path
    display_name: str
    options: dict[str, Any]
    work_dir: Path
    state: State = "queued"
    messages: list[str] = field(default_factory=list)
    summary: dict | None = None
    plan: dict | None = None
    draft_path: str | None = None
    installed_path: str | None = None
    error: str | None = None
    outputs: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.display_name,
            "state": self.state,
            "messages": list(self.messages),
            "summary": self.summary,
            "plan": self.plan,
            "draft_path": self.draft_path,
            "installed_path": self.installed_path,
            "error": self.error,
            "downloads": sorted(self.outputs),
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class JobStore:
    """작업 등록·조회·진행 알림."""

    def __init__(self, work_root: Path):
        self.work_root = Path(work_root)
        self.uploads_dir = self.work_root / "uploads"
        self.jobs_dir = self.work_root / "jobs"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, Job] = {}
        self._condition = threading.Condition()

    # ------------------------------------------------------------ 업로드

    def upload_path(self, filename: str) -> tuple[str, Path]:
        upload_id = uuid.uuid4().hex[:12]
        safe = _safe_name(filename)
        target = self.uploads_dir / upload_id
        target.mkdir(parents=True, exist_ok=True)
        return upload_id, target / safe

    def find_upload(self, upload_id: str) -> Path | None:
        folder = self.uploads_dir / _safe_component(upload_id)
        if not folder.is_dir():
            return None
        files = [p for p in folder.iterdir() if p.is_file()]
        return files[0] if files else None

    # -------------------------------------------------------------- 작업

    def create(self, source: Path, options: dict[str, Any]) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            id=job_id,
            source=Path(source),
            display_name=Path(source).name,
            options=options,
            work_dir=self.jobs_dir / job_id,
        )
        job.work_dir.mkdir(parents=True, exist_ok=True)
        with self._condition:
            self._jobs[job_id] = job
            self._condition.notify_all()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._condition:
            return self._jobs.get(job_id)

    def start(self, job: Job) -> None:
        thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        thread.start()

    def _publish(self, job: Job, message: str) -> None:
        with self._condition:
            job.messages.append(message)
            self._condition.notify_all()

    def _finish(self, job: Job, state: State, error: str | None = None) -> None:
        with self._condition:
            job.state = state
            job.error = error
            job.finished_at = time.time()
            self._condition.notify_all()

    def watch(self, job_id: str, timeout: float = 0.5) -> Iterator[dict]:
        """SSE용. 새 메시지나 상태 변화가 있을 때마다 이벤트를 흘린다."""
        sent = 0
        last_state: str | None = None
        while True:
            with self._condition:
                job = self._jobs.get(job_id)
                if job is None:
                    yield {"type": "error", "error": "없는 작업입니다."}
                    return
                if sent >= len(job.messages) and job.state == last_state:
                    self._condition.wait(timeout)
                    job = self._jobs.get(job_id)
                    if job is None:
                        return
                pending = job.messages[sent:]
                sent = len(job.messages)
                state = job.state
                snapshot = job.public() if state in ("done", "error") else None

            for message in pending:
                yield {"type": "log", "message": message}
            if state != last_state:
                last_state = state
                yield {"type": "state", "state": state}
            if state in ("done", "error") and snapshot is not None:
                yield {"type": "result", "job": snapshot}
                return

    # ------------------------------------------------------------ 실행부

    def _run(self, job: Job) -> None:
        with self._condition:
            job.state = "running"
            self._condition.notify_all()
        try:
            self._execute(job)
            self._finish(job, "done")
        except Exception as exc:  # 웹 UI에서는 스택 대신 한 줄로 보여 준다
            self._publish(job, f"실패: {exc}")
            traceback.print_exc()
            self._finish(job, "error", str(exc))

    def _execute(self, job: Job) -> None:
        cfg = build_config(job.options)
        say = lambda message: self._publish(job, message)  # noqa: E731

        plan, info, _words = pipeline.analyze(
            job.source, cfg, work_dir=job.work_dir, progress=say
        )

        with self._condition:
            job.summary = plan.summary()
            job.plan = plan.to_dict()

        # 자막
        if plan.subtitles:
            srt = job.work_dir / "subtitles.srt"
            srt.write_text(subtitles.to_srt(plan.subtitles), encoding="utf-8")
            job.outputs["srt"] = str(srt)

        # 편집안
        plan_path = job.work_dir / "plan.json"
        import json

        plan_path.write_text(
            json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        job.outputs["plan"] = str(plan_path)

        # 소재 출처
        if plan.overlays:
            credits = job.work_dir / "credits.md"
            credits.write_text(
                asset_cache.credits_text([o.asset for o in plan.overlays]),
                encoding="utf-8",
            )
            job.outputs["credits"] = str(credits)

        # CapCut 드래프트
        drafts_root = job.work_dir / "drafts"
        result = draft_mod.build(
            plan,
            info,
            cfg,
            drafts_root=drafts_root,
            project_name=Path(job.source).stem,
            overwrite=True,
        )
        job.draft_path = str(result.path)
        say(
            f"드래프트 생성: 클립 {result.clip_count}개 / 자막 {result.text_count}줄 / "
            f"자료화면 {result.overlay_count}개 / 효과음 {result.sfx_count}개"
        )

        archive = _zip_draft(result.path, job.work_dir / f"{result.name}-draft.zip")
        job.outputs["draft"] = str(archive)

        # 미리보기 렌더
        if job.options.get("preview", True):
            preview = job.work_dir / "preview.mp4"
            render_mod.render(
                plan,
                cfg,
                preview,
                width=cfg.output.width or info.width or 1920,
                height=cfg.output.height or info.height or 1080,
                srt_path=Path(job.outputs["srt"]) if "srt" in job.outputs else None,
                work_dir=job.work_dir / ".render",
                has_audio=info.has_audio,
                show_stats=False,
                progress=say,
            )
            job.outputs["preview"] = str(preview)

    # ------------------------------------------------- CapCut 폴더에 설치

    def install(self, job: Job, drafts_dir: str | None = None) -> str:
        if job.state != "done" or not job.draft_path:
            raise ValueError("아직 완료되지 않은 작업입니다.")
        root = Path(drafts_dir) if drafts_dir else capcut_paths.find()
        if root is None:
            raise ValueError(capcut_paths.describe())

        source = Path(job.draft_path)
        target = Path(root) / source.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        job.installed_path = str(target)
        return str(target)


# --------------------------------------------------------------- 설정 변환


def build_config(options: dict[str, Any]) -> Config:
    """웹 폼에서 온 값을 Config로 옮긴다."""
    cfg = Config()
    overrides: dict[str, Any] = {}

    toggles = {
        "silence": "silence.enabled",
        "disfluency": "disfluency.enabled",
        "subtitles": "subtitle.enabled",
        "sfx": "sfx.enabled",
        "assets": "assets.enabled",
    }
    for key, path in toggles.items():
        if key in options:
            overrides[path] = bool(options[key])

    if not options.get("subtitles", True) and not options.get("disfluency", True):
        # 자막도 버벅임도 안 쓸 거면 음성 인식 자체가 필요 없다 — 훨씬 빠르다.
        overrides["transcribe.enabled"] = False

    passthrough = {
        "model": "transcribe.model",
        "language": ("transcribe.language", "disfluency.language"),
        "min_silence": "silence.min_silence",
        "padding": "silence.keep_padding",
        "max_chars": "subtitle.max_chars",
        "sfx_volume": "sfx.volume",
        "sfx_per_minute": "sfx.max_per_minute",
        "assets_per_minute": "assets.max_per_minute",
        "assets_folder": "assets.local_folder",
        "sfx_library": "sfx.library",
        "aggressive_fillers": "disfluency.aggressive_fillers",
        "retakes": "disfluency.remove_retakes",
        "burn_subtitles": "output.burn_subtitles",
    }
    for key, target in passthrough.items():
        if options.get(key) in (None, ""):
            continue
        for path in (target,) if isinstance(target, str) else target:
            overrides[path] = options[key]

    if options.get("prefer"):
        first = options["prefer"]
        rest = tuple(k for k in ("video", "image", "gif") if k != first)
        overrides["assets.prefer"] = (first,) + rest

    if options.get("vertical"):
        overrides["output.width"] = 1080
        overrides["output.height"] = 1920

    cfg.apply_overrides(overrides)
    return cfg


# ------------------------------------------------------------------- 유틸


def _zip_draft(draft_dir: Path, target: Path) -> Path:
    """드래프트 폴더를 zip으로. 절대 경로 주의 문구를 함께 넣는다."""
    draft_dir = Path(draft_dir)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(draft_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(draft_dir.parent))
        archive.writestr(
            "읽어주세요.txt",
            "CapCut 드래프트는 원본 영상과 소재를 절대 경로로 참조합니다.\n"
            "다른 PC에서 열면 소재가 비어 보일 수 있습니다. 같은 PC에서는\n"
            "웹 UI의 'CapCut에 설치' 버튼을 쓰는 편이 확실합니다.\n",
        )
    return target


def _safe_component(value: str) -> str:
    """경로 탈출 방지 — 구분자와 상위 참조를 제거한다."""
    cleaned = value.replace("\\", "/").split("/")[-1]
    return "".join(ch for ch in cleaned if ch.isalnum() or ch in "-_") or "unnamed"


def _safe_name(filename: str) -> str:
    cleaned = Path(filename.replace("\\", "/")).name.strip() or "video.mp4"
    banned = '<>:"|?*\0'
    cleaned = "".join("_" if ch in banned else ch for ch in cleaned)
    return cleaned.lstrip(".") or "video.mp4"


__all__ = ["Job", "JobStore", "build_config", "MAX_UPLOAD_BYTES"]
