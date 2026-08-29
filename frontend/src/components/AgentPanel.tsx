import { FormEvent, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bot, Check, CircleDot, Loader2, RotateCcw, Send, X } from 'lucide-react'
import { api, type AgentTraceStep, type EditPlan } from '../api/client'
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

export function AgentPanel({ projectId }: { projectId: string }) {
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
  const queryClient = useQueryClient()
  const setBottomTab = useEditorStore((state) => state.setBottomTab)

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
    if (!projectId) {
      setTrace([
        {
          title: '项目未就绪',
          detail: '当前页面没有可用的 projectId，无法发送 Agent 请求。'
        }
      ])
      return
    }
    setIsSending(true)
    setStatusMessage('Agent 正在启动')
    setReply('')
    setPlan(null)
    setDecisions({})
    setTrace([
      {
        title: '提交剪辑目标',
        detail: `正在把指令发送给 Agent：${content}`
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
              detail: String(event.detail ?? '主 Agent 正在选择工具和专业 Agent。'),
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
        onDone: () => {
          if (!receivedPlan) {
            setNotice(
              receivedPreview
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
        <h2>Agent</h2>
        <Bot size={18} />
      </div>
      <div className="agent-log">
        {isSending ? (
          <div className="agent-status">
            <Loader2 className="spin" size={15} />
            <span>{statusMessage || 'Agent 正在工作，任务仍在进行中。'}</span>
          </div>
        ) : null}
        <p className="muted">{reply || '输入剪辑目标，Agent 会生成可审批的结构化编辑计划。'}</p>
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
      <div className="agent-trace">
        <div className="section-label">执行过程</div>
        {trace.length ? (
          trace.map((step, index) => (
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
          ))
        ) : (
          <p className="muted compact">等待发送指令。</p>
        )}
      </div>
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
      <form className="agent-input" onSubmit={onSubmit}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="用自然语言告诉 Agent 想怎么剪"
        />
        <button type="button" onClick={submitAgentMessage} disabled={isSending || !input.trim()}>
          <Send size={17} />
        </button>
      </form>
    </aside>
  )
}
