-- anon이 가진 권한을 눈으로 확인한다.
-- 기대: articles=SELECT / reactions,clicks=INSERT /
--       notes=SELECT,INSERT / article_bodies,runs,kakao_auth=행 없음
select table_name, privilege_type
from information_schema.role_table_grants
where grantee = 'anon'
  and table_schema = 'public'
order by table_name, privilege_type;

-- RLS가 모든 테이블에 켜져 있는지 확인한다. 기대: 전부 true
select relname, relrowsecurity
from pg_class
where relnamespace = 'public'::regnamespace
  and relkind = 'r'
order by relname;
