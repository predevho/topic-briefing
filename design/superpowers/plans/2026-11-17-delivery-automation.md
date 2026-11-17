# 전달과 자동화 구현 계획 (계획 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매일 아침 브리핑이 카톡으로 오고, 조용히 망가지면 슬랙으로 알리고, 이 전부가 GitHub Actions에서 자동으로 돈다.

**Architecture:** `Sender` 프로토콜에 `KakaoSender`를 더한다(기존 `ConsoleSender` 옆). 슬랙은 브리핑이 아니라 **경고만** 보내는 별도 경로다. `lib/guard`가 세 가지 조용한 실패(소스 침묵·토큰 만료·크레딧 조기 소진)를 판정하고 슬랙으로 내보낸다. Actions는 재시도하지 않는다 — 실패하면 다음 날 수집 윈도우가 이틀치를 덮는다.

**Tech Stack:** Python 3.11+, httpx, pydantic, Supabase, 카카오 메시지 API, 슬랙 Incoming Webhook, GitHub Actions

**설계 스펙:** `design/superpowers/specs/2026-11-17-plan3-delivery-design.md`

---

## 시작하기 전에

### 내가 직접 해야 하는 것

**Task 7 전에** 슬랙 Webhook이 필요하고, **Task 14 전에** Actions Secrets가 필요하다. 그 전까지는 코드만 쓸 수 있고 검증이 안 된다.

| 항목 | 언제 필요한가 | 상태 |
|---|---|---|
| 카카오 앱·동의항목·웹 도메인 | — | ✅ 2026-11-17 완료 |
| 카카오 `refresh_token` | — | ✅ Supabase `kakao_auth` (만료 2027-01-16) |
| **슬랙 Incoming Webhook URL** | Task 7 | ⬜ |
| **`.env`의 `MONTHLY_BUDGET_USD`** | Task 11 | ⬜ |
| **GitHub Actions Secrets 6개** | Task 14 | ⬜ |

### 계획 1의 코드를 건드린다

Task 1~3이 `llm.py`·`rank.py`·`summarize.py`·`store.py`·`notify.py`를 고친다. 전부 **완료되고 테스트가 통과하는 코드**다. 계획 2 Task 2에서 `record_run`에 `briefing_date`를 더한 것과 같은 성격이고, 같은 방식으로 테스트로 감싼다.

이유는 크레딧 가드(Task 11)가 토큰 수를 필요로 하는데 **`AnthropicLLM.parse`가 출력 토큰을 아예 돌려주지 않기 때문**이다(`pipeline/lib/llm.py:327`이 `response.usage.input_tokens`만 돌려준다). `rank`와 `summarize`는 받은 입력 토큰마저 `_tokens`로 버린다.

### 실행 순서 주의

**Task 12(가드를 notify에 연결)는 Task 8·10·11을 전부 필요로 한다.** 그 셋을 먼저 끝내면 Task 12의 커밋이 바로 돈다. 나머지는 번호대로 하면 각 커밋이 통과한다.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `pipeline/models.py` | `TokenUsage` 추가, `RankedBundle`·`Briefing`에 `tokens` 필드 |
| `pipeline/lib/llm.py` | `parse`가 `TokenUsage`를 돌려준다 |
| `pipeline/rank.py` · `summarize.py` | 토큰을 버리지 않고 번들에 싣는다 |
| `pipeline/lib/store.py` | `record_run`에 `output_tokens` |
| `pipeline/notify.py` | 토큰 배선 + 가드 호출 |
| `supabase/migrations/2026-11-17-output-tokens.sql` | `runs.output_tokens` |
| `pipeline/lib/kakao.py` | `refresh_token` → `access_token`, 토큰 회전 저장 |
| `pipeline/lib/sender.py` | `KakaoSender` 추가 |
| `pipeline/lib/slack.py` | `SlackSender` — 경고 전용 |
| `pipeline/lib/guard.py` | 침묵·토큰 만료·크레딧 |
| `pipeline/report_failure.py` | 단계 실패 리포트 |
| `pipeline/lib/config.py` | `Source`에 `quiet_tier` |
| `config/sources.yaml` | 소스 45개에 등급 배정 |
| `.github/workflows/daily.yml` | 매일 07:20 KST |

**테스트:** `tests/test_kakao.py`, `tests/test_slack.py`, `tests/test_guard.py`, 그리고 기존 `tests/test_sender.py`·`test_remote_store.py`·`test_config.py`에 추가.

---

## 요구사항 커버리지

| 요구사항 | 내용 | 태스크 |
|---|---|---|
| O6 | 카톡 텍스트 템플릿 200자, 상위 5건 + "외 N건" | Task 5 |
| O7 | 카톡 토큰 갱신 (`refresh_token_expires_in` 저장) | Task 4 |
| O8 | 슬랙은 경고 전용 (브리핑 전문 미발송) | Task 7 |
| R27 | 소스 침묵 경고는 소스별 평소 간격을 쓴다 | Task 8·9 |
| D6 | 실행 이력으로 윈도우·멱등성·소스 감지를 지탱 | Task 8이 `runs.source_counts`를 읽는다 |

---

## Task 1: `TokenUsage` — `parse`가 출력 토큰도 돌려준다

크레딧 가드의 선행 작업이다. 지금 `parse`는 입력 토큰만 돌려주고 출력 토큰은 버린다.

**Files:**
- Modify: `pipeline/models.py`
- Modify: `pipeline/lib/llm.py:85-94` (프로토콜), `:327` (반환)
- Modify: `tests/fakes.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_llm.py` 끝에 추가한다.

```python
def test_parse가_입력과_출력_토큰을_모두_돌려준다():
    """크레딧 가드가 둘 다 필요하다. 지금은 입력만 돌려주고 출력은 버린다.

    출력 토큰이 더 비싸다 — opus-5-5 기준 입력 $4 / 출력 $20 per MTok.
    출력을 빼고 세면 비용을 크게 낮잡는다.
    """
    from pipeline.models import TokenUsage

    usage = TokenUsage(input=1000, output=250)

    assert usage.input == 1000
    assert usage.output == 250
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -m pytest tests/test_llm.py::test_parse가_입력과_출력_토큰을_모두_돌려준다 -v
```

Expected: FAIL — `ImportError: cannot import name 'TokenUsage'`

- [ ] **Step 3: `pipeline/models.py`에 `TokenUsage`를 더한다**

`Topic` 정의 바로 아래, `class Contract` 앞에 넣는다.

> **`Contract`를 상속한다** — `BaseModel`이 아니다. 이 파일에는 이미
> `frozen=True, extra="forbid"`를 가진 `Contract` 기반 클래스가 있고,
> 모든 계약 모델이 그것을 쓴다. 설정을 따로 적으면 둘이 갈라진다.
> 그래서 삽입 위치도 **`Contract` 정의 뒤**다.

```python
class TokenUsage(Contract):
    """한 번의 LLM 호출이 쓴 토큰.

    **출력도 센다.** opus-5-5 기준 입력 $4 / 출력 $20 per MTok이라
    출력이 5배 비싸다 — 입력만 세면 비용을 크게 낮잡는다.

    models.py에 두는 이유: llm.py가 여기를 import해도 순환이 생기지
    않는다(이 파일은 stdlib과 pydantic만 import한다). 반대로 두면 순환이다.
    """

    input: int = Field(ge=0)
    output: int = Field(ge=0)

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        """여러 호출을 합산한다. rank와 summarize의 토큰을 더할 때 쓴다."""
        return TokenUsage(
            input=self.input + other.input,
            output=self.output + other.output,
        )
```

- [ ] **Step 4: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_llm.py::test_parse가_입력과_출력_토큰을_모두_돌려준다 -v
```

Expected: PASS

- [ ] **Step 5: 합산 테스트를 더한다**

```python
def test_토큰_사용량을_더할_수_있다():
    """rank와 summarize가 각각 쓴 것을 notify가 합쳐 기록한다."""
    from pipeline.models import TokenUsage

    total = TokenUsage(input=1000, output=250) + TokenUsage(input=40, output=900)

    assert total.input == 1040
    assert total.output == 1150
