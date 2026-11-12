# 브리핑 웹페이지 구현 계획 (계획 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매일의 브리핑을 폰에서 읽을 수 있는 공개 페이지를 만들고, 좋아요·클릭·메모를 모아 계획 3의 학습 신호를 쌓기 시작한다.

**Architecture:** 한 번 빌드한 SPA가 런타임에 날짜별 JSON을 불러온다. 파이프라인은 `docs/data/*.json`만 떨어뜨리므로 **프론트엔드가 망가져도 브리핑 전송은 멈추지 않는다**(스펙 6.4의 결정적 이유). 상호작용은 브라우저에서 Supabase anon 키로 직접 기록한다.

**Tech Stack:** Vite + React + TypeScript + Tailwind CSS, Supabase JS 클라이언트, GitHub Pages (`docs/` 서빙)

---

## 시작하기 전에 — 이 계획의 전제

### 결정 사항 (2026-11-12)

| 항목 | 결정 | 근거 |
|---|---|---|
| 배포 | **리포를 공개로 전환 + GitHub Pages** | 스펙 7.2의 원안. 무료 플랜은 비공개 리포에서 Pages를 제공하지 않는다 |
| 다크 모드 | **라이트 모드만** | 쓰면서 필요하면 나중에 추가. 지금 CSS를 두 벌 만들지 않는다 |
| 톤 | **A 톤** (조용한 읽기 도구) | 목업 아트보드 7개에서 확정 |

### 계획 1에서 확인한 제약 — 이 계획이 반드시 지켜야 하는 것

**1. `render`는 `briefing.json`이 아니라 Supabase `articles`를 읽는다.**

세 가지 이유가 겹친다.

- **`article_id`가 필요하다.** 페이지가 `reactions`·`clicks`에 삽입할 때 FK로 쓴다.
  `SupabaseStore.save_articles`는 `None`을 돌려주므로 id가 파이프라인 안에 남지 않는다.
- **`articles` 테이블에 본문 컬럼이 아예 없다.** 본문은 `article_bodies`에 따로 있다.
  그래서 `articles`만 읽으면 **요구사항 D3(본문 미커밋)이 구조적으로 보장된다** —
  실수로 넣을 경로가 없다.
- `articles`가 페이지에 필요한 것을 모두 갖고 있다: `id`, `briefing_date`, `url`,
  `source`, `published_at`, `headline`, `bullets`, `why_it_matters`, `topic`, `score`, `reason`.

0건인 날 화면에 필요한 수치는 `runs`에서 읽는다 — `collected_count`,
`considered_count`, `max_score`, `source_counts`.

**2. anon 권한이 목업의 상호작용과 어긋난다.** 계획 1의 `supabase/schema.sql` 실측:

| 테이블 | anon 권한 | 목업이 가정한 것 | 차이 |
|---|---|---|---|
| `articles` | SELECT | 읽기 | 맞음 |
| `reactions` | **INSERT만** | 토글 (채운 하트 ↔ 빈 하트) | **읽기·삭제 불가** |
| `clicks` | **INSERT만** | 기록만 | 맞음 |
| `notes` | SELECT + INSERT | 제자리 수정, 태그 × 버튼 | **수정·삭제 불가** |

**권한을 늘리지 않고 해결한다.** anon에 DELETE를 주면 URL을 아는 누구나
좋아요를 지울 수 있고, 스펙 7.2는 "본문 차단과 색인 차단은 되돌리기 어려우므로
그쪽에 노력을 쓴다"고 정했다. 그 판단과 일관되게 간다.

- **좋아요**: DB는 **추가 전용**(이벤트). 눌렀는지 여부는 **`localStorage`**가
  기기별로 기억한다. 같은 글을 두 번 눌러도 이벤트가 두 개 쌓이는데, 스펙 7.2가
  "신호 오염이 생기면 Phase 2에서 바로 드러나 그때 대응"으로 이미 수용했다.
- **메모**: 추가 전용. 읽을 때 **그 글의 가장 최근 행**을 쓴다(`notes`에 SELECT가
  있다). 저장은 매번 새 행이고, 태그 삭제는 "삭제한 태그를 뺀 새 행"이다.
- `localStorage`는 사생활이 아니라 **편의**다. 지워져도 화면이 깨지지 않게
  `try/catch`로 감싸고, 없으면 "안 누른 상태"로 그린다.

**3. Vite의 `emptyOutDir`를 반드시 끈다.** 빌드 결과를 `docs/`에 넣는데
`docs/superpowers/`(설계·계획 문서)와 `docs/data/`(영구 보관 JSON)가 같이 있다.
기본값대로 두면 **빌드가 그 둘을 지운다.**

**4. `.nojekyll`이 필요하다.** GitHub Pages는 Jekyll로 처리하면서 `_`로 시작하는
파일을 무시한다. Vite 산출물에 그런 이름이 생길 수 있다.

### 목업에서 확정한 값 — 그대로 쓴다

**색 (A 톤).** `accent`는 **상호작용에만** 쓴다(요구사항 O14).

| 용도 | 값 |
|---|---|
| 배경 | `#FBFAF8` |
| 본문 글자 | `#1A1A18` |
| 보조 글자 (불릿) | `#3D3B37` |
| 흐린 글자 (메타·"왜") | `#6B6862` |
| 더 흐린 글자 (0건 날짜) | `#8A8780` |
| 구분선 | `#E5E1DA` / 목록 구분 `#ECE8E1` |
| 패널 배경 | `#F3F1EC` |
| 태그 배경 | `#E7E2D9` |
| 테두리 | `#DAD5CC` / "왜" 왼쪽 선 `#E0DBD2` |
| **accent (상호작용)** | `#9A5B3C` |
| 경고 | `#9A3412` |

**글꼴.** 본문은 `Noto Serif KR` (400, 600), 메타·UI는 `Inter` (400, 500).

> **한글에 이탤릭을 쓰지 않는다.** `Noto Serif KR`에는 이탤릭 자체가 없어서
> 브라우저가 기울임을 **합성**하고, 한글에서는 그게 어긋나 보인다. 목업에서
> "왜" 문단의 강조를 **왼쪽 2px 선**(`#E0DBD2`)으로 바꾼 이유다.

**카드 구조** (목업 `Main.dc.html`):

```
h2  헤드라인          19px / 600 / line-height 1.45 / letter-spacing -0.01em
ul  불릿 2~3개        14.5px / line-height 1.7 / #3D3B37 / gap 6px / padding-left 15px
p   왜 중요한가        13.5px / line-height 1.6 / #6B6862 / border-left 2px #E0DBD2 / padding-left 11px
div 메타               11.5px / Inter / #6B6862 — 출처 · 점수 · [좋아요 44×44]
```

카드 사이는 `#E5E1DA` 1px 선, 세로 간격 26px, 좌우 여백 22px.

**버튼은 44×44px.** 손가락 터치 목표 크기다. 목업이 `margin-right: -10px`로
시각적 정렬을 맞춘다.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `pipeline/render.py` | Supabase → `docs/data/YYYY-MM-DD.json`, `docs/data/index.json` |
| `tests/test_render.py` | 위의 테스트 |
| `web/package.json` | 프론트엔드 의존성 |
| `web/vite.config.ts` | `base`, `outDir: ../docs`, `emptyOutDir: false` |
| `web/tailwind.config.ts` | A 톤 색·글꼴 토큰 |
| `web/index.html` | `noindex` 메타, 글꼴 링크 |
| `web/src/main.tsx` | 엔트리 |
| `web/src/App.tsx` | 라우팅 (`/`, `/:date`) |
| `web/src/lib/types.ts` | JSON 스키마의 TypeScript 타입 |
| `web/src/lib/data.ts` | JSON 불러오기 |
| `web/src/lib/supabase.ts` | anon 클라이언트 + 상호작용 기록 |
| `web/src/lib/liked.ts` | `localStorage` 좋아요 상태 |
| `web/src/components/Card.tsx` | 글 한 건 |
| `web/src/components/Today.tsx` | 오늘 화면 (0건 포함) |
| `web/src/components/Archive.tsx` | 날짜 아카이브 |
| `web/src/components/Note.tsx` | 메모·태그 |
| `docs/robots.txt` | 색인 차단 |
| `docs/.nojekyll` | Jekyll 처리 끄기 |
| `docs/404.html` | SPA 라우팅 폴백 |

---

## 요구사항 커버리지

| 요구사항 | 내용 | 태스크 |
|---|---|---|
| O9 | 웹페이지: 오늘자 + 날짜별 아카이브 | Task 7 (오늘), Task 8 (아카이브) |
| O10 | 모바일 1열 / 태블릿 이상 2열 | Task 7 (`md:grid-cols-2`), Task 13 Step 4 (실제 확인) |
| O11 | SPA + JSON 런타임 로딩 (파이프라인과 프론트 분리) | Task 2 (`render`), Task 5 (`data.ts`), **Task 14 Step 1이 분리를 검증한다** |
| O12 | GitHub Pages SPA 라우팅 (`404.html` 폴백) | Task 9 |
| O13 | 좋아요·클릭·메모 저장 | Task 10 (좋아요·클릭), Task 11 (메모·태그) |
| O14 | accent는 상호작용에만 | Task 4 (토큰 주석) — 쓰는 곳은 `LikeButton`, 메모 저장 버튼, 메모 열기 버튼, 에러 화면의 링크뿐이다 |
| D3 | 본문은 리포지토리에 커밋되지 않는다 | Task 2 (`PAGE_FIELDS` 화이트리스트 + `test_본문과_판단근거는_담지_않는다`) |
| D4 | 검색 색인 차단 (`robots.txt` + `noindex`) | Task 4 (메타 태그), Task 12 (`robots.txt`) |

---

## 실행 순서 주의 — Task 6과 10의 의존

`Card.tsx`(Task 6)가 `LikeButton`(Task 10)을 임포트한다. **Task 6만 끝낸
상태에서는 `npm run build`가 실패한다.**

