# 브리핑 파이프라인 + 슬랙 전송 구현 계획 (Phase 1 / 계획 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로컬에서 명령 몇 개를 순서대로 실행하면 IT 토픽이 수집·선별·요약되어 슬랙으로 도착한다.

**Architecture:** 단계별 독립 실행 파이프라인. 각 단계가 `data/YYYY-MM-DD/`에 JSON을 떨어뜨리고 다음 단계가 그것을 입력으로 읽는다. 어느 단계든 단독 재실행이 가능하므로 프롬프트 튜닝 비용이 낮다. 상태(실행 이력·발행 이력·본문)는 Supabase, 중간 산출물은 로컬 파일.

**Tech Stack:** Python 3.12, feedparser(RSS 파싱), trafilatura(본문 추출), httpx(HTTP), anthropic(Claude API), supabase(DB), PyYAML, pydantic(구조화된 출력 검증), pytest.

**설계 스펙:** `docs/superpowers/specs/2026-11-10-it-column-automation-design.md`

---

## 스펙에서 변경된 두 가지

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
| `pipeline/lib/secrets.py` | 환경변수 접근 단일 통로 |
| `pipeline/lib/store.py` | `LocalStore`(JSON 파일) + `RemoteStore`(Supabase) |
| `pipeline/lib/llm.py` | Claude API 래퍼 (주입 가능 → 테스트에서 교체) |
| `pipeline/lib/slack.py` | 슬랙 Block Kit 메시지 조립 + 전송 |
| `pipeline/collect.py` | 윈도우 내 수집 → `raw.json` |
| `pipeline/seed.py` | 1회성 시드 수집 (윈도우 무제한) |
| `pipeline/rank.py` | 선별 채점 → `ranked.json` |
| `pipeline/evaluate.py` | 선별 품질 비교 (운영 비포함) |
| `pipeline/enrich.py` | 본문 확보 → `articles.json` |
| `pipeline/summarize.py` | 임계값 + 요약 → `briefing.json` |
| `pipeline/notify.py` | 슬랙 전송 + 실행 이력 기록 |
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
    "anthropic>=1.0.0",        # Claude API 공식 SDK
    "supabase>=2.15.0",        # Supabase 클라이언트
    "PyYAML>=6.0.2",           # sources.yaml 읽기
    "pydantic>=2.11.0",        # LLM 구조화된 출력 검증
    "python-dotenv>=1.0.1",    # 로컬 .env 로딩
]

[project.optional-dependencies]
dev = ["pytest>=8.3.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
# -q: 간결한 출력. --strict-markers: 오타난 마커를 에러로
addopts = "-q --strict-markers"
```

> **설명** — `pyproject.toml`은 Python 프로젝트의 표준 설정 파일이다. `[project]`에 의존성을, `[tool.<도구명>]`에 각 도구 설정을 담는다. `>=`로 최소 버전만 지정하면 설치 시 최신 호환 버전이 들어온다.

- [ ] **Step 2: `.env.example` 작성**

실제 비밀값은 `.env`에 넣고 커밋하지 않는다. `.env.example`은 "어떤 키가 필요한지"만 알려주는 문서다.

```bash
# Claude API — Max 크레딧이 연결된 Console 조직에서 발급한 키여야 한다
ANTHROPIC_API_KEY=sk-ant-...

# Supabase
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...

# 슬랙 Incoming Webhook
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

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
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Expected: `2 passed`

> **설명** — `python -m venv .venv`는 이 프로젝트만의 격리된 패키지 디렉터리를 만든다. `pip install -e ".[dev]"`의 `-e`는 "editable 설치"로, 소스를 고치면 재설치 없이 반영된다. `[dev]`는 위에서 정의한 `optional-dependencies`의 dev 묶음을 함께 설치한다.

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
    compute_window,
    to_utc_iso,
)


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

Expected: `12 passed`

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/timeutil.py tests/test_timeutil.py
git commit -m "feat: 시각 정규화와 수집 윈도우 계산 (마지막 발송 이후, 상한 96h)"
```

---

## Task 4: 데이터 계약

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


class SourceError(Contract):
    source: str
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


# --- 03 본문 ---

class Article(Contract):
    ranked: RankedItem
    body: str
    body_source: BodySource


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

Expected: `11 passed`

- [ ] **Step 5: sanity 테스트 삭제 후 전체 실행**

```bash
rm tests/test_sanity.py
pytest
```

Expected: `31 passed` (urls 8 + timeutil 12 + models 11)

- [ ] **Step 6: 커밋**

```bash
git add pipeline/models.py tests/test_models.py
git rm tests/test_sanity.py
git commit -m "feat: 단계 간 데이터 계약 (pydantic, 불변, 미정의 키 거부)"
```

---

## Task 5: 환경변수 접근

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

## Task 6: 로컬 저장소 (중간 산출물)

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
- RemoteStore: 실행 이력·발행 이력·본문 (Supabase) — Task 8에서 추가
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

## Task 7: Supabase 스키마

SQL이므로 단위 테스트가 아니라 **실제 적용 후 권한 검증**으로 확인한다.

**Files:**
- Create: `supabase/schema.sql`
- Create: `supabase/verify_permissions.sql`

- [ ] **Step 1: Supabase 프로젝트 생성**

1. https://supabase.com 에서 새 프로젝트 생성 (리전은 `Northeast Asia (Seoul)`)
2. Project Settings → API에서 세 값을 복사해 `.env`에 넣는다
   - `SUPABASE_URL` = Project URL
   - `SUPABASE_SERVICE_KEY` = `service_role` 키 (**비밀. 브라우저에 절대 노출 금지**)
   - `VITE_SUPABASE_ANON_KEY` = `anon` 키 (계획 2에서 쓴다. 지금 적어둔다)

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
  article_id  bigint primary key references public.articles(id) on delete cascade,
  body        text not null,
  body_source text not null,
  created_at  timestamptz not null default now(),

  constraint article_bodies_source_enum
    check (body_source in ('trafilatura', 'rss_excerpt'))
);

-- 실행 이력. 윈도우 계산·멱등성 판정·소스 침묵 감지가 모두 이걸 읽는다.
create table if not exists public.runs (
  id              bigint generated always as identity primary key,
  window_start    timestamptz not null,
  window_end      timestamptz not null,
  sent_at         timestamptz not null default now(),
  published_count int         not null default 0,
  -- {"토스_기술블로그": 3, "전자신문_오피니언": 0} — 3회 연속 0건이면 경고
  source_counts   jsonb       not null default '{}'::jsonb,
  input_tokens    int,
  errors          jsonb       not null default '[]'::jsonb
);

-- 좋아요 (계획 2)
create table if not exists public.reactions (
  id         bigint generated always as identity primary key,
  article_id bigint not null references public.articles(id) on delete cascade,
  created_at timestamptz not null default now()
);

-- 클릭 (계획 2)
create table if not exists public.clicks (
  id         bigint generated always as identity primary key,
  article_id bigint not null references public.articles(id) on delete cascade,
  created_at timestamptz not null default now()
);

-- 짧은 메모와 태그 (계획 2)
create table if not exists public.notes (
  id         bigint generated always as identity primary key,
  article_id bigint not null references public.articles(id) on delete cascade,
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

-- 마지막 발송 시각 조회 (윈도우 계산이 매 실행마다 쓴다)
create index if not exists runs_sent_at_idx
  on public.runs (sent_at desc);

-- 외래 키 컬럼에는 인덱스를 만든다. 없으면 부모 행 삭제 시 자식 테이블을
-- 전체 스캔하고, article_id로 집계할 때도 느리다.
create index if not exists reactions_article_id_idx on public.reactions (article_id);
create index if not exists clicks_article_id_idx    on public.clicks (article_id);
create index if not exists notes_article_id_idx     on public.notes (article_id);

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
grant insert on public.reactions to anon;
create policy reactions_public_insert on public.reactions
  for insert to anon with check (true);

grant insert on public.clicks to anon;
create policy clicks_public_insert on public.clicks
  for insert to anon with check (true);

-- notes: 내 메모를 내 페이지에서 쓰고 읽는다
grant select, insert on public.notes to anon;
create policy notes_public_read on public.notes
  for select to anon using (true);
create policy notes_public_insert on public.notes
  for insert to anon with check (true);

-- article_bodies / runs / kakao_auth: anon 정책을 만들지 않는다.
-- 권한도 회수했고 정책도 없으므로 이중으로 차단된다.
```

> **설명** — `generated always as identity`는 자동 증가 정수 기본키를 만드는 표준 SQL 문법이다. 구식 `serial`과 달리 숨은 시퀀스에 별도 권한을 줄 필요가 없어, anon이 삽입하는 테이블에서 특히 편하다. `timestamptz`는 타임존을 포함한 시각 타입으로, `timestamp`(타임존 없음)를 쓰면 서버 시간대에 따라 값이 달라진다. `jsonb`는 JSON을 이진 형태로 저장해 인덱스와 질의가 가능하다. `check` 제약은 잘못된 값이 DB에 들어오는 것을 애플리케이션 버그와 무관하게 막는다.

- [ ] **Step 3: 스키마 적용**

Supabase 대시보드 → SQL Editor에 `supabase/schema.sql` 전체를 붙여 넣고 Run.

Expected: `Success. No rows returned`

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

`article_bodies`, `runs`, `kakao_auth`가 **목록에 없어야** 한다. 하나라도 보이면 `revoke`가 적용되지 않은 것이므로 본문이 공개된다.

Expected (두 번째 쿼리): 7개 테이블 전부 `relrowsecurity = true`

- [ ] **Step 6: anon 키로 본문이 안 읽히는지 실제 확인**

```bash
curl -s "$SUPABASE_URL/rest/v1/article_bodies?select=*" \
  -H "apikey: $VITE_SUPABASE_ANON_KEY" \
  -H "Authorization: Bearer $VITE_SUPABASE_ANON_KEY"
```

Expected: 권한 거부 에러 (`"code":"42501"` 또는 유사). **빈 배열 `[]`이 나오면 안 된다** — 그건 "권한은 있고 데이터가 없다"는 뜻이므로 데이터가 쌓이면 노출된다.

- [ ] **Step 7: 커밋**

```bash
git add supabase/
git commit -m "feat: Supabase 스키마 — 본문 테이블 분리로 anon 차단, RLS 전면 활성화"
```

---

