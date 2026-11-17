"""전송 대상.

보낼 곳이 여러 곳이 될 것이 정해져 있으므로(계획 3에서 카카오톡과 슬랙)
프로토콜로 추상화한다. 계획 1은 ConsoleSender만 구현한다.

계획 3에서 추가될 것:
- KakaoSender  — 텍스트 템플릿 200자, 상위 5건 + "외 N건" + 페이지 버튼
- SlackSender  — 경고 전용. 카카오 토큰이 만료되면 카톡으로는 그 사실을
                 알릴 수 없으므로, 만료가 없는 채널이 하나 필요하다.
"""

import json
from datetime import datetime
from typing import Protocol, runtime_checkable

from pipeline.lib.http import DEFAULT_TIMEOUT, FORM, post_form
from pipeline.lib.timeutil import KST
from pipeline.models import Briefing, RawBundle

TOPIC_MARKS = {
    "AI": "🤖",
    "backend": "⚙️",
    "infra": "🏗️",
    "tooling": "🔧",
}


@runtime_checkable
class Sender(Protocol):
    """브리핑을 어딘가로 내보내는 것.

    runtime_checkable이라 `isinstance(sender, Sender)`로 확인할 수 있다
    (메서드 이름만 본다 — 서명은 보지 않는다).
    """

    name: str

    def send(self, *, briefing: Briefing, raw: RawBundle) -> None:
        ...


def collect_warnings(*, briefing: Briefing, raw: RawBundle) -> list[str]:
    """사람이 조치해야 하는 것만 모은다.

    일시 실패(transient)는 넣지 않는다 — 내가 할 일이 없고, 매번 알리면
    알림 피로가 생겨서 정작 중요한 경고를 무시하게 된다.
    """
    warnings: list[str] = []

    fallbacks = [
        summary for summary in briefing.summaries
        if summary.article.body_source == "rss_excerpt"
    ]
    if fallbacks:
        # "품질 저하"라고 쓰지 않는다. 2026-11-12 실측: 크롤링이 막힌 소스가
        # 피드에 전문을 담는 경우가 많다(Netflix 15,633자). 멀쩡한 날에
        # 품질 경고가 뜨면 경고를 무시하게 된다. 길이를 함께 보여 주고
        # 판단은 읽는 사람에게 맡긴다.
        lines = [f"발췌로 요약한 글 {len(fallbacks)}건:"]
        lines += [
            f"  {summary.article.ranked.item.source} "
            f"({len(summary.article.body):,}자): "
            f"{summary.article.fallback_reason}"
            for summary in fallbacks
        ]
        warnings.append("\n".join(lines))

    config_errors = [error for error in raw.errors if error.kind == "config"]
    if config_errors:
        lines = [f"고쳐야 할 소스 {len(config_errors)}개:"]
        lines += [f"  {error.source}: {error.message}" for error in config_errors]
        warnings.append("\n".join(lines))

    moved = [error for error in raw.errors if error.kind == "moved"]
    if moved:
        lines = [f"주소가 이전된 소스 {len(moved)}개 (sources.yaml 갱신):"]
        lines += [f"  {error.source}: {error.message}" for error in moved]
        warnings.append("\n".join(lines))

    return warnings


class ConsoleSender:
    """터미널에 브리핑을 출력한다.

    계획 1의 유일한 전송 대상이다. 초기 튜닝은 결과를 보면서 프롬프트를
    고치는 일이고, 그건 터미널에서 하는 작업이다.
    """

    name = "console"

    def send(self, *, briefing: Briefing, raw: RawBundle) -> None:
        when = datetime.fromisoformat(briefing.window_end).astimezone(KST)
        count = len(briefing.summaries)

        print()
        print(f"📡 {when.strftime('%m/%d (%a)')} IT 브리핑 · "
              f"{count}건  (후보 {briefing.considered}건)")
        print("=" * 78)

        if count == 0:
            print()
            print(f"  후보 {briefing.considered}건을 봤지만 기준을 넘는 글이 없습니다.")
            print("  조용한 날입니다 — 시스템은 정상입니다.")
        else:
            for position, summary in enumerate(briefing.summaries, start=1):
                item = summary.article.ranked.item
                mark = TOPIC_MARKS.get(summary.article.ranked.topic, "📄")
                # 발췌로 요약한 건은 표시한다. 요약이 얕을 수 있다는 걸
                # 읽는 사람이 알아야 한다.
                출처표시 = (
                    "발췌" if summary.article.body_source == "rss_excerpt" else "본문"
                )

                print()
                print(f"  [{position}] {summary.article.ranked.score:3d}  "
                      f"{mark}  {summary.headline}")
                for bullet in summary.bullets:
                    print(f"           • {bullet}")
                print(f"           왜: {summary.why_it_matters}")
                print(f"           {item.source} · {출처표시}  {item.url}")

        for warning in collect_warnings(briefing=briefing, raw=raw):
            print()
            print("⚠️  " + warning.replace("\n", "\n    "))

        print()


