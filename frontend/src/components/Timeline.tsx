import { useRef } from 'react'
import type { Timeline as TimelineType, TimelineTrack } from '../api/client'
import { useEditorStore } from '../stores/editor'

const COLORS: Record<string, string> = {
  VIDEO_MAIN: '#3b82f6',
  VIDEO_BROLL: '#8b5cf6',
  SUBTITLE: '#22c55e',
  AUDIO_ORIGINAL: '#eab308',
  AUDIO_MUSIC: '#ec4899'
}

function itemStyle(start: number, end: number, duration: number, color: string) {
  const safeDuration = Math.max(duration, 1000)
  return {
    left: `${(start / safeDuration) * 100}%`,
    width: `${Math.max(1.5, ((end - start) / safeDuration) * 100)}%`,
    backgroundColor: color
  }
}

function Track({
  track,
  duration,
  selection,
  onRangeStart,
  onRangeMove,
  onRangeEnd
}: {
  track: TimelineTrack
  duration: number
  selection: { start_ms: number; end_ms: number } | null
  onRangeStart: (value: number) => void
  onRangeMove: (value: number) => void
  onRangeEnd: (value: number) => void
}) {
  const color = COLORS[track.type] ?? '#64748b'
  const selectedClipIds = useEditorStore((state) => state.selectedClipIds)
  const selectClip = useEditorStore((state) => state.selectClip)
  const setPlayhead = useEditorStore((state) => state.setPlayhead)
  const items = track.cues?.map((cue) => ({ id: cue.id, start: cue.start_ms, end: cue.end_ms, label: cue.text })) ??
    track.clips?.map((clip) => ({
      id: clip.id,
      start: clip.timeline_start_ms ?? 0,
      end: clip.timeline_end_ms ?? 0,
      label: clip.asset_id?.slice(0, 8) ?? 'clip',
      selectable: true
    })) ??
    []

  return (
    <div className="timeline-track">
      <span className="track-label">{track.name}</span>
      <div
        className="track-lane"
        onPointerDown={(event) => {
          if (event.button !== 0) return
          event.currentTarget.setPointerCapture(event.pointerId)
          const rect = event.currentTarget.getBoundingClientRect()
          onRangeStart(Math.round(duration * (event.clientX - rect.left) / rect.width))
        }}
        onPointerMove={(event) => {
          if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
          const rect = event.currentTarget.getBoundingClientRect()
          onRangeMove(Math.round(duration * (event.clientX - rect.left) / rect.width))
        }}
        onPointerUp={(event) => {
          const rect = event.currentTarget.getBoundingClientRect()
          onRangeEnd(Math.round(duration * (event.clientX - rect.left) / rect.width))
          event.currentTarget.releasePointerCapture(event.pointerId)
        }}
      >
        {selection ? (
          <span
            className="timeline-selection"
            style={itemStyle(selection.start_ms, selection.end_ms, duration, 'rgba(34, 211, 238, 0.2)')}
          />
        ) : null}
        {items.map((item) => (
          <b
            key={item.id}
            className={selectedClipIds.includes(item.id) ? 'selected' : ''}
            style={itemStyle(item.start, item.end, duration, color)}
            title={item.label}
            onClick={(event) => {
              event.stopPropagation()
              if ('selectable' in item) {
                selectClip(item.id, event.shiftKey)
                setPlayhead(item.start)
              }
            }}
            onPointerDown={(event) => event.stopPropagation()}
          >
            {item.label}
          </b>
        ))}
      </div>
    </div>
  )
}

export function Timeline({ timeline }: { timeline: TimelineType | undefined }) {
  const playhead = useEditorStore((state) => state.playheadMs)
  const setPlayhead = useEditorStore((state) => state.setPlayhead)
  const selection = useEditorStore((state) => state.highlightRange)
  const setSelection = useEditorStore((state) => state.setHighlightRange)
  const dragStart = useRef<number | null>(null)
  const duration = timeline?.duration_ms || 120000

  const bounded = (value: number) => Math.max(0, Math.min(duration, value))
  const updateSelection = (value: number) => {
    if (dragStart.current === null) return
    const next = bounded(value)
    setSelection({ start_ms: Math.min(dragStart.current, next), end_ms: Math.max(dragStart.current, next) })
  }

  return (
    <section className="timeline-panel">
      <div className="playhead" style={{ left: `${(playhead / Math.max(duration, 1)) * 100}%` }} />
      {timeline?.tracks.map((track) => (
        <Track
          key={track.id}
          track={track}
          duration={duration}
          selection={selection}
          onRangeStart={(value) => {
            dragStart.current = bounded(value)
            setPlayhead(bounded(value))
            setSelection(null)
          }}
          onRangeMove={updateSelection}
          onRangeEnd={(value) => {
            updateSelection(value)
            if (dragStart.current !== null && Math.abs(bounded(value) - dragStart.current) < 100) {
              setSelection(null)
              setPlayhead(bounded(value))
            }
            dragStart.current = null
          }}
        />
      ))}
    </section>
  )
}
