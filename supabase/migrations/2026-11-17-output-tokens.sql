-- 크레딧 가드가 비용을 계산하려면 출력 토큰도 필요하다 (계획 3).
--
-- 출력이 입력보다 5배 비싸다 — opus-5-5 기준 입력 $4 / 출력 $20 per MTok.
-- 입력만 세면 비용을 크게 낮잡는다.
--
-- **nullable이다.** 배선 전 실행에는 값이 없고, 그건 "0"이 아니라
-- "모른다"다. 0으로 채우면 가드가 "안 썼다"로 읽어 거짓 안심을 한다.
alter table public.runs add column if not exists output_tokens int;

-- **anon·authenticated에 권한을 주지 않는다.**
--
-- runs는 컬럼 단위 grant이고 input_tokens가 의도적으로 빠져 있다
-- (2026-11-17-page-direct-read.sql). 컬럼을 더하기만 하고 grant 목록을
-- 손대지 않으므로 자동으로 막히지만, 그 "자동"에 기대지 않고
-- scripts/verify_anon_access.sh가 실측으로 확인한다.
