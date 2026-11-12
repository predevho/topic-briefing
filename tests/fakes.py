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
        save_error: Exception | None = None,
    ) -> None:
        self._known = known or set()
        self._headlines = headlines or []
        self._last_sent = last_sent
        # 전송은 됐는데 DB 저장이 실패하는 경우를 재현한다.
        self._save_error = save_error
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
        if self._save_error is not None:
            raise self._save_error
        self.saved.append({"briefing_date": briefing_date, "summaries": summaries})


class FakeLLM:
    """미리 준비한 응답을 순서대로 돌려준다.

    HTTP 모킹이 필요 없고, 받은 프롬프트를 기록하므로 프롬프트 조립을
    테스트할 수 있다.
    """

    def __init__(self, responses: list, input_tokens: int = 1000) -> None:
        self._responses = list(responses)
        self._input_tokens = input_tokens
        self.prompts: list[str] = []
        # 호출할 때 넘긴 인자도 기록한다. effort와 max_tokens는 비용과
        # 잘림을 좌우하므로 "무엇을 넘겼는가"가 테스트 대상이다.
        self.calls: list[dict] = []

    def parse(self, *, prompt: str, output_format, effort, max_tokens: int = 16000):
        self.prompts.append(prompt)
        self.calls.append({
            "prompt": prompt,
            "output_format": output_format,
            "effort": effort,
            "max_tokens": max_tokens,
        })
        if not self._responses:
            raise AssertionError("FakeLLM에 준비된 응답이 없다. responses를 더 넣는다.")
        return self._responses.pop(0), self._input_tokens


class FakeSender:
    """호출 횟수를 세고, 필요하면 정해진 예외를 던진다."""

    def __init__(self, name: str = "fake", error: Exception | None = None) -> None:
        self.name = name
        self._error = error
        self.calls = 0
        self.briefings: list = []

    def send(self, *, briefing, raw) -> None:
        self.calls += 1
        self.briefings.append(briefing)
        if self._error is not None:
            raise self._error
