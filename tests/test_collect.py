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
