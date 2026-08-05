"""웹 UI 서버 테스트 — 진짜 소켓을 열고 HTTP로 두드린다."""

import json
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

from capcut_auto.web.jobs import JobStore, build_config, _safe_name, _zip_draft
from capcut_auto.web.server import Server


# --------------------------------------------------------------- 설정 변환


class TestBuildConfig:
    def test_toggles_map_to_config(self):
        cfg = build_config({"silence": False, "sfx": False, "assets": True})
        assert cfg.silence.enabled is False
        assert cfg.sfx.enabled is False
        assert cfg.assets.enabled is True

    def test_transcription_skipped_when_not_needed(self):
        # 자막도 버벅임도 안 쓰면 Whisper를 돌릴 이유가 없다
        cfg = build_config({"subtitles": False, "disfluency": False})
        assert cfg.transcribe.enabled is False

    def test_transcription_kept_when_subtitles_wanted(self):
        cfg = build_config({"subtitles": True, "disfluency": False})
        assert cfg.transcribe.enabled is True

    def test_numeric_passthrough(self):
        cfg = build_config({"min_silence": 0.5, "max_chars": 14, "sfx_volume": 0.2})
        assert cfg.silence.min_silence == 0.5
        assert cfg.subtitle.max_chars == 14
        assert cfg.sfx.volume == 0.2

    def test_language_sets_both_places(self):
        cfg = build_config({"language": "en"})
        assert cfg.transcribe.language == "en"
        assert cfg.disfluency.language == "en"

    def test_blank_strings_are_ignored(self):
        cfg = build_config({"assets_folder": "", "sfx_library": ""})
        assert cfg.assets.local_folder is None
        assert cfg.sfx.library is None

    def test_prefer_reorders_kinds(self):
        cfg = build_config({"prefer": "gif"})
        assert cfg.assets.prefer[0] == "gif"
        assert set(cfg.assets.prefer) == {"video", "image", "gif"}

    def test_vertical_sets_shorts_canvas(self):
        cfg = build_config({"vertical": True})
        assert (cfg.output.width, cfg.output.height) == (1080, 1920)

    def test_defaults_when_empty(self):
        cfg = build_config({})
        assert cfg.silence.enabled and cfg.subtitle.enabled


# ------------------------------------------------------------------ 유틸


class TestSafeName:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("영상.mp4", "영상.mp4"),
            ("../../etc/passwd", "passwd"),
            ("C:\\Users\\me\\a.mp4", "a.mp4"),
            ("a<b>c.mp4", "a_b_c.mp4"),
            ("", "video.mp4"),
        ],
    )
    def test_sanitises(self, raw, expected):
        assert _safe_name(raw) == expected


def test_zip_draft_includes_files_and_notice(tmp_path):
    draft = tmp_path / "drafts" / "talk"
    draft.mkdir(parents=True)
    (draft / "draft_content.json").write_text("{}", encoding="utf-8")
    archive = _zip_draft(draft, tmp_path / "out.zip")
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert "talk/draft_content.json" in names
    assert any("읽어주세요" in n for n in names)


# ------------------------------------------------------------------ 서버


@pytest.fixture
def server(tmp_path):
    store = JobStore(tmp_path / "work")
    srv = Server(("127.0.0.1", 0), store)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base, store, srv
    srv.shutdown()
    srv.server_close()


