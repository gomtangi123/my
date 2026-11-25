# 축구 분석·예측 웹사이트

유럽 4대 리그·유럽 중소 리그·K리그1·J1리그·AFC 챔피언스리그를 대상으로 하는 축구 통계·예측 사이트.
기획은 [CLAUDE.md](CLAUDE.md), 단계별 진행은 [단계별_프롬프트.md](단계별_프롬프트.md) 참고.

## 3단계: 기본 통계 + 피처

```bash
cd football
python -m backend.scripts.show_stats --league eng_premier_league            # 순위표 + 1위 팀 통계 + 다가오는 경기 피처
python -m backend.scripts.show_stats --league kor_k_league_1 --team "Ulsan HD"
```

- `backend/features/stats.py` (화면용): 순위표(전체/홈/원정), 최근 폼, H2H, 오버/언더 2.5·BTTS·무실점 비율,
  전·후반 득점, 코너·카드·슈팅·xG 평균, 득점−xG, 휴식일, 최근 N일 경기 수
- `backend/features/match_features.py` (모델용): 경기마다 홈·원정 팀의 폼(5·10경기), 평균 득실, 홈/원정 폼, xG·슈팅,
  오버2.5·BTTS 비율, 휴식일, 14·30일 경기 수, H2H
- **미래 정보 누출 방지**: 모든 계산은 "경기 시작 시각보다 이전에 끝난 경기"만 쓴다. 같은 시각에 시작한 경기끼리도 서로 보지 않는다.
  테스트로 확인: ① 기준 시각 이후 결과를 무작위로 바꿔도 그 이전 경기 피처가 그대로인지 ② 이후 경기를 지워도 같은지
  ③ 빠른 누적 계산 결과가 경기마다 다시 걸러서 계산한 값과 같은지
- 데이터 한계
  - 골 시간 정보가 없어 **15분 단위 득점·선제골 시 승률은 계산하지 않음** (전·후반 득점으로 대체). 골 시간 데이터가 생기면 추가.
  - 휴식일·경기 수는 DB에 있는 대회만 센다. UEFA 대회·국내 컵 경기는 수집하지 않으므로 그런 팀은 실제보다 여유 있게 나온다.

## 2단계: 데이터 수집기

```bash
cd football
python -m backend.jobs.collect backfill --league eng_premier_league --seasons 5   # 리그 하나
python -m backend.jobs.collect backfill --all --seasons 5                         # 활성 대회 전체
python -m backend.jobs.collect daily                                              # 매일: 진행 중 시즌 + 다가오는 일정
```

- 어댑터: `backend/collectors/football_data.py`(유럽 10개 리그·J1), `backend/collectors/thesportsdb.py`(K리그1·ACL).
  새 소스는 `RawMatch`를 만들어 내는 어댑터만 추가하면 된다 (DB 저장은 `store.py` 공통).
- 원본은 `data/raw/`에 캐시. 종료된 시즌은 다시 받지 않고, 진행 중 시즌·일정은 12시간(일정 6시간)마다 새로 받는다.
- 모든 다운로드는 `data/http_calls.log`에 기록. 429(호출 제한) 응답이면 서버가 알려준 시간만큼 쉬고 최대 3번 다시 시도.
- TheSportsDB 무료 키는 30초에 약 12회를 넘으면 2분 차단 → 요청 간격 6초. K리그 한 시즌 약 40회 ≈ 4분.
- 시간대: Football-Data.co.uk는 **영국 현지 시간**(실제 데이터로 확인: 여름 영국 15:00 경기가 15:00으로 기록), TheSportsDB `strTimestamp`는 UTC.
- 연장전(AET)·승부차기 경기는 `result_90 = D`(90분 무승부), 스코어는 소스가 준 최종 스코어, `decided_by`로 구분.
- 같은 팀이 두 소스에 나오면(예: J1 팀이 ACL에도) 이름이 정확히 같을 때 같은 팀으로 연결하고 로그에 "팀 연결 확인 필요"로 남긴다.
  이름이 다르면 다른 팀으로 생긴다 → 별칭 정리 필요(로그·`teams` 표 확인).
