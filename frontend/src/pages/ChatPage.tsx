import { useRef, useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { chatApi, projectApi } from '@/services/api'
import { useAppStore } from '@/store/appStore'
import { useSession, useProjects, useOllamaConnections, useQueryDatabases } from '@/hooks'
import { Icon } from '@/components/ui/Icon'
import { SqlBlock } from '@/components/ui/SqlBlock'
import { QueryResultView } from '@/components/chat/QueryResult'
import type { GenerateResponse, Message, QueryResult } from '@/types'
import amrLogo from '@/assets/amr-logo.png'

const STATUS_FA: Record<string, string> = {
  DATA_GAP:              'این اطلاعات در سیستم موجود نیست یا هنوز تعریف نشده.',
  ACCESS_DENIED:         'دسترسی به این اطلاعات مجاز نیست.',
  OUT_OF_SCOPE:          'این سوال مرتبط با حوزه منابع انسانی نیست.',
  SQL_VALIDATION_FAILED: 'SQL تولید شده از نظر امنیتی تأیید نشد.',
  NEEDS_CLARIFICATION:   'لطفاً سوال را واضح‌تر بیان کنید.',
}

function getBlockedText(msg: Message, info?: GenerateResponse): string | null {
  if (!msg.error?.startsWith('BLOCKED:')) return null
  if (info?.message_fa) return info.message_fa
  const status = msg.error.replace('BLOCKED:', '')
  return STATUS_FA[status] ?? null
}

const ROUTE_STYLE: Record<string, { bg: string; text: string; border: string }> = {
  SQL:                 { bg: 'var(--accent-bg)',  text: 'var(--accent-text)',  border: 'var(--accent-border)' },
  GAP:                 { bg: 'var(--amber-bg)',   text: 'var(--amber)',        border: 'var(--amber-border)' },
  REJECT:              { bg: 'var(--red-bg)',     text: 'var(--red)',          border: 'var(--red-border)' },
  NEEDS_CLARIFICATION: { bg: 'var(--bg-raised)',  text: 'var(--text-3)',       border: 'var(--border-default)' },
}

const STATUS_LABEL: Record<string, string> = {
  DATA_GAP:       'Data Gap',
  ANALYTICAL_GAP: 'Analytical Gap',
  ACCESS_DENIED:  'Access Denied',
  OUT_OF_SCOPE:   'Out of Scope',
}

const DECISION_STYLE: Record<string, { color: string; bg: string; border: string }> = {
  rule:      { color: 'var(--text-3)',      bg: 'var(--bg-raised)',   border: 'var(--border-subtle)' },
  policy:    { color: 'var(--red)',         bg: 'var(--red-bg)',      border: 'var(--red-border)' },
  template:  { color: 'var(--accent-text)', bg: 'var(--accent-bg)',   border: 'var(--accent-border)' },
  llm:       { color: 'var(--amber)',       bg: 'var(--amber-bg)',    border: 'var(--amber-border)' },
  db:        { color: 'var(--text-2)',      bg: 'var(--bg-raised)',   border: 'var(--border-default)' },
  component: { color: 'var(--text-2)',      bg: 'var(--bg-raised)',   border: 'var(--border-default)' },
}

function traceStatusColor(status: string): string {
  const s = status.toLowerCase()
  if (s.includes('fail') || s.includes('error') || s.includes('invalid') || s.includes('denied') || s.includes('blocked'))
    return 'var(--red)'
  if (s === 'warning' || s === 'not_configured' || s === 'unknown')
    return 'var(--amber)'
  return 'var(--text-3)'
}

function sqlSourceLabel(source?: string | null): string | null {
  if (!source) return null
  if (source.includes('template')) return 'template'
  if (source.includes('generator') || source.includes('llm')) return 'llm'
  return null
}

function MetaChip({ label }: { label: string }) {
  return (
    <span
      className="text-[10px] font-mono px-1.5 py-[3px] rounded-[4px]"
      style={{ background: 'var(--bg-raised)', color: 'var(--text-3)', border: '1px solid var(--border-subtle)' }}
    >
      {label}
    </span>
  )
}

type TraceStep = { step: string; status: string; duration_ms: number; details?: Record<string, unknown> }

function isComplex(v: unknown): boolean {
  if (v === null || v === undefined) return false
  if (Array.isArray(v)) return v.length > 0
  if (typeof v === 'object') return Object.keys(v as object).length > 0
  return false
}

function TraceDetails({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details).filter(([k]) => k !== 'decision_by')
  if (entries.length === 0) return null

  const simple = entries.filter(([, v]) => !isComplex(v))
  const complex = entries.filter(([, v]) => isComplex(v))

  return (
    <div
      className="text-[10px] font-mono"
      style={{
        borderTop: '1px solid var(--border-subtle)',
        background: 'var(--bg-base)',
        borderLeft: '3px solid var(--accent-border)',
      }}
    >
      {/* simple key-value grid */}
      {simple.length > 0 && (
        <div
          className="grid px-3 py-2 gap-x-4 gap-y-[3px]"
          style={{ gridTemplateColumns: 'minmax(100px, max-content) 1fr' }}
        >
          {simple.map(([k, v]) => (
            <>
              <span key={`k-${k}`} style={{ color: 'var(--text-3)' }}>{k}</span>
              <span key={`v-${k}`} className="break-all" style={{ color: 'var(--text-2)' }}>
                {v === null || v === undefined ? '—' : String(v)}
              </span>
            </>
          ))}
        </div>
      )}

      {/* complex values — each in its own labeled block */}
      {complex.length > 0 && (
        <div
          className="flex flex-col gap-2 px-3 pb-2.5"
          style={{ borderTop: simple.length > 0 ? '1px solid var(--border-subtle)' : undefined, paddingTop: '8px' }}
        >
          {complex.map(([k, v]) => (
            <div key={k}>
              <div className="mb-0.5 font-semibold" style={{ color: 'var(--text-3)' }}>{k}</div>
              <pre
                className="px-2.5 py-2 rounded-[4px] text-[9.5px] overflow-x-auto leading-relaxed"
                style={{ background: 'var(--bg-raised)', color: 'var(--text-2)', border: '1px solid var(--border-subtle)' }}
              >
                {JSON.stringify(v, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function TracePanel({ traces }: { traces: TraceStep[] }) {
  const [expandedRow, setExpandedRow] = useState<number | null>(null)

  return (
    <div
      className="mt-1.5 rounded-[6px] overflow-hidden text-[10px] font-mono overflow-x-auto"
      style={{ border: '1px solid var(--border-subtle)', background: 'var(--bg-raised)' }}
    >
      <div className="grid" style={{ gridTemplateColumns: 'minmax(110px, 1.8fr) minmax(80px, 1fr) 44px 88px', gap: 0, minWidth: 320 }}>
        {/* header */}
        {(['step', 'status', 'ms', 'decision'] as const).map((h) => (
          <div key={h} className="px-2.5 py-1.5 font-semibold uppercase tracking-wide text-[9px]"
            style={{ color: 'var(--text-3)', borderBottom: '1px solid var(--border-subtle)' }}>
            {h}
          </div>
        ))}
        {/* rows */}
        {traces.map((t, i) => {
          const isLast = i === traces.length - 1
          const isExpanded = expandedRow === i
          const hasDetails = t.details && Object.keys(t.details).filter((k) => k !== 'decision_by').length > 0
          const decision = (t.details?.decision_by as string | undefined) ?? '—'
          const ds = DECISION_STYLE[decision]
          const statusColor = traceStatusColor(t.status)
          const isErrorStatus = statusColor === 'var(--red)'
          const rowBorder = (!isLast || isExpanded) ? '1px solid var(--border-subtle)' : undefined
          return (
            <>
              <div
                key={`s-${i}`}
                className={hasDetails ? 'px-2.5 py-[5px] cursor-pointer hover:opacity-70' : 'px-2.5 py-[5px]'}
                style={{ color: 'var(--text-2)', borderBottom: rowBorder }}
                onClick={() => hasDetails && setExpandedRow(isExpanded ? null : i)}
              >
                {hasDetails && <span className="mr-1" style={{ color: 'var(--text-3)' }}>{isExpanded ? '▾' : '▸'}</span>}
                {t.step}
              </div>
              <div key={`st-${i}`} className="px-2.5 py-[5px]" style={{ borderBottom: rowBorder }}>
                <span style={{ color: statusColor, fontWeight: isErrorStatus ? 600 : undefined }}>{t.status}</span>
              </div>
              <div key={`ms-${i}`} className="px-2.5 py-[5px] tabular-nums text-right" style={{ color: 'var(--text-3)', borderBottom: rowBorder }}>{t.duration_ms.toFixed(1)}</div>
              <div key={`d-${i}`} className="px-2.5 py-[5px]" style={{ borderBottom: rowBorder }}>
                <span className="px-1.5 py-[2px] rounded-[3px] whitespace-nowrap"
                  style={{ color: ds?.color ?? 'var(--text-3)', background: ds?.bg ?? 'transparent', border: `1px solid ${ds?.border ?? 'var(--border-subtle)'}` }}>
                  {decision}
                </span>
              </div>
              {isExpanded && t.details && (
                <div key={`det-${i}`} className="col-span-4" style={{ borderBottom: isLast ? undefined : '1px solid var(--border-subtle)' }}>
                  <TraceDetails details={t.details} />
                </div>
              )}
            </>
          )
        })}
      </div>
    </div>
  )
}

function PipelineBadges({ info }: { info: GenerateResponse }) {
  const [open, setOpen] = useState(false)
  const route = info.route ?? ''
  if (!['SQL', 'GAP', 'REJECT'].includes(route)) return null
  const rs = ROUTE_STYLE[route]
  const statusLabel = info.status ? STATUS_LABEL[info.status] : null
  const srcLabel = route === 'SQL' ? sqlSourceLabel(info.source) : null
  const templateId = route === 'SQL' && info.template_id ? info.template_id : null
  const modelLabel = route === 'SQL' && srcLabel === 'llm' && info.model_called ? info.model_called : null
  const rowsLabel = route === 'SQL'
    ? (info.executed ? `${info.row_count ?? 0} rows` : 'not run')
    : null
  const traces = (info.traces ?? []) as TraceStep[]
  const hasTraces = traces.length > 0

  return (
    <div className="ml-8 sm:ml-10" style={{ marginTop: '-2px' }}>
      <div className="flex items-center gap-1.5 flex-wrap">
        <span
          className="text-[10px] font-mono font-medium px-1.5 py-[3px] rounded-[4px]"
          style={{ background: rs.bg, color: rs.text, border: `1px solid ${rs.border}` }}
        >
          {info.route}
        </span>
        {statusLabel && <MetaChip label={statusLabel} />}
        {route === 'GAP' && info.detected_intent && <MetaChip label={info.detected_intent} />}
        {srcLabel && <MetaChip label={srcLabel} />}
        {modelLabel && <MetaChip label={modelLabel} />}
        {templateId && (
          <span
            className="text-[10px] font-mono truncate max-w-[120px] sm:max-w-[200px] px-1.5 py-[3px] rounded-[4px]"
            style={{ background: 'var(--bg-base)', color: 'var(--text-2)', border: '1px dashed var(--border-default)', fontStyle: 'italic' }}
            title={templateId}
          >
            {templateId}
          </span>
        )}
        {rowsLabel && <MetaChip label={rowsLabel} />}
        {hasTraces && (
          <button
            onClick={() => setOpen((v) => !v)}
            className="ml-0.5 text-[10px] font-mono select-none transition-colors"
            style={{
              color: open ? 'var(--accent-text)' : 'var(--text-3)',
              background: open ? 'var(--accent-bg)' : 'var(--bg-raised)',
              border: `1px solid ${open ? 'var(--accent-border)' : 'var(--border-default)'}`,
              borderRadius: '4px', padding: '2px 6px',
            }}
          >
            {open ? '↑' : '↓'} trace
          </button>
        )}
      </div>
      {open && hasTraces && <TracePanel traces={traces} />}
    </div>
  )
}

function KpiCard({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  if (rows.length !== 1 || columns.length !== 1) return null
  const value = rows[0][0]
  const num = Number(value)
  if (isNaN(num) && typeof value !== 'string') return null
  return (
    <div className="inline-flex flex-col items-start rounded-[12px] px-5 py-4 min-w-[160px]" style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)' }}>
      <span className="text-[10px] font-medium uppercase tracking-[.8px] mb-1" style={{ color: 'var(--text-3)' }}>{columns[0]}</span>
      <span className="text-3xl font-semibold tabular-nums" style={{ color: 'var(--text-1)' }}>
        {isNaN(num) ? String(value) : num.toLocaleString('fa-IR')}
      </span>
    </div>
  )
}

export function ChatPage({ onOpenSidebar }: { onOpenSidebar?: () => void }) {
  const { activeSessionId, setActivePage } = useAppStore()
  const { data: session, isLoading } = useSession(activeSessionId)
  const { data: projects } = useProjects()
  const { data: ollamaConns } = useOllamaConnections()
  const { data: queryDbs } = useQueryDatabases()
  const qc = useQueryClient()

  const ollamaActive = ollamaConns?.some((c) => c.is_active) ?? true
  const dbActive = queryDbs?.some((d) => d.is_active) ?? true
  const hasWarning = !ollamaActive || !dbActive

  const project = projects?.find((p) => p.id === session?.project_id)
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)
  const [inputFocused, setInputFocused] = useState(false)
  const [queryResults, setQueryResults] = useState<Record<string, QueryResult>>({})
  const [pipelineInfo, setPipelineInfo] = useState<Record<string, GenerateResponse>>(() => {
    try {
      const raw = localStorage.getItem('bi-pipeline-cache')
      return raw ? (JSON.parse(raw) as Record<string, GenerateResponse>) : {}
    } catch {
      return {}
    }
  })
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [feedback, setFeedback] = useState<Record<string, boolean | null>>({})
  const bodyRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: 'smooth' })
  }, [session?.messages, sending])

  async function handleSend() {
    const q = question.trim()
    if (!q || sending || !session || hasWarning) return
    setQuestion('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    setSending(true)

    try {
      const userSession = await chatApi.addMessage(session.id, { role: 'user', content: q })
      qc.setQueryData(['session', session.id], userSession)

      if (userSession.title === 'New chat') {
        const updated = await chatApi.updateSession(session.id, { title: q.slice(0, 60) })
        qc.invalidateQueries({ queryKey: ['sessions'] })
        qc.setQueryData(['session', session.id], { ...updated, messages: userSession.messages })
      }

      let result: GenerateResponse
      try {
        result = await chatApi.generate(q, session.project_id, session.model_name)
      } catch (err) {
        const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        const errSession = await chatApi.addMessage(session.id, {
          role: 'assistant', content: '', sql: null,
          error: detail ?? 'Could not generate a response.',
        })
        qc.setQueryData(['session', session.id], errSession)
        return
      }

      const isBlocked = !result.success && !!STATUS_FA[result.status ?? '']

      const aiSession = await chatApi.addMessage(session.id, {
        role: 'assistant', content: '',
        sql: result.success ? result.sql : null,
        error: isBlocked ? `BLOCKED:${result.status}` : (result.error ?? null),
      })
      qc.setQueryData(['session', session.id], aiSession)

      const lastMsg = aiSession.messages[aiSession.messages.length - 1]
      if (lastMsg) {
        setPipelineInfo((prev) => {
          const next = { ...prev, [lastMsg.id]: result }
          try {
            const entries = Object.entries(next)
            const trimmed = Object.fromEntries(entries.slice(-500))
            localStorage.setItem('bi-pipeline-cache', JSON.stringify(trimmed))
          } catch { /* storage quota exceeded or unavailable */ }
          return next
        })
      }
    } finally {
      setSending(false)
    }
  }

  async function handleRunQuery(msg: Message) {
    if (!msg.sql || !session) return
    const userQuestion = [...(session.messages ?? [])].reverse()
      .find((m) => m.role === 'user' && new Date(m.created_at) < new Date(msg.created_at))?.content
    try {
      const result = await chatApi.runQuery(msg.sql, { session_id: session.id, question: userQuestion, project_id: session.project_id })
      setQueryResults((prev) => ({ ...prev, [msg.id]: result }))
      setTimeout(() => {
        document.getElementById(`result-${msg.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      }, 50)
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setQueryResults((prev) => ({
        ...prev,
        [msg.id]: { columns: [], rows: [], row_count: 0, elapsed_ms: 0, success: false, error: detail ?? 'Failed to execute query.' },
      }))
    }
  }

  async function handleFeedback(msgId: string, correct: boolean) {
    const experimentId = queryResults[msgId]?.experiment_id
    if (!experimentId) return
    setFeedback((prev) => ({ ...prev, [msgId]: correct }))
    try {
      await projectApi.setExperimentFeedback(experimentId, correct)
    } catch {
      setFeedback((prev) => ({ ...prev, [msgId]: null }))
    }
  }

  if (!activeSessionId) {
    return (
      <div className="flex flex-col flex-1 overflow-hidden">
        <div className="h-[52px] flex items-center px-3 flex-shrink-0 md:hidden" style={{ borderBottom: '1px solid var(--border-default)', background: 'var(--bg-surface)' }}>
          <button
            onClick={onOpenSidebar}
            className="w-8 h-8 flex items-center justify-center rounded-[8px]"
            style={{ color: 'var(--text-2)' }}
          >
            <Icon name="menu" size={16} />
          </button>
        </div>
        <div className="flex flex-col flex-1 items-center justify-center gap-4" style={{ color: 'var(--text-3)' }}>
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center" style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)' }}>
            <Icon name="message" size={28} />
          </div>
          <div className="text-center">
            <p className="text-sm font-medium" style={{ color: 'var(--text-2)' }}>No chat selected</p>
            <p className="text-xs mt-1">Create a new chat from the sidebar</p>
          </div>
        </div>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex flex-col flex-1 overflow-hidden">
        <div className="h-[52px] flex items-center px-3 flex-shrink-0 md:hidden" style={{ borderBottom: '1px solid var(--border-default)', background: 'var(--bg-surface)' }}>
          <button
            onClick={onOpenSidebar}
            className="w-8 h-8 flex items-center justify-center rounded-[8px]"
            style={{ color: 'var(--text-2)' }}
          >
            <Icon name="menu" size={16} />
          </button>
        </div>
        <div className="flex flex-1 items-center justify-center text-sm" style={{ color: 'var(--text-3)' }}>Loading…</div>
      </div>
    )
  }

  const messages = session?.messages ?? []

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Header */}
      <div className="h-[52px] flex items-center px-3 sm:px-6 gap-2 sm:gap-3 flex-shrink-0" style={{ borderBottom: '1px solid var(--border-default)', background: 'var(--bg-surface)' }}>
        <button
          onClick={onOpenSidebar}
          className="md:hidden w-8 h-8 flex items-center justify-center rounded-[8px] flex-shrink-0 transition-colors"
          style={{ color: 'var(--text-2)' }}
        >
          <Icon name="menu" size={16} />
        </button>
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-medium truncate" style={{ color: 'var(--text-1)' }}>{session?.title ?? 'Chat'}</p>
        </div>
        {project && (
          <span className="text-[11px] px-2.5 py-1 rounded-full font-medium flex-shrink-0 hidden sm:inline-block" style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }}>
            {project.name}
          </span>
        )}
        <span className="text-[11px] hidden sm:block flex-shrink-0" style={{ color: 'var(--text-3)' }}>{session?.model_name?.split(':')[0]}</span>
      </div>

      {/* Messages */}
      <div ref={bodyRef} className="flex-1 overflow-y-auto px-3 py-4 sm:px-6 sm:py-6 flex flex-col gap-3">
        {messages.map((msg) => {
          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="flex justify-end">
                <div
                  className="max-w-[85%] sm:max-w-[65%] px-4 py-2.5 rounded-[18px_18px_4px_18px] text-[13px] leading-[1.6]"
                  style={{ background: 'var(--accent)', color: '#fff', direction: 'rtl', textAlign: 'right' }}
                >
                  {msg.content}
                </div>
              </div>
            )
          }

          const info = pipelineInfo[msg.id]
          const blockedText = getBlockedText(msg, info)

          return (
            <div key={msg.id} className="flex flex-col gap-2">
              <div className="flex gap-3 items-start">
                {/* AI avatar */}
                <div className="w-7 h-7 rounded-[9px] flex items-center justify-center flex-shrink-0 mt-0.5 overflow-hidden"
                  style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)' }}>
                  <img src={amrLogo} alt="AI" className="w-[18px] h-[18px] object-contain" />
                </div>

                {blockedText ? (
                  <div
                    className="px-4 py-2.5 rounded-[4px_18px_18px_18px] text-[13px] leading-[1.6] max-w-[85%] sm:max-w-[65%]"
                    style={{ background: 'var(--bg-raised)', color: 'var(--text-2)', border: '1px solid var(--border-default)', direction: 'rtl', textAlign: 'right' }}
                  >
                    {blockedText}
                  </div>
                ) : msg.error && !msg.error.startsWith('BLOCKED:') ? (
                  <div className="text-[13px] pt-1" style={{ color: 'var(--text-3)' }}>{msg.error}</div>
                ) : msg.sql ? (
                  <div className="flex-1 min-w-0 max-w-[calc(100%-44px)]" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: '4px 12px 12px 12px', overflow: 'hidden' }}>
                    {/* SQL header */}
                    <div className="flex items-center gap-2 px-3 py-1.5" style={{ borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-raised)' }}>
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }}>SQL</span>
                      {info?.detected_intent && (
                        <span className="text-[10px] font-mono truncate max-w-[180px]" style={{ color: 'var(--text-3)' }}>{info.detected_intent}</span>
                      )}
                      <button
                        onClick={() => navigator.clipboard.writeText(msg.sql ?? '')}
                        className="ml-auto flex items-center gap-1 text-[11px] transition-opacity hover:opacity-70"
                        style={{ color: 'var(--text-3)' }}
                      >
                        <Icon name="copy" size={12} /> Copy
                      </button>
                    </div>
                    <SqlBlock code={msg.sql ?? ''} />
                    {!queryResults[msg.id] && !dismissed.has(msg.id) && (
                      <div className="flex gap-2 px-3 py-2" style={{ borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-raised)' }}>
                        <button
                          onClick={() => handleRunQuery(msg)}
                          className="flex items-center gap-1.5 px-3 py-1 rounded-[6px] text-[11px] font-medium transition-opacity hover:opacity-80"
                          style={{ background: 'var(--green-bg)', color: 'var(--green)', border: '1px solid var(--green-border)' }}
                        >
                          <Icon name="play" size={12} /> Run on DB
                        </button>
                        <button
                          onClick={() => setDismissed((p) => new Set([...p, msg.id]))}
                          className="text-[11px] px-2 py-1 rounded-[6px] transition-colors"
                          style={{ color: 'var(--text-3)' }}
                        >
                          Dismiss
                        </button>
                      </div>
                    )}
                  </div>
                ) : null}
              </div>

              {/* Pipeline trace badges */}
              {info && <PipelineBadges info={info} />}

              {/* Query results */}
              {queryResults[msg.id] && (
                <div id={`result-${msg.id}`} className="ml-8 sm:ml-10 flex flex-col gap-2">
                  {queryResults[msg.id].success && (
                    <KpiCard columns={queryResults[msg.id].columns} rows={queryResults[msg.id].rows} />
                  )}
                  <QueryResultView result={queryResults[msg.id]} />
                  {queryResults[msg.id].success && queryResults[msg.id].experiment_id && (
                    <div className="flex items-center gap-2">
                      <span className="text-[11px]" style={{ color: 'var(--text-2)' }}>Was this correct?</span>
                      {([true, false] as const).map((val) => {
                        const active = feedback[msg.id] === val
                        return (
                          <button
                            key={String(val)}
                            onClick={() => handleFeedback(msg.id, val)}
                            className="text-[11px] px-2.5 py-0.5 rounded-[5px] font-medium transition-all"
                            style={{
                              background: active ? (val ? 'var(--accent-bg)' : 'var(--red-bg)') : 'var(--bg-raised)',
                              color: active ? (val ? 'var(--accent-text)' : 'var(--red)') : 'var(--text-2)',
                              border: `1px solid ${active ? (val ? 'var(--accent-border)' : 'var(--red-border)') : 'var(--border-default)'}`,
                            }}
                          >
                            {val ? '✓ Yes' : '✗ No'}
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}

        {/* Sending indicator */}
        {sending && (
          <div className="flex gap-3 items-center">
            <div className="relative w-7 h-7 flex-shrink-0">
              <div className="absolute inset-0 rounded-[9px] animate-pulse" style={{ background: 'var(--accent)', opacity: 0.18 }} />
              <div className="w-7 h-7 rounded-[9px] flex items-center justify-center overflow-hidden relative"
                style={{ background: 'var(--bg-raised)', border: '1px solid var(--accent-border)' }}>
                <img src={amrLogo} alt="AI" className="w-[18px] h-[18px] object-contain" />
              </div>
            </div>
            <div className="flex gap-1 py-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="w-2 h-2 rounded-full" style={{ background: 'var(--text-3)', animation: `bounce 1.2s ${i * 0.2}s infinite` }} />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div
        className="px-4 pb-4 pt-3 flex-shrink-0"
        style={{ borderTop: '1px solid var(--border-default)', background: 'var(--bg-surface)' }}
      >
        {hasWarning && (
          <div className="flex items-center gap-2 mb-2.5 px-1" style={{ color: 'var(--text-3)' }}>
            <span className="flex-shrink-0" style={{ color: 'var(--amber)', display: 'flex' }}><Icon name="zap" size={11} /></span>
            <span className="text-[11px]">
              {!ollamaActive && !dbActive
                ? 'Ollama and database not connected.'
                : !ollamaActive
                ? 'Ollama not connected.'
                : 'No database connected.'}
            </span>
            <button
              onClick={() => setActivePage('settings')}
              className="ml-auto text-[11px] flex-shrink-0 hover:underline"
              style={{ color: 'var(--accent-text)' }}
            >
              Settings →
            </button>
          </div>
        )}

        <div
          className="rounded-[16px] transition-all duration-150 overflow-hidden"
          style={{
            background: 'var(--bg-raised)',
            border: `1.5px solid ${inputFocused ? 'var(--accent)' : 'var(--border-default)'}`,
            boxShadow: inputFocused
              ? '0 0 0 3px var(--accent-bg), 0 2px 8px rgba(0,0,0,0.08)'
              : '0 1px 3px rgba(0,0,0,0.06)',
          }}
          onFocus={() => setInputFocused(true)}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node)) setInputFocused(false)
          }}
        >
          <textarea
            ref={textareaRef}
            value={question}
            onChange={(e) => {
              setQuestion(e.target.value)
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 180) + 'px'
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
            }}
            placeholder="سوال خود را بپرسید…"
            rows={1}
            className="placeholder:text-[var(--text-3)] w-full block"
            style={{
              direction: 'rtl',
              textAlign: 'right',
              padding: '12px 16px 6px',
              maxHeight: '180px',
              background: 'transparent',
              border: 'none',
              outline: 'none',
              resize: 'none',
              fontSize: '14px',
              lineHeight: '1.65',
              color: 'var(--text-1)',
              fontFamily: 'inherit',
            }}
          />

          {/* Bottom bar — natural flow, not absolute */}
          <div className="flex items-center gap-2 px-3 pb-2.5">
            {project && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded-[4px] truncate max-w-[120px] select-none"
                style={{
                  background: 'var(--accent-bg)',
                  color: 'var(--accent-text)',
                  border: '1px solid var(--accent-border)',
                }}
              >
                {project.name}
              </span>
            )}
            {session?.model_name && (
              <span
                className="text-[10px] font-mono px-1.5 py-0.5 rounded-[4px] truncate max-w-[140px] select-none"
                style={{
                  background: 'var(--bg-surface)',
                  color: 'var(--text-3)',
                  border: '1px solid var(--border-subtle)',
                }}
              >
                {session.model_name.split(':')[0]}
              </span>
            )}
            <button
              onClick={handleSend}
              disabled={sending || !question.trim() || hasWarning}
              className="ml-auto w-7 h-7 rounded-[9px] flex items-center justify-center transition-all"
              style={{
                background: !sending && question.trim() && !hasWarning ? 'var(--accent)' : 'transparent',
                color: !sending && question.trim() && !hasWarning ? '#fff' : 'var(--text-3)',
                border: !sending && question.trim() && !hasWarning ? 'none' : '1px solid var(--border-default)',
                transform: !sending && question.trim() && !hasWarning ? 'scale(1.05)' : 'scale(1)',
              }}
            >
              {sending
                ? <div className="w-3 h-3 rounded-full border-2 border-current border-t-transparent animate-spin" />
                : <Icon name="send" size={12} />
              }
            </button>
          </div>
        </div>

        {/* Keyboard hint */}
        <p className="text-center text-[10px] mt-2 select-none" style={{ color: 'var(--text-3)' }}>
          <span className="font-mono opacity-70">↵</span> ارسال
          <span className="mx-1.5 opacity-40">·</span>
          <span className="font-mono opacity-70">⇧↵</span> خط جدید
        </p>
      </div>
    </div>
  )
}
