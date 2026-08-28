import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Search, Trash2 } from 'lucide-react'
import { api, type SubtitleCue } from '../api/client'
import { useEditorStore } from '../stores/editor'

type Props = {
  projectId: string
  cues: SubtitleCue[]
}

export function ScriptView({ projectId, cues }: Props) {
  const [query, setQuery] = useState('')
  const queryClient = useQueryClient()
  const setPlayhead = useEditorStore((state) => state.setPlayhead)
  const selectedCueIds = useEditorStore((state) => state.selectedCueIds)
  const selectCue = useEditorStore((state) => state.selectCue)

  const update = useMutation({
    mutationFn: ({ cue, text }: { cue: SubtitleCue; text: string }) =>
      api.subtitles.update(projectId, cue.id, { text, start_ms: cue.start_ms, end_ms: cue.end_ms }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
  })

  const remove = useMutation({
    mutationFn: (cueId: string) => api.subtitles.remove(projectId, cueId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['subtitles', projectId] })
    }
  })

  const filtered = useMemo(
    () => cues.filter((cue) => cue.text.toLowerCase().includes(query.toLowerCase())),
    [cues, query]
  )

  return (
    <section className="script-panel">
      <label className="search-box">
        <Search size={16} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索字幕" />
      </label>
      <div className="cue-list">
        {filtered.map((cue) => (
          <article
            key={cue.id}
            className={selectedCueIds.includes(cue.id) ? 'cue selected' : 'cue'}
            onClick={(event) => {
              selectCue(cue.id, event.shiftKey)
              setPlayhead(cue.start_ms)
            }}
          >
            <time>{Math.round(cue.start_ms / 1000)}s</time>
            <textarea
              defaultValue={cue.text}
              onBlur={(event) => {
                if (event.currentTarget.value !== cue.text) {
                  update.mutate({ cue, text: event.currentTarget.value })
                }
              }}
            />
            <button className="icon-button" onClick={() => remove.mutate(cue.id)}>
              <Trash2 size={16} />
            </button>
          </article>
        ))}
      </div>
    </section>
  )
}
