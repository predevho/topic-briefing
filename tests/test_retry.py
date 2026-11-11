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
