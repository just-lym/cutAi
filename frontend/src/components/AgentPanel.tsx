import { FormEvent, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bot, Check, ChevronDown, CircleDot, CircleHelp, Loader2, RotateCcw, Send, Sparkles, X } from 'lucide-react'
import { api, type AgentTraceStep, type EditPlan } from '../api/client'
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
  if (type === 'UPDATE_SUBTITLE') return '修正字幕'
  if (type === 'CREATE_SUBTITLE') return '新增字幕'
  if (type === 'DELETE_SUBTITLE') return '删除字幕'
  if (type === 'ADD_MARKER') return '添加标记'
  if (type === 'INSERT_BROLL_OVERLAY') return '插入 B-roll'
  return String(type)
}

function hasSubtitleOperation(plan: EditPlan) {
  return plan.operations.some((operation) => ['UPDATE_SUBTITLE', 'CREATE_SUBTITLE'].includes(operation.type))
}

export function AgentPanel({ projectId, videoType }: { projectId: string; videoType: VideoType }) {
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
  const processRef = useRef<HTMLDetailsElement>(null)
  const queryClient = useQueryClient()
  const setBottomTab = useEditorStore((state) => state.setBottomTab)
  const currentMode = getVideoMode(videoType)

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
      return api.agent.approve(plan.id, { approved_indices, rejected_indices })
    },
    onMutate: () => {
      setSendError('')
      setNotice('正在应用到时间线，完成后会刷新预览和字幕轨。')
    },
    onSuccess: async (response) => {
      const files = plan?.rendered_files ?? []
      setNotice(
        files.length
          ? `已应用 ${response.applied_count} 条到时间线，拒绝 ${response.rejected_count} 条；FFmpeg 已生成 ${files.length} 个视频文件。`
          : `已应用 ${response.applied_count} 条到时间线，拒绝 ${response.rejected_count} 条；这一步不会重新合成视频。`
      )
      setLastRenderedFiles(files)
      setLastAppliedPlanId(plan?.id ?? null)
      if (plan && hasSubtitleOperation(plan)) {
        setBottomTab('script')
      }
      setPlan(null)
      await queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['subtitles', projectId] })
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : '应用失败'
      setSendError(message)
    }
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

  const submitAgentMessage = async () => {
    const content = input.trim()
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
      })
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
          <p className="pending-text">
            点击应用会创建新的时间线版本，并让预览/字幕轨刷新；FFmpeg 文件如果已生成，会在下方显示路径。
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
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="用自然语言告诉 Agent 想怎么剪"
          />
          <button type="button" onClick={submitAgentMessage} disabled={!input.trim()}>
            <Send size={17} />
          </button>
        </form>
      ) : null}
    </aside>
  )
}