```

- [ ] **Step 6: `parse`의 반환 타입을 바꾼다**

`pipeline/lib/llm.py`:

```python
from pipeline.models import TokenUsage
```

프로토콜(85~94행):

```python
    def parse(
        self,
        *,
        prompt: str,
        output_format: type[TOut],
        effort: Effort,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> tuple[TOut, TokenUsage]:
        """구조화된 출력을 받는다. (파싱된 결과, 토큰 사용량)을 돌려준다."""
        ...
```

`AnthropicLLM.parse`와 `_parse_once`의 반환 주석도 `tuple[TOut, TokenUsage]`로 바꾸고, 327행을 고친다.

```python
        return parsed, TokenUsage(
            input=response.usage.input_tokens,
            output=response.usage.output_tokens,
        )
```

- [ ] **Step 7: `tests/fakes.py`의 `FakeLLM`을 맞춘다**

```python
class FakeLLM:
    """미리 준비한 응답을 순서대로 돌려준다."""

    def __init__(
        self,
        responses: list,
        input_tokens: int = 1000,
        output_tokens: int = 250,
    ) -> None:
        self._responses = list(responses)
        self._usage = TokenUsage(input=input_tokens, output=output_tokens)
        self.prompts: list[str] = []

    def parse(self, *, prompt, output_format, effort, max_tokens=16000):
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("FakeLLM에 준비된 응답이 없다. responses를 더 넣는다.")
        return self._responses.pop(0), self._usage
```

파일 위에 `from pipeline.models import TokenUsage`를 더한다.

- [ ] **Step 8: 전체 테스트**

```bash
.venv/bin/python -m pytest -q
```

Expected: **먼저 1건 실패한다.** `tests/test_llm.py::test_가짜_LLM이_인터페이스를_만족한다`가 `assert tokens > 0`으로 int를 가정하고 있다 (2026-11-17 실측).

```
TypeError: '>' not supported between instances of 'TokenUsage' and 'int'
```

계약이 바뀐 결과이므로 테스트를 새 계약에 맞춘다.

```python
    result, tokens = fake.parse(prompt="아무거나", output_format=Answer, effort="low")
    assert result.value == 7
    # parse는 이제 TokenUsage를 돌려준다 — 입력만 세면 비용을 낮잡는다.
    assert tokens.input > 0
    assert tokens.output > 0
```

고친 뒤 다시 돌린다. Expected: 399 passed (기존 397 + 새 2).

`rank`·`summarize`는 값을 `_tokens`로 버리므로 이 단계에서 깨지지 않는다 — Task 2에서 받아 쓴다.

- [ ] **Step 9: 커밋**

```bash
git add pipeline/models.py pipeline/lib/llm.py tests/fakes.py tests/test_llm.py
git commit -m "feat: parse가 입력과 출력 토큰을 모두 돌려준다"
```

---

## Task 2: `rank`·`summarize`가 토큰을 번들에 싣는다

지금 둘 다 `sheet, _tokens = llm.parse(...)`로 버린다.

**Files:**
- Modify: `pipeline/models.py` (`RankedBundle`, `Briefing`)
- Modify: `pipeline/rank.py:209`, `pipeline/summarize.py:137`
- Test: `tests/test_rank.py`, `tests/test_summarize.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_rank.py`에 추가한다.

```python
def test_선별이_쓴_토큰을_번들에_싣는다():
    """크레딧 가드가 읽는다. 버리면 나중에 복구할 방법이 없다."""
    llm = FakeLLM([_sheet(2)], input_tokens=42135, output_tokens=1820)

    bundle = run_rank(raw=_raw(2), interests="관심사", llm=llm, store=...)

    assert bundle.tokens is not None
    assert bundle.tokens.input == 42135
    assert bundle.tokens.output == 1820
```

> `_sheet`·`_raw`·`store` 인자는 그 파일의 기존 테스트가 쓰는 헬퍼와 같다. 기존 테스트 하나를 열어 같은 모양으로 맞춘다.

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_rank.py::test_선별이_쓴_토큰을_번들에_싣는다 -v
```

Expected: FAIL — `AttributeError: 'RankedBundle' object has no attribute 'tokens'`

- [ ] **Step 3: 두 번들에 필드를 더한다**

`pipeline/models.py`의 `RankedBundle`:

```python
    # 이 단계가 쓴 토큰. 크레딧 가드(계획 3)가 읽는다.
    # None은 "아직 배선되지 않은 과거 실행"이다.
    tokens: TokenUsage | None = None
```

`Briefing`에도 같은 필드를 같은 주석으로 더한다.

- [ ] **Step 4: `rank.py`와 `summarize.py`를 고친다**

`pipeline/rank.py:209`:

```python
    sheet, tokens = llm.parse(
```

그리고 `RankedBundle(...)`을 만드는 곳에 `tokens=tokens`를 더한다.

`pipeline/summarize.py:137`도 같다 — `sheet, tokens = llm.parse(`로 바꾸고 `Briefing(...)`에 `tokens=tokens`를 더한다.

- [ ] **Step 5: `summarize`에도 같은 테스트를 더한다**

```python
def test_요약이_쓴_토큰을_번들에_싣는다():
    llm = FakeLLM([_sheet(1)], input_tokens=8000, output_tokens=2400)

    briefing = run_summarize(articles=_articles(1), llm=llm, store=...)

    assert briefing.tokens is not None
    assert briefing.tokens.input == 8000
    assert briefing.tokens.output == 2400
```

- [ ] **Step 6: 전체 테스트**

```bash
.venv/bin/python -m pytest -q
```

Expected: 401 passed

- [ ] **Step 7: 커밋**

```bash
git add pipeline/models.py pipeline/rank.py pipeline/summarize.py tests/
git commit -m "feat: 선별·요약이 쓴 토큰을 번들에 싣는다"
```

---

## Task 3: `runs.output_tokens` + `notify` 배선

**Files:**
- Create: `supabase/migrations/2026-11-17-output-tokens.sql`
- Modify: `supabase/schema.sql`
- Modify: `pipeline/lib/store.py` (프로토콜과 구현, 두 곳)
- Modify: `pipeline/notify.py:70`
- Modify: `tests/fakes.py`, `tests/test_remote_store.py`, `scripts/smoke_supabase.py`
- Modify: `scripts/verify_anon_access.sh`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_remote_store.py`에 추가한다.

```python
def test_실행_이력에_출력_토큰도_남긴다():
    """크레딧 가드가 비용을 계산하려면 둘 다 필요하다.
    출력 토큰이 5배 비싸므로 빼고 세면 크게 낮잡는다.
    """
    fake = FakeRemoteStore()

    fake.record_run(
        briefing_date="2026-11-17",
        window_start=datetime(2026, 11, 16, 22, 20, tzinfo=timezone.utc),
        window_end=datetime(2026, 11, 17, 22, 20, tzinfo=timezone.utc),
        status="sent",
        sent_at=datetime(2026, 11, 17, 22, 20, tzinfo=timezone.utc),
        collected_count=240,
        considered_count=10,
        max_score=100,
        published_count=7,
        source_counts={"토스_기술블로그": 3},
        input_tokens=50135,
        output_tokens=4220,
        errors=[],
    )

    assert fake.runs[0]["input_tokens"] == 50135
    assert fake.runs[0]["output_tokens"] == 4220
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_remote_store.py::test_실행_이력에_출력_토큰도_남긴다 -v
```

Expected: FAIL — `TypeError: record_run() got an unexpected keyword argument 'output_tokens'`

- [ ] **Step 3: `record_run`에 `output_tokens`를 더한다**

`pipeline/lib/store.py`의 **두 곳**(프로토콜과 `SupabaseStore`)에서 `input_tokens` 바로 아래에 넣는다.

```python
        input_tokens: int | None,
        output_tokens: int | None,
```

`SupabaseStore`의 insert 페이로드에도 `"output_tokens": output_tokens,`를 더한다.

- [ ] **Step 4: 호출하는 네 곳을 고친다**

```bash
grep -rn 'record_run' pipeline/ scripts/ tests/
```

- `pipeline/notify.py` — 아래 Step 5에서 함께
- `scripts/smoke_supabase.py` — `output_tokens=None,`
- `tests/fakes.py` — 시그니처와 기록 dict
- `tests/test_remote_store.py` — 기존 호출 세 곳

- [ ] **Step 5: `notify.py`가 실제 토큰을 넘긴다**

`pipeline/notify.py`의 `record` 클로저에서 `input_tokens=None,`을 지우고 넣는다.

```python
            input_tokens=totals.input if totals else None,
            output_tokens=totals.output if totals else None,
```

`record` 정의 바로 위에 합산을 둔다.

```python
    # rank와 summarize가 쓴 것을 합친다. 과거 실행은 둘 다 None일 수 있다.
    totals = None
    if ranked.tokens and briefing.tokens:
        totals = ranked.tokens + briefing.tokens
    elif ranked.tokens or briefing.tokens:
        totals = ranked.tokens or briefing.tokens
```

- [ ] **Step 6: 마이그레이션 SQL**

`supabase/migrations/2026-11-17-output-tokens.sql`:

```sql
-- 크레딧 가드가 비용을 계산하려면 출력 토큰도 필요하다 (계획 3).
-- 출력이 입력보다 5배 비싸므로(opus-5-5: $4 vs $20 per MTok) 빼고 세면
-- 비용을 크게 낮잡는다.
--
-- nullable이다. 과거 실행에는 값이 없고, 그건 "0"이 아니라 "모른다"다.
alter table public.runs add column if not exists output_tokens int;

-- **anon에 권한을 주지 않는다.** runs는 컬럼 단위 grant이고 input_tokens가
-- 의도적으로 빠져 있다(계획 2 마이그레이션). 컬럼을 더하기만 하고 grant
-- 목록을 손대지 않으므로 자동으로 막히지만, 아래 verify로 실측 확인한다.
```

`supabase/schema.sql`의 `runs` 테이블 정의에도 `output_tokens   int,`를 `input_tokens` 아래에 더한다.

- [ ] **Step 7: Supabase에 적용한다**

MCP의 `apply_migration`을 쓰거나 대시보드 SQL 편집기에 붙여 넣는다.

```bash
cat supabase/migrations/2026-11-17-output-tokens.sql
```

- [ ] **Step 8: 권한 검사에 한 줄 더한다**

`scripts/verify_anon_access.sh`의 3번(컬럼 단위 차단) 반복문에 `output_tokens`를 넣는다.

```bash
for col in errors input_tokens output_tokens window_start; do
```

- [ ] **Step 9: 검증**

```bash
.venv/bin/python -m pytest -q
bash scripts/verify_anon_access.sh
```

Expected: 402 passed / 권한 검사 전부 통과 (`runs.output_tokens 차단` 포함)

- [ ] **Step 10: 커밋**

```bash
git add supabase/ pipeline/ scripts/ tests/
git commit -m "feat: runs.output_tokens + notify 토큰 배선"
```

---

## Task 4: `lib/kakao` — 토큰 갱신

최초 인증은 `scripts/kakao_auth.py`로 끝났다(2026-11-17). 여기서는 **매일 쓰는 쪽**만 만든다.

**Files:**
- Create: `pipeline/lib/kakao.py`
- Test: `tests/test_kakao.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from datetime import datetime, timedelta, timezone

import pytest

from pipeline.lib.kakao import KakaoTokens, access_token, should_store


def test_refresh_token으로_access_token을_받는다():
    def fake_post(url, data, headers, timeout):
        assert data["grant_type"] == "refresh_token"
        return {"access_token": "AT", "expires_in": 21599}

    tokens = access_token(
        refresh_token="RT",
        client_id="ID",
        client_secret="SECRET",
        post=fake_post,
    )

    assert tokens.access_token == "AT"
    assert tokens.refresh_token is None      # 회전되지 않았다


def test_새_refresh_token이_오면_담아_준다():
    """카카오는 기존 만료가 1개월 미만일 때만 새 것을 준다.
    왔는데 저장하지 않으면 다음 달에 로그인이 끊긴다.
    """
    def fake_post(url, data, headers, timeout):
        return {
            "access_token": "AT",
            "expires_in": 21599,
            "refresh_token": "NEW_RT",
            "refresh_token_expires_in": 5184000,
        }

    tokens = access_token(
        refresh_token="RT", client_id="ID", client_secret="SECRET", post=fake_post
    )

    assert tokens.refresh_token == "NEW_RT"
    assert tokens.refresh_token_expires_in == 5184000


def test_회전된_토큰만_저장한다():
    """매일 저장하면 쓸데없이 쓰기가 생긴다. 한 달에 한 번이면 된다."""
    assert should_store(KakaoTokens(access_token="AT", refresh_token="NEW")) is True
    assert should_store(KakaoTokens(access_token="AT")) is False
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_kakao.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.kakao'`

- [ ] **Step 3: `pipeline/lib/kakao.py`**

```python
"""카카오 토큰 갱신.

최초 인증(인가 코드 → refresh_token)은 scripts/kakao_auth.py가 한다.
사람이 브라우저에서 동의해야 하므로 파이프라인에 둘 수 없다.

여기는 매일 쓰는 쪽이다 — refresh_token으로 access_token을 받는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import httpx

from pipeline.lib.http import classify_status
from pipeline.lib.retry import Permanent

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
FORM = "application/x-www-form-urlencoded;charset=utf-8"


@dataclass(frozen=True)
class KakaoTokens:
    access_token: str
    # 기존 만료가 1개월 미만일 때만 온다. 안 오는 것이 정상이다.
    refresh_token: str | None = None
    refresh_token_expires_in: int | None = None


def _post(url: str, data: dict, headers: dict, timeout: float) -> dict:
    response = httpx.post(url, data=data, headers=headers, timeout=timeout)
    if response.status_code != 200:
        # 토큰 발급 실패는 대부분 설정 문제다(키 오타, 앱 설정 변경).
        # 재시도해도 같은 결과이므로 Permanent로 올린다.
        raise classify_status(response.status_code, f"카카오 토큰: {response.text}")
    return response.json()


def access_token(
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    post: Callable[..., dict] = _post,
) -> KakaoTokens:
    payload = post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": FORM},
        timeout=20.0,
    )
    if "access_token" not in payload:
        raise Permanent(f"카카오 응답에 access_token이 없다: {sorted(payload)}")
    return KakaoTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        refresh_token_expires_in=payload.get("refresh_token_expires_in"),
    )


def should_store(tokens: KakaoTokens) -> bool:
    """회전된 refresh_token이 왔을 때만 저장한다.

    카카오는 기존 만료가 1개월 미만일 때만 새 것을 준다. 매일 저장하면
    한 달에 29번은 같은 값을 다시 쓰는 셈이다.
    """
    return tokens.refresh_token is not None
```

- [ ] **Step 4: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_kakao.py -v
```

Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/kakao.py tests/test_kakao.py
git commit -m "feat: 카카오 토큰 갱신"
```

---

## Task 5: `KakaoSender` — 200자 조립

**Files:**
- Modify: `pipeline/lib/sender.py`
- Test: `tests/test_sender.py`

> **200자가 상한이다**(스펙 6.1). 머리글 약 20자 + 건당 약 33자(번호 3자 + 헤드라인 30자)이므로 **5건이 상한**이다(20 + 5×33 = 185). 7건이면 251자로 넘는다. 넘으면 **뒤쪽부터 접어** 반드시 안에 맞춘다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_sender.py`에 추가한다.

```python
from pipeline.lib.sender import build_kakao_text

MAX_TEXT = 200


def test_다섯_건까지는_그대로_싣는다():
    text = build_kakao_text("2026-11-17", ["가" * 10] * 5, total=5)

    assert "1. " in text and "5. " in text
    assert "외" not in text
    assert len(text) <= MAX_TEXT


def test_여섯_건부터는_외_N건으로_접는다():
    text = build_kakao_text("2026-11-17", ["가" * 10] * 5, total=7)

    assert "외 2건" in text
    assert len(text) <= MAX_TEXT


def test_헤드라인이_길면_건수를_줄여서라도_200자를_지킨다():
    """DB가 헤드라인을 30자로 막지만, 머리글과 번호를 더하면 5건이
    200자를 넘을 수 있다. 그때 조용히 잘리는 대신 건수를 줄인다.
    """
    long_ones = ["가" * 30] * 5

    text = build_kakao_text("2026-11-17", long_ones, total=7)

    assert len(text) <= MAX_TEXT
    assert "외" in text          # 접었다


def test_0건이어도_보낸다():
    """조용히 끝나면 시스템이 죽은 것과 구분되지 않는다 (요구사항 O2)."""
    text = build_kakao_text("2026-11-17", [], total=0)

    assert "0건" in text
    assert len(text) <= MAX_TEXT


def test_날짜를_월일로_줄인다():
    """200자 안에서 네 글자가 아깝다."""
    text = build_kakao_text("2026-11-17", ["가"], total=1)

    assert "11/17" in text
    assert "2026" not in text
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_sender.py -k kakao -v
```

Expected: FAIL — `ImportError: cannot import name 'build_kakao_text'`

- [ ] **Step 3: `pipeline/lib/sender.py`에 조립 함수를 더한다**

```python
# 카카오 기본 텍스트 템플릿의 상한. 넘으면 발송이 거부된다(스펙 6.1).
KAKAO_MAX_TEXT = 200
KAKAO_TOP_N = 5


def build_kakao_text(briefing_date: str, headlines: list[str], total: int) -> str:
    """카톡 본문을 만든다. **반드시 200자 이하를 돌려준다.**

    headlines는 상위 건의 헤드라인, total은 발행 전체 건수다. 둘을 나눈
    이유는 "5건 보여주고 외 2건"을 쓰려면 전체 수를 알아야 하기 때문이다.

    길이를 못 맞추면 조용히 자르지 않고 **건수를 줄인다.** 잘린 헤드라인은
    읽는 사람에게 아무 뜻이 없지만, 건수가 줄어든 것은 "외 N건"이 알려준다.
    """
    month_day = briefing_date[5:].replace("-", "/")   # 2026-11-17 → 11/17
    header = f"📡 {month_day} IT 브리핑 · {total}건"

    if total == 0:
        return f"{header}\n\n오늘은 기준을 넘긴 글이 없습니다."

    for shown in range(min(KAKAO_TOP_N, len(headlines)), 0, -1):
        lines = [f"{i}. {h}" for i, h in enumerate(headlines[:shown], 1)]
        rest = total - shown
        if rest > 0:
            lines.append(f"   외 {rest}건")
        text = header + "\n\n" + "\n".join(lines)
        if len(text) <= KAKAO_MAX_TEXT:
            return text

    # 한 건도 못 넣는다 — 헤드라인이 비정상적으로 길다. 건수만 알린다.
    return f"{header}\n\n   외 {total}건"
```

- [ ] **Step 4: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_sender.py -k kakao -v
```

Expected: 5 passed

- [ ] **Step 5: `KakaoSender`를 더한다**

같은 파일에 이어서 쓴다.

```python
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


class KakaoSender:
    """나에게 보내기. Sender 프로토콜을 만족한다.

    "나에게 보내기"에는 일간·월간 제공량 제한이 없다 — 제한은 "친구에게
    발송"에만 적용된다(스펙 6.1).
    """

    name = "kakao"

    def __init__(self, *, access_token: str, page_url: str, post=None) -> None:
        self._token = access_token
        self._page = page_url
        self._post = post or self._http_post

    @staticmethod
    def _http_post(url: str, data: dict, headers: dict, timeout: float) -> dict:
        response = httpx.post(url, data=data, headers=headers, timeout=timeout)
        if response.status_code != 200:
            raise classify_status(response.status_code, f"카카오 발송: {response.text}")
        return response.json()

    def send(self, *, briefing, raw) -> None:
        headlines = [s.headline for s in briefing.summaries[:KAKAO_TOP_N]]
        text = build_kakao_text(
            briefing_date=briefing.window_end[:10],
            headlines=headlines,
            total=len(briefing.summaries),
        )

        template = {
            "object_type": "text",
            "text": text,
            # 두 주소를 같게 둔다. 그리고 이 호스트가 카카오 콘솔의
            # [제품 링크 관리] → [웹 도메인]에 등록돼 있어야 한다 —
            # 없으면 발송은 성공하고 버튼만 죽는다(스펙 6.1).
            "link": {"web_url": self._page, "mobile_web_url": self._page},
            "button_title": "전체 보기",
        }

        # **form-urlencoded에 template_object를 JSON 문자열로 넣는다.**
        # 본문 전체를 JSON으로 보내면 받지 않는다.
        self._post(
            SEND_URL,
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": FORM,
            },
            timeout=20.0,
        )
```

파일 위에 `import json`, `import httpx`, `from pipeline.lib.http import classify_status`, 그리고 `FORM = "application/x-www-form-urlencoded;charset=utf-8"`를 더한다.

- [ ] **Step 6: 인터페이스와 발송 테스트를 더한다**

```python
def test_KakaoSender가_인터페이스를_만족한다():
    sender = KakaoSender(access_token="AT", page_url="https://x.test/")

    assert isinstance(sender, Sender)
    assert sender.name == "kakao"


def test_발송_본문이_form으로_나간다():
    """카카오 토큰 엔드포인트와 발송 엔드포인트 둘 다 JSON 본문을 받지 않는다."""
    sent = {}

    def fake_post(url, data, headers, timeout):
        sent.update(url=url, data=data, headers=headers)
        return {"result_code": 0}

    KakaoSender(
        access_token="AT", page_url="https://x.test/", post=fake_post
    ).send(briefing=_briefing([_summary()]), raw=_raw())

    assert "template_object" in sent["data"]
    template = json.loads(sent["data"]["template_object"])
    assert template["object_type"] == "text"
    assert template["link"]["web_url"] == "https://x.test/"
    assert sent["headers"]["Authorization"] == "Bearer AT"
```

- [ ] **Step 7: 전체 테스트**

```bash
.venv/bin/python -m pytest -q
```

Expected: 409 passed

- [ ] **Step 8: 커밋**

```bash
git add pipeline/lib/sender.py tests/test_sender.py
git commit -m "feat: KakaoSender — 200자 조립과 외 N건 접기"
```

---
## Task 6: 카톡 실제 발송 — 두 링크를 모두 확인한다

코드가 아니라 **검증 태스크**다. 2026-11-17에 두 번 막히고 배운 것이 여기 들어간다.

**Files:**
- Modify: `scripts/kakao_send_test.py` (실제 브리핑으로 보내도록)

- [ ] **Step 1: 스크립트가 실제 브리핑을 싣게 한다**

`scripts/kakao_send_test.py`의 고정 문구를 `build_kakao_text`로 바꾼다.

```python
from pipeline.lib.sender import build_kakao_text
from pipeline.lib.store import SupabaseStore

# 최신 브리핑을 Supabase에서 읽어 실제 본문으로 보낸다.
rows = (
    client.table("articles")
    .select("briefing_date, headline, score")
    .order("briefing_date", desc=True)
    .order("score", desc=True)
    .limit(10)
    .execute()
)
items = rows.data or []
date = items[0]["briefing_date"] if items else "2026-01-01"
same_day = [r["headline"] for r in items if r["briefing_date"] == date]

text = build_kakao_text(date, same_day[:5], total=len(same_day))
print(f"   text 길이: {len(text)}자 (상한 200)")
```

`template["text"] = text`로 바꾸고 `link`는 `.env`의 `PAGE_URL`을 그대로 쓴다.

- [ ] **Step 2: 보낸다**

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -u scripts/kakao_send_test.py
```

Expected: `result_code: 0`, `text 길이`가 200 이하

- [ ] **Step 3: 폰에서 두 링크를 모두 누른다**

**이 단계를 건너뛰면 검증이 아니다.** 발송 성공(`result_code: 0`)은 둘 중 어느 것도 보장하지 않는다.

| 누를 곳 | 기대 | 목적지를 정하는 것 |
|---|---|---|
| **[전체 보기] 버튼** | 브리핑 페이지 | 템플릿의 `link.web_url` |
| **하단 "IT 브리핑 >" 행** | **같은 페이지** | 콘솔의 등록 도메인 — 코드로 못 건드린다 |

하단 행이 404면 카카오 콘솔의 [제품 링크 관리] → [웹 도메인]에 `PAGE_URL`의 **호스트**가 등록돼 있는지 본다. 경로는 무시된다(실측).

- [ ] **Step 4: 본문이 읽히는지 본다**

5건이 번호와 함께 보이고, 6건 이상이면 "외 N건"이 붙어 있어야 한다. 헤드라인이 잘려 있으면 `build_kakao_text`가 건수를 줄이는 대신 자른 것이므로 버그다.

- [ ] **Step 5: 커밋**

```bash
git add scripts/kakao_send_test.py
git commit -m "test: 발송 확인 스크립트가 실제 브리핑을 싣는다"
```

---

## Task 7: `SlackSender` — 경고 전용

> **선행:** `.env`에 `SLACK_WEBHOOK_URL`이 있어야 Step 5를 할 수 있다. 워크스페이스에서 Incoming Webhook을 발급한다.

**브리핑 전문을 보내지 않는다**(스펙 6.2). 읽는 자리는 페이지이고, 채널이 둘이면 포맷터를 둘 유지해야 한다.

**Files:**
- Create: `pipeline/lib/slack.py`
- Test: `tests/test_slack.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
import pytest

from pipeline.lib.slack import SlackSender, format_warnings


def test_경고가_없으면_보내지_않는다():
    """빈 메시지를 매일 보내면 그게 알림 피로다."""
    sent = []
    sender = SlackSender(webhook_url="https://hooks.test/x", post=lambda **kw: sent.append(kw))

    sender.warn([])

    assert sent == []


def test_경고를_줄바꿈으로_묶어_보낸다():
    sent = []
    sender = SlackSender(webhook_url="https://hooks.test/x", post=lambda **kw: sent.append(kw))

    sender.warn(["소스 죽음: 404", "토큰 만료 10일 전"])

    assert len(sent) == 1
    assert "404" in sent[0]["json"]["text"]
    assert "토큰 만료" in sent[0]["json"]["text"]


def test_전문을_보내는_메서드가_없다():
    """스펙 6.2 — 브리핑은 슬랙으로 가지 않는다. 구조로 막는다."""
    assert not hasattr(SlackSender, "send")


def test_머리글이_무엇에_대한_경고인지_말한다():
    sent = []
    SlackSender(
        webhook_url="https://hooks.test/x", post=lambda **kw: sent.append(kw)
    ).warn(["무언가"])

    assert "브리핑" in sent[0]["json"]["text"]
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_slack.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.slack'`

- [ ] **Step 3: `pipeline/lib/slack.py`**

```python
"""슬랙 — 경고 전용.

**브리핑 전문을 보내지 않는다**(스펙 6.2). 읽는 자리는 페이지이고,
슬랙이 그 일을 중복하면 포맷터를 하나 더 유지해야 한다.

슬랙이 필요한 이유는 하나다 — **카카오 토큰이 만료되면 카톡으로는 그
사실을 알릴 수 없다.** 카톡이 유일한 채널이면 시스템이 조용히 죽는다.
Incoming Webhook URL은 만료가 없다.
"""

from __future__ import annotations

from typing import Callable

import httpx

HEADER = "⚠️ 브리핑 경고"


def format_warnings(warnings: list[str]) -> str:
    lines = "\n".join(f"• {w}" for w in warnings)
    return f"{HEADER}\n{lines}"


class SlackSender:
    """`Sender` 프로토콜을 **의도적으로 만족하지 않는다** — `send`가 없다.

    프로토콜을 만족하면 `notify`의 센더 목록에 넣을 수 있게 되고, 그러면
    언젠가 누군가 브리핑을 슬랙으로 보낸다. 구조로 막는다.
    """

    name = "slack"

    def __init__(
        self,
        *,
        webhook_url: str,
        post: Callable[..., object] | None = None,
    ) -> None:
        self._url = webhook_url
        self._post = post or self._http_post

    @staticmethod
    def _http_post(*, url: str, json: dict, timeout: float) -> object:
        # 경고 전송이 실패해도 브리핑을 막지 않는다 — 호출부가 감싼다.
        return httpx.post(url, json=json, timeout=timeout)

    def warn(self, warnings: list[str]) -> None:
        """경고가 없으면 아무것도 보내지 않는다."""
        if not warnings:
            return
        self._post(url=self._url, json={"text": format_warnings(warnings)}, timeout=15.0)
```

- [ ] **Step 4: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_slack.py -v
```

Expected: 4 passed

- [ ] **Step 5: 실제로 한 번 보낸다**

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -c "
from pathlib import Path
from pipeline.lib.slack import SlackSender

env = dict(
    l.split('=', 1) for l in Path('.env').read_text(encoding='utf-8').splitlines()
    if l.strip() and not l.startswith('#') and '=' in l
)
SlackSender(webhook_url=env['SLACK_WEBHOOK_URL'].strip()).warn(
    ['연결 확인 — 이 줄이 보이면 경고 채널이 동작합니다.']
)
print('보냈다. 슬랙 채널을 확인한다.')
"
```

Expected: 슬랙 채널에 메시지가 뜬다

- [ ] **Step 6: 커밋**

```bash
git add pipeline/lib/slack.py tests/test_slack.py
git commit -m "feat: SlackSender — 경고 전용, send 메서드 없음"
```

---

## Task 8: `lib/guard` — 소스 침묵

**지표를 바꾼다.** "N일 연속 0건"이 아니라 **"그 소스에서 마지막으로 글이 온 날로부터 경과일"**이다. 0건은 수집 윈도우(최대 96시간) 기준이라 주간 소스는 7일 중 5일이 0건이고, "연속" 카운트가 소스의 실제 상태와 어긋난다.

**Files:**
- Create: `pipeline/lib/guard.py`
- Modify: `pipeline/lib/config.py` (`Source`에 `quiet_tier`)
- Test: `tests/test_guard.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from datetime import date

from pipeline.lib.guard import QUIET_THRESHOLDS, days_since_seen, silent_sources


def _run(day: str, counts: dict) -> dict:
    return {"briefing_date": day, "source_counts": counts}


def test_마지막으로_본_날로부터_센다():
    runs = [                                   # briefing_date 내림차순
        _run("2026-11-17", {"토스": 0}),
        _run("2026-11-16", {"토스": 0}),
        _run("2026-11-15", {"토스": 2}),
    ]

    assert days_since_seen(runs, "토스", today=date(2026, 11, 17)) == 2


def test_한_번도_못_봤으면_None이다():
    """새로 넣은 소스와 죽은 소스를 구별할 수 없다. 다른 문제다."""
    runs = [_run("2026-11-17", {"토스": 1})]

    assert days_since_seen(runs, "새소스", today=date(2026, 11, 17)) is None


def test_등급마다_임계값이_다르다():
    assert QUIET_THRESHOLDS["fast"] == 30
    assert QUIET_THRESHOLDS["weekly"] == 90
    assert QUIET_THRESHOLDS["monthly"] == 200
    assert QUIET_THRESHOLDS["none"] is None


def test_none_등급은_경고하지_않는다():
    """400일에 2편인 소스를 400일 기준으로 감시하는 건 가드가 아니라
    가드인 척이다. 그 한 줄이 잘못된 안심을 준다.
    """
    runs = [_run("2026-11-17", {})]
    sources = [_source("Lil_Log", tier="none")]

    assert silent_sources(sources, runs, today=date(2026, 11, 17)) == []


def test_임계값을_넘긴_소스만_고른다():
    runs = [_run("2026-11-17", {"빠른소스": 0, "주간소스": 0})]
    # 둘 다 한 번도 안 보였으므로 None → 경고하지 않는다
    sources = [_source("빠른소스", tier="fast"), _source("주간소스", tier="weekly")]

    assert silent_sources(sources, runs, today=date(2026, 11, 17)) == []


def test_경과일과_임계값을_함께_알려준다():
    """'토스가 조용하다'보다 '토스 45일째 (기준 30일)'가 조치로 이어진다."""
    runs = [
        _run("2026-11-17", {"토스": 0}),
        _run("2026-10-03", {"토스": 1}),
    ]
    sources = [_source("토스", tier="fast")]

    found = silent_sources(sources, runs, today=date(2026, 11, 17))

    assert found == [("토스", 45, 30)]
```

`_source` 헬퍼를 파일 위에 둔다.

```python
from pipeline.lib.config import Source


def _source(name: str, tier: str) -> Source:
    return Source(
        name=name,
        url=f"https://e.com/{name}",
        kind="rss",
        weight=1.0,
        lang="ko",
        quiet_tier=tier,
    )
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_guard.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.lib.guard'`

- [ ] **Step 3: `Source`에 `quiet_tier`를 더한다**

`pipeline/lib/config.py`:

```python
QuietTier = Literal["fast", "weekly", "monthly", "none"]
```

`Source` 클래스 안, `enabled` 위에:

```python
    # 침묵 경고의 임계값 등급. 소스의 **관측된 최대공백**으로 정한다
    # (중앙값이 아니다 — 몰아서 쓰는 소스가 있다).
    # 기본 fast: 새 소스는 빨리 쓸 것으로 보고, 오탐이 나면 한 칸 올린다.
    quiet_tier: QuietTier = "fast"
```

- [ ] **Step 4: `pipeline/lib/guard.py`**

```python
"""조용히 실패하는 것들을 잡는다.

브리핑이 오지 않으면 "오늘 뉴스가 없었나보다"로 착각하게 되고, 그것이
2주 지속되면 시스템이 죽은 것을 모른다. 더 나쁜 것은 브리핑이 **정상적으로
오면서** 내용만 조금씩 빈약해지는 경우다 — 아무 신호가 없다.

가치 순서는 **소스 침묵 > 토큰 만료 > 크레딧**이다(스펙 8.4).
"""

from __future__ import annotations

from datetime import date

from pipeline.lib.config import Source

# 관측된 최대공백으로 나눈 등급별 임계값(일).
# 시드(2026-11-12, 400일 윈도우) 측정에서 나왔다.
QUIET_THRESHOLDS: dict[str, int | None] = {
    "fast": 30,       # 최대공백 ≤ 16일 — 25개
    "weekly": 90,     # 17~45일 — 10개
    "monthly": 200,   # 46~130일 — 5개
    "none": None,     # 131일+ 또는 표본 3건 미만 — 가드 제외
}


def days_since_seen(runs: list[dict], source: str, *, today: date) -> int | None:
    """그 소스에서 마지막으로 글이 온 날로부터 며칠인가.

    runs는 briefing_date 내림차순이어야 한다. 한 번도 못 봤으면 None —
    **"오래 조용하다"와 "처음부터 없었다"는 다른 문제다.** 새로 넣은
    소스를 죽었다고 경고하면 그게 오탐이다.
    """
    for run in runs:
        if (run.get("source_counts") or {}).get(source, 0) > 0:
            seen = date.fromisoformat(run["briefing_date"])
            return (today - seen).days
    return None


def silent_sources(
    sources: list[Source], runs: list[dict], *, today: date
) -> list[tuple[str, int, int]]:
    """임계값을 넘긴 소스를 (이름, 경과일, 임계값)으로 돌려준다.

    임계값을 함께 주는 이유: "토스가 조용하다"보다 "토스 45일째 (기준
    30일)"가 조치로 이어진다. 기준을 올릴지 소스를 끌지 판단할 수 있다.
    """
    found = []
    for source in sources:
        limit = QUIET_THRESHOLDS[source.quiet_tier]
        if limit is None:
            continue
        gap = days_since_seen(runs, source.name, today=today)
        if gap is not None and gap >= limit:
            found.append((source.name, gap, limit))
    return found
```

- [ ] **Step 5: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_guard.py -v
```

Expected: 6 passed

- [ ] **Step 6: 커밋**

```bash
git add pipeline/lib/guard.py pipeline/lib/config.py tests/test_guard.py
git commit -m "feat: 소스 침묵 가드 — 경과일 기준, 등급별 임계값"
```

---

## Task 9: `sources.yaml`에 등급을 배정한다

시드(2026-11-12, 1,923건) 측정에서 나온 배정이다. 괄호는 **관측된 최대공백**.

**Files:**
- Modify: `config/sources.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: 배정을 넣는다**

`fast`는 기본값이므로 **적지 않는다.** 나머지 20개에만 `quiet_tier:`를 더한다.

**`weekly` (10개)** — 당근_기술블로그(41), Dropbox_Tech(37), Shopify_Engineering(36), Sebastian_Raschka(32), Airbnb_Engineering(28), Grab_Engineering(28), Google_Research_Blog(24), Google_DeepMind_Blog(20), 네이버_D2(20), 카카오_기술블로그(19)

**`monthly` (5개)** — 쏘카_기술블로그(119), Slack_Engineering(108), 인프런_기술블로그(92), 하이퍼커넥트_기술블로그(89), Discord_Engineering(52)

**`none` (5개)** — Canva_Engineering(275), 뱅크샐러드_기술블로그(265), 데브시스터즈_기술블로그(201), Lil_Log(표본 2건), 스포카_기술블로그(표본 1건)

각 항목에 이유를 주석으로 남긴다.

```yaml
  # 최대공백 119일 — 분기에 몰아서 쓴다. 중앙 11일로는 임계값을 못 정한다.
  - name: 쏘카_기술블로그
    url: https://tech.socarcorp.kr/feed
    kind: rss
    weight: 1.3
    lang: ko
    quiet_tier: monthly
```

`none`에는 **왜 뺐는지**를 적는다.

```yaml
  # 400일에 2편 — 원래 이 속도다. 침묵이 정보를 담지 않으므로 가드에서 뺀다.
  # 분기에 한 번 check_feeds.py로 확인한다.
  - name: Lil_Log
    ...
    quiet_tier: none
```

- [ ] **Step 2: 로더가 받는지 확인한다**

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -c "
from collections import Counter
from pipeline.lib.config import load_sources

tiers = Counter(s.quiet_tier for s in load_sources())
print(dict(tiers))
assert tiers['weekly'] == 10, tiers
assert tiers['monthly'] == 5, tiers
assert tiers['none'] == 5, tiers
assert tiers['fast'] == 25, tiers
print('배정 확인: fast 25 / weekly 10 / monthly 5 / none 5 = 45')
"
```

Expected: `배정 확인: fast 25 / weekly 10 / monthly 5 / none 5 = 45`

- [ ] **Step 3: 모르는 등급을 거부하는 테스트**

`tests/test_config.py`에 추가한다.

```python
def test_모르는_침묵_등급을_거부한다():
    """오타가 조용히 기본값으로 떨어지면 그 소스는 감시되지 않는다."""
    with pytest.raises(ValidationError):
        Source(
            name="s", url="https://e.com/r", kind="rss",
            weight=1.0, lang="ko", quiet_tier="weekley",   # 오타
        )


def test_등급을_안_적으면_fast다():
    source = Source(name="s", url="https://e.com/r", kind="rss", weight=1.0, lang="ko")

    assert source.quiet_tier == "fast"
```

- [ ] **Step 4: 전체 테스트**

```bash
.venv/bin/python -m pytest -q
```

Expected: 421 passed

- [ ] **Step 5: 커밋**

```bash
git add config/sources.yaml tests/test_config.py
git commit -m "feat: 소스 45개에 침묵 등급 배정 (시드 실측 기준)"
```

---

## Task 10: `lib/guard` — 토큰 만료

**Files:**
- Modify: `pipeline/lib/guard.py`
- Test: `tests/test_guard.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from datetime import datetime, timedelta, timezone

from pipeline.lib.guard import TOKEN_WARN_DAYS, token_expiring


def test_14일_안이면_알린다():
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)

    assert token_expiring(now + timedelta(days=10), now=now) == 10


