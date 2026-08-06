"""자료화면 제공자.

로컬 폴더는 키 없이 바로 되고, 나머지는 무료 API 키가 필요하다.
키는 설정 파일이나 환경변수로 준다.

  PEXELS_API_KEY   https://www.pexels.com/api/         (이미지 + 영상)
  PIXABAY_API_KEY  https://pixabay.com/api/docs/       (이미지 + 영상)
  GIPHY_API_KEY    https://developers.giphy.com/       (GIF)
  TENOR_API_KEY    https://tenor.com/gifapi            (GIF)

키가 하나도 없으면 로컬 폴더만 쓰고, 그것도 없으면 자료화면 단계를
통째로 건너뛴다 (컷편집·자막·효과음은 그대로 동작한다).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .models import AssetRef

USER_AGENT = "capcut-auto/0.1 (+https://github.com/)"
TIMEOUT = 20

TAGS_FILE = ".tags.json"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}
GIF_EXTS = {".gif"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mkv"}
_SPLIT_RE = re.compile(r"[^a-z0-9가-힣]+")


class ProviderError(RuntimeError):
    pass


def _get_json(url: str, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"{url.split('?')[0]} → HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProviderError(f"{url.split('?')[0]} → {exc}") from exc


@dataclass
class Provider:
    """공통 인터페이스."""

    name: str = "base"

    def search(self, query: str, kind: str, limit: int = 5) -> list[AssetRef]:
        raise NotImplementedError

    def supports(self, kind: str) -> bool:
        return True


# --------------------------------------------------------------------- 로컬


@dataclass
class LocalProvider(Provider):
    """내 소재 폴더. 파일 이름이 곧 태그다.

    예) broll/서울_도시_야경.mp4 -> {서울, 도시, 야경}
    """

    folder: Path = Path(".")
    name: str = "local"

    def __post_init__(self) -> None:
        self.folder = Path(self.folder).expanduser()
        self._index: list[tuple[frozenset[str], AssetRef]] = []
        if not self.folder.is_dir():
            raise FileNotFoundError(f"소재 폴더가 없습니다: {self.folder}")
        self._tag_overrides = self._load_tag_overrides()
        for path in sorted(self.folder.rglob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in IMAGE_EXTS:
                kind = "image"
            elif suffix in GIF_EXTS:
                kind = "gif"
            elif suffix in VIDEO_EXTS:
                kind = "video"
            else:
                continue
            ref = AssetRef(
                kind=kind,  # type: ignore[arg-type]
                url=str(path.resolve()),
                source="local",
                source_id=path.name,
                credit="",
            )
            self._index.append((self._tags(path), ref))

    def _load_tag_overrides(self) -> dict[str, str]:
        """웹 UI로 올린 소재는 ASCII 이름으로 저장되므로 원래 이름을 옆에 적어 둔다."""
        path = self.folder / TAGS_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {k: str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _tags(self, path: Path) -> frozenset[str]:
        parts: list[str] = []
        try:
            relative = path.relative_to(self.folder)
        except ValueError:
            relative = Path(path.name)
        for piece in relative.parts[:-1]:
            parts.extend(_SPLIT_RE.split(piece.lower()))
        parts.extend(_SPLIT_RE.split(path.stem.lower()))
        original = self._tag_overrides.get(path.name)
        if original:
            parts.extend(_SPLIT_RE.split(original.lower()))
        return frozenset(p for p in parts if p)

    def search(self, query: str, kind: str, limit: int = 5) -> list[AssetRef]:
        terms = {t for t in _SPLIT_RE.split(query.lower()) if t}
        if not terms:
            return []
        scored = []
        for tags, ref in self._index:
            if kind != "any" and ref.kind != kind:
                continue
            hits = len(terms & tags)
            if hits:
                scored.append((hits, ref))
        scored.sort(key=lambda pair: -pair[0])
        return [ref for _hits, ref in scored[:limit]]


# -------------------------------------------------------------------- Pexels


@dataclass
class PexelsProvider(Provider):
    api_key: str = ""
    name: str = "pexels"
    orientation: str = ""

    def supports(self, kind: str) -> bool:
        return kind in ("image", "video")

    def search(self, query: str, kind: str, limit: int = 5) -> list[AssetRef]:
        if not self.supports(kind):
            return []
        params = {"query": query, "per_page": str(max(1, min(limit, 30)))}
        if self.orientation:
            params["orientation"] = self.orientation
        base = (
            "https://api.pexels.com/videos/search"
            if kind == "video"
            else "https://api.pexels.com/v1/search"
        )
        data = _get_json(
            f"{base}?{urllib.parse.urlencode(params)}",
            headers={"Authorization": self.api_key},
        )
        return (
            self._videos(data, query) if kind == "video" else self._photos(data, query)
        )

    def _photos(self, data: dict, query: str) -> list[AssetRef]:
        out = []
        for item in data.get("photos", []):
            src = item.get("src", {})
            url = src.get("large2x") or src.get("large") or src.get("original")
            if not url:
                continue
            out.append(
                AssetRef(
                    kind="image",
                    url=url,
                    source="pexels",
                    source_id=str(item.get("id", "")),
                    width=int(item.get("width", 0) or 0),
                    height=int(item.get("height", 0) or 0),
                    credit=f"Photo by {item.get('photographer', '')} on Pexels",
                    page_url=item.get("url", ""),
                )
            )
        return out

    def _videos(self, data: dict, query: str) -> list[AssetRef]:
        out = []
        for item in data.get("videos", []):
            files = [f for f in item.get("video_files", []) if f.get("link")]
            if not files:
                continue
            # 1080p 근처를 고른다. 너무 크면 다운로드가 오래 걸린다.
            files.sort(key=lambda f: abs((f.get("height") or 0) - 1080))
            best = files[0]
            out.append(
                AssetRef(
                    kind="video",
                    url=best["link"],
                    source="pexels",
                    source_id=str(item.get("id", "")),
                    width=int(best.get("width", 0) or 0),
                    height=int(best.get("height", 0) or 0),
                    duration=float(item.get("duration", 0) or 0),
                    credit=f"Video by {item.get('user', {}).get('name', '')} on Pexels",
                    page_url=item.get("url", ""),
                )
            )
        return out


# ------------------------------------------------------------------- Pixabay


@dataclass
class PixabayProvider(Provider):
    api_key: str = ""
    name: str = "pixabay"

    def supports(self, kind: str) -> bool:
        return kind in ("image", "video")

    def search(self, query: str, kind: str, limit: int = 5) -> list[AssetRef]:
        if not self.supports(kind):
            return []
        params = {
            "key": self.api_key,
            "q": query,
            "per_page": str(max(3, min(limit, 200))),
            "safesearch": "true",
        }
        if kind == "image":
            params["image_type"] = "photo"
            base = "https://pixabay.com/api/"
        else:
            base = "https://pixabay.com/api/videos/"
        data = _get_json(f"{base}?{urllib.parse.urlencode(params)}")

        out = []
        for item in data.get("hits", []):
            if kind == "image":
                url = item.get("largeImageURL") or item.get("webformatURL")
                if not url:
                    continue
                out.append(
                    AssetRef(
                        kind="image",
                        url=url,
                        source="pixabay",
                        source_id=str(item.get("id", "")),
                        width=int(item.get("imageWidth", 0) or 0),
                        height=int(item.get("imageHeight", 0) or 0),
                        credit=f"Image by {item.get('user', '')} on Pixabay",
                        page_url=item.get("pageURL", ""),
                    )
                )
            else:
                streams = item.get("videos", {})
                pick = streams.get("large") or streams.get("medium") or streams.get("small")
                if not pick or not pick.get("url"):
                    continue
                out.append(
                    AssetRef(
                        kind="video",
                        url=pick["url"],
                        source="pixabay",
                        source_id=str(item.get("id", "")),
                        width=int(pick.get("width", 0) or 0),
                        height=int(pick.get("height", 0) or 0),
                        duration=float(item.get("duration", 0) or 0),
                        credit=f"Video by {item.get('user', '')} on Pixabay",
                        page_url=item.get("pageURL", ""),
                    )
                )
        return out


# --------------------------------------------------------------------- GIF


@dataclass
class GiphyProvider(Provider):
    api_key: str = ""
    name: str = "giphy"
    language: str = "ko"

    def supports(self, kind: str) -> bool:
        return kind == "gif"

    def search(self, query: str, kind: str, limit: int = 5) -> list[AssetRef]:
        if not self.supports(kind):
            return []
        params = {
            "api_key": self.api_key,
            "q": query,
            "limit": str(max(1, min(limit, 25))),
            "rating": "pg-13",
            "lang": self.language,
        }
        data = _get_json(
            "https://api.giphy.com/v1/gifs/search?" + urllib.parse.urlencode(params)
        )
        out = []
        for item in data.get("data", []):
            images = item.get("images", {})
            # CapCut은 gif보다 mp4를 훨씬 안정적으로 다룬다.
            pick = images.get("original_mp4") or images.get("downsized_small")
            url = (pick or {}).get("mp4") or (images.get("original") or {}).get("url")
            if not url:
                continue
            original = images.get("original", {})
            out.append(
                AssetRef(
                    kind="gif",
                    url=url,
                    source="giphy",
                    source_id=str(item.get("id", "")),
                    width=int(original.get("width", 0) or 0),
                    height=int(original.get("height", 0) or 0),
                    credit="via GIPHY",
                    page_url=item.get("url", ""),
                )
            )
        return out


@dataclass
class TenorProvider(Provider):
    api_key: str = ""
    name: str = "tenor"
    locale: str = "ko_KR"

    def supports(self, kind: str) -> bool:
        return kind == "gif"

    def search(self, query: str, kind: str, limit: int = 5) -> list[AssetRef]:
        if not self.supports(kind):
            return []
        params = {
            "key": self.api_key,
            "q": query,
            "limit": str(max(1, min(limit, 50))),
            "locale": self.locale,
            "contentfilter": "medium",
            "media_filter": "mp4,gif",
            "client_key": "capcut_auto",
        }
        data = _get_json(
            "https://tenor.googleapis.com/v2/search?" + urllib.parse.urlencode(params)
        )
        out = []
        for item in data.get("results", []):
            formats = item.get("media_formats", {})
            pick = formats.get("mp4") or formats.get("gif")
            if not pick or not pick.get("url"):
                continue
            dims = pick.get("dims") or [0, 0]
            out.append(
                AssetRef(
                    kind="gif",
                    url=pick["url"],
                    source="tenor",
                    source_id=str(item.get("id", "")),
                    width=int(dims[0] or 0),
                    height=int(dims[1] or 0),
                    duration=float(pick.get("duration", 0) or 0),
                    credit="via Tenor",
                    page_url=item.get("itemurl", ""),
                )
            )
        return out


# ------------------------------------------------------------------- 레지스트리


def build_providers(cfg, progress=None) -> list[Provider]:
    """설정 + 환경변수를 보고 쓸 수 있는 제공자만 모은다."""
    say = progress or (lambda _m: None)
    providers: list[Provider] = []

    if cfg.local_folder:
        try:
            providers.append(LocalProvider(folder=Path(cfg.local_folder)))
            say(f"소재 제공자: local ({cfg.local_folder})")
        except FileNotFoundError as exc:
            say(f"경고: {exc}")

    def key_for(name: str, configured: str | None) -> str:
        return (configured or os.environ.get(name, "")).strip()

    pexels = key_for("PEXELS_API_KEY", cfg.pexels_api_key)
    if pexels:
        providers.append(PexelsProvider(api_key=pexels, orientation=cfg.orientation))
        say("소재 제공자: pexels")

    pixabay = key_for("PIXABAY_API_KEY", cfg.pixabay_api_key)
    if pixabay:
        providers.append(PixabayProvider(api_key=pixabay))
        say("소재 제공자: pixabay")

    giphy = key_for("GIPHY_API_KEY", cfg.giphy_api_key)
    if giphy:
        providers.append(GiphyProvider(api_key=giphy))
        say("소재 제공자: giphy")

    tenor = key_for("TENOR_API_KEY", cfg.tenor_api_key)
    if tenor:
        providers.append(TenorProvider(api_key=tenor))
        say("소재 제공자: tenor")

    return providers


def missing_key_hint() -> str:
    return (
        "쓸 수 있는 소재 제공자가 없습니다. 다음 중 하나를 설정하세요:\n"
        "  - assets.local_folder 에 내 소재 폴더 지정 (키 불필요)\n"
        "  - PEXELS_API_KEY   (무료, 이미지+자료화면)  https://www.pexels.com/api/\n"
        "  - PIXABAY_API_KEY  (무료, 이미지+자료화면)  https://pixabay.com/api/docs/\n"
        "  - GIPHY_API_KEY    (무료, GIF)             https://developers.giphy.com/\n"
        "  - TENOR_API_KEY    (무료, GIF)             https://tenor.com/gifapi"
    )


__all__ = [
    "Provider",
    "LocalProvider",
    "PexelsProvider",
    "PixabayProvider",
    "GiphyProvider",
    "TenorProvider",
    "ProviderError",
    "build_providers",
    "missing_key_hint",
]
