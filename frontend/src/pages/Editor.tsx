import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Bot, Captions, Download, Film, FolderOpen, Image, Loader2, Music, Save, SlidersHorizontal, Square, Type } from 'lucide-react'
import { api, type Timeline as TimelineData } from '../api/client'
import { AgentPanel } from '../components/AgentPanel'
import { AssetPanel } from '../components/AssetPanel'
import { InspectorPanel } from '../components/InspectorPanel'
import { PreviewPanel } from '../components/PreviewPanel'
import { ScriptView } from '../components/ScriptView'
import { Timeline } from '../components/Timeline'
import { useHotkeys } from '../hooks/useHotkeys'
import { useWebSocket } from '../hooks/useWebSocket'
import { useEditorStore } from '../stores/editor'

const RESOLUTION_OPTIONS = [
  { label: '720p', width: 1280, height: 720 },
  { label: '1080p', width: 1920, height: 1080 },
  { label: '2K', width: 2560, height: 1440 },
  { label: '4K', width: 3840, height: 2160 }
]

const FRAME_RATE_OPTIONS = [24, 25, 30, 50, 60]

function formatEta(seconds: number) {
  const safeSeconds = Math.max(0, Math.ceil(seconds))
  const minutes = Math.floor(safeSeconds / 60)
  const rest = safeSeconds % 60
  return minutes ? `${minutes}分${rest.toString().padStart(2, '0')}秒` : `${rest}秒`
}

function estimateRenderSeconds(timeline: TimelineData | undefined, width: number, height: number, frameRate: number) {
  const durationSeconds = Math.max(1, (timeline?.duration_ms ?? 0) / 1000)
  const overlayCount = timeline?.tracks.find((track) => track.id === 'video-broll')?.clips?.length ?? 0
  const musicClipCount = timeline?.tracks.find((track) => track.id === 'audio-music')?.clips?.length ?? 0
  const subtitleCount = timeline?.tracks.find((track) => track.id === 'subtitles')?.cues?.length ?? 0
  const pixelFactor = (width * height) / (1280 * 720)
  const fpsFactor = frameRate / 30
  const complexity = 1.2 + overlayCount * 0.35 + musicClipCount * 0.15 + (subtitleCount ? 0.3 : 0)
  return Math.max(5, Math.round(durationSeconds * pixelFactor * fpsFactor * complexity * 0.35))
}

