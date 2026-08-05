"""브라우저 UI용 HTTP 서버.

의존성을 늘리지 않으려고 stdlib만 쓴다. 멀티파트 파싱을 피하려고
업로드는 `PUT /api/uploads?name=...` 으로 파일 본문을 그대로 받는다
(브라우저에서 `fetch(url, {method:"PUT", body: file})` 한 줄이면 된다).

기본으로 127.0.0.1에만 바인딩한다. 이 서버는 올라온 파일을 로컬에서
ffmpeg으로 처리하고 로컬 경로를 돌려주므로 외부에 열면 안 된다.
"""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import socket
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..capcut import paths as capcut_paths
from .jobs import MAX_UPLOAD_BYTES, JobStore

STATIC_DIR = Path(__file__).parent / "static"
CHUNK = 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "capcut-auto"

    # 서버 인스턴스에서 주입한다
    store: JobStore

    def log_message(self, fmt: str, *args) -> None:  # 접근 로그는 조용히
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    # ------------------------------------------------------------- 라우팅

    def do_GET(self) -> None:
        route, query = self._split()
        try:
            if route in ("/", "/index.html"):
                return self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            if route == "/api/config":
                return self._send_json(self._environment())
            if route.startswith("/api/jobs/"):
                rest = route[len("/api/jobs/"):].split("/")
                job = self.store.get(rest[0])
                if job is None:
                    return self._send_json({"error": "없는 작업입니다."}, HTTPStatus.NOT_FOUND)
                if len(rest) == 1:
                    return self._send_json(job.public())
                if rest[1] == "events":
                    return self._stream_events(rest[0])
                if rest[1] == "file" and len(rest) > 2:
                    path = job.outputs.get(rest[2])
                    if not path or not Path(path).exists():
                        return self._send_json(
                            {"error": "없는 파일입니다."}, HTTPStatus.NOT_FOUND
                        )
                    download = query.get("download", ["0"])[0] == "1"
                    return self._send_file(Path(path), download=download)
            self._send_json({"error": "없는 경로입니다."}, HTTPStatus.NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError):
            pass  # 브라우저가 먼저 끊은 것뿐

    def do_PUT(self) -> None:
        route, query = self._split()
        if route != "/api/uploads":
            return self._send_json({"error": "없는 경로입니다."}, HTTPStatus.NOT_FOUND)

        name = query.get("name", ["video.mp4"])[0]
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return self._send_json({"error": "빈 요청입니다."}, HTTPStatus.BAD_REQUEST)
        if length > MAX_UPLOAD_BYTES:
            return self._send_json(
                {"error": f"파일이 너무 큽니다 (최대 {MAX_UPLOAD_BYTES // 2**30}GB)."},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )

        upload_id, target = self.store.upload_path(name)
        remaining = length
        try:
            with target.open("wb") as fh:
                while remaining > 0:
                    block = self.rfile.read(min(CHUNK, remaining))
                    if not block:
                        break
                    fh.write(block)
                    remaining -= len(block)
        except (BrokenPipeError, ConnectionResetError):
            shutil.rmtree(target.parent, ignore_errors=True)
            return
        if remaining > 0:
            shutil.rmtree(target.parent, ignore_errors=True)
            return self._send_json(
                {"error": "업로드가 중간에 끊겼습니다."}, HTTPStatus.BAD_REQUEST
            )

        self._send_json({"upload_id": upload_id, "name": target.name, "size": length})

    def do_POST(self) -> None:
        route, _query = self._split()
        try:
            payload = self._read_json()
        except ValueError as exc:
            return self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

        if route == "/api/jobs":
            upload_id = str(payload.get("upload_id", ""))
            source = self.store.find_upload(upload_id)
            if source is None:
                return self._send_json(
                    {"error": "업로드를 찾을 수 없습니다."}, HTTPStatus.NOT_FOUND
                )
            options = payload.get("options") or {}
            if not isinstance(options, dict):
                return self._send_json({"error": "옵션 형식 오류"}, HTTPStatus.BAD_REQUEST)
            job = self.store.create(source, options)
            self.store.start(job)
            return self._send_json({"job_id": job.id}, HTTPStatus.ACCEPTED)

        if route.startswith("/api/jobs/") and route.endswith("/install"):
            job_id = route[len("/api/jobs/"): -len("/install")]
            job = self.store.get(job_id)
            if job is None:
                return self._send_json({"error": "없는 작업입니다."}, HTTPStatus.NOT_FOUND)
            try:
                target = self.store.install(job, payload.get("drafts_dir"))
            except (ValueError, OSError) as exc:
                return self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return self._send_json({"installed_path": target})

        self._send_json({"error": "없는 경로입니다."}, HTTPStatus.NOT_FOUND)

    # ------------------------------------------------------------- 응답부

    def _split(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path.rstrip("/") or "/", urllib.parse.parse_qs(parsed.query)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Content-Length 없음")
        if length <= 0:
            return {}
        if length > 4 * 1024 * 1024:
            raise ValueError("요청이 너무 큽니다")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"JSON 파싱 실패: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("객체가 아닙니다")
        return data

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(
        self, path: Path, content_type: str | None = None, download: bool = False
    ) -> None:
        """Range 요청을 지원한다. 없으면 미리보기 영상에서 탐색이 안 된다."""
        path = Path(path)
        if not path.is_file():
            return self._send_json({"error": "없는 파일입니다."}, HTTPStatus.NOT_FOUND)

        size = path.stat().st_size
        ctype = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        status = HTTPStatus.OK

        raw_range = self.headers.get("Range")
        if raw_range and raw_range.startswith("bytes=") and size:
            spec = raw_range[len("bytes="):].split(",")[0].strip()
            first, _, last = spec.partition("-")
            try:
                if first:
                    start = int(first)
                    end = int(last) if last else size - 1
                else:  # "bytes=-500" = 마지막 500바이트
                    start = max(0, size - int(last))
                    end = size - 1
            except ValueError:
                start, end = 0, size - 1
            else:
                if start >= size:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                status = HTTPStatus.PARTIAL_CONTENT

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            quoted = urllib.parse.quote(path.name)
            self.send_header(
                "Content-Disposition", f"attachment; filename*=UTF-8''{quoted}"
            )
        self.end_headers()

        with path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                block = fh.read(min(CHUNK, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def _stream_events(self, job_id: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        for event in self.store.watch(job_id):
            payload = json.dumps(event, ensure_ascii=False)
            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()

    # ------------------------------------------------------------ 환경 조회

    def _environment(self) -> dict:
        drafts = capcut_paths.find()
        providers = [
            name
            for name, env in (
                ("pexels", "PEXELS_API_KEY"),
                ("pixabay", "PIXABAY_API_KEY"),
                ("giphy", "GIPHY_API_KEY"),
                ("tenor", "TENOR_API_KEY"),
            )
            if os.environ.get(env, "").strip()
        ]
        try:
            import faster_whisper  # type: ignore  # noqa: F401

            has_whisper = True
        except ImportError:
            has_whisper = False

        return {
            "ffmpeg": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
            "whisper": has_whisper,
            "providers": providers,
            "capcut_drafts_dir": str(drafts) if drafts else None,
            "max_upload_bytes": MAX_UPLOAD_BYTES,
        }


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store: JobStore, verbose: bool = False):
        self.verbose = verbose
        handler = type("BoundHandler", (Handler,), {"store": store})
        super().__init__(address, handler)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    work_root: Path | None = None,
    open_browser: bool = False,
    verbose: bool = False,
) -> None:
    store = JobStore(Path(work_root or "capcut-out/web"))
    try:
        server = Server((host, port), store, verbose)
    except OSError as exc:
        raise SystemExit(f"{host}:{port} 를 열 수 없습니다 — {exc}") from exc

    actual = server.server_address[1]
    url = f"http://{host if host != '0.0.0.0' else socket.gethostname()}:{actual}/"
    print(f"capcut-auto 웹 UI  →  {url}")
    print(f"작업 폴더: {store.work_root.resolve()}")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("경고: 로컬 파일을 다루는 서버입니다. 외부에 노출하지 마세요.")
    print("종료하려면 Ctrl+C")

    if open_browser:
        import threading
        import webbrowser

        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        server.server_close()


__all__ = ["serve", "Server", "Handler"]
