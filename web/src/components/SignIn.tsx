import { useState } from 'react'
import type { FormEvent } from 'react'
import { signIn } from '../lib/auth'

type Props = { onDone: () => void; onCancel: () => void }

/**
 * 쓰기를 누를 때만 뜨는 작은 폼이다. 전체 화면을 가리지 않는다 —
 * 아침에 카톡 링크를 탭했을 때 로그인 화면이 뜨면 그 시스템은 쓰이지
 * 않는다(설계 2.1).
 */
export default function SignIn({ onDone, onCancel }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(email, password)
      onDone()
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mt-3 rounded-md border border-rule bg-panel p-3.5"
    >
      <p className="mb-2.5 font-meta text-[12.5px] leading-[1.5] text-muted">
        좋아요와 메모는 기기당 한 번만 로그인하면 됩니다. 읽기는 로그인이
        필요하지 않습니다.
      </p>

      <input
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        placeholder="이메일"
        autoComplete="username"
        required
        className="mb-2 w-full rounded border border-edge bg-paper px-2.5 py-2 font-meta text-[13.5px]"
      />
      <input
        type="password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        placeholder="비밀번호"
        autoComplete="current-password"
        required
        className="mb-2.5 w-full rounded border border-edge bg-paper px-2.5 py-2 font-meta text-[13.5px]"
      />

      {error && (
        <p className="mb-2 font-meta text-[12.5px] leading-[1.5] text-warn">
          {error}
        </p>
      )}

      <div className="flex items-center gap-2">
        {/* accent는 상호작용에만 쓴다 (요구사항 O14). */}
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-accent px-3 py-1.5 font-meta text-[12.5px] font-medium text-paper disabled:opacity-50"
        >
          {busy ? '확인 중…' : '로그인'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="font-meta text-[12.5px] text-muted"
        >
          취소
        </button>
      </div>
    </form>
  )
}
