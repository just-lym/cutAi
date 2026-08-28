import { FormEvent, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bot, Check, Send, X } from 'lucide-react'
import { api, type EditPlan } from '../api/client'

type Decision = 'approved' | 'rejected'

function operationTitle(operation: Record<string, unknown>) {
  const type = operation.type
  if (type === 'DELETE_RANGE') return '删除静音'
  if (type === 'SET_VOLUME') return '调整音量'
  if (type === 'UPDATE_SUBTITLE') return '修正字幕'
  if (type === 'INSERT_BROLL_OVERLAY') return '插入 B-roll'
  return String(type)
}

export function AgentPanel({ projectId }: { projectId: string }) {
  const [input, setInput] = useState('帮我删除静音并调整音量')
  const [reply, setReply] = useState('')
  const [plan, setPlan] = useState<EditPlan | null>(null)
  const [decisions, setDecisions] = useState<Record<number, Decision>>({})
  const [notice, setNotice] = useState('')
  const queryClient = useQueryClient()

  const send = useMutation({
    mutationFn: (content: string) => api.agent.send(projectId, content),
    onSuccess: (response) => {
      setReply(response.reply)
      setPlan(response.edit_plan)
      setDecisions({})
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
    onSuccess: async (response) => {
      setNotice(`已应用 ${response.applied_count} 条，拒绝 ${response.rejected_count} 条`)
      setPlan(null)
      await queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['subtitles', projectId] })
    }
  })

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (!input.trim()) return
    setNotice('')
    send.mutate(input)
  }

  return (
    <aside className="panel agent-panel">
      <div className="panel-title">
        <h2>Agent</h2>
        <Bot size={18} />
      </div>
      <div className="agent-log">
        <p className="muted">{reply || '输入剪辑目标，Agent 会生成可审批的结构化编辑计划。'}</p>
        {notice ? <p className="success-text">{notice}</p> : null}
        {send.error ? <p className="error-text">{send.error.message}</p> : null}
      </div>
      {plan ? (
        <div className="plan-list">
          <strong>{plan.summary}</strong>
          {plan.operations.map((operation, index) => (
            <article className="operation-card" key={index}>
              <div>
                <b>{operationTitle(operation)}</b>
                <code>{JSON.stringify(operation)}</code>
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
          <button className="wide-button" onClick={() => approve.mutate()} disabled={approve.isPending}>
            提交决策
          </button>
        </div>
      ) : null}
      <form className="agent-input" onSubmit={onSubmit}>
        <textarea value={input} onChange={(event) => setInput(event.target.value)} />
        <button type="submit" disabled={send.isPending}>
          <Send size={17} />
        </button>
      </form>
    </aside>
  )
}
