-- IT 브리핑 Phase 1 스키마
--
-- 공개/비공개 경계가 이 파일의 핵심이다:
--   articles        — 요약·링크. **컬럼 단위** 읽기 허용 (reason 제외)
--   article_bodies  — 기사 본문. 접근 전면 차단 (재배포가 되면 안 된다)
--   runs            — 실행 이력. **컬럼 단위** 읽기 (errors·input_tokens 제외)
--   reactions       — authenticated만. 자기 행만 읽기·삽입·삭제
--   clicks          — anon 삽입(user_id null) + authenticated 자기 행 삽입
--   notes           — authenticated만. 자기 행만 읽기·삽입 (추가 전용)
--   kakao_auth      — 토큰. anon 접근 차단 (계획 3)
--
-- 모든 식별자는 소문자. 시각은 timestamptz. 길이 제한 없는 text.

-- ---------------------------------------------------------------
-- 테이블
-- ---------------------------------------------------------------

-- 발행된 글의 요약과 메타. 공개 가능한 것만 담는다.
create table if not exists public.articles (
  -- bigint identity: 순차 증가라 인덱스 삽입이 뒤쪽에 몰려 효율적이다.
  -- 랜덤 uuid는 삽입이 인덱스 전체에 흩어져 불리하다.
  id             bigint generated always as identity primary key,
  briefing_date  date        not null,
  -- 정규화된 URL. unique가 중복 발행을 DB 차원에서 막고, 조회 인덱스도 겸한다.
  url            text        not null unique,
  source         text        not null,
  published_at   timestamptz not null,
  headline       text        not null,
  bullets        jsonb       not null default '[]'::jsonb,
  why_it_matters text        not null,
  topic          text        not null,
  score          int         not null,
  -- LLM의 판단 근거. "왜 이게 뽑혔나"를 나중에 조회한다.
  reason         text        not null,
  created_at     timestamptz not null default now(),

  constraint articles_score_range check (score between 0 and 100),
  -- 카톡 200자 제약에서 파생. 애플리케이션과 DB 양쪽에서 막는다.
  constraint articles_headline_len check (char_length(headline) <= 30)
);

-- 기사 본문. 별도 테이블로 분리해 anon에게 권한을 아예 주지 않는다.
-- Phase 3의 임베딩 컬럼도 여기에 추가한다.
create table if not exists public.article_bodies (
  article_id      bigint primary key references public.articles(id) on delete cascade,
  body            text not null,
  body_source     text not null,
  -- 폴백이 일어난 이유. 폴백이 없으면 NULL. 과거 기록에서
  -- "이 소스는 늘 403이 난다"를 확인할 수 있다.
  fallback_reason text,
  created_at      timestamptz not null default now(),

  constraint article_bodies_source_enum
    check (body_source in ('trafilatura', 'rss_excerpt'))
);

-- 실행 이력. 윈도우 계산·멱등성 판정·소스 침묵 감지가 모두 이걸 읽는다.
create table if not exists public.runs (
  id               bigint generated always as identity primary key,
  -- 0건인 날은 articles 행이 하나도 없다. 이 컬럼이 그 날짜의 유일한
  -- 기록이고, 페이지가 "조용한 날"과 "안 돈 날"을 구별하는 근거다.
  -- window_end를 KST로 변환해 추측할 수도 있지만, 브라우저 질의에
  -- 타임존 변환을 넣으면 인덱스를 못 타고 경계에서 조용히 틀린다.
  briefing_date    date        not null,
  window_start     timestamptz not null,
  window_end       timestamptz not null,
  -- 전송 성공 시각. status='failed'인 행에서는 NULL이다.
  sent_at          timestamptz,
  -- 전송이 실패한 실행도 남긴다. source_counts가 소스 침묵 경고의 유일한
  -- 입력이므로, 실패한 날이 빠지면 경고가 그만큼 늦어진다.
  status           text        not null,
  collected_count  int         not null default 0,   -- 중복 제거 후 수집 건수
  considered_count int         not null default 0,   -- 요약 후보로 올린 건수
  max_score        int,                              -- 수집 0건이면 NULL
  published_count  int         not null default 0,
  -- {"토스_기술블로그": 3, "전자신문_오피니언": 0} — 3회 연속 0건이면 경고
  source_counts    jsonb       not null default '{}'::jsonb,
  input_tokens     int,
  -- 출력이 5배 비싸다. 입력만 세면 비용을 크게 낮잡는다 (계획 3).
  output_tokens    int,
  errors           jsonb       not null default '[]'::jsonb,

  constraint runs_status_enum check (status in ('sent', 'failed')),
  -- 'sent'면 sent_at이 있어야 하고 'failed'면 없어야 한다. 애플리케이션
  -- 버그로 둘이 어긋나면 윈도우 계산이 조용히 틀어지므로 DB가 막는다.
  constraint runs_sent_at_matches_status check (
    (status = 'sent' and sent_at is not null)
    or (status = 'failed' and sent_at is null)
  )
);

