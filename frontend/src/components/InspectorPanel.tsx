import { useEffect, useMemo, useState } from 'react'
import { Scissors, Trash2, Upload, Volume2 } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type Asset, type Clip, type EditOperation, type Timeline } from '../api/client'
import { useEditorStore } from '../stores/editor'

type Props = {
  projectId: string
  timeline: Timeline | undefined
  assets: Asset[]
}

function findClip(timeline: Timeline | undefined, clipId: string | null) {
  if (!timeline || !clipId) return null
  for (const track of timeline.tracks) {
    for (const clip of track.clips ?? []) {
      if (clip.id === clipId) return { track, clip }
    }
  }
  return null
}

function msToSeconds(value: number | undefined) {
  return ((value ?? 0) / 1000).toFixed(2)
}

function secondsToMs(value: string) {
  return Math.max(0, Math.round(Number(value || 0) * 1000))
}

export function InspectorPanel({ projectId, timeline, assets }: Props) {
  const queryClient = useQueryClient()
  const playheadMs = useEditorStore((state) => state.playheadMs)
  const selectedAssetId = useEditorStore((state) => state.selectedAssetId)
  const selectedClipIds = useEditorStore((state) => state.selectedClipIds)
  const clearClipSelection = useEditorStore((state) => state.clearClipSelection)
  const selectedClipId = selectedClipIds[0] ?? null
  const selection = useMemo(() => findClip(timeline, selectedClipId), [selectedClipId, timeline])
  const selectedAsset = assets.find((asset) => asset.id === selectedAssetId) ?? null
  const [startSeconds, setStartSeconds] = useState('0.00')
  const [endSeconds, setEndSeconds] = useState('0.00')
  const [volume, setVolume] = useState('1.00')
  const [positionX, setPositionX] = useState('0')
  const [positionY, setPositionY] = useState('0')
  const [scale, setScale] = useState('1')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    const transform = selection?.clip.transform ?? {}
    setStartSeconds(msToSeconds(selection?.clip.timeline_start_ms))
    setEndSeconds(msToSeconds(selection?.clip.timeline_end_ms))
    setVolume(String(selection?.clip.volume ?? 1))
    setPositionX(String(transform.x ?? 0))
    setPositionY(String(transform.y ?? 0))
    setScale(String(transform.scale ?? 1))
  }, [selection?.clip])

  const commit = useMutation({
    mutationFn: (payload: { operations: EditOperation[]; summary: string }) =>
      api.timeline.commit(projectId, {
        operations: payload.operations,
        change_summary: payload.summary
      }),
    onSuccess: async (_, variables) => {
      setNotice(variables.summary)
      await queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    },
    onError: (error) => {
      setNotice(error instanceof Error ? error.message : '操作失败')
    }
  })

  const insertSelectedAsset = () => {
    if (!selectedAsset) return
    const duration = selectedAsset.type === 'IMAGE' ? 4000 : selectedAsset.duration_ms ?? 4000
    commit.mutate({
      summary: `手动插入素材 ${selectedAsset.original_name}`,
      operations: [
        {
          type: 'INSERT_MEDIA_CLIP',
          asset_id: selectedAsset.id,
          track_type: selectedAsset.type === 'AUDIO' ? 'audio' : selectedAsset.type === 'IMAGE' ? 'broll' : 'video',
          position_ms: playheadMs,
          duration_ms: duration,
          source_in_ms: 0,
          source_out_ms: duration,
          volume: selectedAsset.type === 'AUDIO' ? 0.7 : 1
        }
      ]
    })
  }

  const splitSelectedClip = () => {
    if (!selection) return
    const clip = selection.clip
    const start = clip.timeline_start_ms ?? 0
    const end = clip.timeline_end_ms ?? 0
    if (playheadMs <= start || playheadMs >= end) {
      setNotice('播放头需要位于选中片段内部才能拆分。')
      return
    }
    commit.mutate({
      summary: '手动拆分片段',
      operations: [{ type: 'SPLIT_CLIP', clip_id: clip.id, at_ms: playheadMs }]
    })
  }

  const deleteSelectedClips = () => {
    const selected: Clip[] = []
    for (const track of timeline?.tracks ?? []) {
      for (const clip of track.clips ?? []) {
        if (selectedClipIds.includes(clip.id)) selected.push(clip)
      }
    }
    if (!selected.length) return
    commit.mutate({
      summary: '手动删除选中片段',
      operations: selected.map((clip) => ({ type: 'DELETE_CLIP', clip_id: clip.id }))
    })
    clearClipSelection()
  }

  const updateSelectedClip = () => {
    if (!selection) return
    const start = secondsToMs(startSeconds)
    const end = secondsToMs(endSeconds)
    if (end <= start) {
      setNotice('结束时间必须大于开始时间。')
      return
    }
    const operations: EditOperation[] = [
      {
        type: 'UPDATE_CLIP',
        clip_id: selection.clip.id,
        timeline_start_ms: start,
        timeline_end_ms: end,
        volume: Math.min(2, Math.max(0, Number(volume || 1)))
      }
    ]
    operations.push({
      type: 'UPDATE_CLIP_TRANSFORM',
      clip_id: selection.clip.id,
      transform: {
        x: Math.round(Number(positionX || 0)),
        y: Math.round(Number(positionY || 0)),
        scale: Math.max(0.1, Math.min(3, Number(scale || 1)))
      }
    })
    commit.mutate({
      summary: '手动调整片段参数',
      operations
    })
  }

  return (
    <aside className="panel inspector-panel">
      <div className="panel-title">
        <h2>参数</h2>
        <span className="muted">{timeline ? `${timeline.width}x${timeline.height}` : '未加载'}</span>
      </div>

      <section className="inspector-section">
        <div className="section-label">手动编辑</div>
        <div className="manual-actions">
          <button className="ghost-button" onClick={insertSelectedAsset} disabled={!selectedAsset || commit.isPending}>
            <Upload size={15} />
            插入素材
          </button>
          <button className="ghost-button" onClick={splitSelectedClip} disabled={!selection || commit.isPending}>
            <Scissors size={15} />
            拆分
          </button>
          <button className="ghost-button danger-button" onClick={deleteSelectedClips} disabled={!selection || commit.isPending}>
            <Trash2 size={15} />
            删除
          </button>
        </div>
      </section>

      <section className="inspector-section">
        <div className="section-label">选中素材</div>
        {selectedAsset ? (
          <div className="property-list">
            <span>{selectedAsset.original_name}</span>
            <small>{selectedAsset.type} · {selectedAsset.duration_ms ? `${(selectedAsset.duration_ms / 1000).toFixed(1)}s` : '无时长'}</small>
          </div>
        ) : (
          <p className="muted compact">从左侧选择一个素材。</p>
        )}
      </section>

      <section className="inspector-section">
        <div className="section-label">选中片段</div>
        {selection ? (
          <div className="clip-form">
            <label>
              <span>开始</span>
              <input value={startSeconds} onChange={(event) => setStartSeconds(event.target.value)} />
            </label>
            <label>
              <span>结束</span>
              <input value={endSeconds} onChange={(event) => setEndSeconds(event.target.value)} />
            </label>
            <label>
              <span><Volume2 size={13} />音量</span>
              <input value={volume} onChange={(event) => setVolume(event.target.value)} />
            </label>
            <div className="transform-grid">
              <label>
                <span>X</span>
                <input value={positionX} onChange={(event) => setPositionX(event.target.value)} />
              </label>
              <label>
                <span>Y</span>
                <input value={positionY} onChange={(event) => setPositionY(event.target.value)} />
              </label>
              <label>
                <span>缩放</span>
                <input value={scale} onChange={(event) => setScale(event.target.value)} />
              </label>
            </div>
            <button className="wide-button" onClick={updateSelectedClip} disabled={commit.isPending}>
              应用参数
            </button>
          </div>
        ) : (
          <p className="muted compact">点击底部时间线上的片段进行编辑。</p>
        )}
      </section>

      {notice ? <p className={commit.isError ? 'error-text' : 'success-text'}>{notice}</p> : null}
    </aside>
  )
}
