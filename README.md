# 📚 Paper Digest — arXiv 논문 자동 요약 → 노션

매일 arXiv에서 관심 분야(기본값: **VLA safety**) 신규 논문을 모아 Claude로 **본문 전체를 읽고** 한국어 요약을 만들고, 노션 데이터베이스와 "오늘의 논문 다이제스트" 페이지로 정리합니다.

요약은 기본적으로 **Claude Code CLI + Claude 구독(Pro/Max)** 으로 돌아가서 별도 API 키나 API 요금이 들지 않습니다. 원하면 Anthropic API 키 방식으로 바꿀 수 있습니다.

```
arXiv API ─▶ 주제 필터 ─▶ 노션 중복 제거 ─▶ Semantic Scholar 보강 ─▶ arXiv HTML 전문 ─▶ Claude 요약(JSON) ─▶ 노션 페이지 + 다이제스트
```

## 결과물

**논문 데이터베이스** (논문 1편 = 페이지 1개)

| 속성 | 타입 | 설명 |
|---|---|---|
| 제목 | 제목 | 논문 제목 |
| 한 줄 요약 | 텍스트 | 표 보기에서 바로 볼 수 있게 |
| 관련도 | 선택 | `5 · 매우 높음`(빨강) → `1 · 무관`(회색) 색상 구분 |
| 저자 | 텍스트 | |
| 발행일 | 날짜 | arXiv v1 제출일 |
| 카테고리 | 다중 선택 | cs.CL, cs.AI, cs.RO … |
| 키워드 | 다중 선택 | Claude가 뽑은 태그 |
| arXiv / PDF | URL | |
| 인용수 | 숫자 | Semantic Scholar |
| 저자 최대 인용수 | 숫자 | 공저자 중 최고 누적 인용수 |

**페이지 본문**: 💡 한 줄 요약 callout → 메타 정보(날짜·카테고리·인용·h-index·링크) → 관련도와 그 이유 → `문제 정의` / `핵심 기여` / `방법론` / `주요 결과`(원문 수치 포함) / `한계점` (heading 2 + 불릿) → 접힌 토글 안의 원문 초록. 맨 아래에 전문 기반 요약인지 초록 기반 요약인지 표시됩니다(arXiv HTML 버전이 없는 논문은 초록으로 요약). 페이지 아이콘은 대표 카테고리에 따라 자동으로 붙습니다 (💬 cs.CL, 🤖 cs.AI, 🦾 cs.RO … `config.yaml`에서 변경 가능).

**다이제스트 페이지**: 매일 `오늘의 논문 다이제스트 · YYYY-MM-DD` 페이지가 생기고, 그날 논문이 관련도 높은 순으로 (페이지 링크, 한 줄 요약, arXiv/PDF 링크와 함께) 정리됩니다.

---

## 1. 키 발급

### 1-1. Claude 인증 (둘 중 하나)

**A. Claude 구독 사용 — 기본값, API 키 불필요**
- **로컬 실행**: Claude Code에 구독 계정으로 로그인돼 있으면 끝입니다. `claude` 명령이 PATH에 없어도 VS Code 확장에 들어 있는 CLI를 자동으로 찾습니다. 직접 설치하려면 `npm install -g @anthropic-ai/claude-code` 후 `claude`를 실행해 로그인하세요.
- **GitHub Actions**: 터미널에서 `claude setup-token`을 실행하면 브라우저 인증 후 1년짜리 토큰(`sk-ant-oat01-...`)이 출력됩니다. 이 토큰을 `CLAUDE_CODE_OAUTH_TOKEN` 시크릿으로 등록하세요.
- 사용량은 구독 한도에서 차감됩니다. 본문 전체 요약은 1편당 입력 약 2만 토큰이라 하루 15편이면 Pro 플랜에서는 한도에 걸릴 수 있습니다. 그 경우 `max_papers_per_day`를 줄이거나 `summary_source: abstract`로 바꾸세요.

**B. Anthropic API 키 사용**
1. <https://console.anthropic.com> → **Settings → API Keys → Create Key**
2. `.env`의 `ANTHROPIC_API_KEY`에 입력하고 `config.yaml`에서 `summarizer: api`로 변경
3. **Billing**에서 크레딧 충전 필요 (`claude-sonnet-5`로 전문 요약 시 1편당 약 $0.05~0.1)

