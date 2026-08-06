"""설정. YAML 또는 JSON 파일에서 읽고, CLI 플래그로 덮어쓴다."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_type_hints

# 한국어 필러(간투사) 기본 사전. 단어 단위로 정확히 일치할 때만 잡는다.
#
# 여기 있는 말들은 거의 언제나 군말이라 지워도 뜻이 안 상한다.
# 뜻을 가질 수 있는 말("그러니까", "이제", "좀"…)은 아래 AGGRESSIVE 쪽에 뒀다.
DEFAULT_FILLERS_KO: tuple[str, ...] = (
    "음",
    "으음",
    "흠",
    "어",
    "어어",
    "에",
    "에에",
    "아",
    "아아",
    "그",
    "그그",
    "저",
    "저기",
    "뭐랄까",
    "뭐지",
    "그니까",
)

# `disfluency.aggressive_fillers: true`일 때만 추가로 잡는다.
# 접속사·부사로 쓰이면 뜻이 있는 말들이라 기본으로는 건드리지 않는다.
# ("그러니까 이게 핵심입니다" 의 '그러니까'까지 날아가면 곤란하다)
AGGRESSIVE_FILLERS_KO: tuple[str, ...] = (
    "그러니까",
    "이제",
    "인제",
    "뭐",
    "약간",
    "막",
    "좀",
    "이렇게",
    "그런",
    "무슨",
    "진짜",
    "되게",
)

DEFAULT_FILLERS_EN: tuple[str, ...] = (
    "uh",
    "um",
    "umm",
    "erm",
    "er",
    "ah",
    "hmm",
    "like",
    "so",
    "well",
    "actually",
    "basically",
    "youknow",
    "imean",
)


@dataclass
class SilenceConfig:
    enabled: bool = True
    # None이면 소음 바닥(noise floor)을 보고 자동으로 잡는다.
    threshold_db: float | None = None
    # 자동 임계값일 때 소음 바닥 위로 몇 dB를 말소리로 볼지.
    auto_margin_db: float = 12.0
    # 어떤 경우에도 이 값보다 낮은 임계값은 쓰지 않는다.
    floor_db: float = -60.0
    # 이보다 짧은 무음은 그냥 둔다 (숨소리·자연스러운 간격).
    min_silence: float = 0.35
    # 말소리 앞뒤로 남길 여유. 컷이 숨 붙는 걸 막아준다.
    keep_padding: float = 0.08
    # 컷 후 남는 조각이 이보다 짧으면 통째로 버린다.
    min_clip: float = 0.20


@dataclass
class DisfluencyConfig:
    enabled: bool = True
    remove_fillers: bool = True
    remove_stutters: bool = True
    remove_retakes: bool = False  # 공격적이라 기본 off
    language: str = "ko"
    # "그러니까", "이제", "좀" 같이 뜻을 가질 수도 있는 말까지 잘라낸다.
    # 말이 많이 늘어지는 영상에는 효과가 크지만, 먼저 analyze로 확인할 것.
    aggressive_fillers: bool = False
    extra_fillers: tuple[str, ...] = ()
    keep_fillers: tuple[str, ...] = ()  # 사전에서 빼고 싶은 단어
    # 필러는 이 길이 이하일 때만 자른다 (길게 끈 "그으~"는 살릴 수도).
    max_filler_duration: float = 1.20
    # True면 앞뒤로 `isolation_gap` 이상 떠 있는 필러만 자른다.
    # 말 중간에 낀 필러까지 다 자르면 소리가 튈 때가 있어서 보수적으로 가려면 켠다.
    require_isolation: bool = False
    isolation_gap: float = 0.12
    # 문장 묶기 기준(더듬음/재촬영 판정용) — 이보다 벌어지면 다른 문장으로 본다.
    sentence_gap: float = 0.60
    # 같은 말 반복을 더듬음으로 볼 최대 간격.
    stutter_max_gap: float = 0.70
    # 말을 끊고 다시 시작한 것("그러니 → 그러니까")으로 보려면
    # 앞 토막이 이 글자 수 이상이어야 한다. 필러는 이 제한을 받지 않는다.
    # 1로 낮추면 "이 이야기"의 '이'까지 잘려나가므로 기본은 2.
    stutter_min_prefix: int = 2
    # 재촬영(같은 문장 다시 말하기) 판정 유사도.
    retake_similarity: float = 0.75
    # 재촬영 후보를 찾을 때 앞뒤로 볼 시간 범위.
    retake_window: float = 25.0
    # 이 글자 수보다 짧은 문장은 재촬영 판정에서 제외한다 ("네." 끼리 매칭 방지).
    retake_min_chars: int = 8
    # 잘라낸 말 앞뒤로 함께 날릴 여유.
    pad: float = 0.04


@dataclass
class TranscribeConfig:
    enabled: bool = True
    backend: str = "faster-whisper"  # faster-whisper | whisper | none
    model: str = "large-v3"
    language: str | None = "ko"
    device: str = "auto"
    compute_type: str = "auto"
    beam_size: int = 5
    vad_filter: bool = True
    initial_prompt: str | None = None


@dataclass
class SubtitleConfig:
    enabled: bool = True
    # 한 줄 최대 글자 수. 세로 영상은 14~18, 가로는 24~30이 무난하다.
    max_chars: int = 18
    max_lines: int = 2
    max_duration: float = 4.0
    min_duration: float = 0.6
    # 단어 사이가 이만큼 벌어지면 줄을 끊는다.
    split_gap: float = 0.45
    # 문장부호에서 끊기.
    split_punctuation: bool = True
    # 자막에서 문장 끝 마침표를 지운다 (숏폼 관행).
    strip_trailing_period: bool = True
    font_size: float = 8.0
    font_color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    # 화면 아래에서 얼마나 띄울지. -1.0(아래) ~ 1.0(위) 좌표계.
    position_y: float = -0.72
    stroke: bool = True
    stroke_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    stroke_width: float = 0.08


@dataclass
class SfxConfig:
    enabled: bool = True
    # 효과음 폴더. 없으면 내장 합성음(whoosh/pop/ding/riser…)을 쓴다.
    library: str | None = None
    volume: float = 0.35
    # 컷 이음매마다 전환음
    transition: bool = True
    transition_sound: str = "whoosh"
    # 잘려나간 길이가 이보다 짧으면 전환음을 넣지 않는다 (필러 하나 뺀 자리 등).
    transition_min_gap: float = 0.35
    # 이보다 크게 잘렸으면 화제 전환으로 보고 라이저를 깐다.
    section_gap: float = 1.50
    section_sound: str = "riser"
    # 숫자·강조어·물음표에 포인트 사운드
    emphasis: bool = True
    emphasis_sound: str = "ding"
    question_sound: str = "pop"
    number_sound: str = "pop"
    # 밀도 제한 — 이게 없으면 금방 촌스러워진다.
    min_interval: float = 1.00
    max_per_minute: float = 18.0
    # 효과음을 살짝 앞당겨 깔면 붙는 느낌이 산다.
    lead: float = 0.03
    # 사용자 규칙: [{"match": "웃|하하", "sound": "boing"}]
    rules: tuple[dict, ...] = ()


@dataclass
class AssetsConfig:
    """자료화면 / 이미지 / GIF 자동 삽입."""

    enabled: bool = True
    # 내 소재 폴더 (키 없이 동작). 파일 이름이 태그가 된다.
    local_folder: str | None = None
    # 온라인 제공자 키. 비워 두면 같은 이름의 환경변수를 본다.
    pexels_api_key: str | None = None
    pixabay_api_key: str | None = None
    giphy_api_key: str | None = None
    tenor_api_key: str | None = None
    # 어떤 종류를 우선할지. video = 자료화면(B-roll)
    prefer: tuple[str, ...] = ("video", "image")
    gif_for_reactions: bool = True
    # 소재를 어떻게 깔지.
    #   "spots" — 키워드가 맞는 자리에만 띄엄띄엄 (기본)
    #   "full"  — 처음부터 끝까지 빈틈없이. 소재가 모자라면 돌려 쓴다.
    coverage: str = "spots"
    # 제공자당 후보 개수
    candidates: int = 8
    # 한 소재가 화면에 머무는 시간
    min_duration: float = 1.80
    max_duration: float = 4.50
    # 소재 사이 최소 간격 / 분당 최대 개수
    min_gap: float = 2.50
    max_per_minute: float = 8.0
    # 키워드 점수가 이보다 낮으면 자료화면을 붙이지 않는다.
    min_score: float = 0.55
    # 화면 채움 비율. 자료화면은 꽉 채우고 이미지/GIF는 띄운다.
    broll_scale: float = 1.0
    image_scale: float = 0.62
    gif_scale: float = 0.42
    overlay_position_y: float = 0.22
    # Pexels 검색 방향 ("landscape" / "portrait" / "")
    orientation: str = ""
    # 한국어→영어 검색어 매핑 추가분
    query_map: dict = field(default_factory=dict)
    use_konlpy: bool = True


@dataclass
class OutputConfig:
    fps: float = 30.0
    width: int = 0  # 0이면 원본에서 읽어온다
    height: int = 0
    project_name: str = ""
    # ffmpeg 직접 렌더링 옵션
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    crf: int = 18
    preset: str = "medium"
    burn_subtitles: bool = False


@dataclass
class Config:
    silence: SilenceConfig = field(default_factory=SilenceConfig)
    disfluency: DisfluencyConfig = field(default_factory=DisfluencyConfig)
    transcribe: TranscribeConfig = field(default_factory=TranscribeConfig)
    subtitle: SubtitleConfig = field(default_factory=SubtitleConfig)
    sfx: SfxConfig = field(default_factory=SfxConfig)
    assets: AssetsConfig = field(default_factory=AssetsConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    @property
    def fillers(self) -> frozenset[str]:
        base: tuple[str, ...]
        if self.disfluency.language == "en":
            base = DEFAULT_FILLERS_EN
        elif self.disfluency.language == "ko":
            base = DEFAULT_FILLERS_KO
        else:
            base = DEFAULT_FILLERS_KO + DEFAULT_FILLERS_EN
        if self.disfluency.aggressive_fillers and self.disfluency.language != "en":
            base = base + AGGRESSIVE_FILLERS_KO
        words = set(base) | set(self.disfluency.extra_fillers)
        return frozenset(words - set(self.disfluency.keep_fillers))

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        if path is None:
            return cls()
        p = Path(path)
        raw = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except ImportError as exc:  # pragma: no cover - 환경 의존
                raise SystemExit(
                    "YAML 설정을 쓰려면 `pip install pyyaml` 하거나 .json으로 저장하세요."
                ) from exc
            data = yaml.safe_load(raw) or {}
        else:
            data = json.loads(raw)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        return _build(cls, data)

    def apply_overrides(self, overrides: dict[str, Any]) -> None:
        """'silence.min_silence' 같은 점 표기 키로 값을 덮어쓴다."""
        for dotted, value in overrides.items():
            if value is None:
                continue
            target: Any = self
            parts = dotted.split(".")
            for part in parts[:-1]:
                target = getattr(target, part)
            leaf = parts[-1]
            if not hasattr(target, leaf):
                raise KeyError(f"알 수 없는 설정 키: {dotted}")
            setattr(target, leaf, value)


def _build(cls: type, data: dict[str, Any]) -> Any:
    kwargs: dict[str, Any] = {}
    # `from __future__ import annotations` 때문에 field.type은 문자열이다.
    # 중첩 dataclass를 알아보려면 실제 타입으로 되돌려야 한다.
    hints = get_type_hints(cls)
    known = {f.name for f in fields(cls)}
    for key, value in data.items():
        if key not in known:
            raise KeyError(f"알 수 없는 설정 키: {cls.__name__}.{key}")
        ftype = hints[key]
        if is_dataclass(ftype) and isinstance(value, dict):
            kwargs[key] = _build(ftype, value)  # type: ignore[arg-type]
        elif isinstance(value, list):
            kwargs[key] = tuple(value)
        else:
            kwargs[key] = value
    return cls(**kwargs)


__all__ = [
    "Config",
    "SilenceConfig",
    "DisfluencyConfig",
    "TranscribeConfig",
    "SubtitleConfig",
    "SfxConfig",
    "AssetsConfig",
    "OutputConfig",
    "DEFAULT_FILLERS_KO",
    "AGGRESSIVE_FILLERS_KO",
    "DEFAULT_FILLERS_EN",
]
