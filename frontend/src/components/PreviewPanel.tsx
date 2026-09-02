import { CSSProperties, useEffect, useMemo, useRef } from 'react'
import { Pause, Play, RotateCcw, RotateCw } from 'lucide-react'
import { api, type Asset, type Clip, type Timeline } from '../api/client'
import { useEditorStore } from '../stores/editor'

function formatMs(value: number) {
  const totalSeconds = Math.floor(value / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
}

function findActiveMainClip(timeline: Timeline | undefined, playheadMs: number) {
  const mainTrack = timeline?.tracks.find((track) => track.id === 'video-main')
  return (mainTrack?.clips ?? [])
    .slice()
    .sort((left, right) => (left.timeline_start_ms ?? 0) - (right.timeline_start_ms ?? 0))
    .find((clip) => (clip.timeline_start_ms ?? 0) <= playheadMs && (clip.timeline_end_ms ?? 0) > playheadMs)
}

function findActiveTrackClips(timeline: Timeline | undefined, trackId: string, playheadMs: number) {
  const track = timeline?.tracks.find((item) => item.id === trackId)
  return (track?.clips ?? []).filter(
    (clip) => (clip.timeline_start_ms ?? 0) <= playheadMs && (clip.timeline_end_ms ?? 0) > playheadMs
  )
}

function TimelineAudio({
  asset,
  clip,
  playhead,
  isPlaying
}: {
  asset: Asset
  clip: Clip
  playhead: number
  isPlaying: boolean
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const speed = Math.max(0.1, Number(clip.speed ?? 1))
  const sourceTimeMs = Number(clip.source_in_ms ?? 0) + (playhead - Number(clip.timeline_start_ms ?? 0)) * speed
  const src = asset.proxy_path ? api.assets.proxyUrl(asset.id) : api.assets.fileUrl(asset.id)

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    audio.playbackRate = speed
    audio.volume = Math.max(0, Math.min(1, Number(clip.volume ?? 1)))
    if (Math.abs(audio.currentTime * 1000 - sourceTimeMs) > 250) {
      audio.currentTime = sourceTimeMs / 1000
    }
    if (isPlaying) {
      void audio.play().catch(() => undefined)
    } else {
      audio.pause()
    }
  }, [clip.volume, isPlaying, sourceTimeMs, speed])

  return <audio ref={audioRef} src={src} preload="metadata" />
}

function isMostlyLatin(text: string) {
  const latin = (text.match(/[A-Za-z]/g) ?? []).length
  const cjk = (text.match(/[\u3400-\u9fff]/g) ?? []).length
  return latin > 0 && latin >= cjk
}

function subtitlePosition(cue: { text: string; style: Record<string, unknown> | null }, index: number) {
  const stylePosition = String(cue.style?.position ?? cue.style?.placement ?? '').toLowerCase()
  if (['upper', 'top', 'above'].includes(stylePosition)) return 'upper'
  if (['lower', 'bottom', 'below'].includes(stylePosition)) return 'lower'
  if (isMostlyLatin(cue.text)) return 'lower'
  return index === 0 ? 'upper' : 'lower'
}

function overlayStyle(transform: Record<string, unknown> | undefined): CSSProperties {
  const x = Number(transform?.x ?? 0)
  const y = Number(transform?.y ?? 0)
  const scale = Math.max(0.1, Math.min(3, Number(transform?.scale ?? 1)))
  const width = Number(transform?.width ?? 360)
  return {
    left: `${x}px`,
    top: `${y}px`,
    width: `${Math.max(80, width * scale)}px`
  }
}

