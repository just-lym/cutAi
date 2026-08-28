import { useEffect, useMemo, useRef } from 'react'
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
  const activeCue = cues.find((cue) => cue.start_ms <= playhead && cue.end_ms > playhead)
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
          {activeCue ? <p className="subtitle-overlay">{activeCue.text}</p> : null}
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
