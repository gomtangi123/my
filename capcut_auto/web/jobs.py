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

# 내 소재 폴더 안에 두는 "저장이름 -> 원래이름" 표. 키워드 매칭에 쓴다.
TAGS_FILE = ".tags.json"

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
        self.library_dir = self.work_root / "library"
        for folder in (self.uploads_dir, self.jobs_dir, self.library_dir):
            folder.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, Job] = {}
        self._condition = threading.Condition()

    # ------------------------------------------------------------ 업로드

    def upload_path(self, filename: str) -> tuple[str, Path]:
        upload_id = uuid.uuid4().hex[:12]
        target = self.uploads_dir / upload_id
        target.mkdir(parents=True, exist_ok=True)
        return upload_id, target / _ascii_name(filename)

    def find_upload(self, upload_id: str) -> Path | None:
        folder = self.uploads_dir / _safe_component(upload_id)
        if not folder.is_dir():
            return None
        files = [p for p in folder.iterdir() if p.is_file()]
        return files[0] if files else None

    # ------------------------------------------------- 내 소재 라이브러리

    def library_path(self, library_id: str | None, filename: str) -> tuple[str, Path]:
        """사용자가 올린 자료 이미지/영상을 모아 두는 폴더."""
        library_id = _safe_component(library_id) if library_id else uuid.uuid4().hex[:12]
        folder = self.library_dir / library_id
        folder.mkdir(parents=True, exist_ok=True)
        return library_id, folder / _ascii_name(filename)

    def library_folder(self, library_id: str) -> Path | None:
        folder = self.library_dir / _safe_component(library_id)
        return folder if folder.is_dir() else None

    def remember_tags(self, folder: Path, stored_name: str, original: str) -> None:
        """검색어로 쓸 원래 파일 이름을 따로 적어 둔다.

        파일 자체는 ASCII 이름으로 저장하지만(경로에 한글이 있으면 윈도우에서
        ffmpeg 호출이 깨진다) 키워드 매칭에는 "서울_야경.jpg" 쪽이 필요하다.
        """
        import json

        path = Path(folder) / TAGS_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        data[stored_name] = Path(original).stem
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # -------------------------------------------------------------- 작업

    def create(
        self, source: Path, options: dict[str, Any], display_name: str | None = None
    ) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            id=job_id,
            source=Path(source),
            display_name=display_name or Path(source).name,
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
            project_name=Path(job.display_name).stem or Path(job.source).stem,
            overwrite=True,
        )
        job.draft_path = str(result.path)
        say(
            f"드래프트 생성: 클립 {result.clip_count}개 / 자막 {result.text_count}줄 / "
            f"자료화면 {result.overlay_count}개 / 효과음 {result.sfx_count}개"
        )

        archive = _zip_draft(result.path, job.work_dir / f"{result.name}-draft.zip")
        job.outputs["draft"] = str(archive)

        # 미리보기 렌더.
        # 여기서 실패해도 작업 전체를 실패로 만들지 않는다. 드래프트·자막은
        # 이미 다 만들어졌고, 미리보기는 어디까지나 확인용이다.
        if job.options.get("preview", True):
            try:
                self._render_preview(job, plan, info, cfg, say)
            except Exception as exc:
                say(f"미리보기 렌더 실패 (드래프트와 자막에는 영향 없습니다): {exc}")

    def _render_preview(self, job: Job, plan, info, cfg, say) -> None:
        preview = job.work_dir / "preview.mp4"
        render_mod.render(
            plan,
            cfg,
            preview,
            width=cfg.output.width or info.width or _asset_width(plan),
            height=cfg.output.height or info.height or _asset_height(plan),
            srt_path=Path(job.outputs["srt"]) if "srt" in job.outputs else None,
            work_dir=job.work_dir / ".render",
            has_audio=info.has_audio,
            slideshow=info.is_audio_only,
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
        "pexels_api_key": "assets.pexels_api_key",
        "pixabay_api_key": "assets.pixabay_api_key",
        "giphy_api_key": "assets.giphy_api_key",
        "tenor_api_key": "assets.tenor_api_key",
        "image_scale": "assets.image_scale",
        "aggressive_fillers": "disfluency.aggressive_fillers",
        "retakes": "disfluency.remove_retakes",
        "burn_subtitles": "output.burn_subtitles",
    }
    for key, target in passthrough.items():
        if options.get(key) in (None, ""):
            continue
        for path in (target,) if isinstance(target, str) else target:
            overrides[path] = options[key]

    if options.get("full_coverage"):
        overrides["assets.coverage"] = "full"

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


def _asset_width(plan) -> int:
    """오디오만 들어왔을 때 화면 크기는 첫 이미지에서 가져온다."""
    return (plan.overlays[0].asset.width if plan.overlays else 0) or 1920


def _asset_height(plan) -> int:
    return (plan.overlays[0].asset.height if plan.overlays else 0) or 1080


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


def _ascii_name(filename: str) -> str:
    """디스크에 저장할 이름은 ASCII로만 만든다.

    한글 이름 그대로 두면 윈도우에서 ffprobe 호출이 빈손으로 돌아온다
    (로케일 코드페이지와 UTF-8이 어긋나면서 출력이 통째로 사라진다).
    보여줄 이름은 Job.display_name이 따로 들고 있으므로 사용자는 모른다.
    """
    stem = Path(_safe_name(filename))
    suffix = "".join(ch for ch in stem.suffix if ch.isascii() and (ch.isalnum() or ch == "."))
    ascii_stem = "".join(
        ch if (ch.isascii() and (ch.isalnum() or ch in "-_")) else "_"
        for ch in stem.stem
    ).strip("_")
    if not ascii_stem:
        ascii_stem = "media-" + uuid.uuid4().hex[:8]
    return ascii_stem[:60] + (suffix if len(suffix) > 1 else "")


__all__ = ["Job", "JobStore", "build_config", "MAX_UPLOAD_BYTES"]
