import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { Clapperboard, FolderPlus, PlayCircle, Trash2 } from 'lucide-react'
import { api, type Project } from '../api/client'
import { getVideoMode, VIDEO_MODE_OPTIONS, type VideoType } from '../constants/videoModes'

export function ProjectList() {
  const [name, setName] = useState('')
  const [videoType, setVideoType] = useState<VideoType>('TALKING_HEAD')
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects.list })
  const createProject = useMutation({
    mutationFn: api.projects.create,
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${project.id}`)
    }
  })
  const deleteProject = useMutation({
    mutationFn: api.projects.remove,
    onSuccess: async () => {
      setDeleteTarget(null)
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
    }
  })

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    createProject.mutate({ name: name.trim() || '未命名项目', video_type: videoType })
  }

  return (
    <main className="project-shell">
      <header className="topbar">
        <div className="brand">
          <Clapperboard size={26} />
          <span>AICut</span>
        </div>
        <Link className="ghost-button" to="/demo">
          <PlayCircle size={18} />
          体验演示
        </Link>
      </header>

      <section className="project-create">
        <form onSubmit={onSubmit}>
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="项目名称" />
          <button type="submit" disabled={createProject.isPending}>
            <FolderPlus size={18} />
            新建项目
          </button>
          <div className="project-mode-heading">
            <strong>视频类型</strong>
            <span>决定新项目使用哪一位主导演 Agent，进入编辑器后仍可切换</span>
          </div>
          <div className="video-mode-switch" aria-label="视频类型">
            {VIDEO_MODE_OPTIONS.map(({ value, label, description, Icon }) => (
              <button
                type="button"
                className={videoType === value ? 'video-mode-option active' : 'video-mode-option'}
                key={value}
                onClick={() => setVideoType(value)}
              >
                <Icon size={15} />
                <span className="project-mode-copy">
                  <strong>{label}</strong>
                  <small>{description}</small>
                </span>
              </button>
            ))}
          </div>
        </form>
        {projects.error ? <p className="error-text">后端暂未响应，可以先进入演示页。</p> : null}
        {deleteProject.error ? (
          <p className="error-text">{deleteProject.error instanceof Error ? deleteProject.error.message : '删除项目失败'}</p>
        ) : null}
      </section>

      <section className="project-grid">
        {projects.data?.map((project) => (
          <article className="project-card" key={project.id}>
            <Link className="project-card-link" to={`/projects/${project.id}`}>
              <div className="project-thumb">
                {project.width}x{project.height}
              </div>
              <div className="project-card-body">
                <strong>{project.name}</strong>
                <span>
                  {getVideoMode(project.video_type).label} · v{project.current_timeline_version} · {Math.round(project.duration_ms / 1000)}s · {project.status}
                </span>
              </div>
            </Link>
            <button
              className="project-delete-button"
              type="button"
              title={`删除项目：${project.name}`}
              aria-label={`删除项目：${project.name}`}
              disabled={deleteProject.isPending && deleteProject.variables === project.id}
              onClick={() => setDeleteTarget(project)}
            >
              <Trash2 size={16} />
            </button>
          </article>
        ))}
      </section>
      {deleteTarget ? (
        <div className="dialog-backdrop" role="presentation" onClick={() => setDeleteTarget(null)}>
          <section
            className="confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-project-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="confirm-dialog-title">
              <Trash2 size={18} />
              <h2 id="delete-project-title">删除项目</h2>
            </div>
            <p>
              确认永久删除“{deleteTarget.name}”？项目、素材、时间线历史和项目内生成文件都会被物理删除，无法恢复。
            </p>
            <div className="confirm-dialog-actions">
              <button type="button" className="ghost-button" onClick={() => setDeleteTarget(null)}>
                取消
              </button>
              <button
                type="button"
                className="danger-ghost-button"
                disabled={deleteProject.isPending}
                onClick={() => deleteProject.mutate(deleteTarget.id)}
              >
                <Trash2 size={15} />
                {deleteProject.isPending ? '正在删除' : '确认删除'}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  )
}