# --- 카카오톡 ---
#
# 기본 텍스트 템플릿의 상한은 200자다(스펙 6.1). 넘으면 발송이 **거부된다**
# — 즉 그날 브리핑이 안 간다. 머리글 약 19자 + 건당 약 33자(번호 3자 +
# 헤드라인 30자)라서 5건이 상한이다.
KAKAO_MAX_TEXT = 200
KAKAO_TOP_N = 5

SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def kakao_len(text: str) -> int:
    """카카오가 셀 수 있는 **가장 큰 값**으로 센다.

    Python의 `len()`은 코드 포인트를 센다 — 📡(U+1F4E1)는 1이다. 많은
    플랫폼은 UTF-16 코드 단위로 세고, 그러면 📡는 2다. 어느 쪽인지 모르는
    채로 작은 쪽을 믿으면 상한을 넘겨 발송이 거부된다.

    여유가 실제로 한 자다. 2026-11-17 실측 — 헤드라인 30자(DB 상한) 5건에
    발행 12건이면 `len()` 199자인데 UTF-16으로는 **200단위**다. 상한을
    믿고 센 쪽이 틀리면 그날 브리핑이 안 간다.

    `//  2`인 이유: utf-16-le 인코딩은 코드 단위당 정확히 2바이트다
    (BOM 없는 변종을 골라야 앞에 2바이트가 붙지 않는다).
    """
    return len(text.encode("utf-16-le")) // 2


def build_kakao_text(briefing_date: str, headlines: list[str], total: int) -> str:
    """카톡 본문을 만든다. **반드시 200자 이하를 돌려준다.**

    `briefing_date`는 `YYYY-MM-DD`(KST 기준 날짜)다. `headlines`는 상위 건의
    헤드라인, `total`은 발행 전체 건수다. 둘을 나눈 이유는 "5건 보여주고
    외 2건"을 쓰려면 전체 수를 알아야 하기 때문이다.

    길이를 못 맞추면 조용히 자르지 않고 **건수를 줄인다.** 잘린 헤드라인은
    읽는 사람에게 아무 뜻이 없지만, 건수가 줄어든 것은 "외 N건"이 알려준다.
    """
    month_day = briefing_date[5:].replace("-", "/")   # 2026-11-17 → 11/17
    header = f"📡 {month_day} IT 브리핑 · {total}건"

    if total == 0:
        return f"{header}\n\n오늘은 기준을 넘긴 글이 없습니다."

    # 많이 싣는 쪽부터 시도해 처음 들어맞는 것을 쓴다.
    for shown in range(min(KAKAO_TOP_N, len(headlines)), 0, -1):
        lines = [f"{i}. {h}" for i, h in enumerate(headlines[:shown], 1)]
        rest = total - shown
        if rest > 0:
            lines.append(f"   외 {rest}건")
        text = header + "\n\n" + "\n".join(lines)
        if kakao_len(text) <= KAKAO_MAX_TEXT:
            return text

    # 한 건도 못 넣는다 — 헤드라인이 비정상적으로 길다. 건수만 알린다.
    # 조용히 끝나지 않는 것이 핵심이다(요구사항 O2).
    return f"{header}\n\n   외 {total}건"


class KakaoSender:
    """나에게 보내기. `Sender` 프로토콜을 만족한다.

    "나에게 보내기"에는 일간·월간 제공량 제한이 없다 — 제한은 "친구에게
    발송"에만 적용된다(스펙 6.1).
    """

    name = "kakao"

    def __init__(self, *, access_token: str, page_url: str, post=None) -> None:
        self._token = access_token
        self._page = page_url
        # 기본 전송은 lib/http.py의 post_form이다. 전송과 실패 분류가
        # 거기 한곳에 있다.
        self._post = post or post_form

    def send(self, *, briefing: Briefing, raw: RawBundle) -> None:
        # **window_end는 UTC다.** 그대로 [:10]을 자르면 전날이 된다 —
        # cron이 22:20 UTC(=07:20 KST 다음날)라서 예외가 아니라 매 실행이
        # 그렇다. ConsoleSender와 같은 규칙으로 KST로 바꿔 읽는다.
        when = datetime.fromisoformat(briefing.window_end).astimezone(KST)

        text = build_kakao_text(
            briefing_date=when.date().isoformat(),
            headlines=[s.headline for s in briefing.summaries[:KAKAO_TOP_N]],
            total=len(briefing.summaries),
        )

        template = {
            "object_type": "text",
            "text": text,
            # 두 주소를 같게 둔다. 그리고 이 호스트가 카카오 콘솔의
            # [제품 링크 관리] → [웹 도메인]에 등록돼 있어야 한다 —
            # 없으면 발송은 성공하고 버튼만 죽는다(스펙 6.1).
            "link": {"web_url": self._page, "mobile_web_url": self._page},
            "button_title": "전체 보기",
        }

        # **form-urlencoded에 template_object를 JSON 문자열로 넣는다.**
        # 본문 전체를 JSON으로 보내면 받지 않는다.
        self._post(
            SEND_URL,
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": FORM,
            },
            timeout=DEFAULT_TIMEOUT,
        )
