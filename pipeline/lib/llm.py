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

# 비스트리밍 요청의 기본 출력 상한.
DEFAULT_MAX_TOKENS = 16000

# 비스트리밍으로 보낼 수 있는 max_tokens의 상한.
#
# SDK가 스스로 막는다(`_base_client._calculate_nonstreaming_timeout`):
#   expected_time = 3600 * max_tokens / 128_000
#   expected_time > 600초 이면 ValueError
# → max_tokens > 128_000 * 600 / 3600 = 21,333 이면 거부된다.
#
# 2026-11-12 실측으로 걸렸다. 240건 채점에 34,400을 요청했더니 SDK가 1초
# 만에 "Streaming is required for operations that may take longer than
# 10 minutes"로 거부했다. 넘으면 스트리밍으로 보낸다.
NONSTREAMING_MAX_TOKENS = 21_333

Effort = Literal["low", "medium", "high", "xhigh", "max"]
TOut = TypeVar("TOut", bound=BaseModel)
TResult = TypeVar("TResult")


class RefusedError(Permanent):
    """정책 거부. 같은 입력을 다시 보내도 또 거부되므로 재시도하지 않는다."""


class TruncatedError(Permanent):
    """max_tokens에 걸려 출력이 잘렸다.

    Permanent인 이유: 같은 max_tokens로 다시 보내면 똑같이 잘린다.
    재시도가 아니라 max_tokens를 올리거나 입력을 줄여야 한다.
    """


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


def needs_streaming(max_tokens: int) -> bool:
    """이 max_tokens는 스트리밍으로 보내야 하나.

    호출하는 단계가 신경 쓸 일이 아니다 — 래퍼가 알아서 고른다.
    """
    return max_tokens > NONSTREAMING_MAX_TOKENS


def classify_response(
    *,
    stop_reason: str | None,
    stop_details: object | None,
    parsed: object | None,
    max_tokens: int,
) -> None:
    """응답 자체의 문제를 분류해 던진다. 문제가 없으면 아무것도 하지 않는다.

    SDK 호출과 분리해 둔 덕분에 네트워크 없이 테스트할 수 있다
    (`classify_sdk_error`와 같은 이유).

    **순서가 중요하다.** 거부와 잘림은 둘 다 HTTP 200으로 오고, 그때
    content를 먼저 읽으면 엉뚱한 것을 보게 된다.
    """
    # 거부는 예외가 아니라 200 + stop_reason으로 온다. stop_details는
    # 거부일 때만 채워지고 그 외에는 None이다.
    if stop_reason == "refusal":
        category = getattr(stop_details, "category", None)
        raise RefusedError(
            f"정책 거부 (category={category}). 서버 측 폴백도 실패했다. "
            f"같은 입력은 다시 보내도 거부된다."
        )

    # 잘림을 스키마 실패와 구분해야 한다. 구분하지 않으면 증상이
    # "구조화된 출력이 비어 있다"로 나와 원인을 못 찾는다 — 실제로는
    # max_tokens가 모자란 것이고, 재시도해도 똑같이 잘린다.
    if stop_reason == "max_tokens":
        raise TruncatedError(
            f"출력이 max_tokens({max_tokens:,})에 걸려 잘렸다. 재시도해도 같다. "
            f"max_tokens를 올리거나(그만큼 크면 스트리밍이 필요하다) "
            f"입력 항목 수를 줄인다."
        )

    # parsed_output은 content 블록을 훑는 프로퍼티다. 스키마를 못 맞췄으면
    # None이 나온다. 위 두 경우를 걸러낸 뒤에야 이 판정이 의미를 갖는다.
    if parsed is None:
        raise SchemaError(f"구조화된 출력이 비어 있다 (stop_reason={stop_reason})")


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
        # beta.messages.*를 쓴다. 비-beta 쪽에는 betas·fallbacks 인자가
        # 없어서 거부 폴백을 넘길 수 없다
        # (test_parse에_필요한_인자가_모두_있다가 고정한다).
        #
        # thinking은 **넘기지 않는다.** Opus 5.5는 사고가 항상 켜져 있고
        # {"type": "disabled"}나 budget_tokens는 어떤 effort에서도 400이다.
        # 깊이 조절은 output_config의 effort로만 한다.
        kwargs = dict(
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
            # output_format은 **이 헬퍼들 자신의 인자**다. messages.create의
            # 폐기된 output_format과 다르다(create에서는 output_config.format을
            # 쓴다). pydantic 모델 클래스를 넘기면 응답이 그 스키마를 따르고
            # parsed_output으로 검증된 객체가 나온다.
            output_format=output_format,
            messages=[{"role": "user", "content": prompt}],
        )

        try:
            if needs_streaming(max_tokens):
                # SDK가 비스트리밍을 거부하는 구간이다. stream의
                # get_final_message()도 parse와 같은 ParsedBetaMessage를
                # 돌려주므로 아래 처리는 한 가지로 끝난다.
                with self._client.beta.messages.stream(**kwargs) as stream:
                    response = stream.get_final_message()
            else:
                response = self._client.beta.messages.parse(**kwargs)
        except Exception as error:  # noqa: BLE001 — classify_sdk_error가 선별한다
            raise classify_sdk_error(error) from error

        # 거부·잘림·스키마 실패를 순서대로 가려낸다. 셋 다 HTTP 200으로 온다.
        parsed = response.parsed_output
        classify_response(
            stop_reason=response.stop_reason,
            stop_details=response.stop_details,
            parsed=parsed,
            max_tokens=max_tokens,
        )
        assert parsed is not None     # classify_response가 None이면 던진다

        return parsed, response.usage.input_tokens
