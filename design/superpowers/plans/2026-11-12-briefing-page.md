# 브리핑 웹페이지 구현 계획 (계획 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매일의 브리핑을 폰에서 읽을 수 있는 공개 페이지를 만들고, 좋아요·클릭·메모를 모아 계획 3의 학습 신호를 쌓기 시작한다.

**Architecture:** 한 번 빌드한 SPA가 런타임에 **Supabase를 직접 조회한다.** 파이프라인은 DB에만 쓰므로 페이지와 완전히 분리되고(스펙 6.4의 결정적 이유), 리포지토리에는 매일 아무것도 커밋되지 않는다. 읽기는 익명 공개, 좋아요·메모는 로그인한 사용자만.

**Tech Stack:** Vite + React + TypeScript + Tailwind CSS, Supabase JS 클라이언트 (조회 + Auth), GitHub Pages (`docs/` 서빙)

---

## 개정 이력 (2026-11-13)

초판(2026-11-12)에서 다섯 가지가 바뀌었다. **초판을 읽은 상태라면 이 절만 읽고 넘어가면 된다.**

| 바뀐 것 | 초판 | 개정판 | 이유 |
|---|---|---|---|
| 데이터 경로 | `render`가 `docs/data/*.json`을 생성 → 페이지가 fetch | **페이지가 Supabase를 직접 조회** | 공개 리포에 기사 데이터를 매일 영구 축적하지 않는다. 읽기·쓰기 클라이언트가 하나로 모인다 |
| `pipeline/render.py` | Task 2 (약 490줄) | **삭제** | 위의 결과 |
| 인증 | 없음 (`localStorage` 좋아요) | **읽기 공개 + 쓰기 로그인** | 좋아요 토글·기기 간 동일 표시가 가능해지고, 낯선 사람의 신호 오염이 닫힌다 |
| 리포지토리 공개 | Task 1에서 전환 | **완료** (2026-11-13) | `design/공개-전-점검.md` 참조 |
| `docs/`의 설계 문서 | 그대로 둠 | **`design/`으로 옮긴다** (Task 1) | `docs/`가 웹 루트라 설계·계획 문서가 웹에서 열렸다 |

초판에서 **그대로 남은 것**: 목업에서 확정한 색·글꼴·카드 구조(A 톤), Task 4(디자인 토큰), Task 6(카드), Task 7(오늘 화면), Task 8(아카이브), Task 9(라우팅). 네 태스크는 `fetchDay`·`fetchArchive`·`fetchLatest`·`NotFound`와 `Day`·`Archive` 타입만 쓰므로 **구현이 바뀌어도 한 글자도 바뀌지 않는다.** 그게 Task 5를 그 이름으로 유지하는 이유다.

---

## 결정 사항

| 항목 | 결정 | 근거 |
|---|---|---|
| 데이터 조회 | **브라우저가 Supabase 직접 조회** | 아래 "제약 1" |
| 배포 | **GitHub Pages, `docs/` 서빙** | 매일 push할 것이 없으므로 배포는 코드가 바뀔 때만 일어난다. 외부 서비스가 필요 없다 |
| 리포지토리 | **공개** (2026-11-13 전환 완료) | 스펙 7.2의 원안 |
| 인증 | **읽기 익명 공개 + 쓰기 로그인** | 아래 "제약 3" |
| 다크 모드 | **라이트 모드만** | 쓰면서 필요하면 추가. 지금 CSS를 두 벌 만들지 않는다 |
| 톤 | **A 톤** (조용한 읽기 도구) | 목업 아트보드 7개에서 확정 |
| 사용자별 브리핑 | **하지 않는다** | 설계 2.1 — "비용이 아니라 근거가 없기 때문이다. 외부 사용자가 실제로 무엇에 반응하는지를 보고 정해야 한다." 사용자가 0명인 지금 설계하면 틀린다 |

---

## 계획 1에서 확인한 제약 — 이 계획이 반드시 지켜야 하는 것

### 1. 페이지는 Supabase `articles`를 직접 조회한다

`articles`가 페이지에 필요한 것을 모두 갖고 있다: `id`, `briefing_date`, `url`, `source`, `published_at`, `headline`, `bullets`, `why_it_matters`, `topic`, `score`.

**`articles` 테이블에 본문 컬럼이 아예 없다.** 본문은 `article_bodies`에 따로 있고 anon에 권한이 없다(`verify_anon_access.sh`로 실측). 그래서 **요구사항 D3·D2가 구조적으로 보장된다** — 페이지로 본문이 갈 경로가 없다.

**스펙 6.4와의 관계.** 6.4는 "매일 SPA 전체를 다시 빌드한다"와 "SPA는 한 번 빌드하고 런타임에 불러온다"를 비교해 후자를 택했다. 결정적 이유는 **파이프라인과 프론트엔드의 분리**였다 — "매일 빌드하면 오늘 브리핑을 보내는 일이 React 빌드가 성공하는 일에 묶여서, `package.json` 의존성 하나가 깨지면 카톡이 오지 않는다." 직접 조회는 그 분리를 **더 강하게** 지킨다: 파이프라인이 DB에 쓰면 끝이고, 페이지 쪽에서 일어나는 일이 없다. 6.4가 경로를 `docs/data/`로 적은 것은 당시 "Supabase 직접 조회"를 선택지로 올리지 않았기 때문이고, 그 비교는 이 개정판에서 했다.

### 2. 0건인 날은 `runs`가 유일한 출처다 — `briefing_date` 컬럼이 필요하다

0건인 날은 `articles` 행이 **하나도 없다**(`summarize`의 `SCORE_THRESHOLD = 60`을 넘은 글만 저장된다). 그래서 `articles`만 조회하면:

- 그 날짜가 아카이브에 **아예 나타나지 않는다**
- `/2026-11-13`을 직접 열면 "그 날짜의 브리핑이 없습니다"가 떠서 **파이프라인이 안 돈 것과 구별되지 않는다**

요구사항 D8이 `runs.considered_count`·`max_score`를 기록해 둔 것이 정확히 이것을 위해서다(ERD 4.2). 그런데 **`runs`에 날짜 컬럼이 없다** — `window_start`/`window_end`/`sent_at`만 있고, 브리핑 날짜는 KST 변환으로만 얻는다. 브라우저 쿼리에 타임존 변환을 넣으면 인덱스를 못 타고, 경계에서 조용히 틀린다.

**그래서 Task 2가 `runs.briefing_date`를 추가한다. 이것은 계획 1의 완료된 스키마와 `notify`를 고치는 일이다** — 이 계획에서 유일하게 계획 1을 건드리는 부분이고, 의도적이다. 대안(수치 없이 "글이 없습니다"만 띄우기)은 D8이 데이터를 남긴 이유를 버리는 것이고, 더 나쁘게는 Task 7이 이미 `day.collected ?? 0`으로 폴백하므로 **"수집 0건"이라고 거짓말하는 화면**이 된다.

### 3. 인증 — 읽기는 익명 공개, 쓰기는 로그인

설계 2.1이 로그인을 반대한 근거는 이것이었다.

> 1인이 자기 사이트에 로그인하는 것은 순손실이다. 아침에 카톡 링크를 탭했는데 로그인 화면이 뜨면 그 시스템은 쓰이지 않는다.

**읽기와 쓰기를 나누면 이 근거가 사라진다.** 아침에 카톡 링크를 탭하면 로그인 화면 없이 바로 읽힌다. 좋아요·메모를 누를 때만 로그인하고, 그것도 기기당 최초 1회다(Supabase 세션이 자동 갱신된다).

이것이 설계 2.1이 그린 형태와 같다 — "정보는 모두에게 공개하고, 알림은 로그인한 권한자에게만."

**얻는 것.** `auth.uid() = user_id` RLS는 남의 행을 보이지 않게 하므로 SELECT·DELETE를 안전하게 줄 수 있다.

| | 초판 (익명) | 개정판 (인증) |
|---|---|---|
| 좋아요 토글 | 불가 → `localStorage` | **목업대로 토글** |
| 기기 간 동일 표시 | 안 됨 | **됨** |
| 신호 오염 | 낯선 사람 클릭이 섞임 (스펙 7.2가 수용) | **원천 차단** — anon INSERT 정책을 없앤다 |
| 보안 근거 | "아무도 모르는 URL" | **RLS** |

마지막 줄이 ERD 3.2.1이 걱정한 것을 닫는다 — "Phase 2가 '내 좋아요'로 큐레이션을 학습하는데, 지금은 누구나 좋아요를 누를 수 있어 낯선 사람의 클릭이 내 기준을 바꾼다."

**메모는 추가 전용을 유지한다.** UPDATE를 주지 않는다 — 추가 전용이 화면에서 제자리 수정과 구별되지 않으면서 수정 이력을 남긴다. 읽을 때 그 글의 가장 최근 행을 쓴다.

**`user_id` 컬럼은 이미 있다.** `reactions`·`clicks`·`notes`에 `user_id uuid references auth.users(id)`와 인덱스가 들어가 있고, anon INSERT 정책이 `with check (user_id is null)`로 좁혀져 있다(위장 삽입 차단). 설계 2.1이 "나중에 추가하면 중간, 지금 하면 낮음 → 이것만 지금 했다"로 미리 처리한 항목이다. **마이그레이션이 없다.**

### 4. `reason` 컬럼이 지금 이미 노출돼 있다

`articles.reason`은 LLM의 판단 근거다. 페이지에 쓰지 않는다. 그런데 **anon에 테이블 통째로 `grant select`가 걸려 있어서 API로 `?select=reason`을 부르면 읽힌다.** 초판의 `PAGE_FIELDS` 화이트리스트는 화면 표시만 막고 있었다.

Task 2가 **컬럼 단위 grant**로 닫는다. Postgres가 컬럼 단위 `grant select (…)`를 지원하므로 뷰를 만들 필요가 없다. 이것은 직접 조회로 가면서 생기는 비용이 아니라 **지금 있는 노출을 막는 것**이고, 어느 방식을 택해도 해야 한다.

### 5. `docs/`가 웹 루트다 — 설계 문서를 옮긴다

GitHub Pages 브랜치 배포는 루트를 `/` 또는 `/docs`만 허용한다. 그런데 `docs/`에 설계·계획 문서가 들어 있어서, 브리핑 URL을 아는 사람이 **웹에서 그것들을 열 수 있다.**

```
https://predevho.github.io/topic-briefing/superpowers/specs/2026-11-11-erd.md
https://predevho.github.io/topic-briefing/공개-전-점검.md
```

`robots.txt`는 크롤링을 막지 크롤러 아닌 접근을 막지 못한다. Task 1이 `design/`으로 옮긴다.

### 6. Vite의 `emptyOutDir`를 반드시 끈다