카드를 먼저 쓴 이유는 그게 `LikeButton`이 무엇을 받아야 하는지를 정하기
때문이다(`articleId`, `className`). 각 커밋이 빌드되기를 원하면 **Task 10의
Step 1~4를 Task 6보다 먼저** 하면 된다 — 그 둘 사이에 다른 의존은 없다.

나머지 태스크는 순서대로 하면 각 커밋이 빌드된다.

---

## Task 1: 리포지토리 공개 전환

Pages가 무료 플랜에서 비공개 리포를 지원하지 않으므로 **이것이 선행 조건**이다.
`docs/공개-전-점검.md`의 판단 항목을 먼저 정리한다.

**Files:**
- Modify: `docs/공개-전-점검.md`
- Modify: `config/sources.yaml` (문구만)

- [ ] **Step 1: 판단 항목 2번을 읽고 결정한다**

`docs/공개-전-점검.md`의 "2. 본인이 판단할 것"에 두 항목이 있다.

**(a) `config/interests.md` — 개인 프로필 49줄.** 그대로 둘지, 일반화할지 정한다.
그대로 두는 쪽을 권한다 — 이 파일이 선별 품질의 핵심이고, 예시가 빈약하면
리포를 받은 사람이 재현할 수 없다. 내용은 기술 관심사 서술이라 공개 이력서 수준이다.

**(b) 실명 매체·기업에 대한 판단 문구.** 아래 문장들은 전부 측정 근거가 붙어
있지만 **평가가 섞인 것만** 사실 서술로 바꾼다.

```bash
grep -n "중단으로 본다\|더 이상 IT 매체 피드가 아니다" config/sources.yaml
```

바꿀 것:

```yaml
# 전
  # 끔 — 최신 글이 2024-10-14 — 13개월 무발행. 느린 발행이 아니라 중단으로 본다.
# 후
  # 끔 — 최신 글이 2024-10-14 (13개월 전). 다시 올라오면 켠다.
```

```yaml
# 전
  # 끔 — 더 이상 IT 매체 피드가 아니다. 같은 도메인의 다른 섹션
# 후
  # 끔 — 같은 도메인의 다른 섹션(/rss/S1N4.xml)이 "파인데일리 - 예술"을
  #      돌려준다. 받아 본 4건도 일반 경제·금융이었다.
```

- [ ] **Step 2: 내용 검사를 다시 돌린다**

```bash
git ls-files -z | xargs -0 grep -nE \
  '/Users/|/private/tmp/claude-|[a-z0-9]{15,}\.supabase\.co|sb_secret_[A-Za-z0-9]|sk-ant-[A-Za-z0-9]|eyJ[A-Za-z0-9_-]{20,}'
```

Expected: `scripts/smoke_supabase.py`와 계획 문서의 `sb_secret_sentinel_...` 2건만
나온다. **그 밖에 하나라도 나오면 멈춘다.**

```bash
git log --all --format="%ae %ce" | sort -u
```

Expected: `242947563+predevho@users.noreply.github.com`만 나온다.

- [ ] **Step 3: 커밋**

```bash
git add config/sources.yaml docs/공개-전-점검.md
git commit -m "docs: 공개 전환 준비 — 소스 주석을 사실 서술로"
git push origin main
```

- [ ] **Step 4: 공개로 전환**

```bash
gh repo edit predevho/topic-briefing --visibility public --accept-visibility-change-consequences
gh repo view predevho/topic-briefing --json visibility -q .visibility
```

Expected: `PUBLIC`

- [ ] **Step 5: 점검 문서를 갱신하고 커밋**

`docs/공개-전-점검.md`의 머리말을 "이 리포지토리는 **공개**다. 아래는 공개 당시의
점검 기록이다."로 바꾸고, 2번 항목에 내린 결정을 적는다.

```bash
git add docs/공개-전-점검.md
git commit -m "docs: 공개 전환 완료 기록"
git push origin main
```

---

## Task 2: `render` — Supabase에서 날짜별 JSON을 떨어뜨린다

**Files:**
- Create: `pipeline/render.py`
- Create: `tests/test_render.py`
- Modify: `tests/fakes.py` (`FakeRemoteStore`에 조회 메서드 추가)

> **왜 `briefing.json`을 읽지 않는가** — 이 계획 맨 앞 "계획 1에서 확인한 제약"의
> 1번이다. `article_id`가 필요하고, `articles` 테이블에 본문 컬럼이 없어서
> 요구사항 D3이 구조적으로 보장된다.

- [ ] **Step 1: 저장소 프로토콜에 조회 메서드를 더하는 테스트**

`tests/test_render.py`:

```python
import json

import pytest

from pipeline.render import (
    DATA_DIR,
    build_day,
    build_index,
    write_day,
    write_index,
)

ARTICLES = [
    {
        "id": 7,
        "briefing_date": "2026-11-12",
        "url": "https://toss.tech/article/agent-platform-foundation",
        "source": "토스_기술블로그",
        "published_at": "2026-11-10T05:30:00+00:00",
        "headline": "망분리 환경 Agent Platform 설계",
        "bullets": ["하네스마다 격리했다.", "인증 프록시가 키를 주입한다."],
        "why_it_matters": "프로세스 수준 격리의 설계 기준이 된다.",
        "topic": "AI",
        "score": 100,
        "reason": "관심사 정중앙",
    },
    {
        "id": 8,
        "briefing_date": "2026-11-12",
        "url": "https://blog.cloudflare.com/choosing-quepaxa",
        "source": "Cloudflare_Blog",
        "published_at": "2026-11-11T01:00:00+00:00",
        "headline": "Cloudflare가 QuePaxa를 택한 이유",
        "bullets": ["리더 기반 합의는 WAN에서 멈춘다."],
        "why_it_matters": "가용성 한계와 대안을 이해하게 된다.",
        "topic": "backend",
        "score": 98,
        "reason": "원리 분석",
    },
]

RUN = {
    "window_start": "2026-11-07T16:20:25+00:00",
    "window_end": "2026-11-11T16:20:25+00:00",
    "collected_count": 240,
    "considered_count": 10,
    "max_score": 100,
    "published_count": 2,
    "source_counts": {"토스_기술블로그": 3, "조용한소스": 0},
}


# --- 하루치 JSON ---

def test_글을_점수_내림차순으로_담는다():
    day = build_day(date="2026-11-12", articles=ARTICLES, run=RUN)
    assert [a["score"] for a in day["articles"]] == [100, 98]


def test_페이지가_필요한_필드를_담는다():
    day = build_day(date="2026-11-12", articles=ARTICLES, run=RUN)
    first = day["articles"][0]

    for key in ("id", "headline", "bullets", "why_it_matters",
                "source", "url", "published_at", "topic", "score"):
        assert key in first, key


def test_article_id를_담는다():
    """페이지가 reactions·clicks에 삽입할 때 FK로 쓴다. 없으면 좋아요가 안 된다."""
    day = build_day(date="2026-11-12", articles=ARTICLES, run=RUN)
    assert day["articles"][0]["id"] == 7


def test_본문과_판단근거는_담지_않는다():
    """D3 — 본문은 리포지토리에 커밋되지 않는다. reason은 화면에 쓰지 않는다."""
    day = build_day(date="2026-11-12", articles=ARTICLES, run=RUN)
    첫째 = day["articles"][0]

    assert "body" not in 첫째
    assert "excerpt" not in 첫째
    assert "reason" not in 첫째


def test_0건인_날에_필요한_수치를_담는다():
    """화면이 "후보 10건 / 최고 100점 / 기준 60점"을 보여준다."""
    day = build_day(date="2026-11-12", articles=[], run=RUN)

    assert day["collected"] == 240
    assert day["considered"] == 10
    assert day["max_score"] == 100
    assert day["threshold"] == 60


def test_임계값은_summarize에서_가져온다():
    """두 곳에 하드코딩하면 어긋난다."""
    from pipeline.summarize import SCORE_THRESHOLD

    day = build_day(date="2026-11-12", articles=[], run=RUN)
    assert day["threshold"] == SCORE_THRESHOLD


def test_소스별_건수를_담는다():
    """0건인 날 화면이 "토스 0건 · 3일 연속"을 보여주는 재료다."""
    day = build_day(date="2026-11-12", articles=[], run=RUN)
    assert day["source_counts"]["조용한소스"] == 0


def test_날짜를_담는다():
    day = build_day(date="2026-11-12", articles=ARTICLES, run=RUN)
    assert day["date"] == "2026-11-12"


def test_실행_기록이_없으면_수치를_None으로_둔다():
    """글은 있는데 runs 조회가 비는 경우. 0으로 두면 "수집 0건"이라 거짓말한다."""
    day = build_day(date="2026-11-12", articles=ARTICLES, run=None)

    assert day["collected"] is None
    assert day["max_score"] is None
    assert day["source_counts"] == {}


# --- 아카이브 목록 ---

def test_아카이브를_최신순으로_담는다():
    index = build_index([
        {"briefing_date": "2026-11-10", "count": 5, "lead": "앞의 글"},
        {"briefing_date": "2026-11-12", "count": 2, "lead": "뒤의 글"},
    ])
    assert [d["date"] for d in index["dates"]] == ["2026-11-12", "2026-11-10"]


def test_아카이브에_건수와_대표_헤드라인을_담는다():
    """목록이 "11/10  MCP 스펙 2.0 외 4건  5건" 형태다."""
    index = build_index([
        {"briefing_date": "2026-11-12", "count": 2, "lead": "망분리 환경 Agent Platform 설계"},
    ])
    first = index["dates"][0]

    assert first["count"] == 2
    assert first["lead"] == "망분리 환경 Agent Platform 설계"


def test_0건인_날도_아카이브에_넣는다():
    """목업의 "11/06  기준을 넘긴 글 없음  0건" 줄이다. articles만 보면 빠진다."""
    index = build_index([
        {"briefing_date": "2026-11-06", "count": 0, "lead": None},
    ])
    assert index["dates"][0]["count"] == 0
    assert index["dates"][0]["lead"] is None


def test_아카이브_총계를_담는다():
    """목업 머리말이 "발행 시작 후 19일 · 총 71건"이다."""
    index = build_index([
        {"briefing_date": "2026-11-12", "count": 2, "lead": "a"},
        {"briefing_date": "2026-11-10", "count": 5, "lead": "b"},
    ])
    assert index["days"] == 2
    assert index["total"] == 7


def test_빈_아카이브도_만들어진다():
    index = build_index([])
    assert index == {"dates": [], "days": 0, "total": 0}


# --- 파일로 쓰기 ---

def test_하루치를_날짜_파일명으로_쓴다(tmp_path):
    path = write_day(build_day(date="2026-11-12", articles=ARTICLES, run=RUN),
                     root=tmp_path)

    assert path.name == "2026-11-12.json"
    assert json.loads(path.read_text(encoding="utf-8"))["date"] == "2026-11-12"


def test_한글이_그대로_저장된다(tmp_path):
    """ensure_ascii가 켜지면 \\uXXXX가 되어 눈으로 디버깅할 수 없다."""
    path = write_day(build_day(date="2026-11-12", articles=ARTICLES, run=RUN),
                     root=tmp_path)
    assert "망분리" in path.read_text(encoding="utf-8")


def test_아카이브를_index_json으로_쓴다(tmp_path):
    path = write_index(build_index([]), root=tmp_path)
    assert path.name == "index.json"


def test_기본_경로가_docs_data다():
    """GitHub Pages가 docs/를 서빙한다. 스펙 7.5의 영구 보관 위치다."""
    assert DATA_DIR.as_posix().endswith("docs/data")
```