def test_여유가_있으면_알리지_않는다():
    """매일 알리면 그게 알림 피로다. 60일 남은 날에는 조용해야 한다."""
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)

    assert token_expiring(now + timedelta(days=60), now=now) is None


def test_이미_만료됐으면_음수로_알린다():
    """'3일 지났다'가 '0일 남았다'보다 정확하다."""
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)

    assert token_expiring(now - timedelta(days=3), now=now) == -3


def test_임계값이_14일이다():
    assert TOKEN_WARN_DAYS == 14
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_guard.py -k token -v
```

Expected: FAIL — `ImportError: cannot import name 'token_expiring'`

- [ ] **Step 3: 구현**

`pipeline/lib/guard.py`에 더한다.

```python
from datetime import datetime

# 재인증은 브라우저에서 사람이 해야 한다(scripts/kakao_auth.py).
# 2주면 주말을 두 번 지나므로 바쁜 주에도 처리할 시간이 있다.
TOKEN_WARN_DAYS = 14


def token_expiring(expires_at: datetime, *, now: datetime) -> int | None:
    """만료까지 남은 일수. 여유가 있으면 None.

    음수를 그대로 돌려준다 — "3일 지났다"가 "0일 남았다"보다 정확하고,
    이미 끊긴 상태와 곧 끊길 상태는 다른 조치를 부른다.
    """
    days = (expires_at - now).days
    return days if days <= TOKEN_WARN_DAYS else None
