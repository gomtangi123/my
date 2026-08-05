# capcut-auto 로컬 설치 (Windows / PowerShell)
#
#   .\scripts\setup.ps1          설치하고 점검까지
#   .\scripts\setup.ps1 -Web     설치한 뒤 웹 UI까지 바로 실행
#   .\scripts\setup.ps1 -NoVenv  가상환경 없이 현재 파이썬에 설치
#
# 실행이 막히면 (실행 정책):
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1

param(
    [switch]$Web,
    [switch]$NoVenv
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Write-Step($text) { Write-Host $text -ForegroundColor Cyan }
function Write-Warn($text) { Write-Host $text -ForegroundColor Yellow }
function Write-Fail($text) { Write-Host $text -ForegroundColor Red }

# ------------------------------------------------------------ 1. 파이썬
Write-Step "1/4  파이썬 확인"
$py = $null
foreach ($candidate in @("python", "python3", "py")) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $found) { continue }
    $check = & $candidate -c "import sys; print(1 if sys.version_info >= (3,10) else 0)" 2>$null
    if ($check -eq "1") { $py = $candidate; break }
}
if (-not $py) {
    Write-Fail "파이썬 3.10 이상이 필요합니다."
    Write-Host "  winget install Python.Python.3.12"
    Write-Host "  설치할 때 'Add Python to PATH'를 꼭 체크하세요."
    exit 1
}
Write-Host "     $(& $py --version)"

# ------------------------------------------------------------- 2. ffmpeg
Write-Step "2/4  시스템 패키지 확인"
$hasFfmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue) -and
             (Get-Command ffprobe -ErrorAction SilentlyContinue)
if ($hasFfmpeg) {
    Write-Host "     ffmpeg 있습니다"
} else {
    Write-Warn "     ffmpeg가 없습니다"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $answer = Read-Host "     winget으로 지금 설치할까요? [y/N]"
        if ($answer -match "^[Yy]$") {
            winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
            Write-Warn "     설치 후에는 PowerShell을 새로 열어야 PATH가 잡힙니다."
        } else {
            Write-Warn "     건너뜁니다. 나중에 'winget install Gyan.FFmpeg' 를 실행하세요."
        }
    } else {
        Write-Fail "     winget이 없습니다. https://ffmpeg.org 에서 직접 받아 PATH에 추가하세요."
    }
}
# libmediainfo는 Windows에서 pymediainfo 휠에 들어 있어 따로 설치할 필요가 없다.

# ------------------------------------------------------------- 3. 설치
Write-Step "3/4  capcut-auto 설치"
if (-not $NoVenv) {
    if (-not (Test-Path "$Root\.venv")) {
        & $py -m venv "$Root\.venv"
        Write-Host "     가상환경 생성: .venv"
    } else {
        Write-Host "     기존 가상환경 사용: .venv"
    }
    $py = "$Root\.venv\Scripts\python.exe"
}

& $py -m pip install --upgrade pip --quiet
Write-Host "     의존성 설치 중… (Whisper 포함, 몇 분 걸릴 수 있습니다)"
& $py -m pip install -e "$Root[all]" --quiet
Write-Host "     완료"

# ------------------------------------------------------------- 4. 점검
Write-Step "4/4  설치 점검"
& $py -m capcut_auto doctor

Write-Host ""
Write-Step "다음 단계"
if (-not $NoVenv) {
    Write-Host "  .\.venv\Scripts\Activate.ps1   # 새 터미널을 열 때마다"
}
Write-Host "  capcut-auto web --open         # 브라우저에서 쓰기"
Write-Host "  capcut-auto edit 영상.mp4 --install"
Write-Host ""
Write-Host "  Whisper 모델은 첫 편집 때 한 번 내려받습니다(small 기준 약 500MB)."

if ($Web) {
    Write-Host ""
    Write-Step "웹 UI를 시작합니다…"
    & $py -m capcut_auto web --open
}