- [ ] **Step 2: 실패를 확인**

Run: `.venv/bin/python -m pytest tests/test_render.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.render'`

- [ ] **Step 3: `RemoteStore`에 조회 메서드를 더한다**

`pipeline/lib/store.py`의 `RemoteStore` Protocol에 추가:

```python
    def articles_for(self, briefing_date: str) -> list[dict]:
        """그 날짜에 발행한 글. render가 쓴다 — 본문은 다른 테이블이라 안 온다."""
        ...

    def run_for(self, briefing_date: str) -> dict | None:
        """그 날짜의 전송 성공 실행 기록. 0건인 날 화면의 수치를 준다."""
        ...

    def archive_days(self) -> list[dict]:
        """전송한 모든 날짜와 건수·대표 헤드라인. 0건인 날도 포함한다."""
        ...
```

`SupabaseStore`에 구현:

```python
    def articles_for(self, briefing_date: str) -> list[dict]:
        return (
            self._db.table("articles")
            .select("id,briefing_date,url,source,published_at,headline,"
                    "bullets,why_it_matters,topic,score")
            .eq("briefing_date", briefing_date)
            .order("score", desc=True)
            .execute()
            .data
        )

    def run_for(self, briefing_date: str) -> dict | None:
        # 하루에 여러 번 보낼 수 있으므로(--force) 마지막 성공을 쓴다.
        rows = (
            self._db.table("runs")
            .select("window_start,window_end,collected_count,considered_count,"
                    "max_score,published_count,source_counts")
            .eq("status", "sent")
            .gte("sent_at", f"{briefing_date}T00:00:00+09:00")
            .lt("sent_at", f"{briefing_date}T23:59:59.999+09:00")
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None

    def archive_days(self) -> list[dict]:
        """전송한 날짜 목록. articles만 보면 0건인 날이 빠진다."""
        runs = (
            self._db.table("runs")
            .select("sent_at,published_count")
            .eq("status", "sent")
            .order("sent_at", desc=True)
            .execute()
            .data
        )
        arts = (
            self._db.table("articles")
            .select("briefing_date,headline,score")
            .order("score", desc=True)
            .execute()
            .data
        )

        # 날짜별 대표 헤드라인 = 그 날 최고 점수의 헤드라인.
        # score 내림차순으로 받았으므로 처음 만난 것이 최고다.
        lead: dict[str, str] = {}
        count: dict[str, int] = {}
        for a in arts:
            d = a["briefing_date"]
            lead.setdefault(d, a["headline"])
            count[d] = count.get(d, 0) + 1

        # sent_at(UTC)에서 KST 날짜를 만든다. briefing_date와 같은 기준이다.
        날짜들: list[str] = []
        for r in runs:
            d = datetime.fromisoformat(r["sent_at"]).astimezone(KST).date().isoformat()
            if d not in 날짜들:
                날짜들.append(d)

        return [
            {"briefing_date": d, "count": count.get(d, 0), "lead": lead.get(d)}
            for d in 날짜들
        ]
```

`store.py` 상단에 `from pipeline.lib.timeutil import KST`를 더한다
(`datetime`은 이미 임포트돼 있다).

`tests/fakes.py`의 `FakeRemoteStore`에 추가:

```python
    def articles_for(self, briefing_date: str) -> list[dict]:
        return [a for a in self.articles_rows
                if a["briefing_date"] == briefing_date]

    def run_for(self, briefing_date: str) -> dict | None:
        return self.run_row

    def archive_days(self) -> list[dict]:
        return list(self.archive_rows)
```

`FakeRemoteStore.__init__`에 세 줄 더한다:

```python
        self.articles_rows: list[dict] = []
        self.run_row: dict | None = None
        self.archive_rows: list[dict] = []
```

- [ ] **Step 4: `pipeline/render.py` 작성**

```python
"""05 렌더: Supabase에서 날짜별 JSON을 떨어뜨린다 (계획 2).

**`briefing.json`을 읽지 않고 Supabase `articles`를 읽는다.** 이유가 셋이다.

- 페이지가 `reactions`·`clicks`에 삽입할 때 쓰는 `article_id`가 필요하다.
  `save_articles`는 id를 돌려주지 않으므로 파이프라인 안에 남지 않는다.
- `articles` 테이블에는 **본문 컬럼이 아예 없다**(본문은 `article_bodies`).
  그래서 요구사항 D3(본문 미커밋)이 구조적으로 보장된다 — 넣을 경로가 없다.
- `articles`가 페이지에 필요한 것을 모두 갖고 있다.

산출물은 `docs/data/`에 들어가고 **커밋한다**(스펙 7.5: 영구 보관).
GitHub Pages가 `docs/`를 서빙한다.

실행:
  python -m pipeline.render                  # 오늘자 + 아카이브 목록
  python -m pipeline.render --date 2026-11-10 # 특정 날짜 다시 만들기
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.lib.secrets import require
from pipeline.lib.store import RemoteStore, SupabaseStore
from pipeline.lib.timeutil import KST
from pipeline.summarize import SCORE_THRESHOLD

# GitHub Pages가 서빙하는 위치. 빌드 산출물과 같은 디렉터리를 쓴다.
DATA_DIR = Path("docs/data")

# 페이지에 내보내는 필드. **여기에 없는 것은 나가지 않는다** —
# body·excerpt·reason이 실수로 끼어드는 것을 막는 화이트리스트다.
PAGE_FIELDS = (
    "id", "headline", "bullets", "why_it_matters",
    "source", "url", "published_at", "topic", "score",
)


def build_day(*, date: str, articles: list[dict], run: dict | None) -> dict:
    """하루치 페이지 데이터."""
    고른것 = [
        {k: a[k] for k in PAGE_FIELDS}
        for a in sorted(articles, key=lambda a: a["score"], reverse=True)
    ]
    return {
        "date": date,
        "articles": 고른것,
        # 0건인 날 화면이 "후보 N건 / 최고 M점 / 기준 60점"을 보여준다.
        # 기록이 없으면 None으로 둔다 — 0으로 두면 "수집 0건"이라 거짓말한다.
        "collected": run["collected_count"] if run else None,
        "considered": run["considered_count"] if run else None,
        "max_score": run["max_score"] if run else None,
        "threshold": SCORE_THRESHOLD,
        "source_counts": run["source_counts"] if run else {},
    }


def build_index(days: list[dict]) -> dict:
    """아카이브 목록. 0건인 날도 들어간다."""
    정렬 = sorted(days, key=lambda d: d["briefing_date"], reverse=True)
    return {
        "dates": [
            {"date": d["briefing_date"], "count": d["count"], "lead": d.get("lead")}
            for d in 정렬
        ],
        "days": len(정렬),
        "total": sum(d["count"] for d in 정렬),
    }


def _write(name: str, payload: dict, root: Path | None) -> Path:
    directory = root or DATA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    # ensure_ascii=False여야 한글이 그대로 저장된다. 기본값이면 \uXXXX가 되어
    # 커밋 diff를 눈으로 읽을 수 없다.
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def write_day(day: dict, *, root: Path | None = None) -> Path:
    return _write(f"{day['date']}.json", day, root)


def write_index(index: dict, *, root: Path | None = None) -> Path:
    return _write("index.json", index, root)


def render(*, remote: RemoteStore, date: str, root: Path | None = None) -> tuple[Path, Path]:
    day = build_day(
        date=date,
        articles=remote.articles_for(date),
        run=remote.run_for(date),
    )
    index = build_index(remote.archive_days())
    return write_day(day, root=root), write_index(index, root=root)


def main() -> None:
    parser = argparse.ArgumentParser(description="페이지 데이터 생성")
    parser.add_argument("--date", help="기본값은 오늘(KST)")
    args = parser.parse_args()

    date = args.date or datetime.now(timezone.utc).astimezone(KST).date().isoformat()
    remote = SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SECRET_KEY"))

    day_path, index_path = render(remote=remote, date=date)
    day = json.loads(day_path.read_text(encoding="utf-8"))
    index = json.loads(index_path.read_text(encoding="utf-8"))

    print(f"{date}: 글 {len(day['articles'])}건 → {day_path}")
    print(f"아카이브: {index['days']}일 · 총 {index['total']}건 → {index_path}")
    if not day["articles"]:
        print(f"  0건인 날이다. 후보 {day['considered']}건 · "
              f"최고 {day['max_score']}점 · 기준 {day['threshold']}점")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 통과를 확인**

Run: `.venv/bin/python -m pytest tests/test_render.py`
Expected: `18 passed`

Run: `.venv/bin/python -m pytest`
Expected: 전부 통과

- [ ] **Step 6: 실제로 돌려 본다**

```bash
.venv/bin/python -m pipeline.render
```

Expected: `docs/data/2026-11-12.json`과 `docs/data/index.json`이 생기고, 글 7건이
들어간다(계획 1에서 발행한 것).

**본문이 안 들어갔는지 반드시 확인한다:**

```bash
grep -c "body\|excerpt\|reason" docs/data/2026-11-12.json
```

Expected: `0`

- [ ] **Step 7: 커밋**

```bash
git add pipeline/render.py tests/test_render.py pipeline/lib/store.py tests/fakes.py docs/data/
git commit -m "feat: 페이지 데이터 생성 — articles에서 읽어 본문 유출 경로를 없앴다"
```

---

## Task 3: 프론트엔드 스캐폴드

**Files:**
- Create: `web/` (Vite 스캐폴드)
- Create: `web/vite.config.ts`
- Create: `docs/.nojekyll`
- Modify: `.gitignore`

> **공개 전환과 맞물리는 결과 — 점검 문서를 갱신해야 한다.**
>
> 브라우저가 Supabase에 직접 붙으므로 **빌드된 JS에 Supabase URL과
> publishable 키가 들어간다.** 공개 리포에서는 둘 다 공개된다.
>
> 설계상 괜찮다 — 스펙 7.2가 "publishable 키는 비밀이 아니다. 브라우저에
> 노출되도록 설계된 키다"라고 정했고, RLS가 실제 방어다(계획 1에서
> `verify_anon_access.sh`로 실측 확인). 다만 `docs/공개-전-점검.md`의
> "공개되지 않는 것" 목록에서 **"Supabase 프로젝트 ref·URL — 0건"을 지워야
> 한다.** Task 13에서 함께 고친다.

- [ ] **Step 1: Vite + React + TypeScript 스캐폴드**

```bash
cd /Users/predevho/토픽컬럼자동화
npm create vite@latest web -- --template react-ts
cd web && npm install
```

- [ ] **Step 2: Tailwind와 Supabase 클라이언트 설치**

```bash
cd /Users/predevho/토픽컬럼자동화/web
npm install tailwindcss @tailwindcss/vite
npm install @supabase/supabase-js
```

- [ ] **Step 3: 해결된 버전을 기록한다**

```bash
cd /Users/predevho/토픽컬럼자동화/web
npm ls --depth=0
```

출력된 버전을 이 계획 문서의 이 자리에 적어 둔다. **락파일을 커밋하므로**
나중에 "무엇이 깨졌나"를 추적할 수 있다.

- [ ] **Step 4: `web/vite.config.ts`**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],

  // GitHub Pages 프로젝트 사이트는 /<repo>/ 하위에 올라간다.
  // 이 값이 틀리면 JS·CSS 경로가 404가 된다.
  base: '/topic-briefing/',

  build: {
    // GitHub Pages가 docs/를 서빙한다.
    outDir: '../docs',

    // **반드시 false다.** docs/에는 superpowers 설계·계획 문서와
    // data/*.json(영구 보관)이 같이 있다. 기본값(true)이면 빌드가 그것들을
    // 지운다 — 되돌릴 수 없는 손실이다.
    emptyOutDir: false,
  },
})
```