빌드 결과가 `docs/`로 들어가는데 거기에 `docs/.nojekyll`·`docs/robots.txt`·`docs/404.html`이 같이 있다. 기본값(`true`)이면 **빌드가 그것들을 지우고** 사이트가 조용히 깨진다. 설계 문서를 옮긴 뒤에도 이 세 파일 때문에 여전히 `false`가 필요하다.

### 7. `.nojekyll`이 필요하다

GitHub Pages는 Jekyll로 처리하면서 `_`로 시작하는 파일을 무시한다. Vite 산출물에 그런 이름이 생길 수 있다.

---

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
| `supabase/migrations/2026-11-13-page-direct-read.sql` | 컬럼 단위 grant, `runs.briefing_date`, 인증 RLS |
| `supabase/schema.sql` | 위를 반영한 현재 스키마 (새 프로젝트가 같은 결과를 얻는다) |
| `supabase/verify_permissions.sql` | 권한 점검 질의 갱신 |
| `pipeline/lib/store.py` | `record_run`에 `briefing_date` 추가 |
| `pipeline/notify.py` | 위를 넘긴다 (이미 스코프에 있다) |
| `web/package.json` | 프론트엔드 의존성 |
| `web/vite.config.ts` | `base`, `outDir: ../docs`, `emptyOutDir: false` |
| `web/index.html` | `noindex` 메타, 글꼴 링크 |
| `web/src/main.tsx` | 엔트리 |
| `web/src/App.tsx` | 라우팅 (`/`, `/:date`, `/archive`) |
| `web/src/lib/types.ts` | 페이지가 쓰는 타입 |
| `web/src/lib/supabase.ts` | 클라이언트 하나 (조회 + Auth + 상호작용) |
| `web/src/lib/data.ts` | `fetchLatest` / `fetchDay` / `fetchArchive` |
| `web/src/lib/auth.ts` | 세션 훅과 로그인·로그아웃 |
| `web/src/components/Card.tsx` | 글 한 건 |
| `web/src/components/LikeButton.tsx` | 좋아요 토글 |
| `web/src/components/Note.tsx` | 메모·태그 |
| `web/src/components/SignIn.tsx` | 로그인 (쓰기를 누를 때만 뜬다) |
| `web/src/components/Today.tsx` | 오늘 화면 (0건 포함) |
| `web/src/components/Archive.tsx` | 날짜 아카이브 |
| `docs/robots.txt` | 색인 차단 |
| `docs/.nojekyll` | Jekyll 처리 끄기 |
| `docs/404.html` | SPA 라우팅 폴백 |
| `design/` | **설계·계획 문서** (Task 1에서 `docs/`에서 옮긴다) |

**삭제되는 것:** `pipeline/render.py`, `tests/test_render.py`, `docs/data/`, `web/src/lib/liked.ts` — 초판에 있었고 이 개정판에서는 만들지 않는다.

---

## 요구사항 커버리지

| 요구사항 | 내용 | 태스크 |
|---|---|---|
| O9 | 웹페이지: 오늘자 + 날짜별 아카이브 | Task 7 (오늘), Task 8 (아카이브) |
| O10 | 모바일 1열 / 태블릿 이상 2열 | Task 7 (`md:grid-cols-2`), Task 14 Step 4 (실제 확인) |
| O11 | 파이프라인과 프론트엔드 분리 | **Task 5** — 페이지가 Supabase를 직접 조회하므로 파이프라인은 DB에만 쓴다. **Task 15 Step 1이 분리를 검증한다** (빌드·커밋 없이 DB에 행을 넣어 새 날짜가 보이는지) |
| O12 | GitHub Pages SPA 라우팅 (`404.html` 폴백) | Task 9 |
| O13 | 좋아요·클릭·메모 저장 | Task 11 (좋아요·클릭), Task 12 (메모·태그) |
| O14 | accent는 상호작용에만 | Task 4 (토큰 주석) — 쓰는 곳은 `LikeButton`, 메모 저장·열기 버튼, 로그인 버튼, 에러 화면의 링크뿐 |
| D2 | 본문은 공개되지 않는다 | **구조적**: `article_bodies`에 anon·authenticated 권한이 없다. Task 2 Step 6이 재검증한다 |
| D3 | 본문은 리포지토리에 커밋되지 않는다 | **구조적으로 더 강해졌다**: 리포지토리에 기사 데이터를 **아무것도** 커밋하지 않는다. `docs/data/`가 없다 |
| D4 | 검색 색인 차단 (`robots.txt` + `noindex`) | Task 3 (메타 태그), Task 13 (`robots.txt`) |
| D8 | 0건인 날의 후보 수·최고 점수를 남긴다 | **Task 2**가 `runs.briefing_date`를 추가해 페이지가 이 데이터에 도달하게 한다. Task 7이 표시한다 |

> **요구사항 문서를 함께 갱신한다.** O11의 문구가 "SPA + JSON 런타임 로딩"이고 검증이 "JSON만 커밋해 새 날짜가 보이는지"다. 의도(파이프라인과 프론트 분리)는 그대로지만 수단이 바뀌었으므로 `design/superpowers/specs/2026-11-11-requirements.md`의 O11·O13·D3 행을 Task 15 Step 5에서 고친다.

---

## 실행 순서 주의 — Task 6과 11의 의존

`Card.tsx`(Task 6)가 `LikeButton`(Task 11)과 `Note`(Task 12)를 임포트한다. **Task 6만 끝낸 상태에서는 `npm run build`가 실패한다.**

카드를 먼저 쓴 이유는 그게 두 컴포넌트가 무엇을 받아야 하는지를 정하기 때문이다(`articleId`, `className`). 각 커밋이 빌드되기를 원하면 **Task 11과 12를 Task 6보다 먼저** 하면 된다 — 그 사이에 다른 의존은 없다. 다만 Task 11·12는 Task 10(인증)을 필요로 하므로, 그 경우 순서는 **10 → 11 → 12 → 6 → 7 → 8 → 9**가 된다.

나머지 태스크는 번호대로 하면 각 커밋이 빌드된다.

---

## Task 1: 설계 문서를 `docs/` 밖으로 옮긴다

`docs/`가 GitHub Pages의 웹 루트가 되므로, 거기 있는 설계·계획 문서는 **브리핑 URL을 아는 사람에게 웹에서 열린다.** 배포 전에 옮긴다.

**Files:**
- Move: `design/superpowers/` → `design/superpowers/`
- Move: `design/공개-전-점검.md` → `design/공개-전-점검.md`
- Modify: `README.md`, `design/superpowers/specs/2026-11-10-it-column-automation-design.md`, `design/공개-전-점검.md` (경로 참조)

- [ ] **Step 1: 옮긴다**

```bash
cd "$(git rev-parse --show-toplevel)"
mkdir -p design
git mv design/superpowers design/superpowers
git mv design/공개-전-점검.md design/공개-전-점검.md
```

- [ ] **Step 2: `docs/`에 남은 것을 확인한다**

```bash
git ls-files docs/
```

Expected: **아무것도 나오지 않는다.** 아직 빌드 산출물이 없으므로 `docs/`는 비어 있어야 한다. 무언가 남아 있으면 그것이 웹에 공개될 파일이므로 지금 판단한다.

- [ ] **Step 3: 경로 참조를 고친다**

```bash
cd "$(git rev-parse --show-toplevel)"
git ls-files -z | xargs -0 grep -ln 'design/superpowers\|design/공개-전-점검'
```

나온 파일에서 `design/superpowers` → `design/superpowers`, `design/공개-전-점검` → `design/공개-전-점검`으로 바꾼다.

```bash
git ls-files -z | xargs -0 perl -pi -e 's{design/superpowers}{design/superpowers}g; s{design/공개-전-점검}{design/공개-전-점검}g'
```

> `perl -pi`를 쓰는 이유: BSD `sed -i`는 빈 확장자 인자를 요구해 플랫폼마다 다르고, 한글 경로가 섞이면 zsh에서 따옴표 처리가 까다롭다.

- [ ] **Step 4: 남은 참조가 없는지 확인한다**

```bash
git ls-files -z | xargs -0 grep -n 'design/superpowers\|design/공개-전-점검'
```

Expected: 아무것도 나오지 않는다.

- [ ] **Step 5: 점검 문서에 이 조치를 기록한다**

`design/공개-전-점검.md`의 "3. 검토했고 공개해도 되는 것" 표에 한 줄 추가한다.

```markdown
| 설계·계획 문서 | `design/`에 있다. **`docs/`는 웹 루트이므로 그쪽에 두면 브리핑 URL을 아는 사람이 웹에서 열 수 있다**(2026-11-13 Task 1에서 옮겼다). 리포지토리가 공개이므로 GitHub에서는 보이지만, 그것은 의도한 공개다 |
```

- [ ] **Step 6: 테스트와 커밋**

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -m pytest -q
```

Expected: 396 passed. **문서만 옮겼으므로 하나도 깨지지 않아야 한다.** 깨지면 테스트가 문서 경로를 참조하고 있다는 뜻이므로 그것을 고친다.

```bash
git add -A
git commit -m "refactor: 설계 문서를 design/으로 — docs/는 웹 루트다"
git push origin main
```

---

## Task 2: 스키마 — 컬럼 단위 grant, `runs.briefing_date`, 인증 RLS

이 태스크가 **계획 1의 완료된 스키마와 `record_run`을 고친다.** 이 계획에서 유일하게 그렇게 하는 부분이고, 이유는 "제약 2"와 "제약 4"에 있다.

**Files:**
- Create: `supabase/migrations/2026-11-13-page-direct-read.sql`
- Modify: `supabase/schema.sql`
- Modify: `supabase/verify_permissions.sql`
- Modify: `pipeline/lib/store.py`, `pipeline/notify.py`, `scripts/smoke_supabase.py`
- Modify: `tests/fakes.py`, `tests/test_remote_store.py`
- Test: `tests/test_remote_store.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다 — `briefing_date`를 받는다**

`tests/test_remote_store.py`에 추가한다.

```python
def test_실행_이력에_브리핑_날짜를_남긴다():
    """0건인 날은 articles 행이 없으므로 runs가 그 날짜의 유일한 기록이다.
    날짜 컬럼이 없으면 페이지가 "파이프라인이 안 돌았다"와 구별할 수 없다.
    """
    fake = FakeRemoteStore()

    fake.record_run(
        briefing_date="2026-11-13",
        window_start=datetime(2026, 11, 12, 22, 20, tzinfo=timezone.utc),
        window_end=datetime(2026, 11, 13, 22, 20, tzinfo=timezone.utc),
        status="sent",
        sent_at=datetime(2026, 11, 13, 22, 20, tzinfo=timezone.utc),
        collected_count=240,
        considered_count=10,
        max_score=52,
        published_count=0,
        source_counts={"토스_기술블로그": 3},
        input_tokens=42135,
        errors=[],
    )

    assert fake.runs[0]["briefing_date"] == "2026-11-13"
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -m pytest tests/test_remote_store.py::test_실행_이력에_브리핑_날짜를_남긴다 -v
```

