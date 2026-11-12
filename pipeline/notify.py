"""04.5 전송: 센더로 내보내고 실행 이력을 남긴다.

순서가 중요하다 — **하나라도 전송에 성공한 뒤에 `status='sent'` 이력을
남긴다.** 거꾸로 하면 전송이 실패했는데 "이미 보냄"으로 기록되어, 원인을
고친 뒤 재실행이 막히고 그날 브리핑이 사라진다.

계획 1의 센더는 ConsoleSender 하나다. 계획 3에서 KakaoSender와
SlackSender가 추가된다.

실행:
  python -m pipeline.notify
  python -m pipeline.notify --force    # 이미 보낸 윈도우를 다시 보낸다
"""

import argparse
from datetime import datetime, timezone

from pipeline.lib.secrets import require
from pipeline.lib.sender import ConsoleSender, Sender
from pipeline.lib.store import LocalStore, RemoteStore, SupabaseStore
from pipeline.lib.timeutil import KST
from pipeline.models import Briefing, RankedBundle, RawBundle


class AlreadySentError(RuntimeError):
    """이 윈도우는 이미 전송됐다. --force로 우회할 수 있다."""


class AllSendersFailedError(RuntimeError):
    """모든 센더가 실패했다.

    `status='failed'` 실행 기록은 **남는다**(소스 침묵 감지의 입력이므로).
    `last_sent_at`이 `status='sent'`만 보기 때문에 재실행은 막히지 않는다.
    """


def notify(
    *,
    briefing: Briefing,
    ranked: RankedBundle,
    raw: RawBundle,
    remote: RemoteStore,
    briefing_date: str,
    senders: list[Sender],
    force: bool = False,
    now: datetime | None = None,
) -> None:
    """센더로 내보내고 이력을 남긴다. 0건도 내보내고, 실패해도 기록한다."""
    if not senders:
        raise ValueError(
            "센더가 하나도 없다. 설정 실수로 아무 데도 보내지 않는 것을 막는다."
        )

    window_start = datetime.fromisoformat(briefing.window_start)
    window_end = datetime.fromisoformat(briefing.window_end)
    moment = now or datetime.now(timezone.utc)

    def record(status: str, sent_at: datetime | None, extra: list[dict]) -> None:
        """실행 이력을 남긴다. 성공·실패 양쪽에서 같은 값을 쓴다."""
        remote.record_run(
            window_start=window_start,
            window_end=window_end,
            status=status,
            sent_at=sent_at,
            collected_count=len(raw.items),
            considered_count=briefing.considered,
            max_score=ranked.max_score,
            published_count=len(briefing.summaries),
            source_counts=raw.source_counts,
            input_tokens=None,
            errors=[error.model_dump() for error in raw.errors] + extra,
        )

    if not force:
        last = remote.last_sent_at()
        if last is not None and last >= window_end:
            # 센더를 부르기 전에 막는다. 부르고 나서 막으면 막은 의미가 없다.
            raise AlreadySentError(
                f"이 윈도우(~{window_end.isoformat()})는 이미 전송됐다 "
                f"(마지막 발송: {last.isoformat()}). "
                f"다시 보내려면 --force를 쓴다."
            )

    # 센더는 서로 독립이다. 계획 3에서 카톡 토큰이 만료돼도 슬랙은 가야 한다.
    delivered: list[str] = []
    failures: list[dict] = []

    for sender in senders:
        try:
            sender.send(briefing=briefing, raw=raw)
            delivered.append(sender.name)
        except Exception as error:  # noqa: BLE001 — 센더 단위로 격리한다
            failures.append({
                "source": f"sender:{sender.name}",
                "kind": "config",
                "message": f"{type(error).__name__}: {error}",
            })

    if not delivered:
        # 아무 데도 못 보냈다. status='failed'로 **기록은 남기고** 예외를 올린다.
        #
        # 기록을 남기는 이유: source_counts가 소스 침묵 경고의 유일한 입력이고,
        # 실패한 날이 빠지면 경고가 그만큼 늦어진다.
        # 재실행이 막히지 않는 이유: last_sent_at이 status='sent'만 보기 때문이다.
        record("failed", None, failures)
        detail = "; ".join(failure["message"] for failure in failures)
        raise AllSendersFailedError(
            f"모든 센더가 실패했다 ({len(senders)}개). "
            f"실행 기록은 status='failed'로 남았고 전송 이력은 갱신되지 않았으므로, "
            f"원인을 고친 뒤 그대로 재실행하면 된다. {detail}"
        )

    if briefing.summaries:
        # 전송은 이미 됐다. 여기서 예외를 올리면 실행 기록이 남지 않고,
        # 재실행이 **이미 보낸 브리핑을 다시 보낸다.** 사용자에게 두 번
        # 가는 것이 페이지가 비는 것보다 나쁘다. 실패를 기록에 남기고 계속한다.
        try:
            remote.save_articles(
                briefing_date=briefing_date,
                summaries=briefing.summaries,
            )
        except Exception as error:  # noqa: BLE001 — 전송은 이미 성공했다
            failures.append({
                "source": "save_articles",
                "kind": "transient",
                "message": f"{type(error).__name__}: {error}",
            })

    # 0건이어도 반드시 남긴다. 남기지 않으면 다음 윈도우가 계속 늘어나
    # 같은 항목을 반복 평가하게 된다.
    record("sent", moment, failures)


def main() -> None:
    parser = argparse.ArgumentParser(description="브리핑 전송")
    parser.add_argument("--force", action="store_true",
                        help="이미 전송한 윈도우를 다시 보낸다")
    args = parser.parse_args()

    date = datetime.now(timezone.utc).astimezone(KST).date().isoformat()
    store = LocalStore(date=date)

    notify(
        briefing=store.read("briefing", Briefing),
        ranked=store.read("ranked", RankedBundle),
        raw=store.read("raw", RawBundle),
        remote=SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SECRET_KEY")),
        briefing_date=date,
        # 계획 3에서 KakaoSender·SlackSender가 이 목록에 추가된다.
        senders=[ConsoleSender()],
        force=args.force,
    )

    print(f"전송 완료 ({date})")


if __name__ == "__main__":
    main()