- [ ] **Step 5: `docs/.nojekyll`**

```bash
touch /Users/predevho/토픽컬럼자동화/docs/.nojekyll
```

GitHub Pages는 기본적으로 Jekyll로 처리하면서 `_`로 시작하는 파일·디렉터리를
무시한다. Vite 산출물에 그런 이름이 생기면 조용히 404가 된다.

- [ ] **Step 6: `.gitignore`에 프론트엔드 산출물 추가**

```
# Node
node_modules/
web/dist/
```

`node_modules/`와 `web/dist/`는 이미 있다. **`docs/`는 넣지 않는다** — 빌드
결과를 커밋해야 Pages가 서빙한다.

- [ ] **Step 7: 빌드가 `docs/`를 지우지 않는지 확인**

이게 이 태스크에서 가장 중요한 검증이다.

```bash
cd /Users/predevho/토픽컬럼자동화
ls docs/              # superpowers/, data/, 공개-전-점검.md 가 있어야 한다
cd web && npm run build
cd .. && ls docs/     # 위의 것들이 **그대로 있어야 한다** + index.html, assets/
```

Expected: `docs/superpowers/`와 `docs/data/`가 살아 있다. 사라졌으면
`emptyOutDir: false`가 안 들어간 것이므로 `git checkout docs/`로 되돌린다.

- [ ] **Step 8: 커밋**

```bash
git add web/ docs/.nojekyll .gitignore
git commit -m "feat: 프론트엔드 스캐폴드 — docs/를 지우지 않는 빌드 설정"
```

---

## Task 4: 디자인 토큰

**Files:**
- Create: `web/src/index.css`
- Modify: `web/index.html`
- Delete: `web/src/App.css`

- [ ] **Step 1: `web/src/index.css` — A 톤 색과 글꼴**

```css
@import "tailwindcss";

/* 목업 아트보드에서 확정한 A 톤. accent는 상호작용에만 쓴다(요구사항 O14). */
@theme {
  --color-paper:       #FBFAF8;  /* 배경 */
  --color-ink:         #1A1A18;  /* 본문 글자 */
  --color-ink-2:       #3D3B37;  /* 불릿 */
  --color-muted:       #6B6862;  /* 메타·"왜" */
  --color-muted-2:     #8A8780;  /* 0건인 날의 날짜 */
  --color-rule:        #E5E1DA;  /* 카드 구분선 */
  --color-rule-soft:   #ECE8E1;  /* 목록 구분선 */
  --color-panel:       #F3F1EC;  /* 패널 배경 */
  --color-tag:         #E7E2D9;  /* 태그 배경 */
  --color-edge:        #DAD5CC;  /* 입력 테두리 */
  --color-quote:       #E0DBD2;  /* "왜" 왼쪽 선 */
  --color-accent:      #9A5B3C;  /* 상호작용 전용 */
  --color-warn:        #9A3412;  /* 경고 */

  --font-serif: "Noto Serif KR", serif;
  --font-meta:  Inter, sans-serif;
}

body {
  margin: 0;
  background: var(--color-paper);
  color: var(--color-ink);
  font-family: var(--font-serif);
}

a { color: inherit; text-decoration: none; }
a:hover h2 {
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 4px;
}

/* 포커스 표시를 남긴다. 키보드로 쓸 때 어디 있는지 보여야 한다. */
button:focus-visible,
textarea:focus-visible,
input:focus-visible,
a:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}
```

> **한글에 이탤릭을 쓰지 않는다.** `Noto Serif KR`에 이탤릭 자체가 없어서
> 브라우저가 기울임을 **합성**하고, 한글에서는 어긋나 보인다. 목업이 "왜"
> 문단의 강조를 왼쪽 2px 선으로 바꾼 이유이고, 이 CSS에 `italic`이 없는 이유다.

- [ ] **Step 2: `web/index.html` — 색인 차단과 글꼴**

```html
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />

    <!-- 요구사항 D4. "아무도 모르는 URL"이라는 전제가 색인되면 깨진다.
         robots.txt만으로는 이미 수집된 페이지가 남으므로 메타 태그도 넣는다. -->
    <meta name="robots" content="noindex, nofollow, noarchive" />

    <title>IT 브리핑</title>

    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      rel="stylesheet"
      href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600&family=Inter:wght@400;500&display=swap"
    />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 3: 스캐폴드가 만든 `App.css`를 지우고 `main.tsx`를 고친다**

```bash
rm /Users/predevho/토픽컬럼자동화/web/src/App.css
```

`web/src/main.tsx`:

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

- [ ] **Step 4: 빌드가 되는지 확인**

Run: `cd web && npm run build`
Expected: 오류 없이 끝나고 `docs/assets/`에 CSS·JS가 생긴다.

- [ ] **Step 5: 커밋**

```bash
git add web/src/index.css web/index.html web/src/main.tsx
git rm --cached web/src/App.css 2>/dev/null || true
git commit -m "feat: A 톤 디자인 토큰 + 색인 차단 메타"
```

---

## Task 5: 타입과 데이터 불러오기

**Files:**
- Create: `web/src/lib/types.ts`
- Create: `web/src/lib/data.ts`

- [ ] **Step 1: `web/src/lib/types.ts` — `render.py`의 출력과 1:1**

```typescript
// pipeline/render.py의 PAGE_FIELDS와 맞춰야 한다. 한쪽만 바꾸면 조용히 깨진다.
export type Article = {
  id: number
  headline: string
  bullets: string[]
  why_it_matters: string
  source: string
  url: string
  published_at: string
  topic: string
  score: number
}

export type Day = {
  date: string
  articles: Article[]
  // 실행 기록이 없으면 null이다. 0으로 두면 "수집 0건"이라 거짓말하므로
  // render가 일부러 null을 넣는다.
  collected: number | null
  considered: number | null
  max_score: number | null
  threshold: number
  source_counts: Record<string, number>
}

export type ArchiveEntry = {
  date: string
  count: number
  lead: string | null
}

export type Archive = {
  dates: ArchiveEntry[]
  days: number
  total: number
}
```

- [ ] **Step 2: `web/src/lib/data.ts`**

```typescript
import type { Archive, Day } from './types'