Expected: FAIL — `TypeError: record_run() got an unexpected keyword argument 'briefing_date'`

- [ ] **Step 3: `record_run`에 `briefing_date`를 더한다**

`pipeline/lib/store.py`의 **두 곳**(`RemoteStore` 프로토콜과 `SupabaseStore` 구현)에서 `record_run`의 시그니처 첫 키워드로 넣는다.

```python
    def record_run(
        self,
        *,
        # 0건인 날은 articles 행이 없다. 이 컬럼이 그 날짜의 유일한 기록이다.
        briefing_date: str,
        window_start: datetime,
        window_end: datetime,
        status: str,                 # "sent" | "failed"
        sent_at: datetime | None,    # failed면 None
        collected_count: int,
        considered_count: int,
        max_score: int | None,
        published_count: int,
        source_counts: dict[str, int],
        input_tokens: int | None,
        errors: list[dict],
    ) -> None:
```

`SupabaseStore` 구현의 삽입 페이로드에도 넣는다.

```python
            "briefing_date": briefing_date,
```

- [ ] **Step 4: 호출하는 네 곳을 고친다**

```bash
cd "$(git rev-parse --show-toplevel)"
grep -rn 'record_run' pipeline/ scripts/ tests/
```

- `pipeline/notify.py:60` — `briefing_date`가 **이미 함수 스코프에 있다**(43행). `briefing_date=briefing_date,`를 더하면 끝이다.
- `scripts/smoke_supabase.py:61` — 스모크 스크립트. 날짜 문자열을 넘긴다.
- `tests/fakes.py:36` — 가짜 구현. 시그니처를 맞추고 `briefing_date`를 기록한다.
- `tests/test_remote_store.py:29,50` — 기존 호출 두 곳에 인자를 더한다.

- [ ] **Step 5: 통과를 확인한다**

```bash
.venv/bin/python -m pytest -q
```

Expected: 397 passed (기존 396 + 새 1건)

- [ ] **Step 6: 마이그레이션 SQL**

`supabase/migrations/2026-11-13-page-direct-read.sql`:

```sql
-- 페이지가 Supabase를 직접 조회하도록 권한을 다시 그린다 (계획 2).
--
-- 바뀌는 것 세 가지:
--   1) runs.briefing_date — 0건인 날을 날짜로 찾을 키
--   2) articles/runs에 **컬럼 단위** SELECT — reason과 errors를 내보내지 않는다
--   3) 쓰기는 authenticated만 — anon의 reactions/notes 쓰기를 거둔다
--
-- 멱등하게 쓴다. 여러 번 돌려도 같은 결과여야 한다.

-- ---------------------------------------------------------------
-- 1) runs.briefing_date
-- ---------------------------------------------------------------

alter table public.runs add column if not exists briefing_date date;

-- 기존 행 채우기. sent_at이 없으면(failed) window_end를 쓴다.
-- KST로 변환하는 이유: 브리핑 날짜는 사람이 읽는 날짜다.
update public.runs
   set briefing_date = (coalesce(sent_at, window_end) at time zone 'Asia/Seoul')::date
 where briefing_date is null;

alter table public.runs alter column briefing_date set not null;

-- 아카이브가 최신순으로 읽으므로 desc.
create index if not exists runs_briefing_date_idx
  on public.runs (briefing_date desc);

-- ---------------------------------------------------------------
-- 2) 컬럼 단위 SELECT
-- ---------------------------------------------------------------

-- articles: reason(LLM 판단 근거)을 뺀다. 지금은 테이블 통째로 grant돼 있어
-- ?select=reason으로 읽힌다 — 화면에 안 그려도 API는 열려 있었다.
revoke select on public.articles from anon;

grant select (id, briefing_date, url, source, published_at,
              headline, bullets, why_it_matters, topic, score)
  on public.articles to anon;

-- 로그인한 뒤에도 페이지를 읽는다. authenticated는 anon과 **다른 역할**이므로
-- 따로 주지 않으면 로그인하자마자 화면이 빈다.
grant select (id, briefing_date, url, source, published_at,
              headline, bullets, why_it_matters, topic, score)
  on public.articles to authenticated;

create policy articles_auth_read on public.articles
  for select to authenticated using (true);

-- runs: 0건인 날의 수치만. errors(내부 오류 메시지)·input_tokens·window_*·id는
-- 주지 않는다.
grant select (briefing_date, status, collected_count, considered_count,
              max_score, published_count, source_counts)
  on public.runs to anon, authenticated;

create policy runs_public_read on public.runs
  for select to anon using (status = 'sent');

create policy runs_auth_read on public.runs
  for select to authenticated using (status = 'sent');

-- briefing_index: 아카이브 화면용. **날짜당 한 행**을 준다.
--
-- 이게 없으면 아카이브가 기사 전체를 받아 브라우저에서 집계해야 하고,
-- PostgREST의 기본 상한(1000행)에 조용히 걸린다. 날짜당 한 행이면 5년이
-- 지나도 2천 행 아래다.
--
-- security_invoker = true: 뷰가 **호출자의 권한으로** 돈다. 그래서 위에서
-- 준 컬럼 grant와 RLS가 그대로 적용된다. false(기본값, definer)로 두면
-- RLS를 우회하므로 쓰지 않는다.
create or replace view public.briefing_index
  with (security_invoker = true) as
select
  briefing_date,
  count(*)::int                                     as count,
  -- 그 날짜의 최고 점수 헤드라인. 아카이브가 "<lead> 외 N건"으로 그린다.
  (array_agg(headline order by score desc))[1]      as lead
from public.articles
group by briefing_date;

grant select on public.briefing_index to anon, authenticated;

-- ---------------------------------------------------------------
-- 3) 쓰기는 로그인한 사용자만
-- ---------------------------------------------------------------

-- reactions: anon INSERT를 거둔다. ERD 3.2.1이 걱정한 "낯선 사람의 클릭이
-- 내 기준을 바꾼다"가 여기서 닫힌다.
drop policy if exists reactions_public_insert on public.reactions;
revoke insert on public.reactions from anon;

grant select, insert, delete on public.reactions to authenticated;

-- (select auth.uid())로 감싸는 이유: 행마다 재평가되지 않고 한 번만 계산된다.
create policy reactions_own_read on public.reactions
  for select to authenticated using ((select auth.uid()) = user_id);
create policy reactions_own_insert on public.reactions
  for insert to authenticated with check ((select auth.uid()) = user_id);
-- DELETE는 먼저 SELECT로 행을 찾는다. 위의 read 정책이 그것을 받친다.
create policy reactions_own_delete on public.reactions
  for delete to authenticated using ((select auth.uid()) = user_id);

-- notes: 추가 전용을 유지한다. UPDATE·DELETE를 주지 않으므로 수정 이력이 남고,
-- 화면에서는 가장 최근 행을 읽어 제자리 수정처럼 보인다.
drop policy if exists notes_public_read on public.notes;
drop policy if exists notes_public_insert on public.notes;
revoke select, insert on public.notes from anon;

grant select, insert on public.notes to authenticated;

create policy notes_own_read on public.notes
  for select to authenticated using ((select auth.uid()) = user_id);
create policy notes_own_insert on public.notes
  for insert to authenticated with check ((select auth.uid()) = user_id);

-- clicks: 로그인 전에도 눌린다. anon INSERT(user_id is null)를 유지하고
-- 로그인 사용자도 자기 id로 넣게 한다.
grant insert on public.clicks to authenticated;
create policy clicks_own_insert on public.clicks
  for insert to authenticated with check ((select auth.uid()) = user_id);
```

- [ ] **Step 7: Supabase에 적용한다**

```bash
cd "$(git rev-parse --show-toplevel)"
# MCP의 execute_sql이나 대시보드 SQL 편집기에 붙여 넣는다.
# supabase CLI가 연결돼 있으면:
#   supabase db query < supabase/migrations/2026-11-13-page-direct-read.sql
cat supabase/migrations/2026-11-13-page-direct-read.sql
```

적용 뒤 어드바이저를 돌린다.

```bash
supabase db advisors   # CLI v2.81.3+. 없으면 MCP get_advisors
```

Expected: 새로운 보안 경고가 없다.

- [ ] **Step 8: `schema.sql`을 현재 상태로 맞춘다**

마이그레이션은 델타이고 `schema.sql`은 **새 프로젝트가 같은 결과를 얻는 원본**이다. 둘이 어긋나면 나중에 재현이 안 된다.

1. `runs` 테이블 정의에 `briefing_date date not null`을 넣는다
2. `runs_briefing_date_idx` 인덱스를 넣는다
3. grant·policy 절을 마이그레이션의 최종 상태로 교체한다
4. 머리말의 경계 설명을 고친다

```sql
--   articles        — 요약·링크. anon/authenticated **컬럼 단위** 읽기 (reason 제외)
--   article_bodies  — 기사 본문. anon·authenticated 접근 전면 차단
--   runs            — 실행 이력. **컬럼 단위** 읽기 (errors·input_tokens 제외)
--   reactions       — authenticated만. 자기 행만 읽기·삽입·삭제
--   clicks          — anon 삽입(user_id null) + authenticated 자기 행 삽입
--   notes           — authenticated만. 자기 행만 읽기·삽입 (추가 전용)
--   kakao_auth      — 토큰. 접근 차단 (계획 3)
```

- [ ] **Step 9: 권한을 실측한다**

`scripts/verify_anon_access.sh`가 "본문이 anon에게 막히는지"를 확인한다(요구사항 D2). 이번 변경으로 확인할 것이 늘었다. 스크립트에 세 가지를 더한다.

```bash
# anon이 reason을 읽을 수 없어야 한다 (컬럼 단위 grant)
curl -s "$SUPABASE_URL/rest/v1/articles?select=reason&limit=1" \
  -H "apikey: $KEY" -H "Authorization: Bearer $KEY" | tee /dev/stderr | grep -q '42501\|permission denied' \
  && echo "✓ reason 차단" || { echo "✗ reason이 읽힌다"; exit 1; }

# anon이 runs의 errors를 읽을 수 없어야 한다
curl -s "$SUPABASE_URL/rest/v1/runs?select=errors&limit=1" \
  -H "apikey: $KEY" -H "Authorization: Bearer $KEY" | grep -q '42501\|permission denied' \
  && echo "✓ runs.errors 차단" || { echo "✗ runs.errors가 읽힌다"; exit 1; }

# anon이 reactions에 삽입할 수 없어야 한다
curl -s -X POST "$SUPABASE_URL/rest/v1/reactions" \
  -H "apikey: $KEY" -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" -d '{"article_id": 1}' \
  | grep -q '42501\|permission denied' \
  && echo "✓ anon 좋아요 차단" || { echo "✗ anon이 좋아요를 넣는다"; exit 1; }
```

