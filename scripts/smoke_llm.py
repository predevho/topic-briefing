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
