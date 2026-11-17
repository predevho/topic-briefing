import { supabase } from './supabase'

export type Note = { text: string; tags: string[] }

/**
 * 그 글의 가장 최근 메모. 없으면 null이다.
 *
 * `notes`는 **추가 전용**이다(UPDATE·DELETE 권한을 주지 않았다). 행이 여러
 * 개일 수 있고 **최신 하나만** 의미가 있다. 화면에서는 제자리 수정과
 * 구별되지 않으면서 수정 이력이 남는다.
 */
export async function loadNote(articleId: number): Promise<Note | null> {
  const { data, error } = await supabase
    .from('notes')
    .select('text, tags')
    .eq('article_id', articleId)
    .order('created_at', { ascending: false })
    .limit(1)

  // 로그인하지 않았으면 권한이 없다. 메모는 로그인 후에만 보이므로 정상이다.
  if (error) return null

  const row = data?.[0]
  if (!row) return null
  return { text: row.text as string, tags: (row.tags ?? []) as string[] }
}

/**
 * 메모를 저장한다. **새 행을 넣는다** — 수정이 아니다.
 * 태그 삭제도 "그 태그를 뺀 새 행"으로 표현된다.
 */
export async function saveNote(
  articleId: number,
  userId: string,
  note: Note,
): Promise<void> {
  const { error } = await supabase.from('notes').insert({
    article_id: articleId,
    // RLS의 with check가 auth.uid() = user_id를 요구한다. 빼면 거부된다.
    user_id: userId,
    text: note.text.trim(),
    tags: note.tags,
  })
  if (error) throw new Error(`메모를 저장하지 못했다: ${error.message}`)
}

/** 입력한 태그 문자열을 정리한다. 쉼표·공백으로 나누고 중복을 없앤다. */
export function parseTags(input: string): string[] {
  const parts = input
    .split(/[,\s]+/)
    .map((tag) => tag.replace(/^#/, '').trim())
    .filter((tag) => tag.length > 0)
  // Set으로 중복을 없애면서 입력 순서를 유지한다.
  return [...new Set(parts)]
}
