-- 관련 글 연결 (2026-11-23). 설계: design/superpowers/specs/2026-11-23-related-articles-design.md
--
-- 새 브리핑 글마다 더 이전 날짜의 비슷한 글(코사인 유사도 0.52 이상, 최대 3건)을
-- 찾아 article_links에 둔다. 페이지는 article_links만 읽는다.

-- pgvector. Supabase 관례대로 extensions 스키마에 둔다(public을 어지럽히지 않는다).
create extension if not exists vector with schema extensions;

-- 글 하나당 벡터 하나 (헤드라인 + 본문 요약 + 왜 중요한가, Voyage voyage-4, 1024차원).
-- **공개하지 않는다** — 페이지에 필요 없다. RLS를 켜고 anon·authenticated에 아무 권한도 주지 않는다.
-- model을 남기는 이유: 모델을 바꾸면 벡터끼리 비교가 안 된다. 섞이지 않게 거를 수 있어야 한다.
create table if not exists public.article_embeddings (
  article_id  bigint primary key references public.articles(id) on delete cascade,
  model       text not null,
  embedding   extensions.vector(1024) not null,
  created_at  timestamptz not null default now()
);
alter table public.article_embeddings enable row level security;
revoke all on public.article_embeddings from anon, authenticated;

-- 관련 글. id와 유사도뿐이라 공개해도 된다. 페이지가 FK로 관련 글의 날짜·헤드라인을 읽는다.
create table if not exists public.article_links (
  article_id  bigint not null references public.articles(id) on delete cascade,
  related_id  bigint not null references public.articles(id) on delete cascade,
  similarity  real   not null,
  primary key (article_id, related_id),
  constraint article_links_not_self check (article_id <> related_id)
);
alter table public.article_links enable row level security;
-- Supabase 기본 권한이 anon에게 insert·update·delete까지 준다. RLS가 막지만
-- 정책 하나 잘못 넣으면 바로 열리므로 권한 자체를 걷는다.
revoke insert, update, delete, truncate, references, trigger
  on public.article_links from anon, authenticated;
grant select on public.article_links to anon, authenticated;
drop policy if exists article_links_public_read on public.article_links;
create policy article_links_public_read on public.article_links
  for select to anon, authenticated using (true);

-- 그날 글의 관련 글을 다시 계산해 article_links에 쓴다. 쓴 행 수를 돌려준다.
--
-- - **더 이전 날짜** 글만 본다 — 같은 날 글끼리 묶지 않는다.
-- - 같은 모델로 만든 벡터끼리만 비교한다.
-- - 가까운 순 상위 p_limit건 중 유사도 p_threshold 이상만 남긴다.
-- - 다시 부르면 그 글들의 링크를 지우고 새로 쓴다 — 재실행이 결과를 바꿀 수 있다.
--
-- <=> 는 코사인 거리다. Voyage 벡터는 길이 1이라 1 - 거리 = 코사인 유사도.
create or replace function public.link_related(
  p_article_ids bigint[], p_threshold real, p_limit int
) returns integer
language plpgsql
security invoker
set search_path = public, extensions
as $$
declare
  written integer;
begin
  delete from public.article_links where article_id = any(p_article_ids);

  with targets as (
    select a.id, a.briefing_date, e.model, e.embedding
    from public.articles a
    join public.article_embeddings e on e.article_id = a.id
    where a.id = any(p_article_ids)
  ),
  ranked as (
    select t.id as article_id,
           c.id as related_id,
           1 - (ce.embedding <=> t.embedding) as similarity,
           row_number() over (partition by t.id order by ce.embedding <=> t.embedding) as rn
    from targets t
    join public.articles c on c.briefing_date < t.briefing_date
    join public.article_embeddings ce on ce.article_id = c.id and ce.model = t.model
  )
  insert into public.article_links (article_id, related_id, similarity)
  select article_id, related_id, similarity
  from ranked
  where rn <= p_limit and similarity >= p_threshold;

  get diagnostics written = row_count;
  return written;
end;
$$;

-- Postgres는 새 함수에 EXECUTE를 PUBLIC으로 준다. anon이 부르면 링크를 지우고 다시 쓸 수
-- 있게 된다(쓰기는 RLS에 막히지만 기대지 않는다). 파이프라인(service_role)만 부른다.
revoke execute on function public.link_related(bigint[], real, int) from public, anon, authenticated;
grant execute on function public.link_related(bigint[], real, int) to service_role;