export function PreviewPanel({
  timeline,
  assets
}: {
  timeline: Timeline | undefined
  assets: Asset[]
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const playhead = useEditorStore((state) => state.playheadMs)
  const isPlaying = useEditorStore((state) => state.isPlaying)
  const togglePlay = useEditorStore((state) => state.togglePlay)
  const setPlaying = useEditorStore((state) => state.setPlaying)
  const setPlayhead = useEditorStore((state) => state.setPlayhead)
  const cues = timeline?.tracks.find((track) => track.id === 'subtitles')?.cues ?? []
  const activeCues = cues
    .filter((cue) => cue.start_ms <= playhead && cue.end_ms > playhead)
    .slice(0, 4)
  const brollTrack = timeline?.tracks.find((track) => track.id === 'video-broll')
  const activeOverlays = (brollTrack?.clips ?? [])
    .filter((clip) => (clip.timeline_start_ms ?? 0) <= playhead && (clip.timeline_end_ms ?? 0) > playhead)
    .map((clip) => ({ clip, asset: assets.find((item) => item.id === clip.asset_id) }))
    .filter((item) => item.asset)
  const activeClip = useMemo(() => findActiveMainClip(timeline, playhead), [playhead, timeline])
  const originalAudioClips = useMemo(
    () => findActiveTrackClips(timeline, 'audio-original', playhead),
    [playhead, timeline]
  )
  const musicClips = useMemo(
    () => findActiveTrackClips(timeline, 'audio-music', playhead),
    [playhead, timeline]
  )
  const asset = useMemo(
    () => assets.find((item) => item.id === activeClip?.asset_id),
    [activeClip?.asset_id, assets]
  )
  const videoSrc = asset ? (asset.proxy_path ? api.assets.proxyUrl(asset.id) : api.assets.fileUrl(asset.id)) : null
  const clipSpeed = Math.max(0.1, Number(activeClip?.speed ?? 1))
  const matchingOriginalAudio = originalAudioClips.find((clip) => clip.asset_id === activeClip?.asset_id)
  const sourceTimeMs = activeClip
    ? Number(activeClip.source_in_ms ?? 0) + (playhead - Number(activeClip.timeline_start_ms ?? 0)) * clipSpeed
    : 0

  useEffect(() => {
    const video = videoRef.current
    if (!video || !activeClip) return
    video.playbackRate = clipSpeed
    video.volume = Math.max(0, Math.min(1, Number(matchingOriginalAudio?.volume ?? activeClip.volume ?? 1)))
    if (Math.abs(video.currentTime * 1000 - sourceTimeMs) > 250) {
      video.currentTime = sourceTimeMs / 1000
    }
  }, [activeClip, clipSpeed, matchingOriginalAudio?.volume, sourceTimeMs, videoSrc])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    if (isPlaying) {
      void video.play().catch(() => setPlaying(false))
    } else {
      video.pause()
    }
  }, [isPlaying, setPlaying, videoSrc])

  return (
    <section className="preview-panel">
      <div className="preview-stage">
        <div className="preview-frame">
          {videoSrc ? (
            <video
              ref={videoRef}
              key={`${videoSrc}-${activeClip?.id ?? ''}`}
              className="preview-video"
              src={videoSrc}
              preload="metadata"
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onTimeUpdate={(event) => {
                if (!activeClip) return
                const sourcePositionMs = event.currentTarget.currentTime * 1000
                const sourceOutMs = Number(activeClip.source_out_ms ?? Number.POSITIVE_INFINITY)
                if (sourcePositionMs >= sourceOutMs - 20) {
                  setPlayhead(Number(activeClip.timeline_end_ms ?? playhead))
                  return
                }
                const nextPlayhead = Number(activeClip.timeline_start_ms ?? 0)
                  + (sourcePositionMs - Number(activeClip.source_in_ms ?? 0)) / clipSpeed
                setPlayhead(Math.min(Number(activeClip.timeline_end_ms ?? nextPlayhead), Math.round(nextPlayhead)))
              }}
              onLoadedMetadata={(event) => {
                event.currentTarget.currentTime = sourceTimeMs / 1000
                event.currentTarget.playbackRate = clipSpeed
              }}
            />
          ) : (
            <>
              <strong>AICut Preview</strong>
              <span>
                {timeline
                  ? `当前时间点没有主视频片段 · ${timeline.width}x${timeline.height}`
                  : 'Loading'}
              </span>
            </>
          )}
          {activeCues.length ? (
            <div className="subtitle-stack">
              {activeCues.map((cue, index) => (
                <p className={`subtitle-overlay ${subtitlePosition(cue, index)}`} key={cue.id}>
                  {cue.text}
                </p>
              ))}
            </div>
          ) : null}
          {activeOverlays.map(({ clip, asset }) => {
            if (!asset) return null
            const src = asset.proxy_path ? api.assets.proxyUrl(asset.id) : api.assets.fileUrl(asset.id)
            return asset.type === 'VIDEO' ? (
              <video
                key={clip.id}
                className="preview-overlay-media"
                src={src}
                muted
                autoPlay
                loop
                style={overlayStyle(clip.transform)}
              />
            ) : (
              <img
                key={clip.id}
                className="preview-overlay-media"
                src={src}
                alt=""
                style={overlayStyle(clip.transform)}
              />
            )
          })}
          {originalAudioClips
            .filter((clip) => clip.asset_id !== activeClip?.asset_id)
            .map((clip) => {
              const audioAsset = assets.find((item) => item.id === clip.asset_id)
              return audioAsset ? (
                <TimelineAudio key={clip.id} asset={audioAsset} clip={clip} playhead={playhead} isPlaying={isPlaying} />
              ) : null
            })}
          {musicClips.map((clip) => {
            const audioAsset = assets.find((item) => item.id === clip.asset_id)
            return audioAsset ? (
              <TimelineAudio key={clip.id} asset={audioAsset} clip={clip} playhead={playhead} isPlaying={isPlaying} />
            ) : null
          })}
          {asset?.processing_status === 'FAILED' ? (
            <p className="preview-warning">素材处理失败，请先点击左侧重处理按钮生成可播放代理。</p>
          ) : null}
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