```

- [ ] **Step 4: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_guard.py -k token -v
```

Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/guard.py tests/test_guard.py
git commit -m "feat: 토큰 만료 가드 — 14일 전부터"
```

---

## Task 11: `lib/guard` — 크레딧

> **선행:** `.env`에 `MONTHLY_BUDGET_USD`가 있어야 Task 12에서 쓸 수 있다. 숫자 하나다 (예: `MONTHLY_BUDGET_USD=20`).

**Anthropic은 잔여 크레딧을 알려주지 않는다.** Usage and Cost Analytics의 `/cost`는 "할인 후, 크레딧 적용 전" 금액이고, Admin API 키와 4~24시간 지연이 따라온다. 그래서 **우리 사용량을 누적해 내가 정한 예산과 비교한다**(설계 0.1).

**Files:**
- Modify: `pipeline/lib/guard.py`
- Test: `tests/test_guard.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from pipeline.lib.guard import BUDGET_WARN_RATIO, SPIKE_FACTOR, month_cost_usd, token_spike


def test_입력과_출력을_각각의_단가로_센다():
    """출력이 5배 비싸다. 입력만 세면 비용을 크게 낮잡는다."""
    runs = [{"input_tokens": 1_000_000, "output_tokens": 1_000_000}]

    assert month_cost_usd(runs, model="claude-opus-5-5") == 24.0   # 4 + 20


