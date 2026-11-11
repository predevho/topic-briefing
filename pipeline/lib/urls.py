"""URL 정규화. 같은 기사의 서로 다른 표기를 하나의 키로 만든다."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
