import { supabase } from './supabase'

/**
 * 내가 좋아요한 article_id 집합.
 *
 * **모듈 수준 캐시를 쓰는 이유.** 카드가 7장이면 각 LikeButton이 "내가
 * 눌렀나"를 따로 물어 질의가 7번 간다. React 컨텍스트로 묶으려면
 * App.tsx에 프로바이더를 넣어야 하는데, App.tsx는 Task 9에서 쓰고 더
 * 고치지 않는다. 모듈 수준 캐시가 프로바이더 없이 같은 일을 한다.
 *
 * RLS가 auth.uid() = user_id로 좁히므로 **내 행만** 온다.
 */
let cache: Promise<Set<number>> | null = null

// 집합이 바뀔 때 다시 그릴 컴포넌트들.
const listeners = new Set<() => void>()

function announce(): void {
  for (const notify of listeners) notify()
}

export function subscribe(notify: () => void): () => void {
  listeners.add(notify)
  return () => {
    listeners.delete(notify)
  }
}

/** 로그인·로그아웃 시 캐시를 버린다. 사용자가 바뀌면 집합도 달라진다. */
export function resetLikes(): void {
  cache = null
  announce()
}

export function loadLikes(): Promise<Set<number>> {
  if (cache) return cache
  cache = (async () => {
    const { data, error } = await supabase.from('reactions').select('article_id')
    // 로그인하지 않았으면 권한이 없어 오류가 난다. 그건 정상이므로
    // 빈 집합으로 둔다 — 하트가 전부 빈 상태로 그려진다.
    if (error) return new Set<number>()
    return new Set<number>((data ?? []).map((row) => row.article_id as number))
  })()
  return cache
}

/**
 * 좋아요를 뒤집는다. 돌려주는 값은 **뒤집은 뒤의 상태**다.
 * 로그인하지 않았으면 호출하지 않는다 — 버튼이 먼저 로그인을 띄운다.
 */
export async function toggleLike(
  articleId: number,
  userId: string,
): Promise<boolean> {
  const liked = await loadLikes()

  if (liked.has(articleId)) {
    const { error } = await supabase
      .from('reactions')
      .delete()
      .eq('article_id', articleId)
    if (error) throw new Error(`좋아요를 지우지 못했다: ${error.message}`)
    liked.delete(articleId)
    announce()
    return false
  }

  // user_id를 **명시해서** 넣는다. RLS의 with check가
  // auth.uid() = user_id를 요구하므로 빼면 거부된다.
  const { error } = await supabase
    .from('reactions')
    .insert({ article_id: articleId, user_id: userId })
  if (error) throw new Error(`좋아요를 넣지 못했다: ${error.message}`)
  liked.add(articleId)
  announce()
  return true
}

/**
 * 원문 링크 클릭을 기록한다. 실패해도 조용히 넘긴다 — 클릭 신호 하나보다
 * 링크가 열리는 것이 중요하다.
 *
 * **인자는 articleId 하나다.** 세션은 안에서 읽는다 — 호출하는 쪽(Card)이
 * 로그인 상태를 알 필요가 없고, 로그인 전에도 클릭은 기록되어야 한다
 * (anon의 clicks INSERT 정책이 user_id null을 받는다).
 *
 * sendBeacon을 쓰지 않는 이유: 헤더를 설정할 수 없고 Supabase REST는
 * apikey/Authorization을 요구한다.
 */
export function recordClick(articleId: number): void {
  void (async () => {
    const { data } = await supabase.auth.getSession()
    await supabase.from('clicks').insert({
      article_id: articleId,
      // 로그인했으면 내 id, 아니면 null. RLS가 두 경로를 각각 허용한다.
      user_id: data.session?.user?.id ?? null,
    })
  })().catch(() => undefined)
}

// 로그인·로그아웃 때 캐시를 버린다. 들고 있으면 로그아웃한 뒤에도
// 하트가 채워진 채로 남는다.
//
// **이 구독을 supabase.ts가 아니라 여기에 둔다.** 계획서 초판은
// supabase.ts가 resetLikes를 import하게 했는데, 그러면 likes.ts와
// supabase.ts가 서로를 import하는 순환이 생긴다. 캐시의 주인이 여기이므로
// 구독도 여기 두는 것이 맞고, 순환이 아예 없어진다.
supabase.auth.onAuthStateChange((event) => {
  if (event === 'SIGNED_IN' || event === 'SIGNED_OUT') resetLikes()
})