def test_값이_없는_실행은_0으로_세지_않고_건너뛴다():
    """배선 전 실행은 None이다. 0으로 세면 '안 썼다'가 되어 거짓 안심이다."""
    runs = [
        {"input_tokens": None, "output_tokens": None},
        {"input_tokens": 1_000_000, "output_tokens": 0},
    ]

    assert month_cost_usd(runs, model="claude-opus-5-5") == 4.0


def test_표본이_적으면_급증을_판정하지_않는다():
    """이틀치로 '평소의 3배'를 판정하면 셋째 날마다 경고가 뜬다."""
    runs = [{"input_tokens": 1000}, {"input_tokens": 1000}]

    assert token_spike(runs, today_input=9999) is False


def test_중앙값의_3배를_넘으면_급증이다():
    runs = [{"input_tokens": 1000} for _ in range(10)]

    assert token_spike(runs, today_input=3001) is True
    assert token_spike(runs, today_input=2999) is False


def test_임계값들():
    assert BUDGET_WARN_RATIO == 0.8
    assert SPIKE_FACTOR == 3
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_guard.py -k "cost or spike or 임계값들" -v
```

Expected: FAIL — `ImportError: cannot import name 'month_cost_usd'`

- [ ] **Step 3: 구현**

```python
import statistics