- [ ] **Step 10: 커밋**

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -m pytest -q
git add supabase/ pipeline/ scripts/ tests/
git commit -m "feat: 페이지 직접 조회용 권한 — 컬럼 grant, runs.briefing_date, 인증 RLS"
git push origin main
```

---

## Task 3: 프론트엔드 스캐폴드

**Files:**
- Create: `web/` (Vite 스캐폴드)
- Create: `web/vite.config.ts`, `web/.env.local`, `web/.env.example`
- Create: `docs/.nojekyll`
- Modify: `web/index.html`, `.gitignore`

> **빌드된 JS에 Supabase URL과 publishable 키가 들어간다.** 공개 리포에서는 둘 다 공개되고, 공개 사이트에서도 보인다.
>
> 설계상 괜찮다 — 스펙 7.2가 "publishable 키는 비밀이 아니다. 브라우저에 노출되도록 설계된 키다"라고 정했고, RLS가 실제 방어다(Task 2 Step 9에서 실측). **secret 키는 들어가지 않는다** — Vite는 `VITE_` 접두사가 붙은 변수만 클라이언트에 넣고, `SUPABASE_SECRET_KEY`에는 접두사가 없다.

- [ ] **Step 1: Vite + React + TypeScript 스캐폴드**

```bash
cd "$(git rev-parse --show-toplevel)"
npm create vite@latest web -- --template react-ts
cd web && npm install
```

- [ ] **Step 2: Tailwind와 Supabase 클라이언트 설치**

```bash
cd web
npm install tailwindcss @tailwindcss/vite
npm install @supabase/supabase-js
```

- [ ] **Step 3: 해결된 버전을 기록한다**

```bash
cd web
npm ls --depth=0
```

출력된 버전을 이 계획 문서의 이 자리에 적어 둔다. **락파일을 커밋하므로** 나중에 "무엇이 깨졌나"를 추적할 수 있다.

- [ ] **Step 4: `web/vite.config.ts`**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],

  // GitHub Pages 프로젝트 사이트는 /<repo>/ 하위에 올라간다.
  // 이 값이 틀리면 JS·CSS 경로가 404가 되어 빈 화면이 뜬다.
  base: '/topic-briefing/',

  build: {
    // GitHub Pages가 docs/를 서빙한다.
    outDir: '../docs',

    // **반드시 false다.** docs/에 .nojekyll, robots.txt, 404.html이 같이
    // 있는데 기본값(true)이면 빌드가 그것들을 지우고 사이트가 조용히 깨진다.
    emptyOutDir: false,
  },
})
```

- [ ] **Step 5: 환경 변수**

`web/.env.example` (커밋한다):

```
# 브라우저용 publishable 키. 비밀이 아니다 — 빌드된 JS에 그대로 들어간다.
# 실제 방어는 RLS다(supabase/migrations/2026-11-13-page-direct-read.sql).
VITE_SUPABASE_URL=https://xxxxx.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```

`web/.env.local` (커밋하지 않는다): 루트 `.env`의 같은 값을 넣는다.

```bash
cd "$(git rev-parse --show-toplevel)"
grep -E '^(SUPABASE_URL|VITE_SUPABASE_PUBLISHABLE_KEY)=' .env \
  | sed 's/^SUPABASE_URL=/VITE_SUPABASE_URL=/' > web/.env.local
cat web/.env.local
```

- [ ] **Step 6: `web/index.html` — 색인 차단과 글꼴**

`<head>`에 넣는다. 요구사항 D4의 절반이다(나머지는 Task 13의 `robots.txt`).

```html
    <meta name="robots" content="noindex, nofollow" />
    <title>브리핑</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600&family=Inter:wght@400;500&display=swap"
      rel="stylesheet"
    />
```

- [ ] **Step 7: `docs/.nojekyll`**

```bash
cd "$(git rev-parse --show-toplevel)"
touch docs/.nojekyll
```

GitHub Pages는 기본적으로 Jekyll로 처리하면서 `_`로 시작하는 파일·디렉터리를 무시한다. Vite 산출물에 그런 이름이 생기면 조용히 404가 된다.

- [ ] **Step 8: `.gitignore`**

```
# Node
node_modules/
web/dist/
web/.env.local
```

**`docs/`는 넣지 않는다** — 빌드 결과를 커밋해야 Pages가 서빙한다. 다만 **코드가 바뀔 때만** 커밋한다(스펙 6.4). 매일 커밋할 것은 없다.

- [ ] **Step 9: 빌드가 `docs/`의 설정 파일을 지우지 않는지 확인**

이게 이 태스크에서 가장 중요한 검증이다.

```bash
cd "$(git rev-parse --show-toplevel)"
ls -a docs/            # .nojekyll 이 있어야 한다
cd web && npm run build
cd .. && ls -a docs/   # .nojekyll 이 **그대로 있어야 한다** + index.html, assets/
```

Expected: `.nojekyll`이 살아 있다. 사라졌으면 `emptyOutDir: false`가 안 들어간 것이다.

- [ ] **Step 10: 커밋**

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
rm web/src/App.css
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

## Task 5: Supabase 클라이언트와 데이터 조회

**이 태스크가 초판의 Task 2(`render`)와 Task 5를 대체한다.** 함수 이름(`fetchLatest`·`fetchDay`·`fetchArchive`·`NotFound`)과 타입 모양(`Day`·`Archive`·`Article`·`ArchiveEntry`)을 **초판과 똑같이 유지한다** — Task 6~9가 그것만 쓰므로, 구현을 바꿔도 그 네 태스크는 한 글자도 바뀌지 않는다.

**Files:**
- Create: `web/src/lib/types.ts`
- Create: `web/src/lib/supabase.ts`
- Create: `web/src/lib/data.ts`

- [ ] **Step 1: `web/src/lib/types.ts`**

```typescript
// Supabase articles 테이블의 **페이지가 읽는 컬럼**과 1:1.
// reason은 없다 — 마이그레이션이 컬럼 단위 grant로 막았고, 넣으면 쿼리가 실패한다.
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
  // runs 행에서 온다. 0건인 날에도 실행 기록은 있으므로 수치가 채워진다.
  // 그 행조차 없으면 그 날짜는 존재하지 않는 것이고 fetchDay가 NotFound를 던진다.
  collected: number | null
  considered: number | null
  max_score: number | null
  threshold: number
  source_counts: Record<string, number>
}

export type ArchiveEntry = {
  date: string
  count: number
  // count > 0이면 **반드시 문자열이다.** Archive 화면이 `${lead} 외 N건`으로
  // 그대로 그리므로, null이 들어오면 화면에 "null"이 보인다.
  lead: string | null
}

export type Archive = {
  dates: ArchiveEntry[]
  days: number
  total: number
}
```

- [ ] **Step 2: `web/src/lib/supabase.ts`**

```typescript
import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

// 빈 값으로 클라이언트를 만들면 첫 질의에서 "Failed to fetch"만 나와서
// 원인을 찾기 어렵다. 여기서 바로 멈추고 이유를 말한다.
if (!url || !key) {
  throw new Error(
    'VITE_SUPABASE_URL / VITE_SUPABASE_PUBLISHABLE_KEY가 비어 있다. ' +
      'web/.env.local을 확인한다 (web/.env.example 참고).',
  )
}

export const supabase = createClient(url, key, {
  auth: {
    // 기기당 로그인 1회. 세션을 localStorage에 두고 토큰을 자동 갱신한다.
    persistSession: true,
    autoRefreshToken: true,
    // URL 해시로 돌아오는 매직링크·OAuth 콜백을 자동으로 처리한다.
    detectSessionInUrl: true,
  },
})
```

- [ ] **Step 3: `web/src/lib/data.ts`**

```typescript
import { supabase } from './supabase'
import type { Archive, ArchiveEntry, Article, Day } from './types'

// pipeline/summarize.py의 SCORE_THRESHOLD와 같은 값이다. **두 곳에 있다** —
// 파이프라인에서 바꾸면 여기도 바꾼다. 화면의 "기준 60점" 표시에만 쓰이므로
// 어긋나도 선별 동작은 바뀌지 않지만, 표시가 거짓이 된다.
export const THRESHOLD = 60

// articles에서 읽는 컬럼. reason을 넣으면 컬럼 단위 grant 때문에 쿼리가 실패한다.
const ARTICLE_COLUMNS =
  'id, url, source, published_at, headline, bullets, why_it_matters, topic, score'

// runs에서 읽는 컬럼. errors·input_tokens·window_*는 grant가 없다.
const RUN_COLUMNS =
  'briefing_date, collected_count, considered_count, max_score, source_counts'

// 아카이브 질의의 상한. 날짜당 한 행이므로 2000이면 5년 넘는다.
// PostgREST의 기본 상한(1000)에 조용히 걸리는 것을 막으려고 명시한다.
const ARCHIVE_LIMIT = 2000

/** 그 날짜에 브리핑이 없다 (실행 기록조차 없다). */
export class NotFound extends Error {}

function fail(context: string, error: { message: string }): never {
  // Supabase 오류를 그대로 던지면 화면에 "JSON object requested..." 같은
  // 내부 문구가 뜬다. 무엇을 하다 실패했는지를 앞에 붙인다.
  throw new Error(`${context}: ${error.message}`)
}

export async function fetchDay(date: string): Promise<Day> {
  // 두 질의를 동시에 보낸다. 직렬이면 왕복이 두 배다.
  const [articles, runs] = await Promise.all([
    supabase
      .from('articles')
      .select(ARTICLE_COLUMNS)
      .eq('briefing_date', date)
      .order('score', { ascending: false }),
    // maybeSingle()을 쓰지 않는다 — 같은 날짜에 행이 둘이면 **던진다.**
    // notify의 AlreadySent 가드가 그걸 막지만, 화면이 그 가드에 의존할 이유가 없다.
    supabase
      .from('runs')
      .select(RUN_COLUMNS)
      .eq('briefing_date', date)
      .limit(1),
  ])

  if (articles.error) fail(`${date}의 글을 읽지 못했다`, articles.error)
  if (runs.error) fail(`${date}의 실행 기록을 읽지 못했다`, runs.error)

  const run = runs.data?.[0] ?? null
  const rows = (articles.data ?? []) as Article[]

  // **이 줄이 "0건인 날"과 "없는 날짜"를 구별한다.**
  // 실행 기록이 있으면 파이프라인이 돌았고 기준을 넘긴 글이 없었던 것이다.
  // 둘 다 없으면 그 날짜는 존재하지 않는다.
  if (rows.length === 0 && run === null) throw new NotFound(date)

  return {
    date,
    articles: rows,
    collected: run?.collected_count ?? null,
    considered: run?.considered_count ?? null,
    max_score: run?.max_score ?? null,
    threshold: THRESHOLD,
    source_counts: run?.source_counts ?? {},
  }
}

export async function fetchArchive(): Promise<Archive> {
  // briefing_index는 날짜당 한 행(건수 + 최고점 헤드라인)을 주는 뷰다.
  // runs는 **0건인 날까지** 포함한 전체 날짜 목록이다. 둘을 합쳐야
  // "조용했던 날"이 아카이브에서 사라지지 않는다.
  const [index, runs] = await Promise.all([
    supabase
      .from('briefing_index')
      .select('briefing_date, count, lead')
      .order('briefing_date', { ascending: false })
      .limit(ARCHIVE_LIMIT),
    supabase
      .from('runs')
      .select('briefing_date')
      .order('briefing_date', { ascending: false })
      .limit(ARCHIVE_LIMIT),
  ])

  if (index.error) fail('아카이브 목록을 읽지 못했다', index.error)
  if (runs.error) fail('실행 날짜를 읽지 못했다', runs.error)

  const byDate = new Map<string, { count: number; lead: string | null }>()
  for (const row of index.data ?? []) {
    byDate.set(row.briefing_date as string, {
      count: row.count as number,
      lead: row.lead as string | null,
    })
  }

  // runs의 날짜가 기준이다. 글이 있는 날은 뷰에서 건수와 헤드라인을 가져오고,
  // 없는 날은 count 0으로 남는다.
  const dates: ArchiveEntry[] = (runs.data ?? []).map((row) => {
    const date = row.briefing_date as string
    const hit = byDate.get(date)
    return { date, count: hit?.count ?? 0, lead: hit?.lead ?? null }
  })

  return {
    dates,
    days: dates.length,
    total: dates.reduce((sum, entry) => sum + entry.count, 0),
  }
}

/** 최신 브리핑. 아카이브 전체를 받지 않고 날짜 하나만 찾는다. */
export async function fetchLatest(): Promise<Day> {
  const { data, error } = await supabase
    .from('runs')
    .select('briefing_date')
    .order('briefing_date', { ascending: false })
    .limit(1)

  if (error) fail('최신 브리핑 날짜를 읽지 못했다', error)

  const latest = data?.[0]?.briefing_date as string | undefined
  if (!latest) throw new NotFound('아직 발행한 브리핑이 없다')

  return fetchDay(latest)
}
```

