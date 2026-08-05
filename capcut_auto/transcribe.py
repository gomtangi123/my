"""음성 인식 (단어 단위 타임스탬프).

기본은 faster-whisper. 단어 타임스탬프가 있어야 필러 하나만 콕 집어
잘라낼 수 있으므로 `word_timestamps=True`는 필수다.

인식 결과는 JSON으로 캐시한다. 같은 영상으로 설정만 바꿔가며
여러 번 돌릴 때 매번 몇 분씩 기다리지 않아도 된다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import TranscribeConfig
from .models import Word


class TranscriptionUnavailable(RuntimeError):
    pass


def cache_key(media: str | Path, cfg: TranscribeConfig) -> str:
    p = Path(media)
    stat = p.stat()
    payload = "|".join(
        [
            str(p.resolve()),
            str(stat.st_size),
            str(int(stat.st_mtime)),
            cfg.backend,
            cfg.model,
            str(cfg.language),
            str(cfg.beam_size),
            str(cfg.vad_filter),
            str(cfg.initial_prompt),
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def load_cache(path: Path) -> list[Word] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return [Word(**w) for w in data.get("words", [])]


def save_cache(path: Path, words: list[Word]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "words": [
                    {
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "text": w.text,
                        "probability": round(w.probability, 4),
                    }
                    for w in words
                ]
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )


def transcribe(
    media: str | Path,
    cfg: TranscribeConfig,
    cache_dir: Path | None = None,
    progress=None,
) -> list[Word]:
    """단어 목록을 돌려준다. 캐시가 있으면 그걸 쓴다."""
    cache_path = None
    if cache_dir is not None:
        cache_path = Path(cache_dir) / f"transcript-{cache_key(media, cfg)}.json"
        cached = load_cache(cache_path)
        if cached is not None:
            if progress:
                progress(f"음성 인식 캐시 사용: {cache_path.name} ({len(cached)}단어)")
            return cached

    if cfg.backend == "faster-whisper":
        words = _faster_whisper(media, cfg, progress)
    elif cfg.backend == "whisper":
        words = _openai_whisper(media, cfg, progress)
    else:
        raise TranscriptionUnavailable(f"모르는 backend: {cfg.backend}")

    if cache_path is not None:
        save_cache(cache_path, words)
    return words


def _resolve_device(cfg: TranscribeConfig) -> tuple[str, str]:
    device, compute = cfg.device, cfg.compute_type
    if device == "auto":
        try:
            import torch  # type: ignore

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return device, compute


def _faster_whisper(media, cfg: TranscribeConfig, progress) -> list[Word]:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise TranscriptionUnavailable(
            "faster-whisper가 설치되어 있지 않습니다.\n"
            "  pip install faster-whisper\n"
            "자막/더듬음 제거 없이 무음 컷만 하려면 --no-transcribe 를 쓰세요."
        ) from exc

    device, compute = _resolve_device(cfg)
    if progress:
        progress(f"Whisper 모델 로드: {cfg.model} ({device}/{compute})")
    model = WhisperModel(cfg.model, device=device, compute_type=compute)

    segments, _info = model.transcribe(
        str(media),
        language=cfg.language,
        beam_size=cfg.beam_size,
        word_timestamps=True,
        vad_filter=cfg.vad_filter,
        initial_prompt=cfg.initial_prompt,
    )

    words: list[Word] = []
    for segment in segments:  # 제너레이터라서 여기서 실제 인식이 돈다
        for w in segment.words or []:
            text = (w.word or "").strip()
            if not text:
                continue
            words.append(
                Word(
                    start=float(w.start),
                    end=float(w.end),
                    text=text,
                    probability=float(getattr(w, "probability", 1.0) or 1.0),
                )
            )
        if progress and words:
            progress(f"인식 중… {segment.end:.0f}초 지점 ({len(words)}단어)")
    return words


def _openai_whisper(media, cfg: TranscribeConfig, progress) -> list[Word]:
    try:
        import whisper  # type: ignore
    except ImportError as exc:
        raise TranscriptionUnavailable(
            "openai-whisper가 설치되어 있지 않습니다: pip install openai-whisper"
        ) from exc

    if progress:
        progress(f"Whisper 모델 로드: {cfg.model}")
    model = whisper.load_model(cfg.model)
    result = model.transcribe(
        str(media), language=cfg.language, word_timestamps=True, verbose=False
    )
    words: list[Word] = []
    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            text = (w.get("word") or "").strip()
            if not text:
                continue
            words.append(
                Word(
                    start=float(w["start"]),
                    end=float(w["end"]),
                    text=text,
                    probability=float(w.get("probability", 1.0)),
                )
            )
    return words


__all__ = ["transcribe", "TranscriptionUnavailable", "cache_key"]
