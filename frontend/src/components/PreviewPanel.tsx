import { CSSProperties, useEffect, useMemo, useRef } from 'react'
import { Pause, Play, RotateCcw, RotateCw } from 'lucide-react'
import { api, type Asset, type Timeline } from '../api/client'
import { useEditorStore } from '../stores/editor'

function formatMs(value: number) {
  const totalSeconds = Math.floor(value / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
}

function findMainVideoAsset(timeline: Timeline | undefined, assets: Asset[]) {
  const mainTrack = timeline?.tracks.find((track) => track.id === 'video-main')
  const assetId = mainTrack?.clips?.[0]?.asset_id
  return assets.find((asset) => asset.id === assetId) ?? assets.find((asset) => asset.type === 'VIDEO')
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
  const asset = useMemo(() => findMainVideoAsset(timeline, assets), [assets, timeline])
  const videoSrc = asset ? (asset.proxy_path ? api.assets.proxyUrl(asset.id) : api.assets.fileUrl(asset.id)) : null

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    if (Math.abs(video.currentTime * 1000 - playhead) > 500) {
      video.currentTime = playhead / 1000
    }
  }, [playhead, videoSrc])

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
              key={videoSrc}
              className="preview-video"
              src={videoSrc}
              controls
              preload="metadata"
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onTimeUpdate={(event) => setPlayhead(Math.round(event.currentTarget.currentTime * 1000))}
              onLoadedMetadata={(event) => setPlayhead(Math.round(event.currentTarget.currentTime * 1000))}
            />
          ) : (
            <>
              <strong>AICut Preview</strong>
              <span>{timeline ? `${timeline.width}x${timeline.height} · ${timeline.frame_rate}fps` : 'Loading'}</span>
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
