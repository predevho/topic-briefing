-- 기사의 **순번**을 저장한다. 카톡의 "3."과 페이지의 "3."이 같은 글이어야 한다.
--
-- 왜 계산하지 않고 저장하나: 같은 점수가 흔하다. 2026-11-12에 100점이 3건,
-- 98점이 3건이었다. 카톡은 파이프라인의 순서(summaries)로 번호를 매기는데,
-- 페이지는 `order by score desc`로만 읽었고 아카이브 뷰도 `order by score desc`
-- 로 대표 헤드라인을 골랐다. **동점 사이의 순서를 Postgres는 보장하지 않는다.**
-- 번호를 붙이는 순간 그 어긋남이 "카톡 3번 ≠ 페이지 3번"으로 드러난다.
--
-- nullable이다. 값이 없으면 "순번을 모른다"이고 페이지는 점수순으로 물러선다.
alter table public.articles add column if not exists position smallint;

-- 기존 행을 채운다. 지금까지 save_articles는 summaries 순서대로 한 건씩
-- upsert했으므로 **id 순서가 곧 파이프라인 순서다.** 2026-11-17 확인: 11/12의
-- 7건을 (score desc, id asc)로 읽으면 실제 카톡 순서와 일치한다.
update public.articles a
set position = r.rn
from (
  select id,
         row_number() over (partition by briefing_date
                            order by score desc, id asc) as rn
  from public.articles
) r
where a.id = r.id
  and a.position is null;

-- 페이지가 읽는다. articles는 **컬럼 단위** grant라 새 컬럼이 자동으로
-- 열리지 않는다(output_tokens와 반대 방향 — 그쪽은 막혀 있어야 했다).
--
-- **뷰보다 먼저 연다.** briefing_index는 security_invoker라 호출자의 권한으로
-- 돈다. 뷰가 position으로 정렬하는데 anon에게 그 컬럼 권한이 없으면 아카이브
-- 질의 전체가 42501로 실패한다.
grant select (position) on public.articles to anon, authenticated;

-- 아카이브의 대표 헤드라인을 "1번"으로 맞춘다. 이전에는 최고점 중 아무거나였다.
-- create or replace는 기존 grant를 유지한다. 컬럼 이름·타입·순서가 같아야 한다.
create or replace view public.briefing_index
  with (security_invoker = true) as
select
  briefing_date,
  count(*)::int as count,
  (array_agg(headline order by position nulls last, score desc, id))[1] as lead
from public.articles
group by briefing_date;
