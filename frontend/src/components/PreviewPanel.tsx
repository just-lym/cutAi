import { Pause, Play, RotateCcw, RotateCw } from 'lucide-react'
import type { Timeline } from '../api/client'
import { useEditorStore } from '../stores/editor'

function formatMs(value: number) {
  const totalSeconds = Math.floor(value / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
}

export function PreviewPanel({ timeline }: { timeline: Timeline | undefined }) {
  const playhead = useEditorStore((state) => state.playheadMs)
  const isPlaying = useEditorStore((state) => state.isPlaying)
  const togglePlay = useEditorStore((state) => state.togglePlay)
  const setPlayhead = useEditorStore((state) => state.setPlayhead)
  const cues = timeline?.tracks.find((track) => track.id === 'subtitles')?.cues ?? []
  const activeCue = cues.find((cue) => cue.start_ms <= playhead && cue.end_ms > playhead)

  return (
    <section className="preview-panel">
      <div className="preview-stage">
        <div className="preview-frame">
          <strong>AICut Preview</strong>
          <span>{timeline ? `${timeline.width}x${timeline.height} · ${timeline.frame_rate}fps` : 'Loading'}</span>
          {activeCue ? <p className="subtitle-overlay">{activeCue.text}</p> : null}
        </div>
      </div>
      <div className="play-controls">
        <button className="icon-button" onClick={() => setPlayhead(Math.max(0, playhead - 5000))}>
          <RotateCcw size={18} />
        </button>
        <button className="primary-icon" onClick={togglePlay}>
          {isPlaying ? <Pause size={20} /> : <Play size={20} />}
        </button>
        <button className="icon-button" onClick={() => setPlayhead(playhead + 5000)}>
          <RotateCw size={18} />
        </button>
        <span>{formatMs(playhead)}</span>
      </div>
    </section>
  )
}
