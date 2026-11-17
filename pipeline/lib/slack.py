"""슬랙 — 경고 전용.

**브리핑 전문을 보내지 않는다**(스펙 6.2). 읽는 자리는 페이지이고, 슬랙이
그 일을 중복하면 포맷터를 하나 더 유지해야 한다.

슬랙이 필요한 이유는 하나다 — **카카오 토큰이 만료되면 카톡으로는 그 사실을
알릴 수 없다.** 카톡이 유일한 채널이면 시스템이 조용히 죽는다. Incoming
Webhook URL은 만료가 없다.

그래서 이 채널 자신이 조용히 죽으면 안 된다. 실패는 숨기지 않고 던진다 —
"경고 전송 실패가 브리핑을 막지 않게" 하는 것은 호출부의 일이다(계획 3
Task 12). 삼키는 것과 막지 않는 것은 다르다.
"""

from __future__ import annotations

from typing import Callable

from pipeline.lib.http import post_json
from pipeline.lib.retry import Permanent

HEADER = "⚠️ 브리핑 경고"

# 실패 메시지에 쓰는 이름. **웹훅 URL은 그 자체가 비밀이다** — 가진 사람은
# 누구나 채널에 글을 쓸 수 있다. 리포가 퍼블릭이라 Actions 로그도 공개다.
LABEL = "Slack webhook"

SLACK_TIMEOUT = 15.0


def _escape(text: str) -> str:
    """슬랙이 반드시 바꾸라고 하는 세 글자를 엔티티로 바꾼다.

    경고에는 외부 사이트의 오류 본문이 섞인다(SourceError.message). 안 바꾸면
    `<!channel>`이 채널 멘션이 되고 `<http://x|토스>`가 링크로 위장한다.

    **&를 먼저 바꾼다.** 나중에 바꾸면 방금 만든 `&lt;`의 &까지 다시 바뀌어
    `&amp;lt;`가 된다.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_warnings(warnings: list[str]) -> str:
    """머리글 + 경고마다 한 줄. 경고 안의 줄바꿈은 그대로 둔다.

    collect_warnings가 "고쳐야 할 소스 2개:\\n  a: ...\\n  b: ..."처럼
    여러 줄 경고를 만든다. 첫 줄에만 글머리표를 붙인다.
    """
    lines = "\n".join(f"• {_escape(w)}" for w in warnings)
    return f"{HEADER}\n{lines}"


class SlackSender:
    """`Sender` 프로토콜을 **의도적으로 만족하지 않는다** — `send`가 없다.

    프로토콜을 만족하면 `notify`의 센더 목록에 넣을 수 있게 되고, 그러면
    언젠가 누군가 브리핑을 슬랙으로 보낸다. 구조로 막는다.
    """

    name = "slack"

    def __init__(
        self,
        *,
        webhook_url: str,
        post: Callable[..., str] = post_json,
    ) -> None:
        self._url = webhook_url
        self._post = post

    def warn(self, warnings: list[str]) -> None:
        """경고를 한 메시지로 보낸다. 경고가 없으면 아무것도 보내지 않는다.

        실패하면 Transient/Permanent를 던진다. 404(`no_service`)는 웹훅이
        폐기된 것이라 영구다 — 새로 발급해야 한다.
        """
        if not warnings:
            return

        reply = self._post(
            self._url,
            payload={"text": format_warnings(warnings)},
            timeout=SLACK_TIMEOUT,
            label=LABEL,
        )

        # 슬랙 웹훅은 성공하면 본문으로 정확히 "ok"를 준다. 프록시가 200에
        # HTML을 실어 보내면 상태 코드로는 성공으로 읽히므로 본문까지 본다.
        if reply.strip() != "ok":
            raise Permanent(f"{LABEL} 응답이 ok가 아니다: {reply[:200]!r}")
