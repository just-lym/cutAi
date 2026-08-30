import type { VideoType } from '../constants/videoModes'

export type Project = {
  id: string
  owner_id: string
  name: string
  video_type: VideoType
  width: number
  height: number
  frame_rate: number
  duration_ms: number
  current_timeline_version: number
  status: string
}

export type Asset = {
  id: string
  project_id: string
  type: string
  source_type: string
  original_name: string
  file_path: string
  proxy_path: string | null
  mime_type: string
  duration_ms: number | null
  width: number | null
  height: number | null
  frame_rate: number | null
  checksum: string | null
  processing_status: string
  processing_step: string | null
  processing_error: string | null
}

export type Clip = {
  id: string
  asset_id?: string
  timeline_start_ms?: number
  timeline_end_ms?: number
  source_in_ms?: number
  source_out_ms?: number
  volume?: number
  transform?: Record<string, unknown>
  effects?: Record<string, unknown>[]
}

export type SubtitleCue = {
  id: string
  start_ms: number
  end_ms: number
  text: string
  speaker: string | null
  confidence: number | null
  style: Record<string, unknown> | null
}

export type TimelineTrack = {
  id: string
  type: string
  name: string
  clips?: Clip[]
  cues?: SubtitleCue[]
  effects?: Record<string, unknown>[]
}

export type Timeline = {
  duration_ms: number
  width: number
  height: number
  frame_rate: number
  tracks: TimelineTrack[]
  volume_changes: Record<string, unknown>[]
}

export type TimelineVersion = {
  id: string
  project_id: string
  version: number
  parent_version_id: string | null
  timeline_json: Timeline
  change_summary: string | null
  created_by: string
}

export type EditOperation = {
  type: string
  [key: string]: unknown
}

export type EditPlan = {
  id: string
  summary: string
  operations: EditOperation[]
  conflicts: string[]
  requires_user_approval: boolean
  rendered_files?: string[]
}

export type TimelineCommitPayload = {
  operations: EditOperation[]
  change_summary?: string
}

export type AgentTraceStep = {
  title: string
  detail: string
  data?: Record<string, unknown>
}

export type ApprovalPayload = {
  approved_indices?: number[]
  rejected_indices?: number[]
}

export type ApprovalResponse = {
  ok: boolean
  applied_count: number
  rejected_count: number
  plan_status: string
  timeline_version: number | null
}

export type UsageSummary = {
  total_cost: number
  input_tokens: number
  output_tokens: number
  audio_ms: number
  monthly_budget: number
  budget_remaining: number
}

export type Job = {
  id: string
  project_id: string
  asset_id: string | null
  type: string
  status: string
  progress: number
  step: string | null
  error: string | null
  output: Record<string, unknown> | null
}

export type RenderOptions = {
  width?: number
  height?: number
  frame_rate?: number
  output_path?: string
}

export type RenderPathResponse = {
  path: string | null
}

export type AgentStreamDone = {
  session_id: string
  total_cost: number
  video_type: VideoType
  coordinator: string
  team: string[]
}

export type AgentStreamHandlers = {
  onThinking?: (event: Record<string, unknown>) => void
  onStatus?: (event: Record<string, unknown>) => void
  onToolCall?: (event: Record<string, unknown>) => void
  onProgress?: (event: Record<string, unknown>) => void
  onPreviewReady?: (event: Record<string, unknown>) => void
  onTrace?: (step: AgentTraceStep) => void
  onPlan?: (plan: EditPlan) => void
  onToken?: (content: string) => void
  onDone?: (event: AgentStreamDone) => void
  onError?: (message: string) => void
}

const BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const isForm = options?.body instanceof FormData
  const res = await fetch(`${BASE}${path}`, {
    headers: isForm ? undefined : { 'Content-Type': 'application/json' },
    ...options
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json() as Promise<T>
}

function dispatchAgentEvent(
  rawEvent: string,
  handlers: AgentStreamHandlers
) {
  const lines = rawEvent.split(/\r?\n/)
  let eventName = 'message'
  const dataLines: string[] = []
  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
  }
  const rawData = dataLines.join('\n')
  const data = rawData ? JSON.parse(rawData) : {}
  if (eventName === 'thinking') {
    handlers.onThinking?.(data)
  } else if (eventName === 'status') {
    handlers.onStatus?.(data)
  } else if (eventName === 'tool_call') {
    handlers.onToolCall?.(data)
  } else if (eventName === 'progress') {
    handlers.onProgress?.(data)
  } else if (eventName === 'preview_ready') {
    handlers.onPreviewReady?.(data)
  } else if (eventName === 'trace') {
    handlers.onTrace?.(data as AgentTraceStep)
  } else if (eventName === 'plan') {
    handlers.onPlan?.(data as EditPlan)
  } else if (eventName === 'token') {
    handlers.onToken?.(String(data.content ?? ''))
  } else if (eventName === 'done') {
    handlers.onDone?.(data as AgentStreamDone)
  } else if (eventName === 'error') {
    handlers.onError?.(String(data.message ?? 'Agent 流式请求失败'))
  }
}