- 아직 없는 것: 부상·선수 기록(무료 소스에 없음), ACL 토너먼트 라운드(TheSportsDB 라운드 번호 체계 확인 필요).

## 1단계: 프로젝트 뼈대 + DB

```bash
cd football
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m backend.db.init_db      # data/football.db (SQLite) 생성 + leagues.yaml 대회 동기화
python -m pytest -q backend/tests
```

- 테이블: leagues, seasons, teams, team_aliases, players, external_ids, matches, match_team_stats, match_odds, player_match_stats, injuries
- 배포 때는 `DATABASE_URL` 환경변수로 PostgreSQL 지정 (9단계)
- 시간은 UTC로만 저장된다(시간대 없는 값은 거부). 연장·승부차기 경기도 스코어는 90분 기준, `decided_by`에 결정 방식 기록.

## 0단계: 데이터 조사 (API-Football)

### 진행 상태
- [x] 대상 대회 목록: `config/leagues.yaml` (활성 13개 + 후보 4개)
- [x] 요금제·호출 한도 정리 (아래 표 — 웹 검색 기준)
- [x] 조사 스크립트 작성: 키만 있으면 실제 응답을 받아 아래 "조사 결과" 표를 자동으로 채운다
- [x] 실제 응답 확인 (2026-11-25, 무료 키로 약 60회 호출)
- [ ] 마지막 확인 호출 중 API가 "계정 정지(suspended)" 응답을 줌 — 대시보드에서 원인 확인 필요

### 핵심 결론 (실제 응답 기준)
1. **13개 대회 모두 지원됨.** 경기 통계는 대부분 2014~2016 시즌부터 있고, K리그1은 2020 시즌부터로 표시됨.
2. **무료 요금제는 2022~2024 시즌만 조회 가능.** 현재 시즌(2025-26 / 2026)을 요청하면
   `"Free plans do not have access to this season, try from 2022 to 2024."` 응답.
   → 무료로는 **다가오는 경기 일정·최근 결과를 받을 수 없어 예측 서비스를 운영할 수 없다.** 과거 데이터로 모델 개발·검증만 가능.
3. **무료 요금제는 여러 경기 묶음 조회(`fixtures?ids=`) 불가** → 과거 경기 통계는 경기마다 1회씩 호출해야 함.
4. **xG(`expected_goals`)**: 2024 시즌 정규 라운드 샘플에서 4대 리그·챔피언십·에레디비시·포르투갈·벨기에·튀르키예·J1리그는 값이 있었고,
   스코틀랜드·ACL은 항목은 있으나 값이 없음(X), **K리그1은 해당 경기 통계 자체가 비어 있음(?)**. 경기 1개씩만 본 결과라 수집 단계에서 다시 확인한다.
5. 부상 정보는 포르투갈·벨기에·스코틀랜드·K리그1·J1리그·ACL에서 제공되지 않음(최근 시즌 커버리지 플래그 기준).

### 요금제별 호출 한도

| 요금제 | 하루 호출 | 월 요금 | 비고 |
|---|---|---|---|
| Free | 100회 | 무료 | 카드 등록 불필요 |
| Pro | 7,500회 | $19 | |
| Ultra | 75,000회 | $29 | |
| Mega | 150,000회 | $39 | |

**선택: Free (하루 100회)** — 설정은 `config/settings.yaml`. 유료로 바꿀 때는 `plan`·`daily_limit`만 고치면 된다.

