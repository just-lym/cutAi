import { Link } from 'react-router-dom'
import { ArrowLeft, Sparkles } from 'lucide-react'

export function DemoEditor() {
  return (
    <main className="editor-shell">
      <header className="editor-header">
        <Link className="icon-button" to="/">
          <ArrowLeft size={18} />
        </Link>
        <div>
          <strong>离线演示项目</strong>
          <span>无需后端即可预览布局</span>
        </div>
      </header>
      <section className="editor-grid">
        <aside className="panel">
          <h2>素材</h2>
          {['主视频.mp4', '城市 B-roll.mp4', '背景音乐.wav'].map((item) => (
            <div className="asset-row" key={item}>
              <span>{item}</span>
              <small>COMPLETED</small>
            </div>
          ))}
        </aside>
        <section className="preview-panel">
          <div className="demo-preview">
            <Sparkles size={42} />
            <strong>AI Cut Preview</strong>
            <span>字幕、B-roll 和播放头会在真实项目中联动</span>
          </div>
        </section>
        <aside className="panel">
          <h2>Agent</h2>
          <p className="muted">我会删除静音、修正字幕，并建议插入一段 B-roll。</p>
        </aside>
      </section>
      <section className="timeline-panel">
        <div className="track"><span>视频主轨</span><b style={{ width: '68%' }} /></div>
        <div className="track"><span>B-roll</span><b style={{ width: '24%', marginLeft: '32%' }} /></div>
        <div className="track"><span>字幕</span><b style={{ width: '80%' }} /></div>
      </section>
    </main>
  )
}