// import.meta.env.BASE_URL은 vite.config.ts의 base와 같다('/topic-briefing/').
// 하드코딩하면 로컬 dev 서버('/')에서 깨진다.
const DATA = `${import.meta.env.BASE_URL}data`

export class NotFound extends Error {}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: 'no-cache' })
  if (res.status === 404) throw new NotFound(path)
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return (await res.json()) as T
}

export function fetchArchive(): Promise<Archive> {
  return get<Archive>(`${DATA}/index.json`)
}

export function fetchDay(date: string): Promise<Day> {
  return get<Day>(`${DATA}/${date}.json`)
}

/** 최신 브리핑. 아카이브 목록의 첫 항목이 가장 최근이다. */
export async function fetchLatest(): Promise<Day> {
  const archive = await fetchArchive()
  const first = archive.dates[0]
  if (!first) throw new NotFound('아직 발행한 브리핑이 없다')
  return fetchDay(first.date)
}
```

- [ ] **Step 3: 커밋**

```bash
git add web/src/lib/types.ts web/src/lib/data.ts
git commit -m "feat: 페이지 데이터 타입과 불러오기"
```

---

## Task 6: 카드 컴포넌트

**Files:**
- Create: `web/src/components/Card.tsx`

목업 `Main.dc.html`의 구조·치수를 그대로 옮긴다.

- [ ] **Step 1: `web/src/components/Card.tsx`**

```tsx
import type { Article } from '../lib/types'
import LikeButton from './LikeButton'

type Props = { article: Article; onOpen: (article: Article) => void }

export default function Card({ article, onOpen }: Props) {
  return (
    <article className="flex flex-col gap-2.5">
      <a
        href={article.url}
        target="_blank"
        rel="noreferrer noopener"
        onClick={() => onOpen(article)}
      >
        <h2 className="m-0 text-[19px] font-semibold leading-[1.45] tracking-[-0.01em]">
          {article.headline}
        </h2>
      </a>

      <ul className="m-0 flex list-disc flex-col gap-1.5 pl-[15px] text-[14.5px] leading-[1.7] text-ink-2">
        {article.bullets.map((bullet, i) => (
          <li key={i}>{bullet}</li>
        ))}
      </ul>

      {/*
        한글에 이탤릭을 쓰지 않는다 — Noto Serif KR에 이탤릭이 없어서 브라우저가
        합성하고, 한글에서는 어긋나 보인다. 목업처럼 왼쪽 2px 선으로 강조한다.
      */}
      <p className="m-0 border-l-2 border-quote pl-[11px] text-[13.5px] leading-[1.6] text-muted">
        {article.why_it_matters}
      </p>

      <div className="mt-0.5 flex items-center gap-2.5 font-meta text-[11.5px] text-muted">
        <span>{article.source}</span>
        <span aria-hidden="true">·</span>
        <span className="font-medium text-ink-2">{article.score}</span>
        <LikeButton articleId={article.id} className="ml-auto -mr-2.5" />
      </div>
    </article>
  )
}
```

- [ ] **Step 2: 커밋** (`LikeButton`은 Task 10에서 만든다 — 그때 빌드가 통과한다)

```bash
git add web/src/components/Card.tsx
git commit -m "feat: 카드 컴포넌트 — 목업 치수 그대로"
```

---

## Task 7: 오늘 화면 (0건 포함)

**Files:**
- Create: `web/src/components/Today.tsx`
- Create: `web/src/components/Empty.tsx`

- [ ] **Step 1: `web/src/components/Empty.tsx` — 목업 `Empty.dc.html`**

```tsx
import type { Day } from '../lib/types'

export default function Empty({ day }: { day: Day }) {
  const silent = Object.entries(day.source_counts)
    .filter(([, n]) => n === 0)
    .map(([name]) => name)

  return (
    <div className="flex flex-col gap-6">
      <p className="m-0 text-[15px] leading-[1.75] text-ink-2">
        후보 {day.considered ?? 0}건을 봤지만 기준을 넘긴 글이 없었습니다.
        <br />
        조용한 날입니다 — <strong className="font-semibold">시스템은 정상입니다.</strong>
      </p>

      <section className="flex flex-col gap-3 bg-panel px-[18px] py-4 font-meta">
        <h2 className="m-0 font-serif text-[14px] font-semibold">왜 비었는지</h2>
        <dl className="m-0 flex flex-col gap-2 text-[12.5px]">
          <Row label="수집" value={`${day.collected ?? 0}건`} />
          <Row label="최고 점수" value={day.max_score === null ? '없음' : `${day.max_score}점`} />
          <Row label="기준" value={`${day.threshold}점`} strong />
        </dl>
        {day.max_score !== null && (
          <p className="m-0 font-serif text-[12.5px] leading-[1.65] text-muted">
            최고 점수가 기준에 {day.threshold - day.max_score}점 못 미쳤습니다. 이런 날이
            한 주에 세 번 넘으면 기준을 내리거나 소스를 늘릴 때입니다.
          </p>
        )}
      </section>

      {silent.length > 0 && (
        <section className="flex flex-col gap-2.5 font-meta">
          <h2 className="m-0 font-serif text-[14px] font-semibold">0건인 소스</h2>
          <ul className="m-0 flex list-none flex-col gap-[7px] p-0 text-[12.5px]">
            {silent.map((name) => (
              <li key={name} className="flex justify-between gap-3">
                <span className="text-ink-2">{name}</span>
                <span className="text-muted">0건</span>
              </li>
            ))}
          </ul>
          {/*
            목업은 "3일 연속"까지 보여주지만, 그건 여러 날의 runs를 봐야 안다.
            계획 3의 lib/guard가 그 판정을 하므로 여기서는 그날의 0건만 보여준다.
          */}
        </section>
      )}
    </div>
  )
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className={`m-0 ${strong ? 'font-medium text-ink-2' : 'text-ink'}`}>{value}</dd>
    </div>
  )
}
```

- [ ] **Step 2: `web/src/components/Today.tsx`**

```tsx
import type { Article, Day } from '../lib/types'
import { recordClick } from '../lib/supabase'
import Card from './Card'
import Empty from './Empty'

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']

function korean(date: string): string {
  // "2026-11-12" → "11월 12일 목요일". Date의 월은 0부터 시작한다.
  const [y, m, d] = date.split('-').map(Number)
  const when = new Date(y, m - 1, d)
  return `${m}월 ${d}일 ${WEEKDAYS[when.getDay()]}요일`
}

export default function Today({ day }: { day: Day }) {
  const count = day.articles.length

  function onOpen(article: Article) {
    recordClick(article.id)
  }

  return (
    <main className="mx-auto flex max-w-[1340px] flex-col gap-[26px] px-[22px] pb-8 pt-7">
      <header className="flex flex-col gap-2">
        <div className="font-meta text-[12px] uppercase tracking-[0.06em] text-muted">
          {korean(day.date)}
        </div>
        <h1 className="m-0 text-[25px] font-semibold tracking-[-0.01em]">
          {count === 0 ? '오늘은 보낼 글이 없습니다' : `오늘의 토픽 ${count}건`}
        </h1>
        {count > 0 && (
          <p className="m-0 font-meta text-[12.5px] text-muted">
            후보 {day.considered ?? '?'}건 중 기준을 넘긴 글
          </p>
        )}
      </header>

      <div className="h-px bg-rule" />

      {count === 0 ? (
        <Empty day={day} />
      ) : (
        // 모바일 1열 / 태블릿 이상 2열 (요구사항 O10)
        <div className="grid grid-cols-1 gap-[26px] md:grid-cols-2 md:gap-x-10">
          {day.articles.map((article) => (
            <div key={article.id} className="flex flex-col gap-[26px]">
              <Card article={article} onOpen={onOpen} />
              <div className="h-px bg-rule md:hidden" />
            </div>
          ))}
        </div>
      )}

      <nav className="mt-auto flex items-center justify-end font-meta text-[13px]">
        <a href={`${import.meta.env.BASE_URL}archive`} className="py-3 text-muted">
          지난 브리핑
        </a>
      </nav>
    </main>
  )
}
```

- [ ] **Step 3: 커밋**

```bash
git add web/src/components/Today.tsx web/src/components/Empty.tsx
git commit -m "feat: 오늘 화면 — 0건인 날은 왜 비었는지 보여준다"
```

---

## Task 8: 아카이브 화면

**Files:**
- Create: `web/src/components/Archive.tsx`

목업 `Archive.dc.html`의 구조. 월별로 묶고 0건인 날도 보여준다.

- [ ] **Step 1: `web/src/components/Archive.tsx`**

```tsx
import type { Archive as ArchiveData, ArchiveEntry } from '../lib/types'

function monthLabel(date: string): string {
  const [y, m] = date.split('-')
  return `${y}년 ${Number(m)}월`
}

function dayLabel(date: string): string {
  const [, m, d] = date.split('-')
  return `${m}/${d}`
}

/** 월별로 묶는다. dates는 최신순으로 들어오므로 순서가 유지된다. */
function byMonth(dates: ArchiveEntry[]): [string, ArchiveEntry[]][] {
  const groups = new Map<string, ArchiveEntry[]>()
  for (const entry of dates) {
    const key = monthLabel(entry.date)
    const list = groups.get(key)
    if (list) list.push(entry)
    else groups.set(key, [entry])
  }
  return [...groups.entries()]
}

