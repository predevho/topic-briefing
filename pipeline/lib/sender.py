"""전송 대상.

보낼 곳이 여러 곳이 될 것이 정해져 있으므로(계획 3에서 카카오톡과 슬랙)
프로토콜로 추상화한다. 계획 1은 ConsoleSender만 구현한다.

계획 3에서 추가될 것:
- KakaoSender  — 텍스트 템플릿 200자, 상위 5건 + "외 N건" + 페이지 버튼
- SlackSender  — 경고 전용. 카카오 토큰이 만료되면 카톡으로는 그 사실을
                 알릴 수 없으므로, 만료가 없는 채널이 하나 필요하다.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

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