export function Editor() {
  const { projectId = '' } = useParams()
  const queryClient = useQueryClient()
  const [rightTab, setRightTab] = useState<'inspector' | 'agent'>('inspector')
  const [renderNotice, setRenderNotice] = useState('')
  const [resolution, setResolution] = useState('1920x1080')
  const [frameRate, setFrameRate] = useState('30')
  const [outputPath, setOutputPath] = useState('')
  const [currentRenderJobId, setCurrentRenderJobId] = useState<string | null>(null)
  const [currentRenderKind, setCurrentRenderKind] = useState<'preview' | 'export' | null>(null)
  const [renderStartedAt, setRenderStartedAt] = useState<number | null>(null)
  const [renderElapsed, setRenderElapsed] = useState(0)
  const [renderEstimateSeconds, setRenderEstimateSeconds] = useState(0)
  const [renderQuality, setRenderQuality] = useState<{
    score: number | null
    passed: boolean
    issues: string[]
    integratedLufs: number | null
  } | null>(null)
  const activeBottomTab = useEditorStore((state) => state.activeBottomTab)
  const setBottomTab = useEditorStore((state) => state.setBottomTab)
  const setSubtitleCues = useEditorStore((state) => state.setSubtitleCues)
  useHotkeys()

  const [project, timeline, assets, usage] = useQueries({
    queries: [
      { queryKey: ['project', projectId], queryFn: () => api.projects.get(projectId), enabled: !!projectId },
      { queryKey: ['timeline', projectId], queryFn: () => api.timeline.get(projectId), enabled: !!projectId },
      { queryKey: ['assets', projectId], queryFn: () => api.assets.list(projectId), enabled: !!projectId },
      { queryKey: ['usage'], queryFn: api.usage.summary }
    ]
  })

  const onSocketEvent = useCallback((event: { type: string; data: Record<string, unknown> }) => {
    if (event.type === 'job_progress') {
      const jobId = String(event.data.job_id ?? '')
      const isCurrentRender = Boolean(currentRenderJobId) && jobId === currentRenderJobId
      const estimated = Number(event.data.estimated_seconds ?? 0)
      if (isCurrentRender && estimated > 0) setRenderEstimateSeconds(estimated)
      const status = String(event.data.status ?? '')
      if (isCurrentRender && status === 'COMPLETED') {
        const output = event.data.output as Record<string, unknown> | undefined
        const path = String(output?.output_path ?? '')
        const quality = output?.quality_report as Record<string, unknown> | undefined
        const qualityIssues = Array.isArray(quality?.issues)
          ? quality.issues
              .map((item) => item as Record<string, unknown>)
              .map((item) => String(item.detail ?? ''))
              .filter(Boolean)
              .slice(0, 3)
          : []
        const audioQuality = quality?.audio as Record<string, unknown> | undefined
        setRenderQuality(quality ? {
          score: typeof quality.score === 'number' ? quality.score : null,
          passed: Boolean(quality.passed),
          issues: qualityIssues,
          integratedLufs: typeof audioQuality?.integrated_lufs === 'number' ? audioQuality.integrated_lufs : null
        } : null)
        const doneLabel = currentRenderKind === 'preview' ? '预览' : '导出'
        setRenderStartedAt(null)
        setCurrentRenderJobId(null)
        setCurrentRenderKind(null)
        setRenderNotice(path ? `${doneLabel}完成：${path}` : `${doneLabel}任务已完成。`)
      }
      if (isCurrentRender && status === 'FAILED') {
        setRenderStartedAt(null)
        setCurrentRenderJobId(null)
        setCurrentRenderKind(null)
        setRenderNotice(String(event.data.error ?? '导出失败，请查看任务错误。'))
      }
      if (isCurrentRender && status === 'CANCELLED') {
        setRenderStartedAt(null)
        setCurrentRenderJobId(null)
        setCurrentRenderKind(null)
        setRenderNotice('导出已停止，半成品已清理。')
      }
    }
    if (event.type === 'timeline_updated') {
      void queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['subtitles', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    }
    if (event.type === 'asset_deleted' || (event.type === 'job_progress' && event.data.asset_id)) {
      void queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    }
  }, [currentRenderJobId, currentRenderKind, projectId, queryClient])

  useWebSocket(projectId, onSocketEvent)

  const [selectedWidth, selectedHeight] = useMemo(
    () => resolution.split('x').map((value) => Number(value)),
    [resolution]
  )
  const selectedFrameRate = Number(frameRate)
  const renderOptions = {
    width: selectedWidth,
    height: selectedHeight,
    frame_rate: selectedFrameRate
  }
  const exportOptions = {
    ...renderOptions,
    output_path: outputPath.trim() || undefined
  }
  const currentEstimate = estimateRenderSeconds(timeline.data?.timeline_json, selectedWidth, selectedHeight, selectedFrameRate)

  useEffect(() => {
    if (!renderStartedAt) {
      setRenderElapsed(0)
      return
    }
    const timer = window.setInterval(() => {
      setRenderElapsed(Math.round((Date.now() - renderStartedAt) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [renderStartedAt])

  const previewRender = useMutation({
    mutationFn: () => api.render.preview(projectId, renderOptions),
    onMutate: () => {
      setRenderQuality(null)
      const estimate = currentEstimate
      setCurrentRenderKind('preview')
      setRenderEstimateSeconds(estimate)
      setRenderStartedAt(Date.now())
      setRenderNotice(`正在合成预览，预计 ${formatEta(estimate)}。`)
    },
    onSuccess: (job) => {
      const path = String(job.output?.output_path ?? '')
      setCurrentRenderJobId(job.id)
      setRenderNotice(path ? `预览正在后台合成：${path}` : '预览正在后台合成。')
    },
    onError: (error) => {
      setRenderStartedAt(null)
      setCurrentRenderJobId(null)
      setCurrentRenderKind(null)
      setRenderNotice(error instanceof Error ? error.message : '预览任务失败')
    }
  })

  const exportRender = useMutation({
    mutationFn: () => api.render.exports(projectId, exportOptions),
    onMutate: () => {
      setRenderQuality(null)
      const estimate = currentEstimate
      setCurrentRenderKind('export')
      setRenderEstimateSeconds(estimate)
      setRenderStartedAt(Date.now())
      setRenderNotice(`正在导出 ${selectedWidth}x${selectedHeight} / ${selectedFrameRate}fps，预计 ${formatEta(estimate)}。`)
    },
    onSuccess: (job) => {
      const path = String(job.output?.output_path ?? '')
      setCurrentRenderJobId(job.id)
      setRenderNotice(path ? `导出正在后台进行：${path}` : '导出正在后台进行。')
    },
    onError: (error) => {
      setRenderStartedAt(null)
      setCurrentRenderJobId(null)
      setCurrentRenderKind(null)
      setRenderNotice(error instanceof Error ? error.message : '导出失败')
    }
  })

  const chooseSavePath = useMutation({
    mutationFn: () => {
      const safeProjectName = (project.data?.name ?? 'final').replace(/[\\/:*?"<>|]+/g, '_').trim() || 'final'
      return api.render.chooseSavePath(`${safeProjectName}_v${project.data?.current_timeline_version ?? 1}.mp4`)
    },
    onSuccess: (result) => {
      if (result.path) {
        setOutputPath(result.path)
      }
    },
    onError: (error) => {
      setRenderNotice(error instanceof Error ? error.message : '选择保存位置失败')
    }
  })

  const cancelRender = useMutation({
    mutationFn: () => api.render.cancel(currentRenderJobId ?? ''),
    onMutate: () => {
      setRenderNotice('正在停止导出并清理半成品...')
    },
    onSuccess: () => {
      setRenderStartedAt(null)
      setCurrentRenderJobId(null)
      setCurrentRenderKind(null)
      setRenderNotice('导出已停止，半成品已清理。')
    },
    onError: (error) => {
      setRenderNotice(error instanceof Error ? error.message : '停止导出失败')
    }
  })

  const activeRender = previewRender.isPending || exportRender.isPending || Boolean(currentRenderJobId)
  const remainingSeconds = Math.max(0, (renderEstimateSeconds || currentEstimate) - renderElapsed)

  const cues = timeline.data?.timeline_json.tracks.find((track) => track.id === 'subtitles')?.cues ?? []

  useEffect(() => {
    setSubtitleCues(cues)
  }, [cues, setSubtitleCues])

  if (project.isLoading || timeline.isLoading) {
    return (
      <main className="loading-shell">
        <Loader2 className="spin" />
      </main>
    )
  }

  return (
    <main className="editor-shell">
      <header className="editor-header">
        <Link className="icon-button" to="/">
          <ArrowLeft size={18} />
        </Link>
        <div>
          <strong>{project.data?.name ?? 'AICut 项目'}</strong>
          <span>
            {project.data?.width}x{project.data?.height} · v{project.data?.current_timeline_version} · 预算余 ¥
            {usage.data?.budget_remaining.toFixed(2) ?? '--'}
          </span>
        </div>
        <div className="header-actions">
          <label className="export-select">
            <span>分辨率</span>
            <select value={resolution} onChange={(event) => setResolution(event.target.value)} disabled={activeRender}>
              {RESOLUTION_OPTIONS.map((item) => (
                <option key={item.label} value={`${item.width}x${item.height}`}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="export-select">
            <span>帧率</span>
            <select value={frameRate} onChange={(event) => setFrameRate(event.target.value)} disabled={activeRender}>
              {FRAME_RATE_OPTIONS.map((item) => (
                <option key={item} value={item}>
                  {item}fps
                </option>
              ))}
            </select>
          </label>
          <label className="export-path">
            <span>保存到</span>
            <span className="export-path-control">
              <input value={outputPath} onChange={(event) => setOutputPath(event.target.value)} disabled={activeRender} />
              <button
                className="icon-button"
                onClick={() => chooseSavePath.mutate()}
                disabled={activeRender || chooseSavePath.isPending}
                title="选择保存位置"
              >
                {chooseSavePath.isPending ? <Loader2 className="spin" size={16} /> : <FolderOpen size={16} />}
              </button>
            </span>
          </label>
          <button className="ghost-button" onClick={() => previewRender.mutate()} disabled={activeRender}>
            {previewRender.isPending ? <Loader2 className="spin" size={17} /> : <Save size={17} />}
            合成预览
          </button>
          <button className="primary-icon" onClick={() => exportRender.mutate()} disabled={activeRender}>
            {exportRender.isPending ? <Loader2 className="spin" size={17} /> : <Download size={17} />}
            导出
          </button>
          {currentRenderJobId ? (
            <button className="danger-ghost-button" onClick={() => cancelRender.mutate()} disabled={cancelRender.isPending}>
              {cancelRender.isPending ? <Loader2 className="spin" size={17} /> : <Square size={15} />}
              停止
            </button>
          ) : null}
        </div>
      </header>

      <nav className="editor-toolstrip">
        <button className="active"><Film size={16} />媒体</button>
        <button><Music size={16} />音频</button>
        <button><Type size={16} />文本</button>
        <button><Captions size={16} />字幕</button>
        <button><Image size={16} />贴纸</button>
        <button><SlidersHorizontal size={16} />调节</button>
        {activeRender ? (
          <span>
            {currentRenderKind === 'preview' ? '预览' : '导出'}已用 {formatEta(renderElapsed)}，约剩 {formatEta(remainingSeconds)} · {renderNotice}
          </span>
        ) : renderNotice ? (
          <span>{renderNotice}</span>
        ) : null}
      </nav>
      {renderQuality ? (
        <div className={renderQuality.passed ? 'render-quality passed' : 'render-quality needs-review'}>
          <b>质量自评：{renderQuality.score === null ? '未评分' : `${renderQuality.score} 分`} ·
            {renderQuality.passed ? '通过' : '建议复查'}</b>
          {renderQuality.integratedLufs !== null ? <span>响度 {renderQuality.integratedLufs.toFixed(1)} LUFS</span> : null}
          {renderQuality.issues.length ? <span>{renderQuality.issues.join('；')}</span> : null}
        </div>
      ) : null}

      <section className="editor-grid">
        <AssetPanel projectId={projectId} assets={assets.data ?? []} />
        <PreviewPanel timeline={timeline.data?.timeline_json} assets={assets.data ?? []} />
        <aside className="right-workspace">
          <div className="right-tabs">
            <button className={rightTab === 'inspector' ? 'active' : ''} onClick={() => setRightTab('inspector')}>
              <SlidersHorizontal size={15} />
              参数
            </button>
            <button className={rightTab === 'agent' ? 'active' : ''} onClick={() => setRightTab('agent')}>
              <Bot size={15} />
              AI
            </button>
          </div>
          {rightTab === 'inspector' ? (
            <InspectorPanel projectId={projectId} timeline={timeline.data?.timeline_json} assets={assets.data ?? []} />
          ) : (
            <AgentPanel
              projectId={projectId}
              videoType={project.data?.video_type ?? 'TALKING_HEAD'}
              assets={assets.data ?? []}
              timeline={timeline.data?.timeline_json}
            />
          )}
        </aside>
      </section>

      <section className="bottom-workspace">
        <div className="tabs">
          <button className={activeBottomTab === 'timeline' ? 'active' : ''} onClick={() => setBottomTab('timeline')}>
            时间轴
          </button>
          <button className={activeBottomTab === 'script' ? 'active' : ''} onClick={() => setBottomTab('script')}>
            脚本
          </button>
        </div>
        {activeBottomTab === 'timeline' ? (
          <Timeline timeline={timeline.data?.timeline_json} />
        ) : (
          <ScriptView projectId={projectId} cues={cues} />
        )}
      </section>
    </main>
  )
}
