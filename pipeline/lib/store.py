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
        errors: list[dict],
    ) -> None:
        """실행 이력을 남긴다. 0건이어도, 전송에 실패해도 반드시 호출한다."""
        ...

    def save_articles(self, *, briefing_date: str, summaries: list) -> None:
        """발행 글과 본문을 저장한다. 본문은 별도 테이블로 들어간다."""
        ...


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
        errors: list[dict],
    ) -> None:
        self._db.table("runs").insert({
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
            "errors": errors,
        }).execute()

    def save_articles(self, *, briefing_date: str, summaries: list) -> None:
        for summary in summaries:
            raw = summary.article.ranked.item
            # upsert + on_conflict: 같은 URL이 다시 와도 에러 대신 갱신한다.
            rows = (
                self._db.table("articles")
                .upsert({
                    "briefing_date": briefing_date,
                    "url": raw.url,
                    "source": raw.source,
                    "published_at": raw.published,
                    "headline": summary.headline,
                    "bullets": summary.bullets,
                    "why_it_matters": summary.why_it_matters,
                    "topic": summary.article.ranked.topic,
                    "score": summary.article.ranked.score,
                    "reason": summary.article.ranked.reason,
                }, on_conflict="url")
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
