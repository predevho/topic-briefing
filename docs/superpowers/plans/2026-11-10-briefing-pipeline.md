# 브리핑 파이프라인 구현 계획 (Phase 1 / 계획 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로컬에서 명령 5개를 순서대로 실행하면 IT 토픽이 수집·선별·요약되어 터미널에 브리핑으로 출력되고, 발행 이력이 쌓인다. **큐레이션 품질 튜닝을 여기서 끝낸다.**

전달 채널(카카오톡·슬랙)은 계획 3으로 미룬다. 계획 1의 목적은 "뭘 보낼지"를 정하는 것이고, 그건 터미널과 `evaluate.py`로 하는 작업이다. 다만 보낼 곳이 여러 곳이 될 것이 정해져 있으므로 `Sender` 프로토콜로 이음새를 만들어 둔다.

**Architecture:** 단계별 독립 실행 파이프라인. 각 단계가 `data/YYYY-MM-DD/`에 JSON을 떨어뜨리고 다음 단계가 그것을 입력으로 읽는다. 어느 단계든 단독 재실행이 가능하므로 프롬프트 튜닝 비용이 낮다. 상태(실행 이력·발행 이력·본문)는 Supabase, 중간 산출물은 로컬 파일.

**Tech Stack:** Python 3.12, feedparser(RSS 파싱), trafilatura(본문 추출), httpx(HTTP), anthropic(Claude API), supabase(DB), PyYAML, pydantic(구조화된 출력 검증), pytest.

**설계 스펙:** `docs/superpowers/specs/2026-11-10-it-column-automation-design.md`

---

## Python 버전과 구문법 대조표

**이 프로젝트는 Python 3.12를 쓴다.** 취향이 아니라 제약이다 — anthropic SDK(검증 시점 2.7.0)가 3.10 이상을 요구하고, 이 맥의 시스템 `python3`인 3.9는 2025-10-31에 수명이 끝났다.

Python에는 **LTS가 없다.** [PEP 602](https://peps.python.org/pep-0602/)에 따라 매년 10월에 피처 릴리스가 나오고 각 버전은 총 5년(약 2년 전체 지원 + 약 3년 보안 패치만)을 받고 끝난다.

| 버전 | 상태 (2026-11 기준) |
|---|---|
| 3.9 | **수명 종료** (2025-10-31). 시스템 `python3`가 이 버전이다 |
| 3.10 | **수명 종료** (2026-10-01) |
| 3.11 | 보안 패치만, 2027-10 종료 |
| 3.12 | 보안 패치만, 2028-10 종료 ← **이 프로젝트** |
| 3.13 / 3.14 | 신규 프로젝트 권장 |

### 구문법 대조

레거시 코드베이스에는 아래 왼쪽 형태가 가득하다. **읽을 수 있어야 한다.** 다만 이 프로젝트에서는 오른쪽으로 쓴다.

| 구형 (`typing` 별칭) | 현행 | 언제부터 |
|---|---|---|
| `Optional[str]` | `str \| None` | 3.10 |
| `Union[int, str]` | `int \| str` | 3.10 |
| `List[str]` | `list[str]` | 3.9 |
| `Dict[str, int]` | `dict[str, int]` | 3.9 |
| `Set[int]` | `set[int]` | 3.9 |
| `Tuple[int, str]` | `tuple[int, str]` | 3.9 |
| `Type[Foo]` | `type[Foo]` | 3.9 |
| `Callable[[str], int]` | 그대로 (`typing`에서 가져온다) | — |
| `Literal["a", "b"]` | 그대로 | — |

대문자 별칭은 **없어지지 않았고 지금도 동작한다.** 다만 신규 코드에서는 쓰지 않는 쪽이 표준이 됐다.

### `from __future__ import annotations` — 레거시 지원의 실제 기법

구형 Python을 지원해야 하는 **라이브러리**는 `Optional[str]`을 손으로 쓰는 대신 이걸 쓴다.

```python
from __future__ import annotations   # 파일의 첫 import여야 한다

def f(x: str | None) -> list[int]:   # 3.9에서도 문법 오류가 안 난다
    ...
```

어노테이션을 **문자열로 미뤄 평가**하기 때문에, 그 자리에 3.10 문법을 적어도 인터프리터가 읽지 않는다. 다만 공짜는 아니다 — **런타임에 어노테이션을 실제로 읽는 라이브러리**(pydantic이 대표적이다. 타입을 보고 검증기를 만든다)와는 미묘하게 어긋날 수 있어서, 그런 경우엔 해석 가능한 이름이 모듈에 실제로 있어야 한다.

이 프로젝트는 3.12를 쓰고 pydantic에 크게 의존하므로 **이 기법을 쓰지 않는다.** 알아두는 것이 목적이다.

---

## 스펙에서 변경된 세 가지

구현하다 막히는 문제라 계획 단계에서 고친다.

**1. 숫자 접두 파일명 → 모듈명 + `python -m`**

스펙은 `pipeline/01_collect.py`로 적었다. 그런데 Python에서 숫자로 시작하는 모듈명은 import할 수 없다(`import 01_collect`는 문법 오류). 테스트를 쓸 수 없으므로 폐기한다.

- `pipeline/collect.py` … `pipeline/notify.py`로 두고 `python -m pipeline.collect`로 실행한다.
- 실행 순서는 Actions 워크플로 YAML에 이미 명시되므로 파일명에 담을 필요가 없다.

**2. `articles.body` → `article_bodies` 별도 테이블**

스펙은 본문을 `articles.body`에 두고 "RLS로 anon에게 차단"이라고 했다. 문제가 둘이다.

- RLS는 **행** 단위다. 컬럼을 가리려면 `grant select (컬럼 목록)`으로 컬럼 권한을 따로 관리해야 하고, 컬럼을 추가할 때마다 권한을 다시 손봐야 한다.
- PostgREST에서 anon이 `body`에 SELECT 권한이 없으면 `select *`가 **에러**가 된다. 프론트엔드가 항상 컬럼을 명시해야 하고, 한 번 빠뜨리면 전체 조회가 깨진다.

→ 본문을 `article_bodies` 테이블로 분리하고 **anon에게 그 테이블 권한을 아예 주지 않는다.** 테이블 단위 권한이라 검증이 `anon으로 조회해보기` 한 번으로 끝난다. Phase 3의 임베딩도 같은 테이블에 들어가므로 구조가 맞다.

**3. 에러를 Transient / Permanent로 분류 (`lib/retry.py`, `lib/http.py` 신설)**

스펙 8.1의 실패 정책은 "소스 하나 실패 → 기록하고 계속" 수준이다. 그대로 구현하면 서로 다른 실패가 한 덩어리가 된다.

- 피드가 **404**(주소가 죽음)인 것과 **503**(일시 장애)인 것이 같은 문자열로 기록된다. 전자는 `sources.yaml`을 고쳐야 하고 후자는 기다리면 되는데 로그만 보고는 구분이 안 된다.
- **403**(봇 차단, 영구)에도 재시도를 걸면 10건이면 수십 초를 버린다.
- **429**의 `Retry-After` 헤더를 무시하고 더 빨리 때리면 더 오래 막힌다.
- 슬랙 **404**(웹훅 삭제)와 **429**(레이트 리밋)가 같은 예외로 올라오면, 전자는 재시도가 무의미한데 재시도한다.
- **Anthropic SDK는 429·5xx·연결 오류를 이미 자체 재시도한다**(기본 `max_retries=2`). 그 위에 또 재시도를 걸면 최악의 경우 한 번의 논리적 호출이 6번이 된다.

→ `Transient`(기다리면 됨) / `Permanent`(설정을 고쳐야 함) 두 갈래로만 나누고, 분류 규칙을 `lib/http.py` 한곳에 둔다. 갈래를 상태 코드만큼 늘리면 호출부마다 분기가 생기고 결국 아무도 유지하지 않는다.

파급은 모델 두 필드다 — `SourceError.kind`(계획 3의 소스 경고가 "죽은 소스"와 "불안정한 소스"를 구분하게 된다)와 `Article.fallback_reason`(슬랙 경고가 "2건 발췌" 대신 "403 봇 차단 2건"이 된다).

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `pyproject.toml` | 의존성, pytest 설정 |
| `.env.example` | 필요한 환경변수 목록 (실제 값 없음) |
| `config/sources.yaml` | 수집 소스 목록 |
| `config/interests.md` | 관심사 프로필 — 선별 기준 |
| `supabase/schema.sql` | 테이블 + 권한 + RLS |
| `pipeline/models.py` | 단계 간 데이터 계약 (dataclass + pydantic) |
| `pipeline/lib/urls.py` | URL 정규화 (중복 제거의 기반) |
| `pipeline/lib/timeutil.py` | 시각 정규화, 수집 윈도우 계산 |
| `pipeline/lib/retry.py` | 재시도 분류 (Transient/Permanent) + 지수 백오프 |
| `pipeline/lib/http.py` | HTTP 수집과 상태 코드 분류 |
| `pipeline/lib/secrets.py` | 환경변수 접근 단일 통로 |
| `pipeline/lib/store.py` | `LocalStore`(JSON 파일) + `RemoteStore`(Supabase) |
| `pipeline/lib/llm.py` | Claude API 래퍼 (주입 가능 → 테스트에서 교체) |
| `pipeline/lib/sender.py` | `Sender` 프로토콜 + `ConsoleSender` + 경고 수집 |
| `pipeline/collect.py` | 윈도우 내 수집 → `raw.json` |
| `pipeline/seed.py` | 1회성 시드 수집 (윈도우 무제한) |
| `pipeline/rank.py` | 선별 채점 → `ranked.json` |
| `pipeline/evaluate.py` | 선별 품질 비교 (운영 비포함) |
| `pipeline/enrich.py` | 본문 확보 → `articles.json` |
| `pipeline/summarize.py` | 임계값 + 요약 → `briefing.json` |
| `pipeline/notify.py` | 센더로 내보내고 실행 이력 기록 (윈도우 전진의 핵심) |
| `tests/` | 위 각 모듈의 테스트 + fixtures |

**경계 원칙:** `lib/`의 모듈은 파이프라인 단계를 모른다(순수 함수와 어댑터만). 단계 모듈은 `lib/`를 조립할 뿐 자체 로직을 최소화한다. 그래서 단계 모듈은 각 80~150줄에 머문다.

**테스트 가능성을 위한 의존성 주입:** `collect`/`rank`/`enrich`/`summarize`/`notify`의 핵심 함수는 `store`, `llm`, `fetch` 같은 협력자를 **인자로 받는다.** 테스트는 가짜 객체를 넘기고, `main()`만 실제 객체를 만든다. HTTP 모킹 라이브러리가 필요 없어진다.

---

## Task 1: 프로젝트 기반

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `pipeline/__init__.py`
- Create: `pipeline/lib/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_sanity.py`

- [ ] **Step 1: `pyproject.toml` 작성**

```toml
[project]
name = "topic-briefing"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "feedparser>=6.0.11",      # RSS/Atom 파싱. 매체별 포맷 차이를 흡수한다
    "trafilatura>=2.0.0",      # HTML에서 본문만 추출 (광고·내비 제거)
    "httpx>=0.28.1",           # HTTP 클라이언트. 타임아웃 지정이 명확하다
    "anthropic>=2.7.0",        # Claude API 공식 SDK (2.x 기준으로 코드를 썼다)
    "supabase>=2.15.0",        # Supabase 클라이언트
    "PyYAML>=6.0.2",           # sources.yaml 읽기
    "pydantic>=2.11.0",        # LLM 구조화된 출력 검증
    "python-dotenv>=1.0.1",    # 로컬 .env 로딩
]

[project.optional-dependencies]
dev = ["pytest>=8.3.0"]

# setuptools는 flat 레이아웃에서 최상위 디렉터리를 자동으로 패키지 후보로
# 본다. tests는 자동 제외되지만 config와 supabase(SQL 파일용)는 아니라서
# "최상위 패키지가 여러 개"로 설치가 거부된다. 찾을 범위를 명시해 막는다.
[tool.setuptools.packages.find]
include = ["pipeline*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
# -q: 간결한 출력. --strict-markers: 오타난 마커를 에러로
addopts = "-q --strict-markers"
```

> **설명** — `pyproject.toml`은 Python 프로젝트의 표준 설정 파일이다. `[project]`에 의존성을, `[tool.<도구명>]`에 각 도구 설정을 담는다. `>=`로 최소 버전만 지정하면 설치 시 최신 호환 버전이 들어온다.
>
> **`[tool.setuptools.packages.find]`가 없으면 Step 5가 실패한다.** setuptools는 "flat 레이아웃"(패키지가 저장소 루트에 바로 있는 구조)에서 최상위 디렉터리를 훑어 패키지 후보로 삼는다. `tests`·`docs`·`examples`는 자동 제외 목록에 있지만 **`config`와 `supabase`는 없다.** 그래서 후보가 셋이 되고, setuptools는 어느 것을 패키징할지 추측하지 않고 거부한다 — `Multiple top-level packages discovered in a flat-layout`. `include = ["pipeline*"]`은 "pipeline으로 시작하는 것만 찾아라"는 뜻이고, `pipeline`과 `pipeline.lib`가 여기 걸린다.
>
> 참고로 `supabase/` 디렉터리 이름이 `supabase` 라이브러리와 겹치지만 **가려지지 않는다.** 그 디렉터리에는 `__init__.py`가 없어 네임스페이스 패키지가 되고, **Python은 sys.path 순서와 무관하게 정규 패키지(`__init__.py`가 있는 것)를 우선한다.** 누군가 거기에 `__init__.py`를 넣으면 그때부터 가려진다.

- [ ] **Step 2: `.env.example` 작성**

실제 비밀값은 `.env`에 넣고 커밋하지 않는다. `.env.example`은 "어떤 키가 필요한지"만 알려주는 문서다.

```bash
# Claude API — Max 크레딧이 연결된 Console 조직에서 발급한 키여야 한다
ANTHROPIC_API_KEY=sk-ant-...

# Supabase
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SECRET_KEY=eyJ...

```

> 슬랙 Webhook과 카카오 키는 **계획 3**에서 추가한다. 계획 1은 위 셋으로 돈다.

- [ ] **Step 3: 패키지 초기화 파일 생성**

```bash
mkdir -p pipeline/lib tests/fixtures config supabase
touch pipeline/__init__.py pipeline/lib/__init__.py tests/__init__.py
```

> **설명** — `__init__.py`가 있는 디렉터리는 Python 패키지로 인식되어 `from pipeline.lib import urls` 같은 import가 가능해진다. 빈 파일이어도 된다.

- [ ] **Step 4: 환경 구성이 되는지 확인하는 테스트 작성**

`tests/test_sanity.py`:

```python
"""프로젝트 기반이 제대로 섰는지만 확인한다. 이후 태스크에서 삭제한다."""


def test_pytest가_동작한다():
    assert True


def test_pipeline_패키지를_import할_수_있다():
    import pipeline
    import pipeline.lib

    assert pipeline is not None
    assert pipeline.lib is not None
```

- [ ] **Step 5: 가상환경 생성 후 설치, 테스트 실행**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

> ⚠️ **`python3`가 아니라 `python3.12`다.** 이 맥의 `python3`는 3.9.6이고,
> 3.9는 2025-10-31에 수명이 끝났다(보안 패치도 안 온다). 더 중요한 건
> **anthropic SDK가 Python 3.10 이상을 요구**한다는 점이다 — 3.9에서는
> `pip install`부터 실패한다.
>
> `python3.12`는 brew로 설치돼 있다(`/opt/homebrew/bin/python3.12`, 3.12.16).
> 확인: `python3.12 --version`
>
> **시스템 `python3`를 3.12로 바꾸지 않는다.** brew의 caveats가 안내하는
> `libexec/bin`을 PATH에 넣으면 `python3`가 가려지는데, 다른 도구가 시스템
> `python3`를 기대할 수 있다. 이 프로젝트는 `python3.12`로 venv를 한 번
>만들고 그 뒤에는 `source .venv/bin/activate` 안에서만 작업하므로
> PATH를 건드릴 이유가 없다.

Expected: `2 passed`

> **설명** — `python -m venv .venv`는 이 프로젝트만의 격리된 패키지 디렉터리를 만든다. `pip install -e ".[dev]"`의 `-e`는 "editable 설치"로, 소스를 고치면 재설치 없이 반영된다. `[dev]`는 위에서 정의한 `optional-dependencies`의 dev 묶음을 함께 설치한다.

### 검증된 버전 (2026-11-10, Python 3.12.16에서 실제 설치 확인)

이 계획의 코드는 아래 버전에서 API 표면을 **실제로 확인하고** 작성했다. 추측이 아니다.

| 패키지 | 설치된 버전 | 확인한 것 |
|---|---|---|
| `anthropic` | **2.7.0** | 예외 클래스 9개, `APIConnectionError`가 `APIStatusError`의 **형제**인 것, `Anthropic(max_retries=)`, `beta.messages.parse`의 `betas`·`fallbacks`·`output_config`·`output_format` 인자, `parsed_output`·`stop_reason`·`stop_details`·`usage.input_tokens` |
| `httpx` | 0.28.1 | 예외 계층, **`InvalidURL`이 `HTTPError`의 하위가 아닌 것**, 테스트에서 `Response(status, request=, history=)` 직접 생성 |
| `supabase` | 2.34.1 | `create_client`, `table().select().order(desc=).limit().in_().gte().execute()`, `upsert(on_conflict=)` |
| `pydantic` | 2.14.3 | `frozen`, `extra="forbid"`, `Field(ge/le/max_length)` |
| `feedparser` | 6.0.14 | |
| `trafilatura` | 2.3.1 | |
| `pytest` | 9.2.0 | |

**두 가지 주의할 점이 설치 과정에서 드러났다.**

**1. `httpx`와 `httpx2`가 함께 깔린다.** `anthropic` 2.x가 `httpx2`를 쓰기 때문이다. 설치 로그에 둘 다 보여도 정상이고, 우리 코드의 `import httpx`는 0.28.1을 가리킨다. 섞이지 않는다.

**2. `parsed_output`은 pydantic 필드가 아니라 property다.** `model_fields`에는 없으므로 그걸로 존재를 확인하려 하면 없는 것처럼 보인다. 접근은 평범하게 `response.parsed_output`으로 한다. **구조화된 출력이 붙지 않은 응답에서는 `None`이 나오므로** `lib/llm.py`가 그 경우를 `SchemaError`로 처리한다 — 실제로 일어날 수 있는 경로다.

- [ ] **Step 6: 커밋**

```bash
git add pyproject.toml .env.example pipeline tests
git commit -m "chore: 프로젝트 기반 구성 (의존성, 패키지 구조, pytest)"
```

---

## Task 2: URL 정규화

중복 제거가 조용히 실패하는 걸 막는 토대다. 같은 기사가 `?utm_source=...`만 달라서 두 번 발행되는 것을 여기서 막는다.

**Files:**
- Create: `pipeline/lib/urls.py`
- Create: `tests/test_urls.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_urls.py`:

```python
from pipeline.lib.urls import normalize_url


def test_utm_파라미터를_제거한다():
    url = "https://example.com/post?utm_source=rss&utm_medium=feed&id=7"
    assert normalize_url(url) == "https://example.com/post?id=7"


def test_추적_파라미터가_전부면_쿼리를_없앤다():
    url = "https://example.com/post?utm_source=rss&fbclid=abc"
    assert normalize_url(url) == "https://example.com/post"


def test_프래그먼트를_제거한다():
    url = "https://example.com/post#section-2"
    assert normalize_url(url) == "https://example.com/post"


def test_쿼리_순서가_달라도_같은_결과가_된다():
    a = normalize_url("https://example.com/p?b=2&a=1")
    b = normalize_url("https://example.com/p?a=1&b=2")
    assert a == b


def test_호스트를_소문자로_만든다():
    assert normalize_url("https://Example.COM/Post") == "https://example.com/Post"


def test_끝의_슬래시를_제거한다():
    assert normalize_url("https://example.com/post/") == "https://example.com/post"


def test_루트_경로의_슬래시는_남긴다():
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_같은_기사의_두_변형이_같은_키가_된다():
    """실제로 막으려는 상황."""
    a = "https://news.example.com/article/123?utm_source=rss&utm_campaign=daily"
    b = "https://news.example.com/article/123/"
    assert normalize_url(a) == normalize_url(b)
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_urls.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.urls'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/lib/urls.py`:

```python
"""URL 정규화. 같은 기사의 서로 다른 표기를 하나의 키로 만든다."""

from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# 추적용으로만 붙는 파라미터. 내용에 영향을 주지 않으므로 제거한다.
TRACKING_PREFIXES = ("utm_",)
TRACKING_EXACT = frozenset({
    "fbclid", "gclid", "igshid", "mc_cid", "mc_eid",
    "ref", "ref_src", "source", "spm",
})


def _is_tracking(key: str) -> bool:
    lowered = key.lower()
    return lowered.startswith(TRACKING_PREFIXES) or lowered in TRACKING_EXACT


def normalize_url(url: str) -> str:
    """추적 파라미터·프래그먼트를 제거하고 쿼리를 정렬한 URL을 돌려준다."""
    parts = urlsplit(url)

    # parse_qsl은 "a=1&b=2"를 [("a","1"), ("b","2")]로 바꾼다.
    # keep_blank_values=True여야 "?a=" 같은 빈 값이 사라지지 않는다.
    pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking(key)
    ]
    # sorted로 순서를 고정해야 "?a=1&b=2"와 "?b=2&a=1"이 같은 키가 된다.
    query = urlencode(sorted(pairs))

    path = parts.path
    # 루트("/")는 남기고, 그 외의 끝 슬래시만 제거한다.
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # urlunsplit의 5번째 요소가 프래그먼트. 빈 문자열을 넣어 제거한다.
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, query, ""))
```

> **설명** — `urlsplit`은 URL을 scheme/netloc/path/query/fragment 다섯 조각으로 쪼개고 `urlunsplit`이 다시 합친다. `frozenset`은 변경 불가능한 집합으로, 멤버십 검사(`in`)가 리스트보다 빠르고 상수로 쓰기에 안전하다. `str.startswith`는 튜플을 받아 "이 중 하나로 시작하는가"를 한 번에 검사한다.

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_urls.py
```

Expected: `8 passed`

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/urls.py tests/test_urls.py
git commit -m "feat: URL 정규화 — 추적 파라미터·프래그먼트 제거, 쿼리 정렬"
```

---

## Task 3: 시각 정규화와 수집 윈도우

스펙에서 "조용히 틀리기 가장 쉬운 지점"으로 지목한 부분이다. RSS의 발행 시각 표기는 매체마다 다르고, Actions는 UTC로 돈다.

**Files:**
- Create: `pipeline/lib/timeutil.py`
- Create: `tests/test_timeutil.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_timeutil.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from pipeline.lib.timeutil import (
    KST,
    MAX_WINDOW_HOURS,
    SEND_CRON_UTC,
    SEND_HOUR_UTC,
    SEND_MINUTE_UTC,
    compute_window,
    to_utc_iso,
)

WEEKDAY_NAMES = "월화수목금토일"


def _kst_weekdays_for_cron_days(first_utc_day: int) -> list[str]:
    """UTC로 연속 5일 발송했을 때의 KST 요일을 돌려준다.

    2026-11-08이 일요일이므로, first_utc_day=8이면 cron 요일 0-4(일~목)에
    해당한다.
    """
    return [
        WEEKDAY_NAMES[
            datetime(
                2026, 11, first_utc_day + offset,
                SEND_HOUR_UTC, SEND_MINUTE_UTC, tzinfo=timezone.utc,
            ).astimezone(KST).weekday()
        ]
        for offset in range(5)
    ]


# --- 시각 정규화 ---

def test_RFC822_표기를_UTC로_정규화한다():
    """국내 매체 RSS에서 흔한 형식."""
    assert to_utc_iso("Tue, 10 Nov 2026 14:30:00 +0900") == "2026-11-10T05:30:00+00:00"


def test_ISO8601_Z_표기를_정규화한다():
    assert to_utc_iso("2026-11-10T05:30:00Z") == "2026-11-10T05:30:00+00:00"


def test_오프셋이_있는_ISO8601을_정규화한다():
    assert to_utc_iso("2026-11-10T14:30:00+09:00") == "2026-11-10T05:30:00+00:00"


def test_타임존이_없으면_UTC로_간주한다():
    """표기가 없는 피드가 실제로 있다. 추측하지 않고 UTC로 고정한다."""
    assert to_utc_iso("2026-11-10T05:30:00") == "2026-11-10T05:30:00+00:00"


def test_파싱할_수_없으면_None을_돌려준다():
    """한 건의 날짜 오류로 수집 전체가 죽지 않게 한다."""
    assert to_utc_iso("언젠가") is None
    assert to_utc_iso("") is None
    assert to_utc_iso(None) is None


# --- 수집 윈도우 ---

def test_마지막_발송_시각부터_지금까지가_윈도우가_된다():
    now = datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc)
    last = datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc)

    start, end = compute_window(now=now, last_sent_at=last)

    assert start == last
    assert end == now


def test_주말을_쉰_월요일은_약_72시간이_된다():
    """금요일 발송 후 월요일 실행. 주말 해외 콘텐츠가 포함된다."""
    friday_sent = datetime(2026, 11, 6, 22, 20, tzinfo=timezone.utc)
    monday_now = datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc)

    start, end = compute_window(now=monday_now, last_sent_at=friday_sent)

    assert (end - start) == timedelta(hours=72)


def test_윈도우가_96시간을_넘지_않는다():
    """장애로 2주 멈춘 뒤 복구되어도 수집량이 폭증하지 않게 한다."""
    now = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)
    long_ago = now - timedelta(days=14)

    start, end = compute_window(now=now, last_sent_at=long_ago)

    assert (end - start) == timedelta(hours=MAX_WINDOW_HOURS)
    assert start == now - timedelta(hours=MAX_WINDOW_HOURS)


def test_발송_이력이_없으면_상한만큼_거슬러_올라간다():
    """최초 실행."""
    now = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)

    start, end = compute_window(now=now, last_sent_at=None)

    assert (end - start) == timedelta(hours=MAX_WINDOW_HOURS)


def test_윈도우_경계가_타임존_없는_값을_거부한다():
    """naive datetime을 섞으면 비교가 조용히 틀린다. 즉시 죽인다."""
    naive = datetime(2026, 11, 10, 0, 0)

    with pytest.raises(ValueError, match="타임존"):
        compute_window(now=naive, last_sent_at=None)


def test_KST가_UTC_플러스_9시간이다():
    assert KST.utcoffset(None) == timedelta(hours=9)


# --- 발송 요일 ---

def test_발송_cron이_KST_월금에_해당한다():
    """이 테스트가 없으면 요일이 한 칸 밀린 것을 수동 관찰로만 알 수 있다.

    증상이 "일주일에 한 번 이상한 날에 온다"라서 알아차리기까지 오래 걸린다.
    """
    assert SEND_CRON_UTC == "20 22 * * 0-4"

    # cron 0-4 = UTC 일~목. 2026-11-08이 일요일이다.
    assert _kst_weekdays_for_cron_days(8) == ["월", "화", "수", "목", "금"]


def test_cron_요일을_하나_밀면_월요일이_빠지고_토요일에_발송된다():
    """위 테스트가 실제로 무엇을 막는지 보여준다.

    cron을 1-5(UTC 월~금)로 쓰면 KST로는 화~토가 된다. 월요일은 주말
    해외 콘텐츠를 72시간 윈도우로 받는 날이라 가장 손실이 크다.
    """
    shifted = _kst_weekdays_for_cron_days(9)   # UTC 월요일부터

    assert shifted == ["화", "수", "목", "금", "토"]
    assert "월" not in shifted
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_timeutil.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.timeutil'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/lib/timeutil.py`:

```python
"""시각 처리 규칙을 한곳에 모은다.

규칙:
- 저장은 전부 UTC ISO 8601.
- 윈도우 계산도 UTC로 한다.
- KST는 화면 표시에만 쓴다.
"""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))

# 장애 복구 시 수집량·토큰 폭증을 막는 상한.
MAX_WINDOW_HOURS = 96

# 계획 3의 Actions 워크플로가 쓰는 발송 시각과 cron.
# 여기 두는 이유: 이것이 맞는지 테스트로 고정해야 한다. 틀리기 쉬운 이유가
# 두 겹이기 때문이다.
#   1. UTC 22:20 + 9시간은 "익일" 07:20이다 → KST 요일이 하루 앞선다
#   2. cron의 요일은 0 = 일요일인데 datetime.weekday()는 0 = 월요일이다
# 한 칸 밀리면 토요일에 발송되고 월요일이 빠진다 — 월요일은 주말 해외
# 콘텐츠를 72시간 윈도우로 받는 날이라 하필 가장 중요한 날이 사라진다.
SEND_HOUR_UTC = 22
SEND_MINUTE_UTC = 20
SEND_CRON_UTC = "20 22 * * 0-4"   # KST 월~금 07:20


def to_utc_iso(value: str | None) -> str | None:
    """RSS의 발행 시각 문자열을 UTC ISO 8601로 정규화한다.

    파싱 실패 시 예외를 던지지 않고 None을 돌려준다. 한 건의 날짜 오류로
    수집 전체가 중단되는 것을 막기 위함이다. 호출자가 None을 걸러낸다.
    """
    if not value:
        return None

    parsed: datetime | None = None

    # 1) RFC 822 / RFC 2822 — "Mon, 10 Nov 2026 14:30:00 +0900"
    #    국내 매체 RSS에서 가장 흔하다.
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = None

    # 2) ISO 8601 — "2026-11-10T05:30:00Z" 또는 "+09:00"
    if parsed is None:
        try:
            # fromisoformat은 "Z"를 직접 못 읽으므로 "+00:00"으로 바꿔준다.
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None

    # 타임존 표기가 없는 naive datetime은 UTC로 간주한다.
    # 추측해서 KST로 보정하면 9시간 틀리는 버그가 조용히 생긴다.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc).isoformat()


def _require_aware(moment: datetime, label: str) -> None:
    if moment.tzinfo is None:
        raise ValueError(f"{label}에 타임존이 없다. UTC를 명시해야 한다: {moment!r}")


def compute_window(
    *,
    now: datetime,
    last_sent_at: datetime | None,
) -> tuple[datetime, datetime]:
    """수집 윈도우 (시작, 끝)을 돌려준다.

    "마지막 발송 이후"라는 규칙 하나로 평일·주말·공휴일·장애 복구를 모두
    처리한다. 요일 분기가 없다.
    """
    _require_aware(now, "now")
    if last_sent_at is not None:
        _require_aware(last_sent_at, "last_sent_at")

    floor = now - timedelta(hours=MAX_WINDOW_HOURS)

    if last_sent_at is None:
        start = floor
    else:
        # max()로 상한을 적용한다. 오래 멈췄어도 96시간 전까지만 본다.
        start = max(last_sent_at, floor)

    return start, now
```

> **설명** — `*`가 인자 목록에 홀로 있으면 그 뒤는 **키워드 전용 인자**가 된다. `compute_window(now, last)` 처럼 순서로 넘기는 것을 막아, 두 시각을 바꿔 넣는 실수를 문법 차원에서 차단한다. `str | None`은 "문자열 또는 None"을 뜻하는 타입 힌트다. `datetime`에서 `tzinfo`가 `None`인 값을 naive, 있는 값을 aware라고 부르며, 둘을 비교하면 `TypeError`가 난다 — 그래서 `_require_aware`로 미리 막는다.

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_timeutil.py
```

Expected: `13 passed`

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/timeutil.py tests/test_timeutil.py
git commit -m "feat: 시각 정규화와 수집 윈도우 계산 (마지막 발송 이후, 상한 96h)"
```

---

## Task 4: 재시도 분류

HTTP든 LLM이든, 호출자가 알아야 하는 것은 상태 코드가 아니라 **"다시 하면 되나, 설정을 고쳐야 하나"** 둘 중 하나다. 갈래를 둘로만 묶으면 호출부마다 분기가 늘어나지 않는다.

**Files:**
- Create: `pipeline/lib/retry.py`
- Create: `tests/test_retry.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_retry.py`:

```python
import pytest

from pipeline.lib.retry import (
    MAX_DELAY,
    Permanent,
    Transient,
    backoff_delay,
    with_retry,
)


def test_한_번에_성공하면_한_번만_호출한다():
    calls = []

    def ok():
        calls.append(1)
        return "결과"

    assert with_retry(ok, sleep=lambda _: None) == "결과"
    assert len(calls) == 1


def test_일시적_실패는_재시도한다():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise Transient("일시 장애")
        return "결과"

    assert with_retry(flaky, attempts=3, sleep=lambda _: None) == "결과"
    assert len(calls) == 3


def test_재시도를_다_쓰면_마지막_예외를_올린다():
    with pytest.raises(Transient, match="계속 실패"):
        with_retry(lambda: (_ for _ in ()).throw(Transient("계속 실패")),
                   attempts=3, sleep=lambda _: None)


def test_영구_실패는_재시도하지_않는다():
    """설정 문제에 재시도를 걸면 시간과 비용만 쓴다."""
    calls = []

    def broken():
        calls.append(1)
        raise Permanent("404 주소가 없다")

    with pytest.raises(Permanent):
        with_retry(broken, attempts=5, sleep=lambda _: None)
    assert len(calls) == 1


def test_분류되지_않은_예외는_삼키지_않는다():
    """ZeroDivisionError 같은 코드 버그를 재시도로 가리면 안 된다."""
    with pytest.raises(ZeroDivisionError):
        with_retry(lambda: 1 / 0, sleep=lambda _: None)


def test_지수_백오프로_간격이_늘어난다():
    delays = []

    def always_transient():
        raise Transient("장애")

    with pytest.raises(Transient):
        with_retry(always_transient, attempts=4, sleep=delays.append, base_delay=1.0)

    # 마지막 시도 뒤에는 쉬지 않으므로 3번
    assert delays == [1.0, 2.0, 4.0]


def test_retry_after가_있으면_백오프보다_그것을_따른다():
    """429의 Retry-After 헤더를 무시하고 더 빨리 때리면 더 오래 막힌다."""
    delays = []

    def rate_limited():
        raise Transient("429", retry_after=7.0)

    with pytest.raises(Transient):
        with_retry(rate_limited, attempts=2, sleep=delays.append)

    assert delays == [7.0]


def test_간격에_상한이_있다():
    delays = []

    def slow():
        raise Transient("장애", retry_after=99999.0)

    with pytest.raises(Transient):
        with_retry(slow, attempts=2, sleep=delays.append)

    assert delays == [MAX_DELAY]


def test_백오프_계산이_상한을_넘지_않는다():
    assert backoff_delay(0, base_delay=1.0) == 1.0
    assert backoff_delay(1, base_delay=1.0) == 2.0
    assert backoff_delay(2, base_delay=1.0) == 4.0
    assert backoff_delay(20, base_delay=1.0) == MAX_DELAY


def test_Transient의_retry_after는_없을_수도_있다():
    assert Transient("장애").retry_after is None
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_retry.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.retry'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/lib/retry.py`:

```python
"""재시도 분류.

이 모듈의 요점은 예외를 두 갈래로만 나누는 것이다.

- Transient: 기다리면 된다. 429, 408, 5xx, 타임아웃, 연결 실패.
- Permanent: 설정을 고쳐야 한다. 401, 403, 404, 410, 주소 오타.

상태 코드별로 갈래를 늘리면 호출부마다 분기가 늘어나고, 결국 아무도
그 분기를 유지하지 않는다. "호출자가 뭘 해야 하는가"가 유일한 기준이다.
"""

import time
from typing import Callable, TypeVar

T = TypeVar("T")

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 1.0

# 한 번에 기다릴 수 있는 최대 시간. 서버가 Retry-After로 몇 시간을
# 요구해도 파이프라인이 그만큼 멈춰 있을 수는 없다.
MAX_DELAY = 30.0


class Transient(RuntimeError):
    """잠시 후 다시 하면 되는 실패.

    retry_after가 있으면(429의 Retry-After 헤더 등) 백오프 대신 그 값을 따른다.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class Permanent(RuntimeError):
    """설정을 고쳐야 하는 실패. 재시도는 시간과 비용만 쓴다."""


def backoff_delay(attempt: int, *, base_delay: float = DEFAULT_BASE_DELAY) -> float:
    """지수 백오프 간격. attempt는 0부터 센다."""
    return min(MAX_DELAY, base_delay * (2**attempt))


def with_retry(
    call: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
    base_delay: float = DEFAULT_BASE_DELAY,
) -> T:
    """Transient만 재시도한다.

    Permanent는 즉시 올린다. 분류되지 않은 예외도 즉시 올린다 —
    코드 버그(TypeError 등)를 재시도로 가리면 원인을 못 찾는다.
    """
    last: Transient | None = None

    for attempt in range(attempts):
        try:
            return call()
        except Permanent:
            # 잡아서 아무것도 하지 않고 그대로 올린다. 아래 except Transient에
            # 걸리지 않게 하려는 것이 아니라(둘은 형제다), 의도를 명시하기 위함이다.
            raise
        except Transient as error:
            last = error
            if attempt == attempts - 1:
                break   # 마지막 시도였다. 쉬지 않고 바로 빠져나간다.
            delay = (
                error.retry_after
                if error.retry_after is not None
                else backoff_delay(attempt, base_delay=base_delay)
            )
            sleep(min(delay, MAX_DELAY))

    assert last is not None   # attempts >= 1이면 반드시 설정된다
    raise last
```

> **설명** — `2**attempt`는 2의 거듭제곱이다(`**`가 Python의 거듭제곱 연산자). `TypeVar("T")`와 `Callable[[], T]`를 쓰면 "넘긴 함수가 돌려주는 타입이 그대로 반환형이 된다"를 타입 검사기가 안다. 예외 클래스를 `RuntimeError`에서 상속한 이유는, 아무것도 안 잡는 코드에서도 표준 예외처럼 보이게 하려는 것이다.
>
> **구문법 대조** — `float | None`은 Python 3.10부터 쓸 수 있다. 그 전에는 `typing.Optional[float]`로 썼고, 레거시 코드베이스에서는 여전히 흔하다. 둘은 **같은 뜻**이다. 파일 맨 위에 `from __future__ import annotations`를 넣으면 3.9에서도 `float | None`이라고 **쓸 수는** 있는데, 이건 어노테이션을 문자열로 미뤄 평가하는 기법이라 런타임에 타입을 읽는 라이브러리(pydantic 등)와 미묘하게 어긋날 수 있다. 이 프로젝트는 3.12를 쓰므로 그 기법이 필요 없다.

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_retry.py
```

Expected: `10 passed`

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/retry.py tests/test_retry.py
git commit -m "feat: 재시도 분류 — Transient/Permanent 2갈래, 지수 백오프, Retry-After 존중"
```

---

## Task 5: HTTP 수집과 상태 분류

**Files:**
- Create: `pipeline/lib/http.py`
- Create: `tests/test_http.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_http.py`:

```python
import httpx
import pytest

from pipeline.lib.http import (
    FetchResult,
    classify_status,
    fetch,
    parse_retry_after,
)
from pipeline.lib.retry import Permanent, Transient

URL = "https://example.com/rss"


def _response(status: int, **kwargs) -> httpx.Response:
    """테스트용 응답. httpx.Response를 직접 만들 수 있다."""
    kwargs.setdefault("request", httpx.Request("GET", URL))
    return httpx.Response(status, **kwargs)


# --- Retry-After 파싱 ---

def test_초_단위_숫자를_읽는다():
    assert parse_retry_after("7") == 7.0


def test_공백이_섞여도_읽는다():
    assert parse_retry_after("  7  ") == 7.0


def test_없으면_None이다():
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None


def test_HTTP_날짜_형식은_None으로_둔다():
    """드문 형식이다. 지수 백오프로 대체된다."""
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None


def test_음수는_0으로_만든다():
    assert parse_retry_after("-5") == 0.0


# --- 상태 코드 분류 ---

def test_2xx는_통과한다():
    assert classify_status(200, url=URL) is None
    assert classify_status(204, url=URL) is None


def test_429는_일시적이고_retry_after를_전달한다():
    with pytest.raises(Transient) as caught:
        classify_status(429, url=URL, retry_after=7.0)
    assert caught.value.retry_after == 7.0


def test_408과_5xx는_일시적이다():
    for status in (408, 425, 500, 502, 503, 504):
        with pytest.raises(Transient):
            classify_status(status, url=URL)


def test_501과_505는_영구적이다():
    """서버가 지원하지 않는 것이다. 기다려도 생기지 않는다."""
    for status in (501, 505):
        with pytest.raises(Permanent):
            classify_status(status, url=URL)


def test_403은_영구적이다():
    """봇 차단. 100번 해도 같다. 이 구분이 enrich에서 중요하다."""
    with pytest.raises(Permanent, match="403"):
        classify_status(403, url=URL)


def test_401_404_410도_영구적이다():
    for status in (400, 401, 404, 410, 451):
        with pytest.raises(Permanent):
            classify_status(status, url=URL)


def test_에러_메시지에_URL이_들어간다():
    """로그만 보고 어느 소스인지 알아야 한다."""
    with pytest.raises(Permanent, match="example.com"):
        classify_status(404, url=URL)


def test_상세_설명을_덧붙일_수_있다():
    """Claude API는 본문에 원인을 담는다. 계획 3의 슬랙도 마찬가지로
    channel_not_found 같은 이유를 본문에 담는다."""
    with pytest.raises(Permanent, match="channel_not_found"):
        classify_status(404, url=URL, detail="channel_not_found")


# --- 수집 ---

def test_성공하면_본문과_최종_주소를_돌려준다():
    result = fetch(URL, get=lambda *a, **k: _response(200, content=b"<rss/>"))

    assert isinstance(result, FetchResult)
    assert result.content == b"<rss/>"
    assert result.final_url == URL
    assert result.moved_from is None


def test_영구_리다이렉트를_거치면_원래_주소를_기록한다():
    """자동으로 따라가지만 sources.yaml을 고치라고 알려줘야 한다."""
    old = httpx.Request("GET", "https://old.example.com/rss")
    hop = httpx.Response(301, request=old,
                         headers={"location": URL})
    final = _response(200, content=b"<rss/>", history=[hop])

    result = fetch(URL, get=lambda *a, **k: final)

    assert result.moved_from == "https://old.example.com/rss"


def test_일시_리다이렉트는_기록하지_않는다():
    """302는 임시 이전이다. 설정을 고칠 일이 아니다."""
    old = httpx.Request("GET", "https://old.example.com/rss")
    hop = httpx.Response(302, request=old, headers={"location": URL})
    final = _response(200, content=b"<rss/>", history=[hop])

    assert fetch(URL, get=lambda *a, **k: final).moved_from is None


def test_429의_Retry_After를_예외에_담는다():
    def get(*a, **k):
        return _response(429, headers={"Retry-After": "12"})

    with pytest.raises(Transient) as caught:
        fetch(URL, get=get)
    assert caught.value.retry_after == 12.0


def test_타임아웃은_일시적이다():
    def get(*a, **k):
        raise httpx.ReadTimeout("시간 초과")

    with pytest.raises(Transient, match="시간|Timeout|timeout"):
        fetch(URL, get=get)


def test_연결_실패는_일시적이다():
    def get(*a, **k):
        raise httpx.ConnectError("연결 거부")

    with pytest.raises(Transient):
        fetch(URL, get=get)


def test_지원하지_않는_스킴은_영구적이다():
    """sources.yaml에 주소를 잘못 적은 경우다."""
    def get(*a, **k):
        raise httpx.UnsupportedProtocol("스킴 오류")

    with pytest.raises(Permanent):
        fetch(URL, get=get)


def test_리다이렉트_루프는_영구적이다():
    def get(*a, **k):
        raise httpx.TooManyRedirects("루프")

    with pytest.raises(Permanent):
        fetch(URL, get=get)


def test_InvalidURL도_영구적이다():
    """함정: httpx.InvalidURL은 httpx.HTTPError의 하위가 아니다.
    except httpx.HTTPError로는 잡히지 않으므로 따로 잡아야 한다."""
    assert not issubclass(httpx.InvalidURL, httpx.HTTPError)

    def get(*a, **k):
        raise httpx.InvalidURL("주소 형식 오류")

    with pytest.raises(Permanent):
        fetch(URL, get=get)
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_http.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.http'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/lib/http.py`:

```python
"""HTTP 수집과 상태 코드 분류.

수집(collect)·본문 확보(enrich)·LLM 예외 분류(llm)가 모두 이 모듈을 거친다.
계획 3의 카카오톡·슬랙 전송도 같은 규칙을 쓴다.
분류 규칙이 한곳에만 있어야 "403을 어디선 재시도하고 어디선 안 하는" 일이
생기지 않는다.
"""

from dataclasses import dataclass
from typing import Callable

import httpx

from pipeline.lib.retry import Permanent, Transient

DEFAULT_TIMEOUT = 20.0
USER_AGENT = "briefing-bot/0.1"

# 기다리면 되는 4xx. 429는 레이트 리밋, 408은 요청 타임아웃,
# 425는 "너무 이르다(Too Early)".
TRANSIENT_CLIENT_STATUSES = frozenset({408, 425, 429})

# 5xx 중에서도 이 둘은 영구적이다 — 서버가 그 기능을 지원하지 않는다.
PERMANENT_SERVER_STATUSES = frozenset({501, 505})

# 영구 이전. 자동으로 따라가되 설정을 고치라고 알려야 한다.
# 302/303/307은 임시 이전이므로 기록하지 않는다.
PERMANENT_REDIRECTS = frozenset({301, 308})


@dataclass(frozen=True)
class FetchResult:
    content: bytes
    final_url: str
    # 301/308을 거쳤으면 원래 주소. sources.yaml 갱신 신호다.
    moved_from: str | None = None


def parse_retry_after(value: str | None) -> float | None:
    """Retry-After 헤더를 초로 바꾼다.

    초 단위 숫자만 지원한다. HTTP-date 형식("Wed, 21 Oct ...")은 드물고,
    None을 돌려주면 호출자가 지수 백오프로 대체하므로 문제가 없다.
    """
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return max(0.0, seconds)


def classify_status(
    status: int,
    *,
    url: str,
    retry_after: float | None = None,
    detail: str = "",
) -> None:
    """2xx가 아니면 Transient 또는 Permanent로 분류해 던진다."""
    if 200 <= status < 300:
        return

    # 메시지에 URL을 넣는다. 로그만 보고 어느 소스인지 알아야 한다.
    suffix = f" — {detail}" if detail else ""
    message = f"{url} HTTP {status}{suffix}"

    if status in TRANSIENT_CLIENT_STATUSES:
        raise Transient(message, retry_after=retry_after)
    if status in PERMANENT_SERVER_STATUSES:
        raise Permanent(message)
    if 500 <= status < 600:
        raise Transient(message, retry_after=retry_after)

    # 나머지 4xx(400/401/403/404/410/451 등)는 전부 영구적이다.
    # 403은 봇 차단이라 재시도해도 같고, 404는 주소를 고쳐야 한다.
    raise Permanent(message)


GetFn = Callable[..., httpx.Response]


def _httpx_get(url: str, timeout: float, user_agent: str) -> httpx.Response:
    return httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": user_agent},
    )


def fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    user_agent: str = USER_AGENT,
    get: GetFn | None = None,
) -> FetchResult:
    """URL을 가져온다. 실패는 Transient/Permanent로 분류해 던진다."""
    getter = get or _httpx_get

    try:
        response = getter(url, timeout, user_agent)
    # --- 가장 구체적인 영구 실패부터 ---
    # httpx.InvalidURL은 httpx.HTTPError의 하위가 아니다. 따로 잡지 않으면
    # 주소 오타가 분류되지 않은 예외로 새어 나간다.
    except httpx.InvalidURL as error:
        raise Permanent(f"{url} 주소 형식 오류: {error}") from error
    except httpx.UnsupportedProtocol as error:
        raise Permanent(f"{url} 지원하지 않는 스킴: {error}") from error
    except httpx.TooManyRedirects as error:
        raise Permanent(f"{url} 리다이렉트 루프: {error}") from error
    # --- 일시적 전송 실패 ---
    except httpx.TimeoutException as error:
        raise Transient(f"{url} 시간 초과: {error}") from error
    except httpx.RequestError as error:
        # NetworkError(ConnectError/ReadError), ProtocolError 등.
        raise Transient(f"{url} 전송 실패: {type(error).__name__}: {error}") from error

    # 301/308을 거쳤으면 원래 주소를 기록한다.
    moved_from: str | None = None
    for hop in response.history:
        if hop.status_code in PERMANENT_REDIRECTS:
            moved_from = str(hop.url)
            break

    classify_status(
        response.status_code,
        url=url,
        retry_after=parse_retry_after(response.headers.get("retry-after")),
    )

    return FetchResult(
        content=response.content,
        final_url=str(response.url),
        moved_from=moved_from,
    )
```

> **설명** — `except` 절은 **구체적인 것부터** 쓴다. `UnsupportedProtocol`과 `TooManyRedirects`는 둘 다 `RequestError`의 하위라서, `except httpx.RequestError`를 먼저 쓰면 그 둘이 거기서 잡혀 Transient로 잘못 분류된다. `@dataclass(frozen=True)`는 생성 후 변경 불가한 데이터 묶음을 만든다(여기서는 pydantic이 필요 없어서 표준 라이브러리를 썼다 — 검증할 게 없고 LLM 출력도 아니다). `raise ... from error`는 원래 예외를 체인으로 보존해 트레이스백에 둘 다 남는다.
>
> **구문법 대조** — `frozenset({...})`은 변경 불가능한 집합이고, `in` 검사가 리스트보다 빠르다. 구형 코드에서는 `Dict[str, int]`, `List[str]`, `Set[int]`처럼 `typing` 모듈의 대문자 별칭을 썼다. Python 3.9부터 `dict[str, int]`, `list[str]`, `set[int]`처럼 **내장 타입을 그대로** 쓸 수 있고, 대문자 별칭은 유지만 되는 상태다. 레거시 코드를 읽을 때는 `List[str]`과 `list[str]`이 같은 뜻이라고 보면 된다.

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_http.py
```

Expected: `22 passed`

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/http.py tests/test_http.py
git commit -m "feat: HTTP 수집과 상태 분류 (403/404 영구, 429/5xx 일시, InvalidURL 함정 처리)"
```

---

## Task 6: 데이터 계약

단계 간 JSON이 암묵적 인터페이스가 되는 것을 막는다.

> **스펙에서 한 가지 변경** — 스펙은 `dataclass(frozen=True)`로 적었지만 **pydantic `BaseModel`을 쓴다.** 이유는 하나다: `messages.parse()`에 넘기는 LLM 출력 스키마도 pydantic이어야 하므로, 계약을 pydantic으로 통일하면 `to_dict`/`from_dict`를 손으로 쓸 필요가 없고(`model_dump`/`model_validate`가 공짜) 검증도 따라온다. dataclass를 쓰면 같은 모양을 두 번 정의하게 된다.

**Files:**
- Create: `pipeline/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_models.py`:

```python
import pytest
from pydantic import ValidationError

from pipeline.models import (
    Article,
    ArticlesBundle,
    Briefing,
    RankedBundle,
    RankedItem,
    RawBundle,
    RawItem,
    ScoreItem,
    ScoreSheet,
    SourceError,
    Summary,
)


def _raw() -> RawItem:
    return RawItem(
        source="토스_기술블로그",
        title="결제 서버 P99 40ms 달성기",
        url="https://toss.tech/article/payment-latency",
        published="2026-11-10T05:30:00+00:00",
        excerpt="지연의 원인을 추적한 과정을 정리했다.",
    )


def test_RawItem이_JSON_왕복을_견딘다():
    item = _raw()
    restored = RawItem.model_validate(item.model_dump())
    assert restored == item


def test_모델이_불변이다():
    """단계 간 데이터는 중간에 바뀌면 안 된다."""
    item = _raw()
    with pytest.raises(ValidationError):
        item.title = "다른 제목"


def test_정의되지_않은_필드를_거부한다():
    """오타난 키가 조용히 통과하면 다음 단계에서 터진다."""
    with pytest.raises(ValidationError):
        RawItem(
            source="s", title="t", url="u", published="p", excerpt="e",
            titel="오타",
        )


def test_점수는_0에서_100_사이여야_한다():
    with pytest.raises(ValidationError):
        ScoreItem(index=0, score=101, reason="r", topic="AI")
    with pytest.raises(ValidationError):
        ScoreItem(index=0, score=-1, reason="r", topic="AI")


def test_헤드라인이_30자를_넘으면_거부한다():
    """카톡 200자 제약에서 파생된 규칙. 모델이 직접 강제한다."""
    article = Article(ranked=_ranked(), body="본문", body_source="trafilatura")
    with pytest.raises(ValidationError):
        Summary(
            article=article,
            headline="가" * 31,
            bullets=["요점"],
            why_it_matters="중요한 이유",
        )


def test_헤드라인이_30자면_통과한다():
    article = Article(ranked=_ranked(), body="본문", body_source="trafilatura")
    summary = Summary(
        article=article,
        headline="가" * 30,
        bullets=["요점"],
        why_it_matters="중요한 이유",
    )
    assert len(summary.headline) == 30


def _ranked() -> RankedItem:
    return RankedItem(item=_raw(), score=82, reason="관심사 정중앙", topic="backend")


def test_body_source는_정해진_값만_받는다():
    with pytest.raises(ValidationError):
        Article(ranked=_ranked(), body="본문", body_source="아무거나")


def test_번들이_중첩_JSON_왕복을_견딘다():
    """파일로 쓰고 읽는 경로 전체를 확인한다."""
    bundle = RawBundle(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        items=[_raw()],
        source_counts={"토스_기술블로그": 1},
        errors=[],
    )
    restored = RawBundle.model_validate(bundle.model_dump())
    assert restored == bundle
    assert restored.items[0].title == "결제 서버 P99 40ms 달성기"


def test_SourceError는_실패_성격을_요구한다():
    """kind가 없으면 404와 503이 같은 기록이 된다."""
    with pytest.raises(ValidationError):
        SourceError(source="s", message="m")


def test_SourceError의_kind는_정해진_값만_받는다():
    with pytest.raises(ValidationError):
        SourceError(source="s", kind="아무거나", message="m")


def test_폴백_이유는_없어도_된다():
    article = Article(ranked=_ranked(), body="본문", body_source="trafilatura")
    assert article.fallback_reason is None


def test_폴백_이유를_담을_수_있다():
    article = Article(
        ranked=_ranked(), body="발췌", body_source="rss_excerpt",
        fallback_reason="HTTP 403 — 봇 차단",
    )
    assert article.fallback_reason == "HTTP 403 — 봇 차단"


def test_에러가_담긴_번들도_왕복한다():
    bundle = RawBundle(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        items=[],
        source_counts={"깨진소스": 0},
        errors=[SourceError(source="깨진소스", kind="config", message="HTTP 404")],
    )
    restored = RawBundle.model_validate(bundle.model_dump())
    assert restored.errors[0].kind == "config"


def test_ScoreSheet가_LLM_출력_모양을_담는다():
    sheet = ScoreSheet(scores=[ScoreItem(index=0, score=80, reason="r", topic="AI")])
    assert sheet.scores[0].index == 0


def test_빈_브리핑도_유효하다():
    """임계값 통과분이 0건인 날이 정상 상태다."""
    briefing = Briefing(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        summaries=[],
        considered=10,
    )
    assert briefing.summaries == []


def test_최고_점수는_없어도_된다():
    """수집이 0건이면 최고 점수가 존재하지 않는다."""
    bundle = RankedBundle(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        selected=[], all_scores=[],
    )
    assert bundle.max_score is None


def test_RankedBundle과_ArticlesBundle이_왕복한다():
    ranked = RankedBundle(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        selected=[_ranked()],
        all_scores=[ScoreItem(index=0, score=82, reason="관심사 정중앙", topic="backend")],
    )
    assert RankedBundle.model_validate(ranked.model_dump()) == ranked

    articles = ArticlesBundle(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        articles=[Article(ranked=_ranked(), body="본문", body_source="rss_excerpt")],
    )
    assert ArticlesBundle.model_validate(articles.model_dump()) == articles
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_models.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.models'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/models.py`:

```python
"""단계 간 데이터 계약.

각 단계는 자기 번들을 JSON으로 쓰고, 다음 단계가 그것을 읽는다. 여기서
모양을 한 번만 정의해 "오타난 키가 조용히 통과하는" 사고를 막는다.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 카톡 텍스트 템플릿이 200자이고, 머리글 약 20자 + 건당 번호 3자를 빼면
# 헤드라인에 쓸 수 있는 길이가 30자다. 모델이 직접 강제한다.
HEADLINE_MAX = 30

# 본문 추출 경로. 폴백이 일어났는지 기록해 품질 저하를 추적한다.
BodySource = Literal["trafilatura", "rss_excerpt"]


class Contract(BaseModel):
    """모든 계약 모델의 공통 설정."""

    # frozen: 생성 후 변경 금지. 단계 간 데이터는 흘러가며 바뀌면 안 된다.
    # extra="forbid": 정의하지 않은 키가 들어오면 즉시 에러.
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- 01 수집 ---

class RawItem(Contract):
    source: str
    title: str
    url: str                # 정규화된 URL
    published: str          # UTC ISO 8601
    excerpt: str


# 수집 실패의 성격. 계획 3의 소스 침묵 경고가 "주소가 죽은 소스"와
# "일시적으로 불안정한 소스"를 구분하는 근거가 된다.
#   config    — 설정을 고쳐야 한다 (404/403/주소 오타)
#   transient — 기다리면 된다 (429/5xx/타임아웃). 재시도 후에도 실패한 경우
#   moved     — 301/308로 이전됐다. 실패는 아니지만 sources.yaml을 고쳐야 한다
ErrorKind = Literal["config", "transient", "moved"]


class SourceError(Contract):
    source: str
    kind: ErrorKind
    message: str


class RawBundle(Contract):
    window_start: str
    window_end: str
    items: list[RawItem]
    source_counts: dict[str, int]   # 소스 침묵 감지에 쓴다
    errors: list[SourceError]


# --- 02 선별 ---

class ScoreItem(Contract):
    """LLM이 돌려주는 채점 결과 한 건. 입력을 되돌려받지 않고 index로 참조한다."""

    index: int = Field(ge=0)
    score: int = Field(ge=0, le=100)
    reason: str             # 탈락 이유를 나중에 조회하기 위해 항상 남긴다
    topic: str


class ScoreSheet(Contract):
    """LLM 구조화된 출력의 최상위 모양."""

    scores: list[ScoreItem]


class RankedItem(Contract):
    item: RawItem
    score: int = Field(ge=0, le=100)
    reason: str
    topic: str


class RankedBundle(Contract):
    window_start: str
    window_end: str
    selected: list[RankedItem]      # 상위 N건
    all_scores: list[ScoreItem]     # 전체 — 탈락 이유 조회용
    # 가중치 적용 후 최고 점수. 0건인 날 화면이 "최고 54점 / 기준 60점"을
    # 보여주는 데 쓴다 — 0건이면 articles가 비어서 다른 데서 알 수 없다.
    max_score: int | None = None


# --- 03 본문 ---

class Article(Contract):
    ranked: RankedItem
    body: str
    body_source: BodySource
    # 폴백이 일어난 이유. 경고를 "2건 발췌"가 아니라
    # "403 봇 차단 2건"으로 쓸 수 있게 한다. 폴백이 없으면 None.
    fallback_reason: str | None = None


class ArticlesBundle(Contract):
    window_start: str
    window_end: str
    articles: list[Article]


# --- 04 요약 ---

class SummaryDraft(Contract):
    """LLM이 돌려주는 요약 한 건."""

    index: int = Field(ge=0)
    headline: str = Field(min_length=1, max_length=HEADLINE_MAX)
    bullets: list[str] = Field(min_length=1, max_length=3)
    why_it_matters: str


class SummarySheet(Contract):
    """LLM 구조화된 출력의 최상위 모양. 임계값 미달은 LLM이 아예 빼고 돌려준다."""

    summaries: list[SummaryDraft]


class Summary(Contract):
    article: Article
    headline: str = Field(min_length=1, max_length=HEADLINE_MAX)
    bullets: list[str] = Field(min_length=1, max_length=3)
    why_it_matters: str


class Briefing(Contract):
    window_start: str
    window_end: str
    summaries: list[Summary]    # 0건이 정상 상태다
    considered: int             # 요약 후보로 올린 건수 (적중률 추적용)
```

> **설명** — pydantic의 `BaseModel`은 타입 힌트를 **실행 시점 검증**으로 바꿔준다. `Field(ge=0, le=100)`은 "0 이상 100 이하", `Field(max_length=30)`은 문자열 길이 상한이다. `Literal["a", "b"]`는 두 값만 허용하는 타입이다. `model_config`의 `extra="forbid"`가 중요하다 — 기본값은 모르는 키를 조용히 버리는데, 그러면 오타가 다음 단계에서 `KeyError`로 터진다. `model_dump()`는 dict로, `model_validate()`는 dict에서 모델로 바꾼다.

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_models.py
```

Expected: `17 passed`

- [ ] **Step 5: sanity 테스트 삭제 후 전체 실행**

```bash
rm tests/test_sanity.py
pytest
```

Expected: 전부 통과, 실패 0. (태스크를 진행하며 개수가 늘어나므로 숫자가 아니라 **실패가 0인지**를 본다)

- [ ] **Step 6: 커밋**

```bash
git add pipeline/models.py tests/test_models.py
git rm tests/test_sanity.py
git commit -m "feat: 단계 간 데이터 계약 (pydantic, 불변, 미정의 키 거부)"
```

---

## Task 7: 환경변수 접근

**Files:**
- Create: `pipeline/lib/secrets.py`
- Create: `tests/test_secrets.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_secrets.py`:

```python
import pytest

from pipeline.lib.secrets import optional, require


def test_값이_있으면_돌려준다(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "값")
    assert require("TEST_KEY") == "값"


def test_없으면_즉시_죽는다(monkeypatch):
    """파이프라인 중간에 터지는 것보다 시작할 때 죽는 게 낫다."""
    monkeypatch.delenv("MISSING_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MISSING_KEY"):
        require("MISSING_KEY")


def test_빈_문자열도_없는_것으로_취급한다(monkeypatch):
    """Actions에서 Secret 이름을 틀리면 빈 문자열이 주입된다."""
    monkeypatch.setenv("EMPTY_KEY", "")
    with pytest.raises(RuntimeError, match="EMPTY_KEY"):
        require("EMPTY_KEY")


def test_에러_메시지가_해결_방법을_알려준다(monkeypatch):
    monkeypatch.delenv("SOME_KEY", raising=False)
    with pytest.raises(RuntimeError, match=r"\.env"):
        require("SOME_KEY")


def test_optional은_없으면_기본값을_돌려준다(monkeypatch):
    monkeypatch.delenv("NOPE", raising=False)
    assert optional("NOPE") is None
    assert optional("NOPE", "기본값") == "기본값"
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_secrets.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.secrets'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/lib/secrets.py`:

```python
"""비밀값 접근 단일 통로.

로컬은 .env 파일, GitHub Actions는 Secrets가 환경변수로 주입된다.
호출하는 코드는 그 차이를 모른다.
"""

import os

from dotenv import load_dotenv

# .env가 있으면 환경변수로 올린다. 없으면 조용히 통과한다.
# override=False라 이미 설정된 환경변수를 .env가 덮어쓰지 않는다 —
# Actions에서 Secret이 .env보다 우선해야 한다.
load_dotenv(override=False)


def require(key: str) -> str:
    """환경변수를 읽는다. 없거나 비어 있으면 즉시 RuntimeError."""
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"환경변수 {key}가 없다. "
            f"로컬이면 .env에, GitHub Actions면 리포지토리 Secrets에 추가한다. "
            f"필요한 키 목록은 .env.example을 본다."
        )
    return value


def optional(key: str, default: str | None = None) -> str | None:
    """없어도 되는 환경변수를 읽는다."""
    value = os.environ.get(key)
    return value if value else default
```

> **설명** — `os.environ`은 환경변수를 딕셔너리처럼 다루는 표준 라이브러리 객체다. `python-dotenv`의 `load_dotenv()`는 `.env` 파일을 읽어 환경변수로 올린다. 테스트의 `monkeypatch`는 pytest가 제공하는 fixture로, 환경변수를 임시로 바꾸고 테스트가 끝나면 **자동으로 원복**한다 — 직접 `os.environ`을 고치면 다른 테스트에 영향이 남는다. `if not value`는 `None`과 빈 문자열을 한 번에 걸러낸다.

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_secrets.py
```

Expected: `5 passed`

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/secrets.py tests/test_secrets.py
git commit -m "feat: 환경변수 접근 단일 통로 (없으면 즉시 실패)"
```

---

## Task 8: 로컬 저장소 (중간 산출물)

**Files:**
- Create: `pipeline/lib/store.py`
- Create: `tests/test_local_store.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_local_store.py`:

```python
import pytest

from pipeline.lib.store import LocalStore
from pipeline.models import RawBundle, RawItem


def _bundle() -> RawBundle:
    return RawBundle(
        window_start="2026-11-09T22:20:00+00:00",
        window_end="2026-11-10T22:20:00+00:00",
        items=[RawItem(
            source="s", title="제목", url="https://e.com/a",
            published="2026-11-10T01:00:00+00:00", excerpt="발췌",
        )],
        source_counts={"s": 1},
        errors=[],
    )


def test_쓰고_읽으면_같은_값이_나온다(tmp_path):
    store = LocalStore(root=tmp_path, date="2026-11-10")
    store.write("raw", _bundle())

    assert store.read("raw", RawBundle) == _bundle()


def test_날짜별_디렉터리에_저장한다(tmp_path):
    store = LocalStore(root=tmp_path, date="2026-11-10")
    store.write("raw", _bundle())

    assert (tmp_path / "2026-11-10" / "raw.json").exists()


def test_한글이_그대로_저장된다(tmp_path):
    """\\uXXXX로 이스케이프되면 파일을 눈으로 볼 수 없다."""
    store = LocalStore(root=tmp_path, date="2026-11-10")
    store.write("raw", _bundle())

    text = (tmp_path / "2026-11-10" / "raw.json").read_text(encoding="utf-8")
    assert "제목" in text


def test_없는_파일을_읽으면_친절한_에러가_난다(tmp_path):
    """"앞 단계를 먼저 돌려라"를 알려줘야 한다."""
    store = LocalStore(root=tmp_path, date="2026-11-10")
    with pytest.raises(FileNotFoundError, match="raw"):
        store.read("raw", RawBundle)


def test_다른_날짜는_섞이지_않는다(tmp_path):
    LocalStore(root=tmp_path, date="2026-11-10").write("raw", _bundle())
    other = LocalStore(root=tmp_path, date="2026-11-11")

    with pytest.raises(FileNotFoundError):
        other.read("raw", RawBundle)
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_local_store.py
```

Expected: FAIL — `ImportError: cannot import name 'LocalStore'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/lib/store.py`:

```python
"""저장소.

- LocalStore: 단계 간 중간 산출물 (날짜별 JSON 파일)
- RemoteStore: 실행 이력·발행 이력·본문 (Supabase) — Task 10에서 추가
"""

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

# TypeVar는 "어떤 타입이 들어와도 같은 타입으로 나간다"를 타입 검사기에
# 알려준다. read("raw", RawBundle)의 반환형이 RawBundle로 추론된다.
TModel = TypeVar("TModel", bound=BaseModel)

DEFAULT_ROOT = Path("data")


class LocalStore:
    """날짜별 디렉터리에 단계 산출물을 JSON으로 읽고 쓴다."""

    def __init__(self, *, date: str, root: Path | None = None) -> None:
        self._dir = (root or DEFAULT_ROOT) / date

    def write(self, name: str, model: BaseModel) -> Path:
        # parents=True: 중간 디렉터리까지 만든다
        # exist_ok=True: 이미 있어도 에러 내지 않는다
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{name}.json"

        # ensure_ascii=False여야 한글이 그대로 저장된다. 기본값(True)이면
        # "제목"처럼 바뀌어 파일을 눈으로 디버깅할 수 없다.
        path.write_text(
            json.dumps(model.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def read(self, name: str, model_type: type[TModel]) -> TModel:
        path = self._dir / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"{path}가 없다. '{name}'을 만드는 앞 단계를 먼저 실행한다."
            )
        return model_type.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def exists(self, name: str) -> bool:
        return (self._dir / f"{name}.json").exists()
```

> **설명** — `pathlib.Path`는 경로를 문자열이 아닌 객체로 다루며, `/` 연산자로 경로를 이어붙인다(`root / date / "raw.json"`). 문자열 연결보다 OS 차이에 안전하다. `type[TModel]`은 "클래스 자체"를 받는 타입 힌트다(인스턴스가 아니라 `RawBundle`이라는 클래스를 넘긴다). pytest의 `tmp_path` fixture는 테스트마다 빈 임시 디렉터리를 만들어주고 끝나면 정리한다.

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_local_store.py
```

Expected: `5 passed`

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/store.py tests/test_local_store.py
git commit -m "feat: 로컬 저장소 — 날짜별 중간 산출물 JSON 읽기/쓰기"
```

---

## Task 9: Supabase 스키마

SQL이므로 단위 테스트가 아니라 **실제 적용 후 권한 검증**으로 확인한다.

**Files:**
- Create: `supabase/schema.sql`
- Create: `supabase/verify_permissions.sql`
- Create: `scripts/verify_anon_access.sh`

- [ ] **Step 1: Supabase 프로젝트 생성**

1. https://supabase.com 에서 새 프로젝트 생성 (리전은 `Northeast Asia (Seoul)`)
   - Database Password는 비밀번호 관리자에 저장한다. 지금은 쓰지 않지만 나중에
     `psql`로 붙을 때 필요하고, 분실하면 재설정해야 한다
2. 값 세 개를 `.env`에 넣는다. **받는 곳이 두 군데로 나뉜다.**

| `.env` 키 | 어디서 | 형태 |
|---|---|---|
| `SUPABASE_URL` | **Connect 다이얼로그** (프로젝트 상단 Connect 버튼) | `https://<ref>.supabase.co` |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | 같은 Connect 다이얼로그 (계획 2에서 쓴다) | `sb_publishable_…` |
| `SUPABASE_SECRET_KEY` | **Settings → API Keys** | `sb_secret_…` |

> ⚠️ **`Settings → API` 페이지는 존재하지 않는다.** 문서가 명시한다 —
> "모든 키는 Settings → API Keys에 있고, 별도의 Settings → API 페이지는 없다."
> Connect 다이얼로그는 **publishable 키만** 보여주므로 secret은 API Keys에서 받는다.
>
> **URL은 주소창에서도 만들 수 있다.** 대시보드 URL이
> `supabase.com/dashboard/project/<ref>` 이므로 `https://<ref>.supabase.co`가
> 그 프로젝트의 URL이다.
>
> API Keys 페이지에는 레거시 `anon`/`service_role`도 함께 있다.
> **`eyJ`로 시작하는 긴 JWT가 아니라 `sb_secret_`로 시작하는 짧은 것**을 고른다.
> 레거시 키는 2026년 말에 폐지된다.

- [ ] **Step 2: `supabase/schema.sql` 작성**

```sql
-- IT 브리핑 Phase 1 스키마
--
-- 공개/비공개 경계가 이 파일의 핵심이다:
--   articles        — 요약·링크. anon 읽기 허용 (공개 페이지가 읽는다)
--   article_bodies  — 기사 본문. anon 접근 전면 차단 (재배포가 되면 안 된다)
--   runs            — 실행 이력. anon 접근 차단
--   reactions/clicks — anon 삽입만 허용 (계획 2)
--   notes           — anon 읽기·삽입 허용 (내 메모, 내 페이지) (계획 2)
--   kakao_auth      — 토큰. anon 접근 차단 (계획 3)
--
-- 모든 식별자는 소문자. 시각은 timestamptz. 길이 제한 없는 text.

-- ---------------------------------------------------------------
-- 테이블
-- ---------------------------------------------------------------

-- 발행된 글의 요약과 메타. 공개 가능한 것만 담는다.
create table if not exists public.articles (
  -- bigint identity: 순차 증가라 인덱스 삽입이 뒤쪽에 몰려 효율적이다.
  -- 랜덤 uuid는 삽입이 인덱스 전체에 흩어져 불리하다.
  id             bigint generated always as identity primary key,
  briefing_date  date        not null,
  -- 정규화된 URL. unique가 중복 발행을 DB 차원에서 막고, 조회 인덱스도 겸한다.
  url            text        not null unique,
  source         text        not null,
  published_at   timestamptz not null,
  headline       text        not null,
  bullets        jsonb       not null default '[]'::jsonb,
  why_it_matters text        not null,
  topic          text        not null,
  score          int         not null,
  -- LLM의 판단 근거. "왜 이게 뽑혔나"를 나중에 조회한다.
  reason         text        not null,
  created_at     timestamptz not null default now(),

  constraint articles_score_range check (score between 0 and 100),
  -- 카톡 200자 제약에서 파생. 애플리케이션과 DB 양쪽에서 막는다.
  constraint articles_headline_len check (char_length(headline) <= 30)
);

-- 기사 본문. 별도 테이블로 분리해 anon에게 권한을 아예 주지 않는다.
-- Phase 3의 임베딩 컬럼도 여기에 추가한다.
create table if not exists public.article_bodies (
  article_id      bigint primary key references public.articles(id) on delete cascade,
  body            text not null,
  body_source     text not null,
  -- 폴백이 일어난 이유. 폴백이 없으면 NULL. 과거 기록에서
  -- "이 소스는 늘 403이 난다"를 확인할 수 있다.
  fallback_reason text,
  created_at      timestamptz not null default now(),

  constraint article_bodies_source_enum
    check (body_source in ('trafilatura', 'rss_excerpt'))
);

-- 실행 이력. 윈도우 계산·멱등성 판정·소스 침묵 감지가 모두 이걸 읽는다.
create table if not exists public.runs (
  id               bigint generated always as identity primary key,
  window_start     timestamptz not null,
  window_end       timestamptz not null,
  -- 전송 성공 시각. status='failed'인 행에서는 NULL이다.
  sent_at          timestamptz,
  -- 전송이 실패한 실행도 남긴다. source_counts가 소스 침묵 경고의 유일한
  -- 입력이므로, 실패한 날이 빠지면 경고가 그만큼 늦어진다.
  status           text        not null,
  collected_count  int         not null default 0,   -- 중복 제거 후 수집 건수
  considered_count int         not null default 0,   -- 요약 후보로 올린 건수
  max_score        int,                              -- 수집 0건이면 NULL
  published_count  int         not null default 0,
  -- {"토스_기술블로그": 3, "전자신문_오피니언": 0} — 3회 연속 0건이면 경고
  source_counts    jsonb       not null default '{}'::jsonb,
  input_tokens     int,
  errors           jsonb       not null default '[]'::jsonb,

  constraint runs_status_enum check (status in ('sent', 'failed')),
  -- 'sent'면 sent_at이 있어야 하고 'failed'면 없어야 한다. 애플리케이션
  -- 버그로 둘이 어긋나면 윈도우 계산이 조용히 틀어지므로 DB가 막는다.
  constraint runs_sent_at_matches_status check (
    (status = 'sent' and sent_at is not null)
    or (status = 'failed' and sent_at is null)
  )
);

-- 좋아요 (계획 2)
--
-- user_id가 지금부터 있는 이유: 페이지가 공개이고 인증이 없으므로 누구나
-- 좋아요를 누를 수 있다. 그런데 Phase 2는 "내 좋아요"를 선별 프롬프트에
-- 주입한다 — 낯선 사람의 클릭이 내 큐레이션 기준을 바꾼다.
-- 인증은 지금 켜지 않는다. 컬럼만 두면 전부 NULL("아마 나")이 되고,
-- 나중에 Auth를 켜는 순간 where user_id = auth.uid()로 바로 걸러진다.
-- 처음부터 두면 마이그레이션이 없다. 이것이 "지금 하면 싸고 나중에 하면
-- 비싼" 유일한 항목이다.
create table if not exists public.reactions (
  id         bigint generated always as identity primary key,
  article_id bigint not null references public.articles(id) on delete cascade,
  user_id    uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

-- 클릭 (계획 2)
create table if not exists public.clicks (
  id         bigint generated always as identity primary key,
  article_id bigint not null references public.articles(id) on delete cascade,
  user_id    uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

-- 짧은 메모와 태그 (계획 2)
create table if not exists public.notes (
  id         bigint generated always as identity primary key,
  article_id bigint not null references public.articles(id) on delete cascade,
  user_id    uuid references auth.users(id) on delete set null,
  text       text   not null,
  tags       jsonb  not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

-- 카카오 리프레시 토큰 (계획 3). 단일 행만 쓴다.
create table if not exists public.kakao_auth (
  id                        int primary key default 1,
  refresh_token             text        not null,
  refresh_token_expires_at  timestamptz not null,
  updated_at                timestamptz not null default now(),

  constraint kakao_auth_single_row check (id = 1)
);

-- ---------------------------------------------------------------
-- 인덱스
-- ---------------------------------------------------------------

-- 날짜별 페이지 조회
create index if not exists articles_briefing_date_idx
  on public.articles (briefing_date desc);

-- 마지막 발송 시각 조회 (윈도우 계산이 매 실행마다 쓴다).
-- 부분 인덱스다 — 그 조회가 항상 status='sent'를 거치므로 실패한 행을
-- 인덱스에서 빼면 더 작고 빠르다.
create index if not exists runs_sent_at_idx
  on public.runs (sent_at desc) where status = 'sent';

-- 외래 키 컬럼에는 인덱스를 만든다. 없으면 부모 행 삭제 시 자식 테이블을
-- 전체 스캔하고, article_id로 집계할 때도 느리다.
create index if not exists reactions_article_id_idx on public.reactions (article_id);
create index if not exists clicks_article_id_idx    on public.clicks (article_id);
create index if not exists notes_article_id_idx     on public.notes (article_id);

-- user_id도 외래 키다. Phase 2가 "내 것만" 거르는 질의를 쓰므로 인덱스를
-- 둔다. 지금은 전부 NULL이어서 인덱스가 거의 비어 있다 — 비용이 없다.
create index if not exists reactions_user_id_idx on public.reactions (user_id);
create index if not exists clicks_user_id_idx    on public.clicks (user_id);
create index if not exists notes_user_id_idx     on public.notes (user_id);

-- ---------------------------------------------------------------
-- RLS 활성화
-- ---------------------------------------------------------------
-- RLS를 켜고 정책을 만들지 않으면 그 역할은 전부 거부된다.
-- service_role은 RLS를 우회하므로 파이프라인은 영향받지 않는다.

alter table public.articles       enable row level security;
alter table public.article_bodies enable row level security;
alter table public.runs           enable row level security;
alter table public.reactions      enable row level security;
alter table public.clicks         enable row level security;
alter table public.notes          enable row level security;
alter table public.kakao_auth     enable row level security;

-- ---------------------------------------------------------------
-- 권한: 먼저 전부 회수하고, 필요한 것만 다시 부여
-- ---------------------------------------------------------------
-- Supabase는 public 스키마의 새 테이블에 anon/authenticated 권한을
-- 기본 부여한다. 따라서 명시적으로 회수해야 한다.
-- 테이블 권한과 RLS 정책은 AND 조건이다 — 둘 다 통과해야 접근된다.

revoke all on public.articles       from anon, authenticated;
revoke all on public.article_bodies from anon, authenticated;
revoke all on public.runs           from anon, authenticated;
revoke all on public.reactions      from anon, authenticated;
revoke all on public.clicks         from anon, authenticated;
revoke all on public.notes          from anon, authenticated;
revoke all on public.kakao_auth     from anon, authenticated;

-- articles: 공개 페이지가 읽는다
grant select on public.articles to anon;
create policy articles_public_read on public.articles
  for select to anon using (true);

-- reactions/clicks: 삽입만. 조회는 service_role(= 나)만 한다.
-- identity 컬럼은 시퀀스 권한을 따로 주지 않아도 삽입된다(serial과 다름).
-- with check (user_id is null): anon이 삽입하는 행은 user_id가 반드시
-- 비어 있어야 한다. 이것이 없으면 인증을 켠 뒤에 anon 키로 남의 user_id를
-- 적어 넣을 수 있다 — 위장 경로를 처음부터 막는다. 인증된 사용자는
-- 그때 별도 정책(auth.uid() = user_id)으로 삽입한다.
grant insert on public.reactions to anon;
create policy reactions_public_insert on public.reactions
  for insert to anon with check (user_id is null);

grant insert on public.clicks to anon;
create policy clicks_public_insert on public.clicks
  for insert to anon with check (user_id is null);

-- notes: 내 메모를 내 페이지에서 쓰고 읽는다.
-- 다수 사용자로 가면 이 select 정책은 남의 메모까지 노출하므로
-- auth.uid() = user_id로 좁혀야 한다 (스펙 2.1 참조).
grant select, insert on public.notes to anon;
create policy notes_public_read on public.notes
  for select to anon using (true);
create policy notes_public_insert on public.notes
  for insert to anon with check (user_id is null);

-- article_bodies / runs / kakao_auth: anon 정책을 만들지 않는다.
-- 권한도 회수했고 정책도 없으므로 이중으로 차단된다.

-- ---------------------------------------------------------------
-- 파이프라인(service_role) 권한
-- ---------------------------------------------------------------
-- 파이프라인은 secret 키로 접속하고, 그것은 service_role 역할이 된다.
-- service_role은 BYPASSRLS지만 **테이블 grant는 별개다** — RLS를 우회하는
-- 것과 테이블에 닿을 수 있는 것은 다른 층이다.
--
-- Supabase가 기본으로 주지만, Data API 설정의 "Automatically expose new
-- tables"를 끈 프로젝트에서 service_role이 어떻게 되는지가 문서로 명확하지
-- 않다(그 설정은 "Data API가 쓰는 권한을 회수한다"고만 말한다).
-- 명시해두면 중복이어도 무해하고, 빠졌을 때 겪는 42501 에러를 피한다.
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;
```

> **설명** — `generated always as identity`는 자동 증가 정수 기본키를 만드는 표준 SQL 문법이다. 구식 `serial`과 달리 숨은 시퀀스에 별도 권한을 줄 필요가 없어, anon이 삽입하는 테이블에서 특히 편하다. `timestamptz`는 타임존을 포함한 시각 타입으로, `timestamp`(타임존 없음)를 쓰면 서버 시간대에 따라 값이 달라진다. `jsonb`는 JSON을 이진 형태로 저장해 인덱스와 질의가 가능하다. `check` 제약은 잘못된 값이 DB에 들어오는 것을 애플리케이션 버그와 무관하게 막는다.

- [ ] **Step 3: 스키마 적용**

Supabase 대시보드 → SQL Editor에 `supabase/schema.sql` 전체를 붙여 넣고 Run.

Expected: `Success. No rows returned`

> **`grant`가 곧 Data API 노출 메커니즘이다.** Supabase는 2026-10-30부터 새 테이블을
> Data API에 자동 노출하지 않는다. 이 스키마는 `revoke all` 후 필요한 것만 명시적으로
> `grant`하므로 그 설정이 켜져 있든 꺼져 있든 결과가 같다 — 오히려 설정이 켜져 있을 때
> `revoke all`이 과잉 노출을 걷어낸다.
>
> 나중에 페이지가 테이블을 못 읽으면 PostgREST가 **`42501`** 에러와 함께
> **필요한 `grant` 문장을 그대로 알려준다.** 그 메시지를 그대로 실행하면 된다.
>
> `auth.users`를 참조하는 외래 키가 들어 있다. Supabase는 프로젝트를 만들 때
> `auth` 스키마를 함께 프로비저닝하므로 사용자가 0명이어도 참조가 성립한다.
> **만약 `relation "auth.users" does not exist`가 나면** 세 줄의
> `references auth.users(id) on delete set null`을 지우고 `uuid`만 남긴다 —
> 컬럼의 목적(주인 구분)은 그대로 달성되고, 참조 무결성만 포기한다.

- [ ] **Step 4: 권한 검증 쿼리 작성**

`supabase/verify_permissions.sql`:

```sql
-- anon이 가진 권한을 눈으로 확인한다.
-- 기대: articles=SELECT / reactions,clicks=INSERT /
--       notes=SELECT,INSERT / article_bodies,runs,kakao_auth=행 없음
select table_name, privilege_type
from information_schema.role_table_grants
where grantee = 'anon'
  and table_schema = 'public'
order by table_name, privilege_type;

-- RLS가 모든 테이블에 켜져 있는지 확인한다. 기대: 전부 true
select relname, relrowsecurity
from pg_class
where relnamespace = 'public'::regnamespace
  and relkind = 'r'
order by relname;
```

- [ ] **Step 5: 권한을 실제로 검증**

SQL Editor에서 `verify_permissions.sql`을 실행한다.

Expected (첫 쿼리):

```
articles   | SELECT
clicks     | INSERT
notes      | INSERT
notes      | SELECT
reactions  | INSERT
```

그리고 **anon이 `user_id`를 채워 삽입하려 하면 거부되는지** 확인한다.

```sql
-- anon 역할로 실행해볼 수 없으므로 정책 자체를 확인한다.
-- 기대: reactions/clicks/notes의 insert 정책이 (user_id IS NULL)
select tablename, policyname, cmd, with_check
from pg_policies
where schemaname = 'public' and cmd = 'INSERT'
order by tablename;
```

`article_bodies`, `runs`, `kakao_auth`가 **목록에 없어야** 한다. 하나라도 보이면 `revoke`가 적용되지 않은 것이므로 본문이 공개된다.

Expected (두 번째 쿼리): 7개 테이블 전부 `relrowsecurity = true`

- [ ] **Step 6: `scripts/verify_anon_access.sh` 작성**

권한 표를 눈으로 보는 것만으로는 부족하다. **publishable 키로 실제로 때려봐야** 한다. 그리고 이것은 한 번 쓰고 버릴 확인이 아니다 — **스키마나 정책을 고칠 때마다 다시 돌려야 하므로** 스크립트로 남긴다.

스크립트가 네 가지를 확인한다.

| 확인 | 기대 |
|---|---|
| `articles` 읽힘 | HTTP 200 — 안 읽히면 페이지가 빈다 |
| `article_bodies`·`runs`·`kakao_auth` | **200이 아님** |
| `user_id`를 채운 삽입 | `42501` — 정책이 막는다 |
| `user_id` 없는 삽입 | `23503` — 정책 통과, FK에서만 걸린다 |

**마지막 둘이 서로 다른 코드로 나오는 것이 핵심이다.** 정책이 "막는다"와 "통과시킨다"를 실제로 구분한다는 증거다. 둘 다 `42501`이면 좋아요를 아무도 못 누르고, 둘 다 `23503`이면 `user_id` 위장이 가능하다.

삽입 테스트는 **존재하지 않는 `article_id`**를 쓴다. 정책을 통과하면 외래 키에서 걸리고 막히면 `42501`이 되므로, **어느 경로든 행이 만들어지지 않는다** — 운영 데이터를 건드리지 않고 정책의 방향만 본다.

차단 판정은 **"200이 아닌지"**로 한다. PostgREST가 권한 거부에 401을 줄 때도 403을 줄 때도 있어서 특정 상태 코드에 묶으면 깨지기 쉽다(실측에서는 401 + `42501`이 나왔다).

스크립트 전문은 `scripts/verify_anon_access.sh`에 있다.

- [ ] **Step 7: 검증 실행**

```bash
bash scripts/verify_anon_access.sh
```

Expected: 모든 줄에 `✓`, 마지막에 `전부 통과. anon 권한이 설계대로다.`, 종료 코드 0

**`★`가 하나라도 보이면 멈추고 고친다.** 특히 `article_bodies 가 읽힌다`는 **테이블이 비어 있는 동안 증상이 없다** — 데이터가 쌓인 뒤 발견하면 이미 공개돼 있던 것이다.

이 스크립트는 `.env`의 `VITE_SUPABASE_PUBLISHABLE_KEY`를 쓴다(없으면 `SUPABASE_KEY`도 받는다 — Connect 다이얼로그가 그 이름으로 준다).

- [ ] **Step 8: 커밋**

```bash
git add supabase/ scripts/verify_anon_access.sh
git commit -m "feat: Supabase 스키마 — 본문 테이블 분리로 anon 차단, RLS 전면 활성화"
```

---

## Task 10: Supabase 저장소

파이프라인 단계들이 DB를 직접 알지 않도록 인터페이스를 둔다. 테스트는 가짜 구현을 넘긴다.

**Files:**
- Modify: `pipeline/lib/store.py` (추가)
- Create: `tests/fakes.py`
- Create: `tests/test_remote_store.py`
- Create: `scripts/smoke_supabase.py`

- [ ] **Step 1: 인터페이스와 가짜 구현의 테스트 작성**

`tests/test_remote_store.py`:

```python
"""가짜 구현이 인터페이스를 만족하는지 확인한다.

실제 SupabaseStore는 단위 테스트하지 않는다. 대부분이 DB 호출 통과이고,
모킹하면 '내가 쓴 모킹이 맞는가'만 검증하게 된다. 실제 동작은
scripts/smoke_supabase.py로 1회 확인한다.
"""

from datetime import datetime, timezone

from pipeline.lib.store import RemoteStore
from tests.fakes import FakeRemoteStore


def test_가짜_구현이_인터페이스를_만족한다():
    """Protocol은 런타임 검사가 아니므로 명시적으로 확인한다."""
    fake: RemoteStore = FakeRemoteStore()
    assert fake is not None


def test_발송_이력이_없으면_None을_돌려준다():
    fake = FakeRemoteStore()
    assert fake.last_sent_at() is None


def test_기록한_실행의_시각을_돌려준다():
    fake = FakeRemoteStore()
    sent = datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc)

    fake.record_run(
        window_start=datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc),
        window_end=sent,
        status="sent",
        sent_at=sent,
        collected_count=42,
        considered_count=10,
        max_score=94,
        published_count=3,
        source_counts={"s": 5},
        input_tokens=12000,
        errors=[],
    )

    assert fake.last_sent_at() == sent


def test_실패한_실행은_마지막_발송으로_세지_않는다():
    """세면 원인을 고친 뒤 재실행이 "이미 보냄"으로 막힌다."""
    fake = FakeRemoteStore()

    fake.record_run(
        window_start=datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc),
        window_end=datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc),
        status="failed",
        sent_at=None,
        collected_count=42,
        considered_count=10,
        max_score=94,
        published_count=0,
        source_counts={"s": 5},
        input_tokens=None,
        errors=[{"source": "sender:kakao", "kind": "config", "message": "HTTP 404"}],
    )

    assert fake.last_sent_at() is None
    assert len(fake.runs) == 1          # 기록은 남는다


def test_이미_발행한_URL을_알려준다():
    fake = FakeRemoteStore(known={"https://e.com/a"})
    found = fake.known_urls(["https://e.com/a", "https://e.com/b"])
    assert found == {"https://e.com/a"}


def test_최근_헤드라인을_돌려준다():
    fake = FakeRemoteStore(headlines=["어제 그 글", "그제 그 글"])
    assert fake.recent_headlines(days=14) == ["어제 그 글", "그제 그 글"]
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_remote_store.py
```

Expected: FAIL — `ImportError: cannot import name 'RemoteStore'`

- [ ] **Step 3: 인터페이스를 `store.py`에 추가**

`pipeline/lib/store.py` 끝에 덧붙인다:

```python
# ---------------------------------------------------------------
# 원격 저장소 (Supabase)
# ---------------------------------------------------------------

from datetime import datetime  # noqa: E402  (파일 상단 import에 합쳐도 된다)
from typing import Protocol, runtime_checkable


@runtime_checkable
class RemoteStore(Protocol):
    """파이프라인이 기대하는 영속 저장소의 모양.

    Protocol이므로 상속이 필요 없다. 같은 메서드를 가진 아무 클래스나
    이 자리에 들어갈 수 있다 — 테스트의 가짜 구현이 그렇다.
    """

    def last_sent_at(self) -> datetime | None:
        """마지막 발송 시각. 윈도우 계산의 기준점."""
        ...

    def known_urls(self, urls: list[str]) -> set[str]:
        """주어진 URL 중 이미 발행한 것들."""
        ...

    def recent_headlines(self, days: int) -> list[str]:
        """최근 N일간 발행한 헤드라인. 같은 사건 중복 판정에 쓴다."""
        ...

    def record_run(
        self,
        *,
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
        """실행 이력을 남긴다. 0건이어도, 전송에 실패해도 반드시 호출한다."""
        ...

    def save_articles(self, *, briefing_date: str, summaries: list) -> None:
        """발행 글과 본문을 저장한다. 본문은 별도 테이블로 들어간다."""
        ...


class SupabaseStore:
    """RemoteStore의 Supabase 구현."""

    def __init__(self, url: str, service_key: str) -> None:
        # 지연 import: supabase 패키지를 쓰지 않는 테스트에서 불필요한
        # 의존성 로딩을 피한다.
        from supabase import create_client

        self._db = create_client(url, service_key)

    def last_sent_at(self) -> datetime | None:
        rows = (
            self._db.table("runs")
            .select("sent_at")
            # 전송에 성공한 실행만 본다. 실패한 실행까지 세면 원인을 고친 뒤
            # 재실행이 "이미 보냄"으로 막힌다.
            .eq("status", "sent")
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            return None
        # Postgres는 "2026-11-10T22:20:00+00:00" 형태로 돌려준다.
        return datetime.fromisoformat(rows[0]["sent_at"])

    def known_urls(self, urls: list[str]) -> set[str]:
        if not urls:
            return set()
        rows = (
            self._db.table("articles")
            .select("url")
            .in_("url", urls)
            .execute()
            .data
        )
        return {row["url"] for row in rows}

    def recent_headlines(self, days: int) -> list[str]:
        from datetime import timedelta, timezone

        since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        rows = (
            self._db.table("articles")
            .select("headline")
            .gte("briefing_date", since)
            .order("briefing_date", desc=True)
            .execute()
            .data
        )
        return [row["headline"] for row in rows]

    def record_run(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        status: str,
        sent_at: datetime | None,
        collected_count: int,
        considered_count: int,
        max_score: int | None,
        published_count: int,
        source_counts: dict[str, int],
        input_tokens: int | None,
        errors: list[dict],
    ) -> None:
        self._db.table("runs").insert({
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "status": status,
            "sent_at": sent_at.isoformat() if sent_at is not None else None,
            "collected_count": collected_count,
            "considered_count": considered_count,
            "max_score": max_score,
            "published_count": published_count,
            "source_counts": source_counts,
            "input_tokens": input_tokens,
            "errors": errors,
        }).execute()

    def save_articles(self, *, briefing_date: str, summaries: list) -> None:
        for summary in summaries:
            raw = summary.article.ranked.item
            # upsert + on_conflict: 같은 URL이 다시 와도 에러 대신 갱신한다.
            rows = (
                self._db.table("articles")
                .upsert({
                    "briefing_date": briefing_date,
                    "url": raw.url,
                    "source": raw.source,
                    "published_at": raw.published,
                    "headline": summary.headline,
                    "bullets": summary.bullets,
                    "why_it_matters": summary.why_it_matters,
                    "topic": summary.article.ranked.topic,
                    "score": summary.article.ranked.score,
                    "reason": summary.article.ranked.reason,
                }, on_conflict="url")
                .execute()
                .data
            )
            article_id = rows[0]["id"]

            self._db.table("article_bodies").upsert({
                "article_id": article_id,
                "body": summary.article.body,
                "body_source": summary.article.body_source,
                "fallback_reason": summary.article.fallback_reason,
            }, on_conflict="article_id").execute()
```

> **설명** — `Protocol`은 "이 메서드들을 가진 객체"라는 타입을 상속 없이 정의한다(구조적 타이핑). 테스트의 가짜 구현이 `RemoteStore`를 상속하지 않아도 타입 검사기가 통과시킨다. 메서드 본문의 `...`은 `Ellipsis` 객체로, "구현 없음"을 뜻하는 관례적 표기다. `set` 컴프리헨션 `{row["url"] for row in rows}`는 중복 없는 집합을 만들고, `in` 검사가 리스트보다 훨씬 빠르다.

- [ ] **Step 4: 가짜 구현 작성**

`tests/fakes.py`:

```python
"""테스트용 가짜 협력자.

HTTP·DB 모킹 라이브러리 대신 이것을 쓴다. 모킹은 "내가 쓴 모킹이 맞는가"를
검증하게 되는 반면, 가짜 구현은 실제 인터페이스를 만족해야 하므로
계약이 어긋나면 바로 드러난다.
"""

from datetime import datetime


class FakeRemoteStore:
    def __init__(
        self,
        known: set[str] | None = None,
        headlines: list[str] | None = None,
        last_sent: datetime | None = None,
    ) -> None:
        self._known = known or set()
        self._headlines = headlines or []
        self._last_sent = last_sent
        self.runs: list[dict] = []
        self.saved: list[dict] = []

    def last_sent_at(self) -> datetime | None:
        return self._last_sent

    def known_urls(self, urls: list[str]) -> set[str]:
        return {url for url in urls if url in self._known}

    def recent_headlines(self, days: int) -> list[str]:
        return list(self._headlines)

    def record_run(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        status: str,
        sent_at: datetime | None,
        collected_count: int,
        considered_count: int,
        max_score: int | None,
        published_count: int,
        source_counts: dict[str, int],
        input_tokens: int | None,
        errors: list[dict],
    ) -> None:
        # 실제 저장소처럼, 성공한 실행만 "마지막 발송"으로 센다.
        if status == "sent":
            self._last_sent = sent_at
        self.runs.append({
            "window_start": window_start,
            "window_end": window_end,
            "status": status,
            "sent_at": sent_at,
            "collected_count": collected_count,
            "considered_count": considered_count,
            "max_score": max_score,
            "published_count": published_count,
            "source_counts": source_counts,
            "input_tokens": input_tokens,
            "errors": errors,
        })

    def save_articles(self, *, briefing_date: str, summaries: list) -> None:
        self.saved.append({"briefing_date": briefing_date, "summaries": summaries})
```

- [ ] **Step 5: 통과를 확인**

```bash
pytest tests/test_remote_store.py
```

Expected: `6 passed`

- [ ] **Step 6: 실제 연결 확인 스크립트 작성**

`scripts/smoke_supabase.py`:

```python
"""Supabase 연결과 권한을 1회 확인한다. 운영 파이프라인에 포함되지 않는다.

실행: python scripts/smoke_supabase.py

**스스로 정리한다.** runs에 테스트 행을 넣고 읽어본 뒤 지운다.
남겨두면 last_sent_at()이 그것을 읽어서 첫 실제 수집의 윈도우가 거의 0이
되고, 아무것도 수집하지 않는다.
"""

from datetime import datetime, timedelta, timezone

from pipeline.lib.secrets import require
from pipeline.lib.store import SupabaseStore

# 테스트 행을 찾아 지우기 위한 표식. source_counts에 넣는다.
MARKER = "__smoke_test__"

# 실제 키 대신 이 문장을 키 자리에 넣는다. 예외 메시지에 이게 나타나면
# 실제 secret 키도 같은 자리에 나타난다는 뜻이다.
SENTINEL_KEY = "sb_secret_sentinel_must_not_appear_in_error_messages"


def check_key_does_not_leak() -> bool:
    """잘못된 키로 호출해 예외 메시지에 키가 들어가는지 확인한다.

    왜 확인해야 하나: 리포지토리가 퍼블릭이면 **Actions 로그도 누구나
    볼 수 있다.** SupabaseStore가 올리는 예외에 Authorization 헤더나
    키가 섞여 있으면 secret 키가 그 로그에 남고, 그러면 DB 전체가 열린다.

    실제 키를 쓰지 않으므로 이 점검 자체가 키를 노출하지 않는다.
    """
    bad = SupabaseStore(require("SUPABASE_URL"), SENTINEL_KEY)

    try:
        bad.last_sent_at()
    except Exception as error:  # noqa: BLE001 — 메시지를 보는 것이 목적이다
        message = f"{type(error).__name__}: {error}"
        print(f"   예외: {message[:200]}")
        if SENTINEL_KEY in message:
            print("   ★ 키가 예외 메시지에 들어간다.")
            print("     SupabaseStore의 각 메서드를 try/except로 감싸고,")
            print("     키를 제거한 메시지로 다시 올려야 한다.")
            return False
        print("   → 키는 새지 않았다.")
        return True

    print("   ★ 잘못된 키인데 호출이 성공했다. 키 검증 경로를 확인한다.")
    return False


def main() -> None:
    url = require("SUPABASE_URL")
    store = SupabaseStore(url, require("SUPABASE_SECRET_KEY"))
    now = datetime.now(timezone.utc)

    print("1) 마지막 발송 시각 조회...")
    before = store.last_sent_at()
    print(f"   → {before}  (최초 실행이면 None)")

    print("2) 실행 이력 쓰기...")
    store.record_run(
        window_start=now - timedelta(hours=24),
        window_end=now,
        status="sent",
        sent_at=now,
        collected_count=0,
        considered_count=0,
        max_score=None,
        published_count=0,
        source_counts={MARKER: 0},
        input_tokens=None,
        errors=[],
    )
    after = store.last_sent_at()
    print(f"   → 기록 후 조회: {after}")
    round_trip = after is not None and abs((after - now).total_seconds()) < 5
    print(f"   → 왕복 일치: {'✓' if round_trip else '★ 쓴 값과 읽은 값이 다르다'}")

    print("3) 발행 URL 조회...")
    print(f"   → {store.known_urls(['https://example.com/none'])}  (빈 집합이 정상)")

    print("4) 최근 헤드라인 조회...")
    print(f"   → {len(store.recent_headlines(days=14))}건")

    print("5) 테스트 행 정리...")
    # SupabaseStore에 delete를 두지 않는다 — 운영에서 쓰지 않는 기능이다.
    # 스크립트이므로 클라이언트를 직접 쓴다.
    from supabase import create_client

    db = create_client(url, require("SUPABASE_SECRET_KEY"))
    removed = (
        db.table("runs")
        .delete()
        .contains("source_counts", {MARKER: 0})
        .execute()
        .data
    )
    print(f"   → {len(removed)}행 삭제")
    restored = store.last_sent_at()
    print(f"   → 정리 후 조회: {restored}  (1번과 같아야 한다: {before})")
    if restored != before:
        print("   ★ 정리가 덜 됐다. runs를 직접 확인한다:")
        print(f"     delete from public.runs where source_counts ? '{MARKER}';")
        raise SystemExit(1)

    print("6) 예외 메시지에 비밀값이 새는지...")
    if not check_key_does_not_leak():
        raise SystemExit(1)

    print()
    print("성공. 연결·쓰기·읽기·정리가 모두 동작하고 키가 새지 않는다.")


if __name__ == "__main__":
    main()
```

> **설명** — `if __name__ == "__main__":`는 이 파일을 직접 실행했을 때만 `main()`을 호출하게 한다. 다른 모듈이 import할 때는 실행되지 않는다. Python 스크립트의 표준 관례다.

- [ ] **Step 7: 실제로 실행해 확인**

```bash
mkdir -p scripts && python scripts/smoke_supabase.py
```

Expected: 여섯 단계가 모두 출력되고 마지막에 `성공. 연결·쓰기·읽기·정리가 모두 동작하고 키가 새지 않는다.`

실측(2026-11-11):

```
1) 마지막 발송 시각 조회...      → None
2) 실행 이력 쓰기...             → 왕복 일치: ✓
3) 발행 URL 조회...              → set()
4) 최근 헤드라인 조회...          → 0건
5) 테스트 행 정리...             → 1행 삭제, 정리 후 조회: None
6) 예외 메시지에 비밀값이 새는지... → 키는 새지 않았다
```

**5번(정리)이 없으면 첫 실제 수집이 망가진다.** 2번이 `runs`에 `status='sent'` 행을 남기므로, 지우지 않으면 `last_sent_at()`이 그것을 읽어 **윈도우가 거의 0이 되고 아무것도 수집하지 않는다.** 그래서 스크립트가 스스로 정리하고, 정리 후 조회가 1번과 같은지까지 확인한다.

**6번이 `★ 키가 예외 메시지에 들어간다`로 끝나면 멈추고 고친다.** 리포지토리가 퍼블릭이므로 Actions 로그도 공개된다 — 그 로그에 `SUPABASE_SECRET_KEY`가 남으면 DB 전체가 열린다. 실측에서는 `supabase-py`가 `Invalid API key`만 돌려주고 키를 포함하지 않았다.

확인 후 Supabase SQL Editor에서 테스트 행을 지운다:

```sql
delete from public.runs where source_counts ? 'smoke_test';
```

- [ ] **Step 8: 커밋**

```bash
git add pipeline/lib/store.py tests/fakes.py tests/test_remote_store.py scripts/smoke_supabase.py
git commit -m "feat: Supabase 저장소 + 테스트용 가짜 구현"
```

---

## Task 11: 소스 목록과 관심사 프로필

**이 태스크는 사용자 입력이 필요하다.** 파이프라인 품질을 가장 크게 좌우하는 두 파일이고, 다음 태스크의 시드 수집이 되돌릴 수 없으므로 여기서 확정한다.

**Files:**
- Create: `config/sources.yaml`
- Create: `config/interests.md`
- Create: `scripts/check_feeds.py`

- [x] **Step 1: 후보 소스 목록 작성**

`config/sources.yaml`. 처음 계획에는 후보 11개를 적어 뒀지만, **추측한 11개보다
넓게 던지고 실측으로 거르는 쪽이 정확했다.** 후보를 53개로 늘려 전부 때려 봤다.

- 애그리게이터 3 (GeekNews, Hacker News Best, Lobsters)
- 국내 매체 컬럼 4
- 국내 기업 기술블로그 16
- 해외 기업 엔지니어링 블로그 14
- 해외 AI (기업 공지 + 개인 컬럼) 10
- 인프라·DB·아키텍처 6

**애그리게이터를 넣은 이유:** GeekNews에 올라오는 원문 사이트를 하나씩 등록하는
대신 GeekNews 피드 자체를 받는다. 사람들이 이미 투표로 걸러 준 목록이어서
넓이와 품질을 같이 가져가고, 소스 목록 관리가 늘어나지 않는다. 출처가
제각각이어도 본문은 enrich 단계의 trafilatura가 맡으므로 추가 분기가 없다.
Hacker News·Lobsters도 같은 이유다.

**해외 소스 적재 경로:** 국내 소스와 완전히 같다. `lang: en`은 요약 프롬프트에만
영향을 주고(spec 5.4 — 요약은 한국어), 수집·점수·중복 판정·`articles` 적재는
동일한 코드를 지난다. 원문은 `article_bodies`에 원래 언어로 남는다. 즉
**번역을 위한 별도 단계나 테이블이 없다.**

**GeekNews 피드 주소:** 공식 공지에 두 개가 있다 —
최신 글 전체는 `https://news.hada.io/rss/news`, 긱뉴스 블로그 업데이트는
`https://news.hada.io/rss/blog`. 우리가 쓰는 쪽은 앞의 것이다.
(제3자 블로그에 돌아다니는 feedburner 주소는 공식 문서에 없다.)

- [x] **Step 2: 피드 생존 확인 스크립트 작성**

위 URL은 후보이고 **실제로 살아있는지 확인해야 한다.** 매체 개편으로 주소가 바뀌는 일이 흔하다.

`scripts/check_feeds.py`:

```python
"""config/sources.yaml의 각 피드가 살아있는지 확인한다.

실행: python scripts/check_feeds.py
"""

import sys
from pathlib import Path

import feedparser
import yaml

from pipeline.lib.http import fetch
from pipeline.lib.retry import Permanent, Transient

# 후보 목록은 수십 개라서 소스당 20초(DEFAULT_TIMEOUT)면 전체가 너무 길어진다.
# 이 스크립트는 "살아있나"만 보므로 짧게 끊고, 끊긴 것은 [일시]로 다시 돌린다.
CHECK_TIMEOUT = 10.0


def main() -> int:
    config = yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))
    must_fix: list[str] = []    # 설정을 고쳐야 하는 소스
    flaky: list[str] = []       # 일시 문제일 수 있는 소스

    for source in config["sources"]:
        if not source.get("enabled", True):
            print(f"[   끔] {source['name']}")
            continue

        name, url = source["name"], source["url"]

        try:
            result = fetch(url, timeout=CHECK_TIMEOUT)
        except Permanent as error:
            # 404/403/주소 오타. 고쳐야 한다.
            print(f"[설정] {name}  {error}")
            must_fix.append(name)
            continue
        except Transient as error:
            # 503/타임아웃. 지금만 그럴 수 있다.
            print(f"[일시] {name}  {error}")
            flaky.append(name)
            continue

        feed = feedparser.parse(result.content)
        count = len(feed.entries)

        if count == 0:
            print(f"[ 0건] {name}  ← 파싱은 되지만 항목이 없다. 주소 확인 필요")
            must_fix.append(name)
        else:
            newest = feed.entries[0].get("title", "(제목 없음)")[:40]
            print(f"[{count:3d}건] {name}  최신: {newest}")

        if result.moved_from is not None:
            print(f"         ↳ 영구 이전됨. yaml을 이 주소로 바꾼다: {result.final_url}")
            must_fix.append(name)

    print()
    if must_fix:
        print(f"고쳐야 할 소스 {len(must_fix)}개: {', '.join(must_fix)}")
        print("주소를 바꾸거나 enabled: false로 끈다.")
    if flaky:
        print(f"일시 문제일 수 있는 소스 {len(flaky)}개: {', '.join(flaky)}")
        print("잠시 후 다시 실행해본다. 계속 실패하면 주소를 확인한다.")

    if not must_fix and not flaky:
        print("모든 피드 정상.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

> **설명** — `yaml.safe_load`는 YAML을 Python 딕셔너리로 바꾼다(`load`가 아니라 `safe_load`를 쓴다 — 전자는 임의 객체 생성이 가능해 신뢰할 수 없는 입력에 위험하다). `sys.exit(main())`은 함수의 반환값을 프로세스 종료 코드로 쓴다(0=성공).
>
> 이 스크립트가 `lib/http.fetch`를 쓰는 덕분에 **"고쳐야 할 소스"와 "지금만 그럴 수 있는 소스"가 출력에서 분리된다.** 전부 `[실패]`로 뭉개 놓으면, 503 하나 때문에 멀쩡한 주소를 지우게 된다.

- [x] **Step 3: 피드를 실제로 확인하고 `sources.yaml`을 고친다**

```bash
python scripts/check_feeds.py
```

`[설정]`과 `[ 0건]`으로 나온 소스는 주소를 고치거나 `enabled: false`로 끈다.
**`[설정]`·`[ 0건]`·`↳ 영구 이전됨`이 하나도 없을 때까지 반복한다.**

`[일시]`는 잠시 후 다시 실행해본다. 두세 번 연속 나오면 설정 문제로 보고 주소를 확인한다.

**1차 실행 결과 (2026-11-11): 후보 53개 중 42개 정상, 11개 문제.**
추측으로 적었던 주소의 20%가 틀렸다. 이 단계를 건너뛰었으면 시드 수집에서
조용히 비어 있는 소스를 안고 출발했을 것이다.

영구 이전(301/308) — 최종 주소를 그대로 받았다:

| 소스 | 바뀐 주소 |
|---|---|
| 카카오 기술블로그 | `https://tech.kakao.com/feed` |
| 뱅크샐러드 | `https://corp.banksalad.com/blog/rss.xml` |
| Latent Space | `https://latent.space/feed` |

주소가 달라진 것 — `head`의 feed 선언과 후보 주소를 직접 때려 찾았다:

| 소스 | 증상 | 바꾼 주소 |
|---|---|---|
| 블로터 | 404 | `https://www.bloter.net/rss/allArticle.xml` |
| 쏘카 | 404 (도메인이 `tech.socar.kr`로 이전) | `https://tech.socar.kr/rss.xml` |
| Discord | 404 | `https://discord.com/blog/rss.xml` |

껐다(`enabled: false`) — 주소는 남겨 둬서 나중에 다시 확인할 수 있게 했다:

| 소스 | 이유 |
|---|---|
| 컬리, 리디 | **403.** 피드가 자동 접근을 거부한다. UA를 브라우저로 위장해 우회하지 않는다. |
| Uber Engineering | RSS를 제공하지 않는다(블로그 `head`에 feed 선언이 없다). |
| Anthropic News | RSS를 제공하지 않는다. Anthropic 글은 GeekNews·HN에 거의 항상 올라와 애그리게이터로 커버된다. |
| 카카오페이 | **200에 유효한 RSS인데 `<item>`이 0개다**(블로그엔 글이 있다). 저쪽 버그라 우리가 고칠 수 없다. |

> **403을 우회하지 않는 이유** — UA를 브라우저로 바꾸면 대개 뚫린다. 하지만
> 403은 "자동 수집을 원하지 않는다"는 사이트의 의사 표시다. 뚫고 들어가면
> 차단이 강화되거나 IP가 막히고, 그때는 전체 수집이 멈춘다. 끄는 쪽이 싸다.

**최종: 48개 소스 가동(국내 18 · 해외 30), 5개 끔.** `모든 피드 정상.`으로 종료 코드 0.

> **2차 정리 (Task 13 이후) — 피드가 살아 있는 것과 쓸만한 것은 다르다**
>
> `check_feeds.py`는 "200이 오고 항목이 있나"만 본다. 수집을 실제로 돌려
> **제목을 읽어 보고** 국내 매체 네 곳을 다시 판단했다. 피드가 멀쩡해도
> 내용이 관심사 밖이면 매일 선별 비용만 먹는다.
>
> | 소스 | 받아 본 것 | 판단 |
> |---|---|---|
> | 전자신문_오피니언 (`Section902.xml`) | **피드 이름이 "속보"였다.** 30건이 3분기 실적·채용·코스피 마감·지역 행사. 칼럼은 3건 | **주소가 틀렸다.** 칼럼(`11011.xml`)과 사설(`11013.xml`)로 교체 |
> | ZDNet코리아 | 30건이 ESG 등급·분기 실적·게임 시즌·백제 왕궁 | **끔.** 칼럼 전용 피드가 없다(rss 목록도 404). 하루 30건이라 선별 비용이 가장 크다 |
> | 블로터 | 4건이 롯데렌탈 의무공개매수·SK하이닉스·미국 CPI | **끔.** 같은 도메인의 다른 섹션이 "파인데일리 - 예술"을 돌려준다 — 더 이상 IT 매체 피드가 아니다 |
> | 바이라인네트워크 | 20건 중 6~8건 적중 (에이전트 데이터 엔지니어링, AI 해킹 현주소, TPU 메모리 병목, 기업 AX 프로세스) | **유지**, 가중치 0.9 그대로 |
>
> 전자신문의 **상위 오피니언 피드(`11.xml`)는 쓰지 않았다.** 50건 중 14건이
> `[인사]`·`[부음]`이다. 칼럼(`11011`)·사설(`11013`) 하위 피드는 그게 0건이다.
>
> **최종: 47개 가동(국내 16 · 해외 31), 7개 끔.** 수집 건수는 4일 윈도우에서
> 268 → **227건**으로 줄었다. 줄어든 41건은 거의 전부 선별에서 떨어질 것들이었다.

- [x] **Step 4: 관심사 프로필 작성**

`config/interests.md` — 이 파일 전체가 선별 프롬프트에 들어간다. 추상적인 단어보다 **구체적인 예시**가 훨씬 잘 작동한다.

```markdown
# 관심사 프로필

나는 백엔드 개발자이고, AI를 실무에 끼워 넣는 방법에 관심이 많다.
아래 기준으로 글을 평가한다.

## 높게 평가 (80~100점)

- **AI를 실제 제품·업무에 적용한 구체적 사례.** 에이전트 설계, RAG 구축,
  프롬프트 엔지니어링, LLM 비용·지연 최적화. 특히 **숫자와 실패 경험이 있는 글.**
- **백엔드 아키텍처의 실전 기록.** 장애 회고(postmortem), 성능 개선 과정,
  마이그레이션 기록. "무엇을 했다"가 아니라 "왜 그렇게 결정했고 무엇이 틀렸나"가 있는 글.
- **새로운 기술의 작동 원리를 설명한 글.** 발표 소식이 아니라 내부 구조 분석.
- **AI 활용 스킬·도구.** Claude Code, Cursor, MCP 같은 도구의 실전 사용법과 한계.

## 중간 (50~79점)

- 주요 기업의 기술적으로 의미 있는 발표 (새 모델, 새 DB 기능 등)
- 업계 동향 분석 중 데이터에 근거한 글
- 익숙한 주제의 좋은 입문 설명

## 낮게 평가 (0~49점)

- **보도자료를 재가공한 기사.** 투자 유치, 조직 개편, MOU, 수상, 행사 홍보.
- **제품 마케팅 글.** "우리 서비스가 좋다"가 결론인 글.
- **내용 없는 동향 기사.** "AI가 중요해지고 있다" 류.
- 이미 충분히 아는 주제의 반복 (예: Docker 기초, REST 입문)
- 프런트엔드 프레임워크 세부 비교, 디자인 트렌드, 암호화폐 시세

## 언어는 기준이 아니다

소스의 절반 이상이 해외 글이다. **영어로 썼다는 이유로 점수를 올리거나
내리지 않는다.** 요약 단계에서 한국어로 번역되므로, 선별에서는 내용만 본다.

단, 해외 글 중 **국내에 이미 번역·정리되어 돌아다니는 발표 소식**(새 모델 출시
같은 것)은 중복으로 보고 내린다. 국내에 없는 **깊은 분석과 실전 기록**이
해외 소스를 넣은 이유다.

## 애그리게이터에서 온 글

GeekNews·Hacker News·Lobsters는 사람들이 이미 투표로 걸러 준 목록이다.
**출처가 개인 블로그여도 불리하게 보지 않는다.** 올라왔다는 사실 자체가 신호다.
다만 애그리게이터에는 관심사 밖의 글(하드웨어, 수학, 역사, 정치)도 섞여
들어오므로, **이 프로필에 맞는지는 평소와 똑같이 따진다.**

## 중복 처리

최근 발행한 헤드라인 목록을 함께 받는다. **같은 사건·같은 주제를 다룬 글은
가장 깊이 있는 한 건만 남기고 나머지는 40점 이하로 내린다.** 단, 명시적인
후속편(2편, 심화 편)은 중복이 아니다.
```

> 이 파일은 **앞으로 계속 고치게 된다.** Task 17의 평가 도구로 선별 결과를 보면서 "이건 왜 뽑혔지" 싶은 항목의 패턴을 여기에 추가하는 것이 튜닝 작업이다.

- [ ] **Step 5: 커밋**

```bash
git add config/ scripts/check_feeds.py
git commit -m "feat: 소스 목록과 관심사 프로필, 피드 생존 확인 스크립트"
```

---

## Task 12: 소스 설정 로더

**Files:**
- Create: `pipeline/lib/config.py`
- Create: `tests/test_config.py`

> **계획에서 늘린 부분** — 처음 계획은 테스트 6개였다. 계획을 다시 읽으면서
> 구멍 셋을 찾아 6개를 더했다(총 12개).
>
> 1. **`load_interests`에 테스트가 없었다.** 구현에는 "비어 있으면 거부"가
>    있는데 그걸 확인하는 테스트가 없었다. 빈 프로필로 채점하면 LLM이 제
>    기준으로 점수를 주고 **그 사실이 출력에 드러나지 않는다.**
> 2. **주소 중복을 보지 않았다.** 이름 중복만 막았다. 같은 피드를 두 이름으로
>    등록하면 같은 글을 두 번 받고, 중복 제거가 걸러주더라도 어느 소스에서
>    왔는지가 임의로 정해져 `source_counts`가 흔들린다.
> 3. **url이 그냥 `str`이었다.** `htp://` 같은 스킴 오타가 로딩을 통과하고
>    수집에서 `Permanent`가 된다. 그 소스만 조용히 죽고, 증상은 "며칠째 0건"이다.
>
> 그리고 **중복 검사를 꺼진 소스까지 포함해서** 돈다. 끈 소스를 다시 켤 때
> 이름이 겹치는 걸 그때 발견하면 늦다.

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_config.py`:

```python
import pytest
from pydantic import ValidationError

from pipeline.lib.config import Source, load_interests, load_sources

YAML_OK = """
sources:
  - name: 토스_기술블로그
    url: https://toss.tech/rss.xml
    kind: rss
    weight: 1.3
    lang: ko
    enabled: true
  - name: 꺼진_소스
    url: https://example.com/rss
    kind: rss
    weight: 1.0
    lang: ko
    enabled: false
"""


def test_켜진_소스만_돌려준다(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(YAML_OK, encoding="utf-8")

    sources = load_sources(path)

    assert [s.name for s in sources] == ["토스_기술블로그"]


def test_enabled가_없으면_켜진_것으로_본다(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n  - name: s\n    url: https://e.com/r\n"
        "    kind: rss\n    weight: 1.0\n    lang: ko\n",
        encoding="utf-8",
    )
    assert len(load_sources(path)) == 1


def test_lang은_ko_또는_en만_받는다():
    with pytest.raises(ValidationError):
        Source(name="s", url="https://e.com", kind="rss", weight=1.0, lang="jp")


def test_weight는_0보다_커야_한다():
    with pytest.raises(ValidationError):
        Source(name="s", url="https://e.com", kind="rss", weight=0, lang="ko")


def test_url이_http로_시작하지_않으면_거부한다():
    """스킴 오타는 수집 때 Permanent가 되어 그 소스만 조용히 죽는다.
    증상이 "며칠째 0건"이라 알아차리기까지 오래 걸리므로 로딩에서 막는다.
    """
    with pytest.raises(ValidationError):
        Source(name="s", url="htp://e.com/r", kind="rss", weight=1.0, lang="ko")


def test_소스_이름이_중복되면_거부한다(tmp_path):
    """source_counts의 키가 되므로 중복되면 집계가 조용히 틀린다."""
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - {name: 같은이름, url: 'https://a.com/r', kind: rss, weight: 1.0, lang: ko}\n"
        "  - {name: 같은이름, url: 'https://b.com/r', kind: rss, weight: 1.0, lang: ko}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="중복"):
        load_sources(path)


def test_소스_주소가_중복되면_거부한다(tmp_path):
    """같은 피드를 두 번 등록하면 같은 글을 두 번 받는다. 중복 제거가
    걸러주더라도 어느 소스에서 왔는지가 임의로 정해져 집계가 흔들린다.
    """
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - {name: 이름하나, url: 'https://a.com/r', kind: rss, weight: 1.0, lang: ko}\n"
        "  - {name: 이름둘, url: 'https://a.com/r', kind: rss, weight: 1.0, lang: ko}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="중복"):
        load_sources(path)


def test_꺼진_소스도_중복_검사에_들어간다(tmp_path):
    """끈 소스를 켤 때 이름이 겹치는 걸 그때 발견하면 늦다."""
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - {name: 같은이름, url: 'https://a.com/r', kind: rss, weight: 1.0, lang: ko}\n"
        "  - {name: 같은이름, url: 'https://b.com/r', kind: rss, weight: 1.0, lang: ko,"
        " enabled: false}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="중복"):
        load_sources(path)


def test_소스가_하나도_없으면_거부한다(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text("sources: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="비어"):
        load_sources(path)


def test_전부_꺼져_있으면_거부한다(tmp_path):
    """sources는 차 있지만 켜진 게 없으면 수집할 게 없다."""
    path = tmp_path / "sources.yaml"
    path.write_text(
        "sources:\n"
        "  - {name: s, url: 'https://a.com/r', kind: rss, weight: 1.0, lang: ko,"
        " enabled: false}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="비어"):
        load_sources(path)


def test_관심사_프로필을_그대로_읽는다(tmp_path):
    path = tmp_path / "interests.md"
    path.write_text("# 관심사\n\n백엔드와 AI.\n", encoding="utf-8")

    assert load_interests(path) == "# 관심사\n\n백엔드와 AI."


def test_관심사_프로필이_비어_있으면_거부한다(tmp_path):
    """빈 프로필로 채점하면 LLM이 제 기준으로 점수를 주고, 그 사실이
    출력에 드러나지 않는다. 조용히 틀리는 쪽이라 로딩에서 막는다.
    """
    path = tmp_path / "interests.md"
    path.write_text("   \n\n", encoding="utf-8")

    with pytest.raises(ValueError, match="비어"):
        load_interests(path)
```

- [x] **Step 2: 실패를 확인**

```bash
pytest tests/test_config.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.config'`

- [x] **Step 3: 최소 구현 작성**

`pipeline/lib/config.py`:

```python
"""소스 설정 로딩.

수집(collect)·선별(rank)·요약(summarize)이 모두 이 모듈로 설정을 읽는다.
설정이 틀렸으면 **파이프라인이 시작하기 전에** 터뜨린다. 07:20에 무인으로
도는 작업이라, 설정 오류가 "그 소스만 며칠째 0건"으로 나타나면 알아차리기까지
오래 걸린다.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_SOURCES_PATH = Path("config/sources.yaml")
DEFAULT_INTERESTS_PATH = Path("config/interests.md")


class Source(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    url: str
    kind: Literal["rss"]            # 지금은 rss만. 다른 방식이 생기면 여기 추가한다
    weight: float = Field(gt=0)     # LLM 점수에 곱한다
    lang: Literal["ko", "en"]
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def _http로_시작해야_한다(cls, value: str) -> str:
        # pydantic의 HttpUrl을 쓰지 않는 이유: 주소를 정규화해서 되돌려준다
        # (끝에 / 를 붙이는 등). sources.yaml의 주소는 check_feeds.py로 하나하나
        # 확인한 것이라, 로더가 조용히 바꾸면 확인한 의미가 없어진다.
        # 여기서는 형식만 보고 글자는 그대로 넘긴다.
        if not value.startswith(("http://", "https://")):
            raise ValueError(f"url이 http(s)로 시작하지 않는다: {value!r}")
        return value


def _중복(값들: list[str]) -> list[str]:
    보인것: set[str] = set()
    겹친것: set[str] = set()
    for 값 in 값들:
        if 값 in 보인것:
            겹친것.add(값)
        보인것.add(값)
    return sorted(겹친것)


def load_sources(path: Path | None = None) -> list[Source]:
    """켜진 소스만 돌려준다."""
    path = path or DEFAULT_SOURCES_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    all_sources = [Source.model_validate(row) for row in data.get("sources") or []]

    # 중복 검사는 꺼진 소스까지 포함한다. 끈 소스를 다시 켤 때 이름이
    # 겹치는 걸 그때 발견하면 늦다.
    if 겹친이름 := _중복([s.name for s in all_sources]):
        raise ValueError(
            f"소스 이름이 중복됐다: {', '.join(겹친이름)}. "
            f"이름은 집계 키(runs.source_counts)로 쓰이므로 유일해야 한다."
        )

    if 겹친주소 := _중복([s.url for s in all_sources]):
        raise ValueError(
            f"소스 주소가 중복됐다: {', '.join(겹친주소)}. "
            f"같은 피드를 두 번 받으면 어느 소스에서 왔는지가 임의로 정해진다."
        )

    enabled = [s for s in all_sources if s.enabled]
    if not enabled:
        raise ValueError(f"{path}에 켜진 소스가 비어 있다.")

    return enabled


def load_interests(path: Path | None = None) -> str:
    """관심사 프로필 전문. 선별 프롬프트에 그대로 들어간다."""
    path = path or DEFAULT_INTERESTS_PATH
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{path}가 비어 있다. 선별 기준이 없으면 채점이 무의미하다.")
    return text
```

> **설명** — `data.get("sources") or []`에서 `or`를 쓴 이유는, YAML에 `sources:`만
> 적고 비워두면 `None`이 되기 때문이다. `get("sources", [])`는 키가 **없을 때만**
> 기본값을 주므로 `None`을 막지 못한다. `Field(gt=0)`은 "0보다 큼"(greater than)이다.
>
> `if 겹친이름 := _중복(...)` 의 `:=`는 **대입 표현식**(왈러스 연산자, 3.8+)이다.
> 대입과 조건 검사를 한 줄에 한다. 없으면 `겹친이름 = _중복(...)`을 먼저 쓰고
> 다음 줄에서 `if 겹친이름:`을 써야 한다.
>
> `@field_validator("url")`은 pydantic이 그 필드를 검증할 때 부르는 훅이다.
> `@classmethod`가 함께 붙어야 한다. 안에서 `ValueError`를 던지면 pydantic이
> `ValidationError`로 감싸 주므로, 호출하는 쪽은 예외 종류를 하나만 보면 된다.
>
> **`HttpUrl`을 쓰지 않은 이유** — pydantic에는 주소 검증용 `HttpUrl`이 있다.
> 쓰지 않았다. 검증만 하지 않고 **주소를 정규화해서 되돌려준다**(끝에 `/`를
> 붙이는 등). `sources.yaml`의 주소는 Task 11에서 `check_feeds.py`로 하나하나
> 확인한 것이라, 로더가 조용히 바꿔 버리면 확인한 의미가 없어진다. 형식만 보고
> 글자는 그대로 넘긴다.

- [x] **Step 4: 통과를 확인**

```bash
pytest tests/test_config.py
```

Expected: `12 passed`

- [x] **Step 5: 실제 설정 파일이 로딩되는지 확인**

```bash
python -c "
from pipeline.lib.config import load_sources, load_interests
s = load_sources()
print(f'소스 {len(s)}개:', ', '.join(x.name for x in s))
print(f'관심사 프로필 {len(load_interests())}자')
"
```

**실측 (2026-11-11):** 소스 48개(국내 18 · 해외 30), 가중치 0.9~1.3,
관심사 프로필 1275자. 실제 파일에서도 이름·주소 중복 없이 통과했다.

- [x] **Step 6: 커밋**

```bash
git add pipeline/lib/config.py tests/test_config.py
git commit -m "feat: 소스 설정 로더 (이름·주소 중복, 스킴 오타, 빈 프로필 거부)"
```

---

## Task 13: 수집

**Files:**
- Create: `pipeline/collect.py`
- Create: `pipeline/lib/text.py`
- Create: `tests/fixtures/feed_two_items.xml`
- Create: `tests/fixtures/feed_empty.xml`
- Create: `tests/fixtures/feed_atom_updated.xml`
- Create: `tests/test_collect.py`
- Create: `tests/test_text.py`

> **계획에서 고친 것 — 버그 셋** (테스트 21개 → 30개, `lib/text.py` 추가)
>
> **1. 에러 분류 테스트 다섯 개가 애초에 통과할 수 없었다.** `collect`는
> **전부** 실패하면 `RuntimeError`를 던진다(spec 8.2). 그런데 그 테스트들은
> 소스가 하나뿐인 채로 그 하나를 깨뜨리고 번들을 기대했다. 소스 1개 중 1개
> 실패 = 전부 실패다. 깨진 소스 + 정상 소스로 바꿨고(`_one_broken` 도움 함수),
> 원래 의도였던 "소스 1개가 실패하면 중단"은 별도 테스트로 못 박았다.
>
> **2. 중복 제거가 정반대로 동작했다.** `{item.url: item for item in collected}`에
> "dict는 삽입 순서를 유지하므로 먼저 만난 소스가 남는다"는 주석이 붙어 있었다.
> **틀렸다.** 삽입 순서가 유지되는 건 **키**이고, 같은 키에 다시 대입하면
> **값은 나중 것으로 덮인다.** 즉 마지막 소스가 남았다. 살아남은 항목의
> `source`가 선별 가중치를 정하므로(`sources.yaml` 순서 = 우선순위) 이건
> 품질에 직접 영향을 준다. `setdefault`로 바꿨다. **추가한 테스트가 잡았다.**
>
> **3. `bytes` 리터럴에 한글이 있었다.** `b"...날짜 깨짐..."`은 `SyntaxError:
> bytes can only contain ASCII literal characters`다. `str`로 쓰고 `.encode()`한다.
>
> **그리고 실제로 돌려 보고 하나 더 — 발췌에 HTML이 그대로 들어왔다.**
> 273건 중 **140건**이 `<div><ul><li>`를 담고 있었다. 선별 프롬프트와
> (본문 확보 실패 시) 폴백 본문이 둘 다 이걸 쓰므로 양쪽으로 번진다.
> `lib/text.strip_html`을 만들어 수집에서 한 번 벗긴다. **길이는 자르지 않는다** —
> 선별은 `excerpt[:400]`만 보지만 폴백 본문은 전체를 쓴다(Task 18).

- [x] **Step 1: 테스트 fixture 작성**

`tests/fixtures/feed_two_items.xml` — 윈도우 안의 한 건과 윈도우 밖의 한 건:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>테스트 기술블로그</title>
    <item>
      <title>결제 서버 P99 40ms 달성기</title>
      <link>https://toss.tech/article/payment-latency?utm_source=rss</link>
      <pubDate>Tue, 10 Nov 2026 14:30:00 +0900</pubDate>
      <description>지연의 원인을 추적한 과정을 정리했다.</description>
    </item>
    <item>
      <title>작년에 쓴 오래된 글</title>
      <link>https://toss.tech/article/old-one</link>
      <pubDate>Mon, 10 Nov 2025 09:00:00 +0900</pubDate>
      <description>윈도우 밖이라 걸러져야 한다.</description>
    </item>
  </channel>
</rss>
```

`tests/fixtures/feed_empty.xml` — 파싱은 되지만 항목이 없는 피드:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>빈 피드</title>
  </channel>
</rss>
```

`tests/fixtures/feed_atom_updated.xml` — **Atom은 `published` 없이 `updated`만
주는 경우가 많다.** 네이버 D2가 `.atom`을 주고 실제로 이 모양이다. 구현에
`entry.get("published") or entry.get("updated")` 폴백이 있는데 계획에는 그걸
확인하는 테스트가 없었다. 이걸 놓치면 그 소스 **전체가 조용히 0건**이 된다:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom 피드</title>
  <entry>
    <title>published 없이 updated만 있는 글</title>
    <link rel="alternate" href="https://d2.naver.com/helloworld/1234"/>
    <updated>2026-11-10T14:30:00+09:00</updated>
    <summary>네이버 D2처럼 .atom을 주는 소스가 이 모양이다.</summary>
  </entry>
</feed>
```

- [x] **Step 2: HTML 제거 유틸 — 실패하는 테스트**

`tests/test_text.py`:

```python
from pipeline.lib.text import strip_html


def test_태그를_벗긴다():
    assert strip_html("<p>본문이다</p>") == "본문이다"


def test_중첩된_태그도_벗긴다():
    assert strip_html("<div><p>강조 <strong>된</strong> 글</p></div>") == "강조 된 글"


def test_블록_태그는_공백으로_나눈다():
    """<li>a</li><li>b</li>를 그냥 이으면 "ab"가 된다. GeekNews 발췌가
    전부 <ul><li> 목록이라 이게 깨지면 단어가 붙어 버린다.
    """
    assert strip_html("<ul><li>첫째</li><li>둘째</li></ul>") == "첫째 둘째"


def test_br도_공백으로_나눈다():
    assert strip_html("한 줄<br/>다음 줄") == "한 줄 다음 줄"


def test_인라인_태그는_붙인다():
    """<strong>은 단어 중간에 올 수 있다. 공백을 넣으면 단어가 쪼개진다."""
    assert strip_html("<p>Postgre<strong>SQL</strong></p>") == "PostgreSQL"


def test_엔티티를_되돌린다():
    assert strip_html("<p>a &amp; b &lt; c &quot;d&quot;</p>") == 'a & b < c "d"'


def test_공백을_하나로_모은다():
    """피드의 HTML은 들여쓰기와 줄바꿈이 섞여 있다. 그대로 두면
    프롬프트에 빈 줄만 들어간다.
    """
    assert strip_html("<p>앞\n\n   뒤</p>") == "앞 뒤"


def test_앞뒤_공백을_없앤다():
    assert strip_html("  <p> 가운데 </p>  ") == "가운데"


def test_script와_style_내용은_버린다():
    """본문이 아니다. 프롬프트에 들어가면 토큰만 먹는다."""
    assert strip_html("<p>글</p><script>var x = 1;</script>") == "글"
    assert strip_html("<style>.a{color:red}</style><p>글</p>") == "글"


def test_태그가_없으면_내용만_정리한다():
    assert strip_html("그냥  텍스트") == "그냥 텍스트"


def test_빈_문자열은_빈_문자열이다():
    assert strip_html("") == ""


def test_닫히지_않은_태그도_예외를_내지_않는다():
    """피드의 HTML은 깨져 있는 경우가 흔하다. 한 건 때문에 수집이
    멈추면 안 된다.
    """
    assert strip_html("<p>앞<div>뒤") == "앞 뒤"


def test_주석은_버린다():
    assert strip_html("<!-- 숨김 --><p>보임</p>") == "보임"


def test_링크의_주소는_버리고_글자만_남긴다():
    """Lobsters 발췌가 <a href=...>Comments</a> 하나뿐이다. 주소까지
    남기면 프롬프트가 URL로 가득 찬다.
    """
    assert strip_html('<p><a href="https://lobste.rs/s/abc">Comments</a></p>') == "Comments"
```

- [x] **Step 3: HTML 제거 유틸 구현**

`pipeline/lib/text.py`:

```python
"""피드에서 온 HTML을 글자만 남긴 텍스트로 바꾼다.

RSS·Atom의 `summary`/`content`는 거의 항상 HTML이다. 그대로 두면
- 선별 프롬프트에 `<div><ul><li>`가 들어가 토큰을 먹고 신호를 흐린다
- 본문 확보 실패 시 폴백 본문(`body_source="rss_excerpt"`)에 태그가 남아
  요약 프롬프트까지 번진다

그래서 수집 단계에서 한 번 벗겨 저장한다. 길이는 자르지 않는다 —
선별은 `excerpt[:400]`만 쓰지만 폴백 본문은 전체를 쓴다.
"""

import re
from html.parser import HTMLParser

# 이 태그들은 경계가 곧 띄어쓰기다. <li>첫째</li><li>둘째</li>를 그냥 이으면
# "첫째둘째"가 된다. 반대로 <strong>은 단어 중간에 오므로 붙여야 한다.
BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "ol", "p", "pre", "section", "table", "tbody", "td",
    "tfoot", "th", "thead", "tr", "ul",
})

# 글이 아니다. 내용까지 버린다.
DROP_TAGS = frozenset({"script", "style"})

_WHITESPACE = re.compile(r"\s+")


class _TextOnly(HTMLParser):
    """태그를 버리고 글자만 모은다."""

    def __init__(self) -> None:
        # convert_charrefs=True(기본값)면 &amp; 같은 엔티티를 알아서 되돌려준다.
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._dropping = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in DROP_TAGS:
            self._dropping += 1
        elif tag in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_TAGS:
            # 0 밑으로 내려가지 않게 한다. 깨진 HTML은 여는 태그 없이
            # 닫는 태그만 나오는 경우가 있다.
            self._dropping = max(0, self._dropping - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._dropping:
            self.parts.append(data)


def strip_html(value: str) -> str:
    """HTML에서 글자만 남긴다. 공백은 하나로 모으고 앞뒤를 자른다.

    HTMLParser는 깨진 HTML에도 예외를 내지 않는다. 피드의 HTML은 자주
    깨져 있고, 한 항목 때문에 수집이 멈추면 안 되므로 이 성질이 필요하다.
    """
    parser = _TextOnly()
    parser.feed(value)
    parser.close()
    return _WHITESPACE.sub(" ", "".join(parser.parts)).strip()
```

> **설명** — 표준 라이브러리 `html.parser.HTMLParser`를 쓴다. 정규식으로
> `<[^>]+>`를 지우는 방법보다 안전하다(속성 안의 `>`, 주석, CDATA를 다룬다).
> 새 의존성도 필요 없다.
>
> `convert_charrefs=True`(기본값)면 `&amp;` 같은 엔티티를 알아서 되돌려준다.
>
> **블록 태그와 인라인 태그를 나눈 이유** — `<li>첫째</li><li>둘째</li>`를
> 그냥 이으면 `"첫째둘째"`가 된다. 반대로 `<strong>`은 단어 중간에 오므로
> (`Postgre<strong>SQL</strong>`) 공백을 넣으면 단어가 쪼개진다. 그래서
> 블록 태그 경계에만 공백을 넣는다.
>
> HTMLParser는 **깨진 HTML에도 예외를 내지 않는다.** 피드의 HTML은 자주
> 깨져 있고 한 항목 때문에 수집이 멈추면 안 되므로 이 성질이 필요하다.

- [x] **Step 4: 수집 — 실패하는 테스트 작성**

`tests/test_collect.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.collect import SOURCE_ATTEMPTS, collect
from pipeline.lib.config import Source
from pipeline.lib.http import FetchResult
from pipeline.lib.retry import Permanent, Transient

FIXTURES = Path(__file__).parent / "fixtures"

# fixture의 첫 항목은 2026-11-10T05:30:00Z, 두 번째는 2025-11-10T00:00:00Z
WINDOW_START = datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc)

BROKEN_URL = "https://broken.com/r"


def _source(name: str = "토스_기술블로그", url: str = "https://toss.tech/rss.xml") -> Source:
    return Source(name=name, url=url, kind="rss", weight=1.3, lang="ko")


def _ok(filename: str = "feed_two_items.xml", *, moved_from: str | None = None):
    """fixture 내용을 담은 FetchResult를 돌려주는 fetch 함수를 만든다."""
    data = (FIXTURES / filename).read_bytes()

    def fetch(url: str) -> FetchResult:
        return FetchResult(content=data, final_url=url, moved_from=moved_from)

    return fetch


def _collect(**overrides):
    kwargs = {
        "sources": [_source()],
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "fetch": _ok(),
        "known_urls": lambda urls: set(),
        "sleep": lambda _: None,   # 테스트는 실제로 기다리지 않는다
    }
    kwargs.update(overrides)
    return collect(**kwargs)


def _one_broken(fail):
    """깨진 소스 하나 + 정상 소스 하나로 수집한다.

    collect는 **전부** 실패할 때만 중단한다(spec 8.2). 그래서 실패의 분류를
    보려면 살아 있는 소스가 하나 있어야 한다. 소스가 하나뿐인 채로 그 하나를
    깨뜨리면 번들이 아니라 RuntimeError가 나온다 —
    test_소스가_하나일_때_그_하나가_실패하면_중단한다가 그쪽을 맡는다.

    fail(url)은 깨진 소스에서 부를 함수다. 예외를 던지거나 FetchResult를 돌려준다.
    """
    data = (FIXTURES / "feed_two_items.xml").read_bytes()
    calls: list[str] = []

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        if url == BROKEN_URL:
            return fail(url)
        return FetchResult(content=data, final_url=url, moved_from=None)

    bundle = _collect(
        sources=[_source("깨진소스", BROKEN_URL), _source("정상소스", "https://ok.com/r")],
        fetch=fetch,
    )
    return bundle, calls


# --- 정상 경로 ---

def test_윈도우_안의_항목만_수집한다():
    bundle = _collect()

    assert len(bundle.items) == 1
    assert bundle.items[0].title == "결제 서버 P99 40ms 달성기"


def test_URL을_정규화해서_저장한다():
    """utm_source가 붙은 채로 저장되면 중복 제거가 깨진다."""
    assert _collect().items[0].url == "https://toss.tech/article/payment-latency"


def test_소스_이름을_기록한다():
    assert _collect().items[0].source == "토스_기술블로그"


def test_발행_시각을_UTC로_정규화한다():
    assert _collect().items[0].published == "2026-11-10T05:30:00+00:00"


def test_published가_없으면_updated를_본다():
    """Atom(.atom)을 주는 소스는 published 없이 updated만 있는 경우가 많다.
    네이버 D2가 그렇다. 이걸 놓치면 그 소스 전체가 조용히 0건이 된다.
    """
    bundle = _collect(fetch=_ok("feed_atom_updated.xml"))

    assert len(bundle.items) == 1
    assert bundle.items[0].published == "2026-11-10T05:30:00+00:00"
    assert bundle.items[0].url == "https://d2.naver.com/helloworld/1234"


def test_이미_발행한_URL을_제외한다():
    bundle = _collect(
        known_urls=lambda urls: {"https://toss.tech/article/payment-latency"},
    )
    assert bundle.items == []


def test_같은_URL이_두_소스에_있으면_한_번만_담는다():
    """해외 글이 여러 애그리게이터에 동시에 올라오는 상황."""
    bundle = _collect(sources=[_source("소스A", "https://a.com/r"),
                               _source("소스B", "https://b.com/r")])
    assert len(bundle.items) == 1


def test_중복_제거는_먼저_만난_소스를_남긴다():
    """sources.yaml의 순서가 우선순위가 된다."""
    bundle = _collect(sources=[_source("소스A", "https://a.com/r"),
                               _source("소스B", "https://b.com/r")])
    assert bundle.items[0].source == "소스A"


def test_중복_제거가_소스별_집계를_줄이지_않는다():
    """집계는 "그 소스가 윈도우 안에서 몇 건을 냈나"다. 중복 제거로 빠진
    건까지 0으로 세면, 멀쩡한 소스가 침묵한 것처럼 보인다.
    """
    bundle = _collect(sources=[_source("소스A", "https://a.com/r"),
                               _source("소스B", "https://b.com/r")])

    assert len(bundle.items) == 1
    assert bundle.source_counts == {"소스A": 1, "소스B": 1}


def test_소스별_건수를_집계한다():
    """소스 침묵 감지의 입력이 된다."""
    assert _collect().source_counts == {"토스_기술블로그": 1}


def test_항목이_없는_피드도_0건으로_집계한다():
    bundle = _collect(fetch=_ok("feed_empty.xml"))

    assert bundle.items == []
    assert bundle.source_counts == {"토스_기술블로그": 0}
    assert bundle.errors == []


def test_윈도우_경계를_번들에_기록한다():
    bundle = _collect()
    assert bundle.window_start == WINDOW_START.isoformat()
    assert bundle.window_end == WINDOW_END.isoformat()


def test_발행_시각을_읽을_수_없는_항목은_건너뛴다():
    """한 건의 날짜 오류로 수집이 중단되면 안 된다."""
    # bytes 리터럴(b"...")에는 ASCII만 들어간다. 한글이 있으면 SyntaxError다.
    # str로 쓰고 encode한다.
    xml = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>날짜 깨짐</title><link>https://e.com/a</link>
      <pubDate>언젠가</pubDate><description>d</description></item>
    </channel></rss>""".encode("utf-8")

    bundle = _collect(
        fetch=lambda url: FetchResult(content=xml, final_url=url, moved_from=None)
    )
    assert bundle.items == []
    assert bundle.errors == []      # 항목 하나의 문제는 소스 에러가 아니다


def test_링크가_없는_항목은_건너뛴다():
    """URL은 중복 제거 키이자 upsert 키다. 없으면 담을 수 없다."""
    xml = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>링크 없음</title>
      <pubDate>Tue, 10 Nov 2026 14:30:00 +0900</pubDate><description>d</description></item>
    </channel></rss>""".encode("utf-8")

    bundle = _collect(
        fetch=lambda url: FetchResult(content=xml, final_url=url, moved_from=None)
    )
    assert bundle.items == []


def test_발췌의_HTML을_벗긴다():
    """피드의 summary는 거의 항상 HTML이다(실측: 273건 중 140건).
    그대로 저장하면 선별 프롬프트와 폴백 본문에 태그가 그대로 번진다.
    """
    xml = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>제목</title><link>https://e.com/a</link>
      <pubDate>Tue, 10 Nov 2026 14:30:00 +0900</pubDate>
      <description>&lt;div&gt;&lt;ul&gt;&lt;li&gt;첫째&lt;/li&gt;&lt;li&gt;둘째&lt;/li&gt;&lt;/ul&gt;&lt;/div&gt;</description>
      </item></channel></rss>""".encode("utf-8")

    bundle = _collect(
        fetch=lambda url: FetchResult(content=xml, final_url=url, moved_from=None)
    )
    assert bundle.items[0].excerpt == "첫째 둘째"


def test_제목의_HTML도_벗긴다():
    xml = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>a &amp;amp; b</title><link>https://e.com/a</link>
      <pubDate>Tue, 10 Nov 2026 14:30:00 +0900</pubDate><description>d</description>
      </item></channel></rss>""".encode("utf-8")

    bundle = _collect(
        fetch=lambda url: FetchResult(content=xml, final_url=url, moved_from=None)
    )
    assert bundle.items[0].title == "a & b"


def test_발췌_길이는_자르지_않는다():
    """선별은 excerpt[:400]만 쓰지만, 본문 확보가 실패하면 발췌 전체가
    폴백 본문이 된다(spec 8.2). 수집에서 자르면 그 본문이 잘린다.
    """
    긴글 = "가" * 5000
    xml = f"""<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>제목</title><link>https://e.com/a</link>
      <pubDate>Tue, 10 Nov 2026 14:30:00 +0900</pubDate>
      <description>{긴글}</description>
      </item></channel></rss>""".encode("utf-8")

    bundle = _collect(
        fetch=lambda url: FetchResult(content=xml, final_url=url, moved_from=None)
    )
    assert len(bundle.items[0].excerpt) == 5000


# --- 에러 분류 ---

def test_영구_실패는_config로_기록하고_재시도하지_않는다():
    """404는 sources.yaml을 고쳐야 한다. 재시도는 낭비다."""
    def fail(url):
        raise Permanent(f"{url} HTTP 404")

    bundle, calls = _one_broken(fail)

    assert calls.count(BROKEN_URL) == 1          # 재시도하지 않았다
    assert bundle.errors[0].source == "깨진소스"
    assert bundle.errors[0].kind == "config"
    assert "404" in bundle.errors[0].message
    assert bundle.source_counts["깨진소스"] == 0


def test_403도_config로_기록한다():
    """봇 차단. 기다려도 안 풀린다."""
    def fail(url):
        raise Permanent(f"{url} HTTP 403")

    bundle, _ = _one_broken(fail)
    assert bundle.errors[0].kind == "config"


def test_일시_실패는_재시도하고_transient로_기록한다():
    def fail(url):
        raise Transient(f"{url} HTTP 503")

    bundle, calls = _one_broken(fail)

    assert calls.count(BROKEN_URL) == SOURCE_ATTEMPTS   # 재시도했다
    assert bundle.errors[0].kind == "transient"


def test_재시도_중_성공하면_수집된다():
    calls = []
    data = (FIXTURES / "feed_two_items.xml").read_bytes()

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        if len(calls) == 1:
            raise Transient("일시 장애")
        return FetchResult(content=data, final_url=url, moved_from=None)

    bundle = _collect(fetch=fetch)

    assert len(bundle.items) == 1
    assert bundle.errors == []


def test_재시도할_때_간격을_둔다():
    delays = []

    def fetch(url: str) -> FetchResult:
        raise Transient("장애")

    with pytest.raises(RuntimeError):
        _collect(fetch=fetch, sleep=delays.append)

    assert len(delays) == SOURCE_ATTEMPTS - 1


def test_영구_이전은_실패가_아니지만_기록한다():
    """자동으로 따라갔다. 다만 sources.yaml을 고쳐야 한다."""
    bundle = _collect(fetch=_ok(moved_from="https://old.toss.tech/rss.xml"))

    assert len(bundle.items) == 1                    # 수집은 성공
    assert bundle.errors[0].kind == "moved"
    assert "old.toss.tech" in bundle.errors[0].message
    assert bundle.source_counts == {"토스_기술블로그": 1}


def test_소스_하나가_죽어도_나머지는_수집한다():
    """핵심 요구사항. 매체 하나의 장애로 그날이 날아가면 안 된다."""
    def fail(url):
        raise Permanent("HTTP 404")

    bundle, _ = _one_broken(fail)

    assert len(bundle.items) == 1
    assert bundle.items[0].source == "정상소스"
    assert len(bundle.errors) == 1
    assert bundle.errors[0].source == "깨진소스"
    assert bundle.source_counts == {"깨진소스": 0, "정상소스": 1}


def test_피드_파싱이_깨지면_config로_기록한다():
    def fail(url):
        # feedparser는 웬만한 쓰레기도 파싱하므로 bytes가 아닌 것을 넘겨 예외를 유도한다
        return FetchResult(content=None, final_url=url, moved_from=None)  # type: ignore[arg-type]

    bundle, _ = _one_broken(fail)

    assert bundle.errors[0].kind == "config"
    assert "파싱" in bundle.errors[0].message


# --- 전체 실패 ---

def test_전부_영구_실패면_설정_확인을_안내한다():
    """ "네트워크 확인"이라고 하면 엉뚱한 곳을 보게 된다."""
    def fetch(url: str) -> FetchResult:
        raise Permanent("HTTP 404")

    with pytest.raises(RuntimeError, match="sources.yaml"):
        _collect(sources=[_source("A", "https://a.com/r"), _source("B", "https://b.com/r")],
                 fetch=fetch)


def test_전부_일시_실패면_네트워크_확인을_안내한다():
    def fetch(url: str) -> FetchResult:
        raise Transient("HTTP 503")

    with pytest.raises(RuntimeError, match="네트워크"):
        _collect(sources=[_source("A", "https://a.com/r"), _source("B", "https://b.com/r")],
                 fetch=fetch)


def test_섞여_실패하면_네트워크_확인을_안내한다():
    """config 하나, transient 하나. 전부 config일 때만 sources.yaml을 가리킨다."""
    def fetch(url: str) -> FetchResult:
        if url == "https://a.com/r":
            raise Permanent("HTTP 404")
        raise Transient("HTTP 503")

    with pytest.raises(RuntimeError, match="네트워크"):
        _collect(sources=[_source("A", "https://a.com/r"), _source("B", "https://b.com/r")],
                 fetch=fetch)


def test_소스가_하나일_때_그_하나가_실패하면_중단한다():
    """소스 1개 = 전부. 조용히 0건 번들을 쓰면 다음 단계가 빈 입력으로 돈다."""
    def fetch(url: str) -> FetchResult:
        raise Permanent("HTTP 404")

    with pytest.raises(RuntimeError, match="sources.yaml"):
        _collect(fetch=fetch)


def test_이전_기록만_있으면_전체_실패가_아니다():
    """moved는 실패가 아니다. 이걸 실패로 세면 정상 실행이 중단된다."""
    bundle = _collect(fetch=_ok(moved_from="https://old.com/r"))
    assert len(bundle.items) == 1
```

- [x] **Step 5: 실패를 확인**

```bash
pytest tests/test_collect.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.collect'`

- [x] **Step 6: 최소 구현 작성**

`pipeline/collect.py`:

```python
"""01 수집: 윈도우 내에 발행된 글을 소스별로 긁어 raw.json을 만든다.

소스 단위로 장애를 격리하고, 실패를 성격별로 분류해 기록한다.
- config    주소를 고쳐야 한다 (404/403/파싱 불가). 재시도하지 않는다.
- transient 기다리면 된다 (429/5xx/타임아웃). 재시도 후에도 실패한 경우.
- moved     301/308로 이전됐다. 수집은 성공했지만 설정을 갱신해야 한다.

전부 실패하면 중단한다(spec 8.2). 일부만 실패하면 계속한다 —
매체 하나의 장애로 그날이 날아가면 안 된다.

실행: python -m pipeline.collect
"""

import time
from datetime import datetime, timezone
from typing import Callable

import feedparser

from pipeline.lib.config import Source, load_sources
from pipeline.lib.http import FetchResult
from pipeline.lib.http import fetch as http_fetch
from pipeline.lib.retry import Permanent, Transient, with_retry
from pipeline.lib.secrets import require
from pipeline.lib.store import LocalStore, SupabaseStore
from pipeline.lib.text import strip_html
from pipeline.lib.timeutil import KST, compute_window, to_utc_iso
from pipeline.lib.urls import normalize_url
from pipeline.models import RawBundle, RawItem, SourceError

# 소스당 시도 횟수. 소스가 48개라 넉넉히 주면 전체 실행이 길어진다.
# 일시 장애는 다음 실행(하루 뒤)에 대체로 풀려 있다.
SOURCE_ATTEMPTS = 2

FetchFn = Callable[[str], FetchResult]
KnownUrlsFn = Callable[[list[str]], set[str]]
SleepFn = Callable[[float], None]


def _parse_source(
    source: Source,
    payload: bytes,
    window_start: datetime,
    window_end: datetime,
) -> list[RawItem]:
    """한 소스의 피드에서 윈도우 내 항목을 뽑는다."""
    feed = feedparser.parse(payload)
    items: list[RawItem] = []

    for entry in feed.entries:
        # 매체마다 키가 다르다. RSS는 pubDate → published로 오고, Atom은
        # published 없이 updated만 있는 경우가 많다(네이버 D2가 그렇다).
        raw_date = entry.get("published") or entry.get("updated")
        published = to_utc_iso(raw_date)
        if published is None:
            # 날짜를 못 읽으면 윈도우 판정이 불가능하다. 조용히 건너뛴다.
            continue

        moment = datetime.fromisoformat(published)
        if not (window_start <= moment <= window_end):
            continue

        link = entry.get("link")
        if not link:
            # URL은 중복 제거 키이자 upsert 키다. 없으면 담을 수 없다.
            continue

        # HTML을 여기서 한 번 벗긴다. 피드의 summary는 거의 항상 HTML이고,
        # 선별 프롬프트와 폴백 본문이 둘 다 이걸 쓴다. 길이는 자르지 않는다 —
        # 선별은 excerpt[:400]만 보지만 폴백 본문은 전체를 쓴다.
        items.append(RawItem(
            source=source.name,
            title=strip_html(entry.get("title") or ""),
            url=normalize_url(link),
            published=published,
            excerpt=strip_html(entry.get("summary") or ""),
        ))

    return items


def collect(
    *,
    sources: list[Source],
    window_start: datetime,
    window_end: datetime,
    fetch: FetchFn = http_fetch,
    known_urls: KnownUrlsFn,
    sleep: SleepFn = time.sleep,
) -> RawBundle:
    """윈도우 내 항목을 수집한다. 소스 단위로 장애를 격리한다."""
    collected: list[RawItem] = []
    counts: dict[str, int] = {}
    errors: list[SourceError] = []

    for source in sources:
        counts[source.name] = 0

        try:
            # url=source.url을 기본 인자로 묶는다. 루프 변수를 클로저로
            # 잡으면(lambda: fetch(source.url)) 나중 호출에서 마지막 소스를
            # 가리키는 고전적인 함정이 있다. 여기선 즉시 호출되므로 실제
            # 문제는 없지만, 기본 인자로 고정하는 편이 안전하고 의도가 분명하다.
            result = with_retry(
                lambda url=source.url: fetch(url),
                attempts=SOURCE_ATTEMPTS,
                sleep=sleep,
            )
        except Permanent as error:
            # 재시도하지 않는다. 주소를 고쳐야 한다.
            errors.append(SourceError(
                source=source.name, kind="config", message=str(error),
            ))
            continue
        except Transient as error:
            # with_retry가 이미 재시도했는데도 실패했다.
            errors.append(SourceError(
                source=source.name, kind="transient", message=str(error),
            ))
            continue

        # 301/308로 이전됐으면 수집은 성공했지만 설정을 갱신해야 한다.
        if result.moved_from is not None:
            errors.append(SourceError(
                source=source.name,
                kind="moved",
                message=(
                    f"{result.moved_from} → {result.final_url} "
                    f"(sources.yaml의 주소를 갱신한다)"
                ),
            ))

        try:
            items = _parse_source(source, result.content, window_start, window_end)
        except Exception as error:  # noqa: BLE001 — 파싱 실패도 소스 단위로 격리한다
            errors.append(SourceError(
                source=source.name,
                kind="config",
                message=f"피드 파싱 실패: {type(error).__name__}: {error}",
            ))
            continue

        counts[source.name] = len(items)
        collected.extend(items)

    # moved는 실패가 아니다. 전체 실패 판정에서 제외한다.
    failures = [error for error in errors if error.kind != "moved"]
    if failures and len(failures) == len(sources):
        # 원인에 따라 안내가 달라야 한다. "네트워크 확인"이라고 하면
        # 주소가 틀린 경우에 엉뚱한 곳을 보게 된다.
        if all(error.kind == "config" for error in failures):
            hint = "모든 실패가 설정 문제다. sources.yaml의 주소를 확인한다."
        else:
            hint = "네트워크 또는 소스 서버를 확인한다."
        raise RuntimeError(
            f"모든 소스 수집에 실패했다 ({len(sources)}개). {hint} "
            f"첫 에러: {failures[0].message}"
        )

    # 실행 내 중복 제거 — 같은 글이 여러 소스에 올라오는 경우.
    #
    # setdefault로 **먼저 만난 소스**를 남긴다. sources.yaml의 순서가 우선순위가
    # 되고, 살아남은 항목의 source가 선별 가중치를 정하므로 임의로 정해지면 안 된다.
    #
    # `{item.url: item for item in collected}`로 쓰면 안 된다. dict가 삽입
    # 순서를 유지하는 건 **키**의 순서이고, 같은 키에 다시 대입하면 **값은
    # 나중 것으로 덮인다.** 즉 마지막 소스가 남는다 — 의도의 정반대다.
    #
    # counts는 줄이지 않는다. 집계는 "그 소스가 윈도우 안에서 몇 건을 냈나"이고,
    # 중복으로 빠진 건까지 0으로 세면 멀쩡한 소스가 침묵한 것처럼 보인다.
    by_url: dict[str, RawItem] = {}
    for item in collected:
        by_url.setdefault(item.url, item)
    unique = list(by_url.values())

    # 이미 발행한 것 제거 (DB 조회 1회)
    already = known_urls([item.url for item in unique])
    fresh = [item for item in unique if item.url not in already]

    return RawBundle(
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        items=fresh,
        source_counts=counts,
        errors=errors,
    )


def main() -> None:
    remote = SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SECRET_KEY"))
    now = datetime.now(timezone.utc)
    window_start, window_end = compute_window(now=now, last_sent_at=remote.last_sent_at())

    bundle = collect(
        sources=load_sources(),
        window_start=window_start,
        window_end=window_end,
        known_urls=remote.known_urls,
    )

    # 날짜 디렉터리는 KST 기준으로 만든다. 사람이 보는 이름이기 때문이다.
    date = window_end.astimezone(KST).date().isoformat()
    path = LocalStore(date=date).write("raw", bundle)

    print(f"수집 {len(bundle.items)}건 → {path}")
    print(f"  윈도우: {window_start.isoformat()} ~ {window_end.isoformat()}")
    for name, count in sorted(bundle.source_counts.items()):
        print(f"  {count:4d}건  {name}")

    # 성격별로 나눠 보여준다. config는 내가 고쳐야 하고 transient는 두고 보면 된다.
    marks = {"config": "설정", "transient": "일시", "moved": "이전"}
    for error in bundle.errors:
        print(f"  [{marks[error.kind]}] {error.source}: {error.message}")


if __name__ == "__main__":
    main()
```

> **설명** — `from pipeline.lib.http import fetch as http_fetch`에서 `as`로 이름을
> 바꾼 이유는, 이 모듈의 인자 이름이 `fetch`라서 가려지는 것을 막기 위함이다.
>
> 그리고 `pipeline/lib/http.py`라는 이름이 표준 라이브러리 `http` 모듈과 겹쳐
> 보이지만 **문제가 없다.** Python 3는 기본이 절대 임포트라서, 다른 곳에서
> `import http.client`라고 쓰면 표준 라이브러리를 가져온다. 우리 모듈은
> `pipeline.lib.http`라는 완전한 경로로만 참조된다.
>
> `lambda url=source.url: fetch(url)`에서 기본 인자를 쓴 것은 **늦은
> 바인딩(late binding)** 함정 때문이다. `lambda: fetch(source.url)`은 호출
> 시점에 `source`를 찾으므로, 반복문이 끝난 뒤에 호출하면 마지막 소스를
> 가리킨다. 기본 인자는 **정의 시점**에 값이 고정된다.
>
> `by_url.setdefault(item.url, item)`은 **이미 있으면 덮지 않는다.** 이게
> "먼저 만난 소스가 남는다"를 실제로 만드는 부분이다(위 버그 2).

- [x] **Step 7: 통과를 확인**

```bash
pytest tests/test_collect.py tests/test_text.py
```

Expected: `30 passed`, `14 passed`

- [x] **Step 8: 전체 테스트 확인**

```bash
pytest
```

실측: `142 passed`.

- [x] **Step 9: 실제 48개 소스로 1회 시험 수집**

```bash
python -m pipeline.collect
```

**실측 (2026-11-11):** 4일 윈도우(마지막 발송이 없어 96시간 상한)에서
**273건, 33초, 에러 0건.** `[설정]`·`[일시]`·`[이전]`이 하나도 없었다.

| 확인한 것 | 결과 |
|---|---|
| 전체 소요 시간 | 48개 소스 순차 수집에 33초. Actions 타임아웃 걱정 없음 |
| 소스별 집계 합 vs 최종 건수 | 277 → 273. **중복 제거가 4건 실제로 걸렸다** |
| URL 유일성 | 중복 없음 |
| 추적 파라미터 | `utm_*`·`fbclid` 남은 것 없음 |
| HTML 제거 | 벗긴 뒤 `<`·`>`가 남은 6건은 전부 **정상 텍스트** — `<참고>`(네이버 D2의 한국어 표기), 코드 얘기 속 `` `<img>` ``, Kotlin 제네릭 `actions<ListingActions>()`, HTML 요소를 논하는 `<details><summary>` |
| 발췌 길이 | 중앙값 250자, 최대 19,908자(PostgreSQL Planet은 피드에 본문 전체를 담는다) |
| raw.json | 468KB |

**0건인 소스 14개**는 정상이다. 기업 기술블로그는 주 1회~월 1회 발행이
흔하다. 소스 침묵 경고는 "**며칠 연속** 0건"으로 판정하므로(계획 3) 하루
0건은 신호가 아니다.

> **애그리게이터 세 곳의 `<link>`가 서로 다르다 — 측정 결과**
>
> | 소스 | `<link>`가 가리키는 곳 | 발췌 |
> |---|---|---|
> | Hacker News (hnrss) | **원문 URL** | `Article URL: ... Comments URL: ...` (쓸모 없음) |
> | Lobsters | **원문 URL** | `Comments` 한 단어 (쓸모 없음) |
> | GeekNews | **GeekNews topic 페이지** | **한국어 요약 불릿** (좋음) |
>
> GeekNews의 Atom 피드에는 **원문 URL이 아예 없다.** `<link>`, `<id>`, `<links>`
> 전부 `news.hada.io/topic?id=...`를 가리킨다. 원문 주소는 topic 페이지 HTML에만 있다.
>
> **그대로 두기로 했다.** 원문을 쫓으려면 enrich에 "GeekNews면 topic 페이지를
> 긁어서 원문 링크를 찾고 그걸 다시 받는다"는 소스별 분기가 생긴다. 지금까지
> 피해 온 종류의 분기다. 그리고 바꿀 이유도 약하다 — GeekNews의 `content`는
> **이미 한국어 요약 불릿**이어서, 한국어 독자에게는 영문 원문보다 낫고,
> topic 페이지에는 요약·댓글·원문 링크가 다 있다. 즉 `원문 보기`가 GeekNews를
> 가리키는 것이 손실이 아니다.
>
> HN·Lobsters 발췌가 쓸모없는 건 문제가 아니다. **제목이 신호를 다 담고**,
> `<link>`가 원문을 가리키므로 enrich가 본문을 제대로 가져온다.

> **그래서 `sources.yaml`에서 애그리게이터 구획을 맨 뒤로 옮겼다.**
>
> 중복 제거는 파일에서 먼저 만난 소스를 남긴다(`setdefault`). 애그리게이터가
> 맨 위에 있으면, 직접 구독한 블로그의 글이 HN에도 올라온 경우 **HN이 이긴다.**
> 그러면 글의 원래 제목 대신 HN 제출자가 줄여 쓴 제목이, 글 자신의 요약 대신
> `Article URL: ...` 가 남는다. 그 제목이 브리핑 헤드라인의 재료다.
>
> **실측으로 확인했다** — 순서만 바꾸고 다시 수집하니 정확히 1건이 바뀌었다:
>
> | | 소스 | 제목 | 발췌 |
> |---|---|---|---|
> | 전 | Hacker_News_Best | `AlphaProof Code` | `Article URL: ... Comments URL: ...` (158자) |
> | 후 | Google_DeepMind_Blog | `Introducing AlphaProof Code: a breakthrough in verifying complex software` | 글의 실제 요약 (102자) |
>
> 1건뿐인 이유는 애그리게이터가 링크하는 글이 대개 우리가 구독하지 않는
> 사이트에 있기 때문이다. 충돌은 272건 중 4건이고, 그중 직접 소스와 겹친
> 것이 1건이었다. **드물지만 겹칠 때마다 손해라서 순서로 막는 편이 맞다** —
> 코드에 규칙을 더하지 않고 파일 순서만으로 해결된다.

- [x] **Step 10: 커밋**

```bash
git add pipeline/collect.py pipeline/lib/text.py tests/test_collect.py tests/test_text.py tests/fixtures/
git commit -m "feat: 수집 단계 — 윈도우 필터, 소스 장애 격리, 실패 성격별 분류"
```

---

## Task 14: 시드 수집

**되돌릴 수 없는 작업이다.** 대부분의 RSS 피드는 최근 10~50건만 제공하므로,
지금 긁지 않으면 그 데이터는 영구히 얻을 수 없다. 이후 선별 프롬프트 튜닝의
재료가 된다.

**Files:**
- Create: `pipeline/seed.py`
- Create: `tests/test_seed.py`

> **계획에서 고친 것** (테스트 3개 → 10개)
>
> **1. 계획에 없던 가장 위험한 구멍 — 덮어쓰기.** 계획의 `main()`은
> `LocalStore(date=SEED_DIR).write("raw", bundle)`를 그냥 호출한다. 한 달 뒤에
> 무심코 `python -m pipeline.seed`를 다시 돌리면, 그때 피드는 이미 과거를
> 버렸으므로 **더 적은 데이터로 원본을 덮어쓴다.** 되돌릴 수 없고 증상도 없다 —
> 파일은 그대로 있고 안에 든 것만 줄어든다. 계획의 대비책은 Step 6의 수동
> 백업뿐이었는데, 백업을 안 했으면 끝이다.
>
> `ensure_writable()`을 넣어 **이미 시드가 있으면 거부**한다. 메시지에
> `--force`를 적어 둔다 — 막기만 하고 빠져나갈 방법을 안 알려주면 사용자가
> 파일을 손으로 지운다.
>
> **2. 테스트의 `fetch`가 bytes를 돌려줬다.** `fetch=lambda url: data`는
> `collect`가 기대하는 `FetchResult`가 아니라서 `result.moved_from`에서
> `AttributeError`가 난다. 계획대로면 세 번째 테스트가 실패했다.
>
> **3. `run_seed()`로 분리했다.** 계획의 `main()`은 `load_sources()`,
> `datetime.now()`, 네트워크를 다 안고 있어서 테스트할 수 없었다. 수집·저장을
> `run_seed`로 빼고 `main`은 배선과 출력만 맡는다.

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_seed.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.lib.config import Source
from pipeline.lib.http import FetchResult
from pipeline.lib.store import LocalStore
from pipeline.seed import (
    IGNORE_HISTORY,
    SEED_DIR,
    ensure_writable,
    run_seed,
    seed_window,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _source() -> Source:
    return Source(name="s", url="https://e.com/r", kind="rss", weight=1.0, lang="ko")


def _fetch(filename: str = "feed_two_items.xml"):
    data = (FIXTURES / filename).read_bytes()

    def fetch(url: str) -> FetchResult:
        # collect는 FetchResult를 기대한다. bytes를 그대로 돌려주면
        # result.moved_from에서 AttributeError가 난다.
        return FetchResult(content=data, final_url=url, moved_from=None)

    return fetch


def _store(tmp_path: Path) -> LocalStore:
    return LocalStore(date=SEED_DIR, root=tmp_path)


# --- 윈도우 ---

def test_시드_윈도우가_아주_넓다():
    """피드가 주는 전부를 받으려면 윈도우가 과거를 충분히 덮어야 한다."""
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    start, end = seed_window(now=now)

    assert end == now
    assert (end - start).days >= 365


def test_시드는_별도_디렉터리를_쓴다():
    """운영 날짜 디렉터리와 섞이면 일반 실행이 시드를 덮어쓴다."""
    assert SEED_DIR == "_seed"


def test_오래된_항목도_수집된다(tmp_path):
    """fixture의 2025년 글이 들어와야 한다 — 운영 수집에서는 걸러진 항목."""
    bundle = run_seed(
        sources=[_source()],
        now=datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc),
        fetch=_fetch(),
        store=_store(tmp_path),
    )

    assert len(bundle.items) == 2


def test_발행_이력을_보지_않는다():
    """운영 수집은 이미 발행한 URL을 뺀다. 시드는 튜닝 재료이므로
    발행 여부와 무관하게 전부 받아야 한다.
    """
    assert IGNORE_HISTORY(["https://a.com/1", "https://b.com/2"]) == set()


# --- 덮어쓰기 방지 ---

def test_이미_있는_시드는_덮어쓰지_않는다(tmp_path):
    """이게 이 태스크에서 가장 위험한 지점이다.

    한 달 뒤에 무심코 다시 돌리면, 그때 피드는 이미 과거를 버렸으므로
    **더 적은 데이터로 원본을 덮어쓴다.** 되돌릴 수 없는 손실이고
    증상도 없다 — 파일은 그대로 있고 안에 든 것만 줄어든다.
    """
    store = _store(tmp_path)
    run_seed(sources=[_source()], now=datetime(2026, 11, 10, tzinfo=timezone.utc),
             fetch=_fetch(), store=store)

    with pytest.raises(SystemExit, match="이미 있다"):
        run_seed(sources=[_source()], now=datetime(2026, 12, 10, tzinfo=timezone.utc),
                 fetch=_fetch(), store=store)


def test_force를_주면_덮어쓴다(tmp_path):
    """막아 두더라도 빠져나갈 길은 있어야 한다. 다만 기본값이 아니다."""
    store = _store(tmp_path)
    run_seed(sources=[_source()], now=datetime(2026, 11, 10, tzinfo=timezone.utc),
             fetch=_fetch(), store=store)

    bundle = run_seed(sources=[_source()], now=datetime(2026, 12, 10, tzinfo=timezone.utc),
                      fetch=_fetch(), store=store, force=True)
    assert len(bundle.items) == 2


def test_시드가_없으면_그냥_쓴다(tmp_path):
    ensure_writable(_store(tmp_path), force=False)      # 예외가 나지 않는다


def test_거부_메시지가_force를_알려준다(tmp_path):
    """막기만 하고 빠져나갈 방법을 안 알려주면 사용자가 파일을 손으로 지운다."""
    store = _store(tmp_path)
    run_seed(sources=[_source()], now=datetime(2026, 11, 10, tzinfo=timezone.utc),
             fetch=_fetch(), store=store)

    with pytest.raises(SystemExit, match="--force"):
        ensure_writable(store, force=False)


# --- 저장 ---

def test_시드를_파일로_쓴다(tmp_path):
    store = _store(tmp_path)
    run_seed(sources=[_source()], now=datetime(2026, 11, 10, tzinfo=timezone.utc),
             fetch=_fetch(), store=store)

    assert (tmp_path / SEED_DIR / "raw.json").exists()


def test_항목이_없어도_파일은_쓴다(tmp_path):
    """0건이어도 "언제 시도했는지"는 남아야 한다. 다만 다음 실행이
    이걸 보고 거부하므로, 0건이면 사용자가 force로 다시 돌린다.
    """
    store = _store(tmp_path)
    bundle = run_seed(sources=[_source()],
                      now=datetime(2026, 11, 10, tzinfo=timezone.utc),
                      fetch=_fetch("feed_empty.xml"), store=store)

    assert bundle.items == []
    assert store.exists("raw")
```

- [x] **Step 2: 실패를 확인**

```bash
pytest tests/test_seed.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.seed'`

- [x] **Step 3: 최소 구현 작성**

`pipeline/seed.py`:

```python
"""시드 수집 (1회성): 각 소스가 제공하는 전체 항목을 긁어 저장한다.

운영 수집과 다른 점은 둘뿐이다 — 윈도우가 넓고, 발행 이력을 보지 않는다.
수집 로직은 collect를 그대로 재사용한다.

실행: python -m pipeline.seed

이 데이터는 선별 프롬프트 튜닝(pipeline.evaluate)의 재료다. 대부분의 RSS는
최근 10~50건만 제공하므로, **지금 긁지 않으면 다시 얻을 수 없다.**

같은 이유로 이 모듈은 **이미 있는 시드를 덮어쓰지 않는다.** 한 달 뒤에
무심코 다시 돌리면 그때 피드는 이미 과거를 버렸으므로 더 적은 데이터로
원본을 덮어쓴다. 파일은 그대로 있고 안에 든 것만 줄어드니 증상도 없다.
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from pipeline.collect import FetchFn, SleepFn, collect
from pipeline.lib.config import Source, load_sources
from pipeline.lib.http import fetch as http_fetch
from pipeline.lib.store import LocalStore
from pipeline.models import RawBundle

# 운영 날짜 디렉터리(2026-11-10)와 섞이지 않게 별도 이름을 쓴다.
SEED_DIR = "_seed"

# 피드가 주는 전부를 받기 위한 넉넉한 과거 범위.
#
# 더 넓힐 이유가 없다. 되돌릴 수 없는 것은 "오래된 글"이 아니라 **피드의
# 잘림**이다 — 10건만 주는 피드는 내일 11번째를 버린다. 400일은 어떤 피드가
# 담고 있는 범위보다 넓다. 반대로 과도하게 넓히면(10년) 2019년 글이 튜닝
# 표본에 섞여 들어와, 지금 들어올 글을 대표하지 못하는 재료가 된다.
SEED_LOOKBACK_DAYS = 400


def IGNORE_HISTORY(urls: list[str]) -> set[str]:  # noqa: N802 — 상수처럼 쓰는 주입값
    """시드는 발행 이력을 보지 않는다.

    운영 수집은 이미 발행한 URL을 뺀다(중복 발송 방지). 시드는 튜닝
    재료이므로 발행 여부와 무관하게 전부 받아야 한다.
    """
    return set()


def seed_window(*, now: datetime) -> tuple[datetime, datetime]:
    return now - timedelta(days=SEED_LOOKBACK_DAYS), now


def ensure_writable(store: LocalStore, *, force: bool) -> None:
    """이미 시드가 있으면 거부한다.

    막기만 하고 빠져나갈 방법을 알려주지 않으면 사용자가 파일을 손으로
    지운다. 그래서 메시지에 `--force`를 적는다.
    """
    if store.exists("raw") and not force:
        raise SystemExit(
            "시드가 이미 있다. 덮어쓰지 않는다.\n"
            f"  {SEED_DIR}/raw.json\n"
            "\n"
            "지금 다시 받으면 피드가 그동안 버린 과거가 빠진 채로 원본을\n"
            "덮어쓴다. 파일은 그대로 있고 안에 든 것만 줄어들어 알아차릴\n"
            "수도 없다.\n"
            "\n"
            "정말 다시 받아야 하면 기존 파일을 먼저 다른 이름으로 복사하고\n"
            "`python -m pipeline.seed --force`로 실행한다."
        )


def run_seed(
    *,
    sources: list[Source],
    now: datetime,
    store: LocalStore,
    fetch: FetchFn = http_fetch,
    known_urls: Callable[[list[str]], set[str]] = IGNORE_HISTORY,
    sleep: SleepFn = time.sleep,
    force: bool = False,
) -> RawBundle:
    """시드를 수집해 저장한다. 저장 전에 덮어쓰기를 막는다."""
    ensure_writable(store, force=force)

    window_start, window_end = seed_window(now=now)
    bundle = collect(
        sources=sources,
        window_start=window_start,
        window_end=window_end,
        fetch=fetch,
        known_urls=known_urls,
        sleep=sleep,
    )
    store.write("raw", bundle)
    return bundle


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    force = "--force" in args

    store = LocalStore(date=SEED_DIR)
    bundle = run_seed(
        sources=load_sources(),
        now=datetime.now(timezone.utc),
        store=store,
        force=force,
    )

    print(f"시드 수집 {len(bundle.items)}건 → {SEED_DIR}/raw.json")
    print(f"  윈도우: {bundle.window_start} ~ {bundle.window_end}")
    for name, count in sorted(bundle.source_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}건  {name}")

    marks = {"config": "설정", "transient": "일시", "moved": "이전"}
    for error in bundle.errors:
        print(f"  [{marks[error.kind]}] {error.source}: {error.message}")

    print()
    print("이 파일은 선별 프롬프트 튜닝에 쓴다. 지우지 않는다.")
    print("다시 만들 수 없으므로 저장소 밖에 복사해 둔다.")


if __name__ == "__main__":
    main()
```

> **설명** — `raise SystemExit(메시지)`는 종료 코드 1로 프로세스를 끝내면서
> 메시지를 stderr에 출력한다. `sys.exit()`가 내부적으로 던지는 것과 같은
> 예외이고, `pytest.raises(SystemExit)`로 테스트할 수 있다. `RuntimeError`와
> 달리 **스택 트레이스가 찍히지 않아** 사용자가 읽을 안내문에 적합하다.
>
> `IGNORE_HISTORY`를 함수로 두고 기본 인자로 주입한 이유는 **테스트 가능성**이다.
> `known_urls=lambda urls: set()`을 `run_seed` 안에 박으면 "시드는 발행 이력을
> 보지 않는다"는 규칙을 밖에서 확인할 수 없다.
>
> **`SEED_LOOKBACK_DAYS`를 400일로 둔 이유** — 더 넓힐 이유가 없다. 되돌릴 수
> 없는 것은 "오래된 글"이 아니라 **피드의 잘림**이다. 10건만 주는 피드는 내일
> 11번째를 버린다. 400일은 어떤 피드가 담고 있는 범위보다 넓다(실측: 가장 오래된
> 항목도 400일 안이었다). 반대로 과도하게 넓히면 2019년 글이 튜닝 표본에 섞여,
> 지금 들어올 글을 대표하지 못하는 재료가 된다.

- [x] **Step 4: 통과를 확인**

```bash
pytest tests/test_seed.py
```

Expected: `10 passed`. 전체 `152 passed`.

- [x] **Step 5: 시드를 실제로 수집한다**

```bash
python -m pipeline.seed
```

**실측 (2026-11-12): 1923건, 33초, 에러 0건.** 윈도우
`2025-10-07 ~ 2026-11-11`. 50건 미만 기준을 한참 넘겼다.

- [x] **Step 6: 시드 파일을 git에서 제외하되 백업한다**

`data/`는 `.gitignore`에 있으므로 커밋되지 않는다. 그런데 **이 파일은 다시
만들 수 없으므로** 별도로 복사해 둔다.

```bash
mkdir -p ~/briefing-seed-backup
cp data/_seed/raw.json ~/briefing-seed-backup/raw-$(date +%Y%m%d).json
shasum -a 256 data/_seed/raw.json ~/briefing-seed-backup/raw-$(date +%Y%m%d).json
```

**실측:** 2.9MB, 체크섬 일치 확인. `~/briefing-seed-backup/raw-20261112.json`.

- [x] **Step 7: 시드로만 알 수 있는 것 — 소스별 실제 발행 간격**

시드를 받고 나서야 **각 소스가 실제로 얼마나 자주 쓰는지**를 볼 수 있었다.
`check_feeds.py`는 이걸 모른다 — 200이 오고 항목이 있으면 통과시킨다.

**발행이 멈춘 소스 2개 → 껐다:**

| 소스 | 마지막 발행 | check_feeds 결과 |
|---|---|---|
| 쿠팡_기술블로그 | 2024-10-14 (**13개월**) | 통과 — 200에 10건 들어 있다 |
| Chip_Huyen | 2025-01-16 (**22개월**) | 통과 — 200에 10건 들어 있다 |

**느리지만 살아 있는 소스 5개 → 남겼다.** 끄는 대신 측정값을 `sources.yaml`
주석에 적었다:

| 소스 | 마지막 발행 | 400일간 |
|---|---:|---:|
| 스포카 기술블로그 | 244일 전 | 1건 |
| 하이퍼커넥트 기술블로그 | 203일 전 | 5건 |
| Lil'Log | 130일 전 | 2건 |
| Slack Engineering | 119일 전 | 8건 |
| 쏘카 기술블로그 | 108일 전 | 9건 |

> **이 측정이 설계를 하나 바꿨다.** spec 8.4의 소스 침묵 경고는 "3일 연속
> 0건"이었다. 그러면 **위 다섯은 영구히 경고를 띄운다.** 같은 절에 "진짜 비용은
> 알림 피로"라고 적어 놓고 매일 뜨는 경고를 설계한 셈이다. Lil'Log가 400일에
> 2편인 것은 고장이 아니라 그 저자의 평소 속도이고, 그 2편이 우리가 가장
> 원하는 글이다. spec 8.4를 **소스별 `quiet_days`** 기준으로 고쳤다
> (계획 3의 `lib/guard.py`가 읽는다).

**최종: 가동 45개(국내 16 · 해외 29), 9개 끔.**

> **Task 17(선별 품질 평가)에 넘기는 메모 — 표본이 한쪽으로 쏠려 있다.**
>
> 시드 1923건 중 **OpenAI_Blog가 680건(35%)**, Hugging_Face_Blog가 231건(12%)이다.
> 둘이 전체의 거의 절반이다. `evaluate`가 고정 시드로 무작위 표본을 뽑으면
> 표본의 절반이 이 두 소스가 된다 — 운영 수집의 구성(4일 윈도우에서 OpenAI는
> 10건, 전체의 4%)과 전혀 다르다. **소스별 상한을 두거나 층화 표본을 써야 한다.**

- [x] **Step 8: 커밋**

```bash
git add pipeline/seed.py tests/test_seed.py
git commit -m "feat: 시드 수집 — 피드 전체 항목 확보 (프롬프트 튜닝 재료)"
```

---

## Task 15: LLM 래퍼

**Files:**
- Create: `pipeline/lib/llm.py`
- Modify: `tests/fakes.py` (추가)
- Create: `tests/test_llm.py`
- Create: `scripts/smoke_llm.py`

> **중요 — SDK가 이미 재시도한다.** anthropic SDK는 429·5xx·연결 오류를 자체적으로
> 지수 백오프 재시도한다(기본 `max_retries=2`). 그 위에 내 재시도를 또 걸면 한 번의
> 논리적 호출이 최악의 경우 6번이 되고, 크레딧과 시간을 그만큼 쓴다.
>
> 그래서 역할을 나눈다 — **전송 계층 재시도는 SDK에 맡기고(`max_retries`를 명시),
> 내 래퍼는 분류와 "스키마 실패 1회 재시도"만 담당한다.**

> **계획에서 고친 것** (테스트 18개 → 28개)
>
> 이 태스크는 외부 SDK에 직접 붙으므로, 구현 전에 **설치된 SDK로 전부
> 확인했다**(anthropic 2.8.0). 추측으로 쓸 수 있는 부분이 없었다.
>
> **1. `import httpx`가 틀렸다 — SDK는 `httpx2` 위에 올라가 있다.**
> `anthropic._base_client`에 `httpx` 속성이 아예 없다(`httpx2`만 있다).
> 테스트가 SDK 예외를 직접 만들려면 SDK가 쓰는 쪽을 써야 한다.
> 우리 `pipeline/lib/http.py`는 `httpx`(0.28.1)를 쓰므로 **두 라이브러리가 한
> 프로젝트에 공존한다** — 섞지 않는다. (실측: 지금은 둘 다로 예외를 만들 수
> 있지만, 그건 덕 타이핑 덕분이고 보장이 아니다.)
>
> **2. `output_format`은 `parse()`에서는 맞다 — "폐기됐다"는 `create()` 쪽이다.**
> 폐기된 것은 `messages.create(output_format=...)`이고, 그쪽은
> `output_config={"format": ...}`를 쓴다. 반면 `parse()`의 `output_format`은
> **그 헬퍼 자신의 인자**이고 타입이 `Optional[type[ResponseFormatT]]`다 —
> pydantic 모델 **클래스**를 받는다. 계획이 맞았고, 나중에 누가 "폐기됐다"는
> 말만 보고 고치지 않도록 구현에 주석을 달았다.
>
> **3. `thinking`을 넘기지 않는 것이 필수다.** Opus 5.5는 사고가 항상 켜져 있고
> `{"type": "disabled"}`나 `budget_tokens`는 **어떤 effort에서도 400**이다.
> 계획은 이미 넘기지 않았지만 이유가 적혀 있지 않아, 누가 "비용 절감"으로
> 끄려 할 수 있었다. 주석으로 못 박았다.
>
> **4. SDK 계약 테스트 5개를 더했다.** 아래 문자열·인자가 SDK의 허용 목록에서
> 빠지면 **07:20에 무인으로 돌 때가 아니라 지금** 알아야 한다:
>
> | 테스트 | 지키는 것 |
> |---|---|
> | `test_모델_ID에_날짜_접미사가_없다` | `claude-opus-5-5-20260401` 같은 ID는 존재하지 않는다 |
> | `test_FALLBACK_BETA가_SDK의_허용_목록에_있다` | 오타, 베타 종료 |
> | `test_fallbacks_default가_SDK의_허용값이다` | `"default"` 스칼라 형태 |
> | `test_Effort가_SDK의_단계와_같다` | SDK가 단계를 더하거나 뺐는지 |
> | `test_parse에_필요한_인자가_모두_있다` | `betas`·`fallbacks`는 **beta** parse에만 있다 |
>
> **5. `LLM` Protocol을 `runtime_checkable`로 바꿨다.** 계획의
> `fake: LLM = FakeLLM(...)`은 타입 주석이라 런타임에 아무것도 검사하지
> 않는다. 이제 `isinstance(fake, LLM)`로 실제 확인한다(`RemoteStore`와 동일).
>
> **6. `APITimeoutError`를 확인했다.** `APIConnectionError`의 하위이므로 기존
> 분기에서 함께 잡힌다. 계획에 테스트가 없어 추가했다.

**실측으로 확인한 SDK 표면 (anthropic 2.8.0):**

| 확인한 것 | 결과 |
|---|---|
| 기반 HTTP 라이브러리 | `httpx2` 2.16.0 (`httpx`가 아니다) |
| `messages.parse` | 있다. `output_format`·`output_config` 있고 **`betas`·`fallbacks` 없다** |
| `beta.messages.parse` | 있다. `output_format`·`output_config`·`betas`·`fallbacks` 모두 있다 |
| `output_format` 타입 | `Optional[type[ResponseFormatT]]` — pydantic 클래스를 받는다 |
| `BetaOutputConfigParam` 키 | `effort`, `format`, `task_budget` |
| `effort` 단계 | `low`, `medium`, `high`, `xhigh`, `max` |
| `BetaFallbacksParam` | `Iterable[BetaFallbackParam] | Literal["default"]` |
| `server-side-fallback-2026-07-01` | 허용 목록에 있다 |
| 반환 타입 | `ParsedBetaMessage[ResponseFormatT]` |
| `parsed_output` | **프로퍼티**다. content 블록을 훑어 없으면 `None` |
| `APIConnectionError`가 `APIStatusError`의 하위? | **아니다**(형제다) |
| `APITimeoutError`가 `APIConnectionError`의 하위? | 그렇다 |

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_llm.py`:

```python
import typing

import anthropic

# anthropic 2.x는 httpx가 아니라 httpx2 위에 올라가 있다. SDK 예외를 직접
# 만들려면 SDK가 쓰는 쪽을 써야 한다. (우리 pipeline/lib/http.py는 httpx를
# 쓰므로 두 라이브러리가 한 프로젝트에 공존한다 — 섞지 않는다.)
import httpx2
import pytest
from pydantic import BaseModel

from pipeline.lib.llm import (
    FALLBACK_BETA,
    LLM,
    MODEL,
    SCHEMA_ATTEMPTS,
    Effort,
    RefusedError,
    SchemaError,
    classify_sdk_error,
    retry_on_schema,
)
from pipeline.lib.retry import Permanent, Transient
from tests.fakes import FakeLLM


class Answer(BaseModel):
    value: int


def _request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status: int, message: str = "실패"):
    """SDK 상태 예외를 테스트에서 직접 만든다."""
    return cls(message, response=httpx2.Response(status, request=_request()), body=None)


def _literals(tp) -> set[str]:
    """Literal 중첩·Optional·Union을 뚫고 문자열 값만 모은다."""
    found: set[str] = set()
    stack = [tp]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            found.add(current)
            continue
        args = typing.get_args(current)
        if args:
            stack.extend(args)
    return found


# --- SDK 계약 ---
#
# 아래 넷은 SDK가 바뀌면 깨지라고 둔 테스트다. 우리가 넘기는 문자열이
# SDK의 허용 목록에서 빠지면, 07:20에 무인으로 돌 때가 아니라 지금 알아야 한다.

def test_모델_ID에_날짜_접미사가_없다():
    """'claude-opus-5-5-20260401' 같은 형태는 존재하지 않는 모델이다.
    훈련 데이터에서 본 날짜 접미사를 붙이는 실수가 흔하다.
    """
    assert MODEL == "claude-opus-5-5"

    last = MODEL.split("-")[-1]
    assert not (last.isdigit() and len(last) == 8), f"날짜 접미사가 붙었다: {MODEL}"


def test_FALLBACK_BETA가_SDK의_허용_목록에_있다():
    """오타나 SDK의 베타 종료를 테스트에서 잡는다."""
    from anthropic.types.anthropic_beta_param import AnthropicBetaParam

    assert FALLBACK_BETA in _literals(AnthropicBetaParam)


def test_fallbacks_default가_SDK의_허용값이다():
    """모델 목록을 직접 관리하지 않으려고 "default"를 쓴다."""
    from anthropic.types.beta.beta_fallbacks_param import BetaFallbacksParam

    assert "default" in _literals(BetaFallbacksParam)


def test_Effort가_SDK의_단계와_같다():
    """SDK가 단계를 더하거나 빼면 알아야 한다."""
    from anthropic.types.beta.beta_output_config_param import BetaOutputConfigParam

    sdk_levels = _literals(typing.get_type_hints(BetaOutputConfigParam)["effort"])
    assert _literals(Effort) == sdk_levels


def test_parse에_필요한_인자가_모두_있다():
    """beta.messages.parse에만 betas·fallbacks가 있다. 비-beta parse로
    바꾸면 폴백을 넘길 수 없다.
    """
    import inspect

    client = anthropic.Anthropic(api_key="sk-ant-테스트용-호출하지-않는다")
    params = inspect.signature(client.beta.messages.parse).parameters

    for name in ("output_format", "output_config", "betas", "fallbacks"):
        assert name in params, name


# --- SDK 예외 분류 ---

def test_401은_영구_실패이고_키를_안내한다():
    mapped = classify_sdk_error(
        _status_error(anthropic.AuthenticationError, 401)
    )
    assert isinstance(mapped, Permanent)
    assert "ANTHROPIC_API_KEY" in str(mapped)


def test_403은_영구_실패다():
    mapped = classify_sdk_error(_status_error(anthropic.PermissionDeniedError, 403))
    assert isinstance(mapped, Permanent)


def test_404는_모델_ID를_안내한다():
    """가장 흔한 원인이 모델 ID 오타다."""
    mapped = classify_sdk_error(_status_error(anthropic.NotFoundError, 404))
    assert isinstance(mapped, Permanent)
    assert MODEL in str(mapped)


def test_400은_영구_실패다():
    mapped = classify_sdk_error(_status_error(anthropic.BadRequestError, 400))
    assert isinstance(mapped, Permanent)


def test_429는_일시_실패이고_크레딧을_언급한다():
    """SDK가 이미 재시도했는데도 왔다면 크레딧 소진일 수 있다."""
    mapped = classify_sdk_error(_status_error(anthropic.RateLimitError, 429))
    assert isinstance(mapped, Transient)
    assert "크레딧" in str(mapped)


def test_500은_일시_실패다():
    mapped = classify_sdk_error(_status_error(anthropic.InternalServerError, 500))
    assert isinstance(mapped, Transient)


def test_분류표에_없는_상태는_HTTP_규칙을_따른다():
    """418은 4xx이므로 영구 실패가 된다."""
    mapped = classify_sdk_error(_status_error(anthropic.APIStatusError, 418))
    assert isinstance(mapped, Permanent)


def test_연결_실패는_일시_실패다():
    """APIConnectionError는 APIStatusError의 하위가 아니다(형제다).
    위의 isinstance 사슬에서 안 걸리므로 따로 처리해야 한다."""
    assert not issubclass(anthropic.APIConnectionError, anthropic.APIStatusError)

    mapped = classify_sdk_error(
        anthropic.APIConnectionError(message="연결 거부", request=_request())
    )
    assert isinstance(mapped, Transient)


def test_타임아웃도_일시_실패다():
    """APITimeoutError는 APIConnectionError의 하위다. 사슬에서 잡혀야 한다."""
    assert issubclass(anthropic.APITimeoutError, anthropic.APIConnectionError)

    mapped = classify_sdk_error(anthropic.APITimeoutError(request=_request()))
    assert isinstance(mapped, Transient)


def test_SDK_예외가_아니면_그대로_돌려준다():
    """코드 버그(TypeError 등)를 Transient로 만들면 재시도로 가려진다."""
    original = TypeError("코드 버그")
    assert classify_sdk_error(original) is original


def test_분류_결과는_던지지_않고_돌려준다():
    """호출부가 `raise ... from error`로 원래 예외를 체인에 남길 수 있어야 한다."""
    result = classify_sdk_error(_status_error(anthropic.AuthenticationError, 401))
    assert isinstance(result, Exception)      # 반환값이다. 예외가 나지 않았다


# --- 스키마 재시도 ---

def test_한_번에_성공하면_한_번만_호출한다():
    calls = []

    def ok():
        calls.append(1)
        return "결과"

    assert retry_on_schema(ok) == "결과"
    assert len(calls) == 1


def test_스키마_실패는_다시_시도한다():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise SchemaError("출력이 비었다")
        return "결과"

    assert retry_on_schema(flaky) == "결과"
    assert len(calls) == 2


def test_스키마_실패가_계속되면_올린다():
    calls = []

    def always():
        calls.append(1)
        raise SchemaError("계속 비었다")

    with pytest.raises(SchemaError):
        retry_on_schema(always)
    assert len(calls) == SCHEMA_ATTEMPTS


def test_전송_계층_일시_실패는_재시도하지_않는다():
    """SDK가 이미 재시도했다. 여기서 또 하면 이중 재시도가 된다."""
    calls = []

    def transient():
        calls.append(1)
        raise Transient("SDK 재시도 후에도 실패")

    with pytest.raises(Transient):
        retry_on_schema(transient)
    assert len(calls) == 1


def test_영구_실패는_재시도하지_않는다():
    calls = []

    def permanent():
        calls.append(1)
        raise Permanent("키가 틀렸다")

    with pytest.raises(Permanent):
        retry_on_schema(permanent)
    assert len(calls) == 1


def test_거부는_재시도하지_않는다():
    """RefusedError는 Permanent의 하위다. 같은 입력은 또 거부된다."""
    calls = []

    def refused():
        calls.append(1)
        raise RefusedError("정책 거부")

    with pytest.raises(RefusedError):
        retry_on_schema(refused)
    assert len(calls) == 1


def test_거부는_영구_실패로_분류된다():
    """같은 입력을 다시 보내도 또 거부된다."""
    assert issubclass(RefusedError, Permanent)


def test_스키마_실패는_일시_실패로_분류된다():
    assert issubclass(SchemaError, Transient)


# --- 가짜 구현 ---

def test_가짜_LLM이_인터페이스를_만족한다():
    fake = FakeLLM(responses=[Answer(value=7)])

    # LLM이 runtime_checkable이라 실제로 확인된다. 타입 주석만 달면
    # 런타임에는 아무것도 검사되지 않는다.
    assert isinstance(fake, LLM)

    result, tokens = fake.parse(prompt="아무거나", output_format=Answer, effort="low")
    assert result.value == 7
    assert tokens > 0


def test_가짜_LLM이_받은_프롬프트를_기록한다():
    """프롬프트 조립을 테스트하려면 이게 필요하다."""
    fake = FakeLLM(responses=[Answer(value=1)])
    fake.parse(prompt="관심사: AI", output_format=Answer, effort="low")

    assert fake.prompts == ["관심사: AI"]


def test_가짜_LLM이_응답을_순서대로_돌려준다():
    fake = FakeLLM(responses=[Answer(value=1), Answer(value=2)])

    first, _ = fake.parse(prompt="a", output_format=Answer, effort="low")
    second, _ = fake.parse(prompt="b", output_format=Answer, effort="low")

    assert (first.value, second.value) == (1, 2)


def test_가짜_LLM이_응답이_떨어지면_알려준다():
    """조용히 None을 돌려주면 그 다음 단계에서 엉뚱한 에러가 난다."""
    fake = FakeLLM(responses=[Answer(value=1)])
    fake.parse(prompt="a", output_format=Answer, effort="low")

    with pytest.raises(AssertionError, match="준비된 응답이 없다"):
        fake.parse(prompt="b", output_format=Answer, effort="low")
```

- [x] **Step 2: 실패를 확인**

```bash
pytest tests/test_llm.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.llm'`

- [x] **Step 3: 최소 구현 작성**

`pipeline/lib/llm.py`:

```python
"""Claude API 래퍼.

파이프라인 단계는 LLM 프로토콜만 알고 SDK를 모른다. 테스트는 FakeLLM을
넘기므로 실제 호출이 일어나지 않는다.

재시도 책임 분담:
- 전송 계층(429/5xx/연결 오류) → **SDK가 담당한다**(max_retries).
- 스키마 검증 실패 → 이 모듈이 1회 재시도한다.
- 그 외 → 분류만 하고 올린다.
"""

from typing import Callable, Literal, Protocol, TypeVar, runtime_checkable

import anthropic
from pydantic import BaseModel

from pipeline.lib.http import classify_status
from pipeline.lib.retry import Permanent, Transient

# 스펙 결정: 선별·요약 모두 Opus. Max 플랜 크레딧으로 비용 제약이 없으므로
# 품질 기준으로만 고른다. 바꾸려면 이 한 줄만 고친다.
#
# 날짜 접미사를 붙이지 않는다. 'claude-opus-5-5-20260401' 같은 ID는 존재하지
# 않는다(test_모델_ID에_날짜_접미사가_없다가 지킨다).
MODEL = "claude-opus-5-5"

# 거부(refusal)가 났을 때 서버 측에서 다른 모델로 자동 재시도하게 한다.
# fallbacks="default"는 거부 범주에 따라 서버가 라우팅하므로 모델 목록을
# 직접 관리하지 않아도 된다. 이 문자열이 SDK의 허용 목록에 있는지는
# test_FALLBACK_BETA가_SDK의_허용_목록에_있다가 확인한다.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# SDK의 전송 계층 재시도 횟수. 기본값은 2이고, 명시해 두면 "여기가 전송
# 재시도를 담당한다"가 코드에 드러난다.
SDK_MAX_RETRIES = 3

# 스키마 검증 실패에 대한 내 쪽 시도 횟수(최초 1회 + 재시도 1회).
SCHEMA_ATTEMPTS = 2

# 비스트리밍 요청의 기본 출력 상한. 이보다 크게 잡으려면 스트리밍으로
# 바꿔야 한다 — SDK HTTP 타임아웃에 걸린다.
DEFAULT_MAX_TOKENS = 16000

Effort = Literal["low", "medium", "high", "xhigh", "max"]
TOut = TypeVar("TOut", bound=BaseModel)
TResult = TypeVar("TResult")


class RefusedError(Permanent):
    """정책 거부. 같은 입력을 다시 보내도 또 거부되므로 재시도하지 않는다."""


class SchemaError(Transient):
    """구조화된 출력이 비었거나 스키마를 못 맞췄다. 한 번 더 시도할 가치가 있다."""


@runtime_checkable
class LLM(Protocol):
    """파이프라인이 기대하는 LLM의 모양.

    runtime_checkable이라 `isinstance(fake, LLM)`로 실제 확인할 수 있다
    (메서드 이름만 본다 — 서명은 보지 않는다). 타입 주석만 달면 런타임에는
    아무것도 검사되지 않는다.
    """

    def parse(
        self,
        *,
        prompt: str,
        output_format: type[TOut],
        effort: Effort,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> tuple[TOut, int]:
        """구조화된 출력을 받는다. (파싱된 결과, 입력 토큰 수)를 돌려준다."""
        ...


def classify_sdk_error(error: Exception) -> Exception:
    """anthropic SDK 예외를 Transient/Permanent로 바꿔 **돌려준다**(던지지 않는다).

    돌려주는 쪽으로 만든 이유는 호출부에서 `raise ... from error`로 원래
    예외를 체인으로 보존하기 위함이다.
    """
    # 아래 다섯 클래스는 모두 APIStatusError의 하위다. 구체적인 것부터
    # 검사해야 한다 — 순서를 바꾸면 전부 마지막 분기로 빨려 들어간다.
    if isinstance(error, anthropic.AuthenticationError):
        return Permanent(
            f"API 키가 거부됐다(401). ANTHROPIC_API_KEY가 Max 크레딧이 연결된 "
            f"Console 조직의 키인지 확인한다: {error}"
        )
    if isinstance(error, anthropic.PermissionDeniedError):
        return Permanent(
            f"권한이 없다(403). Console 조직·워크스페이스 설정을 확인한다: {error}"
        )
    if isinstance(error, anthropic.NotFoundError):
        return Permanent(
            f"찾을 수 없다(404). 가장 흔한 원인은 모델 ID 오타다. "
            f"현재 설정: '{MODEL}'. 원문: {error}"
        )
    if isinstance(error, anthropic.BadRequestError):
        return Permanent(
            f"요청이 거부됐다(400). 프롬프트 길이, max_tokens, output_config를 "
            f"확인한다: {error}"
        )
    if isinstance(error, anthropic.RateLimitError):
        # SDK가 이미 재시도했는데도 왔다. 단순 혼잡이 아닐 수 있다.
        return Transient(
            f"레이트 리밋 또는 크레딧 소진(429). SDK 재시도 후에도 실패했다. "
            f"Console의 크레딧 잔액을 확인한다: {error}"
        )
    if isinstance(error, anthropic.APIStatusError):
        # 나머지 비 2xx는 HTTP 분류 규칙을 그대로 쓴다(규칙이 한곳에 있어야 한다).
        try:
            classify_status(
                error.status_code, url="Claude API", detail=str(error)[:200]
            )
        except (Transient, Permanent) as classified:
            return classified
        # classify_status는 비 2xx면 반드시 던지므로 여기 오지 않는다.
        return Transient(f"예상치 못한 응답: {error}")
    if isinstance(error, anthropic.APIConnectionError):
        # APIStatusError의 하위가 아니라 형제다. 위 분기에서 걸리지 않는다.
        # APITimeoutError가 이쪽의 하위라서 여기서 함께 잡힌다.
        return Transient(
            f"Claude API 연결 실패. SDK 재시도 후에도 실패했다: {error}"
        )

    # SDK 예외가 아니다 — 코드 버그일 수 있으므로 분류하지 않고 그대로 돌려준다.
    # 여기서 Transient로 감싸면 TypeError가 재시도로 가려진다.
    return error


def retry_on_schema(
    call: Callable[[], TResult],
    *,
    attempts: int = SCHEMA_ATTEMPTS,
) -> TResult:
    """SchemaError만 재시도한다.

    lib.retry.with_retry를 쓰지 않는 이유: SchemaError와 전송 계층 Transient가
    둘 다 Transient라서 with_retry는 구분하지 못한다. 전송 재시도는 SDK가 이미
    하므로, 여기서는 스키마 실패만 다시 시도해야 한다.
    """
    for attempt in range(attempts):
        try:
            return call()
        except SchemaError:
            if attempt == attempts - 1:
                raise
    raise AssertionError("도달할 수 없다")   # attempts >= 1


class AnthropicLLM:
    """LLM 프로토콜의 Claude API 구현.

    SDK 호출 자체는 단위 테스트하지 않는다 — 모킹하면 '내가 쓴 모킹이 맞는가'만
    검증하게 된다. 분류와 재시도는 위의 순수 함수로 빼서 테스트했고, SDK가
    받아들이는 인자·문자열은 계약 테스트로 고정했고, 실제 동작은
    scripts/smoke_llm.py로 1회 확인한다.
    """

    def __init__(
        self,
        api_key: str,
        model: str = MODEL,
        max_retries: int = SDK_MAX_RETRIES,
    ) -> None:
        # max_retries를 명시한다. SDK가 429/5xx/연결 오류를 이 횟수만큼
        # 지수 백오프로 재시도한다.
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=max_retries)
        self._model = model

    def parse(
        self,
        *,
        prompt: str,
        output_format: type[TOut],
        effort: Effort,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> tuple[TOut, int]:
        return retry_on_schema(
            lambda: self._parse_once(
                prompt=prompt,
                output_format=output_format,
                effort=effort,
                max_tokens=max_tokens,
            )
        )

    def _parse_once(
        self,
        *,
        prompt: str,
        output_format: type[TOut],
        effort: Effort,
        max_tokens: int,
    ) -> tuple[TOut, int]:
        try:
            # beta.messages.parse를 쓴다. 비-beta messages.parse에는
            # betas·fallbacks 인자가 없어서 거부 폴백을 넘길 수 없다
            # (test_parse에_필요한_인자가_모두_있다가 고정한다).
            #
            # thinking은 **넘기지 않는다.** Opus 5.5는 사고가 항상 켜져 있고
            # {"type": "disabled"}나 budget_tokens는 어떤 effort에서도 400이다.
            # 깊이 조절은 output_config의 effort로만 한다.
            response = self._client.beta.messages.parse(
                model=self._model,
                max_tokens=max_tokens,
                # fallbacks: 정책 거부 시 서버가 다른 모델로 같은 요청을
                # 재실행한다. "default"는 거부 범주에 따라 자동 라우팅하므로
                # 모델 목록을 직접 관리하지 않아도 된다.
                betas=[FALLBACK_BETA],
                fallbacks="default",
                # effort는 추론 깊이와 토큰 지출을 조절한다. Opus 5.5의
                # 기본값은 medium이지만 단계마다 명시해 넘긴다 —
                # 채점에는 low, 요약에는 medium을 쓴다.
                output_config={"effort": effort},
                # output_format은 **parse 헬퍼 자신의 인자**다. messages.create의
                # 폐기된 output_format과 다르다(create에서는 output_config.format을
                # 쓴다). parse에 pydantic 모델 클래스를 넘기면 응답이 그 스키마를
                # 따르고 parsed_output으로 검증된 객체가 나온다.
                output_format=output_format,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as error:  # noqa: BLE001 — classify_sdk_error가 선별한다
            raise classify_sdk_error(error) from error

        # 거부는 예외가 아니라 HTTP 200 + stop_reason으로 온다.
        # content를 읽기 전에 반드시 확인한다. stop_details는 거부일 때만
        # 채워지고 그 외에는 None이므로 순서가 중요하다.
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            raise RefusedError(
                f"정책 거부 (category={category}). 서버 측 폴백도 실패했다. "
                f"같은 입력은 다시 보내도 거부된다."
            )

        # parsed_output은 content 블록을 훑는 프로퍼티다. 스키마를 못 맞췄으면
        # None이 나온다.
        parsed = response.parsed_output
        if parsed is None:
            raise SchemaError("구조화된 출력이 비어 있다")

        return parsed, response.usage.input_tokens
```

> **설명** — `classify_sdk_error`가 예외를 **던지지 않고 돌려주는** 설계가
> 낯설 수 있다. 호출부에서 `raise classify_sdk_error(error) from error`라고
> 쓰면 원래 SDK 예외가 트레이스백에 함께 남는다. 함수 안에서 던지면 그
> 체인이 끊긴다.
>
> `isinstance` 사슬의 **순서가 정답을 바꾼다.**
> `AuthenticationError`·`NotFoundError`·`RateLimitError` 등은 모두
> `APIStatusError`의 하위이므로, `APIStatusError` 검사를 위로 올리면 모든
> 에러가 거기서 잡혀 401과 500이 같은 분류가 된다. **실측으로 확인했다:**
> `APIConnectionError`만 형제이고 나머지는 전부 하위다.
>
> `@runtime_checkable`을 붙인 Protocol은 `isinstance`로 검사할 수 있다.
> 단 **메서드 이름만** 본다 — 서명은 보지 않는다. 그래도 타입 주석보다는
> 낫다(주석은 런타임에 아무것도 하지 않는다).
>
> **구문법 대조** — `type[TOut]`은 "클래스 자체"를 받는 타입이다(인스턴스가
> 아니라 `ScoreSheet`라는 클래스를 넘긴다). 구형 코드에서는 `Type[TOut]`으로
> 썼다. `tuple[TOut, int]`도 구형에서는 `Tuple[TOut, int]`였다.

- [x] **Step 4: 가짜 LLM을 `tests/fakes.py`에 추가**

```python
class FakeLLM:
    """미리 준비한 응답을 순서대로 돌려준다.

    HTTP 모킹이 필요 없고, 받은 프롬프트를 기록하므로 프롬프트 조립을
    테스트할 수 있다.
    """

    def __init__(self, responses: list, input_tokens: int = 1000) -> None:
        self._responses = list(responses)
        self._input_tokens = input_tokens
        self.prompts: list[str] = []

    def parse(self, *, prompt: str, output_format, effort, max_tokens: int = 16000):
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("FakeLLM에 준비된 응답이 없다. responses를 더 넣는다.")
        return self._responses.pop(0), self._input_tokens
```

- [x] **Step 5: 통과를 확인**

```bash
pytest tests/test_llm.py
```

Expected: `28 passed`. 전체 `180 passed`.

- [x] **Step 6: 실제 API 연결 확인 스크립트 작성**

`scripts/smoke_llm.py`:

```python
"""Claude API 연결과 구조화된 출력을 1회 확인한다.

실행: python scripts/smoke_llm.py
크레딧을 아주 조금 쓴다.

단위 테스트는 SDK를 호출하지 않는다(FakeLLM을 쓴다). 그래서 "실제로
붙는가"는 이 스크립트만 확인할 수 있다.
"""

from pydantic import BaseModel

from pipeline.lib.llm import (
    FALLBACK_BETA,
    MODEL,
    SDK_MAX_RETRIES,
    AnthropicLLM,
)
from pipeline.lib.retry import Permanent, Transient
from pipeline.lib.secrets import require


class Verdict(BaseModel):
    score: int
    reason: str


def main() -> None:
    llm = AnthropicLLM(require("ANTHROPIC_API_KEY"))

    prompt = (
        "다음 글 제목이 백엔드 개발자에게 얼마나 유용한지 0~100으로 채점하고 "
        "이유를 한 문장으로 써라.\n\n"
        "제목: 결제 서버 P99 지연을 400ms에서 40ms로 줄인 과정"
    )

    print(f"모델: {MODEL}")
    print(f"SDK 전송 재시도: {SDK_MAX_RETRIES}회")
    print(f"거부 시 서버 측 폴백: 켜짐 ({FALLBACK_BETA}, fallbacks=\"default\")")
    print()

    try:
        verdict, input_tokens = llm.parse(
            prompt=prompt, output_format=Verdict, effort="low", max_tokens=2000
        )
    except Permanent as error:
        # 분류가 제대로 작동하는지 여기서도 확인된다 — 설정 문제면
        # 재시도 없이 안내가 붙은 메시지가 나온다.
        print(f"[설정 문제] {error}")
        raise SystemExit(1)
    except Transient as error:
        print(f"[일시 문제] {error}")
        raise SystemExit(1)

    print(f"입력 토큰: {input_tokens}")
    print(f"점수: {verdict.score}")
    print(f"이유: {verdict.reason}")
    print()

    # 스키마를 실제로 지켰는지 확인한다. parse가 돌려준 객체는 pydantic이
    # 검증한 것이므로 타입은 보장되지만, 값의 범위는 모델이 지켜야 한다.
    if not 0 <= verdict.score <= 100:
        print(f"[경고] 점수가 0~100을 벗어났다: {verdict.score}")
        print("선별 프롬프트에서 범위를 더 강하게 못 박아야 한다.")
        raise SystemExit(1)

    print("성공. 구조화된 출력이 스키마대로 돌아왔다.")


if __name__ == "__main__":
    main()
```

- [x] **Step 7: 실제로 실행해 확인**

```bash
python scripts/smoke_llm.py
```

**실측 (2026-11-12):**

```
모델: claude-opus-5-5
SDK 전송 재시도: 3회
거부 시 서버 측 폴백: 켜짐 (server-side-fallback-2026-07-01, fallbacks="default")

입력 토큰: 338
점수: 85
이유: 결제 서버라는 실무 도메인에서 P99 지연을 10배 줄인 구체적 성능 최적화
      사례로 보여 백엔드 개발자가 바로 참고할 만한 실전 지식일 가능성이 높지만,
      제목만으로는 적용 기술이나 범용성을 판단하기 어렵다.

성공. 구조화된 출력이 스키마대로 돌아왔다.
```

4.4초, 종료 코드 0. **한국어 출력이 프롬프트만으로 자연스럽게 나왔다** —
요약 단계에서 번역을 위한 추가 장치가 필요하지 않다는 첫 증거다.

`[설정 문제]`가 나오면 메시지가 원인을 알려준다 — 401이면 키, 404면 모델 ID다.

- [x] **Step 8: 커밋**

```bash
git add pipeline/lib/llm.py tests/fakes.py tests/test_llm.py scripts/smoke_llm.py
git commit -m "feat: Claude API 래퍼 — SDK에 전송 재시도 위임, 예외 분류, 스키마 1회 재시도"
```

---

## Task 16: 선별

**Files:**
- Create: `pipeline/rank.py`
- Create: `tests/test_rank.py`
- Modify: `pipeline/lib/llm.py` (스트리밍 전환, 잘림 분류)
- Modify: `pipeline/models.py` (`Topic` Literal)

> **실제 규모로 돌려 보고 세 가지가 드러났다** (테스트 18개 → 43개).
> 단위 테스트는 항목 2~15건으로 돌아서 전부 통과했는데, **240건을 넣자
> 셋이 연달아 터졌다.** 규모가 바뀌면 다른 코드가 된다.
>
> ### 1. 출력이 `max_tokens`에 걸려 잘린다
>
> 실측(2026-11-12): 240건을 한 프롬프트에 넣으면 입력 **42,135토큰**,
> `ScoreItem` 한 건이 JSON으로 **82토큰**이라 출력에 **18,614토큰**이 필요하다.
> 래퍼의 기본값 16,000으로는 모자란다.
>
> 잘리면 `stop_reason=max_tokens`로 오는데, 계획의 래퍼는 그걸 보지 않고
> `parsed_output is None`만 봐서 **"구조화된 출력이 비어 있다"**를 던진다.
> 그건 `SchemaError`(Transient)라서 한 번 더 호출하고, 똑같이 잘리고, 결국
> 실패한다 — **토큰을 두 배 쓰고 원인은 안 알려주는 실패**다.
>
> 고친 것:
> - `lib/llm.classify_response()`로 거부·잘림·스키마 실패를 **순서대로** 가려낸다
> - `TruncatedError(Permanent)` 추가 — 재시도해도 같으므로 Permanent다
> - `rank.rank_max_tokens(항목수)`로 기본값에 맡기지 않고 계산해 넘긴다
>
> ### 2. SDK가 비스트리밍을 거부한다
>
> 계산한 `max_tokens=34,400`을 보냈더니 **1초 만에** 거부당했다:
>
> ```
> ValueError: Streaming is required for operations that may take longer
>             than 10 minutes
> ```
>
> SDK 내부(`_base_client._calculate_nonstreaming_timeout`)가 막는다:
>
> ```
> expected_time = 3600 * max_tokens / 128_000
> expected_time > 600초 이면 ValueError
> → max_tokens > 128_000 * 600 / 3600 = 21,333 이면 거부
> ```
>
> 항목을 쪼개면 **한 번에 넣어야 가능한 교차 판단(같은 사건 중복)이
> 깨진다** — 그게 일괄 채점의 이유였다. 그래서 스트리밍을 넣었다.
> `beta.messages.stream(...).get_final_message()`가 `parse()`와 **같은
> `ParsedBetaMessage`를 돌려주므로** 응답 처리는 한 갈래로 끝난다.
> 래퍼가 `needs_streaming(max_tokens)`로 알아서 고르고, 호출하는 단계는
> 이걸 신경 쓰지 않는다.
>
> **결과: 240건 채점이 65초에 끝났다.** 240건 전부 채점됐다(누락 0).
>
> ### 3. 가중치 상한이 상위 순서를 납작하게 만든다
>
> 첫 성공 실행의 상위 6건이 **전부 100점**이었다. LLM 원점수는 잘 퍼져
> 있었는데(최고 92, 최저 1, 중앙값 30, 90점 초과가 3건) **100점 쏠림은
> 우리 상한이 만든 것**이었다:
>
> ```
> 원 90 ×1.3 = 117.0 → 100
> 원 85 ×1.3 = 110.5 → 100
> 원 88 ×1.2 = 105.6 → 100
> 원 85 ×1.2 = 102.0 → 100
> ```
>
> 하필 **상위 10건을 고르는 자리**에서 순서가 사라졌다. 동점이면 입력
> 순서로 결정되므로, TOP_N 경계에서 누가 잘리는지가 임의로 정해진다.
>
> 고친 것: **정렬은 상한 없는 값(`weighted_score`)으로, 표시·저장은 상한
> 있는 값(`apply_weight`)으로** 한다. `score`의 계약이 0~100이고 DB 제약도
> 같아서 120점을 보여 줄 수는 없다.
>
> 재실행으로 확인:
>
> ```
> 표시 100  원 90 ×1.3 = 117.0  [토스_기술블로그]
> 표시 100  원 90 ×1.3 = 117.0  [네이버_D2]
> 표시 100  원 85 ×1.3 = 110.5  [네이버_D2]
> 표시 100  원 90 ×1.2 = 108.0  [Hacker_News_Best]
> 표시 100  원 85 ×1.2 = 102.0  [Shopify_Engineering]
> 표시  98  원 82 ×1.2 =  98.4  [Cloudflare_Blog]
> ```
>
> 전부 100으로 표시되지만 순서는 살아 있다.
>
> ### 그 밖에 측정하고 **고치지 않은** 것
>
> **`reason`이 짧다 — 중앙값 9자.** 처음엔 결함으로 봤는데, 점수대별로 나눠
> 보니 길이가 점수에 따라 늘어났다:
>
> | 점수대 | 건수 | 이유 길이 중앙값 |
> |---|---:|---:|
> | 80+ | 12 | 18자 |
> | 60~79 | 37 | 16자 |
> | 40~59 | 45 | 13자 |
> | 0~39 | 146 | 7자 |
>
> 2점짜리 "데브시스터즈, 3분기 매출 껑충"에 `"실적."`이면 **그게 정확히 맞는
> 길이다.** 모델이 알맞게 아끼고 있다. 증거 없이 `min_length`를 걸지 않았다.
> Task 17의 `evaluate`가 이유로 부족하다고 판단하면 그때 근거를 들고 고친다.
>
> **`topic`은 Literal로 묶었다 — 그리고 Task 19에서 되돌렸다.**
>
> 처음 판단: 240건 모두 프롬프트의 다섯 값 안이었지만 DB 컬럼을 프롬프트
> 준수에만 의존하는 것은 약하니, `Topic` Literal로 두면 JSON 스키마에
> `enum`이 들어가 API가 생성 단계에서 막는다 — **"막는다"가 검증되지 않은
> 가정이었다.**
>
> Task 19에서 `maxLength: 30`인 헤드라인이 **33자로 왔다.** pydantic이 시트
> **전체**를 거부해 요약 7건이 한꺼번에 날아갔다. 같은 종류의 제약이므로
> `topic`도 어길 수 있고, 그러면 **채점 240건이 통째로** 날아간다.
>
> 그래서 규칙을 세웠다 — **LLM 초안은 느슨하게, 우리 계약은 엄격하게,
> 경계에서 정규화.** `ScoreItem`에서 제약을 빼고 `rank.clamp_score`·
> `rank.normalize_topic`이 고치며, `RankedItem`이 계약을 지킨다.
>
> **enum을 빼도 품질이 떨어지지 않았다**(실측):
>
> | topic | enum 있음 | enum 없음 |
> |---|---:|---:|
> | AI | 82 | 85 |
> | other | 93 | 89 |
> | backend | 23 | 23 |
> | tooling | 20 | 24 |
> | infra | 22 | 19 |
>
> 다섯 값 밖으로 나온 것은 **0건**이다. 프롬프트의 "AI / backend / infra /
> tooling / other 중 하나"가 그 역할을 한다.
>
> **중복 판정은 아직 한 번도 돌지 않았다.** `recent_headlines`가 0건이라
> (아직 발행한 글이 없다) `build_prompt`가 그 섹션을 생략한다. 첫 발송
> 이후에 자연히 켜진다. 조립 자체는 단위 테스트가 지킨다.

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_rank.py`:

```python
import pytest
from pydantic import ValidationError

from pipeline.lib.llm import TruncatedError
from pipeline.models import RawItem, ScoreItem, ScoreSheet
from pipeline.rank import (
    MAX_OUTPUT_TOKENS,
    OUTPUT_TOKENS_PER_ITEM,
    RANK_EFFORT,
    THINKING_ALLOWANCE,
    TOP_N,
    apply_weight,
    build_prompt,
    rank,
    rank_max_tokens,
    weighted_score,
)
from tests.fakes import FakeLLM

WINDOW = ("2026-11-09T22:20:00+00:00", "2026-11-10T22:20:00+00:00")


def _item(index: int, source: str = "토스_기술블로그") -> RawItem:
    return RawItem(
        source=source,
        title=f"제목 {index}",
        url=f"https://e.com/{index}",
        published="2026-11-10T05:30:00+00:00",
        excerpt=f"발췌 {index}",
    )


# --- 가중치 ---

def test_가중치를_점수에_곱한다():
    assert apply_weight(60, 1.3) == 78


def test_가중치_적용_후_100을_넘지_않는다():
    assert apply_weight(90, 1.3) == 100


def test_가중치가_1이면_점수가_그대로다():
    assert apply_weight(73, 1.0) == 73


def test_가중치가_점수를_내릴_수도_있다():
    assert apply_weight(80, 0.9) == 72


# --- 출력 토큰 산정 ---
#
# 2026-11-12 실측: 227건을 한 프롬프트에 넣으면 입력 42,135토큰이고
# 출력은 ScoreItem 한 건당 82토큰이라 18,614토큰이 필요하다. 기본값
# 16,000으로는 잘린다 — 그러면 stop_reason=max_tokens로 와서 재시도해도
# 똑같이 잘린다. 그래서 항목 수에 맞춰 계산한다.

def test_항목_수에_비례해_늘어난다():
    적음 = rank_max_tokens(10)
    많음 = rank_max_tokens(200)
    assert 많음 > 적음


def test_사고_토큰_여유를_더한다():
    """Opus 5.5는 사고가 항상 켜져 있고 사고 토큰도 max_tokens에 든다."""
    assert rank_max_tokens(0) >= THINKING_ALLOWANCE


def test_실측한_227건을_담을_수_있다():
    """출력 18,614토큰 + 사고. 이게 96시간 윈도우의 현실적 상한이다."""
    assert rank_max_tokens(227) >= 18_614 + THINKING_ALLOWANCE


def test_실측값보다_넉넉하게_잡는다():
    """이유 문장이 길어질 수 있다. 실측 82토큰보다 여유를 둔다."""
    assert OUTPUT_TOKENS_PER_ITEM > 82


def test_상한을_넘지_않는다():
    assert rank_max_tokens(100_000) == MAX_OUTPUT_TOKENS


def test_현실적_상한에_여유가_남아_있다():
    """윈도우가 96시간으로 묶여 있어 227건이 현실적 최대였다.
    소스를 늘려도 한동안 버티는지 확인한다 — 이 테스트가 깨지면
    스트리밍을 도입할 때가 된 것이다.
    """
    여유 = (MAX_OUTPUT_TOKENS - THINKING_ALLOWANCE) // OUTPUT_TOKENS_PER_ITEM
    assert 여유 >= 300, f"항목 {여유}건까지만 담긴다. 227건 실측 대비 여유가 부족하다"


def test_산정한_max_tokens를_LLM에_넘긴다():
    """계산만 하고 넘기지 않으면 아무 의미가 없다."""
    items = [_item(i) for i in range(50)]
    scores = [ScoreItem(index=i, score=70, reason="r", topic="AI") for i in range(50)]
    _, llm = _rank(items, scores)

    assert llm.calls[0]["max_tokens"] == rank_max_tokens(50)


def test_채점은_낮은_effort로_한다():
    """깊은 추론이 필요 없다. 토큰을 아낀다."""
    _, llm = _rank([_item(0)], [ScoreItem(index=0, score=70, reason="r", topic="AI")])
    assert llm.calls[0]["effort"] == RANK_EFFORT == "low"


def test_항목이_너무_많으면_잘리기_전에_거부한다():
    """조용히 잘리는 것보다 이유를 아는 실패가 낫다."""
    한계 = (MAX_OUTPUT_TOKENS - THINKING_ALLOWANCE) // OUTPUT_TOKENS_PER_ITEM
    items = [_item(i) for i in range(한계 + 1)]
    llm = FakeLLM(responses=[])

    with pytest.raises(TruncatedError, match="항목"):
        rank(
            items=items, interests="i", recent_headlines=[], weights={},
            llm=llm, window_start=WINDOW[0], window_end=WINDOW[1],
        )
    assert llm.prompts == []      # 토큰을 쓰지 않고 거부했다


# --- 프롬프트 조립 ---

def test_프롬프트에_관심사_프로필이_들어간다():
    prompt = build_prompt(
        interests="나는 백엔드 개발자다", recent_headlines=[], items=[_item(0)]
    )
    assert "나는 백엔드 개발자다" in prompt


def test_프롬프트에_최근_헤드라인이_들어간다():
    """같은 사건 중복 판정의 입력."""
    prompt = build_prompt(
        interests="i", recent_headlines=["어제 다룬 그 글"], items=[_item(0)]
    )
    assert "어제 다룬 그 글" in prompt


def test_프롬프트에_항목이_번호와_함께_들어간다():
    """LLM이 index로 참조하므로 번호가 정확해야 한다."""
    prompt = build_prompt(interests="i", recent_headlines=[], items=[_item(0), _item(1)])

    assert "[0]" in prompt and "[1]" in prompt
    assert "제목 0" in prompt and "제목 1" in prompt


def test_최근_헤드라인이_없으면_중복_섹션을_생략한다():
    prompt = build_prompt(interests="i", recent_headlines=[], items=[_item(0)])
    assert "최근 발행" not in prompt


def test_프롬프트가_모든_항목에_점수를_요구한다():
    """빠진 항목은 조용히 버려진다. 프롬프트가 전부 채점하라고 말해야 한다."""
    prompt = build_prompt(
        interests="i", recent_headlines=[], items=[_item(i) for i in range(3)]
    )
    assert "3" in prompt and "빠뜨리지" in prompt


def test_발췌를_잘라_토큰을_아낀다():
    긴발췌 = "가" * 2000
    item = RawItem(source="s", title="t", url="https://e.com/1",
                   published="2026-11-10T05:30:00+00:00", excerpt=긴발췌)

    prompt = build_prompt(interests="i", recent_headlines=[], items=[item])
    assert 긴발췌 not in prompt
    assert "가" * 400 in prompt


# --- 선별 ---

def _rank(items, scores, weights=None):
    llm = FakeLLM(responses=[ScoreSheet(scores=scores)])
    return rank(
        items=items,
        interests="i",
        recent_headlines=[],
        weights=weights or {"토스_기술블로그": 1.0},
        llm=llm,
        window_start=WINDOW[0],
        window_end=WINDOW[1],
    ), llm


def test_점수_내림차순으로_정렬한다():
    items = [_item(0), _item(1), _item(2)]
    scores = [
        ScoreItem(index=0, score=50, reason="r", topic="AI"),
        ScoreItem(index=1, score=90, reason="r", topic="AI"),
        ScoreItem(index=2, score=70, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert [r.score for r in bundle.selected] == [90, 70, 50]


def test_상위_N건만_선택한다():
    items = [_item(i) for i in range(TOP_N + 5)]
    scores = [
        ScoreItem(index=i, score=100 - i, reason="r", topic="AI")
        for i in range(TOP_N + 5)
    ]
    bundle, _ = _rank(items, scores)

    assert len(bundle.selected) == TOP_N


def test_전체_점수를_모두_보관한다():
    """탈락 이유를 나중에 조회하려면 전체가 필요하다."""
    items = [_item(i) for i in range(TOP_N + 5)]
    scores = [
        ScoreItem(index=i, score=100 - i, reason=f"이유 {i}", topic="AI")
        for i in range(TOP_N + 5)
    ]
    bundle, _ = _rank(items, scores)

    assert len(bundle.all_scores) == TOP_N + 5


def test_소스_가중치를_반영한다():
    items = [_item(0, "일반매체"), _item(1, "토스_기술블로그")]
    scores = [
        ScoreItem(index=0, score=70, reason="r", topic="AI"),
        ScoreItem(index=1, score=60, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores, weights={"일반매체": 0.9, "토스_기술블로그": 1.3})

    # 70*0.9=63, 60*1.3=78 → 토스가 앞으로 온다
    assert bundle.selected[0].item.source == "토스_기술블로그"
    assert bundle.selected[0].score == 78


def test_가중치_표에_없는_소스는_1로_본다():
    """설정이 빠져도 죽지 않아야 한다."""
    bundle, _ = _rank([_item(0, "모르는소스")],
                      [ScoreItem(index=0, score=70, reason="r", topic="AI")],
                      weights={})
    assert bundle.selected[0].score == 70


def test_범위를_벗어난_index는_무시한다():
    """LLM이 없는 번호를 돌려줘도 IndexError로 죽지 않아야 한다."""
    items = [_item(0)]
    scores = [
        ScoreItem(index=0, score=80, reason="r", topic="AI"),
        ScoreItem(index=99, score=90, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert len(bundle.selected) == 1


def test_음수_index는_계약_경계에서_막힌다():
    """`rank`의 `0 <= index` 검사보다 먼저, pydantic이 거부한다.

    `ScoreItem.index`에 `ge=0`이 있어 **스키마에도 minimum 0이 들어간다** —
    LLM이 음수를 돌려줄 길이 없고, 돌려줘도 파싱에서 걸린다. 검사가
    없으면 `index=-1`이 `items[-1]`(마지막 항목)을 가리킬 뻔했다.
    """
    with pytest.raises(ValidationError):
        ScoreItem(index=-1, score=90, reason="r", topic="AI")


def test_점수_범위도_계약_경계에서_막힌다():
    """0~100을 벗어난 점수는 가중치 계산과 임계값 판정을 무의미하게 만든다."""
    with pytest.raises(ValidationError):
        ScoreItem(index=0, score=101, reason="r", topic="AI")
    with pytest.raises(ValidationError):
        ScoreItem(index=0, score=-1, reason="r", topic="AI")


def test_같은_index를_두_번_주면_한_번만_센다():
    items = [_item(0), _item(1)]
    scores = [
        ScoreItem(index=0, score=80, reason="r", topic="AI"),
        ScoreItem(index=0, score=90, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert len(bundle.selected) == 1


def test_먼저_나온_점수를_쓴다():
    """중복 index에서 어느 쪽을 쓰는지가 정해져 있어야 한다."""
    items = [_item(0), _item(1)]
    scores = [
        ScoreItem(index=0, score=80, reason="먼저", topic="AI"),
        ScoreItem(index=0, score=90, reason="나중", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert bundle.selected[0].reason == "먼저"


def test_채점되지_않은_항목은_빠진다():
    """LLM이 일부를 빼먹으면 그 항목은 순위에 들어올 수 없다.
    all_scores와 수집 건수를 비교하면 누락이 드러난다 —
    main()이 양쪽을 함께 출력한다.
    """
    items = [_item(0), _item(1), _item(2)]
    scores = [ScoreItem(index=0, score=80, reason="r", topic="AI")]
    bundle, _ = _rank(items, scores)

    assert len(bundle.all_scores) == 1
    assert len(bundle.selected) == 1


def test_최고_점수를_기록한다():
    """0건인 날 화면이 "최고 54점 / 기준 60점"을 보여주는 데 쓴다."""
    items = [_item(0), _item(1)]
    scores = [
        ScoreItem(index=0, score=50, reason="r", topic="AI"),
        ScoreItem(index=1, score=90, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert bundle.max_score == 90


def test_가중치_적용_후의_점수를_최고로_기록한다():
    items = [_item(0, "토스_기술블로그")]
    scores = [ScoreItem(index=0, score=60, reason="r", topic="AI")]
    bundle, _ = _rank(items, scores, weights={"토스_기술블로그": 1.3})

    assert bundle.max_score == 78


def test_수집이_0건이면_최고_점수가_없다():
    llm = FakeLLM(responses=[])
    bundle = rank(
        items=[], interests="i", recent_headlines=[], weights={},
        llm=llm, window_start=WINDOW[0], window_end=WINDOW[1],
    )
    assert bundle.max_score is None


def test_채점_결과가_모두_버려져도_최고_점수가_없다():
    """"최고 0점"과 "점수 없음"은 다르다. 0으로 두면 0건인 날 화면이
    "최고 0점"이라고 거짓말한다.
    """
    bundle, _ = _rank([_item(0)], [ScoreItem(index=99, score=90, reason="r", topic="AI")])
    assert bundle.max_score is None


def test_수집_항목이_없으면_LLM을_호출하지_않는다():
    """토큰을 쓰지 않는다."""
    llm = FakeLLM(responses=[])
    bundle = rank(
        items=[], interests="i", recent_headlines=[], weights={},
        llm=llm, window_start=WINDOW[0], window_end=WINDOW[1],
    )

    assert bundle.selected == []
    assert llm.prompts == []


def test_윈도우를_그대로_넘긴다():
    bundle, _ = _rank([_item(0)], [ScoreItem(index=0, score=70, reason="r", topic="AI")])
    assert bundle.window_start == WINDOW[0]
    assert bundle.window_end == WINDOW[1]


# --- 상한이 상위 순서를 망치지 않는다 ---
#
# 2026-11-12 실측에서 상위 6건이 전부 100점으로 묶였다. LLM 원점수는 잘
# 퍼져 있었는데(최고 92, 중앙값 30) 우리 가중치 상한이 납작하게 만들었고,
# 하필 상위 10건을 고르는 자리였다.

def test_상한_없는_가중_점수는_100을_넘는다():
    assert weighted_score(90, 1.3) == pytest.approx(117.0)


def test_표시_점수는_여전히_100에서_멈춘다():
    assert apply_weight(90, 1.3) == 100


def test_상한에_묶여도_순서가_유지된다():
    """실측 그대로: 원 90×1.3=117 과 원 85×1.2=102. 둘 다 100으로 표시되지만
    117이 먼저 와야 한다.
    """
    items = [_item(0, "낮은가중"), _item(1, "높은가중")]
    scores = [
        ScoreItem(index=0, score=85, reason="r", topic="AI"),   # ×1.2 = 102.0
        ScoreItem(index=1, score=90, reason="r", topic="AI"),   # ×1.3 = 117.0
    ]
    bundle, _ = _rank(items, scores, weights={"낮은가중": 1.2, "높은가중": 1.3})

    assert [r.score for r in bundle.selected] == [100, 100]     # 둘 다 상한
    assert bundle.selected[0].item.source == "높은가중"           # 순서는 살아 있다


def test_상한_넘는_항목이_TOP_N_경계에서_밀리지_않는다():
    """상한으로 정렬하면 100점 동점자 중 누가 잘리는지가 입력 순서로
    결정된다. 상한 없는 값으로 정렬해야 실제 우열이 반영된다.
    """
    # 11건 모두 가중 후 100을 넘긴다. 진짜 1등은 마지막에 넣는다.
    items = [_item(i, "높은가중") for i in range(TOP_N + 1)]
    scores = [ScoreItem(index=i, score=80, reason="보통", topic="AI")
              for i in range(TOP_N)]
    scores.append(ScoreItem(index=TOP_N, score=95, reason="최고", topic="AI"))

    bundle, _ = _rank(items, scores, weights={"높은가중": 1.3})

    assert len(bundle.selected) == TOP_N
    assert bundle.selected[0].reason == "최고"


def test_최고_점수는_상한_있는_값으로_기록한다():
    """0건인 날 화면이 "최고 117점 / 기준 60점"이면 안 된다."""
    bundle, _ = _rank([_item(0, "높은가중")],
                      [ScoreItem(index=0, score=90, reason="r", topic="AI")],
                      weights={"높은가중": 1.3})
    assert bundle.max_score == 100


# --- topic 계약 ---

def test_topic은_정해진_다섯_값만_받는다():
    """프롬프트에만 적어 두면 LLM 준수에 의존한다. 값이 흔들리면
    (AI / ai / 인공지능) 집계와 화면 분류가 조용히 깨진다.
    """
    with pytest.raises(ValidationError):
        ScoreItem(index=0, score=50, reason="r", topic="인공지능")


def test_topic이_스키마의_enum으로_나간다():
    """API가 생성 단계에서 막아 주려면 스키마에 enum이 있어야 한다."""
    schema = ScoreSheet.model_json_schema()
    topic = schema["$defs"]["ScoreItem"]["properties"]["topic"]

    assert set(topic["enum"]) == {"AI", "backend", "infra", "tooling", "other"}
```

- [x] **Step 2: 실패를 확인**

```bash
pytest tests/test_rank.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.rank'`

- [x] **Step 3: 최소 구현 작성**

`pipeline/rank.py`:

```python
"""02 선별: 수집 항목을 한 번의 LLM 호출로 채점하고 상위 N건을 고른다.

건당 호출하지 않는 이유는, 한 번에 넣어야 LLM이 "이 둘은 같은 사건이니
하나만" 같은 교차 판단을 할 수 있기 때문이다.

실행: python -m pipeline.rank
"""

from datetime import datetime, timezone

from pipeline.lib.config import load_interests, load_sources
from pipeline.lib.llm import LLM, AnthropicLLM, Effort, TruncatedError
from pipeline.lib.secrets import require
from pipeline.lib.store import LocalStore, SupabaseStore
from pipeline.lib.timeutil import KST
from pipeline.models import (
    RankedBundle,
    RankedItem,
    RawBundle,
    RawItem,
    ScoreItem,
    ScoreSheet,
)

# 본문을 가져올 건수. 03_enrich가 이 개수만 크롤링한다.
TOP_N = 10

# 같은 사건 중복 판정에 참고할 과거 범위.
DEDUP_LOOKBACK_DAYS = 14

# 채점은 깊은 추론이 필요 없다. 토큰을 아낀다.
RANK_EFFORT: Effort = "low"

# 발췌를 자르는 길이. 그 이상은 채점 정확도에 기여하지 않으면서 토큰만
# 늘린다(항목 수가 많으므로 누적이 크다).
EXCERPT_CHARS = 400

# --- 출력 토큰 산정 ---
#
# 2026-11-12 실측: 227건(96시간 윈도우의 현실적 상한)을 한 프롬프트에 넣으면
# 입력 42,135토큰이고, ScoreItem 한 건이 JSON으로 82토큰이라 출력은
# 18,614토큰이 필요하다. **래퍼의 기본값 16,000으로는 잘린다.**
#
# 잘리면 stop_reason=max_tokens로 오고, 재시도해도 똑같이 잘린다. 그래서
# 기본값에 맡기지 않고 항목 수에서 계산해 넘긴다.

# 실측 82토큰에 여유를 둔다. 이유 문장이 길어질 수 있다.
OUTPUT_TOKENS_PER_ITEM = 110

# Opus 5.5는 사고가 항상 켜져 있고(끌 수 없다), 사고 토큰도 max_tokens에
# 포함된다. effort=low라 많지는 않지만 0은 아니다.
THINKING_ALLOWANCE = 8_000

# 비스트리밍으로 안전하게 받을 수 있는 상한. 이보다 크게 받으려면 스트리밍이
# 필요하다. 지금 여유는 약 363건이고 실측 상한이 227건이라 한동안 버틴다
# (test_현실적_상한에_여유가_남아_있다가 지킨다).
MAX_OUTPUT_TOKENS = 48_000


def weighted_score(score: int, weight: float) -> float:
    """상한 없는 가중 점수. **정렬에만** 쓴다.

    왜 상한 없는 값이 따로 필요한가 — 2026-11-12 실측:
    상위권이 전부 100점으로 묶여 순서가 사라졌다.

        원 90 ×1.3 = 117.0 → 100
        원 85 ×1.3 = 110.5 → 100
        원 88 ×1.2 = 105.6 → 100
        원 85 ×1.2 = 102.0 → 100

    LLM 원점수는 잘 퍼져 있었다(최고 92, 중앙값 30). **100점 쏠림은
    우리 상한이 만든 것**이고, 하필 상위 10건을 고르는 자리에서 생겼다.
    정렬은 상한 없는 값으로, 표시·저장은 상한 있는 값으로 한다.
    """
    return score * weight


def apply_weight(score: int, weight: float) -> int:
    """표시·저장용 가중 점수. 상한 100.

    `score`의 계약이 0~100이고 DB 제약도 같다. 120점을 보여 줄 수는 없다.
    """
    return min(100, round(score * weight))


def rank_max_tokens(item_count: int) -> int:
    """항목 수에 맞춘 출력 상한."""
    return min(
        MAX_OUTPUT_TOKENS,
        THINKING_ALLOWANCE + item_count * OUTPUT_TOKENS_PER_ITEM,
    )


def max_items_per_call() -> int:
    """한 번에 채점할 수 있는 항목 수의 상한."""
    return (MAX_OUTPUT_TOKENS - THINKING_ALLOWANCE) // OUTPUT_TOKENS_PER_ITEM


def build_prompt(
    *,
    interests: str,
    recent_headlines: list[str],
    items: list[RawItem],
) -> str:
    """채점 프롬프트를 조립한다."""
    lines = [
        "당신은 아래 '관심사 프로필'을 가진 사람의 큐레이터다.",
        "각 글을 0~100점으로 채점하고, 점수를 준 이유를 한 문장으로 쓴다.",
        "topic은 AI / backend / infra / tooling / other 중 하나로 분류한다.",
        "",
        # 빠뜨린 항목은 순위에 들어올 수 없다 — 조용히 버려진다. 그래서
        # 건수를 명시해 전부 채점하라고 말한다.
        f"글이 {len(items)}개 있다. **{len(items)}개 전부에 점수를 매긴다.** "
        f"낮은 점수를 줄 글도 빠뜨리지 않는다.",
        "",
        "## 관심사 프로필",
        "",
        interests,
    ]

    if recent_headlines:
        lines += [
            "",
            f"## 최근 발행한 헤드라인 (최근 {DEDUP_LOOKBACK_DAYS}일)",
            "",
            "아래와 같은 사건·주제를 다룬 글은 40점 이하로 내린다.",
            "단, 명시적인 후속편은 중복이 아니다.",
            "",
        ]
        lines += [f"- {headline}" for headline in recent_headlines]

    lines += [
        "",
        "## 채점할 글",
        "",
        "각 글은 [번호]로 참조한다. 응답의 index에 그 번호를 쓴다.",
        "",
    ]
    for index, item in enumerate(items):
        lines += [
            f"[{index}] ({item.source}) {item.title}",
            f"      {item.excerpt[:EXCERPT_CHARS]}",
            "",
        ]

    return "\n".join(lines)


def rank(
    *,
    items: list[RawItem],
    interests: str,
    recent_headlines: list[str],
    weights: dict[str, float],
    llm: LLM,
    window_start: str,
    window_end: str,
) -> RankedBundle:
    """채점하고 상위 TOP_N건을 고른다."""
    if not items:
        # 수집이 0건이면 호출할 이유가 없다. 토큰을 쓰지 않는다.
        return RankedBundle(
            window_start=window_start,
            window_end=window_end,
            selected=[],
            all_scores=[],
        )

    # 호출 전에 막는다. 보내 놓고 잘리면 토큰을 쓰고도 결과가 없다.
    한계 = max_items_per_call()
    if len(items) > 한계:
        raise TruncatedError(
            f"항목이 {len(items)}건인데 한 번에 채점할 수 있는 상한은 {한계}건이다. "
            f"보내면 출력이 max_tokens에 걸려 잘리고, 재시도해도 같다. "
            f"소스를 줄이거나, 여러 번에 나눠 채점하도록 고치거나, "
            f"스트리밍을 도입해 MAX_OUTPUT_TOKENS를 올린다."
        )

    prompt = build_prompt(
        interests=interests, recent_headlines=recent_headlines, items=items
    )

    # 재시도는 llm.parse 안에서 끝난다 — 전송 계층은 SDK가, 스키마 실패는
    # 래퍼가 1회 담당한다. 여기서 또 감싸면 이중 재시도가 된다.
    sheet, _tokens = llm.parse(
        prompt=prompt,
        output_format=ScoreSheet,
        effort=RANK_EFFORT,
        max_tokens=rank_max_tokens(len(items)),
    )

    # (정렬 기준, 항목) 쌍으로 모은다. 정렬 기준은 상한 없는 값이고
    # 항목에 담기는 점수는 상한 있는 값이다 — weighted_score의 설명 참조.
    scored: list[tuple[float, RankedItem]] = []
    seen_indexes: set[int] = set()
    kept_scores: list[ScoreItem] = []

    for score in sheet.scores:
        # LLM이 범위 밖 번호나 중복 번호를 돌려줄 수 있다. 둘 다 무시한다.
        # (음수는 ScoreItem의 ge=0이 계약 경계에서 막는다.)
        if not (0 <= score.index < len(items)) or score.index in seen_indexes:
            continue
        seen_indexes.add(score.index)

        item = items[score.index]
        weight = weights.get(item.source, 1.0)

        kept_scores.append(score)
        scored.append((
            weighted_score(score.score, weight),
            RankedItem(
                item=item,
                score=apply_weight(score.score, weight),
                reason=score.reason,
                topic=score.topic,
            ),
        ))

    # 상한 없는 값으로 정렬한다. 상한 있는 값으로 정렬하면 100에 묶인
    # 항목들의 순서가 입력 순서로 결정돼 버린다.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = [item for _, item in scored]

    return RankedBundle(
        window_start=window_start,
        window_end=window_end,
        selected=ranked[:TOP_N],
        all_scores=kept_scores,
        # 정렬했으므로 첫 항목이 최고 점수다. 0건이면 None으로 둔다 —
        # 0으로 두면 "최고 0점"과 "수집 없음"이 구분되지 않는다.
        # 상한 있는 값을 쓴다 — 0건인 날 화면이 "최고 117점"이면 안 된다.
        max_score=ranked[0].score if ranked else None,
    )


def main() -> None:
    date = datetime.now(timezone.utc).astimezone(KST).date().isoformat()
    store = LocalStore(date=date)
    raw = store.read("raw", RawBundle)

    remote = SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SECRET_KEY"))
    weights = {source.name: source.weight for source in load_sources()}

    bundle = rank(
        items=raw.items,
        interests=load_interests(),
        recent_headlines=remote.recent_headlines(days=DEDUP_LOOKBACK_DAYS),
        weights=weights,
        llm=AnthropicLLM(require("ANTHROPIC_API_KEY")),
        window_start=raw.window_start,
        window_end=raw.window_end,
    )

    path = store.write("ranked", bundle)

    # 수집과 채점 건수를 함께 낸다. LLM이 일부를 빼먹으면 그 항목은 순위에
    # 들어올 수 없는데, 한쪽만 보면 누락이 드러나지 않는다.
    누락 = len(raw.items) - len(bundle.all_scores)
    print(f"수집 {len(raw.items)}건 → 채점 {len(bundle.all_scores)}건"
          f"{f' (누락 {누락}건)' if 누락 else ''} → 선별 {len(bundle.selected)}건")
    print(f"  → {path}")
    if 누락:
        print(f"  [주의] {누락}건이 채점되지 않았다. 프롬프트가 전부 채점하라고 "
              f"말하는데도 빠졌다면 항목 수를 줄이는 것을 검토한다.")
    print()
    for item in bundle.selected:
        print(f"  {item.score:3d}  [{item.topic}] {item.item.title[:50]}")
        print(f"       {item.reason[:70]}")


if __name__ == "__main__":
    main()
```

> **설명** — `enumerate(items)`는 `(0, 첫항목), (1, 둘째항목), ...`을 돌려줘서
> 번호와 값을 함께 쓸 수 있다. `list.sort(key=..., reverse=True)`는 리스트를
> 제자리에서 정렬하며 `key`로 비교 기준을 지정한다. 여기서는 `(정렬기준, 항목)`
> 튜플을 모아 `key=lambda pair: pair[0]`로 정렬하는데, **튜플째로 정렬하면
> 안 된다** — 첫 값이 같을 때 두 번째 원소(`RankedItem`)를 비교하려 하고
> pydantic 모델에는 `<` 연산이 없어 `TypeError`가 난다.
>
> `weights.get(name, 1.0)`은 소스가 가중치 표에 없으면 1.0을 쓴다 — 설정이
> 빠져도 죽지 않게 한다.
>
> `llm.parse`를 재시도로 감싸지 않는 것이 의도적이다. 전송 계층 재시도는
> anthropic SDK가 하고(`max_retries`), 스키마 실패 재시도는 `llm.parse`
> 안에서 한다. 여기서 한 겹 더 두르면 한 번의 논리적 호출이 여러 배로 늘어난다.

- [x] **Step 4: 통과를 확인**

```bash
pytest tests/test_rank.py
```

Expected: `43 passed`. 전체 `238 passed`.

- [x] **Step 5: 실제 240건으로 채점**

```bash
python -m pipeline.rank
```

**실측 (2026-11-12): 240건 수집 → 240건 채점 → 10건 선별, 65초, 누락 0.**

선별된 10건:

```
100  [AI] 실행은 격리하고, 세션은 이어간다: 망분리 환경의 Agent Platform 설계기
100  [AI] 검수도 답변도 호출도 AI가? 커머스API의 2026
100  [tooling] AI 스킬 만들기 10계명: Figma→Code 자동화 실전기
100  [AI] Amazon saves millions by replacing Sonnet 4.6 with ...
100  [AI] How we rebuilt the Shopify app in 12 weeks
 98  [backend] Choosing QuePaxa, an unusual consensus algorithm
 98  [AI] Long-horizon agents and durable execution
 98  [backend] 비가 오면 사장님이 먼저 압니다: SSE로 만든 실시간 기상악화 알림
 98  [AI] 딸깍으로 안되는 Multi-interest 개발기
 96  [AI] Fact-Checking at Scale: Building a More Accurate ...
```

**관심사 프로필이 작동하고 있다.** 같은 윈도우에 들어온 "3분기 매출",
"ESG 등급", "코스피 마감"은 2~5점으로 깔렸고, 올라온 것은 전부 실전
기록·원리 분석이다. 점수 분포도 한쪽으로 쏠리지 않았다:

```
90~99 ███ 3          40~49 ████████████████████████████ 28
80~89 █████████ 9    30~39 ████████████████████████████ 28
70~79 █████████████████████ 21   20~29 ███████████████████████████████████ 35
60~69 ████████████████ 16        10~19 ██████████████████████ 22
50~59 █████████████████ 17        0~ 9 █████████████████████████████████████████████████████████████ 61
```

- [x] **Step 6: 커밋**

```bash
git add pipeline/rank.py tests/test_rank.py pipeline/lib/llm.py pipeline/models.py
git commit -m "feat: 선별 단계 — 일괄 채점, 소스 가중치, 잘못된 index 방어"
```

---

## Task 17: 선별 품질 평가 도구

운영에 포함되지 않는다. 시드 데이터로 프롬프트를 고치며 결과를 비교하는 도구다.

**Files:**
- Create: `pipeline/evaluate.py`
- Create: `tests/test_evaluate.py`

> **계획에서 고친 것** (테스트 6개 → 23개)
>
> ### 1. 균등 무작위 표본이 쓸 수 없는 것이었다 — Task 14에서 남긴 메모 그대로
>
> 계획의 `sample_items`는 `random.Random(seed).sample(items, limit)`이다.
> 시드에 실제로 적용해 보니:
>
> | | 소스 수 | 최다 소스 |
> |---|---:|---|
> | 균등 무작위 40건 | **14개** | OpenAI_Blog **18건(45%)** |
> | | | Hugging_Face_Blog 7건(17.5%) |
>
> **두 소스가 표본의 62.5%**를 차지하고 45개 소스 중 14개만 덮었다.
> 시드는 400일치라 발행이 잦은 소스가 누적으로 쌓인다(OpenAI 680건, 전체의 35%).
>
> 그런데 **실제 운영에서 OpenAI는 240건 중 11건(4.6%)**이다. 이 표본으로
> 프로필을 튜닝하면 **OpenAI 공지문에 맞춰 기준을 깎게 된다** — 정작 매일
> 들어오는 국내 기술블로그와 매체 칼럼은 표본에 거의 없다.
>
> **소스별 상한(`PER_SOURCE_CAP = 3`)을 넣었다.** 소스마다 상한까지만 뽑아
> 풀을 만들고 거기서 표본을 뽑는다. 결과:
>
> | | 소스 수 | 최다 소스 |
> |---|---:|---|
> | 소스별 상한 40건 | **31개** | 3건 **(8%)** |
>
> 상한을 1로 하지 않은 이유는, 1건이면 **그 소스의 품질 분포**를 볼 수
> 없어서다(좋은 글과 홍보글이 섞여 오는 소스가 많다).
>
> ### 2. 점수 분포를 출력하지 않았다
>
> 계획 Step 6이 "점수가 60~80에 몰려 있는가"를 확인하라고 하는데, 그걸
> 보여 주지 않아 매번 손으로 세야 했다(Task 16에서 실제로 그랬다).
> `format_distribution`을 넣었다. 쏠림은 프로필 기준이 모호하다는 신호이고
> **튜닝의 주요 입력**이다.
>
> ### 3. 한글 소스명 때문에 표가 어긋났다
>
> 터미널에서 한글은 두 칸인데 `len()`은 1로 센다. `{'점수':>4}`는 폭 4가
> 아니라 `"  점수"`(폭 6)를 만들고, `토스_기술블로그`(폭 16)와
> `Cloudflare_Blog`(폭 15)가 같은 열에서 밀린다. **표로 읽는 게 이 도구의
> 목적**이라 `display_width`·`pad`를 만들어 맞췄다.

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_evaluate.py`:

```python
from collections import Counter

from pipeline.evaluate import (
    DEFAULT_LIMIT,
    PER_SOURCE_CAP,
    display_width,
    format_distribution,
    format_table,
    pad,
    sample_items,
)
from pipeline.models import RankedItem, RawItem, ScoreItem


def _raw(index: int, source: str = "s") -> RawItem:
    return RawItem(
        source=source,
        title=f"t{index}",
        url=f"https://e.com/{index}",
        published="2026-11-10T05:30:00+00:00",
        excerpt="e",
    )


def _ranked(score: int, title: str, source: str = "s") -> RankedItem:
    return RankedItem(
        item=RawItem(
            source=source, title=title, url=f"https://e.com/{score}",
            published="2026-11-10T05:30:00+00:00", excerpt="e",
        ),
        score=score,
        reason="이유",
        topic="AI",
    )


# --- 표본 추출 ---

def test_표본_추출이_요청한_개수를_넘지_않는다():
    items = [_raw(i, f"소스{i % 20}") for i in range(100)]
    assert len(sample_items(items, limit=30)) == 30


def test_항목이_요청보다_적으면_전부_돌려준다():
    assert len(sample_items([_raw(1)], limit=30)) == 1


def test_표본_추출이_재현_가능하다():
    """프롬프트 변경 효과만 비교하려면 입력이 고정돼야 한다."""
    items = [_raw(i, f"소스{i % 20}") for i in range(100)]
    assert sample_items(items, limit=20) == sample_items(items, limit=20)


def test_전역_난수_상태를_건드리지_않는다():
    """random.sample을 직접 쓰면 다른 코드의 재현성에 영향을 준다."""
    import random

    items = [_raw(i, f"소스{i % 20}") for i in range(100)]
    random.seed(1)
    먼저 = random.random()
    random.seed(1)
    sample_items(items, limit=10)
    나중 = random.random()

    assert 먼저 == 나중


def test_한_소스가_표본을_독식하지_못한다():
    """**이 태스크의 핵심.** 2026-11-12 실측: 시드 1923건을 균등 무작위로
    40건 뽑으면 OpenAI_Blog가 18건(45%), Hugging_Face_Blog가 7건(17.5%)으로
    **두 소스가 62.5%**를 차지하고 소스 45개 중 14개만 덮었다.

    시드는 400일치라 발행이 잦은 소스가 누적으로 쌓인다(OpenAI 680건).
    실제 운영에서 OpenAI는 240건 중 11건(4.6%)이다. 쏠린 표본으로
    프로필을 튜닝하면 **OpenAI 공지문에 맞춰 기준을 깎게 된다.**
    """
    items = ([_raw(i, "독식소스") for i in range(500)]
             + [_raw(500 + i, f"소스{i}") for i in range(40)])

    표본 = sample_items(items, limit=40)
    집계 = Counter(i.source for i in 표본)

    assert 집계["독식소스"] <= PER_SOURCE_CAP


def test_소스별_상한이_적용된다():
    items = [_raw(i, "한소스") for i in range(100)]
    표본 = sample_items(items, limit=40)

    # 소스가 하나뿐이면 상한만큼만 나온다 — 40건을 채우려고 상한을 깨지 않는다
    assert len(표본) == PER_SOURCE_CAP


def test_여러_소스를_골고루_덮는다():
    """넓게 보려고 쓰는 도구다. 소스 수가 표본 수에 가까워야 한다."""
    items = [_raw(i, f"소스{i % 45}") for i in range(900)]
    표본 = sample_items(items, limit=40)

    assert len({i.source for i in 표본}) >= 20


def test_상한이_1보다_크다():
    """소스당 1건이면 그 소스의 글 품질 분포를 볼 수 없다."""
    assert PER_SOURCE_CAP >= 2


# --- 한글 폭 정렬 ---
#
# 터미널에서 한글은 두 칸을 차지하는데 len()은 1로 센다. 그대로 두면
# 소스 열이 들쭉날쭉해서 표를 읽는 목적이 깨진다.

def test_한글은_두_칸으로_센다():
    assert display_width("토스") == 4


def test_영문은_한_칸으로_센다():
    assert display_width("toss") == 4


def test_섞여_있어도_합이_맞는다():
    assert display_width("토스tech") == 8


def test_폭을_맞춰_채운다():
    assert display_width(pad("토스", 10)) == 10
    assert display_width(pad("Cloudflare", 10)) == 10


def test_폭을_넘으면_자른다():
    assert display_width(pad("토스_기술블로그입니다", 10)) <= 10


# --- 표 ---

def test_표에_점수와_제목과_소스가_들어간다():
    table = format_table([_ranked(90, "좋은 글", "토스_기술블로그")])

    assert "90" in table
    assert "좋은 글" in table
    assert "토스_기술블로그" in table


def test_표에_판단_이유가_들어간다():
    """'왜 이게 뽑혔나'를 보는 게 이 도구의 목적이다."""
    table = format_table([_ranked(90, "글")])
    assert "이유" in table


def test_빈_목록도_표가_된다():
    assert isinstance(format_table([]), str)


def test_표의_소스_열이_정렬된다():
    """한글 소스와 영문 소스가 섞여도 제목이 같은 칸에서 시작해야 한다."""
    table = format_table([
        _ranked(90, "제목A", "토스_기술블로그"),
        _ranked(80, "제목B", "Cloudflare_Blog"),
    ])
    본문 = [l for l in table.splitlines() if "제목" in l]

    시작 = [display_width(l[:l.index("제목")]) for l in 본문]
    assert len(set(시작)) == 1, f"제목 시작 위치가 어긋났다: {시작}"


# --- 점수 분포 ---
#
# 계획 Step 6이 "점수가 60~80에 몰려 있는가"를 확인하라고 하는데, 분포를
# 출력하지 않으면 매번 손으로 세야 한다. 튜닝의 주요 신호다.

def test_분포에_모든_구간이_나온다():
    scores = [ScoreItem(index=i, score=s, reason="r", topic="AI")
              for i, s in enumerate([5, 15, 95])]
    out = format_distribution(scores)

    assert "0~9" in out and "10~19" in out and "90~99" in out


def test_분포에_건수가_나온다():
    scores = [ScoreItem(index=i, score=50, reason="r", topic="AI") for i in range(7)]
    assert "7" in format_distribution(scores)


def test_분포에_중앙값과_최고가_나온다():
    """쏠림을 한눈에 보려면 요약 수치가 필요하다."""
    scores = [ScoreItem(index=i, score=s, reason="r", topic="AI")
              for i, s in enumerate([10, 50, 92])]
    out = format_distribution(scores)

    assert "92" in out and "50" in out


def test_100점도_구간에_들어간다():
    """(score // 10) * 10이면 100이 별도 구간이 된다."""
    scores = [ScoreItem(index=0, score=100, reason="r", topic="AI")]
    out = format_distribution(scores)

    assert "90~100" in out or "90~99" in out
    assert "100~109" not in out


def test_점수가_없으면_분포도_문자열이다():
    assert isinstance(format_distribution([]), str)


def test_기본_표본_크기가_상한_안에_있다():
    """rank가 363건을 넘으면 거부한다. 기본값이 그 안이어야 한다."""
    from pipeline.rank import max_items_per_call

    assert DEFAULT_LIMIT <= max_items_per_call()
```

- [x] **Step 2: 실패를 확인**

```bash
pytest tests/test_evaluate.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.evaluate'`

- [x] **Step 3: 최소 구현 작성**

`pipeline/evaluate.py`:

```python
"""선별 품질 평가 (개발 도구, 운영 비포함).

시드 데이터로 채점을 돌려 결과를 표로 본다. config/interests.md나
pipeline/rank.py의 프롬프트를 고친 뒤 다시 돌려 비교하는 것이 튜닝 작업이다.

실행:
  python -m pipeline.evaluate                     # 시드에서 40건 표본
  python -m pipeline.evaluate --limit 80          # 표본 크기 변경
  python -m pipeline.evaluate --date 2026-11-12   # 특정 날짜 데이터로
"""

import argparse
import random
import statistics
import unicodedata
from collections import Counter, defaultdict

from pipeline.lib.config import load_interests, load_sources
from pipeline.lib.llm import AnthropicLLM
from pipeline.lib.secrets import require
from pipeline.lib.store import LocalStore
from pipeline.models import RankedItem, RawBundle, RawItem, ScoreItem
from pipeline.rank import rank
from pipeline.seed import SEED_DIR

# 고정 시드. 표본이 매번 달라지면 프롬프트 변경 효과를 분리할 수 없다.
SAMPLE_SEED = 20261110
DEFAULT_LIMIT = 40

# 한 소스가 표본에서 차지할 수 있는 최대 건수.
#
# 2026-11-12 실측: 시드 1923건을 균등 무작위로 40건 뽑으면 OpenAI_Blog가
# 18건(45%), Hugging_Face_Blog가 7건(17.5%)으로 **두 소스가 62.5%**를
# 차지하고 소스 45개 중 14개만 덮었다. 시드는 400일치라 발행이 잦은 소스가
# 누적으로 쌓인다(OpenAI 680건).
#
# 실제 운영에서 OpenAI는 240건 중 11건(4.6%)이다. 쏠린 표본으로 프로필을
# 튜닝하면 **OpenAI 공지문에 맞춰 기준을 깎게 된다.** 1이면 그 소스의
# 품질 분포를 볼 수 없으니 3으로 둔다.
PER_SOURCE_CAP = 3


def display_width(text: str) -> int:
    """터미널에서 차지하는 칸 수.

    한글·한자·일문은 두 칸을 차지하는데 `len()`은 1로 센다. 그대로 두면
    소스 열이 들쭉날쭉해서 표를 읽는 목적이 깨진다.
    """
    return sum(
        2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        for ch in text
    )


def pad(text: str, width: int) -> str:
    """표시 폭 기준으로 잘라 내고 공백을 채운다."""
    kept: list[str] = []
    used = 0
    for ch in text:
        step = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + step > width:
            break
        kept.append(ch)
        used += step
    return "".join(kept) + " " * (width - used)


def sample_items(items: list[RawItem], *, limit: int = DEFAULT_LIMIT) -> list[RawItem]:
    """재현 가능한 표본을 뽑는다. 한 소스가 독식하지 못하게 상한을 둔다."""
    # Random(seed)는 전역 난수 상태를 건드리지 않는 독립 생성기를 만든다.
    # random.sample을 직접 쓰면 다른 코드의 재현성에 영향을 준다.
    rng = random.Random(SAMPLE_SEED)

    소스별: dict[str, list[RawItem]] = defaultdict(list)
    for item in items:
        소스별[item.source].append(item)

    # 소스마다 상한까지만 남긴다. 소스 순서를 정렬해 두는 이유는 dict의
    # 삽입 순서가 입력에 따라 달라져 재현성이 흔들리기 때문이다.
    풀: list[RawItem] = []
    for 소스 in sorted(소스별):
        후보 = 소스별[소스]
        if len(후보) <= PER_SOURCE_CAP:
            풀.extend(후보)
        else:
            풀.extend(rng.sample(후보, PER_SOURCE_CAP))

    if len(풀) <= limit:
        return 풀
    return rng.sample(풀, limit)


def format_table(selected: list[RankedItem]) -> str:
    """선별 결과를 읽기 좋은 표로 만든다."""
    if not selected:
        return "(선별된 항목이 없다)"

    # 머리글도 pad로 맞춘다. f-string의 `{'점수':>4}`는 len() 기준이라
    # 한글 2자를 폭 4로 보지 않고 "  점수"(폭 6)를 만들어 데이터 행과 어긋난다.
    lines = [
        f"{pad('점수', 4)}  {pad('주제', 8)}  {pad('소스', 24)}  제목",
        "-" * 100,
    ]
    for item in selected:
        lines.append(
            f"{item.score:>4}  {pad(item.topic, 8)}  "
            f"{pad(item.item.source, 24)}  {item.item.title[:44]}"
        )
        lines.append(f"      └ {item.reason[:90]}")

    return "\n".join(lines)


def format_distribution(scores: list[ScoreItem]) -> str:
    """점수 분포. 쏠림이 보이면 프로필 기준이 모호하다는 뜻이다."""
    if not scores:
        return "(채점된 항목이 없다)"

    values = [s.score for s in scores]
    # 100점은 90 구간에 넣는다. (score // 10) * 10이면 100이 따로 떨어져
    # 구간이 하나 늘어난다.
    구간 = Counter(min(90, (v // 10) * 10) for v in values)

    최대 = max(구간.values())
    lines = []
    for 하한 in range(90, -1, -10):
        n = 구간.get(하한, 0)
        막대 = "█" * round(n / 최대 * 40) if n else ""
        # 상한 쪽은 자리를 채우지 않는다. 채우면 "90~ 99"가 되어 grep도,
        # 눈으로 읽기도 불편하다.
        lines.append(f"  {하한:3d}~{하한 + 9}  {n:4d}  {막대}")

    lines.append(
        f"  최고 {max(values)} · 최저 {min(values)} · "
        f"중앙값 {int(statistics.median(values))} · 평균 {statistics.mean(values):.1f}"
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="선별 품질 평가")
    parser.add_argument("--date", default=SEED_DIR,
                        help=f"데이터 디렉터리 (기본: {SEED_DIR})")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"표본 크기 (기본: {DEFAULT_LIMIT})")
    args = parser.parse_args()

    raw = LocalStore(date=args.date).read("raw", RawBundle)
    items = sample_items(raw.items, limit=args.limit)

    print(f"데이터: {args.date}  전체 {len(raw.items)}건 중 표본 {len(items)}건")
    집계 = Counter(item.source for item in items)
    print(f"  소스 {len(집계)}개 · 한 소스 최대 {max(집계.values())}건 "
          f"(상한 {PER_SOURCE_CAP})")
    print()

    bundle = rank(
        items=items,
        interests=load_interests(),
        recent_headlines=[],   # 평가에서는 중복 판정을 끈다
        weights={source.name: source.weight for source in load_sources()},
        llm=AnthropicLLM(require("ANTHROPIC_API_KEY")),
        window_start=raw.window_start,
        window_end=raw.window_end,
    )

    print("점수 분포 (가중치 적용 전)")
    print(format_distribution(bundle.all_scores))
    print()

    print(f"상위 {len(bundle.selected)}건")
    print(format_table(bundle.selected))
    print()

    # 하위권도 봐야 한다 — "왜 이게 떨어졌나"가 프롬프트 수정의 단서다.
    lowest = sorted(bundle.all_scores, key=lambda s: s.score)[:10]
    print("최하위 10건 (탈락 이유 확인용)")
    print("-" * 100)
    for score in lowest:
        item = items[score.index]
        print(f"{score.score:>4}  {pad(item.source, 24)}  {item.title[:44]}")
        print(f"      └ {score.reason[:90]}")


if __name__ == "__main__":
    main()
```

> **설명** — `argparse`는 명령행 인자를 파싱하는 표준 라이브러리다.
> `--limit 80`처럼 받은 값을 `args.limit`으로 쓴다.
>
> `random.Random(seed)`로 생성기를 따로 만드는 이유는, `random.sample`을
> 직접 쓰면 **전역 난수 상태를 바꿔** 다른 코드의 재현성에 영향을 주기
> 때문이다(`test_전역_난수_상태를_건드리지_않는다`가 지킨다).
>
> `for 소스 in sorted(소스별)`에서 정렬하는 이유 — dict의 삽입 순서는 입력
> 순서를 따르므로, 수집 순서가 조금 달라지면 표본이 바뀐다. 정렬하면
> **프롬프트 변경 효과만** 비교된다.
>
> `unicodedata.east_asian_width(ch)`는 문자의 동아시아 폭 분류를 돌려준다.
> `"W"`(Wide)·`"F"`(Fullwidth)가 두 칸을 차지한다.

- [x] **Step 4: 통과를 확인**

```bash
pytest tests/test_evaluate.py
```

Expected: `23 passed`. 전체 `261 passed`.

- [x] **Step 5: 실제 시드 데이터로 선별을 돌려본다**

```bash
python -m pipeline.evaluate --limit 40
```

**실측 (2026-11-12):** 시드 1923건 → 표본 40건, 소스 31개.

점수 분포 (가중치 적용 전):

```
 90~99     1  █████
 80~89     7  ███████████████████████████████████
 70~79     3  ███████████████
 60~69     6  ██████████████████████████████
 50~59     8  ████████████████████████████████████████
 40~49     3  ███████████████
 30~39     3  ███████████████
 20~29     1  █████
 10~19     4  ████████████████████
  0~9      4  ████████████████████
최고 90 · 최저 2 · 중앙값 55 · 평균 50.5
```

상위 5건:

```
100  AI       인프런_기술블로그    사내 LLM 요청을 한곳으로 모은 AI Gateway 구축기
100  AI       Slack_Engineering    Slack AI: The Path to Multi-Cloud
100  AI       Airbnb_Engineering   Eval-driven development: Lessons from ...
100  backend  카카오_기술블로그    문자를 보냈다는데 왜 안 오죠? 길 잃은 국제 MO 메시지 구출 작전
100  tooling  토스_기술블로그      머릿속에 있던 로그 정의 기준을 모두의 AI 스킬로 만들기
```

최하위 5건 — **탈락 이유가 전부 정확하다**:

```
 2  Discord_Engineering   During October, Treat a Friend to Nitro ...
    └ Nitro 프로모션 마케팅 글이다.
 3  전자신문_칼럼         [이시형의 잘 쉬는 법]②붓을 들면 고요해지는 머리...
    └ 휴식·문인화 칼럼으로 관심사와 무관하다.
 8  바이라인네트워크      [RE: 자사몰] 브랜드가 '구매 결정'을 설계하는 곳
    └ 자사몰 마케팅 성격 기사다.
10  전자신문_사설         [사설] AI해킹, 한차원 높인 방어력 갖춰야
    └ AI 해킹 대응 사설로 기술 내용이 없다.
15  OpenAI_Blog           Commonwealth Bank of Australia builds AI flu...
    └ ChatGPT Enterprise 도입 보도자료 성격이다.
```

`interests.md`의 "낮게 평가" 항목(보도자료 재가공, 제품 마케팅, 내용 없는
동향 기사)이 **문구 그대로 작동한다.**

> **주의 — 이 분포로 `SCORE_THRESHOLD`를 정하면 안 된다.**
>
> 평가 표본의 중앙값은 55인데 **실제 하루(240건)의 중앙값은 30**이었다.
> 당연하다 — 소스별 상한이 "실적 기사가 하루 30건 들어오는 소스"의 비중을
> 깎기 때문이다. 평가 표본은 **소스 넓이**를 대표하고, 실제 수집은
> **물량**을 대표한다.
>
> 그래서 용도를 나눈다:
> - "프로필이 잘 줄 세우나" → `--date _seed` (넓이)
> - "임계값 60에서 몇 건이 통과하나" → `--date <오늘>` (물량)

- [x] **Step 6: 관심사 프로필을 튜닝한다 (반복)** — **1차 판단 완료: 수정 없음**

출력을 보면서 다음을 확인한다.

- 상위권에 **보도자료 재가공 기사나 마케팅 글**이 있는가 → `config/interests.md`의 "낮게 평가" 항목에 그 패턴을 구체적으로 추가한다
- 하위권에 **읽고 싶은 글**이 있는가 → "높게 평가" 항목에 그 특징을 추가한다
- 점수가 60~80에 몰려 있는가 → 프로필의 기준이 모호하다는 뜻이다. 구체적인 예시를 늘린다

고친 뒤 다시 돌린다. **입력 표본이 고정이므로 프롬프트 변경 효과만 비교된다.**

> **이 단계는 사용자의 판단이 필요하다.** "읽고 싶다"는 프로필 주인의
> 취향이고, 내가 대신 판정하면 내 취향으로 프로필을 깎는 것이 된다.
> 1차 출력을 보여 주고 판단을 받는다.

> **2026-11-12 판단: 상위 10건 그대로 통과.** `interests.md`를 고치지 않았다.
> 첫 실행에서 바로 통과한 이유는 Task 11에서 프로필을 쓸 때 "보도자료
> 재가공", "제품 마케팅", "내용 없는 동향 기사"를 **구체적인 예시와 함께**
> 적어 둔 덕이다. 추상적인 단어만 적었다면 여러 번 돌려야 했을 것이다.
>
> 다음에 다시 돌릴 때 볼 것: `전자신문_사설`이 최하위 10건에 2건 들어
> 있었다("기술 내용이 없다"). 한 번의 표본으로 소스를 끄기에는 근거가
> 얇으니 몇 번 더 관찰한다.

- [x] **Step 7: 커밋** (도구만. 프로필 튜닝은 Step 6 판단 후)

```bash
git add pipeline/evaluate.py tests/test_evaluate.py
git commit -m "feat: 선별 품질 평가 도구 — 소스별 상한 표본, 점수 분포, 한글 폭 정렬"
```

---

## Task 18: 본문 확보

외부 크롤링은 구조적으로 가장 자주 깨지는 단계이면서, 폴백이 존재하는 유일한
단계다. **절대 중단하지 않는다.**

분류가 여기서 실질적인 차이를 만든다 — **403(봇 차단)에 재시도를 걸면 10건이면
수십 초를 버린다.** 영구 실패는 즉시 발췌로 내려간다.

**Files:**
- Create: `pipeline/enrich.py`
- Create: `tests/fixtures/article.html`
- Create: `tests/test_enrich.py`

> **계획에서 고친 것** (테스트 15개 → 25개)
>
> ### trafilatura는 `None`을 잘 주지 않는다
>
> 계획의 테스트 두 개가 통과할 수 없었다:
>
> ```python
> assert extract_body(b"<html><body><nav>메뉴</nav></body></html>") is None
> ```
>
> 실제로 확인해 보니 **`'메뉴'`를 돌려준다.** 그대로 본문으로 쓰면 브리핑에
> "메뉴"가 실린다. `BODY_MIN_CHARS = 200`을 넣어 그보다 짧은 추출은 본문으로
> 보지 않는다. 200자로 정한 근거는 **RSS 발췌가 중앙값 250자**(Task 13 실측)
> 라서다 — 그보다 한참 짧은 추출은 발췌가 낫다.
>
> 같은 이유로 계획의 fixture도 고쳤다. 본문이 약 220자여서 하한에 간신히
> 걸렸다 — 하한을 조금만 올리면 `test_본문을_추출한다`가 깨지는 상태였다.
> 문단을 늘려 491자로 만들었다.
>
> ### 발췌 폴백에도 상한을 적용했다
>
> 계획은 `body[:BODY_MAX_CHARS]`를 두 경로에 공통으로 적용하므로 이미
> 맞지만, **왜 필요한지가 적혀 있지 않았다.** 실측에서 Netflix 발췌가
> 15,633자였다. 피드에 전문을 담는 소스가 있어서 폴백 쪽을 자르지 않으면
> 요약 토큰이 튄다. 테스트로 못 박았다.

**실측 (2026-11-12, 실제 상위 10건): 본문 확보 6건, 폴백 4건, 21초.**

| 소스 | 결과 | 본문/발췌 |
|---|---|---|
| 토스_기술블로그 | 본문 | 8,147자 (발췌는 39자) |
| Hacker_News_Best | 본문 | 5,254자 |
| Shopify_Engineering | 본문 | 18,799자 |
| Cloudflare_Blog | 본문 | 25,384자 |
| Martin_Fowler | 본문 | 37,908자 |
| 우아한형제들 | 본문 | 12,229자 |
| 네이버_D2 × 3 | **추출 0자** | 발췌 975 / 14,790 / 1,015자 |
| Netflix_Tech_Blog | **403** | 발췌 15,633자 |

> **폴백이 품질 저하가 아니었다 — 반비례 관계가 있다.**
>
> 크롤링이 막히거나 JS로 그리는 소스가 **피드에 본문을 길게 담는다**:
> Netflix 15,633자, 네이버 D2 14,790자가 사실상 전문이다. 반대로 본문 추출이
> 성공한 소스의 발췌는 39~673자로 짧다. 즉 두 경로가 서로를 메운다.
>
> 남은 두 건(D2 975자·1,015자)은 **발표 영상 페이지**였다. "NAVER
> Engineering Day 세션을 공개합니다 / 발표 내용 / 발표 대상 / 목차" 구조라
> 읽을 본문이 애초에 없고, 그 발췌가 최선의 설명이다.
>
> 그래서 **UA를 브라우저로 위장하지 않았다.** Task 11에서 403 피드를 끈 것과
> 같은 판단이고, 여기서는 폴백이 실제로 메워 주므로 더 그럴 이유가 없다.

> **Task 19에 넘기는 수치**
>
> 기사 10건의 본문 합계 **63,244자 = 입력 37,432토큰**. 요약 프롬프트의
> 입력 바닥값이다(프로필·지시문 별도).
>
> **10건 중 7건이 `BODY_MAX_CHARS`(8,000자) 상한에 걸렸다.** 즉 이 상수가
> 요약 입력을 좌우하는 손잡이다. 5,000자로 내리면 입력이 약 23,000토큰이 된다.

- [x] **Step 1: HTML fixture 작성**

`tests/fixtures/article.html` — 본문 외에 내비게이션·광고·푸터가 섞인 실제 구조:

```html
<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><title>결제 서버 P99 40ms 달성기</title></head>
<body>
  <nav><a href="/">홈</a> <a href="/tech">기술</a> <a href="/careers">채용</a></nav>
  <aside class="ad">지금 가입하면 10만원 할인! 광고 문의: ad@example.com</aside>
  <article>
    <h1>결제 서버 P99 40ms 달성기</h1>
    <p>결제 서버의 P99 지연이 400ms였다. 사용자 이탈의 직접 원인이었고, 결제
       전환율이 분기 내내 떨어지는 동안 원인을 찾지 못하고 있었다.</p>
    <p>프로파일링 결과 커넥션 풀 고갈이 병목이었다. 처음에는 풀 크기를 늘리는
       처방을 떠올렸지만 그것은 근본 해결이 아니었다. 풀을 두 배로 늘려도 지연은
       280ms에서 멈췄고, 트래픽이 조금만 늘면 다시 400ms로 돌아왔다.</p>
    <p>실제 원인은 트랜잭션 경계가 너무 넓은 것이었다. 외부 결제 게이트웨이를
       호출하는 구간이 트랜잭션 안에 들어 있어, 네트워크 왕복 시간 동안 커넥션을
       붙잡고 있었다. 평균 180ms의 외부 호출이 커넥션 하나를 그만큼 점유했다.</p>
    <p>트랜잭션을 쪼개 외부 호출을 밖으로 빼낸 뒤 P99는 40ms로 떨어졌다. 풀
       크기는 원래대로 되돌렸는데도 그랬다. 교훈은 풀 크기보다 트랜잭션 수명을
       먼저 보라는 것이다. 지표로는 활성 커넥션 수가 아니라 커넥션 점유 시간을
       봐야 병목이 드러난다.</p>
  </article>
  <footer>© 2026 Example Corp. 모든 권리 보유.</footer>
</body>
</html>
```

추출 결과 491자, `채용`·`10만원 할인`·`모든 권리 보유`가 모두 걸러진다.

- [x] **Step 2: 실패하는 테스트 작성**

`tests/test_enrich.py`:

```python
from pathlib import Path

import pytest

from pipeline.enrich import (
    ARTICLE_ATTEMPTS,
    BODY_MAX_CHARS,
    BODY_MIN_CHARS,
    REQUEST_DELAY,
    enrich,
    extract_body,
)
from pipeline.lib.http import FetchResult
from pipeline.lib.retry import Permanent, Transient
from pipeline.models import RankedBundle, RankedItem, RawItem

FIXTURES = Path(__file__).parent / "fixtures"
WINDOW = ("2026-11-09T22:20:00+00:00", "2026-11-10T22:20:00+00:00")


def _ranked(index: int = 0, excerpt: str = "RSS 발췌 내용") -> RankedItem:
    return RankedItem(
        item=RawItem(
            source="토스_기술블로그",
            title=f"제목 {index}",
            url=f"https://toss.tech/a/{index}",
            published="2026-11-10T05:30:00+00:00",
            excerpt=excerpt,
        ),
        score=85,
        reason="이유",
        topic="backend",
    )


def _bundle(items) -> RankedBundle:
    return RankedBundle(
        window_start=WINDOW[0], window_end=WINDOW[1],
        selected=items, all_scores=[],
    )


def _ok_fetch():
    data = (FIXTURES / "article.html").read_bytes()

    def fetch(url: str) -> FetchResult:
        return FetchResult(content=data, final_url=url, moved_from=None)

    return fetch


def _html(body_text: str) -> bytes:
    return f"<html><body><article><p>{body_text}</p></article></body></html>".encode()


def _enrich(items, fetch=None, sleeps=None):
    recorded: list[float] = [] if sleeps is None else sleeps
    bundle = enrich(
        ranked=_bundle(items),
        fetch=fetch or _ok_fetch(),
        sleep=recorded.append,
    )
    return bundle, recorded


# --- 본문 추출 ---

def test_본문을_추출한다():
    body = extract_body((FIXTURES / "article.html").read_bytes())

    assert body is not None
    assert "커넥션 풀 고갈이 병목" in body


def test_내비게이션과_광고와_푸터를_걸러낸다():
    body = extract_body((FIXTURES / "article.html").read_bytes())

    assert "채용" not in body
    assert "10만원 할인" not in body
    assert "모든 권리 보유" not in body


def test_내비게이션만_있는_HTML은_None을_돌려준다():
    """**trafilatura는 이걸 None으로 주지 않는다.** 2026-11-12 확인:
    `<nav>menu</nav>`를 넣으면 `'menu'`를 돌려준다. 그대로 본문으로 쓰면
    브리핑에 "메뉴"가 실린다. 길이 하한이 필요한 이유다.
    """
    assert extract_body(b"<html><body><nav>\xeb\xa9\x94\xeb\x89\xb4</nav></body></html>") is None


def test_너무_짧은_추출은_본문으로_보지_않는다():
    """RSS 발췌가 보통 250자다. 그보다 짧은 추출은 발췌가 낫다."""
    assert extract_body(_html("짧다")) is None


def test_하한을_넘으면_본문으로_본다():
    body = extract_body(_html("가" * BODY_MIN_CHARS))
    assert body is not None


def test_HTML이_아니면_None을_돌려준다():
    assert extract_body(b"\x00\x01\x02") is None


def test_하한이_발췌_길이보다_작지_않다():
    """하한이 너무 크면 멀쩡한 짧은 글이 발췌로 떨어진다.
    2026-11-12 실측 발췌 중앙값 250자를 기준으로 둔다.
    """
    assert 100 <= BODY_MIN_CHARS <= 400


# --- 정상 경로 ---

def test_본문을_확보하고_출처를_기록한다():
    bundle, _ = _enrich([_ranked()])

    assert len(bundle.articles) == 1
    assert bundle.articles[0].body_source == "trafilatura"
    assert bundle.articles[0].fallback_reason is None
    assert "트랜잭션" in bundle.articles[0].body


def test_본문을_상한에서_자른다():
    bundle, _ = _enrich(
        [_ranked()],
        fetch=lambda url: FetchResult(content=_html("가" * 20000),
                                      final_url=url, moved_from=None),
    )

    assert len(bundle.articles[0].body) <= BODY_MAX_CHARS


def test_상한이_하한보다_크다():
    assert BODY_MAX_CHARS > BODY_MIN_CHARS


def test_요청_사이에_간격을_둔다():
    """상대 서버에 부담을 주지 않는다."""
    _, sleeps = _enrich([_ranked(0), _ranked(1), _ranked(2)])

    # 3건이면 2번 쉰다 (마지막 뒤에는 쉬지 않는다)
    assert len(sleeps) == 2
    assert all(delay >= 1.0 for delay in sleeps)


def test_한_건이면_쉬지_않는다():
    _, sleeps = _enrich([_ranked()])
    assert sleeps == []


def test_선별_결과가_비면_요청하지_않는다():
    calls = []

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        return FetchResult(content=b"", final_url=url, moved_from=None)

    bundle, _ = _enrich([], fetch=fetch)

    assert bundle.articles == []
    assert calls == []


def test_윈도우_경계를_이어받는다():
    bundle, _ = _enrich([_ranked()])
    assert bundle.window_start == WINDOW[0]
    assert bundle.window_end == WINDOW[1]


def test_선별_정보를_그대로_들고_간다():
    """점수·이유·주제는 요약과 화면이 쓴다."""
    bundle, _ = _enrich([_ranked()])
    ranked = bundle.articles[0].ranked

    assert ranked.score == 85
    assert ranked.reason == "이유"
    assert ranked.topic == "backend"


# --- 폴백과 분류 ---

def test_본문_추출_실패시_RSS_발췌로_폴백한다():
    """핵심 요구사항. 한 건 실패로 파이프라인이 죽지 않는다."""
    bundle, _ = _enrich(
        [_ranked(excerpt="발췌로 대체된다")],
        fetch=lambda url: FetchResult(
            content=b"<html><body><nav>menu</nav></body></html>",
            final_url=url, moved_from=None,
        ),
    )

    assert bundle.articles[0].body == "발췌로 대체된다"
    assert bundle.articles[0].body_source == "rss_excerpt"
    assert "추출 실패" in bundle.articles[0].fallback_reason


def test_영구_실패는_재시도하지_않고_즉시_폴백한다():
    """403 봇 차단에 재시도를 걸면 10건이면 수십 초를 버린다.

    2026-11-12 실측: 상위 10건 중 Netflix(Medium)가 403이었다.
    """
    calls = []

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        raise Permanent(f"{url} HTTP 403")

    bundle, sleeps = _enrich([_ranked(excerpt="발췌")], fetch=fetch)

    assert len(calls) == 1                      # 재시도하지 않았다
    assert sleeps == []                          # 백오프도 없었다
    assert bundle.articles[0].body_source == "rss_excerpt"
    assert "403" in bundle.articles[0].fallback_reason


def test_일시_실패는_재시도한_뒤_폴백한다():
    calls = []

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        raise Transient(f"{url} HTTP 503")

    bundle, _ = _enrich([_ranked(excerpt="발췌")], fetch=fetch)

    assert len(calls) == ARTICLE_ATTEMPTS
    assert bundle.articles[0].body_source == "rss_excerpt"
    assert "503" in bundle.articles[0].fallback_reason


def test_재시도_중_성공하면_본문을_쓴다():
    calls = []
    data = (FIXTURES / "article.html").read_bytes()

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        if len(calls) == 1:
            raise Transient("일시 장애")
        return FetchResult(content=data, final_url=url, moved_from=None)

    bundle, _ = _enrich([_ranked()], fetch=fetch)

    assert bundle.articles[0].body_source == "trafilatura"
    assert bundle.articles[0].fallback_reason is None


def test_한_건이_실패해도_나머지는_본문을_쓴다():
    """절대 중단하지 않는다 — spec 8.2."""
    data = (FIXTURES / "article.html").read_bytes()

    def fetch(url: str) -> FetchResult:
        if url.endswith("/0"):
            raise Permanent("HTTP 403")
        return FetchResult(content=data, final_url=url, moved_from=None)

    bundle, _ = _enrich([_ranked(0, excerpt="발췌"), _ranked(1)], fetch=fetch)

    assert len(bundle.articles) == 2
    assert bundle.articles[0].body_source == "rss_excerpt"
    assert bundle.articles[1].body_source == "trafilatura"


def test_본문도_발췌도_없으면_그_건만_제외한다():
    """요약할 재료가 전혀 없으면 보낼 수 없다. 중단은 하지 않는다."""
    def fetch(url: str) -> FetchResult:
        raise Permanent("HTTP 404")

    bundle, _ = _enrich([_ranked(0, excerpt=""), _ranked(1, "발췌 있음")], fetch=fetch)

    assert len(bundle.articles) == 1
    assert bundle.articles[0].body == "발췌 있음"


def test_공백뿐인_발췌도_없는_것으로_본다():
    def fetch(url: str) -> FetchResult:
        raise Permanent("HTTP 404")

    bundle, _ = _enrich([_ranked(0, excerpt="   \n  ")], fetch=fetch)
    assert bundle.articles == []


def test_발췌_폴백도_상한에서_자른다():
    """2026-11-12 실측: Netflix 발췌가 15,633자였다. 전문이 피드에 들어
    있는 소스가 있어서, 폴백 쪽도 자르지 않으면 요약 토큰이 튄다.
    """
    def fetch(url: str) -> FetchResult:
        raise Permanent("HTTP 403")

    bundle, _ = _enrich([_ranked(0, excerpt="가" * 20000)], fetch=fetch)
    assert len(bundle.articles[0].body) <= BODY_MAX_CHARS


def test_분류되지_않은_예외는_삼키지_않는다():
    """fetch 구현의 코드 버그를 발췌 폴백으로 가리면 원인을 못 찾는다."""
    def fetch(url: str) -> FetchResult:
        raise TypeError("코드 버그")

    with pytest.raises(TypeError):
        _enrich([_ranked()], fetch=fetch)


def test_요청_간격이_1초_이상이다():
    assert REQUEST_DELAY >= 1.0
```

- [x] **Step 3: 실패를 확인**

```bash
pytest tests/test_enrich.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.enrich'`

- [x] **Step 4: 최소 구현 작성**

`pipeline/enrich.py`:

```python
"""03 본문: 선별된 글의 본문을 가져온다.

이 단계는 절대 중단하지 않는다. 외부 사이트 크롤링은 구조적으로 가장 자주
깨지는 반면, 폴백(RSS 발췌)이 존재하는 유일한 단계이기도 하다.
품질 저하가 전송 실패보다 낫다.

분류의 실익이 여기서 가장 크다 — 403(봇 차단)은 재시도해도 같으므로
즉시 발췌로 내려가고, 503은 재시도한 뒤 내려간다.

2026-11-12 실측(상위 10건): 본문 확보 6건, 폴백 4건. 그리고 폴백이
나쁘지 않았다 — **크롤링이 막히거나 JS로 그리는 소스가 피드에 본문을
길게 담는다**(Netflix 15,633자, 네이버 D2 14,790자가 사실상 전문).
반대로 본문 추출이 성공한 소스의 발췌는 39~673자로 짧았다.

실행: python -m pipeline.enrich
"""

import time
from datetime import datetime, timezone
from typing import Callable

import trafilatura

from pipeline.lib.http import FetchResult
from pipeline.lib.http import fetch as http_fetch
from pipeline.lib.retry import Permanent, Transient, with_retry
from pipeline.lib.store import LocalStore
from pipeline.lib.timeutil import KST
from pipeline.models import Article, ArticlesBundle, RankedBundle

# 이 이상은 요약 품질에 기여하지 않으면서 토큰만 쓴다.
# 발췌 폴백에도 같은 상한을 적용한다 — 피드에 전문을 담는 소스가 있어서
# (실측 15,633자) 폴백 쪽을 자르지 않으면 요약 토큰이 튄다.
BODY_MAX_CHARS = 8000

# 이보다 짧은 추출은 본문으로 보지 않는다.
#
# **trafilatura가 `None`을 잘 주지 않는다.** 2026-11-12 확인:
# `<nav>menu</nav>`만 있는 HTML에 `'menu'`를 돌려준다. 그대로 쓰면 브리핑에
# "메뉴"가 실린다. RSS 발췌가 중앙값 250자이므로, 그보다 한참 짧은 추출은
# 발췌가 낫다.
BODY_MIN_CHARS = 200

# 상대 서버 부담을 줄이는 요청 간격(초).
#
# 호스트별로 두지 않고 모든 요청 사이에 둔다. 상위 10건은 대개 서로 다른
# 사이트라 과한 배려지만, 같은 소스가 2건 들어오는 일이 실제로 있었고
# (실측: 네이버 D2가 상위 10건에 3건) 10건이면 13.5초라 비용이 작다.
REQUEST_DELAY = 1.5

# 글당 시도 횟수 (일시 실패에만 적용된다. 영구 실패는 1회로 끝난다.)
ARTICLE_ATTEMPTS = 2

FetchFn = Callable[[str], FetchResult]
SleepFn = Callable[[float], None]


def extract_body(payload: bytes) -> str | None:
    """HTML에서 본문만 뽑는다. 실패하거나 너무 짧으면 None."""
    try:
        # include_comments=False: 댓글 제외
        # include_tables=False: 표는 요약에 도움이 안 되고 토큰을 많이 쓴다
        # favor_precision=True: 애매하면 빼는 쪽. 광고가 섞이는 것보다 낫다
        text = trafilatura.extract(
            payload,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
    except Exception:  # noqa: BLE001 — 어떤 입력이 와도 None으로 떨어뜨린다
        return None

    if not text:
        return None
    text = text.strip()
    if len(text) < BODY_MIN_CHARS:
        return None
    return text


def _fetch_body(
    url: str,
    *,
    fetch: FetchFn,
    sleep: SleepFn,
) -> tuple[str | None, str | None]:
    """(본문, 폴백 이유)를 돌려준다. 본문이 있으면 이유는 None이다.

    분류되지 않은 예외는 그대로 올린다 — fetch 구현의 코드 버그를
    발췌 폴백으로 가리면 원인을 찾을 수 없다.
    """
    try:
        result = with_retry(
            lambda: fetch(url),
            attempts=ARTICLE_ATTEMPTS,
            sleep=sleep,
        )
    except Permanent as error:
        # 403 봇 차단, 404 삭제, 410 등. 재시도해도 같다.
        return None, f"접근 불가 — {error}"
    except Transient as error:
        # with_retry가 이미 재시도했는데도 실패했다.
        return None, f"일시 실패(재시도 후) — {error}"

    body = extract_body(result.content)
    if body is None:
        return None, (
            f"본문 추출 실패 — 광고·내비게이션만 있거나 JS로 그리는 "
            f"페이지일 수 있다(추출 {BODY_MIN_CHARS}자 미만)"
        )
    return body, None


def enrich(
    *,
    ranked: RankedBundle,
    fetch: FetchFn = http_fetch,
    sleep: SleepFn = time.sleep,
) -> ArticlesBundle:
    """선별된 글의 본문을 확보한다. 실패는 발췌로 폴백한다."""
    articles: list[Article] = []
    total = len(ranked.selected)

    for position, item in enumerate(ranked.selected):
        body, reason = _fetch_body(item.item.url, fetch=fetch, sleep=sleep)

        if body is not None:
            body_source: str = "trafilatura"
            fallback_reason: str | None = None
        else:
            # 폴백: RSS 발췌. 얕을 수도 있고, 소스에 따라 전문일 수도 있다.
            body = item.item.excerpt.strip()
            body_source = "rss_excerpt"
            fallback_reason = reason

        if not body:
            # 본문도 발췌도 없으면 요약할 재료가 없다. 이 건만 제외한다.
            continue

        articles.append(Article(
            ranked=item,
            body=body[:BODY_MAX_CHARS],
            body_source=body_source,   # type: ignore[arg-type]
            fallback_reason=fallback_reason,
        ))

        # 마지막 요청 뒤에는 쉬지 않는다.
        if position < total - 1:
            sleep(REQUEST_DELAY)

    return ArticlesBundle(
        window_start=ranked.window_start,
        window_end=ranked.window_end,
        articles=articles,
    )


def main() -> None:
    date = datetime.now(timezone.utc).astimezone(KST).date().isoformat()
    store = LocalStore(date=date)

    bundle = enrich(ranked=store.read("ranked", RankedBundle))
    path = store.write("articles", bundle)

    fallbacks = [a for a in bundle.articles if a.body_source == "rss_excerpt"]
    print(f"본문 확보 {len(bundle.articles)}건 → {path}")
    for article in bundle.articles:
        mark = "발췌" if article.body_source == "rss_excerpt" else "본문"
        print(f"  [{mark}] {len(article.body):5d}자  {article.ranked.item.title[:45]}")

    if fallbacks:
        print()
        print(f"  {len(fallbacks)}건이 발췌로 폴백됐다")
        for article in fallbacks:
            print(f"    {article.ranked.item.source}: {article.fallback_reason}")
        print("  '접근 불가'가 반복되는 소스는 봇 차단일 가능성이 높다.")
        print("  발췌가 충분히 길면(피드에 전문을 담는 소스) 품질 저하가 아니다.")


if __name__ == "__main__":
    main()
```

> **설명** — `_fetch_body`가 예외를 던지지 않고 `(본문, 이유)` 튜플을 돌려주는
> 이유는, 호출부에서 "실패했지만 계속한다"가 **정상 흐름**이기 때문이다.
> 예외로 처리하면 호출부가 try/except로 감싸야 하고, 그러면 "이건 정상
> 폴백인지 진짜 버그인지"가 흐려진다.
>
> `body_source: str = "trafilatura"`에 타입을 명시한 이유는, 아래 `else`
> 분기에서 다른 값을 넣기 때문이다. 명시하지 않으면 타입 검사기가 첫 대입에서
> `Literal["trafilatura"]`로 좁혀버려 재대입을 에러로 본다.
> `# type: ignore[arg-type]`은 `str`을 `BodySource`(Literal) 자리에 넘기는
> 것을 검사기에게 허용하는 표시다.
>
> `REQUEST_DELAY`를 호스트별이 아니라 모든 요청 사이에 두는 것은 의도적이다.
> 상위 10건은 대개 서로 다른 사이트라 과한 배려지만, **같은 소스가 여러 건
> 들어오는 일이 실제로 있었고**(실측: 네이버 D2가 상위 10건에 3건) 10건이면
> 13.5초라 비용이 작다. 호스트별로 나누는 복잡도를 살 이유가 없다.
>
> **구문법 대조** — `tuple[str | None, str | None]`은 구형으로
> `Tuple[Optional[str], Optional[str]]`이다.

- [x] **Step 5: 통과를 확인**

```bash
pytest tests/test_enrich.py
```

Expected: `25 passed`. 전체 `286 passed`.

- [x] **Step 6: 실제 상위 10건으로 본문 확보**

```bash
python -m pipeline.enrich
```

**실측: 10건 전부 산출(본문 6 · 발췌 4), 21초.** 폴백 이유가 소스별로
출력돼 "어느 소스가 왜 막혔나"가 바로 보인다.

- [x] **Step 7: 커밋**

```bash
git add pipeline/enrich.py tests/test_enrich.py tests/fixtures/article.html
git commit -m "feat: 본문 확보 — 영구 실패 즉시 폴백, 일시 실패만 재시도, 이유 기록"
```

---

## Task 19: 요약과 최종 선정

**Files:**
- Create: `pipeline/summarize.py`
- Create: `tests/test_summarize.py`
- Modify: `pipeline/models.py` (LLM 초안의 제약 완화)
- Modify: `pipeline/lib/llm.py` (스키마 위반을 재시도에 태운다)
- Modify: `pipeline/rank.py` (정규화 추가)

> **이 태스크가 프로젝트의 가정 하나를 깼다.**
>
> ### 스키마 제약은 대체로 지켜지지만 보장이 아니다
>
> 1차 실행이 이렇게 죽었다:
>
> ```
> ValidationError: 1 validation error for SummarySheet
> summaries.3.headline
>   String should have at most 30 characters
>   input_value='Cloudflare가 Raft 대신 QuePaxa를 고른 이유'  (34자)
> ```
>
> `SummaryDraft.headline`에 `max_length=30`이 있고 JSON 스키마에
> `maxLength: 30`으로 나가고 프롬프트에도 "30자 이내"라고 적었는데, 모델이
> 34자를 돌려줬다. 그리고 pydantic이 **SummarySheet 전체를 거부해 요약
> 7건이 한꺼번에 날아갔다.**
>
> **원인을 추적한 과정** (추론이 두 번 틀렸다):
>
> 1. "API가 강제하지 않는 모양이다" → **틀렸다.** 평평한 스키마에 "제약을
>    무시하고 26자를 넣어라"고 지시해도 `maxLength`·`minimum/maximum`·`enum`을
>    모두 강제했다(`abcde`, `10`, `'a'`).
> 2. "스트리밍 경로에서만 안 먹히는 모양이다" → **틀렸다.** 같은 탐침을
>    `beta.messages.stream`으로 보내도 강제됐다.
> 3. "`$defs` 안의 배열 항목이라 안 먹히는 모양이다" → **틀렸다.**
>    중첩 스키마 탐침도 3건 모두 강제됐다.
>
> 그리고 **같은 요청을 다시 보내니 통과했다** — 2차 실행의 같은 글
> 헤드라인은 `Cloudflare가 QuePaxa를 택한 이유`(26자)였다.
>
> 결론: **강제는 대체로 작동하지만 비결정적으로 새어 나간다.** 보장으로
> 기대고 설계하면 안 된다.
>
> ### 그래서 세운 규칙 — LLM 초안은 느슨하게, 우리 계약은 엄격하게, 경계에서 정규화
>
> | | 초안(LLM 출력) | 우리 계약 | 경계 |
> |---|---|---|---|
> | 헤드라인 | `SummaryDraft.headline` 제약 없음 | `Summary.headline` ≤ 30 (DB 제약과 동일) | `summarize.shorten` |
> | 점수 | `ScoreItem.score` 제약 없음 | `RankedItem.score` 0~100 | `rank.clamp_score` |
> | 분류 | `ScoreItem.topic: str` | `RankedItem.topic: Topic` | `rank.normalize_topic` |
> | index | `ScoreItem.index: int` | — | `rank`의 `0 <= index < len` 검사 |
>
> **그러고도 남는 경우를 위한 그물**: `classify_sdk_error`가 pydantic
> `ValidationError`를 `SchemaError`로 바꿔 **1회 재시도**에 태운다.
> 비결정성이므로 두 번째에 통과할 가능성이 높다 — 실제로 2차 실행이 그랬다.
>
> ### 이 변경의 대가를 측정했다
>
> `topic`에서 `enum`을 빼면 생성 품질이 떨어질 수 있다. 재실행해 비교했다:
>
> | topic | enum 있음 | enum 없음 |
> |---|---:|---:|
> | AI | 82 | 85 |
> | other | 93 | 89 |
> | backend | 23 | 23 |
> | tooling | 20 | 24 |
> | infra | 22 | 19 |
>
> **다섯 값 밖으로 나온 것은 0건.** 차이는 재실행 변동 범위다. 프롬프트의
> "AI / backend / infra / tooling / other 중 하나"가 그 역할을 한다.

> **출력 토큰 예산** (Task 16과 같은 함정)
>
> 래퍼 기본값(16,000)에 맡기면 잘릴 수 있고, 잘리면 **브리핑 전체가**
> 날아간다(요약은 폴백이 없다). 채점과 달리 출력 **건수가 MAX_SUMMARIES로
> 묶여** 있어 입력 항목 수에 비례하지 않으므로 함수가 아니라 상수로 뒀다:
> `28,000(사고) + 7 × 400 = 30,800`. 비스트리밍 한계(21,333)를 넘으므로
> 래퍼가 스트리밍을 고른다.

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_summarize.py`:

```python
import pytest
from pydantic import ValidationError

from pipeline.lib.llm import needs_streaming
from pipeline.models import (
    HEADLINE_MAX,
    Article,
    ArticlesBundle,
    RankedItem,
    RawItem,
    SummaryDraft,
    SummarySheet,
)
from pipeline.summarize import (
    MAX_SUMMARIES,
    OUTPUT_TOKENS_PER_SUMMARY,
    SCORE_THRESHOLD,
    SUMMARIZE_EFFORT,
    SUMMARIZE_MAX_TOKENS,
    THINKING_ALLOWANCE,
    build_prompt,
    shorten,
    summarize,
)
from tests.fakes import FakeLLM

WINDOW = ("2026-11-09T22:20:00+00:00", "2026-11-10T22:20:00+00:00")


def _article(index: int = 0, score: int = 85, source: str = "토스_기술블로그") -> Article:
    return Article(
        ranked=RankedItem(
            item=RawItem(
                source=source,
                title=f"제목 {index}",
                url=f"https://e.com/{index}",
                published="2026-11-10T05:30:00+00:00",
                excerpt="발췌",
            ),
            score=score,
            reason="이유",
            topic="backend",
        ),
        body=f"본문 {index}",
        body_source="trafilatura",
    )


def _bundle(articles) -> ArticlesBundle:
    return ArticlesBundle(
        window_start=WINDOW[0], window_end=WINDOW[1], articles=articles
    )


def _draft(index: int) -> SummaryDraft:
    return SummaryDraft(
        index=index,
        headline=f"헤드라인 {index}",
        bullets=["요점 하나", "요점 둘"],
        why_it_matters="중요한 이유",
    )


def _summarize(articles, drafts):
    llm = FakeLLM(responses=[SummarySheet(summaries=drafts)])
    return summarize(articles=_bundle(articles), llm=llm), llm


# --- 출력 토큰 예산 ---
#
# Task 16과 같은 함정이다. 래퍼 기본값(16,000)에 맡기면 잘릴 수 있고, 잘리면
# 브리핑 전체가 날아간다. 여기서는 출력 **건수**가 MAX_SUMMARIES로 묶여 있어
# 항목 수에 비례하지 않으므로 상수로 둔다 — 대신 사고 토큰 여유가 커야 한다.
# 2026-11-18 실측: 입력이 37,432토큰(기사 10건 본문)이고 effort는 medium이다.

def test_요약_출력_예산이_기본값보다_크다():
    from pipeline.lib.llm import DEFAULT_MAX_TOKENS

    assert SUMMARIZE_MAX_TOKENS > DEFAULT_MAX_TOKENS


def test_최대_건수를_담을_수_있다():
    assert SUMMARIZE_MAX_TOKENS >= THINKING_ALLOWANCE + MAX_SUMMARIES * OUTPUT_TOKENS_PER_SUMMARY


def test_사고_토큰_여유가_넉넉하다():
    """effort=medium에 입력 37k 토큰이다. 사고가 길어질 수 있다."""
    assert THINKING_ALLOWANCE >= 16_000


def test_요약은_스트리밍으로_간다():
    """예산이 비스트리밍 한계(21,333)를 넘는다. 래퍼가 알아서 고른다."""
    assert needs_streaming(SUMMARIZE_MAX_TOKENS)


def test_산정한_max_tokens를_LLM에_넘긴다():
    """계산만 하고 넘기지 않으면 아무 의미가 없다."""
    _, llm = _summarize([_article(0)], [_draft(0)])
    assert llm.calls[0]["max_tokens"] == SUMMARIZE_MAX_TOKENS


def test_요약은_medium_effort로_한다():
    """채점은 low, 요약은 medium. 요약이 결과물 자체다."""
    _, llm = _summarize([_article(0)], [_draft(0)])
    assert llm.calls[0]["effort"] == SUMMARIZE_EFFORT == "medium"


# --- 계약 경계 ---

def test_초안_헤드라인에는_상한을_걸지_않는다():
    """**스키마의 maxLength는 강제되지 않는다 — 2026-11-18 실측.**

    `maxLength: 30`을 넣고 프롬프트에도 "30자 이내"라고 적었는데 모델이
    33자를 돌려줬고(`Cloudflare가 Raft 대신 QuePaxa를 고른 이유`),
    pydantic이 SummarySheet **전체**를 거부해 요약 7건이 한꺼번에 날아갔다.

    LLM 출력은 신뢰할 수 없는 입력이다. 상한은 받는 쪽(Summary)에 두고
    중간에서 줄인다.
    """
    schema = SummarySheet.model_json_schema()["$defs"]["SummaryDraft"]
    assert "maxLength" not in schema["properties"]["headline"]

    # 긴 헤드라인도 받아들여야 한다 — 거부하면 브리핑 전체를 잃는다
    draft = SummaryDraft(index=0, headline="가" * 40,
                         bullets=["b"], why_it_matters="w")
    assert len(draft.headline) == 40


def test_불릿_개수가_스키마에_들어간다():
    schema = SummarySheet.model_json_schema()["$defs"]["SummaryDraft"]
    assert schema["properties"]["bullets"]["maxItems"] == 3
    assert schema["properties"]["bullets"]["minItems"] == 1


def test_최종_요약은_헤드라인_상한을_지킨다():
    """DB의 `articles_headline_len` 제약과 같은 값이다."""
    from pipeline.models import Summary

    with pytest.raises(ValidationError):
        Summary(article=_article(), headline="가" * (HEADLINE_MAX + 1),
                bullets=["b"], why_it_matters="w")


def test_빈_헤드라인을_거부한다():
    with pytest.raises(ValidationError):
        SummaryDraft(index=0, headline="", bullets=["b"], why_it_matters="w")


def test_불릿이_없으면_거부한다():
    """요점이 없는 요약은 요약이 아니다."""
    with pytest.raises(ValidationError):
        SummaryDraft(index=0, headline="h", bullets=[], why_it_matters="w")


# --- 프롬프트 ---

def test_프롬프트에_본문이_들어간다():
    prompt = build_prompt(articles=[_article()])
    assert "본문 0" in prompt


def test_프롬프트가_본문을_다시_자르지_않는다():
    """enrich가 이미 BODY_MAX_CHARS로 잘랐다. 여기서 또 자르면 손잡이가
    두 곳이 되어 토큰 예산을 추적할 수 없다.
    """
    긴본문 = "가" * 8000
    article = Article(
        ranked=_article().ranked, body=긴본문, body_source="trafilatura",
    )
    assert 긴본문 in build_prompt(articles=[article])


def test_프롬프트가_한국어_요약을_요구한다():
    """해외 소스가 영어로 요약되면 안 된다."""
    prompt = build_prompt(articles=[_article()])
    assert "한국어" in prompt


def test_프롬프트가_헤드라인_길이_제약을_명시한다():
    prompt = build_prompt(articles=[_article()])
    assert "30자" in prompt


def test_프롬프트가_건수를_채우지_말라고_지시한다():
    """건수 채우기가 큐레이션을 망치는 주된 방식이다."""
    prompt = build_prompt(articles=[_article()])
    assert "채우지" in prompt


def test_프롬프트가_최대_건수를_명시한다():
    prompt = build_prompt(articles=[_article()])
    assert str(MAX_SUMMARIES) in prompt


def test_프롬프트에_출처와_주제가_들어간다():
    """요약이 "토스가 공개한"처럼 출처를 쓸 수 있어야 한다."""
    prompt = build_prompt(articles=[_article(0, source="토스_기술블로그")])
    assert "토스_기술블로그" in prompt and "backend" in prompt


def test_프롬프트에_번호가_들어간다():
    prompt = build_prompt(articles=[_article(0), _article(1)])
    assert "[0]" in prompt and "[1]" in prompt


# --- 요약 ---

def test_LLM이_돌려준_요약을_담는다():
    briefing, _ = _summarize([_article(0)], [_draft(0)])

    assert len(briefing.summaries) == 1
    assert briefing.summaries[0].headline == "헤드라인 0"


def test_LLM이_생략한_건은_빠진다():
    """본문을 읽어보니 내용이 없는 글을 여기서 걸러낸다."""
    briefing, _ = _summarize([_article(0), _article(1)], [_draft(0)])

    assert len(briefing.summaries) == 1
    assert briefing.summaries[0].article.ranked.item.title == "제목 0"


def test_임계값_미달은_LLM이_넣었어도_제외한다():
    """결정적 가드. LLM 판단과 무관하게 점수 기준을 적용한다."""
    low = _article(0, score=SCORE_THRESHOLD - 1)
    briefing, _ = _summarize([low], [_draft(0)])

    assert briefing.summaries == []


def test_임계값과_같으면_통과한다():
    exact = _article(0, score=SCORE_THRESHOLD)
    briefing, _ = _summarize([exact], [_draft(0)])

    assert len(briefing.summaries) == 1


def test_최대_건수를_넘지_않는다():
    articles = [_article(i) for i in range(MAX_SUMMARIES + 3)]
    drafts = [_draft(i) for i in range(MAX_SUMMARIES + 3)]
    briefing, _ = _summarize(articles, drafts)

    assert len(briefing.summaries) == MAX_SUMMARIES


def test_점수_높은_순으로_남긴다():
    """상한을 넘으면 점수가 높은 것이 남아야 한다."""
    articles = [_article(i, score=60 + i) for i in range(MAX_SUMMARIES + 2)]
    drafts = [_draft(i) for i in range(MAX_SUMMARIES + 2)]
    briefing, _ = _summarize(articles, drafts)

    scores = [s.article.ranked.score for s in briefing.summaries]
    assert scores == sorted(scores, reverse=True)
    assert min(scores) > 60


def test_범위를_벗어난_index는_무시한다():
    briefing, _ = _summarize([_article(0)], [_draft(0), _draft(99)])
    assert len(briefing.summaries) == 1


def test_중복_index는_한_번만_담는다():
    briefing, _ = _summarize([_article(0)], [_draft(0), _draft(0)])
    assert len(briefing.summaries) == 1


def test_중복_index는_먼저_나온_것을_쓴다():
    """어느 쪽을 쓰는지가 정해져 있어야 한다."""
    첫째 = SummaryDraft(index=0, headline="먼저", bullets=["b"], why_it_matters="w")
    둘째 = SummaryDraft(index=0, headline="나중", bullets=["b"], why_it_matters="w")
    briefing, _ = _summarize([_article(0)], [첫째, 둘째])

    assert briefing.summaries[0].headline == "먼저"


def test_후보_건수를_기록한다():
    """적중률 추적에 쓴다."""
    briefing, _ = _summarize([_article(0), _article(1)], [_draft(0)])
    assert briefing.considered == 2


def test_본문이_없으면_LLM을_호출하지_않는다():
    llm = FakeLLM(responses=[])
    briefing = summarize(articles=_bundle([]), llm=llm)

    assert briefing.summaries == []
    assert llm.prompts == []
    assert briefing.considered == 0


def test_전부_임계값_미달이면_빈_브리핑이_된다():
    """0건이 정상 상태다. 예외를 던지지 않는다."""
    low = [_article(i, score=10) for i in range(3)]
    briefing, _ = _summarize(low, [_draft(0), _draft(1), _draft(2)])

    assert briefing.summaries == []
    assert briefing.considered == 3


def test_윈도우_경계를_이어받는다():
    briefing, _ = _summarize([_article(0)], [_draft(0)])
    assert briefing.window_start == WINDOW[0]
    assert briefing.window_end == WINDOW[1]


def test_임계값이_가중치_적용_후_점수에_걸린다():
    """`RankedItem.score`는 이미 가중치가 적용된 값이다(rank.apply_weight).
    원점수에 걸면 가중치가 무의미해진다.
    """
    # 원점수 50에 가중치 1.3을 적용하면 65 — 임계값 60을 넘는다.
    # rank가 그 계산을 끝내 놓으므로 여기서는 65를 그대로 본다.
    article = _article(0, score=65)
    briefing, _ = _summarize([article], [_draft(0)])

    assert len(briefing.summaries) == 1


# --- 헤드라인 줄이기 ---
#
# 2026-11-18 실측으로 생긴 기능이다. 스키마의 maxLength는 강제되지 않고,
# 한 건이 넘기면 pydantic이 SummarySheet 전체를 거부해 브리핑이 사라진다.

def test_상한_안이면_그대로_둔다():
    assert shorten("짧은 헤드라인") == "짧은 헤드라인"


def test_상한을_넘으면_줄인다():
    assert len(shorten("가" * 50)) <= HEADLINE_MAX


def test_줄이면_말줄임표를_붙인다():
    assert shorten("가" * 50).endswith("…")


def test_단어_경계에서_끊는다():
    """한글도 띄어쓰기가 있다. 단어 중간에서 끊기면 읽기 나쁘다."""
    원문 = "Cloudflare가 Raft 대신 QuePaxa를 고른 이유"
    결과 = shorten(원문)

    assert len(결과) <= HEADLINE_MAX
    assert 결과.endswith("…")
    assert "QuePax" not in 결과 or 결과.startswith("Cloudflare가 Raft 대신 QuePaxa")


def test_단어_경계가_너무_앞이면_통째로_자른다():
    """공백이 맨 앞에만 있으면 단어 경계를 따르면 거의 다 날아간다."""
    원문 = "가 " + "나" * 50
    결과 = shorten(원문)

    assert len(결과) <= HEADLINE_MAX
    assert len(결과) > HEADLINE_MAX // 2


def test_앞뒤_공백을_없앤다():
    assert shorten("  헤드라인  ") == "헤드라인"


def test_긴_헤드라인이_와도_브리핑을_잃지_않는다():
    """이게 이 기능의 존재 이유다. 한 건 때문에 7건을 잃지 않는다."""
    drafts = [
        SummaryDraft(index=0, headline="짧다", bullets=["b"], why_it_matters="w"),
        SummaryDraft(index=1, headline="가" * 40, bullets=["b"], why_it_matters="w"),
    ]
    briefing, _ = _summarize([_article(0), _article(1)], drafts)

    assert len(briefing.summaries) == 2
    assert all(len(s.headline) <= HEADLINE_MAX for s in briefing.summaries)
```

- [x] **Step 2: 실패를 확인**

```bash
pytest tests/test_summarize.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.summarize'`

- [x] **Step 3: 최소 구현 작성**

`pipeline/summarize.py`:

```python
"""04 요약: 본문을 읽고 최종 선정과 요약을 한다.

02에서 이미 좁혔는데 또 거르는 이유는, 제목만으로는 알 수 없는 "본문을
읽어보니 내용이 없음"을 여기서 걸러내기 위해서다. 보도자료 재가공 기사가
대표적이다.

건수는 임계값으로 결정하고 상한만 둔다. LLM에 건수를 채우라고 하면
기준을 낮춰서 채우고, 그것이 반복되면 시스템이 버려진다.

실행: python -m pipeline.summarize
"""

from datetime import datetime, timezone

from pipeline.lib.llm import LLM, AnthropicLLM, Effort
from pipeline.lib.secrets import require
from pipeline.lib.store import LocalStore
from pipeline.lib.timeutil import KST
from pipeline.models import (
    HEADLINE_MAX,
    Article,
    ArticlesBundle,
    Briefing,
    Summary,
    SummarySheet,
)

# 가중치 적용 후 점수의 하한. 이 아래는 LLM이 넣었어도 보내지 않는다.
# `RankedItem.score`는 rank.apply_weight를 거친 값이므로 여기서 다시
# 가중치를 보지 않는다.
SCORE_THRESHOLD = 60

# 상한. 카톡에는 이 중 상위 5건만 싣고 나머지는 "외 N건"으로 표기한다.
MAX_SUMMARIES = 7

# 요약이 결과물 자체다. 채점(low)보다 한 단계 올린다.
SUMMARIZE_EFFORT: Effort = "medium"

# --- 출력 토큰 예산 ---
#
# Task 16과 같은 함정이다. 래퍼 기본값(16,000)에 맡기면 잘릴 수 있고,
# 잘리면 **브리핑 전체가** 날아간다(요약은 폴백이 없다).
#
# 채점과 달리 출력 **건수가 MAX_SUMMARIES로 묶여** 있어 입력 항목 수에
# 비례하지 않는다. 그래서 함수가 아니라 상수다. 대신 사고 토큰 여유를
# 크게 둔다 — 2026-11-18 실측으로 입력이 37,432토큰(기사 10건 본문)이고
# effort가 medium이라 사고가 길어질 수 있다.

# 요약 한 건당 출력 토큰. 헤드라인 30자 + 불릿 2~3개 + 의미 한 문장이면
# 실측 220토큰 정도이고, 여유를 둔다.
OUTPUT_TOKENS_PER_SUMMARY = 400

# 사고 토큰 여유. 비스트리밍 한계(21,333)를 넘기므로 래퍼가 스트리밍을
# 고른다 — Task 16에서 검증된 경로다.
THINKING_ALLOWANCE = 28_000

SUMMARIZE_MAX_TOKENS = THINKING_ALLOWANCE + MAX_SUMMARIES * OUTPUT_TOKENS_PER_SUMMARY


def shorten(text: str, limit: int = HEADLINE_MAX) -> str:
    """헤드라인을 상한 안으로 줄인다. 가능하면 단어 경계에서 끊는다.

    **왜 필요한가** — 2026-11-18 실측: 스키마에 `maxLength: 30`을 넣고
    프롬프트에도 "30자 이내"라고 적었는데 모델이 33자를 돌려줬다
    (`Cloudflare가 Raft 대신 QuePaxa를 고른 이유`). pydantic이 SummarySheet
    **전체**를 거부해 요약 7건이 한꺼번에 날아갔다.

    길이 보증은 프롬프트나 LLM이 아니라 여기에 있어야 한다. 한 건의 긴
    헤드라인으로 그날 브리핑을 잃을 이유가 없다.
    """
    text = text.strip()
    if len(text) <= limit:
        return text

    # 말줄임표 한 칸을 남긴다.
    cut = text[: limit - 1].rstrip()
    space = cut.rfind(" ")
    # 단어 경계가 너무 앞이면(절반 미만) 통째로 자르는 편이 낫다.
    if space >= limit // 2:
        cut = cut[:space].rstrip()
    return cut + "…"


def build_prompt(*, articles: list[Article]) -> str:
    """요약 프롬프트를 조립한다."""
    lines = [
        "아래 글들을 읽고, **보낼 가치가 있는 것만** 요약한다.",
        "",
        "## 규칙",
        "",
        f"- 최대 {MAX_SUMMARIES}건. **건수를 채우지 않는다.** 가치 있는 글이 2건이면 "
        "2건만 돌려준다. 억지로 채우면 기준이 무너진다.",
        "- 본문을 읽어보니 내용이 없는 글(보도자료 재가공, 제품 홍보, "
        "제목만 그럴듯한 글)은 **제외한다.**",
        f"- headline은 **{HEADLINE_MAX}자 이내**. 카카오톡 메시지 길이 제약이다.",
        "- bullets는 2~3개. 각 한 문장. 글의 핵심 주장과 근거를 담는다.",
        "- why_it_matters는 한 문장. '이게 왜 중요한가'를 백엔드 개발자 관점에서 쓴다.",
        "- **모든 출력은 한국어로 쓴다.** 원문이 영어여도 한국어로 요약한다.",
        "- 고유명사(제품명, 회사명, 기술명)는 원어를 그대로 쓴다.",
        "- index에는 각 글의 [번호]를 쓴다. 제외한 글은 응답에 넣지 않는다.",
        "",
        "## 글",
        "",
    ]

    for index, article in enumerate(articles):
        item = article.ranked.item
        # 본문을 여기서 다시 자르지 않는다. enrich가 BODY_MAX_CHARS로 이미
        # 잘랐고, 손잡이가 두 곳이면 토큰 예산을 추적할 수 없다.
        lines += [
            f"### [{index}] {item.title}",
            f"출처: {item.source}  /  주제: {article.ranked.topic}",
            "",
            article.body,
            "",
            "---",
            "",
        ]

    return "\n".join(lines)


def summarize(*, articles: ArticlesBundle, llm: LLM) -> Briefing:
    """최종 선정과 요약. 0건도 정상 결과다."""
    candidates = articles.articles

    if not candidates:
        return Briefing(
            window_start=articles.window_start,
            window_end=articles.window_end,
            summaries=[],
            considered=0,
        )

    prompt = build_prompt(articles=candidates)
    # 재시도는 llm.parse 안에서 끝난다 (rank.py와 같은 이유).
    sheet, _tokens = llm.parse(
        prompt=prompt,
        output_format=SummarySheet,
        effort=SUMMARIZE_EFFORT,
        max_tokens=SUMMARIZE_MAX_TOKENS,
    )

    summaries: list[Summary] = []
    seen: set[int] = set()

    for draft in sheet.summaries:
        # 범위 밖 번호나 중복 번호를 돌려줄 수 있다. 둘 다 무시하고,
        # 중복은 먼저 나온 것을 쓴다.
        if not (0 <= draft.index < len(candidates)) or draft.index in seen:
            continue
        seen.add(draft.index)

        article = candidates[draft.index]

        # 결정적 가드: LLM 판단과 별개로 점수 하한을 적용한다.
        if article.ranked.score < SCORE_THRESHOLD:
            continue

        summaries.append(Summary(
            article=article,
            # LLM이 상한을 넘겨도 브리핑을 잃지 않는다. shorten 설명 참조.
            headline=shorten(draft.headline),
            bullets=draft.bullets,
            why_it_matters=draft.why_it_matters,
        ))

    # 상한을 넘으면 점수 높은 것부터 남긴다.
    summaries.sort(key=lambda s: s.article.ranked.score, reverse=True)

    return Briefing(
        window_start=articles.window_start,
        window_end=articles.window_end,
        summaries=summaries[:MAX_SUMMARIES],
        considered=len(candidates),
    )


def main() -> None:
    date = datetime.now(timezone.utc).astimezone(KST).date().isoformat()
    store = LocalStore(date=date)

    briefing = summarize(
        articles=store.read("articles", ArticlesBundle),
        llm=AnthropicLLM(require("ANTHROPIC_API_KEY")),
    )
    path = store.write("briefing", briefing)

    print(f"요약 {len(briefing.summaries)}건 / 후보 {briefing.considered}건 → {path}")
    if not briefing.summaries:
        print("  보낼 만한 글이 없다. 이것도 정상 결과다.")

    # 줄인 건수를 센다. 자주 나오면 프롬프트의 "30자 이내"가 안 먹히는
    # 것이고, HEADLINE_MAX 자체를 다시 볼 근거가 된다.
    줄임 = sum(1 for s in briefing.summaries if s.headline.endswith("…"))
    if 줄임:
        print(f"  헤드라인 {줄임}건을 {HEADLINE_MAX}자로 줄였다 "
              f"(프롬프트 지시가 안 먹힌 것이다. 반복되면 상한을 다시 본다)")
    print()
    for summary in briefing.summaries:
        article = summary.article
        mark = "발췌" if article.body_source == "rss_excerpt" else "본문"
        print(f"  {article.ranked.score:3d}  [{mark}] {summary.headline}")
        for bullet in summary.bullets:
            print(f"       - {bullet[:70]}")
        print(f"       → {summary.why_it_matters[:70]}")
        print()


if __name__ == "__main__":
    main()
```

> **설명** — `shorten`이 단어 경계를 보되 "경계가 상한의 절반보다 앞이면
> 통째로 자르는" 예외를 둔 이유: `"가 " + "나"*50`처럼 공백이 맨 앞에만
> 있으면 단어 경계를 따르다가 거의 다 날아간다.
>
> `SCORE_THRESHOLD`를 `RankedItem.score`에 거는 것은 **가중치 적용 후**
> 점수에 거는 것이다(`rank.apply_weight`가 이미 계산해 뒀다). 원점수에
> 걸면 가중치가 무의미해진다.

- [x] **Step 4: 통과를 확인**

```bash
pytest tests/test_summarize.py
```

Expected: `40 passed`. 전체 `337 passed`.

- [x] **Step 5: 실제 10건으로 요약**

```bash
python -m pipeline.summarize
```

**실측 (2026-11-12): 요약 7건 / 후보 10건, 27초.** 헤드라인 19~26자로
전부 상한 안이고 줄임이 0건이었다.

나온 브리핑의 일부:

```
## Sonnet 대신 결정 모델로 비용 98% 절감  (26자)
`100점` · 본문 · Hacker_News_Best
- Amazon은 20개 라벨 중 하나를 고르는 티켓 분류를 Sonnet 4.6에서
  Strands Decider로 바꿔 정확도를 유지하면서 비용을 약 44배 줄였다.
- AppConfig 3단 스위치로 실트래픽에서 두 모델을 병렬 비교했고 롤백은 45초였다.
- JSON 키 순서만 바꿔도 출력 확률이 최대 0.19 달라져 모든 요청을 키 정렬해 보낸다.
> 닫힌 선택지를 고르는 대량 분류라면 LLM 대신 결정 모델로 비용과 지연을
> 크게 줄일 수 있다.

## Netflix 시놉시스 팩트체크 비용 절감  (23자)
`96점` · **발췌** · Netflix_Tech_Blog
- 기존에는 100k 토큰 이상 컨텍스트로 추론 모델을 5회 호출했는데, 확신도
  기반 게이팅으로 어려운 케이스만 추가 검증하도록 바꿨다.
- 비용은 52.4% 줄었고 Recall-Fail은 0.77→0.86, 사람 근거 일치도는 69%→82%.
```

> **Task 18의 판단이 확인됐다.** Netflix 건은 **발췌로 요약했는데도**
> 구체적 수치가 전부 들어왔다(52.4%, 0.77→0.86, 69%→82%). 피드에 전문을
> 담는 소스에서는 발췌 폴백이 품질 저하가 아니다.

- [x] **Step 6: 커밋**

```bash
git add pipeline/summarize.py tests/test_summarize.py \
        pipeline/models.py pipeline/lib/llm.py pipeline/rank.py
git commit -m "feat: 요약 단계 — 임계값 기반 건수, 한국어 출력, 건수 채우기 금지"
```

---

## Task 20: 전송과 실행 이력

보낼 곳이 여러 곳이 될 것이 **이미 정해져 있으므로**(계획 3에서 카카오톡과
슬랙) 전송 대상을 프로토콜로 추상화한다. 계획 1은 터미널 출력 하나만 구현한다.

`notify.py`를 계획 1에 남기는 이유는 **여기에 `runs` 기록이 들어 있기
때문이다.** 그게 없으면 윈도우가 전진하지 않아 매번 같은 구간을 다시
수집한다 — 파이프라인의 핵심 루프가 돌지 않는다.

**Files:**
- Create: `pipeline/lib/sender.py`
- Create: `pipeline/notify.py`
- Create: `tests/test_sender.py`
- Create: `tests/test_notify.py`
- Modify: `tests/fakes.py` (FakeSender, FakeRemoteStore의 save_error)

> **계획에서 고친 것** (테스트 33개 → 41개)
>
> ### 1. 예외 메시지가 거짓말을 했다
>
> 계획의 `AllSendersFailedError`는 이렇게 말한다:
>
> > "전송 이력은 남지 않았으므로 원인을 고친 뒤 그대로 재실행하면 된다"
>
> 그런데 바로 윗줄에서 `record("failed", ...)`로 **실행 기록을 남긴다.**
> 다음 사람이 이 메시지를 믿고 `runs` 테이블을 보면 혼란에 빠진다.
> 정확히는 "`status='failed'` 기록은 남고 전송 이력(`status='sent'`)은
> 갱신되지 않았다"다. 문구를 고치고 `test_실패_메시지가_거짓말하지_않는다`로
> 못 박았다.
>
> ### 2. 저장 실패 경로가 없었다
>
> 계획의 순서는 `센더 전송 → save_articles → record("sent")`다.
> `save_articles`가 터지면 **실행 기록이 남지 않는다.** 그러면 다음 실행이
> `AlreadySent`에 걸리지 않고 **이미 보낸 브리핑을 다시 보낸다.**
>
> 사용자에게 두 번 가는 것이 페이지가 비는 것보다 나쁘다. 전송은 이미
> 성공했으므로, 저장 실패는 `runs.errors`에 `save_articles`로 남기고
> `status='sent'`를 기록한다. 윈도우는 전진한다.
>
> ### 3. "품질 저하"라는 경고 문구를 뺐다
>
> 계획은 발췌 폴백을 `"발췌 폴백 N건 (요약 품질 저하)"`로 알린다. Task 18
> 실측에서 **발췌가 전문인 경우가 많았다**(Netflix 15,633자). 멀쩡한 날에
> 품질 경고가 뜨면 경고를 무시하게 된다 — spec 8.4가 말하는 알림 피로다.
> 문구를 `"발췌로 요약한 글 N건"`으로 바꾸고 **본문 길이를 함께 보여 준다.**
> 판단은 읽는 사람에게 맡긴다.
>
> ### 4. `Sender`를 `runtime_checkable`로 (LLM·RemoteStore와 동일)
>
> 계획의 `sender: Sender = ConsoleSender()`는 타입 주석이라 런타임에
> 아무것도 검사하지 않는다.
>
> ### 5. 막기 전에 센더를 부르지 않는지 테스트했다
>
> 계획에는 `AlreadySentError`가 나는지만 확인하는 테스트가 있었다.
> 센더를 부른 **뒤에** 막으면 막은 의미가 없는데 그걸 확인하지 않았다.

- [x] **Step 1: 전송 대상의 테스트 작성**

`tests/test_sender.py`:

```python
from pipeline.lib.sender import ConsoleSender, Sender, collect_warnings
from pipeline.models import (
    Article,
    Briefing,
    RankedItem,
    RawBundle,
    RawItem,
    SourceError,
    Summary,
)

WINDOW = ("2026-11-09T22:20:00+00:00", "2026-11-10T22:20:00+00:00")


def _summary(index: int = 0, fallback: bool = False) -> Summary:
    return Summary(
        article=Article(
            ranked=RankedItem(
                item=RawItem(
                    source="토스_기술블로그", title=f"원제 {index}",
                    url=f"https://toss.tech/a/{index}",
                    published="2026-11-10T05:30:00+00:00", excerpt="발췌",
                ),
                score=92, reason="이유", topic="backend",
            ),
            body="본문",
            body_source="rss_excerpt" if fallback else "trafilatura",
            fallback_reason="접근 불가 — HTTP 403" if fallback else None,
        ),
        headline=f"헤드라인 {index}",
        bullets=["첫 요점", "둘째 요점"],
        why_it_matters="중요한 이유",
    )


def _briefing(summaries, considered: int = 10) -> Briefing:
    return Briefing(
        window_start=WINDOW[0], window_end=WINDOW[1],
        summaries=summaries, considered=considered,
    )


def _raw(errors=None) -> RawBundle:
    return RawBundle(
        window_start=WINDOW[0], window_end=WINDOW[1], items=[],
        source_counts={"토스_기술블로그": 3},
        errors=errors or [],
    )


# --- 경고 수집 ---

def test_경고가_없으면_빈_목록이다():
    assert collect_warnings(briefing=_briefing([_summary()]), raw=_raw()) == []


def test_발췌_폴백을_경고로_모은다():
    warnings = collect_warnings(
        briefing=_briefing([_summary(0, fallback=True), _summary(1)]),
        raw=_raw(),
    )
    joined = "\n".join(warnings)

    assert "발췌" in joined
    assert "403" in joined


def test_설정_문제_소스를_경고로_모은다():
    """내가 sources.yaml을 고쳐야 하는 것."""
    warnings = collect_warnings(
        briefing=_briefing([_summary()]),
        raw=_raw([SourceError(source="죽은소스", kind="config",
                              message="https://x.com/r HTTP 404")]),
    )
    joined = "\n".join(warnings)

    assert "죽은소스" in joined
    assert "404" in joined


def test_주소_이전을_경고로_모은다():
    warnings = collect_warnings(
        briefing=_briefing([_summary()]),
        raw=_raw([SourceError(source="이전된소스", kind="moved",
                              message="old → new (sources.yaml 갱신)")]),
    )
    assert "이전된소스" in "\n".join(warnings)


def test_일시_실패는_경고로_모으지_않는다():
    """내가 할 일이 없다. 매번 알리면 알림 피로가 생긴다."""
    warnings = collect_warnings(
        briefing=_briefing([_summary()]),
        raw=_raw([SourceError(source="불안정소스", kind="transient",
                              message="HTTP 503")]),
    )
    assert warnings == []


def test_발췌가_길면_품질_저하로_부르지_않는다():
    """2026-11-12 실측: 크롤링이 막힌 소스가 피드에 전문을 담는다
    (Netflix 15,633자). "품질 저하"라고 쓰면 멀쩡한 날에 경고가 뜬다.
    """
    긴발췌 = _summary(0, fallback=True)
    긴발췌 = Summary(
        article=Article(
            ranked=긴발췌.article.ranked,
            body="가" * 5000,
            body_source="rss_excerpt",
            fallback_reason="접근 불가 — HTTP 403",
        ),
        headline=긴발췌.headline,
        bullets=긴발췌.bullets,
        why_it_matters=긴발췌.why_it_matters,
    )
    warnings = collect_warnings(briefing=_briefing([긴발췌]), raw=_raw())

    assert warnings != []                    # 알리기는 한다
    assert "품질 저하" not in "\n".join(warnings)


# --- 터미널 출력 ---

def test_ConsoleSender가_인터페이스를_만족한다():
    sender = ConsoleSender()

    # Sender가 runtime_checkable이라 실제로 확인된다. 타입 주석만 달면
    # 런타임에는 아무것도 검사되지 않는다.
    assert isinstance(sender, Sender)
    assert sender.name == "console"


def test_헤드라인과_요점과_링크를_출력한다(capsys):
    ConsoleSender().send(briefing=_briefing([_summary()]), raw=_raw())
    out = capsys.readouterr().out

    assert "헤드라인 0" in out
    assert "첫 요점" in out
    assert "중요한 이유" in out
    assert "https://toss.tech/a/0" in out


def test_점수와_출처를_출력한다(capsys):
    """튜닝 중에 '왜 이게 뽑혔나'를 보려면 둘 다 필요하다."""
    ConsoleSender().send(briefing=_briefing([_summary()]), raw=_raw())
    out = capsys.readouterr().out

    assert "92" in out
    assert "토스_기술블로그" in out


def test_건수와_후보_수를_출력한다(capsys):
    ConsoleSender().send(briefing=_briefing([_summary(0), _summary(1)]), raw=_raw())
    out = capsys.readouterr().out

    assert "2건" in out
    assert "10" in out


def test_0건이면_그렇게_출력한다(capsys):
    """조용히 끝나면 시스템이 죽은 것과 구분되지 않는다."""
    ConsoleSender().send(briefing=_briefing([], considered=8), raw=_raw())
    out = capsys.readouterr().out

    assert "없" in out
    assert "8" in out


def test_경고를_하단에_출력한다(capsys):
    ConsoleSender().send(
        briefing=_briefing([_summary(0, fallback=True)]),
        raw=_raw([SourceError(source="죽은소스", kind="config", message="HTTP 404")]),
    )
    out = capsys.readouterr().out

    assert "죽은소스" in out
    assert "403" in out


def test_발췌로_온_건을_표시한다(capsys):
    """요약이 얕을 수 있다는 걸 읽는 사람이 알아야 한다."""
    ConsoleSender().send(briefing=_briefing([_summary(0, fallback=True)]), raw=_raw())
    out = capsys.readouterr().out

    assert "발췌" in out
```

- [x] **Step 2: 실패를 확인**

```bash
pytest tests/test_sender.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.sender'`

- [x] **Step 3: 최소 구현 작성**

`pipeline/lib/sender.py`:

```python
"""전송 대상.

보낼 곳이 여러 곳이 될 것이 정해져 있으므로(계획 3에서 카카오톡과 슬랙)
프로토콜로 추상화한다. 계획 1은 ConsoleSender만 구현한다.

계획 3에서 추가될 것:
- KakaoSender  — 텍스트 템플릿 200자, 상위 5건 + "외 N건" + 페이지 버튼
- SlackSender  — 경고 전용. 카카오 토큰이 만료되면 카톡으로는 그 사실을
                 알릴 수 없으므로, 만료가 없는 채널이 하나 필요하다.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from pipeline.lib.timeutil import KST
from pipeline.models import Briefing, RawBundle

TOPIC_MARKS = {
    "AI": "🤖",
    "backend": "⚙️",
    "infra": "🏗️",
    "tooling": "🔧",
}


@runtime_checkable
class Sender(Protocol):
    """브리핑을 어딘가로 내보내는 것.

    runtime_checkable이라 `isinstance(sender, Sender)`로 확인할 수 있다
    (메서드 이름만 본다 — 서명은 보지 않는다).
    """

    name: str

    def send(self, *, briefing: Briefing, raw: RawBundle) -> None:
        ...


def collect_warnings(*, briefing: Briefing, raw: RawBundle) -> list[str]:
    """사람이 조치해야 하는 것만 모은다.

    일시 실패(transient)는 넣지 않는다 — 내가 할 일이 없고, 매번 알리면
    알림 피로가 생겨서 정작 중요한 경고를 무시하게 된다.
    """
    warnings: list[str] = []

    fallbacks = [
        summary for summary in briefing.summaries
        if summary.article.body_source == "rss_excerpt"
    ]
    if fallbacks:
        # "품질 저하"라고 쓰지 않는다. 2026-11-12 실측: 크롤링이 막힌 소스가
        # 피드에 전문을 담는 경우가 많다(Netflix 15,633자). 멀쩡한 날에
        # 품질 경고가 뜨면 경고를 무시하게 된다. 길이를 함께 보여 주고
        # 판단은 읽는 사람에게 맡긴다.
        lines = [f"발췌로 요약한 글 {len(fallbacks)}건:"]
        lines += [
            f"  {summary.article.ranked.item.source} "
            f"({len(summary.article.body):,}자): "
            f"{summary.article.fallback_reason}"
            for summary in fallbacks
        ]
        warnings.append("\n".join(lines))

    config_errors = [error for error in raw.errors if error.kind == "config"]
    if config_errors:
        lines = [f"고쳐야 할 소스 {len(config_errors)}개:"]
        lines += [f"  {error.source}: {error.message}" for error in config_errors]
        warnings.append("\n".join(lines))

    moved = [error for error in raw.errors if error.kind == "moved"]
    if moved:
        lines = [f"주소가 이전된 소스 {len(moved)}개 (sources.yaml 갱신):"]
        lines += [f"  {error.source}: {error.message}" for error in moved]
        warnings.append("\n".join(lines))

    return warnings


class ConsoleSender:
    """터미널에 브리핑을 출력한다.

    계획 1의 유일한 전송 대상이다. 초기 튜닝은 결과를 보면서 프롬프트를
    고치는 일이고, 그건 터미널에서 하는 작업이다.
    """

    name = "console"

    def send(self, *, briefing: Briefing, raw: RawBundle) -> None:
        when = datetime.fromisoformat(briefing.window_end).astimezone(KST)
        count = len(briefing.summaries)

        print()
        print(f"📡 {when.strftime('%m/%d (%a)')} IT 브리핑 · "
              f"{count}건  (후보 {briefing.considered}건)")
        print("=" * 78)

        if count == 0:
            print()
            print(f"  후보 {briefing.considered}건을 봤지만 기준을 넘는 글이 없습니다.")
            print("  조용한 날입니다 — 시스템은 정상입니다.")
        else:
            for position, summary in enumerate(briefing.summaries, start=1):
                item = summary.article.ranked.item
                mark = TOPIC_MARKS.get(summary.article.ranked.topic, "📄")
                # 발췌로 요약한 건은 표시한다. 요약이 얕을 수 있다는 걸
                # 읽는 사람이 알아야 한다.
                출처표시 = (
                    "발췌" if summary.article.body_source == "rss_excerpt" else "본문"
                )

                print()
                print(f"  [{position}] {summary.article.ranked.score:3d}  "
                      f"{mark}  {summary.headline}")
                for bullet in summary.bullets:
                    print(f"           • {bullet}")
                print(f"           왜: {summary.why_it_matters}")
                print(f"           {item.source} · {출처표시}  {item.url}")

        for warning in collect_warnings(briefing=briefing, raw=raw):
            print()
            print("⚠️  " + warning.replace("\n", "\n    "))

        print()
```

> **설명** — `enumerate(..., start=1)`은 0이 아니라 1부터 번호를 센다.
> `datetime.strftime("%m/%d (%a)")`는 "11/10 (Tue)" 형태의 문자열을 만든다.
> `"=" * 78`은 문자열 반복으로 구분선을 만드는 Python 관용구다.
>
> `Sender`를 `Protocol`로 둔 덕분에 `ConsoleSender`가 아무것도 상속하지
> 않는다. 계획 3의 `KakaoSender`도 그렇다. **상속이 없으므로 센더끼리
> 공통 기반 클래스를 통해 엉키지 않는다** — 카톡의 200자 제약이 슬랙
> 코드에 영향을 주는 일이 구조적으로 불가능해진다.
>
> pytest의 `capsys` fixture는 `print` 출력을 가로채
> `capsys.readouterr().out`으로 돌려준다. 출력 함수를 테스트하려고 별도
> 추상화를 만들 필요가 없다.

- [x] **Step 4: 통과를 확인** → `13 passed`

- [x] **Step 5: 전송과 이력의 테스트 작성**

`tests/test_notify.py`:

```python
from datetime import datetime, timezone

import pytest

from pipeline.lib.retry import Permanent
from pipeline.models import (
    Article,
    Briefing,
    RankedBundle,
    RankedItem,
    RawBundle,
    RawItem,
    SourceError,
    Summary,
)
from pipeline.notify import AllSendersFailedError, AlreadySentError, notify
from tests.fakes import FakeRemoteStore, FakeSender

WINDOW_START = datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc)
SENT_AT = datetime(2026, 11, 10, 22, 22, tzinfo=timezone.utc)


def _summary(index: int = 0) -> Summary:
    return Summary(
        article=Article(
            ranked=RankedItem(
                item=RawItem(
                    source="토스_기술블로그", title=f"원제 {index}",
                    url=f"https://toss.tech/a/{index}",
                    published="2026-11-10T05:30:00+00:00", excerpt="발췌",
                ),
                score=85, reason="이유", topic="backend",
            ),
            body="본문", body_source="trafilatura",
        ),
        headline=f"헤드라인 {index}",
        bullets=["요점"],
        why_it_matters="이유",
    )


def _briefing(summaries) -> Briefing:
    return Briefing(
        window_start=WINDOW_START.isoformat(),
        window_end=WINDOW_END.isoformat(),
        summaries=summaries,
        considered=10,
    )


def _raw(item_count: int = 42) -> RawBundle:
    return RawBundle(
        window_start=WINDOW_START.isoformat(),
        window_end=WINDOW_END.isoformat(),
        items=[
            RawItem(
                source="토스_기술블로그", title=f"수집 {i}",
                url=f"https://toss.tech/raw/{i}",
                published="2026-11-10T05:30:00+00:00", excerpt="발췌",
            )
            for i in range(item_count)
        ],
        source_counts={"토스_기술블로그": 3, "조용한소스": 0},
        errors=[SourceError(source="깨진소스", kind="config",
                            message="https://broken.com/r HTTP 404")],
    )


def _ranked(max_score: int | None = 94) -> RankedBundle:
    return RankedBundle(
        window_start=WINDOW_START.isoformat(),
        window_end=WINDOW_END.isoformat(),
        selected=[], all_scores=[], max_score=max_score,
    )


def _notify(briefing, senders=None, store=None, force=False, ranked=None, raw=None):
    remote = store or FakeRemoteStore()
    sent = senders if senders is not None else [FakeSender()]

    notify(
        briefing=briefing,
        ranked=ranked or _ranked(),
        raw=raw or _raw(),
        remote=remote,
        briefing_date="2026-11-10",
        senders=sent,
        force=force,
        now=SENT_AT,
    )
    return remote, sent


# --- 정상 경로 ---

def test_센더로_내보낸다():
    _, senders = _notify(_briefing([_summary()]))
    assert senders[0].calls == 1


def test_실행_이력을_남긴다():
    remote, _ = _notify(_briefing([_summary()]))

    assert len(remote.runs) == 1
    assert remote.runs[0]["published_count"] == 1
    assert remote.runs[0]["window_end"] == WINDOW_END


def test_발행_글을_저장한다():
    remote, _ = _notify(_briefing([_summary()]))

    assert len(remote.saved) == 1
    assert remote.saved[0]["briefing_date"] == "2026-11-10"


def test_소스별_건수를_이력에_남긴다():
    """소스 침묵 감지의 입력이다."""
    remote, _ = _notify(_briefing([_summary()]))
    assert remote.runs[0]["source_counts"] == {"토스_기술블로그": 3, "조용한소스": 0}


def test_에러의_성격까지_이력에_남긴다():
    """계획 3의 소스 경고가 "죽은 소스"와 "불안정한 소스"를 구분하는 근거다."""
    remote, _ = _notify(_briefing([_summary()]))
    assert remote.runs[0]["errors"][0]["kind"] == "config"


def test_수집_후보_최고점수를_이력에_남긴다():
    """0건인 날 화면이 "후보 10건 / 최고 54점 / 기준 60점"을 보여주는 데 쓴다.
    이 셋이 없으면 "기준이 높은가, 소스가 문제인가"를 판단할 수 없다."""
    remote, _ = _notify(_briefing([_summary()]), ranked=_ranked(max_score=54))
    run = remote.runs[0]

    assert run["collected_count"] == 42
    assert run["considered_count"] == 10
    assert run["max_score"] == 54


def test_성공한_실행은_sent_상태와_발송_시각을_남긴다():
    remote, _ = _notify(_briefing([_summary()]))

    assert remote.runs[0]["status"] == "sent"
    assert remote.runs[0]["sent_at"] == SENT_AT


def test_윈도우를_그대로_남긴다():
    """다음 실행의 윈도우 시작점이 된다. 어긋나면 구간이 겹치거나 빈다."""
    remote, _ = _notify(_briefing([_summary()]))

    assert remote.runs[0]["window_start"] == WINDOW_START
    assert remote.runs[0]["window_end"] == WINDOW_END


# --- 0건 ---

def test_0건이어도_내보내고_이력을_남긴다():
    """이력을 남기지 않으면 다음 윈도우가 계속 늘어난다."""
    remote, senders = _notify(_briefing([]))

    assert senders[0].calls == 1
    assert len(remote.runs) == 1
    assert remote.runs[0]["published_count"] == 0


def test_0건이면_글을_저장하지_않는다():
    remote, _ = _notify(_briefing([]))
    assert remote.saved == []


def test_0건이어도_윈도우가_전진한다():
    """파이프라인의 핵심 루프다. 전진하지 않으면 매번 같은 96시간을 다시 본다."""
    remote, _ = _notify(_briefing([]))
    assert remote.last_sent_at() == SENT_AT


# --- 멱등성 ---

def test_이미_보낸_윈도우는_다시_보내지_않는다():
    """cron 중복 실행이나 수동 재실행으로 두 번 오는 것을 막는다."""
    store = FakeRemoteStore(last_sent=WINDOW_END)

    with pytest.raises(AlreadySentError):
        _notify(_briefing([_summary()]), store=store)


def test_이미_보냈으면_센더를_부르지도_않는다():
    """막기만 하고 보내면 막은 의미가 없다."""
    store = FakeRemoteStore(last_sent=WINDOW_END)
    sender = FakeSender()

    with pytest.raises(AlreadySentError):
        _notify(_briefing([_summary()]), store=store, senders=[sender])

    assert sender.calls == 0


def test_더_늦은_발송_이력이_있으면_거부한다():
    later = datetime(2026, 11, 11, tzinfo=timezone.utc)
    with pytest.raises(AlreadySentError):
        _notify(_briefing([_summary()]), store=FakeRemoteStore(last_sent=later))


def test_force면_이미_보냈어도_다시_보낸다():
    store = FakeRemoteStore(last_sent=WINDOW_END)
    _, senders = _notify(_briefing([_summary()]), store=store, force=True)

    assert senders[0].calls == 1


def test_이전_윈도우의_이력은_막지_않는다():
    earlier = datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc)
    _, senders = _notify(_briefing([_summary()]),
                         store=FakeRemoteStore(last_sent=earlier))
    assert senders[0].calls == 1


# --- 센더 실패 ---

def test_센더가_여럿이면_하나가_죽어도_나머지는_보낸다():
    """계획 3에서 카톡 토큰이 만료돼도 슬랙은 가야 한다."""
    broken = FakeSender(name="broken", error=Permanent("HTTP 404"))
    working = FakeSender(name="working")

    remote, _ = _notify(_briefing([_summary()]), senders=[broken, working])

    assert working.calls == 1
    assert len(remote.runs) == 1          # 하나라도 갔으면 기록한다


def test_앞의_센더가_죽어도_뒤의_센더를_부른다():
    """순서에 의존하지 않는다."""
    broken = FakeSender(name="broken", error=Permanent("HTTP 404"))
    working = FakeSender(name="working")

    _notify(_briefing([_summary()]), senders=[broken, working])

    assert broken.calls == 1 and working.calls == 1


def test_하나라도_갔으면_실패한_센더를_이력에_남긴다():
    broken = FakeSender(name="broken", error=Permanent("HTTP 404"))
    remote, _ = _notify(_briefing([_summary()]),
                        senders=[broken, FakeSender(name="working")])

    errors = remote.runs[0]["errors"]
    assert any(error.get("source") == "sender:broken" for error in errors)


def _fail_all():
    """전부 실패하는 센더 둘로 notify를 돌리고 저장소를 돌려준다."""
    remote = FakeRemoteStore()
    senders = [FakeSender(name="a", error=Permanent("404")),
               FakeSender(name="b", error=Permanent("403"))]

    with pytest.raises(AllSendersFailedError) as 잡힘:
        notify(
            briefing=_briefing([_summary()]), ranked=_ranked(), raw=_raw(),
            remote=remote, briefing_date="2026-11-10", senders=senders,
            force=False, now=SENT_AT,
        )
    return remote, 잡힘.value


def test_전부_실패해도_실패_상태로_기록한다():
    """source_counts가 소스 침묵 경고의 유일한 입력이다. 실패한 날이
    기록에서 빠지면 그만큼 경고가 늦어진다."""
    remote, _ = _fail_all()

    assert len(remote.runs) == 1
    assert remote.runs[0]["status"] == "failed"
    assert remote.runs[0]["sent_at"] is None
    assert remote.runs[0]["source_counts"] == {"토스_기술블로그": 3, "조용한소스": 0}


def test_실패_메시지가_거짓말하지_않는다():
    """실행 기록은 status='failed'로 **남는다.** "이력을 남기지 않았다"고
    쓰면 다음 사람이 runs 테이블을 보고 혼란에 빠진다.
    """
    _, 예외 = _fail_all()
    메시지 = str(예외)

    assert "이력은 남지 않" not in 메시지
    assert "재실행" in 메시지


def test_전부_실패하면_글을_저장하지_않는다():
    remote, _ = _fail_all()
    assert remote.saved == []


def test_실패_기록이_재실행을_막지_않는다():
    """last_sent_at이 status='sent'만 보므로 막히지 않아야 한다."""
    remote, _ = _fail_all()

    assert remote.last_sent_at() is None

    # 원인을 고치고 그대로 재실행
    working = FakeSender(name="working")
    notify(
        briefing=_briefing([_summary()]), ranked=_ranked(), raw=_raw(),
        remote=remote, briefing_date="2026-11-10", senders=[working],
        force=False, now=SENT_AT,
    )

    assert working.calls == 1
    assert remote.last_sent_at() == SENT_AT


def test_실패한_센더를_이력의_에러에_남긴다():
    remote, _ = _fail_all()
    names = [error.get("source") for error in remote.runs[0]["errors"]]

    assert "sender:a" in names
    assert "sender:b" in names


def test_센더가_하나도_없으면_거부한다():
    """설정 실수로 조용히 아무 데도 안 보내는 것을 막는다."""
    with pytest.raises(ValueError, match="센더"):
        _notify(_briefing([_summary()]), senders=[])


# --- 저장 실패 ---
#
# 전송은 됐는데 DB 저장이 실패하는 경우. 여기서 예외를 올려 버리면 실행
# 기록이 남지 않고, 재실행이 **이미 보낸 브리핑을 다시 보낸다.**
# 사용자에게 두 번 가는 것이 페이지가 비는 것보다 나쁘다.

def test_저장이_실패해도_실행_기록은_남긴다():
    store = FakeRemoteStore(save_error=RuntimeError("DB 연결 끊김"))
    remote, _ = _notify(_briefing([_summary()]), store=store)

    assert len(remote.runs) == 1
    assert remote.runs[0]["status"] == "sent"


def test_저장_실패를_이력의_에러에_남긴다():
    store = FakeRemoteStore(save_error=RuntimeError("DB 연결 끊김"))
    remote, _ = _notify(_briefing([_summary()]), store=store)

    errors = remote.runs[0]["errors"]
    assert any(error.get("source") == "save_articles" for error in errors)
    assert any("DB 연결 끊김" in error.get("message", "") for error in errors)


def test_저장이_실패해도_윈도우는_전진한다():
    """전진하지 않으면 다음 실행이 같은 브리핑을 또 보낸다."""
    store = FakeRemoteStore(save_error=RuntimeError("DB 연결 끊김"))
    remote, _ = _notify(_briefing([_summary()]), store=store)

    assert remote.last_sent_at() == SENT_AT
```

- [x] **Step 6: 가짜 센더를 `tests/fakes.py`에 추가**

`FakeSender`와, `FakeRemoteStore`에 `save_error`를 추가했다
(전송은 됐는데 DB 저장이 실패하는 경우를 재현한다).

- [x] **Step 7: 실패를 확인**

```bash
pytest tests/test_notify.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.notify'`

- [x] **Step 8: 최소 구현 작성**

`pipeline/notify.py`:

```python
"""04.5 전송: 센더로 내보내고 실행 이력을 남긴다.

순서가 중요하다 — **하나라도 전송에 성공한 뒤에 `status='sent'` 이력을
남긴다.** 거꾸로 하면 전송이 실패했는데 "이미 보냄"으로 기록되어, 원인을
고친 뒤 재실행이 막히고 그날 브리핑이 사라진다.

계획 1의 센더는 ConsoleSender 하나다. 계획 3에서 KakaoSender와
SlackSender가 추가된다.

실행:
  python -m pipeline.notify
  python -m pipeline.notify --force    # 이미 보낸 윈도우를 다시 보낸다
"""

import argparse
from datetime import datetime, timezone

from pipeline.lib.secrets import require
from pipeline.lib.sender import ConsoleSender, Sender
from pipeline.lib.store import LocalStore, RemoteStore, SupabaseStore
from pipeline.lib.timeutil import KST
from pipeline.models import Briefing, RankedBundle, RawBundle


class AlreadySentError(RuntimeError):
    """이 윈도우는 이미 전송됐다. --force로 우회할 수 있다."""


class AllSendersFailedError(RuntimeError):
    """모든 센더가 실패했다.

    `status='failed'` 실행 기록은 **남는다**(소스 침묵 감지의 입력이므로).
    `last_sent_at`이 `status='sent'`만 보기 때문에 재실행은 막히지 않는다.
    """


def notify(
    *,
    briefing: Briefing,
    ranked: RankedBundle,
    raw: RawBundle,
    remote: RemoteStore,
    briefing_date: str,
    senders: list[Sender],
    force: bool = False,
    now: datetime | None = None,
) -> None:
    """센더로 내보내고 이력을 남긴다. 0건도 내보내고, 실패해도 기록한다."""
    if not senders:
        raise ValueError(
            "센더가 하나도 없다. 설정 실수로 아무 데도 보내지 않는 것을 막는다."
        )

    window_start = datetime.fromisoformat(briefing.window_start)
    window_end = datetime.fromisoformat(briefing.window_end)
    moment = now or datetime.now(timezone.utc)

    def record(status: str, sent_at: datetime | None, extra: list[dict]) -> None:
        """실행 이력을 남긴다. 성공·실패 양쪽에서 같은 값을 쓴다."""
        remote.record_run(
            window_start=window_start,
            window_end=window_end,
            status=status,
            sent_at=sent_at,
            collected_count=len(raw.items),
            considered_count=briefing.considered,
            max_score=ranked.max_score,
            published_count=len(briefing.summaries),
            source_counts=raw.source_counts,
            input_tokens=None,
            errors=[error.model_dump() for error in raw.errors] + extra,
        )

    if not force:
        last = remote.last_sent_at()
        if last is not None and last >= window_end:
            # 센더를 부르기 전에 막는다. 부르고 나서 막으면 막은 의미가 없다.
            raise AlreadySentError(
                f"이 윈도우(~{window_end.isoformat()})는 이미 전송됐다 "
                f"(마지막 발송: {last.isoformat()}). "
                f"다시 보내려면 --force를 쓴다."
            )

    # 센더는 서로 독립이다. 계획 3에서 카톡 토큰이 만료돼도 슬랙은 가야 한다.
    delivered: list[str] = []
    failures: list[dict] = []

    for sender in senders:
        try:
            sender.send(briefing=briefing, raw=raw)
            delivered.append(sender.name)
        except Exception as error:  # noqa: BLE001 — 센더 단위로 격리한다
            failures.append({
                "source": f"sender:{sender.name}",
                "kind": "config",
                "message": f"{type(error).__name__}: {error}",
            })

    if not delivered:
        # 아무 데도 못 보냈다. status='failed'로 **기록은 남기고** 예외를 올린다.
        #
        # 기록을 남기는 이유: source_counts가 소스 침묵 경고의 유일한 입력이고,
        # 실패한 날이 빠지면 경고가 그만큼 늦어진다.
        # 재실행이 막히지 않는 이유: last_sent_at이 status='sent'만 보기 때문이다.
        record("failed", None, failures)
        detail = "; ".join(failure["message"] for failure in failures)
        raise AllSendersFailedError(
            f"모든 센더가 실패했다 ({len(senders)}개). "
            f"실행 기록은 status='failed'로 남았고 전송 이력은 갱신되지 않았으므로, "
            f"원인을 고친 뒤 그대로 재실행하면 된다. {detail}"
        )

    if briefing.summaries:
        # 전송은 이미 됐다. 여기서 예외를 올리면 실행 기록이 남지 않고,
        # 재실행이 **이미 보낸 브리핑을 다시 보낸다.** 사용자에게 두 번
        # 가는 것이 페이지가 비는 것보다 나쁘다. 실패를 기록에 남기고 계속한다.
        try:
            remote.save_articles(
                briefing_date=briefing_date,
                summaries=briefing.summaries,
            )
        except Exception as error:  # noqa: BLE001 — 전송은 이미 성공했다
            failures.append({
                "source": "save_articles",
                "kind": "transient",
                "message": f"{type(error).__name__}: {error}",
            })

    # 0건이어도 반드시 남긴다. 남기지 않으면 다음 윈도우가 계속 늘어나
    # 같은 항목을 반복 평가하게 된다.
    record("sent", moment, failures)


def main() -> None:
    parser = argparse.ArgumentParser(description="브리핑 전송")
    parser.add_argument("--force", action="store_true",
                        help="이미 전송한 윈도우를 다시 보낸다")
    args = parser.parse_args()

    date = datetime.now(timezone.utc).astimezone(KST).date().isoformat()
    store = LocalStore(date=date)

    notify(
        briefing=store.read("briefing", Briefing),
        ranked=store.read("ranked", RankedBundle),
        raw=store.read("raw", RawBundle),
        remote=SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SECRET_KEY")),
        briefing_date=date,
        # 계획 3에서 KakaoSender·SlackSender가 이 목록에 추가된다.
        senders=[ConsoleSender()],
        force=args.force,
    )

    print(f"전송 완료 ({date})")


if __name__ == "__main__":
    main()
```

> **설명** — 센더가 여럿일 때 **언제 이력을 남기는지**가 설계 판단이다.
> 전부 실패하면 `status='sent'`를 남기지 않아야 재실행이 되고, 하나라도
> 성공하면 남겨야 재실행이 성공한 센더에 두 번 보내지 않는다. 실패한
> 센더는 `runs.errors`에 `sender:<이름>`으로 기록해 나중에 추적한다.
>
> `except Exception`으로 센더를 감싸는 것은 의도적이다. 여기서는 "어떤
> 이유로든 한 센더가 죽어도 나머지는 보낸다"가 요구사항이므로 분류가
> 필요 없다. 반면 `lib/http.py`나 `enrich.py`에서는 분류가 **행동을
> 바꾸므로**(재시도 여부) 반드시 나눈다.

- [x] **Step 9: 통과를 확인** → `28 passed`. 전체 `378 passed`.

- [x] **Step 10: 실제로 전송하고 DB를 확인한다**

```bash
python -m pipeline.notify
```

**실측 (2026-11-12): 파이프라인의 핵심 루프가 닫혔다.**

| | 실행 전 | 실행 후 |
|---|---|---|
| `last_sent_at` | `None` | `2026-11-12 06:12:17+00:00` |
| `recent_headlines(14일)` | 0건 | **7건** |

`runs` 기록:

```
status             sent
sent_at            2026-11-12T06:12:17+00:00
window_start       2026-11-07T16:20:25+00:00
window_end         2026-11-11T16:20:25+00:00
collected_count    240
considered_count   10
max_score          100
published_count    7
source_counts      소스 45개
errors             0건
input_tokens       None        ← 계획 3에서 연결한다
```

`articles` 7건, `article_bodies` 7건(trafilatura 6 · rss_excerpt 1).

멱등성도 실제로 확인했다 — 같은 윈도우로 재실행하니 센더를 부르지 않고 막혔다:

```
AlreadySentError: 이 윈도우(~2026-11-11T16:20:25+00:00)는 이미 전송됐다
(마지막 발송: 2026-11-12T06:12:17+00:00). 다시 보내려면 --force를 쓴다.
```

> **이 실행이 Task 16의 빈칸을 메웠다.** `recent_headlines`가 0건이라
> 중복 판정 섹션이 프롬프트에서 생략되고 있었는데, 이제 7건이 들어 있어
> **다음 채점부터 같은 사건 중복 판정이 실제로 돈다.**
>
> 그리고 윈도우가 전진했으므로 다음 수집은 96시간이 아니라 "마지막 발송
> 이후"가 된다 — 설계한 루프가 처음으로 제대로 돌게 된다.

- [x] **Step 11: 커밋**

```bash
git add pipeline/lib/sender.py pipeline/notify.py tests/fakes.py \
        tests/test_sender.py tests/test_notify.py
git commit -m "feat: 전송 — Sender 프로토콜, 터미널 출력, 센더별 격리, 실행 이력"
```

---

## Task 21: 중간 산출물 정리

스펙 7.5의 "`data/` 90일 경과분 삭제" 항목이다. 날짜 디렉터리가 무한
증식하는 것을 막는다.

**Files:**
- Create: `pipeline/prune.py`
- Create: `tests/test_prune.py`

> **계획에서 고친 것** (테스트 5개 → 18개)
>
> ### 1. 삭제 경로가 테스트되지 않았다
>
> 계획은 `expired_dirs`(판단)만 테스트하고 `shutil.rmtree`를 부르는
> `main()`은 테스트하지 않았다. **되돌릴 수 없는 작업에서 가장 중요한
> 부분이 빠져 있었다.**
>
> `prune(root, *, today, dry_run)`으로 분리해 `tmp_path`로 실제 삭제를
> 테스트한다 — 오래된 것은 지우고, 시드는 남고, dry_run은 아무것도 지우지
> 않고, 파일은 건드리지 않는지.
>
> ### 2. `"20260101"` 디렉터리를 지울 수 있었다
>
> **Python 3.11부터 `date.fromisoformat`이 대시 없는 기본 ISO 형식도
> 받는다.** `date.fromisoformat("20260101")`이 2026-01-01로 파싱된다.
>
> 우리는 항상 `YYYY-MM-DD`로 만들므로 그 형태가 아닌 이름은 **우리가 만든
> 것이 아니다.** 그런데 계획의 코드는 파싱만 성공하면 지운다. 왕복 비교
> (`when.isoformat() != name`)로 막았다. 되돌릴 수 없는 삭제라 좁게 잡는다.
>
> ### 3. 출력이 파일시스템 순서에 달려 있었다
>
> `expired_dirs`가 입력 순서로 반환해서, `Path.iterdir()`의 순서에 따라 같은
> 상태에서 다른 목록이 나온다. 로그를 비교할 수 없다. 정렬해 돌려준다.

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_prune.py`:

```python
from datetime import date

from pipeline.prune import RETENTION_DAYS, SEED_DIR, expired_dirs, prune

TODAY = date(2026, 11, 10)


def _old(days: int) -> str:
    """오늘로부터 days일 전의 디렉터리 이름."""
    return date.fromordinal(TODAY.toordinal() - days).isoformat()


# --- 대상 선별 ---

def test_보존_기간을_넘긴_디렉터리를_고른다():
    names = ["2026-11-09", "2026-08-01", "2026-01-01"]
    assert expired_dirs(names, today=TODAY) == ["2026-01-01", "2026-08-01"]


def test_결과가_정렬돼_있다():
    """`Path.iterdir()`의 순서는 파일시스템에 달려 있다. 출력이 입력 순서를
    따르면 같은 상태에서 다른 목록이 나와 로그를 비교할 수 없다.
    """
    뒤섞음 = ["2026-01-01", "2026-05-05", "2026-03-03"]
    assert expired_dirs(뒤섞음, today=TODAY) == sorted(뒤섞음)


def test_경계일은_남긴다():
    assert expired_dirs([_old(RETENTION_DAYS)], today=TODAY) == []


def test_경계_하루_전은_지운다():
    assert expired_dirs([_old(RETENTION_DAYS + 1)], today=TODAY) != []


def test_오늘_디렉터리는_남긴다():
    assert expired_dirs([TODAY.isoformat()], today=TODAY) == []


def test_시드_디렉터리는_절대_지우지_않는다():
    """다시 만들 수 없는 데이터다."""
    assert expired_dirs([SEED_DIR], today=date(2030, 1, 1)) == []


def test_날짜가_아닌_이름은_건너뛴다():
    assert expired_dirs(["backup", ".DS_Store"], today=TODAY) == []


def test_날짜처럼_보이지만_아닌_이름도_건너뛴다():
    assert expired_dirs(["2026-13-99", "2026-11", "20260101"], today=TODAY) == []


def test_빈_목록도_처리한다():
    assert expired_dirs([], today=TODAY) == []


# --- 실제 삭제 ---
#
# 계획에는 `main()`만 있어 **삭제 경로가 테스트되지 않았다.** 되돌릴 수 없는
# 작업이라 여기가 가장 중요하다.

def _make(root, name: str, 내용: str = "x") -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "raw.json").write_text(내용, encoding="utf-8")


def test_오래된_디렉터리를_지운다(tmp_path):
    _make(tmp_path, _old(RETENTION_DAYS + 10))
    _make(tmp_path, TODAY.isoformat())

    지움 = prune(tmp_path, today=TODAY, dry_run=False)

    assert 지움 == [_old(RETENTION_DAYS + 10)]
    assert not (tmp_path / _old(RETENTION_DAYS + 10)).exists()
    assert (tmp_path / TODAY.isoformat()).exists()


def test_dry_run은_아무것도_지우지_않는다(tmp_path):
    이름 = _old(RETENTION_DAYS + 10)
    _make(tmp_path, 이름)

    대상 = prune(tmp_path, today=TODAY, dry_run=True)

    assert 대상 == [이름]
    assert (tmp_path / 이름).exists()        # 그대로 있다


def test_시드는_오래돼도_남는다(tmp_path):
    """다시 만들 수 없다. 이 테스트가 깨지면 되돌릴 수 없는 손실이다."""
    _make(tmp_path, SEED_DIR, 내용="시드 1923건")
    _make(tmp_path, _old(RETENTION_DAYS + 10))

    prune(tmp_path, today=date(2030, 1, 1), dry_run=False)

    assert (tmp_path / SEED_DIR / "raw.json").read_text(encoding="utf-8") == "시드 1923건"


def test_날짜가_아닌_디렉터리는_남는다(tmp_path):
    _make(tmp_path, "backup")
    prune(tmp_path, today=date(2030, 1, 1), dry_run=False)

    assert (tmp_path / "backup").exists()


def test_파일은_건드리지_않는다(tmp_path):
    """root 바로 아래의 파일은 날짜 이름이어도 디렉터리가 아니다."""
    (tmp_path / "2026-01-01").write_text("파일이다", encoding="utf-8")

    지움 = prune(tmp_path, today=TODAY, dry_run=False)

    assert 지움 == []
    assert (tmp_path / "2026-01-01").exists()


def test_root가_없으면_조용히_끝난다(tmp_path):
    assert prune(tmp_path / "없는디렉터리", today=TODAY, dry_run=False) == []


def test_지울_것이_없으면_빈_목록이다(tmp_path):
    _make(tmp_path, TODAY.isoformat())
    assert prune(tmp_path, today=TODAY, dry_run=False) == []


def test_여러_개를_한_번에_지운다(tmp_path):
    이름들 = [_old(RETENTION_DAYS + n) for n in (1, 50, 200)]
    for 이름 in 이름들:
        _make(tmp_path, 이름)

    지움 = prune(tmp_path, today=TODAY, dry_run=False)

    assert sorted(지움) == sorted(이름들)
    assert list(tmp_path.iterdir()) == []


def test_보존_기간이_90일이다():
    """스펙 7.5의 값이다. 바꾸려면 스펙도 같이 고친다."""
    assert RETENTION_DAYS == 90
```

- [x] **Step 2: 실패를 확인**

```bash
pytest tests/test_prune.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.prune'`

- [x] **Step 3: 최소 구현 작성**

`pipeline/prune.py`:

```python
"""중간 산출물 정리: data/의 오래된 날짜 디렉터리를 지운다.

스펙 7.5의 "`data/` 90일 경과분 삭제" 항목이다. 날짜 디렉터리가 무한
증식하는 것을 막는다.

**되돌릴 수 없는 작업이다.** 그래서 지우는 판단(`expired_dirs`)과 지우는
행위(`prune`)를 분리해 양쪽을 테스트한다. `main()`은 배선과 출력만 맡는다.

지우지 않는 것:
- `_seed` — RSS에서 다시 얻을 수 없다(Task 14).
- 날짜 형식이 아닌 이름 — 우리가 만든 것이 아니다.
- 파일 — 날짜 이름이어도 디렉터리가 아니면 건드리지 않는다.
- Supabase와 `docs/data/` — 영구 보관이다(스펙 7.5).

실행:
  python -m pipeline.prune --dry-run   # 지울 목록만 본다
  python -m pipeline.prune             # 실제로 지운다
"""

import argparse
import shutil
from datetime import date
from pathlib import Path

from pipeline.lib.store import DEFAULT_ROOT
from pipeline.seed import SEED_DIR

RETENTION_DAYS = 90


def expired_dirs(names: list[str], *, today: date) -> list[str]:
    """보존 기간을 넘긴 날짜 디렉터리 이름을 **정렬해** 돌려준다.

    정렬하는 이유: `Path.iterdir()`의 순서는 파일시스템에 달려 있다.
    출력이 그 순서를 따르면 같은 상태에서 다른 목록이 나와 로그를 비교할 수 없다.
    """
    cutoff = today.toordinal() - RETENTION_DAYS
    expired: list[str] = []

    for name in names:
        # 시드는 RSS에서 다시 얻을 수 없다. 어떤 경우에도 지우지 않는다.
        # (날짜 형식이 아니라 아래에서도 걸리지만, 의도를 코드에 남긴다.)
        if name == SEED_DIR:
            continue
        try:
            when = date.fromisoformat(name)
        except ValueError:
            # 날짜 형식이 아닌 디렉터리는 건드리지 않는다.
            continue
        # **왕복 비교가 필요하다.** Python 3.11부터 `fromisoformat`이 대시 없는
        # 기본 ISO 형식도 받는다 — `"20260101"`이 2026-01-01로 파싱된다.
        # 우리는 항상 `YYYY-MM-DD`로 만들므로, 그 형태가 아닌 이름은 우리가
        # 만든 것이 아니다. 되돌릴 수 없는 삭제라 좁게 잡는다.
        if when.isoformat() != name:
            continue
        if when.toordinal() < cutoff:
            expired.append(name)

    return sorted(expired)


def prune(root: Path, *, today: date, dry_run: bool) -> list[str]:
    """`root` 아래의 만료된 날짜 디렉터리를 지운다.

    지운(또는 dry_run이면 지울) 이름을 돌려준다. `root`가 없으면 빈 목록이다.
    """
    if not root.exists():
        return []

    # 디렉터리만 본다. 날짜 이름의 파일이 있어도 건드리지 않는다.
    names = [entry.name for entry in root.iterdir() if entry.is_dir()]
    targets = expired_dirs(names, today=today)

    if not dry_run:
        for name in targets:
            # shutil.rmtree는 디렉터리와 그 안의 모든 것을 지운다.
            shutil.rmtree(root / name)

    return targets


def main() -> None:
    parser = argparse.ArgumentParser(description="오래된 중간 산출물 정리")
    parser.add_argument("--dry-run", action="store_true", help="지울 목록만 출력")
    args = parser.parse_args()

    root = DEFAULT_ROOT
    if not root.exists():
        print(f"{root}가 없다. 정리할 것이 없다.")
        return

    targets = prune(root, today=date.today(), dry_run=args.dry_run)

    if not targets:
        print(f"보존 기간({RETENTION_DAYS}일)을 넘긴 디렉터리가 없다.")
        return

    표시 = "지울 대상" if args.dry_run else "삭제"
    for name in targets:
        print(f"[{표시}] {root / name}")

    if args.dry_run:
        print()
        print(f"{len(targets)}개가 대상이다. --dry-run 없이 실행하면 삭제된다.")
    else:
        print()
        print(f"{len(targets)}개를 삭제했다. (`{SEED_DIR}`는 보호된다)")


if __name__ == "__main__":
    main()
```

> **설명** — `date.toordinal()`은 날짜를 "서력 1년 1월 1일부터의 일수"인
> 정수로 바꾼다. 날짜 차이를 정수 비교로 처리할 수 있어 월말·윤년 계산이
> 필요 없다. `Path.iterdir()`는 디렉터리 안의 항목을 순회한다.
>
> `entry.is_dir()`로 걸러내는 것이 중요하다. `data/2026-01-01`이라는
> **파일**이 있어도 `rmtree`를 부르면 안 된다.

- [x] **Step 4: 통과를 확인**

```bash
pytest tests/test_prune.py
```

Expected: `18 passed`. 전체 `396 passed`.

- [x] **Step 5: 실제로 확인**

```bash
python -m pipeline.prune --dry-run
```

처음에는 아무것도 없었다(디렉터리가 하루·이틀 된 것들이라 정상):

```
보존 기간(90일)을 넘긴 디렉터리가 없다.
```

`main()`의 배선(`DEFAULT_ROOT`)까지 확인하려고 **가짜 옛 디렉터리로 실제
삭제를 시험했다** (2026-11-12):

```
$ mkdir -p data/2020-01-01 && echo "지워질 것" > data/2020-01-01/raw.json

$ python -m pipeline.prune --dry-run
[지울 대상] data/2020-01-01
1개가 대상이다. --dry-run 없이 실행하면 삭제된다.
   → data/2020-01-01 그대로 있음

$ python -m pipeline.prune
[삭제] data/2020-01-01
1개를 삭제했다. (`_seed`는 보호된다)

$ ls data/
2026-11-11  2026-11-12  _seed
```

**시드 체크섬이 Task 14의 백업과 동일했다**(`6eabe61b3120003e`) — 보호가
실제로 작동한다.

- [x] **Step 6: 커밋**

```bash
git add pipeline/prune.py tests/test_prune.py
git commit -m "feat: 중간 산출물 90일 정리 (시드는 보호)"
```

---

## Task 22: 엔드투엔드 검증과 사용 문서

**Files:**
- Create: `README.md`

- [ ] **Step 1: 전체 테스트를 통과하는지 확인**

```bash
pytest
```

Expected: 모든 테스트 통과, 실패 0. (대략 130개 전후)

- [ ] **Step 2: 파이프라인을 처음부터 끝까지 순차 실행**

각 단계의 출력을 **반드시 눈으로 확인하고** 다음 단계로 넘어간다.

```bash
python -m pipeline.collect
```

Expected: `수집 N건 → data/YYYY-MM-DD/raw.json`, 소스별 건수 목록. 최초 실행이면 윈도우가 96시간이라 수십~수백 건.

```bash
python -m pipeline.rank
```

Expected: `채점 N건 → 선별 10건 → ...`, 선별된 10건의 점수·주제·제목·이유.

**여기서 선별 결과가 납득되지 않으면 멈춘다.** `config/interests.md`를 고치고 `python -m pipeline.rank`를 다시 돌린다 (수집은 재실행하지 않는다 — 이게 단계별 구조의 이득이다).

```bash
python -m pipeline.enrich
```

Expected: `본문 확보 10건`, 각 건의 글자 수. `[발췌]` 표시가 절반을 넘으면 본문 추출이 잘 안 되는 것이므로 어떤 소스에서 실패하는지 본다.

```bash
python -m pipeline.summarize
```

Expected: `요약 N건 / 후보 10건`, 헤드라인과 요점.

**요약 품질이 납득되지 않으면 멈춘다.** `pipeline/summarize.py`의 `build_prompt`를 고치고 `python -m pipeline.summarize`만 다시 돌린다.

```bash
python -m pipeline.notify
```

Expected: 터미널에 브리핑이 출력되고 마지막에 `전송 완료 (YYYY-MM-DD)`

- [ ] **Step 3: 출력을 실제로 읽어본다**

이게 계획 1의 결과물이다. 확인 항목:

- 헤드라인이 **30자 안에서 내용을 전달하는가** (카카오톡 제약이므로 여기서 확인해야 한다)
- 요점 2~3개가 글의 핵심을 담는가, 아니면 제목 보강 수준인가
- `왜:` 한 줄이 "그래서 뭐"에 답하는가
- 점수와 출처를 보고 **"이게 왜 뽑혔는지" 납득되는가**
- 하단 경고에 발췌 폴백·죽은 소스가 제대로 나오는가

납득이 안 되면 **계획 2로 넘어가지 않는다.** `config/interests.md`와 `pipeline/summarize.py`의 프롬프트를 고치고 해당 단계만 재실행한다.

- [ ] **Step 4: 멱등성을 확인**

```bash
python -m pipeline.notify
```

Expected: `AlreadySentError` — "이 윈도우는 이미 전송됐다 ... --force를 쓴다"

```bash
python -m pipeline.notify --force
```

Expected: 브리핑이 한 번 더 출력된다.

- [ ] **Step 5: Supabase에 데이터가 들어갔는지 확인**

SQL Editor에서:

```sql
select briefing_date, count(*) as 건수 from public.articles group by 1 order by 1 desc;
select sent_at, published_count, source_counts from public.runs order by sent_at desc limit 5;
select count(*) as 본문_건수 from public.article_bodies;
```

Expected: `articles`에 발행 건수, `runs`에 실행 이력, `article_bodies`에 `articles`와 같은 건수.

**`article_bodies`의 건수가 `articles`보다 적으면** 본문 저장이 누락된 것이므로 Phase 3의 RAG 재료가 빠진다. `SupabaseStore.save_articles`를 확인한다.

- [ ] **Step 6: 두 번째 실행에서 중복이 걸러지는지 확인**

```bash
python -m pipeline.collect
```

Expected: 윈도우가 "마지막 발송 이후"로 좁아져 수집 건수가 크게 줄어든다. 앞서 발행한 글은 `known_urls`로 걸러진다.

- [ ] **Step 7: 에러 분류가 실제로 작동하는지 확인**

분류는 **일부러 깨뜨려봐야** 검증된다. 둘 다 원복이 쉽다.

**7-1. 죽은 소스가 `[설정]`으로 나오는지**

`config/sources.yaml`에 일부러 없는 주소를 하나 추가한다.

```yaml
  - name: 테스트_죽은소스
    url: https://example.com/this-feed-does-not-exist.xml
    kind: rss
    weight: 1.0
    lang: ko
    enabled: true
```

```bash
python scripts/check_feeds.py
```

Expected: `[설정] 테스트_죽은소스  https://example.com/... HTTP 404`

**`[일시]`로 나오면 분류가 틀렸다.** 404는 영구 실패여야 한다.

```bash
python -m pipeline.collect
```

Expected: 출력 마지막에 `[설정] 테스트_죽은소스: ... HTTP 404`, 그리고 **나머지 소스는 정상 수집**된다.

확인 후 `sources.yaml`에서 그 블록을 지운다.

**7-2. 본문을 못 가져오는 소스가 폴백되는지**

`config/sources.yaml`의 소스 하나에서 **RSS는 살아있지만 본문 페이지가 봇을 차단하는** 경우를 재현하기는 어렵다. 대신 `data/<날짜>/ranked.json`을 열어 `selected` 중 한 건의 `url`을 없는 주소로 바꾼 뒤 본문 단계만 다시 돌린다.

```bash
python -m pipeline.enrich
```

Expected: 그 건이 `[발췌]`로 표시되고, 하단 경고에 `접근 불가 — ... HTTP 404`가 나온다. **나머지 건은 정상으로 처리된다.**

재시도로 몇 초 멈추면 안 된다 — 404는 `Permanent`이므로 1회로 끝나야 한다.

확인 후 `python -m pipeline.rank`를 다시 돌려 `ranked.json`을 원복한다.

- [ ] **Step 8: `README.md` 작성**

````markdown
# 토픽 컬럼 자동화

매일 아침 IT 토픽을 수집·선별·요약해서 카카오톡으로 받는다.

- 설계: `docs/superpowers/specs/2026-11-10-it-column-automation-design.md`
- 계획 1 (현재): 파이프라인 — 수집·선별·요약, 결과는 터미널
- 계획 2 (예정): 웹페이지 + 좋아요·클릭
- 계획 3 (예정): 카카오톡 전송 + 슬랙 경고 + 경고 장치 + GitHub Actions

## 준비

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env     # 값을 채운다
```

## 매일 실행

```bash
python -m pipeline.collect      # 수집  → data/<날짜>/raw.json
python -m pipeline.rank         # 선별  → ranked.json
python -m pipeline.enrich       # 본문  → articles.json
python -m pipeline.summarize    # 요약  → briefing.json
python -m pipeline.notify       # 터미널 출력 + 발행 이력 기록
```

각 단계는 **단독 재실행이 가능하다.** 요약 프롬프트를 고쳤으면
`python -m pipeline.summarize`만 다시 돌린다 — 수집과 선별 비용이 들지 않는다.

## 품질 튜닝

```bash
python -m pipeline.evaluate --limit 40
```

시드 데이터로 선별을 돌려 결과를 표로 본다. 입력 표본이 고정이라
`config/interests.md` 변경 효과만 비교된다.

- 상위권에 보도자료·홍보 글이 있으면 → `interests.md`의 "낮게 평가"에 패턴 추가
- 하위권에 읽고 싶은 글이 있으면 → "높게 평가"에 특징 추가

## 점검

```bash
pytest                              # 전체 테스트
python scripts/check_feeds.py       # 소스 피드 생존 확인
python scripts/smoke_supabase.py    # DB 연결·권한 확인
python scripts/smoke_llm.py         # Claude API 확인
python -m pipeline.prune --dry-run  # 정리 대상 확인
```

## 알아둘 것

- **수집 윈도우는 "마지막 발송 이후"**다 (상한 96시간). 주말을 쉬면 월요일이
  자동으로 72시간이 되어 주말 해외 콘텐츠가 들어온다.
- **건수는 고정이 아니다.** 점수 임계값(60)을 넘는 것만 보내므로 2건인 날도
  0건인 날도 정상이다. 0건이어도 "조용한 날"이라고 출력된다.
- **`notify`를 건너뛰면 안 된다.** 여기서 `runs`를 기록하고, 그게 다음 실행의
  수집 윈도우 시작점이 된다. 안 돌리면 같은 구간을 계속 다시 수집한다.
- **같은 윈도우는 두 번 보내지 않는다.** 다시 보내려면 `--force`.
- **본문은 Supabase의 `article_bodies`에만 있다.** 리포지토리에 커밋하지 않고
  공개 페이지에서도 읽히지 않는다. Phase 3의 RAG 재료다.
- **`data/_seed/raw.json`은 지우지 않는다.** RSS는 과거를 제공하지 않으므로
  다시 만들 수 없다. `~/briefing-seed-backup/`에 백업이 있다.
````

- [ ] **Step 9: 커밋**

```bash
git add README.md
git commit -m "docs: README — 실행 방법과 튜닝 절차"
```

---

## 완료 조건

- [ ] `pytest`가 전부 통과한다
- [ ] 파이프라인 5단계를 순차 실행하면 터미널에 브리핑이 출력된다
- [ ] 출력된 헤드라인이 30자 안에서 내용을 전달한다 (카카오톡 제약 선검증)
- [ ] 출력의 점수·출처·판단 이유를 보고 "왜 뽑혔는지" 납득된다
- [ ] 같은 윈도우를 두 번 보내려 하면 거부된다
- [ ] Supabase의 `articles`와 `article_bodies` 건수가 일치한다
- [ ] anon 키로 `article_bodies`를 읽으면 권한 거부가 난다
- [ ] 두 번째 수집에서 윈도우가 좁아지고 기존 글이 걸러진다
- [ ] `python -m pipeline.evaluate`의 상위 10건 중 8건 이상이 "읽고 싶다"
- [ ] `check_feeds.py` 출력에서 `[설정]`과 `[일시]`가 구분되어 나온다
- [ ] `ranked.json`의 URL을 없는 주소로 바꾸고 `enrich`를 돌리면 **재시도 없이** 발췌로 폴백되고, 그 이유가 경고에 나온다
- [ ] 센더를 빈 목록으로 주면 `notify`가 거부한다 (조용히 아무 데도 안 보내는 것 방지)
- [ ] `runs` 테이블의 `errors`에 `kind`가 들어 있다
- [ ] `smoke_supabase.py`의 5단계가 "키는 새지 않았다"로 끝난다
- [ ] `pytest tests/test_timeutil.py`의 발송 요일 테스트 2개가 통과한다 (cron 한 칸 밀림 방지)

---

## 다음 계획

**계획 2 (웹페이지):** `pipeline/render.py` + Vite·React·Tailwind SPA + 좋아요·클릭 저장. 끝나면 공개 URL이 생기고 폰에서 읽을 수 있다. 카카오톡의 "전체 보기" 버튼이 가리킬 곳이 생기므로 계획 3보다 먼저 와야 한다.

**계획 3 (전달과 자동화):** `Sender` 목록에 둘을 추가하고 자동화한다.

- **`KakaoSender`** — 토큰 최초 인증, 매일 갱신(`refresh_token_expires_in` 저장), 텍스트 템플릿 200자 안에 상위 5건 + "외 N건" + 페이지 버튼
- **`SlackSender`** — **경고 전용이다.** 브리핑 전문을 보내지 않는다(페이지가 그 일을 한다). 카카오 토큰이 만료되면 카톡으로는 그 사실을 알릴 수 없으므로, **만료가 없는 채널이 하나 필요하다.** `collect_warnings`의 결과와 `lib/guard.py`의 경고가 여기로 간다
- **`lib/guard.py`** — 토큰 만료 14일 전, 소스 3일 연속 0건, 크레딧 조기 소진
- **GitHub Actions 워크플로** + `prune.py`

끝나면 매일 아침 자동으로 카톡이 오고, 시스템이 조용히 죽지 않는다.

### 계획 3에서 메워야 할 것 (의도적으로 남긴 구멍)

**`runs.input_tokens`가 항상 `NULL`이다.** `notify`가 `input_tokens=None`을 넣는다.
`AnthropicLLM.parse`는 입력 토큰 수를 돌려주지만 `rank`와 `summarize`가 그 값을
버린다(`_tokens`). 지금은 쓰는 곳이 없어서 배선하지 않았다.

계획 3의 크레딧 소진 가드가 이 값을 쓰므로 그때 다음을 한다.

- `RankedBundle`과 `Briefing`에 `input_tokens: int | None` 필드 추가
- `rank`/`summarize`가 `llm.parse`의 두 번째 반환값을 번들에 담기
- `notify`가 두 번들의 합을 `record_run`에 전달

스키마 컬럼은 이미 있으므로 마이그레이션은 필요 없다.
