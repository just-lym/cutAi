import { FormEvent, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AudioLines, Ban, Bot, Check, ChevronDown, CircleDot, CircleHelp, History, Loader2, ScanSearch, RotateCcw, Send, Sparkles, Video, WandSparkles, X } from 'lucide-react'
import { api, type AgentTraceStep, type Asset, type EditPlan, type Timeline } from '../api/client'
import { getVideoMode, VIDEO_MODE_OPTIONS, type VideoType } from '../constants/videoModes'
import { useEditorStore } from '../stores/editor'

type Decision = 'approved' | 'rejected'

function operationTitle(operation: Record<string, unknown>) {
  const type = operation.type
  if (type === 'DELETE_RANGE') return '删除静音'
  if (type === 'SET_VOLUME') return '调整音量'
  if (type === 'INSERT_MEDIA_CLIP') return '插入素材'
  if (type === 'SPLIT_CLIP') return '拆分片段'
  if (type === 'UPDATE_CLIP') return '调整片段'
  if (type === 'DELETE_CLIP') return '删除片段'
  if (type === 'UPDATE_CLIP_TRANSFORM') return '调整画面'
  if (type === 'APPLY_CLIP_EFFECT') return '添加效果'
  if (type === 'TRIM_CLIP') return '裁切片段'
  if (type === 'MOVE_CLIP') return '移动片段'
  if (type === 'SET_CLIP_SPEED') return '调整速度'
  if (type === 'SET_CLIP_VOLUME') return '调整片段音量'
  if (type === 'DUPLICATE_CLIP') return '复制片段'
  if (type === 'ADD_TRANSITION') return '添加转场'
  if (type === 'REMOVE_EFFECT') return '移除效果'
  if (type === 'UPDATE_SUBTITLE') return '修正字幕'
  if (type === 'CREATE_SUBTITLE') return '新增字幕'
  if (type === 'DELETE_SUBTITLE') return '删除字幕'
  if (type === 'ADD_MARKER') return '添加标记'
  if (type === 'UPDATE_SUBTITLE_STYLE') return '调整字幕样式'
  if (type === 'REMOVE_MARKER') return '移除标记'
  if (type === 'INSERT_BROLL_OVERLAY') return '插入 B-roll'
  return String(type)
}

function hasSubtitleOperation(plan: EditPlan) {
  return plan.operations.some((operation) => ['UPDATE_SUBTITLE', 'CREATE_SUBTITLE'].includes(operation.type))
}

function formatTime(ms: number) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function formatRange(range: { start_ms: number; end_ms: number }) {
  return `${formatTime(range.start_ms)} - ${formatTime(range.end_ms)}`
}

