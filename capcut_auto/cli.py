"""커맨드라인 인터페이스."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

from . import cardnews, pipeline, render as render_mod, subtitles
from .assets import cache as asset_cache, providers as asset_providers
from .capcut import paths as capcut_paths
from .capcut.errors import TemplateError
from .config import AssetsConfig, Config
from .ffmpeg import FFmpegMissing
from .transcribe import TranscriptionUnavailable

PROG = "capcut-auto"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    try:
        return args.handler(args)
    except (FFmpegMissing, TranscriptionUnavailable, TemplateError) as exc:
        print(f"\n오류: {exc}", file=sys.stderr)
        return 2
    except (FileExistsError, FileNotFoundError, ValueError, KeyError) as exc:
        print(f"\n오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단됨", file=sys.stderr)
        return 130


# --------------------------------------------------------------------- parser


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="영상에서 무음·버벅임 구간을 잘라내고 자막을 붙인 "
        "CapCut 드래프트를 만들어 줍니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            f"  {PROG} edit 영상.mp4 --install\n"
            f"  {PROG} edit 영상.mp4 --render 결과.mp4 --burn-subs\n"
            f"  {PROG} web --open                # 브라우저에서 쓰기\n"
            f"  {PROG} analyze 영상.mp4          # 뭘 자를지만 보기\n"
            f"  {PROG} doctor                    # 설치 상태 점검\n"
        ),
    )
    sub = parser.add_subparsers(dest="command")

    edit = sub.add_parser("edit", help="컷편집 + 자막 + 효과음 + 자료화면 → CapCut 드래프트")
    _add_common(edit)
    _add_analysis_flags(edit)
    edit.add_argument(
        "-o",
        "--out",
        type=Path,
        help="작업 폴더 (기본: ./capcut-out). 내려받은 소재와 효과음이 여기 쌓입니다.",
    )
    edit.add_argument(
        "--name", help="드래프트(프로젝트) 이름. 기본은 입력 파일 이름."
    )
    edit.add_argument(
        "--template",
        help="복제해서 시작할 기존 드래프트 이름 (`capcut-auto drafts`로 확인). "
        "캔버스 크기·fps 같은 프로젝트 설정을 물려받습니다.",
    )
    edit.add_argument(
        "--install",
        action="store_true",
        help="CapCut 드래프트 폴더에 바로 만들기 (앱에서 즉시 열림)",
    )
    edit.add_argument("--drafts-dir", type=Path, help="CapCut 드래프트 폴더 직접 지정")
    edit.add_argument("--overwrite", action="store_true", help="같은 이름이면 덮어쓰기")
    edit.add_argument("--no-draft", action="store_true", help="드래프트 생성 건너뛰기")
    edit.add_argument(
        "--render",
        nargs="?",
        const="",
        metavar="OUT.mp4",
        help="ffmpeg로 결과 영상까지 뽑기",
    )
    edit.add_argument(
        "--burn-subs", action="store_true", help="--render 시 자막을 영상에 태우기"
    )
    edit.set_defaults(handler=cmd_edit)

    analyze = sub.add_parser("analyze", help="무엇을 자를지 분석만 하고 보여주기")
    _add_common(analyze)
    _add_analysis_flags(analyze)
    analyze.add_argument("-o", "--out", type=Path, help="plan.json / srt 저장 폴더")
    analyze.add_argument("--json", action="store_true", help="JSON으로 출력")
    analyze.add_argument(
        "--list-cuts", action="store_true", help="잘라낼 구간을 전부 나열"
    )
    analyze.add_argument(
        "--with-assets",
        action="store_true",
        help="자료화면까지 실제로 검색·다운로드 (기본은 건너뜀)",
    )
    analyze.set_defaults(handler=cmd_analyze)

    doctor = sub.add_parser("doctor", help="ffmpeg / whisper / CapCut 설치 점검")
    doctor.set_defaults(handler=cmd_doctor, command="doctor")

    drafts = sub.add_parser("drafts", help="CapCut 드래프트 목록 (템플릿 고를 때)")
    drafts.add_argument("--drafts-dir", type=Path)
    drafts.set_defaults(handler=cmd_drafts, command="drafts")

    cards = sub.add_parser(
        "cardnews", help="대본 → 인스타 카드뉴스 이미지 세트 (캐러셀)"
    )
    cards.add_argument("script", type=Path, help="대본 파일 (.txt / .md)")
    cards.add_argument(
        "-o", "--out", type=Path, help="저장 폴더 (기본: ./capcut-out/cardnews)"
    )
    cards.add_argument(
        "-t",
        "--theme",
        default=cardnews.DEFAULT_THEME,
        help=f"테마: {' / '.join(cardnews.THEMES)} (기본 {cardnews.DEFAULT_THEME})",
    )
    cards.add_argument(
        "-s",
        "--size",
        default="post",
        help="규격: post(1080x1350) / square / story, 또는 1080x1350 형식",
    )
    cards.add_argument("--font", help="글꼴 파일 경로 (.ttf/.otf). 기본은 자동 탐색")
    cards.add_argument("--handle", default="", help="카드 아래에 박을 계정명 (예: @myshop)")
    cards.add_argument(
        "--photos",
        default="auto",
        choices=["auto", "full", "band", "wash", "off"],
        help="사진 깔기. auto면 표·그래프만 그라데이션으로 펴고 나머지는 꽉 채웁니다.",
    )
    cards.add_argument(
        "--assets-folder", help="내 사진 폴더 (API 키 불필요, 파일 이름이 태그)"
    )
    cards.add_argument(
        "--backdrop",
        default=cardnews.DEFAULT_BACKDROP,
        choices=list(cardnews.BACKDROPS) + ["off"],
        help="사진이 없을 때 표지에 깔 배경. 테마 색으로 만들어 쓰므로 출처 문제가 없습니다.",
    )
    cards.add_argument(
        "--source",
        default="",
        help="이미지 출처 등. 마지막 장 아래에만 한 줄로 들어갑니다.",
    )
    cards.add_argument("-q", "--quiet", action="store_true", help="진행 로그 숨기기")
    cards.set_defaults(handler=cmd_cardnews, command="cardnews")

    web = sub.add_parser("web", help="브라우저에서 쓰는 웹 UI 띄우기")
    web.add_argument("-p", "--port", type=int, default=8765, help="포트 (기본 8765)")
    web.add_argument(
        "--host",
        default="127.0.0.1",
        help="바인딩 주소. 기본은 이 PC에서만 접속 가능(127.0.0.1).",
    )
    web.add_argument(
        "-o", "--out", type=Path, help="작업 폴더 (기본: ./capcut-out/web)"
    )
    web.add_argument("--open", action="store_true", help="브라우저 자동으로 열기")
    web.add_argument("-v", "--verbose", action="store_true", help="접근 로그 출력")
    web.set_defaults(handler=cmd_web, command="web")

    return parser


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("media", type=Path, help="입력 영상/오디오 파일")
    p.add_argument("-c", "--config", type=Path, help="설정 파일 (.yaml / .json)")
    p.add_argument("-q", "--quiet", action="store_true", help="진행 로그 숨기기")
    p.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="키=값",
        help="설정 덮어쓰기. 예: --set silence.min_silence=0.5",
    )


def _add_analysis_flags(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("무음")
    g.add_argument("--no-silence", action="store_true", help="무음 컷 끄기")
    g.add_argument(
        "--silence-threshold",
        type=float,
        metavar="dB",
        help="무음 임계값. 안 주면 자동(소음 바닥 기준).",
    )
    g.add_argument(
        "--min-silence", type=float, metavar="초", help="이보다 짧은 무음은 남김"
    )
    g.add_argument(
        "--padding", type=float, metavar="초", help="말소리 앞뒤로 남길 여유"
    )

    g = p.add_argument_group("버벅임")
    g.add_argument("--no-disfluency", action="store_true", help="버벅임 컷 끄기")
    g.add_argument("--no-fillers", action="store_true", help='"음/어/그" 컷 끄기')
    g.add_argument("--no-stutters", action="store_true", help="같은 말 반복 컷 끄기")
    g.add_argument(
        "--retakes",
        action="store_true",
        help="같은 문장을 다시 말한 경우 앞의 것 버리기 (공격적)",
    )
    g.add_argument(
        "--aggressive-fillers",
        action="store_true",
        help='"그러니까/이제/좀/약간"처럼 뜻이 있을 수도 있는 말까지 자르기',
    )
    g.add_argument(
        "--keep-filler",
        action="append",
        default=[],
        metavar="단어",
        help="이 단어는 자르지 않기 (여러 번 지정 가능)",
    )
    g.add_argument(
        "--filler",
        action="append",
        default=[],
        metavar="단어",
        help="필러 사전에 단어 추가 (여러 번 지정 가능)",
    )

    g = p.add_argument_group("음성 인식 / 자막")
    g.add_argument(
        "--no-transcribe",
        action="store_true",
        help="음성 인식 끄기 (무음 컷만 — 자막·버벅임 없음)",
    )
    g.add_argument("--no-subtitles", action="store_true", help="자막 생성 끄기")
    g.add_argument("--model", help="Whisper 모델 (기본 large-v3)")
    g.add_argument("--language", help="언어 코드 (기본 ko)")
    g.add_argument("--device", choices=["auto", "cpu", "cuda"], help="추론 장치")
    g.add_argument("--max-chars", type=int, help="자막 한 줄 최대 글자 수")
    g.add_argument("--no-cache", action="store_true", help="음성 인식 캐시 안 쓰기")

    g = p.add_argument_group("효과음")
    g.add_argument("--no-sfx", action="store_true", help="효과음 끄기")
    g.add_argument(
        "--sfx-library",
        help="내 효과음 폴더. 없으면 내장 합성음(whoosh/pop/ding/riser)을 씁니다.",
    )
    g.add_argument("--sfx-volume", type=float, metavar="0~1", help="효과음 볼륨")
    g.add_argument(
        "--sfx-per-minute", type=float, metavar="개", help="분당 효과음 최대 개수"
    )

    g = p.add_argument_group("자료화면 / 이미지 / GIF")
    g.add_argument("--no-assets", action="store_true", help="자료화면 삽입 끄기")
    g.add_argument(
        "--assets-folder", help="내 소재 폴더 (API 키 없이 동작, 파일 이름이 태그)"
    )
    g.add_argument(
        "--assets-per-minute", type=float, metavar="개", help="분당 소재 최대 개수"
    )
    g.add_argument(
        "--prefer",
        choices=["video", "image", "gif"],
        help="어떤 종류를 우선 넣을지 (video = 자료화면)",
    )


# ---------------------------------------------------------------- config 조립


def _load_config(args) -> Config:
    cfg = Config.load(getattr(args, "config", None))

    overrides: dict = {}
    if getattr(args, "silence_threshold", None) is not None:
        overrides["silence.threshold_db"] = args.silence_threshold
    if getattr(args, "min_silence", None) is not None:
        overrides["silence.min_silence"] = args.min_silence
    if getattr(args, "padding", None) is not None:
        overrides["silence.keep_padding"] = args.padding
    if getattr(args, "model", None):
        overrides["transcribe.model"] = args.model
    if getattr(args, "language", None):
        overrides["transcribe.language"] = args.language
        overrides["disfluency.language"] = args.language
    if getattr(args, "device", None):
        overrides["transcribe.device"] = args.device
    if getattr(args, "max_chars", None) is not None:
        overrides["subtitle.max_chars"] = args.max_chars

    if getattr(args, "no_silence", False):
        overrides["silence.enabled"] = False
    if getattr(args, "no_disfluency", False):
        overrides["disfluency.enabled"] = False
    if getattr(args, "no_fillers", False):
        overrides["disfluency.remove_fillers"] = False
    if getattr(args, "no_stutters", False):
        overrides["disfluency.remove_stutters"] = False
    if getattr(args, "retakes", False):
        overrides["disfluency.remove_retakes"] = True
    if getattr(args, "aggressive_fillers", False):
        overrides["disfluency.aggressive_fillers"] = True
    if getattr(args, "no_transcribe", False):
        overrides["transcribe.enabled"] = False
    if getattr(args, "no_subtitles", False):
        overrides["subtitle.enabled"] = False
    if getattr(args, "burn_subs", False):
        overrides["output.burn_subtitles"] = True
    if getattr(args, "keep_filler", None):
        overrides["disfluency.keep_fillers"] = tuple(args.keep_filler)
    if getattr(args, "filler", None):
        overrides["disfluency.extra_fillers"] = tuple(args.filler)
    if getattr(args, "name", None):
        overrides["output.project_name"] = args.name

    if getattr(args, "no_sfx", False):
        overrides["sfx.enabled"] = False
    if getattr(args, "sfx_library", None):
        overrides["sfx.library"] = args.sfx_library
    if getattr(args, "sfx_volume", None) is not None:
        overrides["sfx.volume"] = args.sfx_volume
    if getattr(args, "sfx_per_minute", None) is not None:
        overrides["sfx.max_per_minute"] = args.sfx_per_minute

    if getattr(args, "no_assets", False):
        overrides["assets.enabled"] = False
    if getattr(args, "assets_folder", None):
        overrides["assets.local_folder"] = args.assets_folder
    if getattr(args, "assets_per_minute", None) is not None:
        overrides["assets.max_per_minute"] = args.assets_per_minute
    if getattr(args, "prefer", None):
        rest = tuple(k for k in ("video", "image", "gif") if k != args.prefer)
        overrides["assets.prefer"] = (args.prefer,) + rest

    cfg.apply_overrides(overrides)

    for item in getattr(args, "set", []) or []:
        key, sep, raw = item.partition("=")
        if not sep:
            raise ValueError(f"--set 형식은 키=값 입니다: {item}")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        cfg.apply_overrides({key.strip(): value})

    return cfg


def _progress(args):
    if getattr(args, "quiet", False):
        return lambda _msg: None
    return lambda msg: print(f"  {msg}", flush=True)


def _run_pipeline(args, cfg: Config, out_dir: Path):
    return pipeline.analyze(
        args.media,
        cfg,
        work_dir=out_dir,
        use_transcript_cache=not getattr(args, "no_cache", False),
        progress=_progress(args),
    )


# ------------------------------------------------------------------- commands


def cmd_analyze(args) -> int:
    cfg = _load_config(args)
    out_dir = Path(args.out) if args.out else Path("capcut-out")
    # 미리보기에서 소재를 내려받으면 느리고 API 쿼터도 먹는다. 명시할 때만 켠다.
    if not args.with_assets:
        cfg.assets.enabled = False
    plan, _info, _words = _run_pipeline(args, cfg, out_dir)

    if args.json:
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print()
    print(_format_summary(plan))
    if args.list_cuts:
        print("\n잘라낼 구간:")
        for cut in plan.cuts:
            print(
                f"  {_hms(cut.span.start)} ~ {_hms(cut.span.end)} "
                f"({cut.span.duration:5.2f}초) [{cut.reason}] {cut.detail}"
            )

    if args.out:
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_plan(plan, out_dir)
        print(f"\n저장: {out_dir}")
    return 0


def cmd_edit(args) -> int:
    cfg = _load_config(args)
    out_dir = Path(args.out) if args.out else Path("capcut-out")
    out_dir.mkdir(parents=True, exist_ok=True)

    plan, info, _words = _run_pipeline(args, cfg, out_dir)
    srt_path = _write_plan(plan, out_dir)

    print()
    print(_format_summary(plan))
    print(f"\n편집안: {out_dir / 'plan.json'}")
    if srt_path:
        print(f"자막:   {srt_path}")

    if plan.overlays:
        credits = out_dir / "credits.md"
        credits.write_text(
            asset_cache.credits_text([o.asset for o in plan.overlays]), encoding="utf-8"
        )
        print(f"출처:   {credits}")

    if not args.no_draft:
        if args.install:
            root = args.drafts_dir or capcut_paths.find()
            if root is None:
                print("\n" + capcut_paths.describe(), file=sys.stderr)
                return 1
            drafts_root = Path(root)
        else:
            drafts_root = out_dir / "drafts"

        # pycapcut 은 드래프트를 구울 때만 필요하다. 카드뉴스처럼 CapCut 과
        # 상관없는 기능까지 이것 때문에 죽지 않도록 여기서 불러온다.
        try:
            from .capcut import draft as draft_mod
        except ImportError as exc:
            print(
                f"\n오류: CapCut 드래프트를 만들려면 pycapcut 이 필요합니다 ({exc}).\n"
                '  pip install -e ".[all]"  로 설치하세요.\n'
                "  (카드뉴스 기능은 이것 없이도 됩니다.)",
                file=sys.stderr,
            )
            return 2

        result = draft_mod.build(
            plan,
            info,
            cfg,
            drafts_root=drafts_root,
            project_name=args.name,
            template=args.template,
            overwrite=args.overwrite,
        )
        print(
            f"\n드래프트({result.mode}): {result.path}\n"
            f"  클립 {result.clip_count}개 / 자막 {result.text_count}줄 / "
            f"자료화면 {result.overlay_count}개 / 효과음 {result.sfx_count}개"
        )
        if args.install:
            print("→ CapCut을 (실행 중이면 껐다가) 다시 열면 목록에 보입니다.")
        else:
            print("→ CapCut에 넣으려면 --install, 또는 위 폴더를 드래프트 폴더로 복사")
        print(f"※ {out_dir / pipeline.ASSETS_DIRNAME} 안의 소재는 지우지 마세요 "
              "(드래프트가 절대 경로로 참조합니다).")

    if args.render is not None:
        target = Path(args.render) if args.render else out_dir / (
            Path(plan.source).stem + "_edited.mp4"
        )
        render_mod.render(
            plan,
            cfg,
            target,
            width=cfg.output.width or info.width or 1920,
            height=cfg.output.height or info.height or 1080,
            srt_path=srt_path,
            work_dir=out_dir / ".render",
            has_audio=info.has_audio,
            slideshow=info.is_audio_only,
            progress=_progress(args),
        )
        print(f"렌더 완료: {target}")

    return 0


def cmd_doctor(_args) -> int:
    ok = True
    print("설치 점검\n")

    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        print(f"  {'OK ' if path else '없음'}  {tool:9s} {path or ''}")
        ok = ok and bool(path)

    try:
        import faster_whisper  # type: ignore  # noqa: F401

        print("  OK   faster-whisper")
    except ImportError:
        print("  없음 faster-whisper   (pip install faster-whisper)")
        print("       → 없으면 자막/버벅임 컷 없이 무음 컷만 됩니다.")

    try:
        import numpy  # type: ignore

        print(f"  OK   numpy          {numpy.__version__}")
    except ImportError:
        print("  없음 numpy           (pip install numpy)")
        ok = False

    try:
        import pycapcut  # type: ignore  # noqa: F401
        import pymediainfo  # type: ignore

        parse = pymediainfo.MediaInfo.can_parse()
        print(f"  {'OK ' if parse else '주의'}  pycapcut")
        if not parse:
            print("       libmediainfo가 없어 소재 정보를 읽지 못합니다.")
            print("       macOS: brew install libmediainfo / Ubuntu: apt install libmediainfo0v5")
            ok = False
    except ImportError:
        print("  없음 pycapcut        (pip install pycapcut)")
        ok = False

    print("\n  자료화면 제공자")
    for env, label in (
        ("PEXELS_API_KEY", "pexels  (이미지+영상)"),
        ("PIXABAY_API_KEY", "pixabay (이미지+영상)"),
        ("GIPHY_API_KEY", "giphy   (GIF)"),
        ("TENOR_API_KEY", "tenor   (GIF)"),
    ):
        has = bool(os.environ.get(env, "").strip())
        print(f"    {'OK ' if has else '없음'}  {label:24s} {env}")
    print("    (하나도 없으면 assets.local_folder 만 쓰거나 --no-assets)")

    print()
    print("  " + capcut_paths.describe().replace("\n", "\n  "))

    root = capcut_paths.find()
    if root:
        drafts = capcut_paths.list_drafts(root)
        print(f"  드래프트 {len(drafts)}개")
        for d in drafts[:10]:
            print(f"    - {d.name}")

    return 0 if ok else 1


def cmd_web(args) -> int:
    from .web.server import serve

    serve(
        host=args.host,
        port=args.port,
        work_root=args.out or Path("capcut-out/web"),
        open_browser=args.open,
        verbose=args.verbose,
    )
    return 0


def cmd_drafts(args) -> int:
    root = args.drafts_dir or capcut_paths.find()
    if root is None:
        print(capcut_paths.describe(), file=sys.stderr)
        return 1
    drafts = capcut_paths.list_drafts(Path(root))
    if not drafts:
        print(f"드래프트가 없습니다: {root}")
        return 0
    print(f"{root}\n")
    for d in drafts:
        print(f"  {d.name}          --template {d.name}")
    return 0


def _cardnews_photos(args, deck, out_dir: Path, say) -> dict:
    """카드에 깔 사진을 모은다. 제공자가 하나도 없으면 조용히 글만 쓴다."""
    if args.photos == "off":
        return {}

    cfg = AssetsConfig(local_folder=args.assets_folder)
    providers = asset_providers.build_providers(cfg, progress=say)
    if not providers:
        say("사진 제공자가 없어 글만 씁니다.")
        say("  --assets-folder 로 내 사진 폴더를 주거나 PEXELS_API_KEY 를 설정하세요.")
        return {}

    say("사진 찾는 중...")
    return cardnews.collect_photos(
        deck,
        providers,
        out_dir / "photos",
        override=args.photos,
        progress=say,
    )


def cmd_cardnews(args) -> int:
    text = args.script.read_text(encoding="utf-8")
    deck = cardnews.parse(text)

    try:
        style = cardnews.build_style(
            cardnews.resolve_theme(args.theme),
            cardnews.resolve_size(args.size),
            font=args.font,
            handle=args.handle,
            source=args.source,
            photo_mode=args.photos,
            backdrop=args.backdrop,
        )
    except cardnews.FontMissing as exc:
        print(f"\n오류: {exc}", file=sys.stderr)
        return 2

    out_dir = args.out or Path("capcut-out") / "cardnews"
    say = (lambda _m: None) if args.quiet else print

    found = _cardnews_photos(args, deck, out_dir, say)
    if found and not args.source:
        # 출처를 안 줬으면 사진 출처라도 자동으로 박는다. 스톡 약관상 필요한 경우가 많다.
        style = replace(style, source=cardnews.photo_credits(found))

    say(f"카드 {len(deck)}장 → {out_dir}")
    paths = cardnews.render_deck(deck, out_dir, style, photos=found, progress=say)

    # CC BY 는 저작자 표시가 의무다. 카드 한 줄에는 다 못 들어가니 따로 뽑는다.
    notes = cardnews.photo_attribution(found)
    if notes:
        (out_dir / "출처.md").write_text(notes, encoding="utf-8")
        say(f"\n사진 출처: {out_dir / '출처.md'}  ← 캡션에 붙여 넣으세요")

    say(
        f"\n완료: {len(paths)}장\n"
        f"  인스타 캐러셀에 이 순서 그대로 올리면 됩니다.\n"
        f"  같은 폴더로 릴스까지 뽑으려면:\n"
        f"    {PROG} edit 대본음성.mp3 --assets-folder {out_dir}"
    )
    return 0


# --------------------------------------------------------------------- 헬퍼


def _write_plan(plan, out_dir: Path) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not plan.subtitles:
        return None
    srt_path = out_dir / "subtitles.srt"
    srt_path.write_text(subtitles.to_srt(plan.subtitles), encoding="utf-8")
    return srt_path


def _hms(seconds: float) -> str:
    return subtitles.format_timestamp(seconds, sep=".")[:-1]


def _format_summary(plan) -> str:
    s = plan.summary()
    lines = [
        "── 편집 요약 ─────────────────────────────",
        f"  원본     {s['source_duration']:8.2f}초",
        f"  결과     {s['output_duration']:8.2f}초"
        f"   (-{s['removed_duration']:.2f}초, {s['removed_ratio'] * 100:.1f}%)",
        f"  클립     {s['clip_count']}개",
        f"  자막     {s['subtitle_count']}줄",
        f"  효과음   {s['sfx_count']}개",
        f"  자료화면 {s['overlay_count']}개",
    ]
    if s["removed_by_reason"]:
        lines.append("  제거 내역")
        labels = {
            "silence": "무음",
            "filler": "간투사",
            "stutter": "더듬음",
            "retake": "재촬영",
            "manual": "수동",
        }
        for reason, secs in s["removed_by_reason"].items():
            count = s["cut_count_by_reason"].get(reason, 0)
            lines.append(
                f"    {labels.get(reason, reason):6s} {secs:7.2f}초  ({count}개)"
            )
    lines.append("──────────────────────────────────────────")
    return "\n".join(lines)


__all__ = ["main"]
