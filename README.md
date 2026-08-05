# capcut-auto

영상 하나를 넣으면 **무음·버벅임을 잘라내고, 자막을 달고, 효과음을 깔고, 자료화면까지 얹은
CapCut 드래프트**를 만들어 줍니다. CapCut에서 열면 이미 편집이 끝나 있고, 마음에 안 드는
부분만 손보면 됩니다.

드래프트 생성은 [`pycapcut`](https://github.com/GuanYixuan/pycapcut)이 담당합니다.

```
영상.mp4
   │
   ├─ 무음 검출        RMS + 히스테리시스
   ├─ 음성 인식        faster-whisper (단어 단위 타임스탬프)
   ├─ 버벅임 검출      필러 / 더듬음 / 재촬영
   ├─ 자막 생성        컷을 반영해 다시 싱크
   ├─ 효과음 배치      전환 / 화제전환 / 강조
   └─ 자료화면 검색    키워드 → Pexels·Pixabay·Giphy·내 폴더
   │
   └─→ CapCut 드래프트 (본편 / 오버레이 / 자막 / 효과음 4트랙)
```

---

## 설치

```bash
pip install -e ".[all]"
```

시스템 의존성 두 가지가 필요합니다.

| 무엇 | 왜 | 설치 |
|---|---|---|
| **ffmpeg** | 오디오 디코딩, 렌더링 | `brew install ffmpeg` / `winget install Gyan.FFmpeg` / `apt install ffmpeg` |
| **libmediainfo** | pycapcut이 소재 길이·해상도를 읽음 | `brew install libmediainfo` / `apt install libmediainfo0v5` (Windows는 pip 패키지에 포함) |

제대로 깔렸는지 확인:

```bash
capcut-auto doctor
```

---

## 빠르게 써 보기

```bash
# 1) 뭘 자를지만 미리 보기 (파일을 건드리지 않음)
capcut-auto analyze 영상.mp4 --list-cuts

# 2) 편집해서 CapCut에 바로 꽂기
capcut-auto edit 영상.mp4 --install

# 3) CapCut 없이 완성본 뽑기
capcut-auto edit 영상.mp4 --render 결과.mp4 --burn-subs
```

`--install`을 주면 CapCut 드래프트 폴더에 바로 만들어집니다. CapCut이 켜져 있었다면
껐다 켜야 목록에 보입니다.

---

## 다섯 가지 자동화

### 1. 무음 컷

고정 임계값(`-30dB` 같은)은 녹음 환경이 바뀔 때마다 손봐야 합니다. 여기서는 프레임별
RMS를 재서 **소음 바닥(noise floor) 대비 상대적으로** 임계값을 잡습니다. 조용히 말해도
잡히고, 에어컨 소리가 있어도 오탐이 적습니다.

말끝이 잘리지 않도록 히스테리시스(켤 때 +1.5dB, 끌 때 −1.5dB)를 걸고, `min_silence`
보다 짧은 틈은 숨 쉬는 간격으로 보고 남깁니다.

```bash
capcut-auto edit 영상.mp4 --min-silence 0.5 --padding 0.12
```

### 2. 버벅임 컷

Whisper의 단어 단위 타임스탬프 위에서 세 가지를 잡습니다.

| 종류 | 예시 | 동작 |
|---|---|---|
| 필러 | "음", "어", "그", "저기", "흠" | 그 단어만 도려냄 |
| 더듬음 | "그 그 그러니까", "그러니 → 그러니까" | 마지막 발화만 남김 |
| 재촬영 | 같은 문장을 다시 말함 | 앞의 것을 버림 (`--retakes`) |

기본 사전에는 **거의 언제나 군말인 말만** 들어 있습니다. "그러니까", "이제", "좀",
"약간", "진짜"처럼 뜻을 가질 수 있는 말은 지우면 문장이 상하므로 기본으로는 건드리지
않습니다. 말이 많이 늘어지는 영상이라면 켜세요:

```bash
capcut-auto edit 영상.mp4 --aggressive-fillers
```

한 글자 접두사 반복도 기본적으로 건드리지 않습니다. "이 이야기"의 '이'는 더듬은 게
아니라 관형사이기 때문입니다(`stutter_min_prefix`).

내 입버릇을 넣거나 빼려면:

```bash
capcut-auto edit 영상.mp4 --filler 아무튼 --keep-filler 그
```

### 3. 자막

자막은 **컷 이전** 타임라인에서 만들고 나서 컷을 반영해 다시 매핑합니다. 그래서
필러를 잘라내면 자막 문구에서도 그 단어가 사라집니다. 문장부호와 말 사이 간격으로
줄을 끊고, `max_chars`에 맞춰 접습니다.

SRT 파일도 함께 나오므로 CapCut·프리미어·유튜브 어디에나 넣을 수 있습니다.

### 4. 효과음

효과음 파일이 없어도 동작합니다. `numpy`로 whoosh·swoosh·pop·ding·click·thud·riser·
boing을 직접 합성해서 씁니다(저작권 문제 없음). 배치 규칙은 세 가지입니다.

- **전환** — 컷 이음매마다. 단, `transition_min_gap`보다 조금 잘린 자리는 건너뜁니다.
- **화제 전환** — 크게 잘린 자리에는 라이저를 깔되, **이음매에서 끝나도록** 배치합니다.
- **강조** — 숫자, "가장/최고/절대" 같은 강조어, 물음표.

`min_interval`과 `max_per_minute`으로 밀도를 제한합니다. 이게 없으면 금세 촌스러워집니다.

내 효과음 폴더를 쓰려면 — 파일 이름이 곧 태그입니다:

```
sfx/
  transition/whoosh_01.wav   → {transition, whoosh, 01}
  pop_bubble.wav             → {pop, bubble}
```

```bash
capcut-auto edit 영상.mp4 --sfx-library ./sfx --sfx-volume 0.25
```

### 5. 자료화면 / 이미지 / GIF

자막 한 줄을 후보 자리로 보고, 그 안에서 키워드를 뽑아 점수를 매긴 뒤 점수가 높은
자리부터 채웁니다. 형태소 분석기 없이도 돌아가도록 조사 제거 + 용언 활용형 필터 +
불용어로 처리하고, `konlpy`가 설치돼 있으면 그쪽을 씁니다.

한국어 키워드는 영어로 바꿔서 검색합니다("인공지능" → "artificial intelligence").
스톡 사이트는 영어 검색 결과가 압도적으로 좋기 때문입니다. 사전에 없는 말은 그대로
검색하고, `assets.query_map`으로 내 채널 주제어를 덧붙일 수 있습니다.

**소스 선택 (하나만 있으면 됩니다):**

```bash
# A. 내 소재 폴더 — API 키 불필요. 파일 이름이 태그
capcut-auto edit 영상.mp4 --assets-folder ./broll

# B. 무료 스톡 API
export PEXELS_API_KEY=...     # 이미지 + 자료화면   https://www.pexels.com/api/
export PIXABAY_API_KEY=...    # 이미지 + 자료화면   https://pixabay.com/api/docs/
export GIPHY_API_KEY=...      # GIF                https://developers.giphy.com/
export TENOR_API_KEY=...      # GIF                https://tenor.com/gifapi
capcut-auto edit 영상.mp4
```

키가 하나도 없고 소재 폴더도 없으면 이 단계만 건너뛰고 나머지는 그대로 동작합니다.

자료화면은 화면을 꽉 채우고(원본 소리는 음소거), 이미지·GIF는 자막을 가리지 않도록
위쪽에 띄웁니다. 사용된 소재의 출처는 `credits.md`로 저장됩니다 — 스톡 사이트 약관상
크레딧이 필요한 경우가 많습니다.

---

## 출력물

```
capcut-out/
  plan.json          편집안 전체 (컷 근거, 자막, 효과음, 소재)
  subtitles.srt      자막
  credits.md         사용된 소재 출처
  assets/            내려받은 자료화면 + 합성한 효과음  ← 지우면 안 됨
  drafts/<이름>/     CapCut 드래프트 (--install이면 CapCut 폴더에 직접 생성)
```

> **주의**: CapCut 드래프트는 소재를 **절대 경로**로 참조합니다. `assets/` 폴더를
> 지우거나 옮기면 드래프트에 빈 클립이 생깁니다.

---

## 자주 쓰는 옵션

```bash
# 무음 컷만 (음성 인식 없이 — 가장 빠름)
capcut-auto edit 영상.mp4 --no-transcribe

# 컷과 자막만, 효과음·자료화면 없이
capcut-auto edit 영상.mp4 --no-sfx --no-assets

# 세로 숏폼
capcut-auto edit 영상.mp4 --max-chars 14 --set output.width=1080 --set output.height=1920

# GPU가 없어서 느릴 때
capcut-auto edit 영상.mp4 --model small --device cpu

# 기존 드래프트의 프로젝트 설정을 물려받기
capcut-auto drafts                                  # 이름 확인
capcut-auto edit 영상.mp4 --template 내템플릿 --install
```

설정 파일로 고정해 두는 게 편합니다:

```bash
cp config.example.yaml myconfig.yaml
capcut-auto edit 영상.mp4 -c myconfig.yaml --install
```

`--set`으로 어떤 설정이든 즉석에서 덮어쓸 수 있습니다:

```bash
capcut-auto edit 영상.mp4 --set sfx.max_per_minute=6 --set assets.prefer='["image"]'
```

---

## 동작 방식 메모

- **시간은 전부 초(float)** 로 다루고, CapCut으로 나갈 때만 마이크로초 정수로 바꿉니다.
- **컷은 구간 대수(interval algebra)** 로 계산합니다. 무음 구간과 버벅임 구간을 합집합
  으로 묶고, 여집합이 남길 구간이 됩니다. `TimeMap`이 컷 전/후 시각을 옮겨 주고,
  자막·효과음·자료화면이 전부 이 매핑을 통과합니다.
- **음성 인식 결과는 캐시**됩니다. 같은 영상으로 설정만 바꿔가며 여러 번 돌릴 때
  매번 몇 분씩 기다리지 않아도 됩니다.

---

## 한계

- CapCut 데스크톱은 Windows/macOS 전용입니다. 리눅스에서는 드래프트 파일 생성과
  `--render`(ffmpeg)까지만 됩니다.
- 자료화면 적중률은 키워드 추출 품질에 달려 있습니다. 전문 용어가 많은 영상이라면
  `assets.query_map`을 채워 두는 편이 낫습니다.
- 재촬영(`--retakes`) 검출은 공격적입니다. 먼저 `analyze --list-cuts`로 확인하세요.

---

## 개발

```bash
pip install -e ".[dev]"
pytest -q
```

테스트는 ffmpeg 없이 돕니다. 드래프트 통합 테스트는 PIL로 만든 이미지와
합성한 wav를 소재로 써서 pycapcut 조립 결과를 실제로 검증합니다.
