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
