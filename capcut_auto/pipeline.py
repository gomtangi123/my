"""무음 검출 + 버벅임 검출 + 자막을 하나의 편집안(EditPlan)으로 묶는다."""

from __future__ import annotations

from pathlib import Path

from . import disfluency, ffmpeg, silence, subtitles, timeline, transcribe
from .assets.planner import plan_assets
from .assets.providers import build_providers, missing_key_hint
from .config import Config
from .models import Cut, EditPlan, Word
from .sfx.library import Library as SfxLibrary
from .sfx.planner import plan_sfx
from .timeline import TimeMap

SAMPLE_RATE = 16000

# CapCut 드래프트는 소재의 절대 경로를 들고 있다. 내려받은 자료화면과
# 만들어낸 효과음은 이 폴더에 남아 있어야 하므로 지우면 안 된다.
ASSETS_DIRNAME = "assets"
SFX_DIRNAME = "sfx"
TRANSCRIPT_CACHE_DIRNAME = ".transcript-cache"


def analyze(
    media: str | Path,
    cfg: Config,
    work_dir: Path,
    use_transcript_cache: bool = True,
    progress=None,
) -> tuple[EditPlan, ffmpeg.MediaInfo, list[Word]]:
    say = progress or (lambda _msg: None)
    media = Path(media)
    work_dir = Path(work_dir)
    cache_dir = work_dir / TRANSCRIPT_CACHE_DIRNAME if use_transcript_cache else None

    info = ffmpeg.probe(media)
    duration = info.duration
    if duration <= 0:
        raise ValueError(f"길이를 읽을 수 없습니다: {media}")
    say(
        f"입력: {media.name}  {duration:.1f}초  {info.width}x{info.height}  "
        f"{info.fps:.2f}fps  오디오={'있음' if info.has_audio else '없음'}"
    )

    cuts: list[Cut] = []

    # 1) 무음
    if cfg.silence.enabled and info.has_audio:
        samples = ffmpeg.decode_audio(media, SAMPLE_RATE)
        result = silence.analyze(samples, SAMPLE_RATE, cfg.silence)
        say(
            f"무음 검출: 임계값 {result.threshold_db:.1f}dB "
            f"(소음바닥 {result.noise_floor_db:.1f} / 말소리 {result.speech_level_db:.1f}) "
            f"— {len(result.silence)}개 구간, 총 {sum(s.duration for s in result.silence):.1f}초"
        )
        cuts.extend(
            Cut(span.clamp(0.0, duration), "silence", f"{span.duration:.2f}초")
            for span in result.silence
            if span.duration > 0
        )
    elif cfg.silence.enabled:
        say("오디오 트랙이 없어 무음 검출을 건너뜁니다.")

    # 2) 음성 인식
    words: list[Word] = []
    needs_words = cfg.transcribe.enabled and (
        cfg.disfluency.enabled or cfg.subtitle.enabled
    )
    if needs_words and info.has_audio:
        words = transcribe.transcribe(media, cfg.transcribe, cache_dir, say)
        say(f"인식된 단어: {len(words)}개")
    elif needs_words:
        say("오디오 트랙이 없어 음성 인식을 건너뜁니다.")

    # 3) 버벅임
    if words and cfg.disfluency.enabled:
        found = disfluency.detect(words, cfg.disfluency, cfg.fillers, duration)
        by_reason: dict[str, int] = {}
        for cut in found:
            by_reason[cut.reason] = by_reason.get(cut.reason, 0) + 1
        if found:
            say(
                "버벅임 검출: "
                + ", ".join(f"{k} {v}개" for k, v in sorted(by_reason.items()))
            )
        cuts.extend(found)

    # 4) 컷 확정
    removal = timeline.merge([c.span for c in cuts])
    keeps = timeline.invert(removal, duration)
    kept = timeline.drop_short(keeps, cfg.silence.min_clip)
    for orphan in [s for s in keeps if s not in kept]:
        cuts.append(Cut(orphan, "silence", "너무 짧은 조각"))
    keeps = kept

    if not keeps:
        raise ValueError(
            "남는 구간이 없습니다. 임계값이 너무 공격적입니다 — "
            "--silence-threshold 를 낮추거나 --no-disfluency 로 확인해 보세요."
        )

    # 5) 자막 (원본 기준으로 만들고 컷 후 타임라인으로 옮긴다)
    timemap = TimeMap(keeps)
    lines = []
    if words and cfg.subtitle.enabled:
        lines = subtitles.build_lines(words, cfg.subtitle)
        lines = subtitles.remap(lines, timemap, cfg.subtitle)
        say(f"자막: {len(lines)}줄")

    plan = EditPlan(
        source=str(media.resolve()),
        source_duration=duration,
        keeps=keeps,
        cuts=sorted(cuts, key=lambda c: c.span.start),
        subtitles=lines,
    )

    # 6) 효과음
    if cfg.sfx.enabled:
        library = SfxLibrary.load(
            cfg.sfx.library, work_dir / ASSETS_DIRNAME / SFX_DIRNAME
        )
        say(library.describe())
        plan.sfx = plan_sfx(plan, timemap, cfg.sfx, library)
        say(f"효과음: {len(plan.sfx)}개")

    # 7) 자료화면 / 이미지 / GIF
    if cfg.assets.enabled and plan.subtitles:
        providers = build_providers(cfg.assets, say)
        if not providers:
            say("자료화면 건너뜀 — " + missing_key_hint().splitlines()[0])
        else:
            result = plan_assets(
                plan,
                timemap,
                cfg.assets,
                providers,
                work_dir / ASSETS_DIRNAME,
                say,
            )
            plan.overlays = result.overlays
            say(f"자료화면/이미지: {len(result.overlays)}개")
            for note in result.skipped[:5]:
                say(f"  건너뜀 — {note}")

    summary = plan.summary()
    say(
        f"결과: {summary['source_duration']}초 → {summary['output_duration']}초 "
        f"({summary['removed_ratio'] * 100:.1f}% 제거, 클립 {summary['clip_count']}개)"
    )
    return plan, info, words


__all__ = ["analyze", "SAMPLE_RATE"]