export function AgentPanel({
  projectId,
  videoType,
  assets,
  timeline
}: {
  projectId: string
  videoType: VideoType
  assets: Asset[]
  timeline: Timeline | undefined
}) {
  const [input, setInput] = useState('')
  const [reply, setReply] = useState('')
  const [trace, setTrace] = useState<AgentTraceStep[]>([])
  const [plan, setPlan] = useState<EditPlan | null>(null)
  const [decisions, setDecisions] = useState<Record<number, Decision>>({})
  const [notice, setNotice] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [sendError, setSendError] = useState('')
  const [statusMessage, setStatusMessage] = useState('')
  const [lastAppliedPlanId, setLastAppliedPlanId] = useState<string | null>(null)
  const [lastRenderedFiles, setLastRenderedFiles] = useState<string[]>([])
  const [awaitingClarification, setAwaitingClarification] = useState(false)
  const [renderAfterApply, setRenderAfterApply] = useState(true)
  const [lastRenderJob, setLastRenderJob] = useState<{ id: string; status: string } | null>(null)
  const processRef = useRef<HTMLDetailsElement>(null)
  const queryClient = useQueryClient()
  const setBottomTab = useEditorStore((state) => state.setBottomTab)
  const selection = useEditorStore((state) => state.highlightRange)
  const selectedAssetId = useEditorStore((state) => state.selectedAssetId)
  const selectedClipIds = useEditorStore((state) => state.selectedClipIds)
  const playheadMs = useEditorStore((state) => state.playheadMs)
  const setSelection = useEditorStore((state) => state.setHighlightRange)
  const selectAsset = useEditorStore((state) => state.selectAsset)
  const currentMode = getVideoMode(videoType)
  const videoAssets = assets.filter((asset) => asset.type === 'VIDEO' && asset.processing_status === 'COMPLETED')
  const selectedVideoAsset = videoAssets.find((asset) => asset.id === selectedAssetId)
  const mainTrack = timeline?.tracks.find((track) => track.type === 'VIDEO_MAIN' || track.id === 'video-main')
  const playheadClip = mainTrack?.clips?.find((clip) =>
    Number(clip.timeline_start_ms ?? 0) <= playheadMs && Number(clip.timeline_end_ms ?? 0) > playheadMs
  ) ?? mainTrack?.clips?.[0]
  const timelineVideoAsset = videoAssets.find((asset) => asset.id === playheadClip?.asset_id)
  const activeVideoAsset = selectedVideoAsset ?? timelineVideoAsset ?? videoAssets[0]

  useEffect(() => {
    if (!selectedAssetId && activeVideoAsset) selectAsset(activeVideoAsset.id)
  }, [activeVideoAsset, selectAsset, selectedAssetId])
  const history = useQuery({
    queryKey: ['agent-history', projectId],
    queryFn: () => api.agent.history(projectId),
    enabled: !!projectId
  })
  const renderJob = useQuery({
    queryKey: ['agent-render-job', lastRenderJob?.id],
    queryFn: () => api.render.job(lastRenderJob?.id ?? ''),
    enabled: Boolean(lastRenderJob?.id),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'RUNNING' || status === 'PENDING' ? 1500 : false
    }
  })
  const renderQuality = renderJob.data?.output?.quality_report as Record<string, unknown> | undefined
  const renderIssues = Array.isArray(renderQuality?.issues)
    ? renderQuality.issues as Array<Record<string, unknown>>
    : []

  useEffect(() => {
    const job = renderJob.data
    if (!job || !lastRenderJob || job.status === lastRenderJob.status) return
    setLastRenderJob({ id: job.id, status: job.status })
    if (job.status === 'COMPLETED') {
      const score = typeof renderQuality?.score === 'number' ? `${renderQuality.score} 分` : '未评分'
      setNotice(`预览渲染完成，质量自评 ${score}，${renderQuality?.passed ? '已通过' : '建议复查'}。`)
      void queryClient.invalidateQueries({ queryKey: ['agent-history', projectId] })
    } else if (job.status === 'FAILED' || job.status === 'CANCELLED') {
      setSendError(job.error || `预览任务${job.status === 'FAILED' ? '失败' : '已取消'}`)
      void queryClient.invalidateQueries({ queryKey: ['agent-history', projectId] })
    }
  }, [lastRenderJob, projectId, queryClient, renderJob.data, renderQuality])

  const changeMode = useMutation({
    mutationFn: (nextVideoType: VideoType) => api.projects.update(projectId, { video_type: nextVideoType }),
    onSuccess: async (nextProject) => {
      const nextMode = getVideoMode(nextProject.video_type)
      setReply('')
      setTrace([])
      setPlan(null)
      setDecisions({})
      setLastRenderedFiles([])
      setAwaitingClarification(false)
      setNotice(`已切换到${nextMode.label}多 Agent 模式。`)
      await queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
    onError: (error) => {
      setSendError(error instanceof Error ? error.message : '切换创作模式失败')
    }
  })

  const approve = useMutation({
    mutationFn: () => {
      if (!plan) throw new Error('No plan')
      const approved_indices = plan.operations
        .map((_, index) => index)
        .filter((index) => decisions[index] !== 'rejected')
      const rejected_indices = plan.operations
        .map((_, index) => index)
        .filter((index) => decisions[index] === 'rejected')
      return api.agent.approve(plan.id, { approved_indices, rejected_indices, render_after_apply: renderAfterApply })
    },
    onMutate: () => {
      setSendError('')
      setNotice('正在应用到时间线，完成后会刷新预览和字幕轨。')
    },
    onSuccess: async (response) => {
      const files = plan?.rendered_files ?? []
      const renderText = response.render_job_id
        ? `预览任务 ${response.render_status ?? 'RUNNING'}`
        : renderAfterApply ? `预览任务未创建：${response.render_status ?? '未知原因'}` : '未启动预览渲染'
      setNotice(`已应用 ${response.applied_count} 条到时间线，拒绝 ${response.rejected_count} 条；${renderText}。`)
      setLastRenderedFiles(files)
      setLastRenderJob(response.render_job_id ? { id: response.render_job_id, status: response.render_status ?? 'RUNNING' } : null)
      setLastAppliedPlanId(plan?.id ?? null)
      if (plan && hasSubtitleOperation(plan)) {
        setBottomTab('script')
      }
      setPlan(null)
      await queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['subtitles', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['agent-history', projectId] })
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : '应用失败'
      setSendError(message)
    }
  })

  const reject = useMutation({
    mutationFn: () => {
      if (!plan) throw new Error('No plan')
      return api.agent.reject(plan.id)
    },
    onSuccess: async () => {
      setNotice('已拒绝整份计划，时间线未修改；本次选择已用于更新偏好。')
      setPlan(null)
      setDecisions({})
      await queryClient.invalidateQueries({ queryKey: ['agent-history', projectId] })
    },
    onError: (error) => setSendError(error instanceof Error ? error.message : '拒绝计划失败')
  })

  const undo = useMutation({
    mutationFn: () => {
      if (!lastAppliedPlanId) throw new Error('没有可撤回的 Agent 操作')
      return api.agent.undo(lastAppliedPlanId)
    },
    onSuccess: async (response) => {
      setNotice(`已撤回上一次 Agent 操作，当前时间线版本 v${response.timeline_version}`)
      setLastAppliedPlanId(null)
      await queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['subtitles', projectId] })
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : '撤回失败'
      setSendError(message)
    }
  })

  const submitAgentMessage = async (
    requestedContent?: string,
    requestedSelection?: { start_ms: number; end_ms: number },
    requestedAssetId?: string
  ) => {
    const content = typeof requestedContent === 'string' ? requestedContent.trim() : input.trim()
    if (!content || isSending) return
    setNotice('')
    setSendError('')
    setStatusMessage('')
    setLastRenderedFiles([])
    setAwaitingClarification(false)
    if (!projectId) {
      setTrace([
        {
          title: '项目未就绪',
          detail: '当前页面没有可用的 projectId，无法发送 Agent 请求。'
        }
      ])
      return
    }
    setInput('')
    if (processRef.current) processRef.current.open = false
    setIsSending(true)
    setStatusMessage('Agent 正在启动')
    setReply('')
    setPlan(null)
    setDecisions({})
    setTrace([
      {
        title: '提交剪辑目标',
        detail: `正在把指令发送给${currentMode.label}创作团队：${content}`
      }
    ])
    let receivedPlan = false
    let receivedPreview = false
    const activeSelection = requestedSelection ?? selection
    try {
      await api.agent.stream(projectId, content, {
        onThinking: (event) => {
          setStatusMessage(String(event.detail ?? 'Agent 正在思考'))
          setTrace((current) => [
            ...current,
            {
              title: 'Agent 开始思考',
              detail: String(event.detail ?? `${currentMode.director}正在选择工具和专业 Agent。`),
              data: event
            }
          ])
        },
        onStatus: (event) => {
          setStatusMessage(String(event.detail ?? 'Agent 正在工作，任务仍在进行中。'))
        },
        onToolCall: (event) => {
          const toolName = String(event.tool ?? '工具')
          setStatusMessage(`正在调用 ${toolName}`)
          setTrace((current) => [
            ...current,
            {
              title: '调用工具',
              detail: String(event.detail ?? `Agent 正在调用 ${toolName}`),
              data: event
            }
          ])
        },
        onProgress: (event) => {
          setStatusMessage(String(event.detail ?? '工具任务正在进行中'))
        },
        onPreviewReady: (event) => {
          receivedPreview = true
          const path = String(event.path ?? '')
          if (path) {
            setLastRenderedFiles((current) => Array.from(new Set([...current, path])))
          }
          setStatusMessage('预览文件已生成')
          setTrace((current) => [
            ...current,
            {
              title: '预览就绪',
              detail: String(event.detail ?? 'Agent 已生成一个可检查的预览文件。'),
              data: event
            }
          ])
        },
        onTrace: (step) => {
          setStatusMessage(step.title)
          setTrace((current) => [...current, step])
        },
        onPlan: (nextPlan) => {
          receivedPlan = true
          setStatusMessage('已生成待审批计划，尚未应用到时间线')
          setPlan(nextPlan)
          setDecisions({})
        },
        onToken: (content) => {
          setReply((current) => current + content)
        },
        onDone: (event) => {
          setAwaitingClarification(event.awaiting_user)
          if (!receivedPlan) {
            setNotice(
              event.awaiting_user
                ? 'Agent 尚未开始剪辑，正在等待你补充需求。'
                : receivedPreview
                ? 'Agent 已生成可检查的预览文件；这次没有生成需要应用到时间线的操作。'
                : 'Agent 已完成，但没有生成可应用计划。'
            )
          }
          setStatusMessage('')
          setIsSending(false)
          void queryClient.invalidateQueries({ queryKey: ['agent-history', projectId] })
        },
        onError: (message) => {
          setStatusMessage('')
          setSendError(message)
          setTrace((current) => [
            ...current,
            {
              title: 'Agent 请求失败',
              detail: message
            }
          ])
        }
      }, activeSelection ? {
        ...activeSelection,
        asset_id: requestedAssetId ?? selectedAssetId ?? undefined,
        clip_ids: selectedClipIds.length ? selectedClipIds : undefined
      } : undefined)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Agent 请求失败'
      setStatusMessage('')
      setSendError(message)
      setTrace((current) => [
        ...current,
        {
          title: 'Agent 请求失败',
          detail: message
        }
      ])
    } finally {
      setIsSending(false)
    }
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    submitAgentMessage()
  }

  const analysisRange = () => {
    if (selection) return selection
    const duration = Math.max(1, activeVideoAsset?.duration_ms ?? timeline?.duration_ms ?? 0)
    const boundedPlayhead = Math.min(Math.max(0, playheadMs), duration)
    const startMs = boundedPlayhead >= duration ? Math.max(0, duration - 30000) : boundedPlayhead
    return {
      start_ms: startMs,
      end_ms: Math.min(duration, Math.max(startMs + 1000, startMs + 30000))
    }
  }

  const runRangeAnalysis = (request: string) => {
    const range = analysisRange()
    setSelection(range)
    void submitAgentMessage(request, range, activeVideoAsset?.id)
  }

  const runSmartRoughCut = () => {
    if (!activeVideoAsset?.duration_ms) {
      setSendError('没有可用于智能粗剪的已完成视频素材。')
      return
    }
    const range = selection ?? { start_ms: 0, end_ms: activeVideoAsset.duration_ms }
    setSelection(range)
    void submitAgentMessage(
      `对素材 ${activeVideoAsset.original_name} 的 ${formatRange(range)} 范围，基于真实画面、音频、转写和当前偏好，生成可审批的智能粗剪计划。`,
      range,
      activeVideoAsset.id
    )
  }

  return (
    <aside className="panel agent-panel">
      <div className="panel-title">
        <h2>{currentMode.label} Agent</h2>
        <Bot size={18} />
      </div>
      <div className="agent-mode-switch video-mode-switch" aria-label="创作模式">
        {VIDEO_MODE_OPTIONS.map(({ value, label, Icon }) => (
          <button
            type="button"
            className={videoType === value ? 'video-mode-option active' : 'video-mode-option'}
            key={value}
            onClick={() => changeMode.mutate(value)}
            disabled={isSending || changeMode.isPending}
            title={`切换到${label}模式`}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>
      <div className="agent-source-control">
        <label htmlFor="agent-source-select"><Video size={14} />分析素材</label>
        <select
          id="agent-source-select"
          value={activeVideoAsset?.id ?? ''}
          onChange={(event) => {
            selectAsset(event.target.value || null)
            setSelection(null)
          }}
          disabled={isSending || !videoAssets.length}
        >
          {!videoAssets.length ? <option value="">没有可用视频</option> : null}
          {videoAssets.map((asset) => (
            <option value={asset.id} key={asset.id}>
              {asset.original_name} · {formatTime(asset.duration_ms ?? 0)}
            </option>
          ))}
        </select>
        <div className="agent-source-range">
          <span>分析范围</span>
          <b>{selection ? formatRange(selection) : `全片 00:00 - ${formatTime(activeVideoAsset?.duration_ms ?? 0)}`}</b>
        </div>
      </div>
      <div className="agent-quick-actions" aria-label="智能操作">
        <button
          type="button"
          onClick={runSmartRoughCut}
          disabled={isSending || !activeVideoAsset}
          title={activeVideoAsset ? `粗剪 ${activeVideoAsset.original_name}` : '没有可用视频'}
        >
          <WandSparkles size={14} />智能粗剪
        </button>
        <button
          type="button"
          onClick={() => runRangeAnalysis('检查指定范围的真实画面、构图、连续性和关键剪点，只分析不修改。')}
          disabled={isSending}
          title={selection ? '检查当前框选范围' : '未框选时检查播放位置后最多 30 秒'}
        >
          <ScanSearch size={14} />画面检查
        </button>
        <button
          type="button"
          onClick={() => runRangeAnalysis('听取指定范围的语音、音乐、噪声和节拍，推荐安全剪点，只分析不修改。')}
          disabled={isSending}
          title={selection ? '分析当前框选范围' : '未框选时分析播放位置后最多 30 秒'}
        >
          <AudioLines size={14} />音频分析
        </button>
        <button
          type="button"
          onClick={() => runRangeAnalysis('综合分析指定范围，给出画面、声音、语义和节奏的剪辑建议，只分析不修改。')}
          disabled={isSending}
          title={selection ? '分析当前框选范围' : '未框选时分析播放位置后最多 30 秒'}
        >
          <Sparkles size={14} />框选建议
        </button>
      </div>
      <div className="agent-log">
        {isSending ? (
          <div className="agent-status">
            <Loader2 className="spin" size={15} />
            <span>{statusMessage || 'Agent 正在工作，任务仍在进行中。'}</span>
          </div>
        ) : null}
        {reply ? (
          <section
            className={awaitingClarification ? 'agent-result clarification' : 'agent-result'}
            aria-label={awaitingClarification ? '需要你确认' : '本轮结论'}
          >
            <div className="agent-result-header">
              {awaitingClarification ? <CircleHelp size={15} /> : <Sparkles size={15} />}
              <span>{awaitingClarification ? '需要你确认' : '本轮结论'}</span>
            </div>
            <p>{reply}</p>
          </section>
        ) : null}
        {notice ? <p className="success-text">{notice}</p> : null}
        {lastRenderJob ? (
          <div className="agent-render-status">
            <div>
              <span>预览任务 {lastRenderJob.id.slice(0, 8)}</span>
              <b>{renderJob.data?.status ?? lastRenderJob.status}</b>
            </div>
            <progress value={renderJob.data?.progress ?? 0} max={1} />
            {renderQuality ? (
              <p className={renderQuality.passed ? 'success-text' : 'pending-text'}>
                质量自评：{typeof renderQuality.score === 'number' ? `${renderQuality.score} 分` : '未评分'}
                {renderIssues[0]?.detail ? ` · ${String(renderIssues[0].detail)}` : ''}
              </p>
            ) : null}
          </div>
        ) : null}
        {lastRenderedFiles.length ? (
          <div className="rendered-files compact-files">
            {lastRenderedFiles.map((file) => (
              <code key={file}>{file}</code>
            ))}
          </div>
        ) : null}
        {lastAppliedPlanId ? (
          <button className="inline-action" onClick={() => undo.mutate()} disabled={undo.isPending}>
            <RotateCcw size={14} />
            撤回上一次 Agent 操作
          </button>
        ) : null}
        {sendError ? <p className="error-text">{sendError}</p> : null}
        {history.data?.length ? (
          <details className="agent-history">
            <summary><History size={14} />会话历史 <span>{history.data.length}</span></summary>
            <div>
              {history.data.slice(-12).map((item) => (
                <article key={item.id} className={`history-${item.role}`}>
                  <b>{item.role === 'user' ? '你' : item.role === 'assistant' ? 'Agent' : '系统'}</b>
                  <p>{item.content}</p>
                </article>
              ))}
            </div>
          </details>
        ) : null}
      </div>
      {trace.length ? (
        <details className="agent-process" ref={processRef}>
          <summary>
            <span className="process-summary-main">
              {isSending ? <Loader2 className="spin" size={14} /> : <CircleDot size={14} />}
              <b>执行过程</b>
            </span>
            <span>{isSending ? '进行中' : `${trace.length} 项`}</span>
            <ChevronDown className="process-chevron" size={15} />
          </summary>
          <div className="agent-trace">
            {trace.map((step, index) => (
              <article className="trace-step" key={`${step.title}-${index}`}>
                <CircleDot size={13} />
                <div>
                  <b>{step.title}</b>
                  <p>{step.detail}</p>
                  {step.data && Object.keys(step.data).length ? (
                    <details className="trace-data">
                      <summary>数据</summary>
                      <code>{JSON.stringify(step.data)}</code>
                    </details>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </details>
      ) : null}
      {plan ? (
        <div className="agent-plan">
          <div className="plan-toolbar">
            <div>
              <b>待审批计划</b>
              <span>{plan.operations.length} 条操作，{plan.rendered_files?.length ?? 0} 个 FFmpeg 文件</span>
            </div>
            <button className="wide-button" onClick={() => approve.mutate()} disabled={approve.isPending}>
              {approve.isPending ? <Loader2 className="spin" size={15} /> : <Check size={15} />}
              应用到时间线
            </button>
          </div>
          <div className="plan-controls">
            <label>
              <input type="checkbox" checked={renderAfterApply} onChange={(event) => setRenderAfterApply(event.target.checked)} />
              应用后渲染预览
            </label>
            <button className="danger-ghost-button" onClick={() => reject.mutate()} disabled={reject.isPending || approve.isPending}>
              {reject.isPending ? <Loader2 className="spin" size={14} /> : <Ban size={14} />}
              整单拒绝
            </button>
          </div>
          <p className="pending-text">
            点击应用会创建新的时间线版本；开启渲染时会立即启动后台预览任务。
          </p>
          <p className="plan-summary">{plan.summary}</p>
          {plan.rendered_files?.length ? (
            <div className="rendered-files">
              {plan.rendered_files.map((file) => (
                <code key={file}>{file}</code>
              ))}
            </div>
          ) : null}
          <div className="plan-list">
            {plan.operations.map((operation, index) => (
              <article className="operation-card" key={index}>
                <div>
                  <b>{index + 1}. {operationTitle(operation)}</b>
                  <details className="operation-data">
                    <summary>参数</summary>
                    <code>{JSON.stringify(operation)}</code>
                  </details>
                </div>
                <div className="decision-buttons">
                  <button
                    className={decisions[index] === 'approved' ? 'decision active' : 'decision'}
                    onClick={() => setDecisions((current) => ({ ...current, [index]: 'approved' }))}
                  >
                    <Check size={15} />
                  </button>
                  <button
                    className={decisions[index] === 'rejected' ? 'decision reject active' : 'decision reject'}
                    onClick={() => setDecisions((current) => ({ ...current, [index]: 'rejected' }))}
                  >
                    <X size={15} />
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>
      ) : null}
      {!isSending ? (
        <form className="agent-input" onSubmit={onSubmit}>
          {selection ? (
            <div className="agent-selection-context">
              <span>{activeVideoAsset?.original_name ?? '当前素材'} · {formatRange(selection)}</span>
              <button type="button" onClick={() => setSelection(null)} title="清除时间段选择" aria-label="清除时间段选择">
                <X size={14} />
              </button>
            </div>
          ) : null}
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="用自然语言告诉 Agent 想怎么剪"
          />
          <button type="button" onClick={() => void submitAgentMessage()} disabled={!input.trim()}>
            <Send size={17} />
          </button>
        </form>
      ) : null}
    </aside>
  )
}