### 1-2. 노션 통합(Integration) 만들기
1. <https://www.notion.so/profile/integrations> 접속 → **새 통합 만들기**
2. 이름 입력(예: `Paper Digest`), 워크스페이스 선택, 유형은 **내부(Internal)**
3. 생성 후 **구성(Configuration)** 탭에서 **내부 통합 시크릿**(`ntn_...`) 복사 → `NOTION_TOKEN`
4. **기능(Capabilities)**에서 *콘텐츠 읽기 / 업데이트 / 삽입*이 모두 켜져 있는지 확인
5. **통합을 페이지에 연결** (가장 많이 빠뜨리는 단계):
   - 노션에서 논문을 모아둘 페이지(예: `📖 Research`)를 하나 만듭니다
   - 페이지 우측 상단 `•••` → **연결(Connections)** → 방금 만든 통합 선택
   - 이 페이지의 하위 페이지·데이터베이스는 모두 통합이 접근할 수 있게 됩니다
6. 페이지 ID 확인: 페이지 URL `https://www.notion.so/Research-1a2b3c4d5e6f...`의 마지막 32자리 16진수가 ID입니다 → `NOTION_PARENT_PAGE_ID`

### 1-3. (선택) Semantic Scholar API 키
키가 없어도 동작하지만, 공용 rate limit을 모든 사용자가 나눠 쓰기 때문에 429가 자주 납니다(코드가 자동으로 재시도합니다). 안정적으로 쓰려면 <https://www.semanticscholar.org/product/api#api-key-form> 에서 신청 → `S2_API_KEY`.

---

## 2. 설치

Python 3.10 이상 필요 (GitHub Actions는 3.11 사용).

```bash
cd paper-digest
python -m venv .venv && source .venv/bin/activate   # conda 사용 시: conda create -n paper-digest python=3.11
pip install -r requirements.txt
cp .env.example .env    # 그리고 .env에 키 입력
```

`.env`:

```ini
ANTHROPIC_API_KEY=                    # summarizer: api 일 때만
NOTION_TOKEN=ntn_...
NOTION_PARENT_PAGE_ID=1a2b3c4d...     # 데이터베이스를 만들 부모 페이지
NOTION_DATABASE_ID=                   # 비워두면 아래 초기화 스크립트가 채워줌
NOTION_DIGEST_PARENT_PAGE_ID=         # (선택) 비우면 DB의 부모 페이지에 다이제스트 생성
S2_API_KEY=                           # (선택)
```

## 3. 노션 데이터베이스 초기화

```bash
python -m paper_digest.init_db
```

- `NOTION_DATABASE_ID`가 비어 있으면 `NOTION_PARENT_PAGE_ID` 아래에 위 속성을 가진 데이터베이스를 만들고 **ID를 `.env`에 자동으로 기록**합니다.
- 이미 ID가 있으면 새로 만들지 않고, 빠진 속성만 추가합니다.
- 기존 DB를 쓰지 않고 새로 만들고 싶다면 `--force`를 붙이세요.

## 4. 실행

```bash
# 노션에 쓰지 않고 요약 결과만 터미널에 출력 (프롬프트·필터 튜닝용)
python -m paper_digest.main --dry-run --limit 1

# 실제 실행
python -m paper_digest.main

# 옵션
python -m paper_digest.main --lookback-hours 168 --limit 5
```

로그는 터미널과 `logs/run-YYYYMMDD.log`에 함께 남습니다.

## 5. GitHub Actions 자동 실행

`.github/workflows/daily-digest.yml`이 **매일 한국 시간 오전 8시**(`cron: "0 23 * * *"`, 전날 UTC 23시)에 실행됩니다.

1. 이 폴더를 GitHub 저장소로 push (`.env`는 `.gitignore`에 포함되어 올라가지 않습니다)
2. 저장소 **Settings → Secrets and variables → Actions → New repository secret**에 등록:

   | Secret | 필수 |
   |---|---|
   | `CLAUDE_CODE_OAUTH_TOKEN` | ✅ (`claude setup-token`으로 발급, 1-1 A 참고) |
   | `NOTION_TOKEN` | ✅ |
   | `NOTION_DATABASE_ID` | ✅ (init_db 실행 후 `.env`에 기록된 값) |
   | `NOTION_DIGEST_PARENT_PAGE_ID` | 선택 |
   | `S2_API_KEY` | 선택 |
   | `ANTHROPIC_API_KEY` | `summarizer: api`일 때만 |

3. **수동 실행**: Actions 탭 → *Daily Paper Digest* → **Run workflow** (lookback 시간과 최대 편수를 입력할 수 있음)
4. 실행 로그는 각 run의 **Artifacts**에서 `logs-<run_id>`로 14일간 받을 수 있습니다.

> GitHub의 schedule 트리거는 부하에 따라 수 분~수십 분 늦게 시작될 수 있고, 저장소에 60일간 활동이 없으면 자동으로 비활성화됩니다.

## 6. 커스터마이즈 (`config.yaml`)