- [ ] **Step 4: 실제 데이터로 확인한다**

이 태스크는 단위 테스트를 두지 않는다 — 검증 가치가 전부 **실제 권한과 실제 행**에 있고, Supabase 클라이언트를 모킹하면 컬럼 grant가 맞는지를 확인할 수 없다. 대신 브라우저 콘솔에서 직접 부른다.

```bash
cd web && npm run dev
```

브라우저 콘솔에서:

```javascript
const { fetchLatest, fetchArchive } = await import('/src/lib/data.ts')
console.log(await fetchLatest())
console.log(await fetchArchive())
```

Expected:

| 확인할 것 | 기대 |
|---|---|
| `fetchLatest()` | `2026-11-12`의 요약 7건. `articles[0].score`가 가장 높다 |
| `collected` / `considered` | `null`이 아니다 — `runs.briefing_date` 마이그레이션이 동작한다는 증거다 |
| `fetchArchive().dates` | 최신순. `lead`가 count > 0인 모든 항목에서 문자열이다 |
| `reason`을 넣어 보기 | `ARTICLE_COLUMNS`에 `reason`을 임시로 더하면 **permission denied(42501)** — 컬럼 grant가 살아 있다는 증거다. 확인 후 되돌린다 |

- [ ] **Step 5: 커밋**

```bash
cd "$(git rev-parse --show-toplevel)"
git add web/src/lib/types.ts web/src/lib/supabase.ts web/src/lib/data.ts
git commit -m "feat: Supabase 직접 조회 — 날짜별 브리핑과 아카이브"
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

- [ ] **Step 2: 커밋** (`LikeButton`은 Task 11, `Note`는 Task 12에서 만든다 — 그때 빌드가 통과한다)

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
import { recordClick } from '../lib/likes'
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

## Task 10: 인증 — 로그인과 세션

읽기는 익명 공개다. **좋아요·메모를 누를 때만** 로그인한다. 아침에 카톡 링크를 탭했을 때 로그인 화면이 뜨면 안 된다(설계 2.1).

**Files:**
- Create: `web/src/lib/auth.ts`
- Create: `web/src/components/SignIn.tsx`

- [ ] **Step 1: Supabase 대시보드에서 가입을 막고 사용자를 하나 만든다** (직접)

이 단계는 대시보드에서 직접 한다. **공개 가입을 열어 두면 아무나 계정을 만들어 좋아요를 넣을 수 있고**, 그건 anon INSERT를 거둔 이유를 무효로 만든다.

1. Authentication → Sign In / Providers → **Email**을 켠다
2. 같은 화면에서 **"Allow new users to sign up"을 끈다**
3. Authentication → Users → **Add user**로 본인 계정 하나를 만든다 (이메일 + 비밀번호). 비밀번호는 직접 정한다
4. **Confirm email**을 체크해서 바로 쓸 수 있게 한다

> 나중에 사람을 늘릴 때도 같은 자리에서 계정을 만들면 된다. RLS가 이미 `auth.uid() = user_id`이므로 코드는 바뀌지 않는다.

- [ ] **Step 2: `web/src/lib/auth.ts`**

```typescript
import { useEffect, useState } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from './supabase'

export function useSession(): { session: Session | null; loading: boolean } {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true

    // 첫 로드: 저장된 세션을 읽는다. 없으면 null이고 그게 정상이다
    // (로그인하지 않아도 페이지는 읽힌다).
    supabase.auth.getSession().then(({ data }) => {
      if (!alive) return
      setSession(data.session)
      setLoading(false)
    })

    // 로그인·로그아웃·토큰 자동 갱신을 구독한다.
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      if (!alive) return
      setSession(next)
      setLoading(false)
    })

    // 구독을 끊지 않으면 컴포넌트가 사라진 뒤에도 setState가 불린다.
    return () => {
      alive = false
      data.subscription.unsubscribe()
    }
  }, [])

  return { session, loading }
}

export async function signIn(email: string, password: string): Promise<void> {
  const { error } = await supabase.auth.signInWithPassword({ email, password })
  // Supabase의 'Invalid login credentials'를 그대로 보여준다 — 어느 쪽이
  // 틀렸는지 알려주지 않는 것이 맞다.
  if (error) throw new Error(error.message)
}

export async function signOut(): Promise<void> {
  await supabase.auth.signOut()
}
```

- [ ] **Step 3: `web/src/components/SignIn.tsx`**

쓰기를 누를 때만 뜨는 작은 폼이다. 전체 화면을 가리지 않는다.

```typescript
import { useState } from 'react'
import { signIn } from '../lib/auth'

type Props = { onDone: () => void; onCancel: () => void }

export default function SignIn({ onDone, onCancel }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(email, password)
      onDone()
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mt-3 rounded-md border border-line bg-panel p-3.5"
    >
      <p className="mb-2.5 text-[12.5px] leading-[1.5] text-muted">
        좋아요와 메모는 기기당 한 번만 로그인하면 됩니다. 읽기는 로그인이
        필요하지 않습니다.
      </p>

      <input
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="이메일"
        autoComplete="username"
        required
        className="mb-2 w-full rounded border border-edge bg-bg px-2.5 py-2 text-[13.5px]"
      />
      <input
        type="password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        placeholder="비밀번호"
        autoComplete="current-password"
        required
        className="mb-2.5 w-full rounded border border-edge bg-bg px-2.5 py-2 text-[13.5px]"
      />

      {error && (
        <p className="mb-2 text-[12.5px] leading-[1.5] text-warn">{error}</p>
      )}

      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-accent px-3 py-1.5 text-[12.5px] font-medium text-white disabled:opacity-50"
        >
          {busy ? '확인 중…' : '로그인'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-[12.5px] text-muted"
        >
          취소
        </button>
      </div>
    </form>
  )
}
```

- [ ] **Step 4: 로그인이 되는지 확인한다**

```bash
cd web && npm run dev
```

브라우저 콘솔에서:

```javascript
const { signIn } = await import('/src/lib/auth.ts')
const { supabase } = await import('/src/lib/supabase.ts')
// 이메일과 비밀번호는 직접 입력한다
await signIn(prompt('이메일'), prompt('비밀번호'))
console.log((await supabase.auth.getSession()).data.session?.user?.id)
```

Expected: uuid가 출력된다. 새로고침한 뒤 다시 `getSession()`을 불러도 같은 값이 나온다 (`persistSession`).

- [ ] **Step 5: 커밋**

```bash
cd "$(git rev-parse --show-toplevel)"
git add web/src/lib/auth.ts web/src/components/SignIn.tsx
git commit -m "feat: 로그인 — 읽기는 익명, 쓰기만 인증"
```

---

## Task 11: 좋아요 — 토글과 클릭 기록

초판은 anon이 INSERT만 가능해서 `localStorage`로 "눌렀는지"를 기억했다. 인증이 생겼으므로 **DB가 기억하고 토글이 된다.**

**Files:**
- Create: `web/src/lib/likes.ts`
- Create: `web/src/components/LikeButton.tsx`

- [ ] **Step 1: `web/src/lib/likes.ts`**

> **모듈 수준 캐시를 쓰는 이유.** 카드가 7장이면 각 `LikeButton`이 "내가 눌렀나"를 따로 물어 질의가 7번 간다. React 컨텍스트로 묶으려면 `App.tsx`에 프로바이더를 넣어야 하는데, `App.tsx`는 Task 9에서 쓰고 더 고치지 않는다. 모듈 수준 캐시가 프로바이더 없이 같은 일을 한다.

```typescript
import { supabase } from './supabase'

// 내가 좋아요한 article_id 집합. 로그인 상태에서 한 번만 받아 공유한다.
// RLS가 auth.uid() = user_id로 좁히므로 **내 행만** 온다.
let cache: Promise<Set<number>> | null = null

// 집합이 바뀔 때 다시 그릴 컴포넌트들.
const listeners = new Set<() => void>()

function announce(): void {
  for (const notify of listeners) notify()
}

export function subscribe(notify: () => void): () => void {
  listeners.add(notify)
  return () => listeners.delete(notify)
}

/** 로그아웃·로그인 시 캐시를 버린다. 사용자가 바뀌면 집합도 달라진다. */
export function resetLikes(): void {
  cache = null
  announce()
}

