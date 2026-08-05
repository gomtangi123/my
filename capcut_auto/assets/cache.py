"""소재 내려받기 + 캐시.

같은 영상을 여러 번 돌려도 다시 받지 않게 URL 해시로 캐싱한다.
CapCut 드래프트는 소재 파일의 '절대 경로'를 들고 있으므로,
받은 파일은 지우면 안 된다(드래프트 폴더 옆에 두는 걸 권장).
"""

from __future__ import annotations

import hashlib
import mimetypes
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .models import Asset, AssetRef
from .providers import TIMEOUT, USER_AGENT, ProviderError

_EXT_BY_KIND = {"image": ".jpg", "gif": ".mp4", "video": ".mp4"}
MAX_BYTES = 80 * 1024 * 1024


def _extension(ref: AssetRef, content_type: str = "") -> str:
    path = urllib.parse.urlparse(ref.url).path
    suffix = Path(path).suffix.lower()
    if suffix and len(suffix) <= 5:
        return suffix
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return guessed
    return _EXT_BY_KIND.get(ref.kind, ".bin")


def cache_path(ref: AssetRef, cache_dir: Path, extension: str) -> Path:
    digest = hashlib.sha1(ref.url.encode("utf-8")).hexdigest()[:16]
    return Path(cache_dir) / f"{ref.source}-{ref.kind}-{digest}{extension}"


def fetch(ref: AssetRef, cache_dir: Path, query: str = "") -> Asset:
    """소재를 로컬로 가져온다. 로컬 제공자면 복사도 안 하고 그대로 쓴다."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if ref.source == "local":
        source = Path(ref.url)
        if not source.exists():
            raise ProviderError(f"소재 파일이 사라졌습니다: {source}")
        return _asset(ref, source, query)

    target = cache_path(ref, cache_dir, _extension(ref))
    if target.exists() and target.stat().st_size > 0:
        return _asset(ref, target, query)

    request = urllib.request.Request(ref.url, headers={"User-Agent": USER_AGENT})
    temp = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            length = int(response.headers.get("Content-Length") or 0)
            if length and length > MAX_BYTES:
                raise ProviderError(f"파일이 너무 큽니다({length // 1_048_576}MB): {ref.url}")
            extension = _extension(ref, response.headers.get("Content-Type", ""))
            if extension != target.suffix:
                target = cache_path(ref, cache_dir, extension)
                temp = target.with_suffix(target.suffix + ".part")
            with temp.open("wb") as fh:
                shutil.copyfileobj(response, fh, length=256 * 1024)
    except urllib.error.HTTPError as exc:
        temp.unlink(missing_ok=True)
        raise ProviderError(f"다운로드 실패 HTTP {exc.code}: {ref.url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        temp.unlink(missing_ok=True)
        raise ProviderError(f"다운로드 실패: {exc}") from exc

    temp.replace(target)
    return _asset(ref, target, query)


def _asset(ref: AssetRef, path: Path, query: str) -> Asset:
    asset = Asset(
        kind=ref.kind,
        path=path.resolve(),
        source=ref.source,
        source_id=ref.source_id,
        width=ref.width,
        height=ref.height,
        duration=ref.duration,
        credit=ref.credit,
        page_url=ref.page_url,
        query=query,
    )
    if asset.kind in ("video", "gif") and asset.duration <= 0:
        asset.duration = _probe_duration(asset.path)
    if not asset.width or not asset.height:
        _probe_size(asset)
    return asset


def _probe_duration(path: Path) -> float:
    from ..ffmpeg import probe

    try:
        return probe(path).duration
    except Exception:
        return 0.0


def _probe_size(asset: Asset) -> None:
    from ..ffmpeg import probe

    try:
        info = probe(asset.path)
        asset.width = asset.width or info.width
        asset.height = asset.height or info.height
    except Exception:
        pass


def credits_text(assets: list[Asset]) -> str:
    """출처 표기용. 스톡 사이트 약관상 크레딧이 필요한 경우가 많다."""
    lines = ["# 사용된 소재 출처", ""]
    seen: set[str] = set()
    for asset in assets:
        key = f"{asset.source}:{asset.source_id}"
        if key in seen:
            continue
        seen.add(key)
        credit = asset.credit or asset.source
        link = f" — {asset.page_url}" if asset.page_url else ""
        lines.append(f"- [{asset.query}] {credit}{link}")
    return "\n".join(lines) + "\n"


__all__ = ["fetch", "cache_path", "credits_text", "MAX_BYTES"]
