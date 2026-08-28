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

function Track({ track, duration }: { track: TimelineTrack; duration: number }) {
  const color = COLORS[track.type] ?? '#64748b'
  const items = track.cues?.map((cue) => ({ id: cue.id, start: cue.start_ms, end: cue.end_ms, label: cue.text })) ??
    track.clips?.map((clip) => ({
      id: clip.id,
      start: clip.timeline_start_ms ?? 0,
      end: clip.timeline_end_ms ?? 0,
      label: clip.asset_id?.slice(0, 8) ?? 'clip'
    })) ??
    []

  return (
    <div className="timeline-track">
      <span className="track-label">{track.name}</span>
      <div className="track-lane">
        {items.map((item) => (
          <b key={item.id} style={itemStyle(item.start, item.end, duration, color)} title={item.label}>
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
  const duration = timeline?.duration_ms || 120000

  return (
    <section className="timeline-panel" onClick={(event) => {
      const rect = event.currentTarget.getBoundingClientRect()
      const ratio = (event.clientX - rect.left) / rect.width
      setPlayhead(Math.round(duration * ratio))
    }}>
      <div className="playhead" style={{ left: `${(playhead / Math.max(duration, 1)) * 100}%` }} />
      {timeline?.tracks.map((track) => <Track key={track.id} track={track} duration={duration} />)}
    </section>
  )
}
