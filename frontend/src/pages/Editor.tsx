import { useCallback, useEffect } from 'react'
import { useQueries, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Download, Loader2, Save } from 'lucide-react'
import { api } from '../api/client'
import { AgentPanel } from '../components/AgentPanel'
import { AssetPanel } from '../components/AssetPanel'
import { PreviewPanel } from '../components/PreviewPanel'
import { ScriptView } from '../components/ScriptView'
import { Timeline } from '../components/Timeline'
import { useHotkeys } from '../hooks/useHotkeys'
import { useWebSocket } from '../hooks/useWebSocket'
import { useEditorStore } from '../stores/editor'

export function Editor() {
  const { projectId = '' } = useParams()
  const queryClient = useQueryClient()
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

  const onSocketEvent = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
    void queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
    void queryClient.invalidateQueries({ queryKey: ['subtitles', projectId] })
  }, [projectId, queryClient])

  useWebSocket(projectId, onSocketEvent)

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
          <button className="ghost-button" onClick={() => api.render.preview(projectId)}>
            <Save size={17} />
            预览任务
          </button>
          <button className="ghost-button" onClick={() => api.render.exports(projectId)}>
            <Download size={17} />
            导出任务
          </button>
        </div>
      </header>

      <section className="editor-grid">
        <AssetPanel projectId={projectId} assets={assets.data ?? []} />
        <PreviewPanel timeline={timeline.data?.timeline_json} assets={assets.data ?? []} />
        <AgentPanel projectId={projectId} />
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
