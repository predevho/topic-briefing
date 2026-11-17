-- 페이지가 Supabase를 직접 조회하도록 권한을 다시 그린다 (계획 2 Task 2).
--
-- 바뀌는 것 네 가지:
--   1) runs.briefing_date   — 0건인 날을 날짜로 찾을 키
--   2) 컬럼 단위 SELECT      — reason과 errors를 내보내지 않는다
--   3) briefing_index 뷰     — 아카이브가 날짜당 한 행만 받는다
--   4) 쓰기는 authenticated만 — anon의 reactions/notes 쓰기를 거둔다
--
-- **멱등하게 쓴다.** 여러 번 돌려도 같은 결과여야 한다. create policy에는
-- IF NOT EXISTS가 없으므로 전부 drop policy if exists를 앞에 둔다.

-- ---------------------------------------------------------------
-- 1) runs.briefing_date
-- ---------------------------------------------------------------

-- 0건인 날은 articles 행이 하나도 없다(summarize의 SCORE_THRESHOLD를 넘은
-- 글만 저장된다). 그래서 runs가 그 날짜의 유일한 기록인데 날짜 컬럼이
-- 없었다 — window_start/end와 sent_at만 있어서 KST 변환으로만 얻는다.
-- 브라우저 질의에 타임존 변환을 넣으면 인덱스를 못 타고 경계에서 틀린다.
alter table public.runs add column if not exists briefing_date date;

-- 기존 행을 채운다. sent_at이 없으면(status='failed') window_end를 쓴다.
-- KST로 변환하는 이유: 브리핑 날짜는 사람이 읽는 날짜다.
update public.runs
   set briefing_date = (coalesce(sent_at, window_end) at time zone 'Asia/Seoul')::date
 where briefing_date is null;

alter table public.runs alter column briefing_date set not null;

-- 아카이브와 최신 브리핑 조회가 최신순으로 읽는다.
create index if not exists runs_briefing_date_idx
  on public.runs (briefing_date desc);

-- ---------------------------------------------------------------
-- 2) 컬럼 단위 SELECT
-- ---------------------------------------------------------------

-- articles: reason(LLM 판단 근거)을 뺀다.
-- 지금까지 테이블 통째로 grant돼 있어서 ?select=reason으로 읽혔다 —
-- 화면에 안 그려도 API는 열려 있었다.
revoke select on public.articles from anon;
revoke select on public.articles from authenticated;

grant select (id, briefing_date, url, source, published_at,
              headline, bullets, why_it_matters, topic, score)
  on public.articles to anon;

-- authenticated는 anon과 **다른 역할**이다. 따로 주지 않으면 로그인하는
-- 순간 화면이 빈다.
grant select (id, briefing_date, url, source, published_at,
              headline, bullets, why_it_matters, topic, score)
  on public.articles to authenticated;

drop policy if exists articles_auth_read on public.articles;
create policy articles_auth_read on public.articles
  for select to authenticated using (true);

-- runs: 0건인 날의 수치만. errors(내부 오류 메시지)·input_tokens·
-- window_*·id는 주지 않는다.
grant select (briefing_date, status, collected_count, considered_count,
              max_score, published_count, source_counts)
  on public.runs to anon, authenticated;

drop policy if exists runs_public_read on public.runs;
create policy runs_public_read on public.runs
  for select to anon using (status = 'sent');

drop policy if exists runs_auth_read on public.runs;
create policy runs_auth_read on public.runs
  for select to authenticated using (status = 'sent');

-- ---------------------------------------------------------------
-- 3) briefing_index — 아카이브용, 날짜당 한 행
-- ---------------------------------------------------------------

-- 이게 없으면 아카이브가 기사 전체를 받아 브라우저에서 집계해야 하고,
-- PostgREST의 기본 상한(1000행)에 조용히 걸린다. 날짜당 한 행이면
-- 5년이 지나도 2천 행 아래다.
--
-- security_invoker = true: 뷰가 **호출자의 권한으로** 돈다. 그래서 위에서
-- 준 컬럼 grant와 RLS가 그대로 적용된다. 기본값(false, definer)은 RLS를
-- 우회하므로 쓰지 않는다.
create or replace view public.briefing_index
  with (security_invoker = true) as
select
  briefing_date,
  count(*)::int                                as count,
  -- 그 날짜의 최고 점수 헤드라인. 아카이브가 "<lead> 외 N건"으로 그린다.
  (array_agg(headline order by score desc))[1] as lead
from public.articles
group by briefing_date;

grant select on public.briefing_index to anon, authenticated;

-- ---------------------------------------------------------------
-- 4) 쓰기는 로그인한 사용자만
-- ---------------------------------------------------------------

-- reactions: anon INSERT를 거둔다. ERD 3.2.1이 걱정한 "낯선 사람의 클릭이
-- 내 기준을 바꾼다"가 여기서 닫힌다.
drop policy if exists reactions_public_insert on public.reactions;
revoke insert on public.reactions from anon;

grant select, insert, delete on public.reactions to authenticated;

-- (select auth.uid())로 감싸는 이유: 행마다 재평가되지 않고 한 번만
-- 계산된다. auth.uid() = user_id로 바로 쓰면 행 수만큼 호출된다.
drop policy if exists reactions_own_read on public.reactions;
create policy reactions_own_read on public.reactions
  for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists reactions_own_insert on public.reactions;
create policy reactions_own_insert on public.reactions
  for insert to authenticated with check ((select auth.uid()) = user_id);

-- DELETE는 먼저 SELECT로 행을 찾는다. 위의 read 정책이 그것을 받친다 —
-- read 정책이 없으면 delete가 조용히 0행을 지운다.
drop policy if exists reactions_own_delete on public.reactions;
create policy reactions_own_delete on public.reactions
  for delete to authenticated using ((select auth.uid()) = user_id);

-- notes: 추가 전용을 유지한다. UPDATE·DELETE를 주지 않으므로 수정 이력이
-- 남고, 화면에서는 가장 최근 행을 읽어 제자리 수정처럼 보인다.
drop policy if exists notes_public_read on public.notes;
drop policy if exists notes_public_insert on public.notes;
revoke select, insert on public.notes from anon;

grant select, insert on public.notes to authenticated;

drop policy if exists notes_own_read on public.notes;
create policy notes_own_read on public.notes
  for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists notes_own_insert on public.notes;
create policy notes_own_insert on public.notes
  for insert to authenticated with check ((select auth.uid()) = user_id);

-- clicks: 로그인 전에도 눌린다. anon INSERT(user_id is null)를 유지하고
-- 로그인 사용자도 자기 id로 넣게 한다.
grant insert on public.clicks to authenticated;

drop policy if exists clicks_own_insert on public.clicks;
create policy clicks_own_insert on public.clicks
  for insert to authenticated with check ((select auth.uid()) = user_id);
