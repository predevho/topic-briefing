import { useEffect, useState } from 'react'
import { useSession } from '../lib/auth'
import { loadLikes, subscribe, toggleLike } from '../lib/likes'
import SignIn from './SignIn'

type Props = { articleId: number; className?: string }

export default function LikeButton({ articleId, className = '' }: Props) {
  const { session } = useSession()
  const [liked, setLiked] = useState(false)
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)

  // 집합이 바뀌면(다른 카드에서 눌렀거나 로그인했을 때) 다시 읽는다.
  useEffect(() => {
    let alive = true
    const read = () => {
      void loadLikes().then((set) => {
        if (alive) setLiked(set.has(articleId))
      })
    }
    read()
    const stop = subscribe(read)
    return () => {
      alive = false
      stop()
    }
  }, [articleId, session])

  async function press() {
    // 로그인하지 않았으면 누른 자리에서 폼을 띄운다. 페이지를 가리지 않는다.
    if (!session) {
      setAsking(true)
      return
    }
    setBusy(true)
    try {
      setLiked(await toggleLike(articleId, session.user.id))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => void press()}
        disabled={busy}
        aria-pressed={liked}
        aria-label={liked ? '좋아요 취소' : '좋아요'}
        // 44×44: 손가락 터치 목표 크기 (목업).
        className={`flex h-11 w-11 items-center justify-center disabled:opacity-50 ${className}`}
      >
        <svg
          viewBox="0 0 24 24"
          className="h-[18px] w-[18px]"
          fill={liked ? 'currentColor' : 'none'}
          stroke="currentColor"
          strokeWidth="1.6"
          // accent는 상호작용에만 쓴다 (요구사항 O14).
          style={{ color: liked ? 'var(--color-accent)' : 'var(--color-muted)' }}
        >
          <path d="M12 20.2l-1.4-1.3C6 14.8 3.4 12.4 3.4 9.3 3.4 6.9 5.3 5 7.7 5c1.4 0 2.7.6 3.5 1.7l.8 1 .8-1C13.6 5.6 14.9 5 16.3 5 18.7 5 20.6 6.9 20.6 9.3c0 3.1-2.6 5.5-7.2 9.6L12 20.2z" />
        </svg>
      </button>

      {asking && (
        // 로그인 직후 집합을 다시 받는 일은 따로 하지 않는다 —
        // onAuthStateChange가 likes.ts의 캐시를 비우고, useSession이
        // 갱신되어 위 useEffect가 다시 돈다.
        <SignIn onDone={() => setAsking(false)} onCancel={() => setAsking(false)} />
      )}
    </>
  )
}