## Task 8: Supabase 저장소

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
        published_count=3,
        source_counts={"s": 5},
        input_tokens=12000,
        errors=[],
    )

    assert fake.last_sent_at() == sent


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
        published_count: int,
        source_counts: dict[str, int],
        input_tokens: int | None,
        errors: list[dict],
    ) -> None:
        """실행 이력을 남긴다. 0건이어도 반드시 호출한다."""
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
        published_count: int,
        source_counts: dict[str, int],
        input_tokens: int | None,
        errors: list[dict],
    ) -> None:
        self._db.table("runs").insert({
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "sent_at": window_end.isoformat(),
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
        published_count: int,
        source_counts: dict[str, int],
        input_tokens: int | None,
        errors: list[dict],
    ) -> None:
        self._last_sent = window_end
        self.runs.append({
            "window_start": window_start,
            "window_end": window_end,
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

Expected: `5 passed`

- [ ] **Step 6: 실제 연결 확인 스크립트 작성**

`scripts/smoke_supabase.py`:

```python
"""Supabase 연결과 권한을 1회 확인한다. 운영 파이프라인에 포함되지 않는다.

실행: python scripts/smoke_supabase.py
"""

from datetime import datetime, timedelta, timezone

from pipeline.lib.secrets import require
from pipeline.lib.store import SupabaseStore


def main() -> None:
    store = SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SERVICE_KEY"))

    print("1) 마지막 발송 시각 조회...")
    print(f"   → {store.last_sent_at()}  (최초 실행이면 None)")

    print("2) 실행 이력 쓰기 테스트...")
    now = datetime.now(timezone.utc)
    store.record_run(
        window_start=now - timedelta(hours=24),
        window_end=now,
        published_count=0,
        source_counts={"smoke_test": 0},
        input_tokens=None,
        errors=[],
    )
    print(f"   → 기록됨. 다시 조회: {store.last_sent_at()}")

    print("3) 발행 URL 조회 테스트...")
    print(f"   → {store.known_urls(['https://example.com/none'])}  (빈 집합이 정상)")

    print("4) 최근 헤드라인 조회 테스트...")
    print(f"   → {len(store.recent_headlines(days=14))}건")

    print()
    print("성공. 테스트로 넣은 runs 행은 Supabase 대시보드에서 지운다:")
    print("  delete from public.runs where source_counts ? 'smoke_test';")


if __name__ == "__main__":
    main()
```

> **설명** — `if __name__ == "__main__":`는 이 파일을 직접 실행했을 때만 `main()`을 호출하게 한다. 다른 모듈이 import할 때는 실행되지 않는다. Python 스크립트의 표준 관례다.

- [ ] **Step 7: 실제로 실행해 확인**

```bash
mkdir -p scripts && python scripts/smoke_supabase.py
```

Expected: 네 단계가 모두 출력되고 마지막에 "성공". 2번에서 기록한 시각이 조회되어야 한다.

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

## Task 9: 소스 목록과 관심사 프로필

**이 태스크는 사용자 입력이 필요하다.** 파이프라인 품질을 가장 크게 좌우하는 두 파일이고, 다음 태스크의 시드 수집이 되돌릴 수 없으므로 여기서 확정한다.

**Files:**
- Create: `config/sources.yaml`
- Create: `config/interests.md`
- Create: `scripts/check_feeds.py`

- [ ] **Step 1: 후보 소스 목록 작성**

`config/sources.yaml`:

```yaml
# 수집 소스.
#
# weight: LLM 점수에 곱하는 가중치. 1.0이 기준.
#   기업 기술블로그처럼 관심사 정중앙인 소스는 1.2~1.3,
#   일반 매체 속보성 기사가 섞이는 소스는 0.8~0.9로 둔다.
# lang: ko | en. 해외 소스는 요약 시 한국어로 번역한다.
# enabled: false로 두면 수집에서 제외된다(삭제하지 않고 끌 수 있게).

sources:
  # --- 국내 IT 매체: 컬럼·오피니언 ---
  - name: 전자신문_오피니언
    url: https://rss.etnews.com/Section902.xml
    kind: rss
    weight: 1.0
    lang: ko
    enabled: true

  - name: ZDNet코리아_칼럼
    url: https://feeds.feedburner.com/zdkorea
    kind: rss
    weight: 0.9
    lang: ko
    enabled: true

  # --- 국내 기업 기술블로그: 관심사 정중앙 ---
  - name: 토스_기술블로그
    url: https://toss.tech/rss.xml
    kind: rss
    weight: 1.3
    lang: ko
    enabled: true

  - name: 카카오_기술블로그
    url: https://tech.kakao.com/feed/
    kind: rss
    weight: 1.3
    lang: ko
    enabled: true

  - name: 우아한형제들_기술블로그
    url: https://techblog.woowahan.com/feed/
    kind: rss
    weight: 1.3
    lang: ko
    enabled: true

  - name: 라인_기술블로그
    url: https://engineering.linecorp.com/ko/feed/
    kind: rss
    weight: 1.2
    lang: ko
    enabled: true

  # --- 해외: 남이 검증한 것 우대 ---
  - name: Hacker_News_Best
    url: https://hnrss.org/best?points=200
    kind: rss
    weight: 1.2
    lang: en
    enabled: true

  - name: AWS_Architecture_Blog
    url: https://aws.amazon.com/blogs/architecture/feed/
    kind: rss
    weight: 1.1
    lang: en
    enabled: true

  - name: Cloudflare_Blog
    url: https://blog.cloudflare.com/rss/
    kind: rss
    weight: 1.1
    lang: en
    enabled: true

  - name: OpenAI_Blog
    url: https://openai.com/blog/rss.xml
    kind: rss
    weight: 1.1
    lang: en
    enabled: true

  - name: Anthropic_News
    url: https://www.anthropic.com/rss.xml
    kind: rss
    weight: 1.2
    lang: en
    enabled: true
```

- [ ] **Step 2: 피드 생존 확인 스크립트 작성**

위 URL은 후보이고 **실제로 살아있는지 확인해야 한다.** 매체 개편으로 주소가 바뀌는 일이 흔하다.

`scripts/check_feeds.py`:

```python
"""config/sources.yaml의 각 피드가 살아있는지 확인한다.

실행: python scripts/check_feeds.py
"""

import sys
from pathlib import Path

import feedparser
import httpx
import yaml

TIMEOUT = 15.0


def main() -> int:
    config = yaml.safe_load(Path("config/sources.yaml").read_text(encoding="utf-8"))
    dead: list[str] = []

    for source in config["sources"]:
        if not source.get("enabled", True):
            print(f"[   끔] {source['name']}")
            continue

        name, url = source["name"], source["url"]
        try:
            # follow_redirects=True: 매체가 주소를 옮기고 301을 주는 경우가 많다
            response = httpx.get(
                url,
                timeout=TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": "briefing-bot/0.1"},
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            count = len(feed.entries)

            if count == 0:
                print(f"[ 0건] {name}  ← 파싱은 되지만 항목이 없다. 주소 확인 필요")
                dead.append(name)
            else:
                newest = feed.entries[0].get("title", "(제목 없음)")[:40]
                print(f"[{count:3d}건] {name}  최신: {newest}")
                if str(response.url) != url:
                    print(f"         ↳ 리다이렉트됨. yaml을 이 주소로 바꾼다: {response.url}")

        except Exception as error:  # noqa: BLE001 — 확인 스크립트이므로 전부 잡는다
            print(f"[실패] {name}  {type(error).__name__}: {error}")
            dead.append(name)

    print()
    if dead:
        print(f"확인 필요한 소스 {len(dead)}개: {', '.join(dead)}")
        print("주소를 고치거나 enabled: false로 끈다.")
        return 1

    print("모든 피드 정상.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

> **설명** — `yaml.safe_load`는 YAML을 Python 딕셔너리로 바꾼다(`load`가 아니라 `safe_load`를 쓴다 — 전자는 임의 객체 생성이 가능해 신뢰할 수 없는 입력에 위험하다). `response.raise_for_status()`는 4xx·5xx 응답에서 예외를 던진다. `sys.exit(main())`은 함수의 반환값을 프로세스 종료 코드로 쓴다(0=성공).

- [ ] **Step 3: 피드를 실제로 확인하고 `sources.yaml`을 고친다**

```bash
python scripts/check_feeds.py
```

죽은 피드는 주소를 고치거나 `enabled: false`로 끈다. **`[실패]`나 `[ 0건]`이 하나도 없을 때까지 반복한다.**

- [ ] **Step 4: 관심사 프로필 작성**

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

## 중복 처리

최근 발행한 헤드라인 목록을 함께 받는다. **같은 사건·같은 주제를 다룬 글은
가장 깊이 있는 한 건만 남기고 나머지는 40점 이하로 내린다.** 단, 명시적인
후속편(2편, 심화 편)은 중복이 아니다.
```

> 이 파일은 **앞으로 계속 고치게 된다.** Task 13의 평가 도구로 선별 결과를 보면서 "이건 왜 뽑혔지" 싶은 항목의 패턴을 여기에 추가하는 것이 튜닝 작업이다.

- [ ] **Step 5: 커밋**

```bash
git add config/ scripts/check_feeds.py
git commit -m "feat: 소스 목록과 관심사 프로필, 피드 생존 확인 스크립트"
```

---

## Task 10: 소스 설정 로더

**Files:**
- Create: `pipeline/lib/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_config.py`:

```python
import pytest
from pydantic import ValidationError

from pipeline.lib.config import Source, load_sources

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


def test_소스가_하나도_없으면_거부한다(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text("sources: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="비어"):
        load_sources(path)
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_config.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.config'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/lib/config.py`:

```python
"""소스 설정 로딩."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

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


def load_sources(path: Path | None = None) -> list[Source]:
    """켜진 소스만 돌려준다."""
    path = path or DEFAULT_SOURCES_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    all_sources = [Source.model_validate(row) for row in data.get("sources") or []]

    names = [s.name for s in all_sources]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise ValueError(
            f"소스 이름이 중복됐다: {', '.join(sorted(duplicates))}. "
            f"이름은 집계 키로 쓰이므로 유일해야 한다."
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

> **설명** — `data.get("sources") or []`에서 `or`를 쓴 이유는, YAML에 `sources:`만 적고 비워두면 `None`이 되기 때문이다. `get("sources", [])`는 키가 **없을 때만** 기본값을 주므로 `None`을 막지 못한다. `Field(gt=0)`은 "0보다 큼"(greater than)이다.

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_config.py
```

Expected: `6 passed`

- [ ] **Step 5: 실제 설정 파일이 로딩되는지 확인**

```bash
python -c "
from pipeline.lib.config import load_sources, load_interests
s = load_sources()
print(f'소스 {len(s)}개:', ', '.join(x.name for x in s))
print(f'관심사 프로필 {len(load_interests())}자')
"
```

Expected: 소스 개수와 이름 목록, 관심사 프로필 길이가 출력된다.

- [ ] **Step 6: 커밋**

```bash
git add pipeline/lib/config.py tests/test_config.py
git commit -m "feat: 소스 설정 로더 (이름 중복·빈 목록 거부)"
```

---

## Task 11: 수집

**Files:**
- Create: `pipeline/collect.py`
- Create: `tests/fixtures/feed_two_items.xml`
- Create: `tests/fixtures/feed_empty.xml`
- Create: `tests/test_collect.py`

- [ ] **Step 1: 테스트 fixture 작성**

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

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_collect.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from pipeline.collect import collect
from pipeline.lib.config import Source

FIXTURES = Path(__file__).parent / "fixtures"

# fixture의 첫 항목은 2026-11-10T05:30:00Z, 두 번째는 2025-11-10T00:00:00Z
WINDOW_START = datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc)


def _source(name: str = "토스_기술블로그", url: str = "https://toss.tech/rss.xml") -> Source:
    return Source(name=name, url=url, kind="rss", weight=1.3, lang="ko")


def _fetch_fixture(filename: str):
    """URL과 무관하게 지정한 fixture를 돌려주는 fetch 함수를 만든다."""
    data = (FIXTURES / filename).read_bytes()

    def fetch(url: str) -> bytes:
        return data

    return fetch


def _collect(**overrides):
    kwargs = {
        "sources": [_source()],
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "fetch": _fetch_fixture("feed_two_items.xml"),
        "known_urls": lambda urls: set(),
    }
    kwargs.update(overrides)
    return collect(**kwargs)


def test_윈도우_안의_항목만_수집한다():
    bundle = _collect()

    assert len(bundle.items) == 1
    assert bundle.items[0].title == "결제 서버 P99 40ms 달성기"


def test_URL을_정규화해서_저장한다():
    """utm_source가 붙은 채로 저장되면 중복 제거가 깨진다."""
    bundle = _collect()

    assert bundle.items[0].url == "https://toss.tech/article/payment-latency"


def test_소스_이름을_기록한다():
    bundle = _collect()
    assert bundle.items[0].source == "토스_기술블로그"


def test_발행_시각을_UTC로_정규화한다():
    bundle = _collect()
    assert bundle.items[0].published == "2026-11-10T05:30:00+00:00"


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


def test_소스별_건수를_집계한다():
    """소스 침묵 감지의 입력이 된다."""
    bundle = _collect()
    assert bundle.source_counts == {"토스_기술블로그": 1}


def test_항목이_없는_피드도_0건으로_집계한다():
    bundle = _collect(fetch=_fetch_fixture("feed_empty.xml"))

    assert bundle.items == []
    assert bundle.source_counts == {"토스_기술블로그": 0}
    assert bundle.errors == []


def test_소스_하나가_죽어도_나머지는_수집한다():
    """핵심 요구사항. 매체 하나의 장애로 그날이 날아가면 안 된다."""
    good = (FIXTURES / "feed_two_items.xml").read_bytes()

    def fetch(url: str) -> bytes:
        if url == "https://broken.com/r":
            raise RuntimeError("연결 실패")
        return good

    bundle = collect(
        sources=[_source("깨진소스", "https://broken.com/r"),
                 _source("정상소스", "https://ok.com/r")],
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        fetch=fetch,
        known_urls=lambda urls: set(),
    )

    assert len(bundle.items) == 1
    assert bundle.items[0].source == "정상소스"
    assert len(bundle.errors) == 1
    assert bundle.errors[0].source == "깨진소스"
    assert "연결 실패" in bundle.errors[0].message
    assert bundle.source_counts == {"깨진소스": 0, "정상소스": 1}


def test_모든_소스가_죽으면_예외를_던진다():
    """전부 실패는 중단 조건이다. 빈 브리핑을 보내서는 안 된다."""
    def fetch(url: str) -> bytes:
        raise RuntimeError("전부 실패")

    import pytest
    with pytest.raises(RuntimeError, match="모든 소스"):
        collect(
            sources=[_source("A", "https://a.com/r"), _source("B", "https://b.com/r")],
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            fetch=fetch,
            known_urls=lambda urls: set(),
        )


def test_발행_시각을_읽을_수_없는_항목은_건너뛴다():
    """한 건의 날짜 오류로 수집이 중단되면 안 된다."""
    xml = b"""<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>날짜 깨짐</title><link>https://e.com/a</link>
      <pubDate>언젠가</pubDate><description>d</description></item>
    </channel></rss>"""

    bundle = collect(
        sources=[_source()],
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        fetch=lambda url: xml,
        known_urls=lambda urls: set(),
    )
    assert bundle.items == []


def test_윈도우_경계를_번들에_기록한다():
    bundle = _collect()
    assert bundle.window_start == WINDOW_START.isoformat()
    assert bundle.window_end == WINDOW_END.isoformat()
```

- [ ] **Step 3: 실패를 확인**

```bash
pytest tests/test_collect.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.collect'`

- [ ] **Step 4: 최소 구현 작성**

`pipeline/collect.py`:

```python
"""01 수집: 윈도우 내에 발행된 글을 소스별로 긁어 raw.json을 만든다.

실행: python -m pipeline.collect
"""

from datetime import datetime, timezone
from typing import Callable

import feedparser
import httpx

from pipeline.lib.config import Source, load_sources
from pipeline.lib.secrets import require
from pipeline.lib.store import LocalStore, SupabaseStore
from pipeline.lib.timeutil import KST, compute_window, to_utc_iso
from pipeline.lib.urls import normalize_url
from pipeline.models import RawBundle, RawItem, SourceError

HTTP_TIMEOUT = 20.0
USER_AGENT = "briefing-bot/0.1"

# 협력자의 타입. 테스트가 가짜를 넘길 수 있도록 함수로 받는다.
FetchFn = Callable[[str], bytes]
KnownUrlsFn = Callable[[list[str]], set[str]]


def http_fetch(url: str) -> bytes:
    """실제 HTTP 수집. follow_redirects로 매체 주소 이전을 따라간다."""
    response = httpx.get(
        url,
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return response.content


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
        # 매체마다 키가 다르다. published가 없으면 updated를 본다.
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
            continue

        items.append(RawItem(
            source=source.name,
            title=(entry.get("title") or "").strip(),
            url=normalize_url(link),
            published=published,
            # summary가 없는 피드도 있다. 없으면 빈 문자열로 둔다.
            excerpt=(entry.get("summary") or "").strip(),
        ))

    return items


def collect(
    *,
    sources: list[Source],
    window_start: datetime,
    window_end: datetime,
    fetch: FetchFn,
    known_urls: KnownUrlsFn,
) -> RawBundle:
    """윈도우 내 항목을 수집한다. 소스 단위로 장애를 격리한다."""
    collected: list[RawItem] = []
    counts: dict[str, int] = {}
    errors: list[SourceError] = []

    for source in sources:
        try:
            items = _parse_source(source, fetch(source.url), window_start, window_end)
        except Exception as error:  # noqa: BLE001 — 소스 장애를 격리하는 것이 목적
            # 어떤 예외든 해당 소스만 포기하고 계속한다.
            counts[source.name] = 0
            errors.append(SourceError(
                source=source.name,
                message=f"{type(error).__name__}: {error}",
            ))
            continue

        counts[source.name] = len(items)
        collected.extend(items)

    # 전부 실패했으면 중단한다. 빈 브리핑을 보내면 "오늘 조용했다"로 오해된다.
    if errors and len(errors) == len(sources):
        raise RuntimeError(
            f"모든 소스 수집에 실패했다 ({len(sources)}개). "
            f"네트워크나 소스 주소를 확인한다. 첫 에러: {errors[0].message}"
        )

    # 실행 내 중복 제거 — 같은 글이 여러 소스에 올라오는 경우.
    # dict는 삽입 순서를 유지하므로 먼저 만난 소스의 항목이 남는다.
    unique = list({item.url: item for item in collected}.values())

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
    remote = SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SERVICE_KEY"))
    now = datetime.now(timezone.utc)
    window_start, window_end = compute_window(now=now, last_sent_at=remote.last_sent_at())

    bundle = collect(
        sources=load_sources(),
        window_start=window_start,
        window_end=window_end,
        fetch=http_fetch,
        known_urls=remote.known_urls,
    )

    # 날짜 디렉터리는 KST 기준으로 만든다. 사람이 보는 이름이기 때문이다.
    date = window_end.astimezone(KST).date().isoformat()
    path = LocalStore(date=date).write("raw", bundle)

    print(f"수집 {len(bundle.items)}건 → {path}")
    print(f"  윈도우: {window_start.isoformat()} ~ {window_end.isoformat()}")
    for name, count in sorted(bundle.source_counts.items()):
        print(f"  {count:4d}건  {name}")
    for error in bundle.errors:
        print(f"  [실패] {error.source}: {error.message}")


if __name__ == "__main__":
    main()
```

> **설명** — `Callable[[str], bytes]`는 "문자열 하나를 받아 bytes를 돌려주는 함수" 타입이다. 이렇게 함수를 인자로 받으면 테스트에서 HTTP 모킹 없이 가짜 함수를 넘길 수 있다. `{item.url: item for item in collected}`는 딕셔너리 컴프리헨션으로, 같은 키가 나오면 **나중 값이 덮어쓴다** — 여기서는 순서 유지만 필요해서 그대로 쓴다. `list.extend`는 리스트를 펼쳐 붙이고(`append`는 리스트 자체를 한 원소로 넣는다), `noqa: BLE001`은 린터의 "광범위 예외 잡기" 경고를 의도적으로 끈 표시다.

- [ ] **Step 5: 통과를 확인**

```bash
pytest tests/test_collect.py
```

Expected: `12 passed`

- [ ] **Step 6: 전체 테스트 확인**

```bash
pytest
```

Expected: `59 passed` (urls 8 + timeutil 12 + models 11 + secrets 5 + local_store 5 + remote_store 5 + config 6 + collect 12 — 실제 수치는 다를 수 있으니 실패가 0인지만 본다)

- [ ] **Step 7: 커밋**

```bash
git add pipeline/collect.py tests/test_collect.py tests/fixtures/
git commit -m "feat: 수집 단계 — 윈도우 필터, URL 정규화, 소스 장애 격리"
```

---

## Task 12: 시드 수집

**되돌릴 수 없는 작업이다.** 대부분의 RSS 피드는 최근 10~50건만 제공하므로, 지금 긁지 않으면 그 데이터는 영구히 얻을 수 없다. 이후 선별 프롬프트 튜닝의 재료가 된다.

**Files:**
- Create: `pipeline/seed.py`
- Create: `tests/test_seed.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_seed.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from pipeline.lib.config import Source
from pipeline.seed import SEED_DIR, seed_window

FIXTURES = Path(__file__).parent / "fixtures"


def test_시드_윈도우가_아주_넓다():
    """피드가 주는 전부를 받으려면 윈도우가 과거를 충분히 덮어야 한다."""
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    start, end = seed_window(now=now)

    assert end == now
    assert (end - start).days >= 365


def test_시드는_별도_디렉터리를_쓴다():
    """운영 날짜 디렉터리와 섞이면 일반 실행이 시드를 덮어쓴다."""
    assert SEED_DIR == "_seed"


def test_오래된_항목도_수집된다():
    """fixture의 2025년 글이 들어와야 한다 — 운영 수집에서는 걸러진 항목."""
    from pipeline.collect import collect

    data = (FIXTURES / "feed_two_items.xml").read_bytes()
    now = datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc)
    start, end = seed_window(now=now)

    bundle = collect(
        sources=[Source(name="s", url="https://e.com/r", kind="rss",
                        weight=1.0, lang="ko")],
        window_start=start,
        window_end=end,
        fetch=lambda url: data,
        known_urls=lambda urls: set(),
    )

    assert len(bundle.items) == 2
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_seed.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.seed'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/seed.py`:

```python
"""시드 수집 (1회성): 각 소스가 제공하는 전체 항목을 긁어 저장한다.

운영 수집과 다른 점은 윈도우뿐이다. 수집 로직은 collect를 재사용한다.

실행: python -m pipeline.seed

이 데이터는 선별 프롬프트 튜닝(pipeline.evaluate)의 재료다. RSS는 과거를
충분히 제공하지 않으므로, 지금 긁지 않으면 다시 얻을 수 없다.
"""

from datetime import datetime, timedelta, timezone

from pipeline.collect import collect, http_fetch
from pipeline.lib.config import load_sources
from pipeline.lib.store import LocalStore

# 운영 날짜 디렉터리(2026-11-10)와 섞이지 않게 별도 이름을 쓴다.
SEED_DIR = "_seed"

# 피드가 주는 전부를 받기 위한 넉넉한 과거 범위.
SEED_LOOKBACK_DAYS = 400


def seed_window(*, now: datetime) -> tuple[datetime, datetime]:
    return now - timedelta(days=SEED_LOOKBACK_DAYS), now


def main() -> None:
    now = datetime.now(timezone.utc)
    window_start, window_end = seed_window(now=now)

    bundle = collect(
        sources=load_sources(),
        window_start=window_start,
        window_end=window_end,
        fetch=http_fetch,
        # 시드는 발행 이력을 보지 않는다. 전부 받아야 한다.
        known_urls=lambda urls: set(),
    )

    path = LocalStore(date=SEED_DIR).write("raw", bundle)

    print(f"시드 수집 {len(bundle.items)}건 → {path}")
    for name, count in sorted(bundle.source_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {count:4d}건  {name}")
    for error in bundle.errors:
        print(f"  [실패] {error.source}: {error.message}")
    print()
    print("이 파일은 선별 프롬프트 튜닝에 쓴다. 지우지 않는다.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_seed.py
```

Expected: `3 passed`

- [ ] **Step 5: 시드를 실제로 수집한다**

```bash
python -m pipeline.seed
```

Expected: 소스별 건수가 출력되고 총합이 수백 건. 소스가 11개면 대략 200~600건.

**수집량이 50건 미만이면 멈추고 원인을 찾는다** — 대부분 `sources.yaml`의 주소 문제이고, `python scripts/check_feeds.py`로 확인한다.

- [ ] **Step 6: 시드 파일을 git에서 제외하되 백업한다**

`data/`는 `.gitignore`에 있으므로 커밋되지 않는다. 그런데 **이 파일은 다시 만들 수 없으므로** 별도로 복사해 둔다.

```bash
mkdir -p ~/briefing-seed-backup
cp data/_seed/raw.json ~/briefing-seed-backup/raw-$(date +%Y%m%d).json
ls -lh ~/briefing-seed-backup/
```

- [ ] **Step 7: 커밋**

```bash
git add pipeline/seed.py tests/test_seed.py
git commit -m "feat: 시드 수집 — 피드 전체 항목 확보 (프롬프트 튜닝 재료)"
```

---

## Task 13: LLM 래퍼

**Files:**
- Create: `pipeline/lib/llm.py`
- Modify: `tests/fakes.py` (추가)
- Create: `tests/test_llm.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_llm.py`:

```python
import pytest
from pydantic import BaseModel

from pipeline.lib.llm import LLM, LLMError, RefusedError, retrying
from tests.fakes import FakeLLM


class Answer(BaseModel):
    value: int


# --- 재시도 헬퍼 ---

def test_한_번에_성공하면_한_번만_호출한다():
    calls = []

    def ok():
        calls.append(1)
        return "결과"

    assert retrying(ok, attempts=2) == "결과"
    assert len(calls) == 1


def test_첫_시도가_실패하면_다시_호출한다():
    """스펙의 '1회 재시도' 정책."""
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise LLMError("일시적 오류")
        return "결과"

    assert retrying(flaky, attempts=2) == "결과"
    assert len(calls) == 2


def test_전부_실패하면_마지막_예외를_올린다():
    def always_fails():
        raise LLMError("계속 실패")

    with pytest.raises(LLMError, match="계속 실패"):
        retrying(always_fails, attempts=2)


def test_거부는_재시도하지_않는다():
    """같은 입력을 다시 보내도 또 거부된다. 토큰만 쓴다."""
    calls = []

    def refused():
        calls.append(1)
        raise RefusedError("정책 거부")

    with pytest.raises(RefusedError):
        retrying(refused, attempts=3)
    assert len(calls) == 1


# --- 가짜 구현 ---

def test_가짜_LLM이_인터페이스를_만족한다():
    fake: LLM = FakeLLM(responses=[Answer(value=7)])
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
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_llm.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.llm'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/lib/llm.py`:

```python
"""Claude API 래퍼.

파이프라인 단계는 LLM 프로토콜만 알고 SDK를 모른다. 테스트는 FakeLLM을
넘기므로 실제 호출이 일어나지 않는다.
"""

from typing import Callable, Literal, Protocol, TypeVar

from pydantic import BaseModel

# 스펙 결정: 선별·요약 모두 Opus. Max 플랜 크레딧으로 비용 제약이 없으므로
# 품질 기준으로만 고른다. 바꾸려면 이 한 줄만 고친다.
MODEL = "claude-opus-5-5"

# 거부(refusal)가 났을 때 서버 측에서 다른 모델로 자동 재시도하게 한다.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

Effort = Literal["low", "medium", "high", "xhigh", "max"]
TOut = TypeVar("TOut", bound=BaseModel)


class LLMError(RuntimeError):
    """재시도할 가치가 있는 실패 (타임아웃, 5xx, 스키마 검증 실패)."""


class RefusedError(LLMError):
    """정책 거부. 같은 입력을 다시 보내도 또 거부되므로 재시도하지 않는다."""


class LLM(Protocol):
    def parse(
        self,
        *,
        prompt: str,
        output_format: type[TOut],
        effort: Effort,
        max_tokens: int = 16000,
    ) -> tuple[TOut, int]:
        """구조화된 출력을 받는다. (파싱된 결과, 입력 토큰 수)를 돌려준다."""
        ...


TResult = TypeVar("TResult")


def retrying(
    call: Callable[[], TResult],
    *,
    attempts: int = 2,
) -> TResult:
    """LLMError에 대해 재시도한다. RefusedError는 즉시 포기한다."""
    last: LLMError | None = None

    for _ in range(attempts):
        try:
            return call()
        except RefusedError:
            # 거부는 결정적이다. 다시 보내면 토큰만 쓰고 또 거부된다.
            raise
        except LLMError as error:
            last = error

    assert last is not None  # attempts >= 1이면 반드시 설정된다
    raise last


class AnthropicLLM:
    """LLM 프로토콜의 Claude API 구현.

    단위 테스트하지 않는다 — 대부분이 SDK 호출 통과이고, 모킹하면
    '내가 쓴 모킹이 맞는가'만 검증하게 된다. 실제 동작은
    scripts/smoke_llm.py로 1회 확인한다.
    """

    def __init__(self, api_key: str, model: str = MODEL) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def parse(
        self,
        *,
        prompt: str,
        output_format: type[TOut],
        effort: Effort,
        max_tokens: int = 16000,
    ) -> tuple[TOut, int]:
        try:
            response = self._client.beta.messages.parse(
                model=self._model,
                max_tokens=max_tokens,
                # fallbacks: 정책 거부 시 서버가 다른 모델로 같은 요청을
                # 재실행한다. "default"는 거부 범주에 따라 자동 라우팅하므로
                # 모델 목록을 직접 관리하지 않아도 된다.
                betas=[FALLBACK_BETA],
                fallbacks="default",
                # effort는 추론 깊이와 토큰 지출을 조절한다.
                # 채점에는 low, 요약에는 medium을 쓴다.
                output_config={"effort": effort},
                # output_format에 pydantic 모델을 넘기면 응답이 그 스키마를
                # 반드시 따르고, parsed_output으로 검증된 객체가 나온다.
                output_format=output_format,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as error:  # noqa: BLE001
            raise LLMError(f"{type(error).__name__}: {error}") from error

        # 거부는 예외가 아니라 HTTP 200 + stop_reason으로 온다.
        # content를 읽기 전에 반드시 확인한다.
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            raise RefusedError(f"정책 거부 (category={category})")

        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("구조화된 출력이 비어 있다")

        return parsed, response.usage.input_tokens
```

> **설명** — `TypeVar("TOut", bound=BaseModel)`은 "pydantic 모델의 어떤 하위 타입"을 뜻하며, `output_format=ScoreSheet`를 넘기면 반환형이 `ScoreSheet`로 추론된다. `raise ... from error`는 원래 예외를 체인으로 보존해 트레이스백에 둘 다 나오게 한다. `except RefusedError: raise`는 잡아서 아무것도 하지 않고 그대로 다시 올린다 — 바로 아래 `except LLMError`에 걸리지 않게 하려는 의도다(`RefusedError`가 `LLMError`의 하위 클래스이므로 순서가 중요하다).

- [ ] **Step 4: 가짜 LLM을 `tests/fakes.py`에 추가**

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

- [ ] **Step 5: 통과를 확인**

```bash
pytest tests/test_llm.py
```

Expected: `8 passed`

- [ ] **Step 6: 실제 API 연결 확인 스크립트 작성**

`scripts/smoke_llm.py`:

```python
"""Claude API 연결과 구조화된 출력을 1회 확인한다.

실행: python scripts/smoke_llm.py
크레딧을 아주 조금 쓴다.
"""

from pydantic import BaseModel

from pipeline.lib.llm import MODEL, AnthropicLLM
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

    verdict, input_tokens = llm.parse(
        prompt=prompt, output_format=Verdict, effort="low", max_tokens=2000
    )

    print(f"모델: {MODEL}")
    print(f"입력 토큰: {input_tokens}")
    print(f"점수: {verdict.score}")
    print(f"이유: {verdict.reason}")
    print()
    print("성공. 구조화된 출력이 스키마대로 돌아왔다.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: 실제로 실행해 확인**

```bash
python scripts/smoke_llm.py
```

Expected: 점수(아마 80 이상)와 이유가 출력되고 "성공".

실패하면 `ANTHROPIC_API_KEY`가 **Max 크레딧이 연결된 Console 조직**의 키인지 확인한다. claude.ai → Settings → Billing에서 조직 연결 상태를 본다.

- [ ] **Step 8: 커밋**

```bash
git add pipeline/lib/llm.py tests/fakes.py tests/test_llm.py scripts/smoke_llm.py
git commit -m "feat: Claude API 래퍼 — 구조화된 출력, 거부 처리, 1회 재시도"
```

---

## Task 14: 선별

**Files:**
- Create: `pipeline/rank.py`
- Create: `tests/test_rank.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_rank.py`:

```python
import pytest

from pipeline.models import RawItem, ScoreItem, ScoreSheet
from pipeline.rank import TOP_N, apply_weight, build_prompt, rank
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


def test_범위를_벗어난_index는_무시한다():
    """LLM이 없는 번호를 돌려줘도 IndexError로 죽지 않아야 한다."""
    items = [_item(0)]
    scores = [
        ScoreItem(index=0, score=80, reason="r", topic="AI"),
        ScoreItem(index=99, score=90, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert len(bundle.selected) == 1


def test_같은_index를_두_번_주면_한_번만_센다():
    items = [_item(0), _item(1)]
    scores = [
        ScoreItem(index=0, score=80, reason="r", topic="AI"),
        ScoreItem(index=0, score=90, reason="r", topic="AI"),
    ]
    bundle, _ = _rank(items, scores)

    assert len(bundle.selected) == 1


def test_수집_항목이_없으면_LLM을_호출하지_않는다():
    """토큰을 쓰지 않는다."""
    llm = FakeLLM(responses=[])
    bundle = rank(
        items=[], interests="i", recent_headlines=[], weights={},
        llm=llm, window_start=WINDOW[0], window_end=WINDOW[1],
    )

    assert bundle.selected == []
    assert llm.prompts == []
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_rank.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.rank'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/rank.py`:

```python
"""02 선별: 수집 항목을 한 번의 LLM 호출로 채점하고 상위 N건을 고른다.

건당 호출하지 않는 이유는, 한 번에 넣어야 LLM이 "이 둘은 같은 사건이니
하나만" 같은 교차 판단을 할 수 있기 때문이다.

실행: python -m pipeline.rank
"""

from datetime import datetime, timezone

from pipeline.lib.config import load_interests, load_sources
from pipeline.lib.llm import LLM, AnthropicLLM, Effort, retrying
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


def apply_weight(score: int, weight: float) -> int:
    """소스 가중치를 점수에 반영한다. 상한 100."""
    return min(100, round(score * weight))


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
        # 발췌는 400자로 자른다. 그 이상은 채점 정확도에 기여하지 않으면서
        # 토큰만 늘린다 (항목 수가 많으므로 누적이 크다).
        excerpt = item.excerpt[:400]
        lines += [
            f"[{index}] ({item.source}) {item.title}",
            f"      {excerpt}",
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

    prompt = build_prompt(
        interests=interests, recent_headlines=recent_headlines, items=items
    )

    sheet, _tokens = retrying(
        lambda: llm.parse(prompt=prompt, output_format=ScoreSheet, effort=RANK_EFFORT)
    )

    ranked: list[RankedItem] = []
    seen_indexes: set[int] = set()
    kept_scores: list[ScoreItem] = []

    for score in sheet.scores:
        # LLM이 범위 밖 번호나 중복 번호를 돌려줄 수 있다. 둘 다 무시한다.
        if not (0 <= score.index < len(items)) or score.index in seen_indexes:
            continue
        seen_indexes.add(score.index)

        item = items[score.index]
        weighted = apply_weight(score.score, weights.get(item.source, 1.0))

        kept_scores.append(score)
        ranked.append(RankedItem(
            item=item,
            score=weighted,
            reason=score.reason,
            topic=score.topic,
        ))

    # 가중치 적용 후 점수로 정렬한다.
    ranked.sort(key=lambda r: r.score, reverse=True)

    return RankedBundle(
        window_start=window_start,
        window_end=window_end,
        selected=ranked[:TOP_N],
        all_scores=kept_scores,
    )


def main() -> None:
    date = datetime.now(timezone.utc).astimezone(KST).date().isoformat()
    store = LocalStore(date=date)
    raw = store.read("raw", RawBundle)

    remote = SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SERVICE_KEY"))
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
    print(f"채점 {len(bundle.all_scores)}건 → 선별 {len(bundle.selected)}건 → {path}")
    for item in bundle.selected:
        print(f"  {item.score:3d}  [{item.topic}] {item.item.title[:50]}")
        print(f"       {item.reason[:70]}")


if __name__ == "__main__":
    main()
```

> **설명** — `enumerate(items)`는 `(0, 첫항목), (1, 둘째항목), ...`을 돌려줘서 번호와 값을 함께 쓸 수 있다. `list.sort(key=..., reverse=True)`는 리스트를 제자리에서 정렬하며, `key`로 비교 기준을 지정한다(`lambda r: r.score`). `weights.get(name, 1.0)`은 소스가 가중치 표에 없으면 1.0을 쓴다 — 설정이 빠져도 죽지 않게 한다. `retrying(lambda: ...)`에서 `lambda`로 감싼 이유는, `retrying`이 함수 **객체**를 받아 여러 번 호출해야 하므로 호출 결과가 아니라 호출 가능한 것을 넘겨야 하기 때문이다.

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_rank.py
```

Expected: `15 passed`

- [ ] **Step 5: 커밋**

```bash
git add pipeline/rank.py tests/test_rank.py
git commit -m "feat: 선별 단계 — 일괄 채점, 소스 가중치, 잘못된 index 방어"
```

---

## Task 15: 선별 품질 평가 도구

운영에 포함되지 않는다. 시드 데이터로 프롬프트를 고치며 결과를 비교하는 도구다.

**Files:**
- Create: `pipeline/evaluate.py`
- Create: `tests/test_evaluate.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_evaluate.py`:

```python
from pipeline.evaluate import format_table, sample_items
from pipeline.models import RankedItem, RawItem


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


def test_표본_추출이_요청한_개수를_넘지_않는다():
    items = [
        RawItem(source="s", title=f"t{i}", url=f"https://e.com/{i}",
                published="2026-11-10T05:30:00+00:00", excerpt="e")
        for i in range(100)
    ]
    assert len(sample_items(items, limit=30)) == 30


def test_항목이_요청보다_적으면_전부_돌려준다():
    items = [
        RawItem(source="s", title="t", url="https://e.com/1",
                published="2026-11-10T05:30:00+00:00", excerpt="e")
    ]
    assert len(sample_items(items, limit=30)) == 1


def test_표본_추출이_재현_가능하다():
    """프롬프트 변경 효과만 비교하려면 입력이 고정돼야 한다."""
    items = [
        RawItem(source="s", title=f"t{i}", url=f"https://e.com/{i}",
                published="2026-11-10T05:30:00+00:00", excerpt="e")
        for i in range(100)
    ]
    assert sample_items(items, limit=20) == sample_items(items, limit=20)
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_evaluate.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.evaluate'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/evaluate.py`:

```python
"""선별 품질 평가 (개발 도구, 운영 비포함).

시드 데이터로 채점을 돌려 결과를 표로 본다. config/interests.md나
pipeline/rank.py의 프롬프트를 고친 뒤 다시 돌려 비교하는 것이 튜닝 작업이다.

실행:
  python -m pipeline.evaluate                # 시드에서 40건 표본
  python -m pipeline.evaluate --limit 80     # 표본 크기 변경
  python -m pipeline.evaluate --date 2026-11-10   # 특정 날짜 데이터로
"""

import argparse
import random

from pipeline.lib.config import load_interests, load_sources
from pipeline.lib.llm import AnthropicLLM
from pipeline.lib.secrets import require
from pipeline.lib.store import LocalStore
from pipeline.models import RankedItem, RawBundle, RawItem
from pipeline.rank import rank
from pipeline.seed import SEED_DIR

# 고정 시드. 표본이 매번 달라지면 프롬프트 변경 효과를 분리할 수 없다.
SAMPLE_SEED = 20261110
DEFAULT_LIMIT = 40


def sample_items(items: list[RawItem], *, limit: int = DEFAULT_LIMIT) -> list[RawItem]:
    """재현 가능한 표본을 뽑는다."""
    if len(items) <= limit:
        return list(items)
    # Random(seed)는 전역 난수 상태를 건드리지 않는 독립 생성기를 만든다.
    return random.Random(SAMPLE_SEED).sample(items, limit)


def format_table(selected: list[RankedItem]) -> str:
    """선별 결과를 읽기 좋은 표로 만든다."""
    if not selected:
        return "(선별된 항목이 없다)"

    lines = [
        f"{'점수':>4}  {'주제':<8}  {'소스':<22}  제목",
        "-" * 100,
    ]
    for item in selected:
        lines.append(
            f"{item.score:>4}  {item.topic:<8}  "
            f"{item.item.source[:22]:<22}  {item.item.title[:44]}"
        )
        lines.append(f"      └ {item.reason[:90]}")

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

    print(format_table(bundle.selected))
    print()

    # 하위권도 봐야 한다 — "왜 이게 떨어졌나"가 프롬프트 수정의 단서다.
    lowest = sorted(bundle.all_scores, key=lambda s: s.score)[:10]
    print("최하위 10건 (탈락 이유 확인용)")
    print("-" * 100)
    for score in lowest:
        title = items[score.index].title[:50]
        print(f"{score.score:>4}  {title}")
        print(f"      └ {score.reason[:90]}")


if __name__ == "__main__":
    main()
```

> **설명** — `argparse`는 명령행 인자를 파싱하는 표준 라이브러리다. `--limit 80`처럼 받은 값을 `args.limit`으로 쓴다. f-string의 `{값:>4}`는 너비 4로 오른쪽 정렬, `{값:<8}`은 왼쪽 정렬이다. `random.Random(seed)`로 생성기를 따로 만드는 이유는, `random.sample`을 직접 쓰면 전역 난수 상태를 바꿔 다른 코드의 재현성에 영향을 주기 때문이다.

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_evaluate.py
```

Expected: `6 passed`

- [ ] **Step 5: 실제 시드 데이터로 선별을 돌려본다**

```bash
python -m pipeline.evaluate --limit 40
```

Expected: 상위 10건의 점수·주제·소스·제목·이유가 표로 나오고, 최하위 10건이 이어서 나온다.

- [ ] **Step 6: 관심사 프로필을 튜닝한다 (반복)**

출력을 보면서 다음을 확인한다.

- 상위권에 **보도자료 재가공 기사나 마케팅 글**이 있는가 → `config/interests.md`의 "낮게 평가" 항목에 그 패턴을 구체적으로 추가한다
- 하위권에 **읽고 싶은 글**이 있는가 → "높게 평가" 항목에 그 특징을 추가한다
- 점수가 60~80에 몰려 있는가 → 프로필의 기준이 모호하다는 뜻이다. 구체적인 예시를 늘린다

고친 뒤 다시 돌린다. **입력 표본이 고정이므로 프롬프트 변경 효과만 비교된다.**

상위 10건 중 8건 이상이 "읽고 싶다"가 될 때까지 반복한다. 보통 5~15회다.

- [ ] **Step 7: 커밋**

```bash
git add pipeline/evaluate.py tests/test_evaluate.py config/interests.md
git commit -m "feat: 선별 품질 평가 도구 + 관심사 프로필 튜닝"
```

---

## Task 16: 본문 확보

외부 크롤링은 구조적으로 가장 자주 깨지는 단계이면서, 폴백이 존재하는 유일한 단계다. **절대 중단하지 않는다.**

**Files:**
- Create: `pipeline/enrich.py`
- Create: `tests/fixtures/article.html`
- Create: `tests/test_enrich.py`

- [ ] **Step 1: HTML fixture 작성**

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
    <p>결제 서버의 P99 지연이 400ms였다. 사용자 이탈의 직접 원인이었다.</p>
    <p>프로파일링 결과 커넥션 풀 고갈이 병목이었다. 풀 크기를 늘리는 것은
       근본 해결이 아니었고, 실제 원인은 트랜잭션 경계가 너무 넓은 것이었다.</p>
    <p>트랜잭션을 쪼갠 뒤 P99는 40ms로 떨어졌다. 교훈은 풀 크기보다
       트랜잭션 수명을 먼저 보라는 것이다.</p>
  </article>
  <footer>© 2026 Example Corp. 모든 권리 보유.</footer>
</body>
</html>
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_enrich.py`:

```python
from pathlib import Path

from pipeline.enrich import BODY_MAX_CHARS, enrich, extract_body
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


# --- 본문 추출 ---

def test_본문을_추출한다():
    html = (FIXTURES / "article.html").read_bytes()
    body = extract_body(html)

    assert body is not None
    assert "커넥션 풀 고갈이 병목" in body


def test_내비게이션과_광고와_푸터를_걸러낸다():
    html = (FIXTURES / "article.html").read_bytes()
    body = extract_body(html)

    assert "채용" not in body
    assert "10만원 할인" not in body
    assert "모든 권리 보유" not in body


def test_본문이_없는_HTML은_None을_돌려준다():
    assert extract_body(b"<html><body><nav>메뉴</nav></body></html>") is None


def test_HTML이_아니면_None을_돌려준다():
    assert extract_body(b"\x00\x01\x02") is None


# --- 확보 ---

def _enrich(items, fetch=None, sleeps=None):
    html = (FIXTURES / "article.html").read_bytes()
    recorded: list[float] = [] if sleeps is None else sleeps
    return enrich(
        ranked=_bundle(items),
        fetch=fetch or (lambda url: html),
        sleep=recorded.append,
    ), recorded


def test_본문을_확보하고_출처를_기록한다():
    bundle, _ = _enrich([_ranked()])

    assert len(bundle.articles) == 1
    assert bundle.articles[0].body_source == "trafilatura"
    assert "트랜잭션" in bundle.articles[0].body


def test_추출_실패시_RSS_발췌로_폴백한다():
    """핵심 요구사항. 한 건 실패로 파이프라인이 죽지 않는다."""
    bundle, _ = _enrich(
        [_ranked(excerpt="발췌로 대체된다")],
        fetch=lambda url: b"<html><body><nav>메뉴만</nav></body></html>",
    )

    assert bundle.articles[0].body == "발췌로 대체된다"
    assert bundle.articles[0].body_source == "rss_excerpt"


def test_HTTP_실패시에도_발췌로_폴백한다():
    def fetch(url: str) -> bytes:
        raise RuntimeError("403 Forbidden")

    bundle, _ = _enrich([_ranked(excerpt="발췌")], fetch=fetch)

    assert bundle.articles[0].body == "발췌"
    assert bundle.articles[0].body_source == "rss_excerpt"


def test_본문도_발췌도_없으면_그_건만_제외한다():
    """요약할 재료가 전혀 없으면 보낼 수 없다. 중단은 하지 않는다."""
    def fetch(url: str) -> bytes:
        raise RuntimeError("실패")

    bundle, _ = _enrich([_ranked(excerpt=""), _ranked(1, "발췌 있음")], fetch=fetch)

    assert len(bundle.articles) == 1
    assert bundle.articles[0].body == "발췌 있음"


def test_본문을_상한에서_자른다():
    long_html = ("<html><body><article><p>" + "가" * 20000
                 + "</p></article></body></html>").encode("utf-8")
    bundle, _ = _enrich([_ranked()], fetch=lambda url: long_html)

    assert len(bundle.articles[0].body) <= BODY_MAX_CHARS


def test_요청_사이에_간격을_둔다():
    """상대 서버에 부담을 주지 않는다."""
    bundle, sleeps = _enrich([_ranked(0), _ranked(1), _ranked(2)])

    # 3건이면 2번 쉰다 (마지막 뒤에는 쉬지 않는다)
    assert len(sleeps) == 2
    assert all(delay >= 1.0 for delay in sleeps)


def test_선별_결과가_비면_요청하지_않는다():
    calls = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return b""

    bundle, _ = _enrich([], fetch=fetch)

    assert bundle.articles == []
    assert calls == []


def test_윈도우_경계를_이어받는다():
    bundle, _ = _enrich([_ranked()])
    assert bundle.window_start == WINDOW[0]
    assert bundle.window_end == WINDOW[1]
```

- [ ] **Step 3: 실패를 확인**

```bash
pytest tests/test_enrich.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.enrich'`

- [ ] **Step 4: 최소 구현 작성**

`pipeline/enrich.py`:

```python
"""03 본문: 선별된 글의 본문을 가져온다.

이 단계는 절대 중단하지 않는다. 외부 사이트 크롤링은 구조적으로 가장 자주
깨지는 반면, 폴백(RSS 발췌)이 존재하는 유일한 단계이기도 하다.
품질 저하가 전송 실패보다 낫다.

실행: python -m pipeline.enrich
"""

import time
from datetime import datetime, timezone
from typing import Callable

import httpx
import trafilatura

from pipeline.lib.store import LocalStore
from pipeline.lib.timeutil import KST
from pipeline.models import Article, ArticlesBundle, RankedBundle

# 이 이상은 요약 품질에 기여하지 않으면서 토큰만 쓴다.
BODY_MAX_CHARS = 8000

# 상대 서버 부담을 줄이는 요청 간격(초).
REQUEST_DELAY = 1.5

HTTP_TIMEOUT = 20.0
USER_AGENT = "briefing-bot/0.1"

FetchFn = Callable[[str], bytes]
SleepFn = Callable[[float], None]


def http_fetch(url: str) -> bytes:
    response = httpx.get(
        url,
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return response.content


def extract_body(payload: bytes) -> str | None:
    """HTML에서 본문만 뽑는다. 실패하면 None."""
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

    if not text or not text.strip():
        return None
    return text.strip()


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
        body: str | None = None

        try:
            body = extract_body(fetch(item.item.url))
        except Exception:  # noqa: BLE001 — HTTP 실패도 폴백 대상이다
            body = None

        if body is not None:
            source = "trafilatura"
        else:
            # 폴백: RSS 발췌. 얕지만 요약은 된다.
            body = item.item.excerpt.strip()
            source = "rss_excerpt"

        if not body:
            # 본문도 발췌도 없으면 요약할 재료가 없다. 이 건만 제외한다.
            continue

        articles.append(Article(
            ranked=item,
            body=body[:BODY_MAX_CHARS],
            body_source=source,
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

    fallbacks = sum(1 for a in bundle.articles if a.body_source == "rss_excerpt")
    print(f"본문 확보 {len(bundle.articles)}건 → {path}")
    if fallbacks:
        print(f"  경고: {fallbacks}건은 RSS 발췌로 폴백됨 (요약 품질 저하)")
    for article in bundle.articles:
        mark = "발췌" if article.body_source == "rss_excerpt" else "본문"
        print(f"  [{mark}] {len(article.body):5d}자  {article.ranked.item.title[:45]}")


if __name__ == "__main__":
    main()
```

> **설명** — `trafilatura.extract`는 HTML에서 본문을 추출한다. `favor_precision=True`는 "확실한 본문만" 뽑으므로 광고가 섞일 위험이 줄어든다. `time.sleep`을 인자로 받는 이유는 테스트에서 실제로 기다리지 않게 하려는 것이다 — 테스트는 `list.append`를 넘겨 "몇 번, 얼마나 쉬려 했는지"만 기록한다. `sum(1 for x in xs if 조건)`은 조건을 만족하는 개수를 세는 관용구다.

- [ ] **Step 5: 통과를 확인**

```bash
pytest tests/test_enrich.py
```

Expected: `12 passed`

- [ ] **Step 6: 커밋**

```bash
git add pipeline/enrich.py tests/test_enrich.py tests/fixtures/article.html
git commit -m "feat: 본문 확보 단계 — 발췌 폴백, 중단 없음, 요청 간격"
```

---

## Task 17: 요약과 최종 선정

**Files:**
- Create: `pipeline/summarize.py`
- Create: `tests/test_summarize.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_summarize.py`:

```python
from pipeline.models import (
    Article,
    ArticlesBundle,
    RankedItem,
    RawItem,
    SummaryDraft,
    SummarySheet,
)
from pipeline.summarize import MAX_SUMMARIES, SCORE_THRESHOLD, build_prompt, summarize
from tests.fakes import FakeLLM

WINDOW = ("2026-11-09T22:20:00+00:00", "2026-11-10T22:20:00+00:00")


def _article(index: int = 0, score: int = 85, lang_source: str = "토스_기술블로그") -> Article:
    return Article(
        ranked=RankedItem(
            item=RawItem(
                source=lang_source,
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


# --- 프롬프트 ---

def test_프롬프트에_본문이_들어간다():
    prompt = build_prompt(articles=[_article()])
    assert "본문 0" in prompt


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


# --- 요약 ---

def _summarize(articles, drafts):
    llm = FakeLLM(responses=[SummarySheet(summaries=drafts)])
    return summarize(articles=_bundle(articles), llm=llm), llm


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


def test_후보_건수를_기록한다():
    """적중률 추적에 쓴다."""
    briefing, _ = _summarize([_article(0), _article(1)], [_draft(0)])
    assert briefing.considered == 2


def test_본문이_없으면_LLM을_호출하지_않는다():
    llm = FakeLLM(responses=[])
    briefing = summarize(articles=_bundle([]), llm=llm)

    assert briefing.summaries == []
    assert llm.prompts == []


def test_전부_임계값_미달이면_빈_브리핑이_된다():
    """0건이 정상 상태다. 예외를 던지지 않는다."""
    low = [_article(i, score=10) for i in range(3)]
    briefing, _ = _summarize(low, [_draft(0), _draft(1), _draft(2)])

    assert briefing.summaries == []
    assert briefing.considered == 3
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_summarize.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.summarize'`

- [ ] **Step 3: 최소 구현 작성**

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

from pipeline.lib.llm import LLM, AnthropicLLM, Effort, retrying
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
SCORE_THRESHOLD = 60

# 상한. 카톡에는 이 중 상위 5건만 싣고 나머지는 "외 N건"으로 표기한다.
MAX_SUMMARIES = 7

SUMMARIZE_EFFORT: Effort = "medium"


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
    sheet, _tokens = retrying(
        lambda: llm.parse(
            prompt=prompt, output_format=SummarySheet, effort=SUMMARIZE_EFFORT
        )
    )

    summaries: list[Summary] = []
    seen: set[int] = set()

    for draft in sheet.summaries:
        if not (0 <= draft.index < len(candidates)) or draft.index in seen:
            continue
        seen.add(draft.index)

        article = candidates[draft.index]

        # 결정적 가드: LLM 판단과 별개로 점수 하한을 적용한다.
        if article.ranked.score < SCORE_THRESHOLD:
            continue

        summaries.append(Summary(
            article=article,
            headline=draft.headline,
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
    for summary in briefing.summaries:
        print(f"  {summary.article.ranked.score:3d}  {summary.headline}")
        for bullet in summary.bullets:
            print(f"       - {bullet[:70]}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_summarize.py
```

Expected: `17 passed`

- [ ] **Step 5: 커밋**

```bash
git add pipeline/summarize.py tests/test_summarize.py
git commit -m "feat: 요약 단계 — 임계값 기반 건수, 한국어 출력, 건수 채우기 금지"
```

---

## Task 18: 슬랙 메시지 조립

**Files:**
- Create: `pipeline/lib/slack.py`
- Create: `tests/test_slack.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_slack.py`:

```python
import json

import pytest

from pipeline.lib.slack import SlackError, build_blocks, send
from pipeline.models import (
    Article,
    Briefing,
    RankedItem,
    RawItem,
    Summary,
)

WINDOW = ("2026-11-09T22:20:00+00:00", "2026-11-10T22:20:00+00:00")


def _summary(index: int = 0, fallback: bool = False) -> Summary:
    return Summary(
        article=Article(
            ranked=RankedItem(
                item=RawItem(
                    source="토스_기술블로그",
                    title=f"원제 {index}",
                    url=f"https://toss.tech/a/{index}",
                    published="2026-11-10T05:30:00+00:00",
                    excerpt="발췌",
                ),
                score=85, reason="이유", topic="backend",
            ),
            body="본문",
            body_source="rss_excerpt" if fallback else "trafilatura",
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


def _text(blocks) -> str:
    """블록 전체를 문자열로 만들어 포함 여부를 검사한다."""
    return json.dumps(blocks, ensure_ascii=False)


def test_헤드라인과_링크가_들어간다():
    blocks = build_blocks(_briefing([_summary()]))
    text = _text(blocks)

    assert "헤드라인 0" in text
    assert "https://toss.tech/a/0" in text


def test_요점과_중요한_이유가_들어간다():
    text = _text(build_blocks(_briefing([_summary()])))

    assert "첫 요점" in text
    assert "둘째 요점" in text
    assert "중요한 이유" in text


def test_출처가_들어간다():
    text = _text(build_blocks(_briefing([_summary()])))
    assert "토스_기술블로그" in text


def test_건수를_헤더에_표시한다():
    blocks = build_blocks(_briefing([_summary(0), _summary(1)]))
    assert "2건" in _text(blocks)


def test_전체_건수를_다_담는다():
    """슬랙은 읽기용이므로 카톡과 달리 전부 넣는다."""
    blocks = build_blocks(_briefing([_summary(i) for i in range(7)]))
    text = _text(blocks)

    for index in range(7):
        assert f"헤드라인 {index}" in text


def test_0건이면_그렇게_알린다():
    """조용히 넘어가면 시스템이 죽은 것과 구분되지 않는다."""
    blocks = build_blocks(_briefing([], considered=8))
    text = _text(blocks)

    assert len(blocks) > 0
    assert "없" in text


def test_발췌_폴백이_있으면_하단에_경고한다():
    """품질 저하를 알 수 있어야 한다."""
    blocks = build_blocks(_briefing([_summary(0, fallback=True), _summary(1)]))
    text = _text(blocks)

    assert "발췌" in text


def test_폴백이_없으면_경고하지_않는다():
    text = _text(build_blocks(_briefing([_summary(0), _summary(1)])))
    assert "발췌로" not in text


def test_블록이_슬랙_상한을_넘지_않는다():
    """슬랙 메시지의 블록 수 상한은 50이다."""
    blocks = build_blocks(_briefing([_summary(i) for i in range(7)]))
    assert len(blocks) <= 50


# --- 전송 ---

def test_웹훅으로_블록을_보낸다():
    sent = {}

    def post(url: str, payload: dict) -> int:
        sent["url"] = url
        sent["payload"] = payload
        return 200

    send(webhook_url="https://hooks.slack.com/x", blocks=[{"type": "divider"}], post=post)

    assert sent["url"] == "https://hooks.slack.com/x"
    assert sent["payload"]["blocks"] == [{"type": "divider"}]


def test_알림용_text가_함께_간다():
    """text가 없으면 폰 알림에 내용이 안 뜬다."""
    sent = {}

    def post(url: str, payload: dict) -> int:
        sent["payload"] = payload
        return 200

    send(webhook_url="https://h/x", blocks=[], post=post, notification_text="IT 브리핑")

    assert sent["payload"]["text"] == "IT 브리핑"


def test_실패_응답이면_예외를_던진다():
    def post(url: str, payload: dict) -> int:
        return 403

    with pytest.raises(SlackError, match="403"):
        send(webhook_url="https://h/x", blocks=[], post=post)
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_slack.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.slack'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/lib/slack.py`:

```python
"""슬랙 Block Kit 메시지 조립과 전송.

슬랙은 길이 제약이 넉넉하므로 전체 건수를 다 담는다 — 실제로 읽는 채널이다.
(카카오톡은 200자 제약 때문에 상위 5건 목록만 싣는다. 계획 3에서 다룬다.)
"""

from datetime import datetime
from typing import Callable

import httpx

from pipeline.lib.timeutil import KST
from pipeline.models import Briefing

# 슬랙 메시지 하나의 블록 수 상한.
MAX_BLOCKS = 50

HTTP_TIMEOUT = 15.0

PostFn = Callable[[str, dict], int]


class SlackError(RuntimeError):
    """슬랙 전송 실패."""


def _topic_emoji(topic: str) -> str:
    return {
        "AI": "🤖",
        "backend": "⚙️",
        "infra": "🏗️",
        "tooling": "🔧",
    }.get(topic, "📄")


def build_blocks(briefing: Briefing) -> list[dict]:
    """브리핑을 Block Kit 블록 목록으로 바꾼다."""
    date_label = datetime.fromisoformat(briefing.window_end).astimezone(KST).strftime(
        "%m/%d (%a)"
    )
    count = len(briefing.summaries)

    if count == 0:
        # 0건도 반드시 보낸다. 안 보내면 "시스템이 죽은 것"과 구분되지 않는다.
        return [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"📡 {date_label} IT 브리핑"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"후보 {briefing.considered}건을 봤지만 "
                        f"*기준을 넘는 글이 없습니다.*\n"
                        f"조용한 날입니다 — 시스템은 정상입니다."
                    ),
                },
            },
        ]

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📡 {date_label} IT 브리핑 · {count}건"},
        }
    ]

    for summary in briefing.summaries:
        item = summary.article.ranked.item
        bullets = "\n".join(f"• {bullet}" for bullet in summary.bullets)

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                # <URL|텍스트>가 슬랙의 링크 문법이다.
                "text": (
                    f"{_topic_emoji(summary.article.ranked.topic)} "
                    f"*<{item.url}|{summary.headline}>*\n"
                    f"{bullets}\n"
                    f"_{summary.why_it_matters}_"
                ),
            },
        })
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"{item.source}  ·  {summary.article.ranked.score}점",
            }],
        })

    # 폴백이 섞였으면 하단에 알린다. 품질 저하를 모르고 넘어가면 안 된다.
    fallbacks = sum(
        1 for s in briefing.summaries if s.article.body_source == "rss_excerpt"
    )
    if fallbacks:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"⚠️ {fallbacks}건은 본문 추출 실패로 RSS 발췌만 요약했습니다.",
            }],
        })

    # 상한을 넘으면 뒤에서 자른다. 건당 2블록 + 헤더 1이라 7건이면 15블록이므로
    # 실제로는 걸리지 않지만, 상한을 코드로 보장해 둔다.
    return blocks[:MAX_BLOCKS]


def http_post(url: str, payload: dict) -> int:
    response = httpx.post(url, json=payload, timeout=HTTP_TIMEOUT)
    return response.status_code


def send(
    *,
    webhook_url: str,
    blocks: list[dict],
    post: PostFn = http_post,
    notification_text: str = "IT 브리핑",
) -> None:
    """Incoming Webhook으로 보낸다."""
    # text는 폰 알림과 블록 미지원 클라이언트의 폴백으로 쓰인다.
    # 없으면 알림에 "새 메시지"만 뜬다.
    payload = {"text": notification_text, "blocks": blocks}

    status = post(webhook_url, payload)
    if status != 200:
        raise SlackError(f"슬랙 전송 실패: HTTP {status}")
```

> **설명** — `dict.get(key, default)`로 이모지를 고르는 패턴은 if/elif 사슬보다 짧고 읽기 쉽다. `strftime("%m/%d (%a)")`는 시각을 "11/10 (Tue)" 형태의 문자열로 만든다. Block Kit에서 `mrkdwn`은 슬랙 전용 마크다운으로, 링크가 `<URL|텍스트>` 문법이고 기울임은 `_텍스트_`다(일반 마크다운과 다르다).

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_slack.py
```

Expected: `12 passed`

- [ ] **Step 5: 슬랙 Webhook을 만든다**

1. https://api.slack.com/apps → Create New App → From scratch
2. 앱 이름 `IT 브리핑`, 워크스페이스 선택
3. Incoming Webhooks → Activate 켜기 → Add New Webhook to Workspace
4. 브리핑을 받을 채널 선택 (전용 채널 권장: `#it-briefing`)
5. Webhook URL을 복사해 `.env`의 `SLACK_WEBHOOK_URL`에 넣는다

- [ ] **Step 6: 커밋**

```bash
git add pipeline/lib/slack.py tests/test_slack.py
git commit -m "feat: 슬랙 Block Kit 메시지 조립 (0건 알림, 폴백 경고 포함)"
```

---

## Task 19: 전송과 실행 이력

**Files:**
- Create: `pipeline/notify.py`
- Create: `tests/test_notify.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_notify.py`:

```python
from datetime import datetime, timezone

import pytest

from pipeline.models import (
    Article,
    Briefing,
    RankedItem,
    RawBundle,
    RawItem,
    SourceError,
    Summary,
)
from pipeline.notify import AlreadySentError, notify
from tests.fakes import FakeRemoteStore

WINDOW_START = datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 11, 10, 22, 20, tzinfo=timezone.utc)


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


def _raw() -> RawBundle:
    return RawBundle(
        window_start=WINDOW_START.isoformat(),
        window_end=WINDOW_END.isoformat(),
        items=[],
        source_counts={"토스_기술블로그": 3, "조용한소스": 0},
        errors=[SourceError(source="깨진소스", message="RuntimeError: 403")],
    )


def _notify(briefing, raw=None, store=None, force=False, sent=None):
    sent_payloads = [] if sent is None else sent
    remote = store or FakeRemoteStore()

    notify(
        briefing=briefing,
        raw=raw or _raw(),
        remote=remote,
        briefing_date="2026-11-10",
        send_slack=lambda blocks, text: sent_payloads.append((blocks, text)),
        force=force,
    )
    return remote, sent_payloads


def test_슬랙으로_보낸다():
    _, sent = _notify(_briefing([_summary()]))
    assert len(sent) == 1


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


def test_수집_에러를_이력에_남긴다():
    remote, _ = _notify(_briefing([_summary()]))

    assert len(remote.runs[0]["errors"]) == 1
    assert remote.runs[0]["errors"][0]["source"] == "깨진소스"


def test_0건이어도_보내고_이력을_남긴다():
    """이력을 남기지 않으면 다음 윈도우가 계속 늘어난다."""
    remote, sent = _notify(_briefing([]))

    assert len(sent) == 1
    assert len(remote.runs) == 1
    assert remote.runs[0]["published_count"] == 0


def test_0건이면_글을_저장하지_않는다():
    remote, _ = _notify(_briefing([]))
    assert remote.saved == []


def test_이미_보낸_윈도우는_다시_보내지_않는다():
    """cron 중복 실행이나 수동 재실행으로 두 번 오는 것을 막는다."""
    store = FakeRemoteStore(last_sent=WINDOW_END)

    with pytest.raises(AlreadySentError):
        _notify(_briefing([_summary()]), store=store)


def test_더_늦은_발송_이력이_있으면_거부한다():
    later = datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)
    store = FakeRemoteStore(last_sent=later)

    with pytest.raises(AlreadySentError):
        _notify(_briefing([_summary()]), store=store)


def test_force면_이미_보냈어도_다시_보낸다():
    store = FakeRemoteStore(last_sent=WINDOW_END)
    _, sent = _notify(_briefing([_summary()]), store=store, force=True)

    assert len(sent) == 1


def test_이전_윈도우의_이력은_막지_않는다():
    earlier = datetime(2026, 11, 9, 22, 20, tzinfo=timezone.utc)
    store = FakeRemoteStore(last_sent=earlier)
    _, sent = _notify(_briefing([_summary()]), store=store)

    assert len(sent) == 1


def test_슬랙_전송이_실패하면_이력을_남기지_않는다():
    """이력을 먼저 남기면, 전송 실패 후 재실행이 '이미 보냄'으로 막힌다."""
    remote = FakeRemoteStore()

    def failing_send(blocks, text):
        raise RuntimeError("웹훅 404")

    with pytest.raises(RuntimeError, match="웹훅"):
        notify(
            briefing=_briefing([_summary()]),
            raw=_raw(),
            remote=remote,
            briefing_date="2026-11-10",
            send_slack=failing_send,
            force=False,
        )

    assert remote.runs == []


def test_알림_텍스트에_건수가_들어간다():
    _, sent = _notify(_briefing([_summary(0), _summary(1)]))
    _blocks, text = sent[0]

    assert "2건" in text
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_notify.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.notify'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/notify.py`:

```python
"""06 전송: 슬랙으로 보내고 실행 이력을 남긴다.

순서가 중요하다 — **전송에 성공한 뒤에 이력을 남긴다.** 거꾸로 하면 전송이
실패했는데 "이미 보냄"으로 기록되어, 재실행이 막히고 그날 브리핑이 사라진다.

실행:
  python -m pipeline.notify
  python -m pipeline.notify --force    # 이미 보낸 윈도우를 다시 보낸다
"""

import argparse
from datetime import datetime, timezone
from typing import Callable

from pipeline.lib.secrets import require
from pipeline.lib.slack import build_blocks, send
from pipeline.lib.store import LocalStore, RemoteStore, SupabaseStore
from pipeline.lib.timeutil import KST
from pipeline.models import Briefing, RawBundle

SendSlackFn = Callable[[list[dict], str], None]


class AlreadySentError(RuntimeError):
    """이 윈도우는 이미 전송됐다. --force로 우회할 수 있다."""


def notify(
    *,
    briefing: Briefing,
    raw: RawBundle,
    remote: RemoteStore,
    briefing_date: str,
    send_slack: SendSlackFn,
    force: bool = False,
) -> None:
    """전송하고 이력을 남긴다. 0건도 전송한다."""
    window_start = datetime.fromisoformat(briefing.window_start)
    window_end = datetime.fromisoformat(briefing.window_end)

    if not force:
        last = remote.last_sent_at()
        if last is not None and last >= window_end:
            raise AlreadySentError(
                f"이 윈도우(~{window_end.isoformat()})는 이미 전송됐다 "
                f"(마지막 발송: {last.isoformat()}). "
                f"다시 보내려면 --force를 쓴다."
            )

    count = len(briefing.summaries)
    label = f"{count}건" if count else "보낼 글 없음"
    notification = f"📡 IT 브리핑 · {label}"

    # 전송을 먼저 한다. 실패하면 예외가 올라가고 이력은 남지 않는다.
    send_slack(build_blocks(briefing), notification)

    if briefing.summaries:
        remote.save_articles(
            briefing_date=briefing_date,
            summaries=briefing.summaries,
        )

    # 0건이어도 반드시 남긴다. 남기지 않으면 다음 윈도우가 계속 늘어나
    # 같은 항목을 반복 평가하게 된다.
    remote.record_run(
        window_start=window_start,
        window_end=window_end,
        published_count=count,
        source_counts=raw.source_counts,
        input_tokens=None,
        errors=[error.model_dump() for error in raw.errors],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="브리핑 전송")
    parser.add_argument("--force", action="store_true",
                        help="이미 전송한 윈도우를 다시 보낸다")
    args = parser.parse_args()

    date = datetime.now(timezone.utc).astimezone(KST).date().isoformat()
    store = LocalStore(date=date)
    webhook = require("SLACK_WEBHOOK_URL")

    notify(
        briefing=store.read("briefing", Briefing),
        raw=store.read("raw", RawBundle),
        remote=SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SERVICE_KEY")),
        briefing_date=date,
        send_slack=lambda blocks, text: send(
            webhook_url=webhook, blocks=blocks, notification_text=text
        ),
        force=args.force,
    )

    print(f"전송 완료 ({date})")


if __name__ == "__main__":
    main()
```

> **설명** — `action="store_true"`는 `--force`가 있으면 `True`, 없으면 `False`가 되는 플래그를 만든다(값을 받지 않는다). `last >= window_end` 비교가 가능한 이유는 두 값이 모두 타임존을 가진 aware datetime이기 때문이다 — Task 3에서 naive를 막아둔 이유다.

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_notify.py
```

Expected: `13 passed`

- [ ] **Step 5: 커밋**

```bash
git add pipeline/notify.py tests/test_notify.py
git commit -m "feat: 전송 단계 — 멱등성, 0건 전송, 전송 성공 후 이력 기록"
```

---

## Task 20: 중간 산출물 정리

스펙 7.5의 "`data/` 90일 경과분 삭제" 항목이다. 날짜 디렉터리가 무한 증식하는 것을 막는다.

**Files:**
- Create: `pipeline/prune.py`
- Create: `tests/test_prune.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_prune.py`:

```python
from datetime import date

from pipeline.prune import RETENTION_DAYS, SEED_DIR, expired_dirs


def test_보존_기간을_넘긴_디렉터리를_고른다():
    today = date(2026, 11, 10)
    names = ["2026-11-09", "2026-08-01", "2026-01-01"]

    assert expired_dirs(names, today=today) == ["2026-08-01", "2026-01-01"]


def test_경계일은_남긴다():
    today = date(2026, 11, 10)
    boundary = (today.toordinal() - RETENTION_DAYS)
    name = date.fromordinal(boundary).isoformat()

    assert expired_dirs([name], today=today) == []


def test_시드_디렉터리는_절대_지우지_않는다():
    """다시 만들 수 없는 데이터다."""
    assert expired_dirs([SEED_DIR], today=date(2030, 1, 1)) == []


def test_날짜가_아닌_이름은_건너뛴다():
    assert expired_dirs(["backup", ".DS_Store"], today=date(2026, 11, 10)) == []


def test_빈_목록도_처리한다():
    assert expired_dirs([], today=date(2026, 11, 10)) == []
```

- [ ] **Step 2: 실패를 확인**

```bash
pytest tests/test_prune.py
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.prune'`

- [ ] **Step 3: 최소 구현 작성**

`pipeline/prune.py`:

```python
"""중간 산출물 정리: data/의 오래된 날짜 디렉터리를 지운다.

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
    """보존 기간을 넘긴 날짜 디렉터리 이름을 돌려준다."""
    cutoff = today.toordinal() - RETENTION_DAYS
    expired: list[str] = []

    for name in names:
        # 시드는 RSS에서 다시 얻을 수 없다. 어떤 경우에도 지우지 않는다.
        if name == SEED_DIR:
            continue
        try:
            when = date.fromisoformat(name)
        except ValueError:
            # 날짜 형식이 아닌 디렉터리는 건드리지 않는다.
            continue
        if when.toordinal() < cutoff:
            expired.append(name)

    return expired


def main() -> None:
    parser = argparse.ArgumentParser(description="오래된 중간 산출물 정리")
    parser.add_argument("--dry-run", action="store_true", help="지울 목록만 출력")
    args = parser.parse_args()

    root = Path(DEFAULT_ROOT)
    if not root.exists():
        print(f"{root}가 없다. 정리할 것이 없다.")
        return

    names = sorted(entry.name for entry in root.iterdir() if entry.is_dir())
    targets = expired_dirs(names, today=date.today())

    if not targets:
        print(f"보존 기간({RETENTION_DAYS}일)을 넘긴 디렉터리가 없다.")
        return

    for name in targets:
        if args.dry_run:
            print(f"[지울 대상] {root / name}")
        else:
            # shutil.rmtree는 디렉터리와 그 안의 모든 것을 지운다.
            shutil.rmtree(root / name)
            print(f"[삭제] {root / name}")

    if args.dry_run:
        print(f"\n{len(targets)}개가 대상이다. --dry-run 없이 실행하면 삭제된다.")


if __name__ == "__main__":
    main()
```

> **설명** — `date.toordinal()`은 날짜를 "서력 1년 1월 1일부터의 일수"인 정수로 바꾼다. 날짜 차이를 정수 비교로 처리할 수 있어 월말·윤년 계산이 필요 없다. `Path.iterdir()`는 디렉터리 안의 항목을 순회한다.

- [ ] **Step 4: 통과를 확인**

```bash
pytest tests/test_prune.py
```

Expected: `5 passed`

- [ ] **Step 5: 실제로 확인 (아직 지울 것이 없어야 정상)**

```bash
python -m pipeline.prune --dry-run
```

Expected: `보존 기간(90일)을 넘긴 디렉터리가 없다.`

- [ ] **Step 6: 커밋**

```bash
git add pipeline/prune.py tests/test_prune.py
git commit -m "feat: 중간 산출물 90일 정리 (시드는 보호)"
```

---

## Task 21: 엔드투엔드 검증과 사용 문서

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

Expected: `전송 완료 (YYYY-MM-DD)`

- [ ] **Step 3: 슬랙에서 실제 메시지를 확인**

확인 항목:
- 헤드라인이 링크로 걸려 원문이 열리는가
- 요점이 읽을 만한가
- 출처와 점수가 보이는가
- 폰 알림에 "📡 IT 브리핑 · N건"이 뜨는가

- [ ] **Step 4: 멱등성을 확인**

```bash
python -m pipeline.notify
```

Expected: `AlreadySentError` — "이 윈도우는 이미 전송됐다 ... --force를 쓴다"

```bash
python -m pipeline.notify --force
```

Expected: 다시 전송되고 슬랙에 같은 메시지가 한 번 더 온다.

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

- [ ] **Step 7: `README.md` 작성**

````markdown
# 토픽 컬럼 자동화

매일 아침 IT 토픽을 수집·선별·요약해서 슬랙으로 받는다.

- 설계: `docs/superpowers/specs/2026-11-10-it-column-automation-design.md`
- 계획 1 (현재): 파이프라인 + 슬랙
- 계획 2 (예정): 웹페이지 + 좋아요·클릭
- 계획 3 (예정): 카카오톡 + 경고 장치 + GitHub Actions 자동화

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
python -m pipeline.notify       # 슬랙 전송
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
  0건인 날도 정상이다. 0건이어도 슬랙에 한 줄이 간다.
- **같은 윈도우는 두 번 보내지 않는다.** 다시 보내려면 `--force`.
- **본문은 Supabase의 `article_bodies`에만 있다.** 리포지토리에 커밋하지 않고
  공개 페이지에서도 읽히지 않는다. Phase 3의 RAG 재료다.
- **`data/_seed/raw.json`은 지우지 않는다.** RSS는 과거를 제공하지 않으므로
  다시 만들 수 없다. `~/briefing-seed-backup/`에 백업이 있다.
````

- [ ] **Step 8: 커밋**

```bash
git add README.md
git commit -m "docs: README — 실행 방법과 튜닝 절차"
```

---

## 완료 조건

- [ ] `pytest`가 전부 통과한다
- [ ] 파이프라인 5단계를 순차 실행하면 슬랙에 브리핑이 온다
- [ ] 슬랙 메시지의 헤드라인 링크가 원문으로 연결된다
- [ ] 같은 윈도우를 두 번 보내려 하면 거부된다
- [ ] Supabase의 `articles`와 `article_bodies` 건수가 일치한다
- [ ] anon 키로 `article_bodies`를 읽으면 권한 거부가 난다
- [ ] 두 번째 수집에서 윈도우가 좁아지고 기존 글이 걸러진다
- [ ] `python -m pipeline.evaluate`의 상위 10건 중 8건 이상이 "읽고 싶다"

---

## 다음 계획

**계획 2 (웹페이지):** `pipeline/render.py` + Vite·React·Tailwind SPA + 좋아요·클릭 저장. 끝나면 공개 URL이 생기고 폰에서 읽을 수 있다.

**계획 3 (자동화):** 카카오톡 전송(토큰 인증, 200자 제약, 상위 5건 + "외 N건") + `lib/guard.py` 경고 장치 + GitHub Actions 워크플로. 끝나면 매일 아침 자동으로 카톡이 온다.

### 계획 3에서 메워야 할 것 (의도적으로 남긴 구멍)

**`runs.input_tokens`가 항상 `NULL`이다.** `notify`가 `input_tokens=None`을 넣는다.
`AnthropicLLM.parse`는 입력 토큰 수를 돌려주지만 `rank`와 `summarize`가 그 값을
버린다(`_tokens`). 지금은 쓰는 곳이 없어서 배선하지 않았다.

계획 3의 크레딧 소진 가드가 이 값을 쓰므로 그때 다음을 한다.

- `RankedBundle`과 `Briefing`에 `input_tokens: int | None` 필드 추가
- `rank`/`summarize`가 `llm.parse`의 두 번째 반환값을 번들에 담기
- `notify`가 두 번들의 합을 `record_run`에 전달

스키마 컬럼은 이미 있으므로 마이그레이션은 필요 없다.