# 모델별 단가 (USD per 1M tokens). 입력, 출력.
# **정가 기준이라 실제 청구액과 다르다** — 할인과 크레딧 적용 전이다.
# 이 가드의 목적은 정확한 금액이 아니라 조기 소진 감지다(설계 4.3).
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
}

BUDGET_WARN_RATIO = 0.8    # 월 예산의 80%를 넘으면 알린다
SPIKE_FACTOR = 3           # 평소의 3배
SPIKE_MIN_SAMPLES = 5      # 이보다 적으면 판정하지 않는다


def month_cost_usd(runs: list[dict], *, model: str) -> float:
    """그 달 실행들이 쓴 비용(정가 기준).

    토큰이 None인 실행은 **건너뛴다.** 0으로 세면 "안 썼다"가 되어
    배선 전 기록이 비용을 낮잡게 만든다.
    """
    price_in, price_out = PRICES[model]
    total = 0.0
    for run in runs:
        if run.get("input_tokens") is None:
            continue
        total += (run["input_tokens"] or 0) / 1_000_000 * price_in
        total += (run.get("output_tokens") or 0) / 1_000_000 * price_out
    return round(total, 4)


def token_spike(runs: list[dict], *, today_input: int) -> bool:
    """오늘 입력 토큰이 평소의 3배를 넘는가.

    피드 하나가 갑자기 10배를 쏟아내는 것 같은 **당일 이상**을 잡는다.
    예산 비율은 느린 누수를 잡고, 이쪽이 사고를 잡는다.

    표본이 적으면 판정하지 않는다 — 이틀치로 중앙값을 내면 셋째 날마다
    경고가 뜬다.
    """
    history = [r["input_tokens"] for r in runs if r.get("input_tokens")]
    if len(history) < SPIKE_MIN_SAMPLES:
        return False
    return today_input > statistics.median(history) * SPIKE_FACTOR
```

- [ ] **Step 4: 통과를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_guard.py -v
```

Expected: 15 passed

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/guard.py tests/test_guard.py
git commit -m "feat: 크레딧 가드 — 우리 사용량 누적 (잔액 API가 없다)"
```

---
## Task 12: 가드를 `notify`에 연결한다

> **선행: Task 8·10·11.** 셋이 다 있어야 이 커밋이 돈다.

가드는 세 가지 데이터를 필요로 한다 — 최근 실행들(침묵·크레딧), 토큰 만료 시각, 그리고 월 예산. 앞의 둘은 `RemoteStore`에 메서드를 더해 가져온다.

**Files:**
- Modify: `pipeline/lib/store.py` (프로토콜과 구현)
- Modify: `pipeline/notify.py`
- Modify: `tests/fakes.py`
- Test: `tests/test_notify.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_notify.py`에 추가한다.

```python
def test_가드_경고가_슬랙으로_간다():
    """브리핑은 카톡으로, 경고는 슬랙으로. 섞이지 않는다."""
    warned = []
    fake = FakeRemoteStore()
    fake.runs_history = [
        {"briefing_date": "2026-11-17", "source_counts": {}, "input_tokens": 1000},
        {"briefing_date": "2026-09-01", "source_counts": {"토스": 3}, "input_tokens": 1000},
    ]

    notify(
        briefing=_briefing([]),
        ranked=_ranked(),
        raw=_raw(),
        remote=fake,
        briefing_date="2026-11-17",
        senders=[_ok_sender()],
        warn=warned.append,
        sources=[_source("토스", tier="fast")],
    )

    assert any("토스" in w for w in warned)
    assert any("77일" in w for w in warned)      # 9/1 → 11/17


def test_가드가_터져도_브리핑은_나간다():
    """경고 때문에 브리핑이 막히면 주객이 전도된다."""
    sent = []
    fake = FakeRemoteStore()

    def exploding_warn(_):
        raise RuntimeError("슬랙이 죽었다")

    notify(
        briefing=_briefing([_summary()]),
        ranked=_ranked(),
        raw=_raw(),
        remote=fake,
        briefing_date="2026-11-17",
        senders=[_recording_sender(sent)],
        warn=exploding_warn,
        sources=[],
    )

    assert len(sent) == 1        # 보냈다
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_notify.py -k 가드 -v
```

Expected: FAIL — `TypeError: notify() got an unexpected keyword argument 'warn'`

- [ ] **Step 3: `RemoteStore`에 조회 메서드를 더한다**

`pipeline/lib/store.py`의 프로토콜과 `SupabaseStore` **양쪽**에 넣는다.

```python
    def recent_runs(self, days: int) -> list[dict]:
        """최근 실행 이력. briefing_date 내림차순.

        가드가 읽는다 — 소스 침묵은 source_counts를, 크레딧은 토큰을 본다.
        status='sent'만이 아니라 **전부** 돌려준다: 전송이 실패한 날에도
        수집은 했으므로 침묵 카운트에 포함되어야 한다(스펙 8.4).
        """
        ...

    def kakao_refresh_token(self) -> tuple[str, datetime] | None:
        """(refresh_token, 만료 시각). 없으면 None."""
        ...

    def save_kakao_refresh_token(self, token: str, expires_at: datetime) -> None:
        """회전된 토큰을 저장한다. 한 달에 한 번쯤 불린다."""
        ...
