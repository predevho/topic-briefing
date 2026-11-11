"""피드에서 온 HTML을 글자만 남긴 텍스트로 바꾼다.

RSS·Atom의 `summary`/`content`는 거의 항상 HTML이다. 그대로 두면
- 선별 프롬프트에 `<div><ul><li>`가 들어가 토큰을 먹고 신호를 흐린다
- 본문 확보 실패 시 폴백 본문(`body_source="rss_excerpt"`)에 태그가 남아
  요약 프롬프트까지 번진다

그래서 수집 단계에서 한 번 벗겨 저장한다. 길이는 자르지 않는다 —
선별은 `excerpt[:400]`만 쓰지만 폴백 본문은 전체를 쓴다.
"""

import re
from html.parser import HTMLParser

# 이 태그들은 경계가 곧 띄어쓰기다. <li>첫째</li><li>둘째</li>를 그냥 이으면
# "첫째둘째"가 된다. 반대로 <strong>은 단어 중간에 오므로 붙여야 한다.
BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "ol", "p", "pre", "section", "table", "tbody", "td",
    "tfoot", "th", "thead", "tr", "ul",
})

# 글이 아니다. 내용까지 버린다.
DROP_TAGS = frozenset({"script", "style"})

_WHITESPACE = re.compile(r"\s+")


class _TextOnly(HTMLParser):
    """태그를 버리고 글자만 모은다."""

    def __init__(self) -> None:
        # convert_charrefs=True(기본값)면 &amp; 같은 엔티티를 알아서 되돌려준다.
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._dropping = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in DROP_TAGS:
            self._dropping += 1
        elif tag in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_TAGS:
            # 0 밑으로 내려가지 않게 한다. 깨진 HTML은 여는 태그 없이
            # 닫는 태그만 나오는 경우가 있다.
            self._dropping = max(0, self._dropping - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._dropping:
            self.parts.append(data)


def strip_html(value: str) -> str:
    """HTML에서 글자만 남긴다. 공백은 하나로 모으고 앞뒤를 자른다.

    HTMLParser는 깨진 HTML에도 예외를 내지 않는다. 피드의 HTML은 자주
    깨져 있고, 한 항목 때문에 수집이 멈추면 안 되므로 이 성질이 필요하다.
    """
    parser = _TextOnly()
    parser.feed(value)
    parser.close()
    return _WHITESPACE.sub(" ", "".join(parser.parts)).strip()
