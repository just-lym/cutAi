import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { Clapperboard, FolderPlus, PlayCircle } from 'lucide-react'
import { api } from '../api/client'

export function ProjectList() {
  const [name, setName] = useState('我的剪辑项目')
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

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    createProject.mutate({ name })
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
          <input value={name} onChange={(event) => setName(event.target.value)} />
          <button type="submit" disabled={createProject.isPending || !name.trim()}>
            <FolderPlus size={18} />
            新建项目
          </button>
        </form>
        {projects.error ? <p className="error-text">后端暂未响应，可以先进入演示页。</p> : null}
      </section>

      <section className="project-grid">
        {projects.data?.map((project) => (
          <Link className="project-card" key={project.id} to={`/projects/${project.id}`}>
            <div className="project-thumb">
              {project.width}x{project.height}
            </div>
            <div>
              <strong>{project.name}</strong>
              <span>
                v{project.current_timeline_version} · {Math.round(project.duration_ms / 1000)}s · {project.status}
              </span>
            </div>
          </Link>
        ))}
      </section>
    </main>
  )
}
