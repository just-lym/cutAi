import { useEffect } from 'react'
import { useEditorStore } from '../stores/editor'

function isEditable(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable
}

export function useHotkeys() {
  const setPlayhead = useEditorStore((state) => state.setPlayhead)
  const playhead = useEditorStore((state) => state.playheadMs)
  const togglePlay = useEditorStore((state) => state.togglePlay)
  const setPlaying = useEditorStore((state) => state.setPlaying)
  const undo = useEditorStore((state) => state.undo)
  const redo = useEditorStore((state) => state.redo)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditable(event.target)) return
      const mod = event.ctrlKey || event.metaKey
      if (event.code === 'Space') {
        event.preventDefault()
        togglePlay()
      } else if (event.key.toLowerCase() === 'k') {
        setPlaying(false)
      } else if (event.key.toLowerCase() === 'j' || event.key === 'ArrowLeft') {
        event.preventDefault()
        setPlayhead(playhead - (event.ctrlKey ? 1000 : 100))
      } else if (event.key.toLowerCase() === 'l' || event.key === 'ArrowRight') {
        event.preventDefault()
        setPlayhead(playhead + (event.ctrlKey ? 1000 : 100))
      } else if (mod && event.key.toLowerCase() === 'z' && event.shiftKey) {
        event.preventDefault()
        redo()
      } else if (mod && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        undo()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [playhead, redo, setPlayhead, setPlaying, togglePlay, undo])
}