-- 좋아요 (계획 2)
--
-- user_id가 지금부터 있는 이유: 페이지가 공개이고 인증이 없으므로 누구나
-- 좋아요를 누를 수 있다. 그런데 Phase 2는 "내 좋아요"를 선별 프롬프트에
-- 주입한다 — 낯선 사람의 클릭이 내 큐레이션 기준을 바꾼다.
-- 인증은 지금 켜지 않는다. 컬럼만 두면 전부 NULL("아마 나")이 되고,
-- 나중에 Auth를 켜는 순간 where user_id = auth.uid()로 바로 걸러진다.
-- 처음부터 두면 마이그레이션이 없다. 이것이 "지금 하면 싸고 나중에 하면
-- 비싼" 유일한 항목이다.
create table if not exists public.reactions (
  id         bigint generated always as identity primary key,
  article_id bigint not null references public.articles(id) on delete cascade,
  user_id    uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

-- 클릭 (계획 2)
create table if not exists public.clicks (
  id         bigint generated always as identity primary key,
  article_id bigint not null references public.articles(id) on delete cascade,
  user_id    uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

-- 짧은 메모와 태그 (계획 2)
create table if not exists public.notes (
  id         bigint generated always as identity primary key,
  article_id bigint not null references public.articles(id) on delete cascade,
  user_id    uuid references auth.users(id) on delete set null,
  text       text   not null,
  tags       jsonb  not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

-- 카카오 리프레시 토큰 (계획 3). 단일 행만 쓴다.
create table if not exists public.kakao_auth (
  id                        int primary key default 1,
  refresh_token             text        not null,
  refresh_token_expires_at  timestamptz not null,
  updated_at                timestamptz not null default now(),

  constraint kakao_auth_single_row check (id = 1)
);

-- ---------------------------------------------------------------
-- 인덱스
-- ---------------------------------------------------------------

-- 날짜별 페이지 조회
create index if not exists articles_briefing_date_idx
  on public.articles (briefing_date desc);

-- 마지막 발송 시각 조회 (윈도우 계산이 매 실행마다 쓴다).
-- 부분 인덱스다 — 그 조회가 항상 status='sent'를 거치므로 실패한 행을
-- 인덱스에서 빼면 더 작고 빠르다.
create index if not exists runs_sent_at_idx
  on public.runs (sent_at desc) where status = 'sent';

-- 외래 키 컬럼에는 인덱스를 만든다. 없으면 부모 행 삭제 시 자식 테이블을
-- 전체 스캔하고, article_id로 집계할 때도 느리다.
create index if not exists reactions_article_id_idx on public.reactions (article_id);
create index if not exists clicks_article_id_idx    on public.clicks (article_id);
create index if not exists notes_article_id_idx     on public.notes (article_id);

-- user_id도 외래 키다. Phase 2가 "내 것만" 거르는 질의를 쓰므로 인덱스를
-- 둔다. 지금은 전부 NULL이어서 인덱스가 거의 비어 있다 — 비용이 없다.
create index if not exists runs_briefing_date_idx on public.runs (briefing_date desc);
create index if not exists reactions_user_id_idx on public.reactions (user_id);
create index if not exists clicks_user_id_idx    on public.clicks (user_id);
create index if not exists notes_user_id_idx     on public.notes (user_id);

-- ---------------------------------------------------------------
-- RLS 활성화
-- ---------------------------------------------------------------
-- RLS를 켜고 정책을 만들지 않으면 그 역할은 전부 거부된다.
-- service_role은 RLS를 우회하므로 파이프라인은 영향받지 않는다.

alter table public.articles       enable row level security;
alter table public.article_bodies enable row level security;
alter table public.runs           enable row level security;
alter table public.reactions      enable row level security;
alter table public.clicks         enable row level security;
alter table public.notes          enable row level security;
alter table public.kakao_auth     enable row level security;

-- ---------------------------------------------------------------
-- 권한: 먼저 전부 회수하고, 필요한 것만 다시 부여
-- ---------------------------------------------------------------
-- Supabase는 public 스키마의 새 테이블에 anon/authenticated 권한을
-- 기본 부여한다. 따라서 명시적으로 회수해야 한다.
-- 테이블 권한과 RLS 정책은 AND 조건이다 — 둘 다 통과해야 접근된다.

revoke all on public.articles       from anon, authenticated;
revoke all on public.article_bodies from anon, authenticated;
revoke all on public.runs           from anon, authenticated;
revoke all on public.reactions      from anon, authenticated;
revoke all on public.clicks         from anon, authenticated;
revoke all on public.notes          from anon, authenticated;
revoke all on public.kakao_auth     from anon, authenticated;

-- 읽기는 익명 공개, 쓰기는 로그인한 사용자만 (계획 2).
-- 정책에 drop if exists를 붙여 이 파일을 다시 돌릴 수 있게 둔다 —
-- create policy에는 IF NOT EXISTS가 없다.

-- articles: 공개 페이지가 읽는다. **컬럼 단위**로 준다 — reason(LLM의
-- 판단 근거)은 페이지에 쓰지 않으므로 내보내지 않는다. 테이블 통째로
-- 주면 ?select=reason으로 읽힌다.
grant select (id, briefing_date, url, source, published_at,
              headline, bullets, why_it_matters, topic, score)
  on public.articles to anon, authenticated;

drop policy if exists articles_public_read on public.articles;
create policy articles_public_read on public.articles
  for select to anon using (true);

-- authenticated는 anon과 **다른 역할**이다. 따로 주지 않으면 로그인하는
-- 순간 화면이 빈다.
drop policy if exists articles_auth_read on public.articles;
create policy articles_auth_read on public.articles
  for select to authenticated using (true);

-- runs: 0건인 날의 수치를 페이지가 읽는다 (요구사항 D8).
-- errors(내부 오류 메시지)·input_tokens·window_*·id는 주지 않는다.
grant select (briefing_date, status, collected_count, considered_count,
              max_score, published_count, source_counts)
  on public.runs to anon, authenticated;

drop policy if exists runs_public_read on public.runs;
create policy runs_public_read on public.runs
  for select to anon using (status = 'sent');

drop policy if exists runs_auth_read on public.runs;
create policy runs_auth_read on public.runs
  for select to authenticated using (status = 'sent');

-- briefing_index: 아카이브가 **날짜당 한 행**만 받는다. 기사 전체를 받아
-- 브라우저에서 집계하면 PostgREST의 기본 상한(1000행)에 조용히 걸린다.
--
-- security_invoker = true: 뷰가 호출자의 권한으로 돈다. 그래서 위의 컬럼
-- grant와 RLS가 그대로 적용된다. 기본값(definer)은 RLS를 우회한다.
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

-- clicks: 로그인 전에도 눌린다. anon은 user_id가 빈 행만, 로그인
-- 사용자는 자기 id로 넣는다.
-- identity 컬럼은 시퀀스 권한을 따로 주지 않아도 삽입된다(serial과 다름).
-- with check (user_id is null): anon이 남의 user_id를 적어 넣는 위장
-- 경로를 막는다.
grant insert on public.clicks to anon, authenticated;

drop policy if exists clicks_public_insert on public.clicks;
create policy clicks_public_insert on public.clicks
  for insert to anon with check (user_id is null);

drop policy if exists clicks_own_insert on public.clicks;
create policy clicks_own_insert on public.clicks
  for insert to authenticated with check ((select auth.uid()) = user_id);

-- reactions: **로그인한 사용자만.** anon에 주지 않는다 — ERD 3.2.1이
-- 걱정한 "낯선 사람의 클릭이 내 기준을 바꾼다"를 닫는다.
--
-- (select auth.uid())로 감싸는 이유: 행마다 재평가되지 않고 한 번만
-- 계산된다. auth.uid() = user_id로 바로 쓰면 행 수만큼 호출된다.
grant select, insert, delete on public.reactions to authenticated;

drop policy if exists reactions_own_read on public.reactions;
create policy reactions_own_read on public.reactions
  for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists reactions_own_insert on public.reactions;
create policy reactions_own_insert on public.reactions
  for insert to authenticated with check ((select auth.uid()) = user_id);

-- DELETE는 먼저 SELECT로 행을 찾는다. 위의 read 정책이 그것을 받친다 —
-- 없으면 delete가 조용히 0행을 지운다.
drop policy if exists reactions_own_delete on public.reactions;
create policy reactions_own_delete on public.reactions
  for delete to authenticated using ((select auth.uid()) = user_id);

-- notes: 로그인한 사용자만, **추가 전용**. UPDATE·DELETE를 주지 않으므로
-- 수정 이력이 남고, 화면은 가장 최근 행을 읽어 제자리 수정처럼 보인다.
grant select, insert on public.notes to authenticated;

drop policy if exists notes_own_read on public.notes;
create policy notes_own_read on public.notes
  for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists notes_own_insert on public.notes;
create policy notes_own_insert on public.notes
  for insert to authenticated with check ((select auth.uid()) = user_id);

-- article_bodies / kakao_auth: anon·authenticated 정책을 만들지 않는다.
-- 권한도 회수했고 정책도 없으므로 이중으로 차단된다 (요구사항 D2).

-- ---------------------------------------------------------------
-- 파이프라인(service_role) 권한
-- ---------------------------------------------------------------
-- 파이프라인은 secret 키로 접속하고, 그것은 service_role 역할이 된다.
-- service_role은 BYPASSRLS지만 **테이블 grant는 별개다** — RLS를 우회하는
-- 것과 테이블에 닿을 수 있는 것은 다른 층이다.
--
-- Supabase가 기본으로 주지만, Data API 설정의 "Automatically expose new
-- tables"를 끈 프로젝트에서 service_role이 어떻게 되는지가 문서로 명확하지
-- 않다(그 설정은 "Data API가 쓰는 권한을 회수한다"고만 말한다).
-- 명시해두면 중복이어도 무해하고, 빠졌을 때 겪는 42501 에러를 피한다.
grant select, insert, update, delete on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;