export function loadLikes(): Promise<Set<number>> {
  if (cache) return cache
  cache = (async () => {
    const { data, error } = await supabase.from('reactions').select('article_id')
    // 로그인하지 않았으면 권한이 없어 오류가 난다. 그건 정상이므로
    // 빈 집합으로 둔다 — 하트가 전부 빈 상태로 그려진다.
    if (error) return new Set<number>()
    return new Set<number>((data ?? []).map((row) => row.article_id as number))
  })()
  return cache
}

/**
 * 좋아요를 뒤집는다. 돌려주는 값은 **뒤집은 뒤의 상태**다.
 * 로그인하지 않았으면 호출하지 않는다 (버튼이 먼저 로그인을 띄운다).
 */
export async function toggleLike(
  articleId: number,
  userId: string,
): Promise<boolean> {
  const liked = await loadLikes()

  if (liked.has(articleId)) {
    const { error } = await supabase
      .from('reactions')
      .delete()
      .eq('article_id', articleId)
    if (error) throw new Error(`좋아요를 지우지 못했다: ${error.message}`)
    liked.delete(articleId)
    announce()
    return false
  }

  // user_id를 **명시해서** 넣는다. RLS의 with check가 auth.uid() = user_id를
  // 요구하므로 빼면 거부된다.
  const { error } = await supabase
    .from('reactions')
    .insert({ article_id: articleId, user_id: userId })
  if (error) throw new Error(`좋아요를 넣지 못했다: ${error.message}`)
  liked.add(articleId)
  announce()
  return true
}

/**
 * 원문 링크 클릭을 기록한다. 실패해도 조용히 넘긴다 — 클릭 신호 하나보다
 * 링크가 열리는 것이 중요하다.
 *
 * **인자는 articleId 하나다.** 세션은 안에서 읽는다 — 호출하는 쪽(Card)이
 * 로그인 상태를 알 필요가 없고, 로그인 전에도 클릭은 기록되어야 한다
 * (anon의 clicks INSERT 정책이 user_id null을 받는다).
 *
 * sendBeacon을 쓰지 않는 이유: 헤더를 설정할 수 없고 Supabase REST는
 * apikey/Authorization을 요구한다.
 */
export function recordClick(articleId: number): void {
  void (async () => {
    const { data } = await supabase.auth.getSession()
    await supabase.from('clicks').insert({
      article_id: articleId,
      // 로그인했으면 내 id, 아니면 null. RLS가 두 경로를 각각 허용한다.
      user_id: data.session?.user?.id ?? null,
    })
  })().catch(() => undefined)
}
```

- [ ] **Step 2: `web/src/components/LikeButton.tsx`**

```typescript
import { useEffect, useState } from 'react'
import { useSession } from '../lib/auth'
import { loadLikes, subscribe, toggleLike } from '../lib/likes'
import SignIn from './SignIn'

type Props = { articleId: number; className?: string }

export default function LikeButton({ articleId, className = '' }: Props) {
  const { session } = useSession()
  const [liked, setLiked] = useState(false)
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)

  // 집합이 바뀌면(다른 카드에서 눌렀거나 로그인했을 때) 다시 읽는다.
  useEffect(() => {
    let alive = true
    const read = () => {
      void loadLikes().then((set) => {
        if (alive) setLiked(set.has(articleId))
      })
    }
    read()
    const stop = subscribe(read)
    return () => {
      alive = false
      stop()
    }
  }, [articleId, session])

  async function press() {
    // 로그인하지 않았으면 누른 자리에서 폼을 띄운다. 페이지를 가리지 않는다.
    if (!session) {
      setAsking(true)
      return
    }
    setBusy(true)
    try {
      setLiked(await toggleLike(articleId, session.user.id))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={press}
        disabled={busy}
        aria-pressed={liked}
        aria-label={liked ? '좋아요 취소' : '좋아요'}
        // 44×44: 손가락 터치 목표 크기 (목업).
        className={`flex h-11 w-11 items-center justify-center disabled:opacity-50 ${className}`}
      >
        <svg
          viewBox="0 0 24 24"
          className="h-[18px] w-[18px]"
          fill={liked ? 'currentColor' : 'none'}
          stroke="currentColor"
          strokeWidth="1.6"
          // accent는 상호작용에만 쓴다 (요구사항 O14).
          style={{ color: liked ? 'var(--color-accent)' : 'var(--color-muted)' }}
        >
          <path d="M12 20.2l-1.4-1.3C6 14.8 3.4 12.4 3.4 9.3 3.4 6.9 5.3 5 7.7 5c1.4 0 2.7.6 3.5 1.7l.8 1 .8-1C13.6 5.6 14.9 5 16.3 5 18.7 5 20.6 6.9 20.6 9.3c0 3.1-2.6 5.5-7.2 9.6L12 20.2z" />
        </svg>
      </button>

      {asking && (
        <SignIn
          onDone={() => {
            setAsking(false)
            // 로그인 직후 집합을 다시 받는다. onAuthStateChange가
            // useSession을 갱신하고, 그것이 위 useEffect를 다시 돌린다.
          }}
          onCancel={() => setAsking(false)}
        />
      )}
    </>
  )
}
```

- [ ] **Step 3: 로그인·로그아웃 시 캐시를 버린다**

`web/src/lib/supabase.ts` 끝에 더한다. 사용자가 바뀌면 좋아요 집합도 달라지므로 캐시를 들고 있으면 안 된다.

```typescript
import { resetLikes } from './likes'

// 로그인·로그아웃 때 좋아요 캐시를 버린다. 들고 있으면 로그아웃한 뒤에도
// 하트가 채워진 채로 남는다.
supabase.auth.onAuthStateChange((event) => {
  if (event === 'SIGNED_IN' || event === 'SIGNED_OUT') resetLikes()
})
```

> **순환 import를 주의한다.** `likes.ts`가 `supabase.ts`를 import하고 그 역도 생긴다. ES 모듈이 순환을 허용하지만 평가 순서에 따라 `resetLikes`가 아직 정의되지 않을 수 있다. 위 코드는 콜백 **안에서만** 부르므로 안전하다 — 모듈 평가가 끝난 뒤에 실행된다.

- [ ] **Step 4: 직접 눌러 확인한다**

```bash
cd web && npm run dev
```

| 확인할 것 | 기대 |
|---|---|
| 로그아웃 상태에서 하트 클릭 | 로그인 폼이 **그 자리에** 뜬다. 페이지가 가려지지 않는다 |
| 로그인 후 하트 클릭 | 채워진다 |
| 다시 클릭 | **빈다** (초판에서는 불가능했던 것) |
| 새로고침 | 채워진 상태가 유지된다 |
| 다른 브라우저에서 같은 계정으로 로그인 | **같은 글이 채워져 보인다** |
| 로그아웃 | 하트가 전부 빈다 |

- [ ] **Step 5: 커밋**

```bash
cd "$(git rev-parse --show-toplevel)"
git add web/src/lib/likes.ts web/src/components/LikeButton.tsx web/src/lib/supabase.ts
git commit -m "feat: 좋아요 토글 — DB가 기억하고 기기 간 같게 보인다"
```

---

## Task 12: 메모와 태그

**추가 전용이다.** `notes`에 UPDATE·DELETE를 주지 않았다. 저장할 때마다 새 행이 생기고, 읽을 때 그 글의 **가장 최근 행**을 쓴다. 화면에서는 제자리 수정과 구별되지 않으면서 수정 이력이 남는다.

**Files:**
- Create: `web/src/lib/notes.ts`
- Create: `web/src/components/Note.tsx`
- Modify: `web/src/components/Card.tsx`

- [ ] **Step 1: `web/src/lib/notes.ts`**

```typescript
import { supabase } from './supabase'

export type Note = { text: string; tags: string[] }

/**
 * 그 글의 가장 최근 메모. 없으면 null이다.
 * 추가 전용이므로 행이 여러 개일 수 있고 **최신 하나만** 의미가 있다.
 */
export async function loadNote(articleId: number): Promise<Note | null> {
  const { data, error } = await supabase
    .from('notes')
    .select('text, tags')
    .eq('article_id', articleId)
    .order('created_at', { ascending: false })
    .limit(1)

  // 로그인하지 않았으면 권한이 없다. 메모는 로그인 후에만 보이므로 정상이다.
  if (error) return null

  const row = data?.[0]
  if (!row) return null
  return { text: row.text as string, tags: (row.tags ?? []) as string[] }
}

/**
 * 메모를 저장한다. **새 행을 넣는다** — 수정이 아니다.
 * 태그 삭제도 "그 태그를 뺀 새 행"으로 표현된다.
 */
export async function saveNote(
  articleId: number,
  userId: string,
  note: Note,
): Promise<void> {
  const { error } = await supabase.from('notes').insert({
    article_id: articleId,
    // RLS의 with check가 auth.uid() = user_id를 요구한다. 빼면 거부된다.
    user_id: userId,
    text: note.text.trim(),
    tags: note.tags,
  })
  if (error) throw new Error(`메모를 저장하지 못했다: ${error.message}`)
}

