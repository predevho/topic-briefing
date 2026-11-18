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
import sys
from datetime import date, datetime, timezone
from typing import Callable

from pipeline.lib.guard import (
    BUDGET_WARN_RATIO,
    SPIKE_FACTOR,
    load_seed_last_seen,
    month_cost_usd,
    new_source_failures,
    silent_sources,
    token_expiring,
    token_spike,
)
from pipeline.lib.config import Source, load_sources
from pipeline.lib.kakao import KakaoTokens, access_token, rotated_expiry, should_store
from pipeline.lib.llm import MODEL
from pipeline.lib.retry import Permanent, Transient
from pipeline.lib.secrets import optional, require
from pipeline.lib.sender import ConsoleSender, KakaoSender, Sender
from pipeline.lib.slack import send_warnings
from pipeline.lib.store import LocalStore, RemoteStore, SupabaseStore
from pipeline.lib.timeutil import KST
from pipeline.models import Briefing, RankedBundle, RawBundle

# 가드가 읽는 실행 이력의 길이. 최고 침묵 임계값(200일)보다 길어야 한다 —
# 짧으면 그보다 오래된 양수를 못 보고 시드 날짜로 물러서 경과일이 부푼다.
GUARD_LOOKBACK_DAYS = 400

Warn = Callable[[str], None]


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
    warn: Warn | None = None,
    sources: list[Source] | None = None,
    budget_usd: float | None = None,
) -> None:
    """센더로 내보내고 이력을 남긴다. 0건도 내보내고, 실패해도 기록한다.

    `warn`을 주면 가드(침묵·토큰 만료·크레딧)를 돌리고, 센더 실패와 페이지 저장
    실패도 경고로 낸다. 경고는 **브리핑을 막지 않는다** — 가드나 경고 채널이
    터져도 발송과 기록은 그대로 간다.
    """
    if not senders:
        raise ValueError(
            "센더가 하나도 없다. 설정 실수로 아무 데도 보내지 않는 것을 막는다."
        )

    window_start = datetime.fromisoformat(briefing.window_start)
    window_end = datetime.fromisoformat(briefing.window_end)
    moment = now or datetime.now(timezone.utc)

    # rank와 summarize가 쓴 토큰을 합친다. 크레딧 가드(계획 3)가 읽는다.
    #
    # 한쪽만 있는 경우가 실제로 생긴다 — 수집이 0건이면 rank가 LLM을
    # 부르지 않아 ranked.tokens가 None이다. 그때 다른 쪽만 세는 것이
    # 맞다. 둘 다 None이면 None으로 남긴다: **"모른다"와 "0"은 다르고**,
    # 0으로 적으면 가드가 "안 썼다"로 읽어 거짓 안심을 한다.
    totals = None
    if ranked.tokens and briefing.tokens:
        totals = ranked.tokens + briefing.tokens
    elif ranked.tokens or briefing.tokens:
        totals = ranked.tokens or briefing.tokens

    def record(status: str, sent_at: datetime | None, extra: list[dict]) -> None:
        """실행 이력을 남긴다. 성공·실패 양쪽에서 같은 값을 쓴다."""
        remote.record_run(
            briefing_date=briefing_date,
            window_start=window_start,
            window_end=window_end,
            status=status,
            sent_at=sent_at,
            collected_count=len(raw.items),
            considered_count=briefing.considered,
            max_score=ranked.max_score,
            published_count=len(briefing.summaries),
            source_counts=raw.source_counts,
            input_tokens=totals.input if totals else None,
            output_tokens=totals.output if totals else None,
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

    def alert(line: str) -> None:
        """경고 하나를 낸다. 경고 채널이 터져도 브리핑은 계속한다."""
        if warn is None:
            return
        try:
            warn(line)
        except Exception as problem:  # noqa: BLE001 — 경고가 브리핑을 막으면 안 된다
            print(f"경고 전달 실패(브리핑은 계속한다): {problem} — {line}", file=sys.stderr)

    # 가드는 브리핑과 독립이다. 터져도 발송을 막지 않는다 — 경고 때문에
    # 브리핑이 안 가면 주객이 전도된다. AlreadySent 검사 **뒤**에 두는 이유:
    # 재실행이 같은 경고를 또 보내면 그것도 알림 피로다.
    if warn is not None:
        try:
            lines = guard_warnings(
                remote=remote,
                sources=sources or [],
                today=date.fromisoformat(briefing_date),
                today_counts=raw.source_counts,
                today_errors=[error.model_dump() for error in raw.errors],
                today_input=totals.input if totals else 0,
                budget_usd=budget_usd,
                now=moment,
            )
        except Exception as problem:  # noqa: BLE001
            # 가드 자체의 실패도 조용히 삼키지는 않는다 — 경고로 알린다.
            lines = [f"가드 실행 실패(브리핑은 나갔다): {type(problem).__name__}: {problem}"]
        for line in lines:
            alert(line)

    # 센더는 서로 독립이다. 카톡이 실패해도 콘솔·기록은 가야 한다.
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
            # ConsoleSender는 항상 성공하므로 카톡이 실패해도 실행은 'sent'로
            # 끝난다. runs.errors에만 남기면 아무도 모른다 — 카톡이 안 갔을 때
            # 알리는 것이 슬랙의 존재 이유다.
            alert(f"전송 실패: {sender.name} — {type(error).__name__}: {error}")

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
            alert(
                f"페이지 저장 실패 — 오늘 브리핑이 카톡에는 갔지만 페이지에 없다: "
                f"{type(error).__name__}: {error}"
            )

    # 0건이어도 반드시 남긴다. 남기지 않으면 다음 윈도우가 계속 늘어나
    # 같은 항목을 반복 평가하게 된다.
    record("sent", moment, failures)


def read_budget(raw: str | None, warn: Warn) -> float | None:
    """MONTHLY_BUDGET_USD를 읽는다. 없으면 None(예산 경고만 생략).

    숫자가 아니면 None으로 두되 **알린다.** 오타("$30")로 예산 경고가 조용히
    꺼지면, 꺼졌다는 사실을 아무도 모른다.
    """
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        warn(f"MONTHLY_BUDGET_USD가 숫자가 아니다({raw!r}) — 예산 경고가 꺼져 있다. 예: 30")
        return None


def guard_warnings(
    *,
    remote: RemoteStore,
    sources: list[Source],
    today: date,
    today_counts: dict[str, int],
    today_input: int,
    budget_usd: float | None,
    now: datetime,
    seed: dict[str, date] | None = None,
    today_errors: list[dict] | None = None,
) -> list[str]:
    """가드(새 소스 실패·침묵·토큰 만료·크레딧)를 돌려 사람이 읽을 줄로 만든다.

    가치 순서는 소스 침묵 > 토큰 만료 > 크레딧이다(스펙 8.4).
    """
    lines: list[str] = []
    runs = remote.recent_runs(days=GUARD_LOOKBACK_DAYS)

    # --- 새로 생긴 소스 실패 ---
    # 침묵 가드보다 먼저 둔다. 막힌 소스를 30일 뒤가 아니라 그날 안다.
    kind_ko = {"config": "설정", "moved": "주소 이전"}
    for failure in new_source_failures(today_errors or [], runs, today=today):
        lines.append(
            f"새 소스 실패: {failure['source']} ({kind_ko[failure['kind']]}) — "
            f"{failure['message']}. 직전 실행에는 없었다. 계속돼도 다시 알리지 않는다"
        )

    # --- 소스 침묵 ---
    # **오늘 수집분을 더한다.** 가드는 오늘 실행 기록을 남기기 전에 돈다.
    # 빼면 30일 조용하던 소스가 오늘 글을 썼는데도 오늘 아침 "30일째"가 뜬다.
    #
    # **seed를 반드시 쓴다.** 빠뜨리면 runs가 시작되기 전부터 조용하던 소스를
    # 영원히 못 잡는다(Task 8 — 2026-11-17 하이퍼커넥트 209일).
    with_today = runs + [{"briefing_date": today.isoformat(), "source_counts": today_counts}]
    for name, gap, limit in silent_sources(
        sources, with_today, today=today,
        seed=load_seed_last_seen() if seed is None else seed,
    ):
        lines.append(f"소스 침묵: {name} — {gap}일째 (기준 {limit}일)")

    # --- 카카오 토큰 만료 ---
    found = remote.kakao_refresh_token()
    if found is not None:
        left = token_expiring(found[1], now=now)
        if left is not None:
            when = f"{left}일 남음" if left >= 0 else f"{-left}일 지남"
            lines.append(
                f"카카오 토큰 만료 {when} — "
                "`.venv/bin/python scripts/kakao_auth.py`로 재발급한다"
            )

    # --- 크레딧 ---
    # 그 달은 KST 기준이다 — briefing_date가 KST 날짜다.
    if budget_usd is not None:
        month = today.isoformat()[:7]
        spent = month_cost_usd(
            [r for r in runs if r["briefing_date"][:7] == month], model=MODEL
        )
        # None은 "모른다"다(Task 11). 모르는데 예산을 넘었다고도, 안 넘었다고도
        # 말하지 않는다.
        if spent is not None and spent >= budget_usd * BUDGET_WARN_RATIO:
            lines.append(
                f"크레딧: 이번 달 ${spent:.2f} / 예산 ${budget_usd:g} "
                f"({spent / budget_usd:.0%}, 정가 기준)"
            )

    if token_spike(runs, today_input=today_input):
        lines.append(
            f"입력 토큰 급증: 오늘 {today_input:,} — 평소(중앙값)의 {SPIKE_FACTOR}배 초과"
        )

    return lines


def build_kakao_sender(
    *,
    remote: RemoteStore,
    client_id: str,
    client_secret: str,
    page_url: str,
    now: datetime,
    warn: Warn,
    exchange: Callable[..., KakaoTokens] | None = access_token,
) -> KakaoSender | None:
    """오늘 쓸 카톡 센더를 만든다. 못 만들면 None을 돌려주고 **알린다.**

    계획서 원안은 토큰이 없으면 카톡을 조용히 빼고, 갱신이 실패하면 예외로
    실행 전체를 멈췄다. 앞은 아무도 모르고, 뒤는 브리핑 기록도 슬랙 경고도
    없이 끝난다. **카톡이 죽은 순간이 슬랙이 있는 이유다.**
    """
    found = remote.kakao_refresh_token()
    if found is None:
        warn("카카오 토큰이 없다 — 카톡 없이 보냈다. "
             "`.venv/bin/python scripts/kakao_auth.py`로 인증한다")
        return None

    try:
        tokens = exchange(
            refresh_token=found[0], client_id=client_id, client_secret=client_secret
        )
    except (Permanent, Transient) as error:
        warn(f"카카오 토큰 갱신 실패 — 카톡 없이 보냈다: {error}. "
             "계속되면 `.venv/bin/python scripts/kakao_auth.py`로 재발급한다")
        return None

    # 회전된 토큰이 왔을 때만 저장한다 — 한 달에 한 번쯤이다.
    # 초 → 시각 변환은 rotated_expiry 한 곳에서만 한다(Task 10).
    if should_store(tokens):
        try:
            remote.save_kakao_refresh_token(
                tokens.refresh_token, rotated_expiry(tokens, now=now)
            )
        except Exception as error:  # noqa: BLE001 — 오늘 발송은 할 수 있다
            # access_token은 받았으니 오늘은 보낸다. 새 refresh_token을 잃었으므로
            # 사람이 알아야 한다 — 내버려 두면 한 달 뒤 조용히 끊긴다.
            warn(f"회전된 카카오 토큰 저장 실패 — 오늘은 보냈지만 재인증이 필요할 수 있다: "
                 f"{type(error).__name__}: {error}")

    return KakaoSender(access_token=tokens.access_token, page_url=page_url)


def main() -> None:
    parser = argparse.ArgumentParser(description="브리핑 전송")
    parser.add_argument("--force", action="store_true",
                        help="이미 전송한 윈도우를 다시 보낸다")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    today = now.astimezone(KST).date().isoformat()
    store = LocalStore(date=today)
    remote = SupabaseStore(require("SUPABASE_URL"), require("SUPABASE_SECRET_KEY"))

    # 경고는 모았다가 끝에 슬랙으로 한 번에 보낸다. 슬랙 웹훅은 **필수**다 —
    # 없으면 경고가 실행 로그에만 남고, 로그는 아무도 매일 읽지 않는다.
    webhook = require("SLACK_WEBHOOK_URL")
    collected: list[str] = []

    senders: list[Sender] = [ConsoleSender()]
    kakao = build_kakao_sender(
        remote=remote,
        client_id=require("KAKAO_REST_API_KEY"),
        client_secret=require("KAKAO_CLIENT_SECRET"),
        page_url=require("PAGE_URL"),
        now=now,
        warn=collected.append,
    )
    if kakao is not None:
        senders.append(kakao)

    try:
        notify(
            briefing=store.read("briefing", Briefing),
            ranked=store.read("ranked", RankedBundle),
            raw=store.read("raw", RawBundle),
            remote=remote,
            briefing_date=today,
            senders=senders,
            force=args.force,
            now=now,
            warn=collected.append,
            sources=load_sources(),
            budget_usd=read_budget(optional("MONTHLY_BUDGET_USD"), collected.append),
        )
    finally:
        # notify가 실패해도(모든 센더 실패 등) 그때까지 모은 경고는 보낸다.
        warned = send_warnings(collected, webhook_url=webhook)

    print(f"전송 완료 ({today}) · 경고 {len(collected)}건")
    if not warned:
        sys.exit("슬랙 경고 전송에 실패했다 — 위 로그에 경고 전문이 있다")


if __name__ == "__main__":
    main()
