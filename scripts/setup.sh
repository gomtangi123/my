#!/usr/bin/env bash
#
# capcut-auto 로컬 설치 (macOS / Linux)
#
#   ./scripts/setup.sh          설치하고 점검까지
#   ./scripts/setup.sh --web    설치한 뒤 웹 UI까지 바로 실행
#   ./scripts/setup.sh --no-venv  가상환경 없이 현재 파이썬에 설치
#
# 시스템 패키지(ffmpeg 등)는 물어보고 나서 설치한다. 마음대로 건드리지 않는다.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

USE_VENV=1
LAUNCH_WEB=0
for arg in "$@"; do
  case "$arg" in
    --no-venv) USE_VENV=0 ;;
    --web) LAUNCH_WEB=1 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "모르는 옵션: $arg"; exit 1 ;;
  esac
done

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
warn() { printf '\033[33m%s\033[0m\n' "$1"; }
fail() { printf '\033[31m%s\033[0m\n' "$1" >&2; }

ask() {
  # 사용자가 파이프로 실행 중이면(비대화형) 자동 설치하지 않는다
  [ -t 0 ] || return 1
  printf '%s [y/N] ' "$1"
  read -r reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

# ------------------------------------------------------------ 1. 파이썬
bold "1/4  파이썬 확인"
PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
      PY="$candidate"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  fail "파이썬 3.10 이상이 필요합니다."
  echo "  macOS : brew install python@3.12"
  echo "  Ubuntu: sudo apt install python3.12 python3.12-venv"
  exit 1
fi
echo "     $($PY --version)  ($(command -v "$PY"))"

# ------------------------------------------------- 2. 시스템 패키지 확인
# 여기서는 ffmpeg만 본다. libmediainfo는 요즘 pymediainfo 휠에 같이 들어 있어서
# 설치 전에 미리 판단하면 멀쩡한데도 "없음"으로 잘못 뜬다. 그건 설치가 끝난 뒤
# doctor가 실제로 로드해 보고 판정한다.
bold "2/4  ffmpeg 확인"
OS="$(uname -s)"
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  echo "     있습니다  ($(command -v ffmpeg))"
else
  warn "     ffmpeg가 없습니다"
  if [ "$OS" = "Darwin" ]; then
    if command -v brew >/dev/null 2>&1; then
      CMD="brew install ffmpeg"
    else
      fail "     Homebrew가 없습니다. https://brew.sh 에서 설치한 뒤 다시 실행하세요."
      exit 1
    fi
  elif command -v apt-get >/dev/null 2>&1; then
    CMD="sudo apt-get install -y ffmpeg"
  elif command -v dnf >/dev/null 2>&1; then
    CMD="sudo dnf install -y ffmpeg"
  else
    fail "     패키지 관리자를 못 찾았습니다. ffmpeg를 직접 설치해 주세요."
    exit 1
  fi

  echo "     실행할 명령: $CMD"
  if ask "     지금 설치할까요?"; then
    eval "$CMD"
  else
    warn "     건너뜁니다. 나중에 위 명령을 직접 실행하세요."
  fi
fi

# ------------------------------------------------------------ 3. 설치
bold "3/4  capcut-auto 설치"
PIP_PREFIX=""
if [ "$USE_VENV" = "1" ]; then
  if [ ! -d "$ROOT/.venv" ]; then
    "$PY" -m venv "$ROOT/.venv"
    echo "     가상환경 생성: .venv"
  else
    echo "     기존 가상환경 사용: .venv"
  fi
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  PY="$ROOT/.venv/bin/python"
fi

"$PY" -m pip install --upgrade pip --quiet
echo "     의존성 설치 중… (Whisper 포함, 몇 분 걸릴 수 있습니다)"
"$PY" -m pip install -e "$ROOT[all]" --quiet
echo "     완료"

# ------------------------------------------------------------ 4. 점검
bold "4/4  설치 점검"
if ! "$PY" -m capcut_auto doctor; then
  echo
  warn "필수 항목이 빠져 있습니다. 위 목록에서 '없음'을 보고 채워 주세요."
fi

echo
bold "다음 단계"
if [ "$USE_VENV" = "1" ]; then
  echo "  source .venv/bin/activate     # 새 터미널을 열 때마다"
fi
echo "  capcut-auto web --open        # 브라우저에서 쓰기"
echo "  capcut-auto edit 영상.mp4 --install"
echo
echo "  Whisper 모델은 첫 편집 때 한 번 내려받습니다(small 기준 약 500MB)."

if [ "$LAUNCH_WEB" = "1" ]; then
  echo
  bold "웹 UI를 시작합니다…"
  exec "$PY" -m capcut_auto web --open
fi