/** 입력한 태그 문자열을 정리한다. 쉼표·공백으로 나누고 중복을 없앤다. */
export function parseTags(input: string): string[] {
  const parts = input
    .split(/[,\s]+/)
    .map((tag) => tag.replace(/^#/, '').trim())
    .filter((tag) => tag.length > 0)
  // Set으로 중복을 없애면서 입력 순서를 유지한다.
  return [...new Set(parts)]
}
```

- [ ] **Step 2: `web/src/components/Note.tsx`**

```typescript
import { useEffect, useState } from 'react'
import { useSession } from '../lib/auth'
import { loadNote, parseTags, saveNote, type Note as NoteData } from '../lib/notes'
import SignIn from './SignIn'

type Props = { articleId: number }

export default function Note({ articleId }: Props) {
  const { session } = useSession()
  const [open, setOpen] = useState(false)
  const [asking, setAsking] = useState(false)
  const [note, setNote] = useState<NoteData>({ text: '', tags: [] })
  const [tagInput, setTagInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)

  // 열 때, 그리고 로그인 상태가 바뀔 때 최신 행을 읽는다.
  useEffect(() => {
    if (!open || !session) return
    let alive = true
    void loadNote(articleId).then((found) => {
      if (alive && found) setNote(found)
    })
    return () => {
      alive = false
    }
  }, [open, session, articleId])

  function press() {
    if (!session) {
      setAsking(true)
      return
    }
    setOpen((was) => !was)
  }

  async function save() {
    if (!session) return
    setBusy(true)
    try {
      // 입력창에 남은 태그도 함께 넣는다 — 엔터를 누르지 않고 저장하는
      // 경우가 흔하고, 그때 조용히 사라지면 안 된다.
      const pending = parseTags(tagInput)
      const merged = { text: note.text, tags: [...new Set([...note.tags, ...pending])] }
      await saveNote(articleId, session.user.id, merged)
      setNote(merged)
      setTagInput('')
      setSaved(true)
      setTimeout(() => setSaved(false), 1800)
    } finally {
      setBusy(false)
    }
  }

  function removeTag(tag: string) {
    // 화면에서만 뺀다. 저장을 누를 때 "그 태그가 없는 새 행"이 들어간다.
    setNote((was) => ({ ...was, tags: was.tags.filter((item) => item !== tag) }))
  }

  return (
    <>
      <button
        type="button"
        onClick={press}
        aria-expanded={open}
        className="flex h-11 items-center text-[11.5px] font-medium"
        style={{ color: 'var(--color-accent)' }}
      >
        {open ? '메모 닫기' : note.text || note.tags.length ? '메모 보기' : '메모'}
      </button>

      {asking && (
        <SignIn onDone={() => { setAsking(false); setOpen(true) }} onCancel={() => setAsking(false)} />
      )}

      {open && session && (
        <div className="mt-1.5 rounded-md border border-line bg-panel p-3">
          <textarea
            value={note.text}
            onChange={(event) => setNote({ ...note, text: event.target.value })}
            rows={3}
            placeholder="이 글에 대해 남길 메모"
            className="mb-2 w-full resize-y rounded border border-edge bg-bg px-2.5 py-2 text-[13.5px] leading-[1.6]"
          />

          {note.tags.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {note.tags.map((tag) => (
                <span
                  key={tag}
                  className="flex items-center gap-1 rounded bg-tag px-2 py-0.5 text-[11.5px] text-ink-2"
                >
                  {tag}
                  <button
                    type="button"
                    onClick={() => removeTag(tag)}
                    aria-label={`${tag} 태그 빼기`}
                    className="text-muted"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}

          <input
            value={tagInput}
            onChange={(event) => setTagInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter') return
              event.preventDefault()
              const parsed = parseTags(tagInput)
              if (parsed.length === 0) return
              setNote((was) => ({ ...was, tags: [...new Set([...was.tags, ...parsed])] }))
              setTagInput('')
            }}
            placeholder="태그 (쉼표나 엔터로 구분)"
            className="mb-2.5 w-full rounded border border-edge bg-bg px-2.5 py-1.5 text-[12.5px]"
          />

          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={save}
              disabled={busy}
              className="rounded px-3 py-1.5 text-[12.5px] font-medium text-white disabled:opacity-50"
              style={{ backgroundColor: 'var(--color-accent)' }}
            >
              {busy ? '저장 중…' : '저장'}
            </button>
            {saved && <span className="text-[12px] text-muted">저장했습니다</span>}
          </div>

          <p className="mt-2 text-[11.5px] leading-[1.5] text-muted-2">
            저장할 때마다 새 기록이 쌓입니다. 이전 메모는 지워지지 않습니다.
          </p>
        </div>
      )}
    </>
  )
}
```

- [ ] **Step 3: `Card.tsx`에 메모를 붙인다**

Task 6에서 만든 `web/src/components/Card.tsx`에 import를 더한다.

```typescript
import Note from './Note'
```

그리고 메타 줄(`<div className="mt-0.5 flex items-center gap-2.5 …">`) **다음에**, `</article>` 앞에 넣는다. 메타 줄 **안**이 아니다 — 메모는 펼쳐지면 카드 아래로 자라므로 `flex items-center` 안에 들어가면 레이아웃이 깨진다.

```typescript
      <div className="mt-0.5 flex items-center gap-2.5 font-meta text-[11.5px] text-muted">
        <span>{article.source}</span>
        <span aria-hidden="true">·</span>
        <span className="font-medium text-ink-2">{article.score}</span>
        <LikeButton articleId={article.id} className="ml-auto -mr-2.5" />
      </div>

      <Note articleId={article.id} />
    </article>
```

- [ ] **Step 4: 직접 써서 확인한다**

| 확인할 것 | 기대 |
|---|---|
| 로그아웃 상태에서 "메모" | 로그인 폼이 뜬다 |
| 메모를 쓰고 저장 | "저장했습니다"가 잠깐 뜬다 |
| 닫고 다시 열기 | 쓴 내용이 그대로 있다 (최신 행) |
| 내용을 바꾸고 저장, 다시 열기 | **바꾼 내용**이 보인다 (제자리 수정처럼 보인다) |
| 태그를 넣고 엔터 | 칩으로 들어간다 |
| 태그 `×` 누르고 저장 | 그 태그가 빠진다 |
| 대시보드에서 `select * from notes` | **행이 여러 개다** — 추가 전용이 동작한다는 증거다 |

- [ ] **Step 5: 커밋**

```bash
cd "$(git rev-parse --show-toplevel)"
git add web/src/lib/notes.ts web/src/components/Note.tsx web/src/components/Card.tsx
git commit -m "feat: 메모와 태그 — 추가 전용, 최신 행을 읽는다"
```

---

## Task 13: 색인 차단

**Files:**
- Create: `docs/robots.txt`
- Modify: `design/공개-전-점검.md`

- [ ] **Step 1: `docs/robots.txt`**

```
User-agent: *
Disallow: /
```

요구사항 D4. 스펙 7.2: "GitHub Pages는 검색엔진에 색인되므로, 이것이 없으면 '아무도 모르는 URL'이라는 전제가 깨진다." Task 3의 `noindex` 메타와 **둘 다** 둔다 — `robots.txt`는 크롤링을, 메타는 이미 수집된 페이지의 색인을 막는다.

> **`robots.txt`가 접근을 막지는 않는다.** 크롤러에게 하는 부탁이다. 그래서 Task 1에서 설계 문서를 `docs/` 밖으로 옮겼고, 민감한 것은 애초에 웹 루트에 두지 않는다.

- [ ] **Step 2: 점검 문서를 갱신한다**

`design/공개-전-점검.md`의 "3. 검토했고 공개해도 되는 것" 표에 두 줄을 더한다.

```markdown
| `docs/assets/*.js`의 Supabase URL과 publishable 키 | **의도된 노출이다.** 브라우저가 Supabase에 직접 붙으므로 빌드 산출물에 들어간다. 스펙 7.2: "publishable 키는 비밀이 아니다 — 브라우저에 노출되도록 설계된 키다." 실제 방어는 RLS이고, 계획 2 Task 2 Step 9에서 실측했다. **secret 키는 들어가지 않는다** — Vite는 `VITE_` 접두사만 클라이언트에 넣는다 |
| `supabase/migrations/*.sql` | RLS 정책과 grant가 전부 보인다. 보안이 스키마 비밀에 의존하지 않는다 |
```

그리고 "4. 공개되지 않는 것"에 한 줄을 더한다. 직접 조회로 바꾼 결과다.

```markdown
- **기사 데이터** — 헤드라인·요약·판단 근거가 **리포지토리에 전혀 커밋되지 않는다.**
  페이지가 Supabase를 직접 조회하므로 `docs/data/` 같은 디렉터리가 없다.
  타인 저작물에서 파생된 내용이 공개 git 히스토리에 영구히 쌓이지 않는다
  (설계 2.1이 "전환 시 가장 먼저 검토"로 꼽은 저작권 항목과 같은 방향이다)
```

- [ ] **Step 3: secret 키가 빌드 산출물에 없는지 확인**

이게 이 태스크의 핵심 검증이다.

```bash
cd "$(git rev-parse --show-toplevel)/web" && npm run build && cd ..
grep -rl "sb_secret_" docs/assets/ 2>/dev/null && echo "⚠️  secret 키가 들어갔다" || echo "✓ secret 키 없음"
grep -rlo "sb_publishable_[A-Za-z0-9_-]*" docs/assets/ 2>/dev/null | head -1
```

Expected: secret 키 없음. publishable 키는 **있어야 정상이다** — 없으면 `.env.local`이 빌드에 안 들어간 것이다.

- [ ] **Step 4: 커밋**

```bash
cd "$(git rev-parse --show-toplevel)"
git add docs/robots.txt design/공개-전-점검.md
git commit -m "feat: 색인 차단 + 점검 문서에 노출 면 기록"
```

---

## Task 14: GitHub Pages 배포

**Files:**
- 설정 + 빌드 산출물

- [ ] **Step 1: Pages를 `main`의 `/docs`로 켠다**

```bash
gh api -X POST repos/predevho/topic-briefing/pages \
  -f 'source[branch]=main' -f 'source[path]=/docs'
```

실패하면 웹에서 한다: Settings → Pages → Source: *Deploy from a branch* → Branch `main`, 폴더 `/docs`.

- [ ] **Step 2: 빌드하고 커밋한다**

```bash
cd "$(git rev-parse --show-toplevel)/web" && npm run build && cd ..
git add docs/
git commit -m "build: 페이지 빌드 산출물"
git push origin main
```

> **이것이 매일 하는 일이 아니다.** 빌드 산출물은 **코드가 바뀔 때만** 커밋한다. 브리핑이 새로 나오는 것은 파이프라인이 Supabase에 쓰는 것으로 끝이고, 페이지는 열릴 때 조회한다(스펙 6.4의 분리). Task 15 Step 1이 이것을 검증한다.

- [ ] **Step 3: 배포를 기다려 확인한다**

```bash
gh api repos/predevho/topic-briefing/pages --jq '"status: \(.status)  url: \(.html_url)"'
```

Expected: `status: built`, `url: https://predevho.github.io/topic-briefing/`

- [ ] **Step 4: 실제 URL을 폰과 데스크톱에서 확인한다**

| 확인할 것 | 기대 |
|---|---|
| `https://predevho.github.io/topic-briefing/` | 최신 브리핑 |
| `.../2026-11-12` | 그 날짜 (404 폴백이 동작한다) |
| `.../archive` | 아카이브 목록 |
| `.../1999-01-01` | "그 날짜의 브리핑이 없습니다." |
| `.../robots.txt` | `Disallow: /` |
| 폰 (가로 390px 정도) | 1열, 글자가 읽히는 크기 |
| 데스크톱 | 2열 (`md:grid-cols-2`) |
| **로그인하지 않은 상태** | 브리핑이 **그대로 읽힌다.** 로그인 화면이 뜨지 않는다 |

**`base`가 틀리면 JS·CSS가 404가 되어 빈 화면이 뜬다.** 그러면 `web/vite.config.ts`의 `base`를 `/topic-briefing/`으로 확인한다.

- [ ] **Step 5: 커밋 (있으면)**

```bash
git status --short
```

---

## Task 15: 엔드투엔드 검증과 문서 갱신

- [ ] **Step 1: 파이프라인과 프론트엔드의 분리를 검증한다 (요구사항 O11)**

**이것이 이 계획에서 가장 중요한 검증이다.** 빌드도 커밋도 없이, DB에 행을 넣는 것만으로 페이지에 새 날짜가 보여야 한다.

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python - <<'PY'
import os
from datetime import datetime, timezone
from supabase import create_client

client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
DATE = "2099-01-01"   # 실제 날짜와 섞이지 않는 값

client.table("runs").insert({
    "briefing_date": DATE,
    "window_start": "2099-01-01T00:00:00+00:00",
    "window_end": "2099-01-01T12:00:00+00:00",
    "status": "sent",
    "sent_at": datetime.now(timezone.utc).isoformat(),
    "collected_count": 7, "considered_count": 3, "max_score": 88,
    "published_count": 1, "source_counts": {"검증용": 1},
    "input_tokens": None, "errors": [],
}).execute()

client.table("articles").insert({
    "briefing_date": DATE,
    "url": "https://example.com/separation-check",
    "source": "검증용", "published_at": "2099-01-01T06:00:00+00:00",
    "headline": "분리 검증용 글",
    "bullets": ["빌드 없이 보이는지 확인한다"],
    "why_it_matters": "파이프라인과 프론트엔드가 분리됐다는 증거다.",
    "topic": "other", "score": 88, "reason": "검증용",
}).execute()
print(f"{DATE} 행을 넣었다. 빌드하지 않는다.")
PY
```

브라우저에서 `https://predevho.github.io/topic-briefing/2099-01-01`을 **새로고침만** 한다.

Expected: "분리 검증용 글"이 보인다. **`npm run build`도 `git push`도 하지 않았다.** 보이면 O11이 충족된다.

치운다.

```bash
.venv/bin/python - <<'PY'
import os
from supabase import create_client
client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
client.table("articles").delete().eq("briefing_date", "2099-01-01").execute()
client.table("runs").delete().eq("briefing_date", "2099-01-01").execute()
print("검증용 행을 지웠다")
PY
```

- [ ] **Step 2: 0건인 날이 보이는지 검증한다 (요구사항 D8)**

`runs` 행만 있고 `articles`가 없는 날짜를 만들어, 화면이 "없는 날짜"가 아니라 **"조용한 날"**로 그리는지 본다. 이게 `runs.briefing_date` 마이그레이션의 목적이다.

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python - <<'PY'
import os
from datetime import datetime, timezone
from supabase import create_client
client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])
client.table("runs").insert({
    "briefing_date": "2099-01-02",
    "window_start": "2099-01-02T00:00:00+00:00",
    "window_end": "2099-01-02T12:00:00+00:00",
    "status": "sent", "sent_at": datetime.now(timezone.utc).isoformat(),
    "collected_count": 240, "considered_count": 10, "max_score": 52,
    "published_count": 0, "source_counts": {"검증용": 240},
    "input_tokens": None, "errors": [],
}).execute()
print("0건인 날을 만들었다")
PY
```

| URL | 기대 |
|---|---|
| `.../2099-01-02` | "후보 10건을 봤지만 기준을 넘긴 글이 없었습니다" + **수집 240건 / 최고 52점 / 기준 60점** |
| `.../archive` | `2099-01-02`가 **0건으로 목록에 있다** |
| `.../1999-01-01` | "그 날짜의 브리핑이 없습니다" (실행 기록조차 없는 날짜) |

**수치가 0으로 나오면 마이그레이션이 적용되지 않은 것이다.** Task 2 Step 7로 돌아간다.

치운다.

```bash
.venv/bin/python -c "
import os
from supabase import create_client
create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SECRET_KEY']).table('runs').delete().eq('briefing_date', '2099-01-02').execute()
print('지웠다')
"
```

- [ ] **Step 3: 권한을 실측한다**

```bash
cd "$(git rev-parse --show-toplevel)"
bash scripts/verify_anon_access.sh
```

Expected: 전부 통과 — 본문 차단(D2), `reason` 차단, `runs.errors` 차단, anon 좋아요 차단.

- [ ] **Step 4: 전체 테스트**

```bash
.venv/bin/python -m pytest
```

Expected: 397 passed

- [ ] **Step 5: 요구사항 문서를 갱신한다**

`design/superpowers/specs/2026-11-11-requirements.md`에서 수단이 바뀐 행을 고친다. **의도는 그대로이고 수단만 바뀌었다** — 그 구분이 문서에 남아야 한다.

| ID | 고칠 내용 |
|---|---|
| O9 | 충족 위치 → `계획 2 Task 7·8`, 상태 → ✅ |
| O10 | 상태 → ✅ (Task 14 Step 4에서 실측) |
| **O11** | 요구사항 문구를 "SPA + **런타임 조회** (파이프라인과 프론트 분리)"로. 충족 위치 → `계획 2 Task 5`. 검증 → "Task 15 Step 1 — 빌드·커밋 없이 DB에 행을 넣어 새 날짜가 보이는지 확인". 상태 → ✅ |
| O12 | 상태 → ✅ |
| **O13** | 검증 문구에서 "anon은 INSERT만 가능 / `localStorage`"를 지운다. → "**인증 후 `auth.uid() = user_id` RLS.** 좋아요는 토글(삽입·삭제), 메모는 추가 전용 + 최신 행 읽기". 상태 → ✅ |
| O14 | 상태 → ✅ |
| **D3** | 충족 위치 → "**구조적**: 리포지토리에 기사 데이터를 전혀 커밋하지 않는다. 페이지가 Supabase를 직접 조회하므로 `docs/data/`가 없다". 상태 → ✅ |
| D4 | 충족 위치 → `계획 2 Task 3·13`, 상태 → ✅ |
| **D8** | 검증에 한 줄 추가 → "계획 2 Task 2가 `runs.briefing_date`를 더해 페이지가 이 데이터에 도달한다. Task 15 Step 2에서 실측". 상태 → ✅ |

- [ ] **Step 6: `README.md`를 갱신한다**

"## 매일 실행" 절에 더한다.

```markdown
페이지는 **아무것도 하지 않아도 갱신된다.** 파이프라인이 Supabase에 쓰면
페이지가 열릴 때 조회한다 — 빌드도 커밋도 필요 없다(스펙 6.4의 분리).

프론트엔드 **코드**를 바꿨을 때만 배포한다.

```bash
cd web && npm run build && cd ..
git add docs/ && git commit -m "build: 페이지 갱신" && git push
```

페이지: <https://predevho.github.io/topic-briefing/>
```

- [ ] **Step 7: 커밋**

```bash
cd "$(git rev-parse --show-toplevel)"
git add design/ README.md
git commit -m "docs: 요구사항·README를 직접 조회 방식으로 갱신"
git push origin main
```

---

## 완료 조건

- [ ] `design/`에 설계·계획 문서가 있고 `docs/`에는 빌드 산출물과 `robots.txt`·`.nojekyll`·`404.html`만 있다
- [ ] `https://predevho.github.io/topic-briefing/`이 **로그인 없이** 최신 브리핑을 보여준다
- [ ] `/:date`와 `/archive`가 동작하고, 없는 날짜는 "없습니다"로 끝난다
- [ ] 0건인 날이 아카이브에 0건으로 보이고, 그 날짜 화면이 수집 건수·최고 점수·기준을 보여준다
- [ ] 좋아요가 **토글되고**, 다른 기기에서 같은 계정으로 보면 같게 보인다
- [ ] 메모를 쓰고 다시 열면 그 내용이 있다. `notes` 테이블에는 행이 쌓여 있다
- [ ] `scripts/verify_anon_access.sh`가 통과한다 — 본문·`reason`·`runs.errors`·anon 좋아요가 모두 막혔다
- [ ] `docs/assets/`에 `sb_secret_`이 없다
- [ ] 빌드도 커밋도 없이 DB에 넣은 새 날짜가 페이지에 보인다 (O11)
- [ ] `.venv/bin/python -m pytest` 397 passed
- [ ] 요구사항 문서의 O9~O14·D3·D4·D8이 ✅다

---

## 다음 계획

**계획 3 (전달과 자동화):** `KakaoSender`·`SlackSender`·`lib/guard`·GitHub Actions. 이 계획이 끝나면 **카톡의 "전체 보기" 버튼이 가리킬 곳이 생긴다** — 그것이 계획 2를 먼저 하는 이유였다.

계획 3에서 메워야 할 구멍은 `README.md`의 같은 이름 절에 있다 (`runs.input_tokens` 배선, 소스별 `quiet_days`).

### 이 계획에서 의도적으로 하지 않은 것

- **사용자별 브리핑** — `interests.md`를 DB로 올리고 파이프라인을 사용자별로 돌리는 일. 설계 2.1: "비용이 아니라 **근거가 없기 때문이다.** 외부 사용자가 실제로 무엇에 반응하는지를 보고 정해야 한다. 상상으로 설계하면 틀린다." 사용자가 0명인 지금 하지 않는다. **인증은 이 계획에서 켰으므로, 그때 추가로 할 일은 큐레이션 모델뿐이다.**
- **외부 사용자에게 알림** — 카카오 메시지 API는 같은 서비스 내 사용자 간 발송만 지원하고, 서비스→사용자 직접 발송은 사업자(채널·알림톡) 영역이다. 다수 사용자 알림이 목표가 되면 **슬랙·텔레그램·이메일**로 가야 한다 (설계 2.1).
- **저작권 재검토** — 설계 2.1이 "전환 시 가장 먼저 검토해야 하는 항목"으로 꼽았다. 1인 열람은 사적 복제 범위라는 7.2의 전제가 유지되는 동안은 그대로 간다. **실제로 남에게 보내기 전에** 검토한다.
- **다크 모드** — 라이트 모드만. Task 4가 색을 전부 CSS 변수로 두므로, 나중에 토큰 파일 한 곳에 다크 값을 더하고 `@media (prefers-color-scheme: dark)`로 덮으면 된다. 컴포넌트를 다시 손댈 일이 없다.
- **메모 제자리 수정** — `notes`에 UPDATE를 주지 않는다. 추가 전용이 화면에서 같아 보이면서 수정 이력을 남긴다.
- **공개 가입** — Supabase Auth의 "Allow new users to sign up"을 끈다. 열어 두면 아무나 계정을 만들어 좋아요를 넣을 수 있고, 그건 anon INSERT를 거둔 이유를 무효로 만든다. 사람을 늘릴 때는 대시보드에서 계정을 만든다.
- **로그아웃 버튼** — `auth.ts`에 `signOut()`이 있지만 화면에 버튼을 두지 않았다. 1인용이고 **세션이 기기당 유지되는 것이 목적**이므로 로그아웃할 이유가 드물다. 필요하면 콘솔에서 `(await import('/src/lib/auth.ts')).signOut()`을 부른다. 화면에 넣으려면 `App.tsx`(Task 9)에 푸터를 더하면 되는데, 그 파일은 이 계획에서 초판 그대로 살리는 쪽을 택했다.
- **소스 침묵 "N일 연속"** — 여러 날의 `runs`를 봐야 안다. 계획 3의 `lib/guard`가 한다.