def get(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read(), dict(response.headers)


def post_json(url, payload):
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def put_bytes(url, data):
    request = urllib.request.Request(url, data=data, method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


class TestRoutes:
    def test_index_is_served(self, server):
        base, _store, _srv = server
        status, body, headers = get(base + "/")
        assert status == 200
        assert "capcut-auto" in body.decode("utf-8")
        assert headers["Content-Type"].startswith("text/html")

    def test_config_endpoint(self, server):
        base, _store, _srv = server
        status, body, _ = get(base + "/api/config")
        assert status == 200
        data = json.loads(body)
        assert set(data) >= {"ffmpeg", "whisper", "providers", "capcut_drafts_dir"}

    def test_unknown_path_is_404(self, server):
        base, _store, _srv = server
        with pytest.raises(urllib.error.HTTPError) as exc:
            get(base + "/nope")
        assert exc.value.code == 404

    def test_unknown_job_is_404(self, server):
        base, _store, _srv = server
        with pytest.raises(urllib.error.HTTPError) as exc:
            get(base + "/api/jobs/deadbeef")
        assert exc.value.code == 404


class TestUpload:
    def test_round_trip(self, server):
        base, store, _srv = server
        payload = b"fake video bytes"
        status, data = put_bytes(base + "/api/uploads?name=%EC%98%81%EC%83%81.mp4", payload)
        assert status == 200
        assert data["size"] == len(payload)
        saved = store.find_upload(data["upload_id"])
        assert saved is not None
        assert saved.read_bytes() == payload
        assert saved.name == "영상.mp4"

    def test_empty_upload_rejected(self, server):
        base, _store, _srv = server
        status, data = put_bytes(base + "/api/uploads?name=a.mp4", b"")
        assert status == 400
        assert "error" in data

    def test_path_traversal_in_name_is_neutralised(self, server):
        base, store, _srv = server
        _status, data = put_bytes(base + "/api/uploads?name=../../evil.mp4", b"xx")
        saved = store.find_upload(data["upload_id"])
        assert saved.name == "evil.mp4"
        assert "work" in str(saved)

    def test_traversal_in_upload_id_is_rejected(self, server):
        _base, store, _srv = server
        assert store.find_upload("../../..") is None


class TestJobLifecycle:
    def test_job_for_missing_upload_is_404(self, server):
        base, _store, _srv = server
        status, data = post_json(base + "/api/jobs", {"upload_id": "nope"})
        assert status == 404
        assert "error" in data

    def test_bad_file_produces_error_state(self, server):
        """영상이 아닌 파일 -> 작업은 error로 끝나야지 서버가 죽으면 안 된다."""
        base, store, _srv = server
        _status, upload = put_bytes(base + "/api/uploads?name=broken.mp4", b"not a video")
        status, data = post_json(
            base + "/api/jobs",
            {"upload_id": upload["upload_id"], "options": {"preview": False}},
        )
        assert status == 202
        job_id = data["job_id"]

        deadline = time.time() + 30
        while time.time() < deadline:
            _s, body, _h = get(f"{base}/api/jobs/{job_id}")
            job = json.loads(body)
            if job["state"] in ("done", "error"):
                break
            time.sleep(0.2)
        assert job["state"] == "error"
        assert job["error"]

        # 서버는 살아 있어야 한다
        assert get(base + "/api/config")[0] == 200

    def test_install_before_completion_is_rejected(self, server):
        base, store, _srv = server
        job = store.create(Path("dummy.mp4"), {})
        status, data = post_json(base + f"/api/jobs/{job.id}/install", {})
        assert status == 400
        assert "error" in data


class TestFileServing:
    @pytest.fixture
    def job_with_file(self, server, tmp_path):
        base, store, _srv = server
        job = store.create(tmp_path / "dummy.mp4", {})
        blob = tmp_path / "preview.mp4"
        blob.write_bytes(bytes(range(256)) * 40)  # 10240 바이트
        job.outputs["preview"] = str(blob)
        return base, job, blob

    def test_serves_whole_file(self, job_with_file):
        base, job, blob = job_with_file
        status, body, headers = get(f"{base}/api/jobs/{job.id}/file/preview")
        assert status == 200
        assert body == blob.read_bytes()
        assert headers["Accept-Ranges"] == "bytes"

    def test_range_request_returns_partial(self, job_with_file):
        base, job, blob = job_with_file
        status, body, headers = get(
            f"{base}/api/jobs/{job.id}/file/preview", {"Range": "bytes=100-199"}
        )
        assert status == 206
        assert len(body) == 100
        assert body == blob.read_bytes()[100:200]
        assert headers["Content-Range"] == f"bytes 100-199/{blob.stat().st_size}"

    def test_open_ended_range(self, job_with_file):
        base, job, blob = job_with_file
        size = blob.stat().st_size
        status, body, _h = get(
            f"{base}/api/jobs/{job.id}/file/preview", {"Range": f"bytes={size - 50}-"}
        )
        assert status == 206
        assert len(body) == 50

    def test_suffix_range(self, job_with_file):
        base, job, blob = job_with_file
        status, body, _h = get(
            f"{base}/api/jobs/{job.id}/file/preview", {"Range": "bytes=-64"}
        )
        assert status == 206
        assert body == blob.read_bytes()[-64:]

    def test_range_past_end_is_416(self, job_with_file):
        base, job, blob = job_with_file
        with pytest.raises(urllib.error.HTTPError) as exc:
            get(
                f"{base}/api/jobs/{job.id}/file/preview",
                {"Range": f"bytes={blob.stat().st_size + 10}-"},
            )
        assert exc.value.code == 416

    def test_download_flag_sets_disposition(self, job_with_file):
        base, job, _blob = job_with_file
        _s, _b, headers = get(f"{base}/api/jobs/{job.id}/file/preview?download=1")
        assert "attachment" in headers["Content-Disposition"]

    def test_unknown_output_kind_is_404(self, job_with_file):
        base, job, _blob = job_with_file
        with pytest.raises(urllib.error.HTTPError) as exc:
            get(f"{base}/api/jobs/{job.id}/file/nope")
        assert exc.value.code == 404


class TestWatch:
    def test_emits_logs_then_result(self, tmp_path):
        store = JobStore(tmp_path / "w")
        job = store.create(tmp_path / "a.mp4", {})
        events = []

        def collect():
            for event in store.watch(job.id, timeout=0.05):
                events.append(event)

        thread = threading.Thread(target=collect, daemon=True)
        thread.start()

        store._publish(job, "첫 메시지")
        store._publish(job, "둘째 메시지")
        store._finish(job, "done")
        thread.join(timeout=5)

        kinds = [e["type"] for e in events]
        assert "log" in kinds and kinds[-1] == "result"
        logs = [e["message"] for e in events if e["type"] == "log"]
        assert logs == ["첫 메시지", "둘째 메시지"]
        assert events[-1]["job"]["state"] == "done"

    def test_unknown_job_yields_error(self, tmp_path):
        store = JobStore(tmp_path / "w")
        events = list(store.watch("nope", timeout=0.01))
        assert events == [{"type": "error", "error": "없는 작업입니다."}]
