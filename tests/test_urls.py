from pipeline.lib.urls import normalize_url


def test_utm_파라미터를_제거한다():
    url = "https://example.com/post?utm_source=rss&utm_medium=feed&id=7"
    assert normalize_url(url) == "https://example.com/post?id=7"


def test_추적_파라미터가_전부면_쿼리를_없앤다():
    url = "https://example.com/post?utm_source=rss&fbclid=abc"
    assert normalize_url(url) == "https://example.com/post"


def test_프래그먼트를_제거한다():
    url = "https://example.com/post#section-2"
    assert normalize_url(url) == "https://example.com/post"


def test_쿼리_순서가_달라도_같은_결과가_된다():
    a = normalize_url("https://example.com/p?b=2&a=1")
    b = normalize_url("https://example.com/p?a=1&b=2")
    assert a == b


def test_호스트를_소문자로_만든다():
    assert normalize_url("https://Example.COM/Post") == "https://example.com/Post"


def test_끝의_슬래시를_제거한다():
    assert normalize_url("https://example.com/post/") == "https://example.com/post"


def test_루트_경로의_슬래시는_남긴다():
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_같은_기사의_두_변형이_같은_키가_된다():
    """실제로 막으려는 상황."""
    a = "https://news.example.com/article/123?utm_source=rss&utm_campaign=daily"
    b = "https://news.example.com/article/123/"
    assert normalize_url(a) == normalize_url(b)