```

`SupabaseStore` 구현:

```python
    def recent_runs(self, days: int) -> list[dict]:
        since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
        rows = (
            self._db.table("runs")
            .select("briefing_date, status, source_counts, input_tokens, output_tokens")
            .gte("briefing_date", since)
            .order("briefing_date", desc=True)
            .execute()
        )
        return rows.data or []

    def kakao_refresh_token(self) -> tuple[str, datetime] | None:
        rows = (
            self._db.table("kakao_auth")
            .select("refresh_token, refresh_token_expires_at")
            .eq("id", 1)
            .execute()
        )
        if not rows.data:
            return None
        row = rows.data[0]
        return row["refresh_token"], datetime.fromisoformat(
            row["refresh_token_expires_at"]
        )

    def save_kakao_refresh_token(self, token: str, expires_at: datetime) -> None:
        self._db.table("kakao_auth").upsert(
            {
                "id": 1,
                "refresh_token": token,
                "refresh_token_expires_at": expires_at.isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
```

`FakeRemoteStore`에도 같은 세 메서드를 더한다 — `recent_runs`는 `self.runs_history`(기본 `[]`)를 돌려주고, 토큰 메서드는 `self.kakao`(기본 `None`)를 쓴다.

- [ ] **Step 4: `notify`가 가드를 돌린다**

`pipeline/notify.py` 맨 위에 import를 더한다.

```python
import os
from datetime import date

from pipeline.lib.config import Source, load_sources
from pipeline.lib.guard import (
    BUDGET_WARN_RATIO,
    SPIKE_FACTOR,
    month_cost_usd,
    silent_sources,
    token_expiring,
    token_spike,
)
from pipeline.lib.kakao import access_token, should_store
from pipeline.lib.llm import MODEL
from pipeline.lib.sender import KakaoSender
from pipeline.lib.slack import SlackSender
```

그리고 시그니처에 둘을 더한다.

```python
    warn: Callable[[str], None] | None = None,
    sources: list[Source] | None = None,
```

그리고 **센더를 부르기 전에**, `AlreadySent` 검사 다음에 넣는다.

```python
    # 가드는 브리핑과 독립이다. 터져도 발송을 막지 않는다 — 경고 때문에
    # 브리핑이 안 가면 주객이 전도된다.
    if warn is not None:
        try:
            for line in guard_warnings(
                remote=remote,
                sources=sources or [],
                today=date.fromisoformat(briefing_date),
                today_input=(totals.input if totals else 0),
            ):
                warn(line)
        except Exception as problem:            # noqa: BLE001
            # 가드 자체의 실패도 **조용히** 삼키지는 않는다. runs.errors에
            # 넣지 않는 이유는 그 목록(`failures`)이 센더 루프에서 만들어져
            # 이 시점에 아직 없기 때문이다. Actions 로그에 남으면 충분하다 —
            # 가드의 가드까지 DB에 적을 일은 아니다.
            print(f"가드 실패(브리핑은 계속한다): {problem}", file=sys.stderr)
```

같은 파일 아래에 조립 함수를 둔다.

```python
def guard_warnings(
    *, remote: RemoteStore, sources: list[Source], today: date, today_input: int
) -> list[str]:
    """가드 셋을 돌려 사람이 읽을 줄로 만든다."""
    lines: list[str] = []
    runs = remote.recent_runs(days=400)

    for name, gap, limit in silent_sources(sources, runs, today=today):
        lines.append(f"소스 침묵: {name} — {gap}일째 (기준 {limit}일)")

    found = remote.kakao_refresh_token()
    if found is not None:
        left = token_expiring(found[1], now=datetime.now(timezone.utc))
        if left is not None:
            when = f"{left}일 남음" if left >= 0 else f"{-left}일 지남"
            lines.append(
                f"카카오 토큰 만료 {when} — "
                "`.venv/bin/python scripts/kakao_auth.py`로 재발급한다"
            )

    budget = os.environ.get("MONTHLY_BUDGET_USD")
    if budget:
        this_month = [r for r in runs if r["briefing_date"][:7] == today.isoformat()[:7]]
        spent = month_cost_usd(this_month, model=MODEL)
        if spent >= float(budget) * BUDGET_WARN_RATIO:
            lines.append(f"크레딧: 이번 달 ${spent:.2f} / 예산 ${budget} (정가 기준)")

    if token_spike(runs, today_input=today_input):
        lines.append(f"입력 토큰 급증: 오늘 {today_input:,} — 평소의 {SPIKE_FACTOR}배 초과")

    return lines
```

- [ ] **Step 5: 통과를 확인한다**

```bash
.venv/bin/python -m pytest -q
```

Expected: 423 passed

- [ ] **Step 6: `__main__`에서 센더와 슬랙을 조립한다**

`pipeline/notify.py`의 `main()`을 연다. `ConsoleSender`만 쓰던 곳에 카톡을 더하고 `warn`을 넘긴다.

```python
    senders = [ConsoleSender()]

    refresh = remote.kakao_refresh_token()
    if refresh is not None:
        tokens = access_token(
            refresh_token=refresh[0],
            client_id=env["KAKAO_REST_API_KEY"],
            client_secret=env["KAKAO_CLIENT_SECRET"],
        )
        # 회전된 토큰이 왔을 때만 저장한다 — 한 달에 한 번쯤이다.
        if should_store(tokens):
            expires = datetime.now(timezone.utc) + timedelta(
                seconds=tokens.refresh_token_expires_in or 0
            )
            remote.save_kakao_refresh_token(tokens.refresh_token, expires)
        senders.append(
            KakaoSender(access_token=tokens.access_token, page_url=env["PAGE_URL"])
        )

    slack = env.get("SLACK_WEBHOOK_URL")
    warn = SlackSender(webhook_url=slack).warn if slack else None
```

`warn`은 줄 하나가 아니라 목록을 받으므로, `notify`에 넘길 때는 모아서 한 번에 보내도록 감싼다.

```python
    collected: list[str] = []
    notify(..., warn=collected.append, sources=load_sources())
    if warn and collected:
        warn(collected)
```

- [ ] **Step 7: 커밋**

```bash
git add pipeline/lib/store.py pipeline/notify.py tests/
git commit -m "feat: 가드를 notify에 연결 — 경고는 슬랙으로, 터져도 브리핑은 나간다"
```

---

## Task 13: `report_failure`

**Files:**
- Create: `pipeline/report_failure.py`
- Test: `tests/test_report_failure.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from pipeline.report_failure import build_report


def test_어느_단계에서_죽었는지_말한다():
    report = build_report(
        failed_step="rank",
        run_url="https://github.com/x/y/actions/runs/123",
        briefing_date="2026-11-17",
    )

    assert "rank" in report
    assert "2026-11-17" in report
    assert "actions/runs/123" in report


def test_다음_날이_덮는다는_것을_알려준다():
    """사람이 밤에 손으로 돌릴지 판단하려면 이걸 알아야 한다.
    수집 윈도우가 '마지막 발송 이후'라 내일 이틀치를 덮는다.
    """
    report = build_report(
        failed_step="notify", run_url="https://x/1", briefing_date="2026-11-17"
    )

    assert "다음 날" in report
```

- [ ] **Step 2: 실패를 확인한다**

```bash
.venv/bin/python -m pytest tests/test_report_failure.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: `pipeline/report_failure.py`**

```python
"""단계 실패를 슬랙으로 알린다.

GitHub Actions의 실패 메일은 **크래시만 잡는다.** "소스 하나가 석 달째
조용", "7건 중 5건이 발췌 폴백"은 실행이 성공적으로 끝나므로 메일이 오지
않는다 — 그건 lib/guard가 본다. 여기는 진짜로 죽었을 때다.
"""

from __future__ import annotations

import os
import sys

from pipeline.lib.slack import SlackSender


def build_report(*, failed_step: str, run_url: str, briefing_date: str) -> str:
    return (
        f"브리핑 실패 — {briefing_date}\n"
        f"죽은 단계: {failed_step}\n"
        f"로그: {run_url}\n"
        "다음 날 실행이 이틀치를 덮으므로 급하지 않으면 그냥 둬도 된다. "
        "오늘 꼭 보내야 하면 workflow_dispatch로 다시 돌린다."
    )


def main() -> int:
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        print("SLACK_WEBHOOK_URL이 없다. 실패를 알릴 곳이 없다.", file=sys.stderr)
        return 1

    SlackSender(webhook_url=webhook).warn(
        [
            build_report(
                # 워크플로가 넘긴다. 없으면 "어딘가"라도 알리는 쪽이 낫다.
                failed_step=os.environ.get("FAILED_STEP", "(알 수 없음)"),
                run_url=os.environ.get("RUN_URL", "(없음)"),
                briefing_date=os.environ.get("BRIEFING_DATE", "(오늘)"),
            )
        ]
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인과 커밋**

```bash
.venv/bin/python -m pytest tests/test_report_failure.py -v
git add pipeline/report_failure.py tests/test_report_failure.py
git commit -m "feat: 단계 실패 리포트"
```

---

## Task 14: GitHub Actions

> **선행: Secrets 6개.** 없으면 워크플로가 돌지 않는다.

**Files:**
- Create: `.github/workflows/daily.yml`

- [ ] **Step 1: Secrets를 넣는다** (직접)

<https://github.com/predevho/topic-briefing/settings/secrets/actions> → **New repository secret**

```
ANTHROPIC_API_KEY
KAKAO_REST_API_KEY
KAKAO_CLIENT_SECRET
SLACK_WEBHOOK_URL
SUPABASE_URL
SUPABASE_SECRET_KEY
```

`VITE_SUPABASE_PUBLISHABLE_KEY`는 **넣지 않는다.** 파이프라인은 쓰지 않고, 그 키는 Vercel의 환경 변수에 있다.

- [ ] **Step 2: 포크 PR이 Secrets에 닿지 못하게 한다** (직접)

<https://github.com/predevho/topic-briefing/settings/actions> → **Fork pull request workflows** → "Require approval for all external contributors"

리포가 공개이므로 중요하다. 기본값이 이미 안전하지만 확인한다 — **워크플로에 임의 코드를 넣을 수 있는 사람은 Secrets를 꺼낼 수 있다.**

- [ ] **Step 3: `.github/workflows/daily.yml`**

```yaml
name: daily briefing

on:
  schedule:
    # UTC 22:20 (일~목) → KST 07:20 (월~금).
    # 정각을 피한 이유: GitHub Actions cron은 정각에 전 세계 작업이 몰려
    # 지연이 가장 크다.
    - cron: '20 22 * * 0-4'
  workflow_dispatch:

# 같은 날 두 번 돌지 않게 한다. notify의 AlreadySent 가드가 한 겹 더 있다.
concurrency:
  group: daily-briefing
  cancel-in-progress: false

jobs:
  briefing:
    runs-on: ubuntu-latest
    timeout-minutes: 20

    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      KAKAO_REST_API_KEY: ${{ secrets.KAKAO_REST_API_KEY }}
      KAKAO_CLIENT_SECRET: ${{ secrets.KAKAO_CLIENT_SECRET }}
      SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
      SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
      SUPABASE_SECRET_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
      # 비밀이 아니다 — 평문으로 둔다.
      PAGE_URL: https://topic-briefing.vercel.app
      MONTHLY_BUDGET_USD: '20'

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip

      - run: pip install -e .

      # 단계마다 id를 둔다 — 실패 리포트가 어디서 죽었는지 말하려면 필요하다.
      - id: collect
        run: python -m pipeline.collect
      - id: rank
        run: python -m pipeline.rank
      - id: enrich
        run: python -m pipeline.enrich
      - id: summarize
        run: python -m pipeline.summarize
      - id: notify
        run: python -m pipeline.notify

      - if: failure()
        env:
          FAILED_STEP: >-
            ${{ steps.collect.outcome == 'failure' && 'collect'
             || steps.rank.outcome == 'failure' && 'rank'
             || steps.enrich.outcome == 'failure' && 'enrich'
             || steps.summarize.outcome == 'failure' && 'summarize'
             || 'notify' }}
          RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: python -m pipeline.report_failure
```

**넣지 않는 것:**

- **재시도** — 실패하면 다음 날 윈도우가 이틀치를 덮는다(설계 0.3). `lib/http`와 SDK가 이미 일시 실패를 재시도하므로 여기까지 올라온 실패는 대부분 다시 해도 같다
- **`prune.py`** — 러너의 `data/`는 잡과 함께 사라진다. 지울 것이 없다
- **Node 셋업** — 프론트엔드는 Vercel이 푸시를 받고 따로 빌드한다
- **아티팩트 업로드** — 중간 산출물을 보존하면 "낡은 산출물로 이어가다 조용히 틀리는" 위험이 생긴다

- [ ] **Step 4: 손으로 한 번 돌린다**

```bash
gh workflow run "daily briefing"
sleep 30 2>/dev/null || true
gh run list --workflow "daily briefing" --limit 1
```

그리고 결과를 본다.

```bash
gh run watch
```

Expected: 성공. 카톡이 오고, 경고가 있으면 슬랙에도 온다.

- [ ] **Step 5: 실패 경로를 한 번 확인한다**

`ANTHROPIC_API_KEY` Secret을 일부러 틀린 값으로 바꾸고 돌린 뒤, **슬랙에 실패 리포트가 오는지** 본다. 확인하면 키를 되돌린다.

**이 단계를 건너뛰면 실패 알림이 동작하는지 영영 모른다.** 진짜 실패하는 날에 처음 시험하게 된다.

- [ ] **Step 6: 커밋**

```bash
git add .github/workflows/daily.yml
git commit -m "feat: GitHub Actions — 매일 07:20 KST, 재시도 없음"
```

---

## Task 15: 엔드투엔드 검증과 문서 갱신

- [ ] **Step 1: 전체 테스트와 권한 검사**

```bash
cd "$(git rev-parse --show-toplevel)"
.venv/bin/python -m pytest
bash scripts/verify_anon_access.sh
```

Expected: 전부 통과. `runs.output_tokens 차단`이 포함돼 있어야 한다.

- [ ] **Step 2: 토큰이 실제로 기록되는지 본다**

```bash
.venv/bin/python -c "
import os
from supabase import create_client
from pathlib import Path
env = dict(l.split('=',1) for l in Path('.env').read_text(encoding='utf-8').splitlines()
           if l.strip() and not l.startswith('#') and '=' in l)
c = create_client(env['SUPABASE_URL'].strip(), env['SUPABASE_SECRET_KEY'].strip())
rows = c.table('runs').select('briefing_date, input_tokens, output_tokens').order('briefing_date', desc=True).limit(3).execute()
for r in rows.data:
    print(f\"  {r['briefing_date']}  in={r['input_tokens']}  out={r['output_tokens']}\")
"
```

Expected: 최신 실행에 두 값이 모두 차 있다. `None`이면 Task 2·3의 배선이 끊긴 것이다.

- [ ] **Step 3: 가드를 억지로 울려 본다**

`.env`의 `MONTHLY_BUDGET_USD`를 아주 작게(예: `0.01`) 두고 `python -m pipeline.notify --force`를 돌린다. 슬랙에 크레딧 경고가 와야 한다. 확인하면 되돌린다.

**가드는 울려 봐야 동작을 안다.** 조용한 것이 "정상"인지 "안 돌고 있다"인지 구별되지 않는다.

- [ ] **Step 4: 요구사항 문서를 갱신한다**

`design/superpowers/specs/2026-11-11-requirements.md`에서 ⏳를 ✅로 바꾼다.

| ID | 고칠 내용 |
|---|---|
| O6 | 충족 위치 → `계획 3 Task 5` (`build_kakao_text`). 검증 → "Task 6에서 폰으로 두 링크 모두 확인" |
| O7 | 충족 위치 → `계획 3 Task 4` (`lib/kakao`). 검증 → "회전된 토큰만 저장. 2026-11-17 실측 만료 60일" |
| O8 | 충족 위치 → `계획 3 Task 7`. 검증 → "`SlackSender`에 `send` 메서드가 없다 — 구조로 막았다" |
| R27 | 충족 위치 → `계획 3 Task 8·9`. 검증 → "지표를 경과일로 바꾸고 최대공백 기준 등급 넷. 시드 실측 배정" |

- [ ] **Step 5: README를 갱신한다**

"## 매일 실행" 절 위에 한 줄을 더한다.

```markdown
**이제 자동으로 돈다.** GitHub Actions가 월~금 07:20 KST에 실행한다
(`.github/workflows/daily.yml`). 아래는 손으로 돌릴 때의 절차다.
```

그리고 "## 계획 3에서 메워야 할 구멍" 절을 지운다 — 둘 다 메웠다.

- [ ] **Step 6: 커밋**

```bash
git add design/ README.md
git commit -m "docs: 계획 3 완료 — 요구사항과 README 갱신"
git push origin main
```

---

## 완료 조건

- [ ] 카톡이 월~금 아침에 온다. 5건 + "외 N건", 200자 이하
- [ ] **두 링크가 모두 브리핑 페이지로 간다** — 버튼과 하단 앱 바로가기
- [ ] 슬랙이 경고만 받는다. `SlackSender`에 `send` 메서드가 없다
- [ ] `runs`에 `input_tokens`·`output_tokens`가 차 있다
- [ ] 소스 45개에 등급이 배정돼 있다 (fast 25 / weekly 10 / monthly 5 / none 5)
- [ ] 가드 셋이 울려 본 적이 있다 — 억지로라도
- [ ] 키를 틀리게 두고 돌렸을 때 슬랙에 실패 리포트가 왔다
- [ ] `scripts/verify_anon_access.sh`가 통과한다 (`runs.output_tokens` 차단 포함)
- [ ] 포크 PR이 Secrets에 닿지 못한다
- [ ] 전체 테스트 통과

---

## 다음

**Phase 2 (학습).** 좋아요·클릭·메모가 쌓이기 시작한다. 그 신호로 `interests.md`를 고쳐 나가는 것이 다음이고, **근거가 쌓인 뒤에** 설계한다.

### 이 계획에서 의도적으로 하지 않은 것

- **Admin API로 실제 청구액 조회** — 잔액을 주지 않는데 조직 관리 권한 키와 4~24시간 지연이 따라온다 (설계 0.1)
- **느린 소스 5개의 침묵 감시** — 침묵이 정보를 담지 않는다. 분기에 한 번 `check_feeds.py`로 본다 (설계 4.1)
- **워크플로 재시도** — 윈도우가 흡수한다 (설계 0.3)
- **중간 산출물 아티팩트 보존** — `rank`를 다시 내는 비용보다 "낡은 산출물로 이어가다 조용히 틀리는" 위험이 크다
- **외부 사용자에게 알림** — 카카오 메시지 API는 같은 서비스 내 발송만 지원한다. 다수 사용자가 목표가 되면 슬랙·텔레그램·이메일로 간다 (설계 2.1)
- **소스 침묵의 "한 번도 못 본" 경우** — 새로 넣은 소스와 죽은 소스를 구별할 수 없다. `check_feeds.py`가 넣을 때 확인하는 것으로 갈음한다
