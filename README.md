# capcut-auto

영상 하나를 넣으면 **무음·버벅임을 잘라내고, 자막을 달고, 효과음을 깔고, 자료화면까지 얹은
CapCut 드래프트**를 만들어 줍니다. CapCut에서 열면 이미 편집이 끝나 있고, 마음에 안 드는
부분만 손보면 됩니다.

드래프트 생성은 [`pycapcut`](https://github.com/GuanYixuan/pycapcut)이 담당합니다.

**입력은 영상 또는 대본 음성입니다.** 음성 파일(mp3·wav·m4a)만 올리면
올려 둔 이미지로 슬라이드쇼 영상을 만듭니다 — 이미지가 화면이 되고
음성이 내레이션으로 깔립니다.

```
영상.mp4  또는  대본음성.mp3 + 이미지들
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

음성만 넣은 경우의 트랙 구성은 이렇게 바뀝니다.

```
   video "main"       이미지들이 차례로 (화면 꽉 채움)
   audio "narration"  대본 음성 (무음 잘라낸 구간만)
   text  "sub"        자막
   audio "sfx"        효과음
```

---

## 설치

**macOS / Linux**

```bash
git clone -b claude/capcut-automation-tool-x5031c https://github.com/gomtangi123/my.git
cd my
./scripts/setup.sh --web
```

**Windows** — cmd / Anaconda Prompt / PowerShell 어디서든

```
git clone -b claude/capcut-automation-tool-x5031c https://github.com/gomtangi123/my.git
cd my
scripts\setup.bat --web
```

> Windows에서 `./scripts/setup.sh` 는 동작하지 않습니다. 그건 macOS/Linux용입니다.
> Anaconda를 쓰신다면 스크립트가 알아서 감지해서 ffmpeg를 conda로 깝니다
> (관리자 권한이 필요 없습니다). 이미 쓰던 conda 환경에 그대로 설치하려면
> `scripts\setup.bat --no-venv --web`.

스크립트가 파이썬 버전을 확인하고, ffmpeg가 없으면 **물어본 뒤** 설치하고,
가상환경(`.venv`)을 만들어 의존성을 깔고, 마지막으로 점검까지 합니다.
`--web`(PowerShell은 `-Web`)을 붙이면 끝나자마자 브라우저까지 열어 줍니다.

다음부터는 가상환경만 켜면 됩니다.

```bash
source .venv/bin/activate      # Windows: .\.venv\Scripts\Activate.ps1
capcut-auto web --open
```

<details>
<summary>직접 설치하고 싶다면</summary>

```bash
pip install -e ".[all]"
```

시스템 의존성은 **ffmpeg 하나**입니다 — 오디오 디코딩과 렌더링에 씁니다.
(`brew install ffmpeg` / `winget install Gyan.FFmpeg` / `apt install ffmpeg`)

pycapcut이 소재 길이·해상도를 읽는 데 쓰는 libmediainfo는 보통 `pymediainfo`
휠에 함께 들어 있습니다. `doctor`가 `pycapcut` 줄에 `주의`를 띄울 때만
따로 설치하세요 (`brew install libmediainfo` / `apt install libmediainfo0v5`).

</details>

제대로 깔렸는지는 언제든 확인할 수 있습니다.

```bash
capcut-auto doctor
```

---

## 빠르게 써 보기

터미널이 익숙하지 않다면 **웹 UI**가 제일 쉽습니다.

```bash
capcut-auto web --open
```

브라우저가 열리면 영상을 끌어다 놓고, 켜고 끌 항목을 고른 뒤 「편집 시작」을
누르면 됩니다. 진행 상황이 실시간으로 보이고, 끝나면 결과 미리보기·컷 내역·
다운로드·「CapCut에 설치」 버튼이 나옵니다. 자세한 내용은 [웹 UI](#웹-ui) 참고.

명령줄이 편하다면:

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

## 대본 음성 + 이미지로 영상 만들기

영상 촬영 없이 **내레이션 음성과 이미지만으로** 영상을 만들 수 있습니다.

1. 웹 UI에 **음성 파일**(mp3·wav·m4a)을 끌어다 놓습니다
2. 「자료 이미지 넣기」에 **쓸 이미지들**을 올립니다
3. 「편집 시작」

이미지가 화면 전체를 채우며 차례로 넘어가고, 음성은 무음을 잘라낸 뒤
내레이션 트랙으로 깔립니다. 자막·효과음도 그대로 붙습니다.
**이미지는 파일 이름 순서대로, 한 장씩 한 번만** 쓰이고 전체 길이를 고르게
나눠 갖습니다 — 3장에 13초짜리면 한 장에 4.3초씩입니다.
`1.png` ~ `20.png` 처럼 번호를 매기면 그 순서가 그대로 화면 순서가 됩니다.

각 이미지는 **CapCut에서 따로 만질 수 있는 개별 클립**으로 들어가고,
클립 경계는 **프레임에 딱 맞춰** 놓습니다. 그래서 타임라인에서 끝을 끌어
길이를 조절할 때 반 프레임씩 어긋나는 일이 없고, 스무 장을 넣어도 오차가
쌓여 마지막이 음성과 어긋나지 않습니다. 균등 분배는 어디까지나 출발점이니
나머지는 CapCut에서 편하게 맞추시면 됩니다.

이미지가 화면 그 자체이므로 「자료화면·이미지」와 「처음부터 끝까지 채우기」는
음성 파일을 올리는 순간 자동으로 켜집니다. 꺼 두면 화면이 아예 안 만들어지기
때문에, 꺼져 있어도 무시하고 켭니다.

> 화면 크기는 첫 이미지 크기를 따라갑니다. 세로 숏폼으로 뽑으려면
> 「세부 설정」의 「세로 숏폼」을 켜세요.

---

## 인스타 카드뉴스 만들기

대본 한 편으로 **인스타 캐러셀에 그대로 올릴 이미지 세트**를 뽑습니다.
캐러셀은 저장·공유를 먹고, 같은 이미지로 릴스를 만들면 도달을 먹습니다 —
한 번 쓴 소재를 두 군데에 씁니다.

```bash
capcut-auto cardnews 대본.txt --handle "@myshop"
```

대본은 메모장에서 그냥 써도 되는 평문입니다. `---` 한 줄이 카드 경계이고,
`#`으로 시작하는 줄이 그 카드의 제목입니다.

```
# 월 30만원 아끼는 법
아무도 안 알려주는 것

---

## 1. 통신비
알뜰폰으로 바꾸면 끝입니다.
번호도 그대로 갑니다.

---

@마무리
## 결론
오늘 하나만 바꿔 보세요
```

- **첫 카드는 표지**입니다. 피드에서 넘길지 말지는 사실상 이 한 장이 정하므로
  글씨를 크게 잡고, 본문과 색을 뒤집고, 「넘겨보세요 →」를 붙입니다.
- **한 줄짜리 카드**는 문단이 아니라 한마디로 보고 크게 박습니다.
- `@표지` / `@마무리` 를 카드 첫 줄에 쓰면 종류를 직접 지정할 수 있습니다.
- 글자 크기는 **상자에 맞춰 자동으로** 줄어듭니다. 한국어는 어절이 길어
  넘치기 쉬운데, 어절로 먼저 나누고 그래도 넘치면 글자 단위로 쪼갭니다.

| 옵션 | 설명 |
|---|---|
| `-t, --theme` | `light` · `dark` · `bold` · `paper` (기본 `light`) |
| `-s, --size` | `post` 1080×1350 (기본) · `square` · `story`, 또는 `1080x1350` |
| `--handle` | 카드 아래에 박을 계정명 |
| `--font` | 글꼴 파일 경로. 기본은 OS에서 한글 글꼴을 자동으로 찾습니다 |
| `-o, --out` | 저장 폴더 (기본 `./capcut-out/cardnews`) |

파일은 `01.png`부터 번호가 붙어 나오므로 업로드 화면에서 순서가 그대로
지켜집니다. 그 폴더를 그대로 슬라이드쇼 입력으로 넘기면 릴스가 됩니다.

```bash
capcut-auto cardnews 대본.txt -o ./cards
capcut-auto edit 내레이션.mp3 --assets-folder ./cards
```

> 이미지 그리기에는 Pillow가 필요합니다 — `pip install "capcut-auto[cardnews]"`.
> 리눅스에서 한글이 네모로 나오면 `apt install fonts-nanum` 하거나
> `--font` 으로 `.ttf` 경로를 직접 주세요.

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
위쪽에 띄웁니다. 크기는 `assets.image_scale`(웹 UI의 「이미지 크기」)로 조절합니다 —
`1.0`이면 화면을 꽉 채웁니다.

깔리는 방식은 두 가지입니다.

| `assets.coverage` | 동작 |
|---|---|
| `spots` (기본) | 키워드가 맞는 자리에만 띄엄띄엄. 간격·분당 개수 제한을 지킵니다 |
| `full` | 처음부터 끝까지 빈틈없이. 자막이 없어도 동작합니다 |

`full`에서 소재가 모자랄 때의 동작은 `assets.reuse`가 정합니다.

| `assets.reuse` | 동작 |
|---|---|
| `false` (기본) | 한 장씩 한 번만. 전체 길이를 장수로 나눠 고르게 배분합니다. 영상·GIF는 제 길이를 넘지 않고, 남는 시간은 이미지들이 나눠 갖습니다 |
| `true` | 순서대로 돌려 씁니다 (바로 앞에 나온 것과는 겹치지 않게) | 사용된 소재의 출처는 `credits.md`로 저장됩니다 — 스톡 사이트 약관상
크레딧이 필요한 경우가 많습니다.

---

## 웹 UI

**Windows에서 가장 쉬운 방법**: repo 폴더의 **`시작하기.bat`** 을 더블클릭하세요.
환경을 켜고 브라우저까지 알아서 열어 줍니다. 바탕화면에 바로가기를 만들어 두면
다음부터는 클릭 한 번이면 됩니다.

명령줄로 켤 때:

```bash
capcut-auto web              # http://127.0.0.1:8765
capcut-auto web --open       # 브라우저까지 열기
capcut-auto web -p 9000      # 포트 바꾸기
```

> 새 터미널을 열 때마다 `conda activate capcut` 과 repo 폴더로 `cd` 가 필요합니다.
> `시작하기.bat` 은 그 두 가지를 대신해 줍니다.

한 화면에서 다 됩니다.

1. **영상 끌어다 놓기** — 드래그 앤 드롭 또는 클릭해서 고르기
2. **무엇을 자동으로 할지 고르기** — 무음 컷 / 버벅임 컷 / 자막 / 효과음 /
   자료화면, 그리고 미리보기 영상 생성 여부. 「세부 설정」을 펼치면 Whisper
   모델, 자막 글자 수, 효과음 볼륨, 내 소재 폴더 같은 것도 조절할 수 있습니다.
3. **진행 상황** — 어느 단계를 지나고 있는지 로그가 실시간으로 흐릅니다.
4. **자료 이미지 넣기 (선택)** — 직접 쓸 사진·GIF·영상을 끌어다 놓으면
   말하는 내용의 키워드와 맞는 자리에 알아서 얹습니다. **파일 이름이 곧
   검색어**라서 `서울_야경.jpg`, `커피.png` 처럼 지어 주면 됩니다.
   스톡 사이트를 쓰고 싶으면 「세부 설정」에 API 키를 붙여넣으면 됩니다
   (환경변수를 안 만들어도 됩니다).
   **파일 이름 순서대로** 들어갑니다 — `1.jpg`, `2.jpg` … `20.jpg` 처럼
   번호를 매기면 그 순서 그대로입니다. 숫자를 숫자로 읽으므로
   `10`이 `2`보다 뒤로 갑니다.
   「**처음부터 끝까지 채우기**」를 켜면 띄엄띄엄이 아니라 영상 전체를
   빈틈없이 덮습니다. **기본적으로 한 장씩 한 번만** 쓰고, 영상 길이를
   장수로 나눠 고르게 배분합니다(10장 · 60초 → 한 장에 6초).
   같은 이미지가 여러 번 나와도 괜찮다면 「이미지 반복해서 쓰기」를 켜세요.
5. **결과** — 요약 숫자, 어디가 왜 잘렸는지 보여 주는 컬러 타임라인,
   컷·자막·효과음·자료화면 목록, 미리보기 재생, 그리고 다운로드
   (드래프트 .zip / .srt / plan.json / 미리보기 .mp4).
6. **「CapCut에 설치」** — 이 PC에서 CapCut 드래프트 폴더를 찾으면 버튼이 뜹니다.
   누르면 바로 복사되고, CapCut을 껐다 켜면 목록에 보입니다.

시작할 때 ffmpeg·faster-whisper·자료화면 API 키가 있는지 검사해서 없으면
화면 위에 알려 줍니다. 없는 기능만 건너뛰고 나머지는 그대로 돕니다.

> **보안**: 기본으로 `127.0.0.1`에만 열립니다. 이 서버는 올라온 파일을 로컬에서
> 처리하고 로컬 경로를 돌려주므로 인증이 없습니다. `--host 0.0.0.0`으로
> 외부에 노출하지 마세요.

---

## 출력물

```
capcut-out/
  plan.json          편집안 전체 (컷 근거, 자막, 효과음, 소재)
  subtitles.srt      자막
  credits.md         사용된 소재 출처
  assets/            내려받은 자료화면 + 합성한 효과음  ← 지우면 안 됨
  drafts/<이름>/     CapCut 드래프트 (--install이면 CapCut 폴더에 직접 생성)

capcut-out/web/      웹 UI를 쓸 때
  uploads/<id>/      올린 원본 (파일 이름은 ASCII로 바꿔 저장 — 아래 참고)
  library/<id>/      브라우저에서 올린 내 자료 이미지 + .tags.json
  jobs/<id>/         작업별 결과 (위와 같은 구조 + preview.mp4, draft .zip)
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
- **올린 파일은 ASCII 이름으로 저장**합니다. 윈도우에서 경로에 한글이 있으면
  ffprobe 호출이 빈손으로 돌아오기 때문입니다. 화면에 보이는 이름과 드래프트
  이름은 원래대로 유지되고, 자료 이미지의 한글 이름은 `.tags.json`에 남겨
  검색어로 계속 씁니다.
- **컷 구간은 소재 길이에 맞춰 잘립니다.** ffprobe와 pycapcut이 재는 길이가
  몇 밀리초 다를 수 있어서, 그대로 두면 pycapcut이 세그먼트를 거부합니다.

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
합성한 wav를 소재로 써서 pycapcut 조립 결과를 실제로 검증하고, 웹 테스트는
실제로 소켓을 열어 업로드·Range 요청·SSE·경로 탈출 방어를 확인합니다.
