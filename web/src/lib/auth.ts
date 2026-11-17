import { useEffect, useState } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from './supabase'

/**
 * 현재 세션. 로그인하지 않았으면 null이고 **그게 정상이다** —
 * 읽기는 익명 공개이고 좋아요·메모를 누를 때만 로그인한다.
 */
export function useSession(): { session: Session | null; loading: boolean } {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // 컴포넌트가 사라진 뒤에 setState가 불리는 것을 막는다.
    let alive = true

    // 첫 로드: 저장된 세션을 읽는다(persistSession).
    void supabase.auth.getSession().then(({ data }) => {
      if (!alive) return
      setSession(data.session)
      setLoading(false)
    })

    // 로그인·로그아웃·토큰 자동 갱신을 구독한다.
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      if (!alive) return
      setSession(next)
      setLoading(false)
    })

    return () => {
      alive = false
      data.subscription.unsubscribe()
    }
  }, [])

  return { session, loading }
}

export async function signIn(email: string, password: string): Promise<void> {
  const { error } = await supabase.auth.signInWithPassword({ email, password })
  // Supabase의 'Invalid login credentials'를 그대로 보여준다 — 이메일과
  // 비밀번호 중 어느 쪽이 틀렸는지 알려주지 않는 것이 맞다.
  if (error) throw new Error(error.message)
}

export async function signOut(): Promise<void> {
  await supabase.auth.signOut()
}