export default function Archive({ archive }: { archive: ArchiveData }) {
  return (
    <main className="mx-auto flex max-w-[1340px] flex-col gap-6 px-[22px] pb-8 pt-7">
      <header className="flex flex-col gap-2">
        <a href={import.meta.env.BASE_URL} className="py-1 font-meta text-[12.5px] text-muted">
          ← 오늘로
        </a>
        <h1 className="m-0 text-[25px] font-semibold tracking-[-0.01em]">지난 브리핑</h1>
        <p className="m-0 font-meta text-[12.5px] text-muted">
          발행 {archive.days}일 · 총 {archive.total}건
        </p>
      </header>

      <div className="h-px bg-rule" />

      {byMonth(archive.dates).map(([month, entries]) => (
        <section key={month} className="flex flex-col gap-3">
          <h2 className="m-0 font-meta text-[11.5px] uppercase tracking-[0.08em] text-muted">
            {month}
          </h2>
          <ul className="m-0 flex list-none flex-col p-0">
            {entries.map((entry) => (
              <li key={entry.date} className="border-b border-rule-soft">
                <a
                  href={`${import.meta.env.BASE_URL}${entry.date}`}
                  className="flex items-baseline gap-3 py-[13px]"
                >
                  <span
                    className={`w-[52px] flex-none text-[15px] font-semibold ${
                      entry.count === 0 ? 'text-muted-2' : ''
                    }`}
                  >
                    {dayLabel(entry.date)}
                  </span>
                  <span
                    className={`min-w-0 flex-1 text-[13.5px] leading-[1.55] ${
                      entry.count === 0 ? 'text-muted' : 'text-ink-2'
                    }`}
                  >
                    {entry.count === 0
                      ? '기준을 넘긴 글 없음'
                      : entry.count === 1
                        ? entry.lead
                        : `${entry.lead} 외 ${entry.count - 1}건`}
                  </span>
                  <span
                    className={`flex-none font-meta text-[11.5px] ${
                      entry.count === 0 ? 'text-muted-2' : 'text-ink-2'
                    }`}
                  >
                    {entry.count}건
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  )
}
```

- [ ] **Step 2: 커밋**

```bash
git add web/src/components/Archive.tsx
git commit -m "feat: 아카이브 화면 — 0건인 날도 목록에 남긴다"
```

---

## Task 9: 라우팅과 GitHub Pages 폴백

**Files:**
- Modify: `web/src/App.tsx`
- Create: `docs/404.html` (빌드 후 복사)

> **라우터 의존성을 넣지 않는다.** 경로가 셋(`/`, `/:date`, `/archive`)뿐이고,
> `base` 하위에서 동작해야 해서 라우터 설정에 손이 더 간다. 직접 읽는 쪽이
> 코드가 짧고 폴백 처리도 단순해진다 (YAGNI).
>
> **폴백이 왜 단순해지나** — GitHub Pages는 없는 경로에 `404.html`을 준다.
> 그 파일이 `index.html`의 복사본이면 앱이 그대로 뜨고, 앱은
> `location.pathname`을 읽어 날짜를 알아낸다. `sessionStorage`로 경로를
> 넘기는 흔한 우회가 필요 없다.

- [ ] **Step 1: `web/src/App.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { NotFound, fetchArchive, fetchDay, fetchLatest } from './lib/data'
import type { Archive as ArchiveData, Day } from './lib/types'
import ArchiveView from './components/Archive'
import Today from './components/Today'

const DATE = /^\d{4}-\d{2}-\d{2}$/

/** base('/topic-briefing/')를 떼고 남은 첫 조각. */
function route(): string {
  const base = import.meta.env.BASE_URL
  const path = window.location.pathname
  const rest = path.startsWith(base) ? path.slice(base.length) : path.replace(/^\//, '')
  return rest.replace(/\/$/, '')
}

type State =
  | { kind: 'loading' }
  | { kind: 'day'; day: Day }
  | { kind: 'archive'; archive: ArchiveData }
  | { kind: 'error'; message: string }

export default function App() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    const slug = route()

    const load = async (): Promise<State> => {
      if (slug === 'archive') {
        return { kind: 'archive', archive: await fetchArchive() }
      }
      if (DATE.test(slug)) {
        return { kind: 'day', day: await fetchDay(slug) }
      }
      return { kind: 'day', day: await fetchLatest() }
    }

    load().then(setState, (error: unknown) => {
      const message =
        error instanceof NotFound
          ? '그 날짜의 브리핑이 없습니다.'
          : '브리핑을 불러오지 못했습니다.'
      setState({ kind: 'error', message })
    })
  }, [])

  if (state.kind === 'loading') {
    return <Shell>불러오는 중…</Shell>
  }
  if (state.kind === 'error') {
    return (
      <Shell>
        {state.message}
        <br />
        <a href={import.meta.env.BASE_URL} className="text-accent underline">
          오늘로 가기
        </a>
      </Shell>
    )
  }
  if (state.kind === 'archive') {
    return <ArchiveView archive={state.archive} />
  }
  return <Today day={state.day} />
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto max-w-[1340px] px-[22px] pt-7">
      <p className="m-0 font-meta text-[13px] text-muted">{children}</p>
    </main>
  )
}
```

- [ ] **Step 2: 빌드 후 `404.html`을 만드는 스크립트**

`web/package.json`의 `scripts`에 추가한다.

```json
    "build": "tsc -b && vite build && cp ../docs/index.html ../docs/404.html"
```

- [ ] **Step 3: 빌드하고 폴백 파일을 확인**

```bash
cd web && npm run build && cd ..
diff docs/index.html docs/404.html && echo "404.html이 index.html과 같다"
```

Expected: 차이 없음

- [ ] **Step 4: 로컬에서 날짜 경로가 뜨는지 확인**

```bash
cd web && npm run dev
```

브라우저에서 `http://localhost:5173/2026-11-12`를 연다. dev 서버는 `base`가
`/`이므로 경로가 바로 먹는다.

Expected: 그 날짜의 브리핑이 뜬다. 없는 날짜(`/1999-01-01`)는 "그 날짜의
브리핑이 없습니다."

- [ ] **Step 5: 커밋**

```bash
git add web/src/App.tsx web/package.json docs/index.html docs/404.html docs/assets
git commit -m "feat: 경로 라우팅 + Pages 404 폴백 (라우터 의존성 없이)"
```

---

## Task 10: Supabase 클라이언트와 좋아요

**Files:**
- Create: `web/.env.local` (커밋하지 않는다)
- Create: `web/.env.example`
- Create: `web/src/lib/supabase.ts`
- Create: `web/src/lib/liked.ts`
- Create: `web/src/components/LikeButton.tsx`
- Modify: `.gitignore`

> **anon은 `reactions`에 INSERT만 할 수 있다** (계획 1의 `schema.sql` 실측).
> 읽기도 삭제도 없으므로 **토글을 DB로 구현할 수 없다.** 권한을 늘리지 않는다 —
> anon에 DELETE를 주면 URL을 아는 누구나 좋아요를 지울 수 있다.
>
> DB는 **추가 전용 이벤트**로 쓰고, 눌렀는지 여부는 `localStorage`가 기기별로
> 기억한다. 같은 글을 두 번 눌러도 이벤트가 둘 쌓이는데, 스펙 7.2가 "신호
> 오염이 생기면 Phase 2에서 바로 드러나 그때 대응"으로 이미 수용했다.

- [ ] **Step 1: 환경 변수**

`web/.env.example`:

```
# 브라우저용 publishable 키. **비밀이 아니다** — 브라우저에 노출되도록
# 설계된 키이고, 실제 방어는 RLS다(계획 1의 verify_anon_access.sh로 확인).
# 공개 리포에서는 빌드된 JS에 그대로 들어간다.
VITE_SUPABASE_URL=https://xxxxx.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```

`web/.env.local`을 만들어 실제 값을 넣는다. 루트 `.env`의
`SUPABASE_URL`·`VITE_SUPABASE_PUBLISHABLE_KEY`와 같은 값이다.

`.gitignore`에 추가:

```
web/.env.local
```

- [ ] **Step 2: `web/src/lib/liked.ts`**

```typescript
// localStorage는 사생활이 아니라 **편의**다. 사생활 모드·사이트 데이터 삭제·
// 다른 기기에서는 비어 있으므로, 없으면 "안 누른 상태"로 그린다.
// 접근 자체가 예외를 던질 수 있어서 전부 try/catch로 감싼다.

const KEY = (articleId: number) => `liked:${articleId}`

export function isLiked(articleId: number): boolean {
  try {
    return window.localStorage.getItem(KEY(articleId)) === '1'
  } catch {
    return false
  }
}

export function markLiked(articleId: number): void {
  try {
    window.localStorage.setItem(KEY(articleId), '1')
  } catch {
    // 저장이 안 되면 다음 방문에 빈 하트로 보인다. 화면은 깨지지 않는다.
  }
}
```

- [ ] **Step 3: `web/src/lib/supabase.ts`**

```typescript
import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL as string
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string

export const supabase = createClient(url, key)

/** 좋아요 이벤트를 쌓는다. anon은 INSERT만 가능하므로 추가 전용이다. */
export async function recordLike(articleId: number): Promise<void> {
  // user_id는 넣지 않는다 — RLS 정책이 `with check (user_id is null)`이다.
  const { error } = await supabase.from('reactions').insert({ article_id: articleId })
  if (error) {
    // 기록이 실패해도 화면은 그대로 둔다. 신호 하나가 빠지는 것이
    // 화면이 깨지는 것보다 낫다.
    console.warn('좋아요 기록 실패', error.message)
  }
}

/**
 * 클릭을 기록한다. 원문으로 떠나는 중에도 요청이 살아야 한다.
 *
 * **스펙 7.3은 `navigator.sendBeacon`을 적었지만 쓸 수 없다** —
 * sendBeacon은 헤더를 설정할 수 없고, Supabase REST는 `apikey`와
 * `Authorization` 헤더를 요구한다. `fetch`의 `keepalive: true`가 같은
 * 목적(이탈 중 전송 유지)을 달성하면서 헤더를 보낼 수 있다.
 */
export function recordClick(articleId: number): void {
  const body = JSON.stringify({ article_id: articleId })
  void fetch(`${url}/rest/v1/clicks`, {
    method: 'POST',
    keepalive: true,
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      'Content-Type': 'application/json',
      Prefer: 'return=minimal',
    },
    body,
  }).catch(() => {
    // 이탈 중이라 실패를 보고할 곳이 없다. 조용히 넘긴다.
  })
}
```

- [ ] **Step 4: `web/src/components/LikeButton.tsx`**

```tsx
import { useState } from 'react'
import { isLiked, markLiked } from '../lib/liked'
import { recordLike } from '../lib/supabase'

type Props = { articleId: number; className?: string }

export default function LikeButton({ articleId, className = '' }: Props) {
  const [liked, setLiked] = useState(() => isLiked(articleId))

  function onClick() {
    // 이미 누른 글은 다시 보내지 않는다. DB에 삭제 권한이 없어서 되돌릴 수
    // 없고, 중복 이벤트를 줄이는 것이 신호 품질에 낫다.
    if (liked) return
    setLiked(true)
    markLiked(articleId)
    void recordLike(articleId)
  }

  return (
    <button
      type="button"
      aria-label="이 글에 좋아요"
      aria-pressed={liked}
      onClick={onClick}
      // 44×44는 손가락 터치 목표 크기다. 목업과 같다.
      className={`flex h-11 w-11 items-center justify-center border-0 bg-transparent ${
        liked ? 'cursor-default text-accent' : 'cursor-pointer text-muted'
      } ${className}`}
    >
      <svg
        width="17"
        height="17"
        viewBox="0 0 24 24"
        fill={liked ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="1.8"
        aria-hidden="true"
      >
        <path d="M12 20.5 4.6 13.3a4.8 4.8 0 0 1 6.8-6.8l.6.6.6-.6a4.8 4.8 0 0 1 6.8 6.8z" />
      </svg>
    </button>
  )
}
```

- [ ] **Step 5: 실제로 눌러서 DB에 들어가는지 확인**

```bash
cd web && npm run dev
```

브라우저에서 글 하나의 하트를 누른다. 그다음:

```bash
cd /Users/predevho/토픽컬럼자동화
.venv/bin/python -c "
from supabase import create_client
from pipeline.lib.secrets import require
c = create_client(require('SUPABASE_URL'), require('SUPABASE_SECRET_KEY'))
print(c.table('reactions').select('article_id,user_id,created_at').execute().data)
"
```

Expected: 행 1개, `user_id`가 `None`이다. **`user_id`가 채워져 있으면 RLS 정책이
의도와 다르게 통과한 것이므로 멈춘다.**

새로고침해도 하트가 채워진 상태로 남아야 한다(`localStorage`).

- [ ] **Step 6: 커밋**

```bash
git add web/src/lib/supabase.ts web/src/lib/liked.ts \
        web/src/components/LikeButton.tsx web/.env.example .gitignore
git commit -m "feat: 좋아요 — DB는 추가 전용, 누른 상태는 localStorage"
```

---

## Task 11: 메모와 태그

**Files:**
- Create: `web/src/components/Note.tsx`
- Modify: `web/src/lib/supabase.ts`
- Modify: `web/src/components/Card.tsx`

> **anon은 `notes`에 SELECT와 INSERT만 할 수 있다.** UPDATE·DELETE가 없으므로
> 제자리 수정이 안 된다. **추가 전용으로 쓰고 읽을 때 가장 최근 행을 쓴다.**
> 태그를 지우는 것도 "지운 태그를 뺀 새 행"을 넣는 것이다.

- [ ] **Step 1: `web/src/lib/supabase.ts`에 메모 함수 추가**

```typescript
export type Note = { text: string; tags: string[] }

/** 그 글의 가장 최근 메모. 추가 전용이라 마지막 행이 현재 상태다. */
export async function fetchNote(articleId: number): Promise<Note | null> {
  const { data, error } = await supabase
    .from('notes')
    .select('text,tags')
    .eq('article_id', articleId)
    .order('created_at', { ascending: false })
    .limit(1)

  if (error || !data || data.length === 0) return null
  return { text: data[0].text as string, tags: (data[0].tags as string[]) ?? [] }
}

/** 메모를 저장한다. 수정이 아니라 새 행을 넣는 것이다. */
export async function saveNote(articleId: number, note: Note): Promise<boolean> {
  const { error } = await supabase
    .from('notes')
    .insert({ article_id: articleId, text: note.text, tags: note.tags })
  if (error) {
    console.warn('메모 저장 실패', error.message)
    return false
  }
  return true
}
```

- [ ] **Step 2: `web/src/components/Note.tsx` — 목업 `Interact.dc.html`**

```tsx
import { useEffect, useState } from 'react'
import { fetchNote, saveNote, type Note as NoteData } from '../lib/supabase'

export default function Note({ articleId }: { articleId: number }) {
  const [note, setNote] = useState<NoteData>({ text: '', tags: [] })
  const [tagInput, setTagInput] = useState('')
  const [hint, setHint] = useState('')

  useEffect(() => {
    fetchNote(articleId).then((loaded) => {
      if (loaded) setNote(loaded)
    })
  }, [articleId])

  function addTag() {
    const next = tagInput.trim()
    if (!next || note.tags.includes(next)) return
    setNote({ ...note, tags: [...note.tags, next] })
    setTagInput('')
  }

  async function save() {
    const ok = await saveNote(articleId, note)
    setHint(ok ? '저장했습니다' : '저장하지 못했습니다')
  }

  return (
    <div className="flex flex-col gap-2.5 bg-panel p-3.5 font-meta">
      <label htmlFor={`note-${articleId}`} className="font-serif text-[12.5px] font-semibold">
        메모
      </label>
      <textarea
        id={`note-${articleId}`}
        rows={3}
        value={note.text}
        onChange={(e) => setNote({ ...note, text: e.target.value })}
        placeholder="나중에 찾을 단서를 적습니다"
        className="box-border w-full resize-y border border-edge bg-paper px-2.5 py-[9px] font-serif text-[13px] leading-[1.6] text-ink"
      />

      <div className="flex flex-wrap gap-1.5">
        {note.tags.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-[5px] bg-tag px-[9px] py-1 text-[11.5px] text-ink-2"
          >
            {tag}
            <button
              type="button"
              aria-label={`${tag} 태그 지우기`}
              onClick={() => setNote({ ...note, tags: note.tags.filter((t) => t !== tag) })}
              className="flex h-3.5 w-3.5 items-center justify-center border-0 bg-transparent p-0 text-muted"
            >
              <svg width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                <path d="M2 2l8 8M10 2l-8 8" />
              </svg>
            </button>
          </span>
        ))}
      </div>

      <div className="flex gap-1.5">
        <label htmlFor={`tag-${articleId}`} className="sr-only">태그 추가</label>
        <input
          id={`tag-${articleId}`}
          type="text"
          value={tagInput}
          onChange={(e) => setTagInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addTag() } }}
          placeholder="태그"
          className="box-border min-w-0 flex-1 border border-edge bg-paper px-2.5 py-[9px] font-meta text-[12.5px] text-ink"
        />
        <button
          type="button"
          onClick={addTag}
          className="min-h-11 flex-none cursor-pointer border border-edge bg-paper px-3.5 font-meta text-[12.5px] text-ink-2"
        >
          추가
        </button>
      </div>

      <div className="mt-0.5 flex items-center gap-2.5">
        <button
          type="button"
          onClick={save}
          className="min-h-11 cursor-pointer border-0 bg-accent px-4 font-meta text-[12.5px] text-paper"
        >
          저장
        </button>
        <span className="font-serif text-[11.5px] text-muted">{hint}</span>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: `Card.tsx`에 메모 열기 버튼을 붙인다**

`Card.tsx`의 `import`에 추가:

```tsx
import { useState } from 'react'
import Note from './Note'
```

컴포넌트 본문 맨 위에 추가:

```tsx
  const [noteOpen, setNoteOpen] = useState(false)
```

메타 줄의 `LikeButton` **뒤에** 추가:

```tsx
        <button
          type="button"
          aria-label={noteOpen ? '메모 접기' : '메모 쓰기'}
          aria-expanded={noteOpen}
          onClick={() => setNoteOpen(!noteOpen)}
          className={`-mr-2.5 flex h-11 w-11 cursor-pointer items-center justify-center border-0 bg-transparent ${
            noteOpen ? 'text-accent' : 'text-muted'
          }`}
        >
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
            <path d="M4 20h4l11-11a2.8 2.8 0 0 0-4-4L4 16z" />
          </svg>
        </button>
```

메타 줄을 닫는 `</div>` **뒤에** 추가:

```tsx
      {noteOpen && <Note articleId={article.id} />}
```

`LikeButton`의 `className`에서 `-mr-2.5`를 **빼고** `ml-auto`만 남긴다
(메모 버튼이 마지막이 되므로 음수 여백은 그쪽이 가진다).

- [ ] **Step 4: 저장하고 새로고침해 남는지 확인**

`npm run dev`에서 메모를 쓰고 태그를 둘 추가한 뒤 저장한다. 새로고침한다.

Expected: 메모와 태그가 그대로 보인다(가장 최근 행을 읽는다).

태그 하나를 ×로 지우고 저장한 뒤 새로고침한다.

Expected: 지운 태그가 사라진다. DB에는 행이 **둘** 있다:

```bash
.venv/bin/python -c "
from supabase import create_client
from pipeline.lib.secrets import require
c = create_client(require('SUPABASE_URL'), require('SUPABASE_SECRET_KEY'))
for r in c.table('notes').select('article_id,text,tags,created_at').order('created_at').execute().data:
    print(r['created_at'], r['tags'], r['text'][:30])
"
```

- [ ] **Step 5: 커밋**

```bash
git add web/src/components/Note.tsx web/src/components/Card.tsx web/src/lib/supabase.ts
git commit -m "feat: 메모·태그 — 추가 전용, 읽을 때 최신 행"
```

---

## Task 12: 색인 차단과 점검 문서 갱신

**Files:**
- Create: `docs/robots.txt`
- Modify: `docs/공개-전-점검.md`

- [ ] **Step 1: `docs/robots.txt`**

```
User-agent: *
Disallow: /
```

요구사항 D4. 스펙 7.2: "GitHub Pages는 검색엔진에 색인되므로, 이것이 없으면
'아무도 모르는 URL'이라는 전제가 깨진다." `index.html`의 `noindex` 메타와 **둘 다**
둔다 — `robots.txt`는 크롤링을, 메타는 이미 수집된 페이지의 색인을 막는다.

- [ ] **Step 2: 점검 문서의 "공개되지 않는 것"을 고친다**

**이 줄을 지운다:**

```
- **Supabase 프로젝트 ref·URL** — 추적 파일에 한 건도 없다
```

**대신 "검토했고 공개해도 되는 것" 표에 추가한다:**

| 항목 | 판단 |
|---|---|
| `docs/assets/*.js`의 Supabase URL과 publishable 키 | **의도된 노출이다.** 브라우저가 Supabase에 직접 붙으므로 빌드 산출물에 들어간다. 스펙 7.2: "publishable 키는 비밀이 아니다 — 브라우저에 노출되도록 설계된 키다." 실제 방어는 RLS이고 `verify_anon_access.sh`로 실측 확인했다. **secret 키는 들어가지 않는다**(파이프라인만 쓴다) |

- [ ] **Step 3: secret 키가 빌드 산출물에 없는지 확인**

이게 이 태스크의 핵심 검증이다.

```bash
cd /Users/predevho/토픽컬럼자동화
grep -rl "sb_secret_" docs/assets/ 2>/dev/null && echo "⚠️  secret 키가 들어갔다" || echo "✓ secret 키 없음"
grep -rlo "sb_publishable_[A-Za-z0-9_-]*" docs/assets/ 2>/dev/null | head -1
```

Expected: secret 키 없음. publishable 키는 있어도 정상이다.

> Vite는 `VITE_` 접두사가 붙은 환경 변수만 클라이언트에 넣는다. 루트 `.env`의
> `SUPABASE_SECRET_KEY`는 접두사가 없고 `web/.env.local`에도 없으므로 들어갈
> 경로가 없다 — 그래도 공개 리포이므로 매 빌드마다 확인한다.

- [ ] **Step 4: 커밋**

```bash
git add docs/robots.txt docs/공개-전-점검.md
git commit -m "feat: 색인 차단 + 점검 문서에 publishable 키 노출을 기록"
```

---

## Task 13: GitHub Pages 배포

**Files:**
- 설정만 (리포지토리 설정)

- [ ] **Step 1: Pages를 `docs/`로 켠다**

```bash
gh api -X POST repos/predevho/topic-briefing/pages \
  -f 'source[branch]=main' -f 'source[path]=/docs'
```

실패하면 웹에서 한다: Settings → Pages → Source: *Deploy from a branch* →
Branch `main`, 폴더 `/docs`.

- [ ] **Step 2: 빌드 결과를 커밋하고 푸시**

```bash
cd web && npm run build && cd ..
git add docs/
git commit -m "build: 페이지 빌드 산출물"
git push origin main
```

- [ ] **Step 3: 배포를 기다려 확인**

```bash
gh api repos/predevho/topic-briefing/pages --jq '"status: \(.status)  url: \(.html_url)"'
```

Expected: `status: built`, `url: https://predevho.github.io/topic-briefing/`

- [ ] **Step 4: 실제 URL을 폰과 데스크톱에서 확인**

| 확인할 것 | 기대 |
|---|---|
| `https://predevho.github.io/topic-briefing/` | 최신 브리핑 |
| `.../2026-11-12` | 그 날짜 (404 폴백이 동작한다) |
| `.../archive` | 아카이브 목록 |
| `.../1999-01-01` | "그 날짜의 브리핑이 없습니다." |
| `.../robots.txt` | `Disallow: /` |
| 폰 (가로 390px 정도) | 1열, 글자가 읽히는 크기 |
| 데스크톱 | 2열 (`md:grid-cols-2`) |

**`base`가 틀리면 JS·CSS가 404가 되어 빈 화면이 뜬다.** 그러면
`vite.config.ts`의 `base`를 `/topic-briefing/`으로 확인한다.

- [ ] **Step 5: `README.md`에 배포 절차를 적는다**

"## 매일 실행" 아래에 추가:

```markdown
페이지까지 갱신하려면 두 단계를 더 한다.

```bash
python -m pipeline.render      # docs/data/<날짜>.json + index.json
cd web && npm run build && cd ..   # docs/index.html + assets/
git add docs/ && git commit -m "build: 브리핑 갱신" && git push
```

`render`만 돌리고 빌드를 건너뛰어도 된다 — **SPA는 코드가 바뀔 때만 다시
빌드한다.** JSON만 커밋하면 페이지가 새 날짜를 읽는다(스펙 6.4).
```

- [ ] **Step 6: 커밋**

```bash
git add README.md
git commit -m "docs: 페이지 배포 절차"
git push origin main
```

---

## Task 14: 엔드투엔드 검증

- [ ] **Step 1: 파이프라인부터 페이지까지 한 번에 돌린다**

```bash
cd /Users/predevho/토픽컬럼자동화
.venv/bin/python -m pipeline.collect
.venv/bin/python -m pipeline.rank
.venv/bin/python -m pipeline.enrich
.venv/bin/python -m pipeline.summarize
.venv/bin/python -m pipeline.notify
.venv/bin/python -m pipeline.render
git add docs/data/ && git commit -m "build: 브리핑 갱신" && git push
```

Expected: 1~2분 뒤 페이지에 그날 브리핑이 보인다. **빌드를 다시 하지 않았는데도
보여야 한다** — 그게 스펙 6.4의 분리가 작동한다는 증거다.

- [ ] **Step 2: 0건인 날을 만들어 본다**

`notify` 직후 윈도우가 전진하므로 바로 다시 돌리면 0건이 된다
(계획 1의 Task 22에서 확인한 경로).

```bash
.venv/bin/python -m pipeline.collect && .venv/bin/python -m pipeline.rank \
  && .venv/bin/python -m pipeline.enrich && .venv/bin/python -m pipeline.summarize \
  && .venv/bin/python -m pipeline.notify --force && .venv/bin/python -m pipeline.render
```

Expected: 페이지가 "오늘은 보낼 글이 없습니다"와 **왜 비었는지**(수집·최고 점수·
기준)를 보여준다.

- [ ] **Step 3: 상호작용이 쌓이는지 확인**

```bash
.venv/bin/python -c "
from supabase import create_client
from pipeline.lib.secrets import require
c = create_client(require('SUPABASE_URL'), require('SUPABASE_SECRET_KEY'))
for t in ('reactions', 'clicks', 'notes'):
    n = c.table(t).select('id', count='exact').execute().count
    print(f'{t}: {n}건')
"
```

Expected: 폰에서 누른 좋아요와 클릭이 보인다.

- [ ] **Step 4: 전체 테스트**

Run: `.venv/bin/python -m pytest`
Expected: 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add -A && git commit -m "docs: 계획 2 엔드투엔드 검증 기록" && git push
```

---

## 완료 조건

- [ ] `pytest`가 전부 통과한다
- [ ] 공개 URL을 폰에서 열면 그날 브리핑이 읽힌다
- [ ] `/:date`를 직접 열어도 뜬다 (404 폴백)
- [ ] 없는 날짜는 "그 날짜의 브리핑이 없습니다."가 뜬다
- [ ] 아카이브에 0건인 날도 보인다
- [ ] 0건인 날 화면이 **왜 비었는지**(수집·최고 점수·기준)를 보여준다
- [ ] 모바일 1열 / 태블릿 이상 2열
- [ ] 좋아요를 누르면 `reactions`에 `user_id=NULL`로 들어가고, 새로고침해도 채워져 있다
- [ ] 원문을 클릭하면 `clicks`에 들어간다
- [ ] 메모를 저장하고 새로고침하면 남아 있다
- [ ] 태그를 지우고 저장하면 `notes`에 행이 **하나 더** 쌓인다 (추가 전용)
- [ ] `robots.txt`가 `Disallow: /`이고 HTML에 `noindex`가 있다
- [ ] `docs/assets/`에 **secret 키가 없다** (publishable 키는 있어도 정상)
- [ ] `npm run build`가 `docs/superpowers/`와 `docs/data/`를 **지우지 않는다**
- [ ] `render`만 돌리고 커밋해도 페이지에 새 날짜가 보인다 (파이프라인·프론트 분리)
- [ ] `docs/공개-전-점검.md`가 publishable 키 노출을 기록하고 있다

---

## 다음 계획

**계획 3 (전달과 자동화):** `KakaoSender`·`SlackSender`·`lib/guard`·GitHub Actions.
이 계획이 끝나면 **카톡의 "전체 보기" 버튼이 가리킬 곳이 생긴다** — 그것이
계획 2를 먼저 하는 이유였다.

계획 3에서 메워야 할 구멍은 `README.md`의 "계획 3에서 메워야 할 구멍" 절에 있다
(`runs.input_tokens` 배선, 소스별 `quiet_days`).

### 이 계획에서 의도적으로 하지 않은 것

- **다크 모드** — 라이트 모드만 만든다. 쓰면서 필요하면 추가한다.
- **좋아요 토글** — anon에 DELETE를 주지 않는다. `localStorage`가 기기별로 기억한다.
- **메모 제자리 수정** — anon에 UPDATE를 주지 않는다. 추가 전용으로 쓰고 최신 행을 읽는다.
- **소스 침묵 "N일 연속"** — 여러 날의 `runs`를 봐야 안다. 계획 3의 `lib/guard`가 한다.
- **로그인** — 스펙 7.2가 "좋아요에 추가 인증을 두지 않는다"로 정했다.
  다수 사용자 전환은 설계 2.1에 분석해 뒀고 `user_id` 컬럼만 선반영돼 있다.