async function streamAgentMessage(projectId: string, content: string, handlers: AgentStreamHandlers) {
  const res = await fetch(`${BASE}/projects/${projectId}/agent/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  if (!res.body) {
    throw new Error('当前浏览器不支持流式响应')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (value) {
      buffer += decoder.decode(value, { stream: !done })
      const parts = buffer.split(/\r?\n\r?\n/)
      buffer = parts.pop() ?? ''
      for (const part of parts) {
        if (part.trim()) dispatchAgentEvent(part, handlers)
      }
    }
    if (done) break
  }
  if (buffer.trim()) dispatchAgentEvent(buffer, handlers)
}

export const api = {
  projects: {
    list: () => request<Project[]>('/projects'),
    create: (data: { name: string; video_type: VideoType; width?: number; height?: number; frame_rate?: number }) =>
      request<Project>('/projects', { method: 'POST', body: JSON.stringify(data) }),
    get: (id: string) => request<Project>(`/projects/${id}`),
    update: (id: string, data: { video_type: VideoType }) =>
      request<Project>(`/projects/${id}`, { method: 'PATCH', body: JSON.stringify(data) })
  },
  assets: {
    list: (projectId: string) => request<Asset[]>(`/projects/${projectId}/assets`),
    upload: async (projectId: string, file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return request<Asset>(`/projects/${projectId}/assets/upload`, { method: 'POST', body: fd })
    },
    reprocess: (assetId: string) => request<Asset>(`/assets/${assetId}/reprocess`, { method: 'POST' }),
    remove: (assetId: string) => request<{ ok: boolean }>(`/assets/${assetId}`, { method: 'DELETE' }),
    fileUrl: (assetId: string) => `${BASE}/assets/${assetId}/file`,
    proxyUrl: (assetId: string) => `${BASE}/assets/${assetId}/proxy`
  },
  timeline: {
    get: (projectId: string) => request<TimelineVersion>(`/projects/${projectId}/timeline`),
    commit: (projectId: string, payload: TimelineCommitPayload) =>
      request<TimelineVersion>(`/projects/${projectId}/timeline/commit`, {
        method: 'POST',
        body: JSON.stringify(payload)
      })
  },
  subtitles: {
    update: (projectId: string, cueId: string, data: Partial<SubtitleCue>) =>
      request(`/projects/${projectId}/subtitles/${cueId}`, {
        method: 'PUT',
        body: JSON.stringify(data)
      }),
    remove: (projectId: string, cueId: string) =>
      request(`/projects/${projectId}/subtitles/${cueId}`, { method: 'DELETE' })
  },
  agent: {
    stream: streamAgentMessage,
    approve: (planId: string, payload?: ApprovalPayload) =>
      request<ApprovalResponse>(`/agent/runs/${planId}/approve`, {
        method: 'POST',
        body: JSON.stringify(payload ?? {})
      }),
    undo: (planId: string) =>
      request<{ ok: boolean; timeline_version: number; plan_status: string }>(`/agent/runs/${planId}/undo`, {
        method: 'POST'
      })
  },
  render: {
    chooseSavePath: (defaultName: string) =>
      request<RenderPathResponse>('/render/save-path', {
        method: 'POST',
        body: JSON.stringify({ default_name: defaultName })
      }),
    preview: (projectId: string, options?: RenderOptions) =>
      request<Job>(`/projects/${projectId}/previews`, {
        method: 'POST',
        body: JSON.stringify(options ?? {})
      }),
    exports: (projectId: string, options?: RenderOptions) =>
      request<Job>(`/projects/${projectId}/exports`, {
        method: 'POST',
        body: JSON.stringify(options ?? {})
      }),
    job: (jobId: string) => request<Job>(`/jobs/${jobId}`),
    cancel: (jobId: string) => request<{ ok: boolean; status: string; stopped_process?: boolean }>(
      `/jobs/${jobId}/cancel`,
      { method: 'POST' }
    )
  },
  usage: {
    summary: () => request<UsageSummary>('/usage/summary')
  }
}
