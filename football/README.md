# 축구 분석·예측 웹사이트

유럽 4대 리그·유럽 중소 리그·K리그1·J1리그·AFC 챔피언스리그를 대상으로 하는 축구 통계·예측 사이트.
기획은 [CLAUDE.md](CLAUDE.md), 단계별 진행은 [단계별_프롬프트.md](단계별_프롬프트.md) 참고.

## 0단계: 데이터 조사 (API-Football)

### 진행 상태
- [x] 대상 대회 목록: `config/leagues.yaml` (활성 13개 + 후보 4개)
- [x] 요금제·호출 한도 정리 (아래 표 — 웹 검색 기준)
- [x] 조사 스크립트 작성: 키만 있으면 실제 응답을 받아 아래 "조사 결과" 표를 자동으로 채운다
- [ ] **실제 응답 확인 — API 키가 필요해서 아직 못 함**

### 요금제별 호출 한도

| 요금제 | 하루 호출 | 월 요금 | 비고 |
|---|---|---|---|
| Free | 100회 | 무료 | 카드 등록 불필요 |
| Pro | 7,500회 | $19 | |
| Ultra | 75,000회 | $29 | |
| Mega | 150,000회 | $39 | |

> 2026-11-25 웹 검색(공식 가격 페이지 검색 결과, RapidAPI 가격 페이지) 기준입니다. 공식 사이트(api-football.com)는
> 자동 접속을 막아 직접 열어보지 못했으므로, 가입 전 [가격 페이지](https://www.api-football.com/pricing)에서 다시 확인하세요.
> 분당 호출 제한도 따로 있습니다. 무료 요금제에서 과거 시즌 조회가 제한되는지는 조사 스크립트의 `/status`·실제 응답으로 확인합니다.

### 조사 스크립트 실행

```bash
cd football
pip install -r requirements.txt
cp .env.example .env    # API_FOOTBALL_KEY= 뒤에 키 입력
python -m backend.scripts.survey_api_football
```

- 호출 수: 약 28회(상태 1 + 전체 대회 목록 1 + 대회당 경기 목록 1·경기 통계 샘플 1). 무료 요금제로 충분합니다.
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
_아직 실행 전 — API 키를 넣고 조사 스크립트를 실행하면 이 자리에 표가 생깁니다._
<!-- SURVEY:END -->
