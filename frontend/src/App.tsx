import { useState, useEffect, useRef } from 'react'
import './App.css'

const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:8000'
  : window.location.origin;

interface LogMessage {
  author: string
  message: string
  tool_calls?: string[]
}

interface Panel {
  filename: string
  description: string
  narration?: string
  dialogue?: string
}

function App() {
  const [theme, setTheme] = useState('')
  const [genre, setGenre] = useState('Cyberpunk Noir')
  const [status, setStatus] = useState<'idle' | 'running' | 'completed' | 'error'>('idle')
  const [activeStep, setActiveStep] = useState(-1)
  const [logs, setLogs] = useState<LogMessage[]>([])
  const [activeTab, setActiveTab] = useState<'console' | 'genesis' | 'canvas' | 'plot' | 'outline' | 'comic'>('console')
  const [errorMsg, setErrorMsg] = useState('')

  // Artifact contents
  const [artifacts, setArtifacts] = useState<Record<string, string>>({
    genesis: '',
    canvas: '',
    plot: '',
    outline: ''
  })
  const [panels, setPanels] = useState<Panel[]>([])
  // Per-run artifacts subfolder, so concurrent/previous stories don't collide.
  const [runId, setRunId] = useState('')
  const runIdRef = useRef('')

  const logsEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll logs
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  // Helper to fetch artifacts
  const fetchArtifacts = async () => {
    const files = [
      { key: 'genesis', name: 'genesis.md' },
      { key: 'canvas', name: 'canvas.md' },
      { key: 'plot', name: 'plot.md' },
      { key: 'outline', name: 'outline.md' }
    ]

    // Read this run's artifacts from its per-run subfolder (if we have a run_id yet).
    const rid = runIdRef.current
    const prefix = rid ? `${rid}/` : ''

    const loadedArtifacts: Record<string, string> = {}
    for (const file of files) {
      try {
        // Cache-bust so freshly regenerated artifacts are never served stale from cache
        const res = await fetch(`${API_BASE}/artifacts/${prefix}${file.name}?_=${Date.now()}`, { cache: 'no-store' })
        if (res.ok) {
          loadedArtifacts[file.key] = await res.text()
        } else {
          loadedArtifacts[file.key] = `*Artifact [${file.name}] is still in production.*`
        }
      } catch (err) {
        loadedArtifacts[file.key] = `*Unable to fetch [${file.name}].*`
      }
    }
    setArtifacts(prev => ({ ...prev, ...loadedArtifacts }))

    // Load panels if available
    try {
      const res = await fetch(`${API_BASE}/artifacts/${prefix}comic_production.json?_=${Date.now()}`, { cache: 'no-store' })
      if (res.ok) {
        const prodData = await res.json()
        if (prodData && Array.isArray(prodData.panels)) {
          setPanels(prodData.panels)
        }
      }
    } catch (e) {
      console.error("Error fetching comic_production.json:", e)
    }
  }

  // Poll for artifacts when running
  useEffect(() => {
    let interval: any
    if (status === 'running') {
      interval = setInterval(() => {
        fetchArtifacts()
      }, 5000) // Poll every 5s
    }
    return () => clearInterval(interval)
  }, [status])

  const handleStartGeneration = () => {
    if (!theme.trim()) return

    setStatus('running')
    setActiveStep(0)
    setLogs([])
    setErrorMsg('')
    setPanels([])
    setRunId('')
    runIdRef.current = ''
    setArtifacts({
      genesis: '',
      canvas: '',
      plot: '',
      outline: ''
    })
    setActiveTab('console')

    const fullPrompt = `${theme} (Genre: ${genre})`
    const eventSource = new EventSource(`${API_BASE}/api/story_stream?theme=${encodeURIComponent(fullPrompt)}`)

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        
        if (data.event === 'run_started') {
          // Capture the per-run artifacts subfolder so we fetch the right run's files.
          runIdRef.current = data.run_id
          setRunId(data.run_id)
        } else if (data.event === 'start') {
          setLogs(prev => [...prev, { author: 'System', message: data.message }])
        } else if (data.event === 'agent_message') {
          const author = data.author || 'Agent'
          const message = data.message || ''
          const tool_calls = data.tool_calls || []

          setLogs(prev => [...prev, { author, message, tool_calls }])

          // Dynamic step checking based on text matches
          const lowerMsg = message.toLowerCase()
          if (lowerMsg.includes('genesis') || lowerMsg.includes('character concepts')) {
            setActiveStep(0)
          } else if (lowerMsg.includes('canvas') || lowerMsg.includes('illustrator_remote') || lowerMsg.includes('appearance')) {
            setActiveStep(1)
          } else if (lowerMsg.includes('plot') || lowerMsg.includes('twists') || lowerMsg.includes('breaking the story')) {
            setActiveStep(2)
          } else if (lowerMsg.includes('outline') || lowerMsg.includes('outline_writer_remote')) {
            setActiveStep(3)
          } else if (lowerMsg.includes('production') || lowerMsg.includes('generate_panel_image') || lowerMsg.includes('final panel')) {
            setActiveStep(4)
          }
        } else if (data.event === 'complete') {
          setLogs(prev => [...prev, { author: 'System', message: data.message }])
          setStatus('completed')
          setActiveStep(5)
          eventSource.close()
          fetchArtifacts()
        } else if (data.event === 'error') {
          setErrorMsg(data.message)
          setStatus('error')
          eventSource.close()
        }
      } catch (err) {
        console.error('Error parsing SSE event:', err)
      }
    }

    eventSource.onerror = (err) => {
      console.error('SSE Error:', err)
      setErrorMsg('Lost connection to story generator backend.')
      setStatus('error')
      eventSource.close()
    }
  }

  // Simple Markdown to HTML converter
  const renderMarkdown = (md: string) => {
    if (!md) return <p style={{ color: '#6b7280', fontStyle: 'italic' }}>Generating document...</p>
    
    const lines = md.split('\n')
    return lines.map((line, i) => {
      const trimmed = line.trim()
      if (trimmed.startsWith('# ')) {
        return <h1 key={i}>{trimmed.replace('# ', '')}</h1>
      }
      if (trimmed.startsWith('## ')) {
        return <h2 key={i}>{trimmed.replace('## ', '')}</h2>
      }
      if (trimmed.startsWith('### ')) {
        return <h3 key={i}>{trimmed.replace('### ', '')}</h3>
      }
      if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
        return <li key={i}>{trimmed.substring(2)}</li>
      }
      if (trimmed.startsWith('> ')) {
        return <blockquote key={i}>{trimmed.replace('> ', '')}</blockquote>
      }
      if (trimmed === '') {
        return <br key={i} />
      }
      return <p key={i}>{trimmed}</p>
    })
  }

  const steps = [
    { label: 'Genesis', desc: 'Core Character & World genesis' },
    { label: 'Room & Canvas', desc: 'Arc expansion & Illustrator research' },
    { label: 'Breaking Story', desc: 'Plot debate, twists, & end definition' },
    { label: 'Master Outline', desc: 'Page/panel and dialogues layout' },
    { label: 'Production', desc: 'Continuity review & panel illustration' }
  ]

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="logo-section">
          <h1>ADK Story Genesis Portal</h1>
          <p>Collaborative multi-agent storyboard engine powered by the A2A protocol</p>
        </div>
        <div className="header-status">
          {status === 'running' && (
            <span className="tool-badge" style={{ background: 'rgba(99, 102, 241, 0.2)', color: '#818cf8' }}>
              <span className="loading-spinner" style={{ width: '12px', height: '12px', marginRight: '6px' }}></span>
              Agents Constructing Story...
            </span>
          )}
          {status === 'completed' && (
            <span className="tool-badge" style={{ background: 'rgba(16, 185, 129, 0.2)', color: '#34d399' }}>
              ✓ Storyboard Complete
            </span>
          )}
          {status === 'error' && (
            <span className="tool-badge" style={{ background: 'rgba(239, 68, 68, 0.2)', color: '#f87171' }}>
              ⚠ Production Error
            </span>
          )}
        </div>
      </header>

      {/* Progress Pipeline */}
      <div className="pipeline-container">
        {steps.map((step, idx) => {
          const isCompleted = idx < activeStep || activeStep === 5
          const isActive = idx === activeStep
          return (
            <div key={idx} className={`pipeline-step ${isActive ? 'active' : ''} ${isCompleted ? 'completed' : ''}`}>
              <div className="step-number">
                {isCompleted ? '✓' : idx + 1}
              </div>
              <div className="step-label-wrapper">
                <div className="step-label">{step.label}</div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Dashboard Grid */}
      <div className="dashboard-grid">
        {/* Left Side Control Panel */}
        <aside className="control-panel">
          <h2 className="section-title">Control Deck</h2>
          
          <div className="input-group">
            <label htmlFor="theme-input">Story Theme / Concept</label>
            <textarea
              id="theme-input"
              rows={5}
              placeholder="Describe your story idea here... (e.g. 'A rogue AI escapes onto the internet and builds its own physical avatar using smart appliances')"
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
              disabled={status === 'running'}
            />
          </div>

          <div className="input-group">
            <label htmlFor="genre-select">Genre / Visual Style</label>
            <select
              id="genre-select"
              value={genre}
              onChange={(e) => setGenre(e.target.value)}
              disabled={status === 'running'}
            >
              <option value="Cyberpunk Noir">Cyberpunk Noir</option>
              <option value="Epic Fantasy">Epic Fantasy</option>
              <option value="Retro Sci-Fi">Retro Sci-Fi</option>
              <option value="Mystery Thriller">Mystery Thriller</option>
              <option value="Supernatural Horror">Supernatural Horror</option>
            </select>
          </div>

          <button
            className="generate-btn"
            onClick={handleStartGeneration}
            disabled={status === 'running' || !theme.trim()}
          >
            {status === 'running' ? (
              <>
                <span className="loading-spinner"></span>
                Generating...
              </>
            ) : (
              'Generate Storyboard'
            )}
          </button>

          {errorMsg && (
            <div style={{ color: '#f87171', fontSize: '0.85rem', marginTop: '10px' }}>
              <strong>Error:</strong> {errorMsg}
            </div>
          )}
        </aside>

        {/* Right Side Workspace Panels */}
        <main className="workspace-panels">
          {/* Top Panel: Agent thought logger */}
          <section className="console-logger">
            <div className="panel-header">
              <h3>Agent Communication Feed</h3>
              <span className="tool-badge" style={{ background: '#1e293b' }}>
                {logs.length} events logged
              </span>
            </div>
            <div className="agent-stream">
              {logs.length === 0 ? (
                <div style={{ color: '#4b5563', textAlign: 'center', marginTop: '40px', fontStyle: 'italic' }}>
                  Input a theme and click Generate to activate the agent council...
                </div>
              ) : (
                logs.map((log, idx) => {
                  const authorClass = log.author.toLowerCase().replace(/_remote/g, '').replace(/\s+/g, '-');
                  return (
                    <div key={idx} className={`stream-message ${authorClass}`}>
                      <div className="message-meta">
                        <span className="meta-author">
                          <span className="author-dot"></span>
                          {log.author}
                        </span>
                      </div>
                      <div className="message-text">{log.message}</div>
                      {log.tool_calls && log.tool_calls.length > 0 && (
                        <div className="tool-badge">
                          ⚙ Running Tool: {log.tool_calls.join(', ')}
                        </div>
                      )}
                    </div>
                  )
                })
              )}
              <div ref={logsEndRef} />
            </div>
          </section>

          {/* Bottom Panel: Artifacts & Comic Panels */}
          <section className="artifacts-workspace">
            <div className="tabs-bar">
              <button
                className={`tab-btn ${activeTab === 'console' ? 'active' : ''}`}
                onClick={() => setActiveTab('console')}
              >
                Agent Chat
              </button>
              <button
                className={`tab-btn ${activeTab === 'genesis' ? 'active' : ''}`}
                onClick={() => setActiveTab('genesis')}
              >
                1. Genesis
              </button>
              <button
                className={`tab-btn ${activeTab === 'canvas' ? 'active' : ''}`}
                onClick={() => setActiveTab('canvas')}
              >
                2. Room & Canvas
              </button>
              <button
                className={`tab-btn ${activeTab === 'plot' ? 'active' : ''}`}
                onClick={() => setActiveTab('plot')}
              >
                3. Story Plot
              </button>
              <button
                className={`tab-btn ${activeTab === 'outline' ? 'active' : ''}`}
                onClick={() => setActiveTab('outline')}
              >
                4. Outline Script
              </button>
              <button
                className={`tab-btn ${activeTab === 'comic' ? 'active' : ''}`}
                onClick={() => setActiveTab('comic')}
              >
                5. Comic Panels
              </button>
            </div>

            <div className="tab-content">
              {activeTab === 'console' && (
                <div className="markdown-body">
                  <h2>Active Live Log</h2>
                  <p>Check out the communication stream above to monitor what the Head Writer, the Council of Agents, the Illustrator, and the Outline Writer are debating and researching in real-time.</p>
                </div>
              )}

              {activeTab === 'genesis' && (
                <div className="markdown-body">
                  {renderMarkdown(artifacts.genesis)}
                </div>
              )}

              {activeTab === 'canvas' && (
                <div className="markdown-body">
                  {renderMarkdown(artifacts.canvas)}
                </div>
              )}

              {activeTab === 'plot' && (
                <div className="markdown-body">
                  {renderMarkdown(artifacts.plot)}
                </div>
              )}

              {activeTab === 'outline' && (
                <div className="markdown-body">
                  {renderMarkdown(artifacts.outline)}
                </div>
              )}

              {activeTab === 'comic' && (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                    <h2 style={{ margin: 0 }}>Generated Comic Panels</h2>
                    {panels.length > 0 && (
                      <a
                        href={`${API_BASE}/api/comic_pdf${runId ? `?run_id=${runId}` : ''}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="tool-badge"
                        style={{ background: 'rgba(16, 185, 129, 0.2)', color: '#34d399', textDecoration: 'none', padding: '8px 14px', borderRadius: '8px', fontWeight: 600 }}
                      >
                        ⬇ Download PDF
                      </a>
                    )}
                  </div>
                  {panels.length === 0 ? (
                    <p style={{ color: '#6b7280', fontStyle: 'italic' }}>Comic panels are generated in Step 5 (Scripting & Production). Please run a story theme to view panels.</p>
                  ) : (
                    <div className="comic-grid">
                      {panels.map((panel, idx) => {
                        const getImageUrl = (filename: string) => {
                          if (!filename) return '';
                          if (filename.startsWith('http://') || filename.startsWith('https://')) return filename;
                          if (filename.startsWith('/artifacts/')) return `${API_BASE}${filename}`;
                          if (filename.startsWith('artifacts/')) return `${API_BASE}/${filename}`;
                          const prefix = runId ? `${runId}/` : '';
                          return `${API_BASE}/artifacts/${prefix}${filename}`;
                        };
                        return (
                          <div key={idx} className="panel-card">
                            <div className="panel-img-wrapper">
                              {/* Fetch image dynamically from FastAPI server static files */}
                              <img
                                src={getImageUrl(panel.filename)}
                                alt={`Panel ${idx + 1}`}
                                onError={(e) => {
                                  // Fallback if image not generated yet
                                  (e.target as HTMLImageElement).style.display = 'none';
                                }}
                              />
                            <div className="panel-no-image">Panel Image</div>
                          </div>
                          <div className="panel-info">
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                              <span className="panel-title-badge">Panel {idx + 1}</span>
                            </div>
                            {(panel.narration || panel.dialogue) && (
                              <div className="caption-box" style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: '6px', padding: '10px 14px', fontSize: '0.95rem', color: '#e2e8f0', lineHeight: 1.5 }}>
                                {panel.narration && <div>{panel.narration}</div>}
                                {panel.dialogue && (
                                  <div style={{ marginTop: panel.narration ? '6px' : 0, fontStyle: 'italic', color: '#a5b4fc' }}>
                                    “{panel.dialogue}”
                                  </div>
                                )}
                              </div>
                            )}
                            </div>
                          </div>
                        )})}
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
        </main>
      </div>
    </div>
  )
}

export default App
