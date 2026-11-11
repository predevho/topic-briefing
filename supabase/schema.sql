-- IT 브리핑 Phase 1 스키마
--
-- 공개/비공개 경계가 이 파일의 핵심이다:
--   articles        — 요약·링크. anon 읽기 허용 (공개 페이지가 읽는다)
--   article_bodies  — 기사 본문. anon 접근 전면 차단 (재배포가 되면 안 된다)
--   runs            — 실행 이력. anon 접근 차단
--   reactions/clicks — anon 삽입만 허용 (계획 2)
--   notes           — anon 읽기·삽입 허용 (내 메모, 내 페이지) (계획 2)
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

-- articles: 공개 페이지가 읽는다
grant select on public.articles to anon;
create policy articles_public_read on public.articles
  for select to anon using (true);

-- reactions/clicks: 삽입만. 조회는 service_role(= 나)만 한다.
-- identity 컬럼은 시퀀스 권한을 따로 주지 않아도 삽입된다(serial과 다름).
-- with check (user_id is null): anon이 삽입하는 행은 user_id가 반드시
-- 비어 있어야 한다. 이것이 없으면 인증을 켠 뒤에 anon 키로 남의 user_id를
-- 적어 넣을 수 있다 — 위장 경로를 처음부터 막는다. 인증된 사용자는
-- 그때 별도 정책(auth.uid() = user_id)으로 삽입한다.
grant insert on public.reactions to anon;
create policy reactions_public_insert on public.reactions
  for insert to anon with check (user_id is null);

grant insert on public.clicks to anon;
create policy clicks_public_insert on public.clicks
  for insert to anon with check (user_id is null);

-- notes: 내 메모를 내 페이지에서 쓰고 읽는다.
-- 다수 사용자로 가면 이 select 정책은 남의 메모까지 노출하므로
-- auth.uid() = user_id로 좁혀야 한다 (스펙 2.1 참조).
grant select, insert on public.notes to anon;
create policy notes_public_read on public.notes
  for select to anon using (true);
create policy notes_public_insert on public.notes
  for insert to anon with check (user_id is null);

-- article_bodies / runs / kakao_auth: anon 정책을 만들지 않는다.
-- 권한도 회수했고 정책도 없으므로 이중으로 차단된다.

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
