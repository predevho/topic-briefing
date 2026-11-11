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
