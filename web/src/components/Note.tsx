import { useEffect, useState } from 'react'
import { useSession } from '../lib/auth'
import { loadNote, parseTags, saveNote } from '../lib/notes'
import type { Note as NoteData } from '../lib/notes'
import SignIn from './SignIn'

type Props = { articleId: number }

export default function Note({ articleId }: Props) {
  const { session } = useSession()
  const [open, setOpen] = useState(false)
  const [asking, setAsking] = useState(false)
  const [note, setNote] = useState<NoteData>({ text: '', tags: [] })
  const [tagInput, setTagInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)

  // 열 때, 그리고 로그인 상태가 바뀔 때 최신 행을 읽는다.
  useEffect(() => {
    if (!open || !session) return
    let alive = true
    void loadNote(articleId).then((found) => {
      if (alive && found) setNote(found)
    })
    return () => {
      alive = false
    }
  }, [open, session, articleId])

  function press() {
    if (!session) {
      setAsking(true)
      return
    }
    setOpen((was) => !was)
  }

  async function save() {
    if (!session) return
    setBusy(true)
    try {
      // 입력창에 남은 태그도 함께 넣는다 — 엔터를 누르지 않고 저장하는
      // 경우가 흔하고, 그때 조용히 사라지면 안 된다.
      const pending = parseTags(tagInput)
      const merged = {
        text: note.text,
        tags: [...new Set([...note.tags, ...pending])],
      }
      await saveNote(articleId, session.user.id, merged)
      setNote(merged)
      setTagInput('')
      setSaved(true)
      setTimeout(() => setSaved(false), 1800)
    } finally {
      setBusy(false)
    }
  }

  function removeTag(tag: string) {
    // 화면에서만 뺀다. 저장을 누를 때 "그 태그가 없는 새 행"이 들어간다.
    setNote((was) => ({ ...was, tags: was.tags.filter((item) => item !== tag) }))
  }

  const hasNote = note.text.length > 0 || note.tags.length > 0

  return (
    <>
      <button
        type="button"
        onClick={press}
        aria-expanded={open}
        className="flex h-11 items-center font-meta text-[11.5px] font-medium"
        // accent는 상호작용에만 쓴다 (요구사항 O14).
        style={{ color: 'var(--color-accent)' }}
      >
        {open ? '메모 닫기' : hasNote ? '메모 보기' : '메모'}
      </button>

      {asking && (
        <SignIn
          onDone={() => {
            setAsking(false)
            setOpen(true)
          }}
          onCancel={() => setAsking(false)}
        />
      )}

      {open && session && (
        <div className="mt-1.5 rounded-md border border-rule bg-panel p-3">
          <textarea
            value={note.text}
            onChange={(event) => setNote({ ...note, text: event.target.value })}
            rows={3}
            placeholder="이 글에 대해 남길 메모"
            className="mb-2 w-full resize-y rounded border border-edge bg-paper px-2.5 py-2 font-meta text-[13.5px] leading-[1.6]"
          />

          {note.tags.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {note.tags.map((tag) => (
                <span
                  key={tag}
                  className="flex items-center gap-1 rounded bg-tag px-2 py-0.5 font-meta text-[11.5px] text-ink-2"
                >
                  {tag}
                  <button
                    type="button"
                    onClick={() => removeTag(tag)}
                    aria-label={`${tag} 태그 빼기`}
                    className="text-muted"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}

          <input
            value={tagInput}
            onChange={(event) => setTagInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter') return
              event.preventDefault()
              const parsed = parseTags(tagInput)
              if (parsed.length === 0) return
              setNote((was) => ({
                ...was,
                tags: [...new Set([...was.tags, ...parsed])],
              }))
              setTagInput('')
            }}
            placeholder="태그 (쉼표나 엔터로 구분)"
            className="mb-2.5 w-full rounded border border-edge bg-paper px-2.5 py-1.5 font-meta text-[12.5px]"
          />

          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={() => void save()}
              disabled={busy}
              className="rounded px-3 py-1.5 font-meta text-[12.5px] font-medium text-paper disabled:opacity-50"
              style={{ backgroundColor: 'var(--color-accent)' }}
            >
              {busy ? '저장 중…' : '저장'}
            </button>
            {saved && (
              <span className="font-meta text-[12px] text-muted">
                저장했습니다
              </span>
            )}
          </div>

          <p className="mt-2 font-meta text-[11.5px] leading-[1.5] text-muted-2">
            저장할 때마다 새 기록이 쌓입니다. 이전 메모는 지워지지 않습니다.
          </p>
        </div>
      )}
    </>
  )
}