| 키 | 설명 |
|---|---|
| `categories` | 수집할 arXiv 카테고리. VLA 논문은 cs.RO·cs.CV에 주로 올라오므로 추가를 고려해 보세요. |
| `lookback_hours` | 수집 범위 (아래 참고) |
| `max_papers_per_day` | 하루 최대 처리 편수 (기본 15). 넘치는 논문은 다음 실행에서 처리됩니다. |
| `claude_model` | 요약 모델 (기본 `claude-sonnet-5`) |
| `summarizer` | `claude_code`(구독, 기본) 또는 `api`(API 키) |
| `summary_source` | `fulltext`(arXiv HTML 본문 전체, 기본) 또는 `abstract`(초록만 — 빠르고 사용량 적음) |
| `filter_groups` | 주제 필터. **모든 그룹**에서 정규식이 최소 1개씩 매칭돼야 통과합니다(기본: `vla` 그룹 AND `safety` 그룹). |
| `interest_keywords` | Claude가 관련도(1~5)를 매길 때 기준으로 삼는 관심 키워드 |
| `category_icons` | 카테고리별 페이지 아이콘 |

### 수집 범위(`lookback_hours`)에 대해
arXiv는 논문을 제출한 뒤 **발표(announce)**할 때까지 하루~사흘이 걸립니다(평일 미국 동부 20시 발표, 주말 제출분은 월요일 밤에 한꺼번에). 그래서 이 프로젝트는 **"지금"이 아니라 API에 올라온 가장 최신 논문의 제출 시각을 기준**으로 `lookback_hours`만큼 거슬러 올라가 수집합니다. 기본값 72시간이면 주말 발표분까지 빠짐없이 들어오고, 겹치는 구간은 노션 중복 체크로 걸러집니다.

## 7. 안정성

- **논문별 격리**: 요약이나 페이지 생성 중 한 편이 실패해도 로그(stack trace 포함)만 남기고 다음 논문으로 넘어갑니다. 실패 건수는 다이제스트 상단에도 표시됩니다.
- **재시도**: arXiv / Semantic Scholar / 노션은 429·5xx·네트워크 오류가 나면 지수 백오프로 최대 5~6회 재시도하고, `Retry-After` 헤더가 있으면 그 값을 따릅니다. Claude 요약은 실패 시 30초 → 60초 간격으로 최대 3번 시도합니다(구독 사용량 한도 대비). API 모드는 SDK 내장 재시도(최대 5회)를 씁니다.
- **소요 시간**: 전문 요약은 1편당 약 2분 걸려서 15편이면 30~40분 정도 걸립니다(Actions 제한 시간은 90분).
- **arXiv 이용 수칙**: 페이지 요청 사이에 3초씩 대기합니다.
- **종료 코드**: 처리할 논문이 있었는데 전부 실패한 경우에만 exit 1로 끝나서 Actions 실패 알림이 옵니다.

## 프로젝트 구조

```
paper-digest/
├── config.yaml                 # 카테고리·필터·관심 키워드 등 동작 설정
├── .env.example                # 비밀값 템플릿
├── paper_digest/
│   ├── main.py                 # 파이프라인 진입점
│   ├── init_db.py              # 노션 DB 초기화
│   ├── arxiv_client.py         # arXiv 수집
│   ├── filtering.py            # 정규식 주제 필터
│   ├── semantic_scholar.py     # 인용수 보강
│   ├── fulltext.py             # arXiv HTML 본문 추출
│   ├── summarizer.py           # Claude 구조화 요약 (Claude Code CLI / API)
│   ├── notion_api.py           # 노션 API + 블록 레이아웃
│   ├── http_utils.py           # 재시도 헬퍼
│   ├── models.py               # 데이터 구조 / 요약 스키마
│   └── config.py
└── .github/workflows/daily-digest.yml
```

## 문제 해결

| 증상 | 해결 |
|---|---|
| `Could not find database/page ... Make sure the relevant pages and databases are shared with your integration` | 1-2의 5번 단계(페이지에 통합 연결)를 하지 않은 경우입니다. |
| `환경변수 누락` | `.env` 또는 GitHub Secrets 이름 오타를 확인하세요. |
| 매일 0편 | 필터가 너무 좁은 경우입니다. `--dry-run --lookback-hours 168`로 확인해 보고, `categories`에 `cs.RO`를 추가하거나 `filter_groups`를 넓혀 보세요. |
| `Claude Code CLI를 찾을 수 없습니다` | `npm i -g @anthropic-ai/claude-code`로 설치하거나 `.env`에 `CLAUDE_CLI=/경로/claude` 지정 |
| 요약이 `usage limit`으로 실패 | 구독 사용량 한도입니다. `max_papers_per_day`를 줄이거나 `summary_source: abstract`로 바꾸세요. |
| S2 인용수가 비어 있음 | 막 나온 논문은 Semantic Scholar에 아직 색인되지 않았을 수 있습니다(정상). |
