"""저장소.

- LocalStore:  단계 간 중간 산출물 (날짜별 JSON 파일)
- RemoteStore: 실행 이력·발행 이력·본문 (Supabase)

파이프라인 단계들이 DB를 직접 알지 않도록 RemoteStore를 프로토콜로 둔다.
테스트는 가짜 구현을 넘기므로 실제 연결이 일어나지 않는다.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

# TypeVar는 "어떤 타입이 들어와도 같은 타입으로 나간다"를 타입 검사기에
# 알려준다. read("raw", RawBundle)의 반환형이 RawBundle로 추론된다.
TModel = TypeVar("TModel", bound=BaseModel)

DEFAULT_ROOT = Path("data")


class LocalStore:
    """날짜별 디렉터리에 단계 산출물을 JSON으로 읽고 쓴다."""

    def __init__(self, *, date: str, root: Path | None = None) -> None:
        self._dir = (root or DEFAULT_ROOT) / date

    def write(self, name: str, model: BaseModel) -> Path:
        # parents=True: 중간 디렉터리까지 만든다
        # exist_ok=True: 이미 있어도 에러 내지 않는다
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{name}.json"

        # ensure_ascii=False여야 한글이 그대로 저장된다. 기본값(True)이면
        # "제목"처럼 바뀌어 파일을 눈으로 디버깅할 수 없다.
        path.write_text(
            json.dumps(model.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def read(self, name: str, model_type: type[TModel]) -> TModel:
        path = self._dir / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"{path}가 없다. '{name}'을 만드는 앞 단계를 먼저 실행한다."
            )
        return model_type.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def exists(self, name: str) -> bool:
        return (self._dir / f"{name}.json").exists()


# ---------------------------------------------------------------
# 원격 저장소 (Supabase)
# ---------------------------------------------------------------


@runtime_checkable
class RemoteStore(Protocol):
    """파이프라인이 기대하는 영속 저장소의 모양.

    Protocol이므로 상속이 필요 없다. 같은 메서드를 가진 아무 클래스나
    이 자리에 들어갈 수 있다 — 테스트의 가짜 구현이 그렇다.
    """

    def last_sent_at(self) -> datetime | None:
        """마지막 발송 시각. 윈도우 계산의 기준점."""
        ...

    def known_urls(self, urls: list[str]) -> set[str]:
        """주어진 URL 중 이미 발행한 것들."""
        ...

    def recent_headlines(self, days: int) -> list[str]:
        """최근 N일간 발행한 헤드라인. 같은 사건 중복 판정에 쓴다."""
        ...

    def record_run(
        self,
        *,
        # 0건인 날은 articles 행이 없다. 이 컬럼이 그 날짜의 유일한 기록이다.
        briefing_date: str,
        window_start: datetime,
        window_end: datetime,
        status: str,                 # "sent" | "failed"
        sent_at: datetime | None,    # failed면 None
        collected_count: int,
        considered_count: int,
        max_score: int | None,
        published_count: int,
        source_counts: dict[str, int],
        input_tokens: int | None,
        output_tokens: int | None,
        errors: list[dict],
    ) -> None:
        """실행 이력을 남긴다. 0건이어도, 전송에 실패해도 반드시 호출한다."""
        ...

    def save_articles(self, *, briefing_date: str, summaries: list) -> None:
        """발행 글과 본문을 저장한다. 본문은 별도 테이블로 들어간다."""
        ...

    # --- 가드가 읽는 것 (계획 3 Task 12) ---

    def recent_runs(self, days: int) -> list[dict]:
        """최근 실행 이력(briefing_date, status, source_counts, 토큰, errors).

        가드가 읽는다 — 소스 침묵은 source_counts를, 크레딧은 토큰을 본다.
        status='sent'만이 아니라 **전부** 돌려준다: 전송이 실패한 날에도
        수집은 했으므로 침묵 판정에 들어가야 한다(스펙 8.4).

        순서는 보장하지 않는다 — 가드가 순서에 기대지 않는다(Task 8).
        """
        ...

    def kakao_refresh_token(self) -> tuple[str, datetime] | None:
        """(refresh_token, 만료 시각). 최초 인증 전이면 None."""
        ...

    def save_kakao_refresh_token(self, token: str, expires_at: datetime) -> None:
        """회전된 토큰을 저장한다. 한 달에 한 번쯤 불린다."""
        ...


def article_rows(*, briefing_date: str, summaries: list) -> list[dict]:
    """articles에 넣을 행을 만든다. **순번(position)을 1부터 매긴다.**

    카톡이 summaries 순서로 "1. 2. 3."을 매긴다. 페이지와 아카이브가 같은
    번호를 보여 주려면 그 순서를 저장해야 한다 — 점수로 다시 정렬하면 동점
    사이가 어긋난다(2026-11-12: 100점 3건, 98점 3건).

    summaries는 summarize가 이미 점수순으로 정렬하고 상한으로 자른 것이다.
    여기서 다시 정렬하지 않는다 — 순서의 주인은 summarize다.

    SupabaseStore 밖에 두는 이유: 이 저장소는 DB 호출을 모킹하지 않는다
    (모킹은 모킹만 검증한다). 행을 만드는 부분만 떼면 순수 함수로 확인된다.
    """
    rows = []
    for position, summary in enumerate(summaries, start=1):
        raw = summary.article.ranked.item
        rows.append({
            "briefing_date": briefing_date,
            "url": raw.url,
            "source": raw.source,
            "published_at": raw.published,
            "headline": summary.headline,
            # 2026-11-19부터 본문 요약이 요점을 대신한다. 새 요약의 bullets는 [].
            "overview": summary.overview,
            "bullets": summary.bullets,
            "why_it_matters": summary.why_it_matters,
            "topic": summary.article.ranked.topic,
            "score": summary.article.ranked.score,
            "reason": summary.article.ranked.reason,
            "position": position,
        })
    return rows


class SupabaseStore:
    """RemoteStore의 Supabase 구현."""

    def __init__(self, url: str, secret_key: str) -> None:
        # 지연 import: supabase 패키지를 쓰지 않는 테스트에서 불필요한
        # 의존성 로딩을 피한다.
        from supabase import create_client

        self._db = create_client(url, secret_key)

    def last_sent_at(self) -> datetime | None:
        rows = (
            self._db.table("runs")
            .select("sent_at")
            # 전송에 성공한 실행만 본다. 실패한 실행까지 세면 원인을 고친 뒤
            # 재실행이 "이미 보냄"으로 막힌다.
            .eq("status", "sent")
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            return None
        # Postgres는 "2026-11-10T22:20:00+00:00" 형태로 돌려준다.
        return datetime.fromisoformat(rows[0]["sent_at"])

    def known_urls(self, urls: list[str]) -> set[str]:
        if not urls:
            return set()
        rows = (
            self._db.table("articles")
            .select("url")
            .in_("url", urls)
            .execute()
            .data
        )
        return {row["url"] for row in rows}

    def recent_headlines(self, days: int) -> list[str]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        rows = (
            self._db.table("articles")
            .select("headline")
            .gte("briefing_date", since)
            .order("briefing_date", desc=True)
            .execute()
            .data
        )
        return [row["headline"] for row in rows]

    def record_run(
        self,
        *,
        # 0건인 날은 articles 행이 없다. 이 컬럼이 그 날짜의 유일한 기록이다.
        briefing_date: str,
        window_start: datetime,
        window_end: datetime,
        status: str,
        sent_at: datetime | None,
        collected_count: int,
        considered_count: int,
        max_score: int | None,
        published_count: int,
        source_counts: dict[str, int],
        input_tokens: int | None,
        output_tokens: int | None,
        errors: list[dict],
    ) -> None:
        self._db.table("runs").insert({
            "briefing_date": briefing_date,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "status": status,
            "sent_at": sent_at.isoformat() if sent_at is not None else None,
            "collected_count": collected_count,
            "considered_count": considered_count,
            "max_score": max_score,
            "published_count": published_count,
            "source_counts": source_counts,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "errors": errors,
        }).execute()

    def save_articles(self, *, briefing_date: str, summaries: list) -> None:
        for summary, row in zip(
            summaries, article_rows(briefing_date=briefing_date, summaries=summaries)
        ):
            # upsert + on_conflict: 같은 URL이 다시 와도 에러 대신 갱신한다.
            # 순번도 갱신된다 — 재실행이 카톡을 새 순서로 다시 보내므로 맞다.
            rows = (
                self._db.table("articles")
                .upsert(row, on_conflict="url")
                .execute()
                .data
            )
            article_id = rows[0]["id"]

            self._db.table("article_bodies").upsert({
                "article_id": article_id,
                "body": summary.article.body,
                "body_source": summary.article.body_source,
                "fallback_reason": summary.article.fallback_reason,
            }, on_conflict="article_id").execute()

    def recent_runs(self, days: int) -> list[dict]:
        since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
        rows = (
            self._db.table("runs")
            .select("briefing_date, status, source_counts, input_tokens, output_tokens, errors")
            .gte("briefing_date", since)
            # PostgREST 기본 상한(1000행)에 조용히 걸리지 않게 명시한다.
            # 날짜당 한두 행이라 400일이면 넉넉하다.
            .limit(2000)
            .execute()
        )
        return rows.data or []

    def kakao_refresh_token(self) -> tuple[str, datetime] | None:
        rows = (
            self._db.table("kakao_auth")
            .select("refresh_token, refresh_token_expires_at")
            .eq("id", 1)
            .execute()
        )
        if not rows.data:
            return None
        row = rows.data[0]
        return row["refresh_token"], datetime.fromisoformat(row["refresh_token_expires_at"])

    def save_kakao_refresh_token(self, token: str, expires_at: datetime) -> None:
        # 컬럼은 refresh_token_expires_at(시각)이다. Task 10에서 발송 확인
        # 스크립트가 없는 컬럼(…_expires_in)에 쓰던 버그를 찾았다.
        # updated_at은 트리거가 없어 직접 넣는다.
        self._db.table("kakao_auth").upsert({
            "id": 1,
            "refresh_token": token,
            "refresh_token_expires_at": expires_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
