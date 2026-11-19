-- 요약 보강(2026-11-19): 요점(bullets) 대신 원문을 간추린 2~3문단 요약.
-- 설계: design/superpowers/specs/2026-11-19-summary-overview-design.md
--
-- nullable이다. 그 전 글에는 없다 — 페이지는 overview가 없으면 요점을 그린다.
-- 새 요약의 bullets는 빈 목록이다(컬럼은 NOT NULL default '[]' 그대로).
alter table public.articles add column if not exists overview text;

-- 페이지가 읽는다. articles는 **컬럼 단위** grant라 새 컬럼이 자동으로 열리지
-- 않는다(position 때와 같다).
grant select (overview) on public.articles to anon, authenticated;
