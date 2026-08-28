import { Route, Routes } from 'react-router-dom'
import { DemoEditor } from './pages/DemoEditor'
import { Editor } from './pages/Editor'
import { ProjectList } from './pages/ProjectList'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ProjectList />} />
      <Route path="/demo" element={<DemoEditor />} />
      <Route path="/projects/:projectId" element={<Editor />} />
    </Routes>
  )
}
