export type Project = {
  id: string
  owner_id: string
  name: string
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
}

export type AgentRunResponse = {
  session_id: string
  reply: string
  edit_plan: EditPlan | null
  awaiting_user: boolean
  total_cost: number
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

export const api = {
  projects: {
    list: () => request<Project[]>('/projects'),
    create: (data: { name: string; width?: number; height?: number; frame_rate?: number }) =>
      request<Project>('/projects', { method: 'POST', body: JSON.stringify(data) }),
    get: (id: string) => request<Project>(`/projects/${id}`)
  },
  assets: {
    list: (projectId: string) => request<Asset[]>(`/projects/${projectId}/assets`),
    upload: async (projectId: string, file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return request<Asset>(`/projects/${projectId}/assets/upload`, { method: 'POST', body: fd })
    }
  },
  timeline: {
    get: (projectId: string) => request<TimelineVersion>(`/projects/${projectId}/timeline`),
    commit: (projectId: string, operations: EditOperation[]) =>
      request<TimelineVersion>(`/projects/${projectId}/timeline/commit`, {
        method: 'POST',
        body: JSON.stringify({ operations })
      })
  },
  subtitles: {
    list: (projectId: string) => request<SubtitleCue[]>(`/projects/${projectId}/subtitles`),
    update: (projectId: string, cueId: string, data: Partial<SubtitleCue>) =>
      request(`/projects/${projectId}/subtitles/${cueId}`, {
        method: 'PUT',
        body: JSON.stringify(data)
      }),
    remove: (projectId: string, cueId: string) =>
      request(`/projects/${projectId}/subtitles/${cueId}`, { method: 'DELETE' })
  },
  broll: {
    analyze: (projectId: string) =>
      request<{ positions: Record<string, unknown>[] }>(`/projects/${projectId}/broll/analyze`, {
        method: 'POST',
        body: '{}'
      }),
    searchLibrary: (projectId: string, query: string, limit = 6) =>
      request<{ candidates: Record<string, unknown>[] }>(`/projects/${projectId}/broll/search-library`, {
        method: 'POST',
        body: JSON.stringify({ query, limit })
      }),
    select: (projectId: string, assetId: string, positionMs: number, durationMs: number) =>
      request<{ ok: boolean; operation: EditOperation }>(`/projects/${projectId}/broll/select`, {
        method: 'POST',
        body: JSON.stringify({ asset_id: assetId, position_ms: positionMs, duration_ms: durationMs })
      })
  },
  agent: {
    send: (projectId: string, content: string) =>
      request<AgentRunResponse>(`/projects/${projectId}/agent/messages`, {
        method: 'POST',
        body: JSON.stringify({ content })
      }),
    approve: (planId: string, payload?: ApprovalPayload) =>
      request<ApprovalResponse>(`/agent/runs/${planId}/approve`, {
        method: 'POST',
        body: JSON.stringify(payload ?? {})
      }),
    reject: (planId: string) => request(`/agent/runs/${planId}/reject`, { method: 'POST' })
  },
  render: {
    preview: (projectId: string) => request(`/projects/${projectId}/previews`, { method: 'POST' }),
    exports: (projectId: string) => request(`/projects/${projectId}/exports`, { method: 'POST' })
  },
  usage: {
    summary: () => request<UsageSummary>('/usage/summary')
  }
}
