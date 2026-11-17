import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

// 빈 값으로 클라이언트를 만들면 첫 질의에서 "Failed to fetch"만 나와서
// 원인을 찾기 어렵다. 여기서 바로 멈추고 이유를 말한다.
if (!url || !key) {
  throw new Error(
    'VITE_SUPABASE_URL / VITE_SUPABASE_PUBLISHABLE_KEY가 비어 있다. ' +
      'web/.env.local을 확인한다 (web/.env.example 참고).',
  )
}

export const supabase = createClient(url, key, {
  auth: {
    // 기기당 로그인 1회. 세션을 localStorage에 두고 토큰을 자동 갱신한다.
    persistSession: true,
    autoRefreshToken: true,
    // URL 해시로 돌아오는 콜백을 자동으로 처리한다.
    detectSessionInUrl: true,
  },
})
