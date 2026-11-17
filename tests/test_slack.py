"""슬랙 경고 테스트.

실제 슬랙을 부르지 않는다. `post`를 주입해 **무엇을 보내는지**만 본다.
HTTP 실패 분류는 `post_json`의 책임이고 tests/test_http.py에서 본다.
"""

import pytest

from pipeline.lib.retry import Permanent
from pipeline.lib.sender import Sender
from pipeline.lib.slack import SlackSender, format_warnings

URL = "https://hooks.slack.test/services/T000/B000/secret"


def _sender(sent: list, reply: str = "ok") -> SlackSender:
    def fake_post(url, *, payload, timeout, label):
        sent.append({"url": url, "payload": payload, "label": label})
        return reply

    return SlackSender(webhook_url=URL, post=fake_post)


def test_경고가_없으면_보내지_않는다():
    """빈 메시지를 매일 보내면 그게 알림 피로다."""
    sent = []
    _sender(sent).warn([])

    assert sent == []


def test_경고를_한_메시지로_묶어_보낸다():
    sent = []
    _sender(sent).warn(["소스 죽음: 404", "토큰 만료 10일 전"])

    assert len(sent) == 1
    text = sent[0]["payload"]["text"]
    assert "404" in text
    assert "토큰 만료" in text


def test_머리글이_무엇에_대한_경고인지_말한다():
    sent = []
    _sender(sent).warn(["무언가"])

    assert "브리핑" in sent[0]["payload"]["text"]


def test_전문을_보내는_메서드가_없다():
    """스펙 6.2 — 브리핑은 슬랙으로 가지 않는다. **구조로** 막는다.

    send가 있으면 Sender 프로토콜을 만족해 notify의 센더 목록에 들어갈 수
    있게 되고, 언젠가 누군가 브리핑을 슬랙으로 보낸다.
    """
    assert not hasattr(SlackSender, "send")
    assert not isinstance(SlackSender(webhook_url=URL), Sender)


def test_슬랙_제어문자를_이스케이프한다():
    """경고에는 **외부 사이트의 오류 본문**이 섞인다(SourceError.message).

    슬랙은 `<`, `>`, `&`를 반드시 엔티티로 바꾸라고 한다. 안 바꾸면
    `<!channel>`이 그대로 채널 멘션이 되고, `<http://x|y>`가 링크로 위장한다.
    """
    text = format_warnings(["응답 본문: <!channel> & <http://evil.test|토스>"])

    assert "<!channel>" not in text
    assert "&lt;!channel&gt;" in text
    assert "&amp;" in text
    assert "<http" not in text


def test_오류_메시지에_웹훅_URL을_싣지_않는다():
    """웹훅 URL은 그 자체가 비밀이다 — 가진 사람은 채널에 글을 쓸 수 있다.

    리포가 퍼블릭이라 Actions 로그도 공개다. 실패 메시지는 label로 쓴다.
    """
    sent = []
    _sender(sent).warn(["무언가"])

    assert sent[0]["url"] == URL                 # 요청은 진짜 주소로 간다
    assert URL not in sent[0]["label"]           # 메시지용 이름은 주소가 아니다
    assert "secret" not in sent[0]["label"]


def test_ok가_아니면_도착하지_않은_것이다():
    """슬랙 웹훅은 성공하면 본문으로 `ok`를 준다.

    프록시나 점검 페이지가 200에 HTML을 실어 보내면 상태 코드만으로는
    성공으로 읽힌다. 경고 채널이 **조용히 죽는 것**이 이 클래스가 막으려는
    바로 그 일이다.
    """
    with pytest.raises(Permanent, match="ok"):
        _sender([], reply="<html>maintenance</html>").warn(["무언가"])
