import { useState } from 'react'
import { signOut, useSession } from './lib/auth'
import SignIn from './components/SignIn'

/**
 * 플레이스홀더다. Task 9(라우팅)가 `/`, `/:date`, `/archive`를 읽어
 * Today·Archive를 띄우는 실제 App으로 교체한다.
 *
 * 지금은 Task 10의 인증 배선을 눈으로 확인하는 역할을 한다 —
 * 세션이 잡히는지, 폼이 뜨는지, 로그아웃이 되는지.
 */
export default function App() {
  const { session, loading } = useSession()
  const [asking, setAsking] = useState(false)

  return (
    <main className="mx-auto max-w-[680px] px-[22px] py-10">
      <h1 className="font-serif text-[22px] font-semibold leading-[1.4]">
        브리핑
      </h1>
      <p className="mt-2 font-meta text-[13px] text-muted">
        디자인 토큰과 인증을 적용했다. 화면은 Task 7부터 붙는다.
      </p>

      <div className="mt-6 border-t border-rule pt-4">
        <p className="font-meta text-[12.5px] text-muted" data-testid="session">
          {loading
            ? '세션 확인 중…'
            : session
              ? `로그인됨 · ${session.user.id}`
              : '로그인하지 않음 (읽기는 이 상태로도 된다)'}
        </p>

        {!loading && !session && !asking && (
          <button
            type="button"
            onClick={() => setAsking(true)}
            className="mt-2 font-meta text-[12.5px] font-medium text-accent"
          >
            로그인
          </button>
        )}

        {!loading && session && (
          <button
            type="button"
            onClick={() => void signOut()}
            className="mt-2 font-meta text-[12.5px] text-muted underline"
          >
            로그아웃
          </button>
        )}

        {asking && (
          <SignIn
            onDone={() => setAsking(false)}
            onCancel={() => setAsking(false)}
          />
        )}
      </div>
    </main>
  )
}
