from pipeline.lib.text import strip_html


def test_태그를_벗긴다():
    assert strip_html("<p>본문이다</p>") == "본문이다"


def test_중첩된_태그도_벗긴다():
    assert strip_html("<div><p>강조 <strong>된</strong> 글</p></div>") == "강조 된 글"


def test_블록_태그는_공백으로_나눈다():
    """<li>a</li><li>b</li>를 그냥 이으면 "ab"가 된다. GeekNews 발췌가
    전부 <ul><li> 목록이라 이게 깨지면 단어가 붙어 버린다.
    """
    assert strip_html("<ul><li>첫째</li><li>둘째</li></ul>") == "첫째 둘째"


def test_br도_공백으로_나눈다():
    assert strip_html("한 줄<br/>다음 줄") == "한 줄 다음 줄"


def test_인라인_태그는_붙인다():
    """<strong>은 단어 중간에 올 수 있다. 공백을 넣으면 단어가 쪼개진다."""
    assert strip_html("<p>Postgre<strong>SQL</strong></p>") == "PostgreSQL"


def test_엔티티를_되돌린다():
    assert strip_html("<p>a &amp; b &lt; c &quot;d&quot;</p>") == 'a & b < c "d"'


def test_공백을_하나로_모은다():
    """피드의 HTML은 들여쓰기와 줄바꿈이 섞여 있다. 그대로 두면
    프롬프트에 빈 줄만 들어간다.
    """
    assert strip_html("<p>앞\n\n   뒤</p>") == "앞 뒤"


def test_앞뒤_공백을_없앤다():
    assert strip_html("  <p> 가운데 </p>  ") == "가운데"


def test_script와_style_내용은_버린다():
    """본문이 아니다. 프롬프트에 들어가면 토큰만 먹는다."""
    assert strip_html("<p>글</p><script>var x = 1;</script>") == "글"
    assert strip_html("<style>.a{color:red}</style><p>글</p>") == "글"


def test_태그가_없으면_내용만_정리한다():
    assert strip_html("그냥  텍스트") == "그냥 텍스트"


def test_빈_문자열은_빈_문자열이다():
    assert strip_html("") == ""


def test_닫히지_않은_태그도_예외를_내지_않는다():
    """피드의 HTML은 깨져 있는 경우가 흔하다. 한 건 때문에 수집이
    멈추면 안 된다.
    """
    assert strip_html("<p>앞<div>뒤") == "앞 뒤"


def test_주석은_버린다():
    assert strip_html("<!-- 숨김 --><p>보임</p>") == "보임"


def test_링크의_주소는_버리고_글자만_남긴다():
    """Lobsters 발췌가 <a href=...>Comments</a> 하나뿐이다. 주소까지
    남기면 프롬프트가 URL로 가득 찬다.
    """
    assert strip_html('<p><a href="https://lobste.rs/s/abc">Comments</a></p>') == "Comments"
