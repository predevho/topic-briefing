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
