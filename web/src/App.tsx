/**
 * 플레이스홀더다. Task 9(라우팅)가 `/`, `/:date`, `/archive`를 읽어
 * Today·Archive를 띄우는 실제 App으로 교체한다.
 *
 * 스캐폴드의 Vite 보일러플레이트를 그대로 두지 않는 이유: `App.css`를
 * 지우면 import가 깨져 **빌드가 실패한다.** 각 커밋이 빌드되도록
 * 최소 형태로 바꿔 둔다.
 */
export default function App() {
  return (
    <main className="mx-auto max-w-[680px] px-[22px] py-10">
      <h1 className="font-serif text-[22px] font-semibold leading-[1.4]">
        브리핑
      </h1>
      <p className="mt-2 font-meta text-[13px] text-muted">
        디자인 토큰을 적용했다. 화면은 Task 7부터 붙는다.
      </p>
    </main>
  )
}