> 2026-11-25 웹 검색(공식 가격 페이지 검색 결과, RapidAPI 가격 페이지) 기준입니다. 공식 사이트(api-football.com)는
> 자동 접속을 막아 직접 열어보지 못했으므로, 가입 전 [가격 페이지](https://www.api-football.com/pricing)에서 다시 확인하세요.
> 분당 호출 제한도 따로 있습니다. 무료 요금제에서 과거 시즌 조회가 제한되는지는 조사 스크립트의 `/status`·실제 응답으로 확인합니다.

### 무료 요금제 운영 계획

| 작업 | 예상 호출 | 하루 100회로 |
|---|---|---|
| 0단계 조사 (1회) | 약 29회 | 하루에 끝남 |
| 매일 갱신 (일정·결과·부상 + 끝난 경기 통계) | 하루 약 30~60회 | 가능 |
| 과거 3시즌 일괄 수집 (경기 약 13,000개) | 경기마다 1회면 약 13,000회 / 20개 묶음 조회가 되면 약 650회 | 약 150일 / **약 7~8일** |

- 20개 묶음 조회(`fixtures?ids=`)가 통계까지 주는지는 0단계 조사에서 실제로 확인한다. 안 되면 수집할 시즌 수·대회를 줄인다.
- 과거 데이터 수집은 매일 갱신 후 남는 호출로 우선순위(`leagues.yaml`의 `priority`) 순서대로 이어받는다.
- 클라이언트는 응답 헤더의 남은 호출 수와 `data/api_calls.log`의 오늘(UTC) 호출 수를 둘 다 보고, 한도 - 여유분(5회)에서 멈춘다.

### 조사 스크립트 실행

```bash
cd football
pip install -r requirements.txt
cp .env.example .env    # API_FOOTBALL_KEY= 뒤에 키 입력
python -m backend.scripts.survey_api_football
```

- 호출 수: 약 29회(상태 1 + 전체 대회 목록 1 + 대회당 경기 목록 1·경기 통계 샘플 1 + 묶음 조회 확인 1). 무료 요금제로 충분합니다.
- 응답 원본은 `data/raw/`에 저장되고, 다시 실행하면 캐시를 써서 호출하지 않습니다. 호출 기록은 `data/api_calls.log`.
- 리그 이름으로 찾지 못한 대회는 추측하지 않고 "찾지 못함 + 같은 국가 후보 이름"으로 표에 남깁니다.
  이 경우 `config/leagues.yaml`의 `names`를 고친 뒤 다시 실행하세요.

### 테스트

```bash
cd football
python -m pytest -q backend/tests
```

## API-Football 조사 결과

<!-- SURVEY:BEGIN -->

_자동 생성: 2026-11-25 — `python -m backend.scripts.survey_api_football`_

- 현재 키의 요금제: **Free**, 하루 한도 100회, 오늘 사용 21회

### 대회별 지원 여부·시즌 수

| 대회 | API ID | API 대회명 | 시즌 수 | 범위 | 경기통계 있는 시즌 | 이벤트 | 라인업 | 선수기록 | 부상 | 배당 |
|---|---|---|---|---|---|---|---|---|---|---|
| 잉글랜드 프리미어리그 | 39 | Premier League | 17 | 2010~2026 | 2014~2026 (13) | O | O | O | O | O |
| 스페인 라리가 | 140 | La Liga | 17 | 2010~2026 | 2014~2026 (13) | O | O | O | O | O |
| 독일 분데스리가 | 78 | Bundesliga | 17 | 2010~2026 | 2015~2026 (12) | O | O | O | O | O |
| 이탈리아 세리에 A | 135 | Serie A | 17 | 2010~2026 | 2015~2026 (12) | O | O | O | O | O |
| 잉글랜드 챔피언십 | 40 | Championship | 16 | 2011~2026 | 2014~2026 (13) | O | O | O | O | O |
| 네덜란드 에레디비시 | 88 | Eredivisie | 17 | 2010~2026 | 2015~2026 (12) | O | O | O | O | O |
| 포르투갈 프리메이라리가 | 94 | Primeira Liga | 17 | 2010~2026 | 2015~2026 (12) | O | O | O | X | O |
| 벨기에 프로리그 | 144 | Jupiler Pro League | 17 | 2010~2026 | 2015~2026 (12) | O | O | O | X | O |
| 튀르키예 쉬페르리그 | 203 | Süper Lig | 16 | 2011~2026 | 2015~2026 (12) | O | O | O | O | O |
| 스코틀랜드 프리미어십 | 179 | Premiership | 17 | 2010~2026 | 2015~2026 (12) | O | O | O | X | O |
| K리그1 | 292 | K League 1 | 11 | 2016~2026 | 2020~2026 (7) | O | O | O | X | O |
| J1리그 | 98 | J1 League | 16 | 2012~2027 | 2015~2027 (13) | O | O | O | X | O |
| AFC 챔피언스리그 엘리트 | 17 | AFC Champions League Elite | 11 | 2016~2026 | 2016~2026 (11) | O | O | O | X | O |

> 이벤트~배당 열은 가장 최근에 시작한 시즌의 커버리지 플래그(`/leagues` 응답)입니다.

### 실제 경기 통계 응답 확인 (xG 포함 여부)

| 대회 | 시즌 | 경기 수 | 샘플 경기 (UTC) | xG | 받은 통계 항목 |
|---|---|---|---|---|---|
| 잉글랜드 프리미어리그 | 2024 | 380 | Bournemouth 1-0 Everton (2025-01-04) | O (1.84) | Shots on Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox, Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %, expected_goals, goals_prevented |
| 스페인 라리가 | 2024 | 380 | Espanyol 2-1 Valladolid (2025-01-17) | O (1.01) | Shots on Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox, Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %, expected_goals, goals_prevented |
| 독일 분데스리가 | 2024 | 308 | Eintracht Frankfurt 2-0 Borussia Dortmund (2025-01-17) | O (1.70) | Shots on Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox, Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %, expected_goals, goals_prevented |
| 이탈리아 세리에 A | 2024 | 380 | Genoa 1-0 Parma (2025-01-12) | O (1.19) | Shots on Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox, Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %, expected_goals, goals_prevented |
| 잉글랜드 챔피언십 | 2024 | 557 | Bristol City 3-0 Portsmouth (2024-12-29) | O (3.06) | Shots on Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox, Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %, expected_goals, goals_prevented |
| 네덜란드 에레디비시 | 2024 | 321 | Heracles 1-1 Sparta Rotterdam (2025-01-11) | O (1.19) | Shots on Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox, Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %, expected_goals, goals_prevented |
| 포르투갈 프리메이라리가 | 2024 | 308 | Benfica 4-0 Famalicao (2025-01-17) | O (4.11) | Shots on Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox, Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %, expected_goals, goals_prevented |
| 벨기에 프로리그 | 2024 | 315 | Kortrijk 3-1 KV Mechelen (2024-11-29) | O (1.67) | Shots on Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox, Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %, expected_goals, goals_prevented |
| 튀르키예 쉬페르리그 | 2024 | 342 | Hatayspor 1-1 Galatasaray (2025-01-17) | O (0.82) | Shots on Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox, Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %, expected_goals, goals_prevented |
| 스코틀랜드 프리미어십 | 2024 | 234 | Aberdeen 1-2 Ross County (2025-01-02) | X | Shots on Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox, Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %, expected_goals, goals_prevented |
| K리그1 | 2024 | 232 | Jeonbuk Motors 2-2 Incheon United (2024-06-16) | ? | 없음 |
| J1리그 | 2024 | 380 | Sanfrecce Hiroshima 1-1 Albirex Niigata (2024-06-26) | O (2.26) | Shots on Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox, Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %, expected_goals, goals_prevented |
| AFC 챔피언스리그 엘리트 | 2024 | 122 | Al Shorta 1-3 Al-Wasl FC (2024-11-26) | X | Shots on Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox, Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %, expected_goals, goals_prevented |

### 여러 경기 묶음 조회 (`fixtures?ids=`)

- 사용 불가 — API 응답: `fixtures 오류: {'plan': 'Free plans do not have access to the Ids parameter.'}` → 과거 경기 통계는 경기마다 1회씩 호출해야 함

### 매일 갱신 예상 호출 수

- 활성 대회 기준 하루 약 **41~85회** (경기 통계만 받으면 하한, 선수 기록·이벤트·라인업까지 받으면 상한)
- 과거 시즌 일괄 수집은 경기 1개당 1~4회가 들어가므로 무료 요금제로는 여러 날에 나눠야 한다.

<!-- SURVEY:END -->

## 대체 무료 데이터 소스 조사 (2026-11-25)

UOS-FootballDataAnalytics-Tutorial(서울시립대 수업 자료)에서 쓰는 공개 데이터 소스를 직접 확인했다.
해당 저장소는 라이선스 파일이 없어 코드는 가져오지 않고, 같은 공개 소스를 우리 수집기에서 직접 쓴다.

### Football-Data.co.uk — 키 없음, 무료 CSV

| 대회 | 파일 코드 | 2026/27 현재 시즌 | 경기 통계(슈팅·코너·카드) | xG | 과거 시즌 |
|---|---|---|---|---|---|
| 프리미어리그 | E0 | O (110경기, 11/23까지) | O | O (이번 시즌부터) | 1993~ |
| 챔피언십 | E1 | O (192경기) | O | O | O |
| 라리가 | SP1 | O (129경기) | O | O | O |
| 분데스리가 | D1 | O (90경기) | O | O | O |
| 세리에 A | I1 | O (120경기) | O | O | O |
| 에레디비시 | N1 | O (117경기) | O | O | O |
| 프리메이라리가 | P1 | O (98경기) | O | O | O |
| 벨기에 프로리그 | B1 | O (108경기) | O | O | O |
| 쉬페르리그 | T1 | O (108경기) | O | O | O |
| 스코틀랜드 프리미어십 | SC0 | O (81경기) | O | O | O |
| J1리그 | new/JPN.csv | O (150경기) | **X (결과·배당만)** | X | 2012~ |
| K리그1 | — | **없음** | | | |
| AFC 챔피언스리그 | — | **없음** | | | |

- URL: `https://football-data.co.uk/mmz4281/{시즌코드}/{리그코드}.csv` (예: 2627/E0), 다가오는 경기: `fixtures.csv`
- xG 열(`HxG`, `AxG`)은 2026/27 시즌부터 생김. 2025/26 이전 시즌 파일에는 없음(E0 2023~2025 확인).
- `fixtures.csv`에는 그 주 일부 리그 일정만 있어서, 전체 일정 소스로는 부족할 수 있음 — 수집 단계에서 확인.
- 배당 열이 들어 있지만 사이트에는 표시하지 않는다(베팅 연계 금지). 모델 평가의 "배당 내재 확률" 기준선으로만 쓴다.

### Understat
- 2026-11-25 접속 시 "We will come back soon" 화면만 나옴 → 지금은 사용 불가. 과거 시즌 xG(4대 리그) 소스 후보로 남겨둔다.

### TheSportsDB — K리그1·ACL 일정·결과 (무료 테스트 키)

| 대회 | TheSportsDB ID | 확인 결과 |
|---|---|---|
| K리그1 | 4689 | 라운드별 조회(`eventsround.php?id=4689&r=1&s=2026`)로 라운드당 6경기 전부 받음. 2020 시즌 이전도 조회됨 |
| AFC 챔피언스리그 엘리트 | 4719 | 시즌 표기 `2026-2027`. 예선(연장 AET 표시)·리그 스테이지 결과 받음 |

- 주는 것: 일정, 킥오프 시간, 스코어, 경기 상태(FT/AET/NS), 라운드, 경기장. **슈팅 등 경기 통계·xG·선수 기록은 없음.**
- 무료 키(`123`)는 한 번에 받는 개수가 제한됨(시즌 전체 조회는 15경기만, 다음 경기 조회는 1경기만) → 라운드별로 나눠 받는다.
- 데이터는 사용자 참여형으로 만들어져 오류·지연이 있을 수 있음(검색 결과에서 상태값이 늦게 반영된 사례 확인). 수집 후 점검 로직을 둔다.
- 무료 키는 테스트·소규모 개인 프로젝트용. 사이트를 공개 운영할 때는 유료 키(Patreon) 조건을 다시 확인한다.

### 데이터 소스 결론 (현재 계획)

| 대회 | 결과·일정 | 경기 통계 | xG | 선수·부상 |
|---|---|---|---|---|
| 유럽 10개 리그 | Football-Data.co.uk | Football-Data.co.uk | Football-Data.co.uk (2026/27~) | 없음 (API-Football 복구 시) |
| J1리그 | Football-Data.co.uk | 없음 | 없음 | 없음 |
| K리그1 | TheSportsDB | 없음 | 없음 | 없음 |
| AFC 챔피언스리그 | TheSportsDB | 없음 | 없음 | 없음 |

→ 아시아 대회는 **골 기반 모델(Elo, Dixon-Coles)** 로만 예측하고, 통계·xG 화면은 숨긴다.
