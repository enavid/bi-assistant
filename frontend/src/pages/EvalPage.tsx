import React, { useRef, useState } from 'react'
import { Icon } from '@/components/ui/Icon'
import { Modal, ConfirmDialog } from '@/components/ui/Modal'
import {
  useAddEvalQuestion,
  useCreateEvalSet,
  useDeleteEvalQuestion,
  useDeleteEvalSet,
  useEvalQuestions,
  useEvalRun,
  useEvalRuns,
  useEvalSets,
  useImportEvalQuestions,
  useTriggerEvalRun,
} from '@/hooks'
import type { EvalQuestion, EvalRun, EvalRunResult } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('fa-IR', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function passRate(run: EvalRun) {
  if (!run.total) return null
  return Math.round((run.passed / run.total) * 100)
}

function StatusBadge({ status }: { status: EvalRun['status'] }) {
  const map: Record<EvalRun['status'], { label: string; color: string; bg: string }> = {
    pending:  { label: 'pending',  color: 'var(--text-3)',   bg: 'var(--bg-raised)' },
    running:  { label: 'running…', color: '#f59e0b',         bg: 'rgba(245,158,11,0.12)' },
    done:     { label: 'done',     color: '#22c55e',         bg: 'rgba(34,197,94,0.12)' },
  }
  const s = map[status]
  return (
    <span
      className="text-[10px] font-semibold px-1.5 py-[2px] rounded-[4px]"
      style={{ color: s.color, background: s.bg }}
    >
      {s.label}
    </span>
  )
}

const inputCls = 'px-3 py-2.5 rounded-[8px] text-[13px] outline-none w-full'
const inputStyle = { background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-1)' }
const labelCls = 'text-[11px] font-semibold uppercase tracking-[0.6px]'

// ---------------------------------------------------------------------------
// Set list panel (left)
// ---------------------------------------------------------------------------

function SetList({
  selectedId,
  onSelect,
}: {
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const { data: sets, isLoading } = useEvalSets()
  const createSet = useCreateEvalSet()
  const deleteSet = useDeleteEvalSet()
  const [newOpen, setNewOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [pendingDeleteSet, setPendingDeleteSet] = useState<{ id: string; name: string } | null>(null)

  async function handleCreate() {
    if (!name.trim()) return
    const s = await createSet.mutateAsync({ name: name.trim(), description: description.trim() })
    setName('')
    setDescription('')
    setNewOpen(false)
    onSelect(s.id)
  }

  return (
    <>
      <div
        className="w-[220px] min-w-[220px] flex flex-col h-full"
        style={{ borderRight: '1px solid var(--border-default)', background: 'var(--bg-surface)' }}
      >
        <div
          className="px-3 py-3 flex items-center justify-between flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}
        >
          <span className={`${labelCls}`} style={{ color: 'var(--text-3)' }}>
            Question Sets
          </span>
          <button
            onClick={() => setNewOpen(true)}
            className="w-6 h-6 rounded-[6px] flex items-center justify-center transition-opacity hover:opacity-70"
            style={{ background: 'var(--accent)', color: '#fff' }}
            title="New set"
          >
            <Icon name="plus" size={13} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {isLoading && (
            <p className="text-[11px] px-2 py-3" style={{ color: 'var(--text-3)' }}>Loading…</p>
          )}
          {!isLoading && !sets?.length && (
            <p className="text-[11px] px-2 py-3 text-center" style={{ color: 'var(--text-3)' }}>No sets yet.</p>
          )}
          {sets?.map((s) => {
            const active = s.id === selectedId
            return (
              <div
                key={s.id}
                onClick={() => onSelect(s.id)}
                className="group flex items-center gap-2 px-2.5 py-2.5 rounded-[8px] mb-0.5 cursor-pointer transition-colors"
                style={{ background: active ? 'var(--accent-bg)' : 'transparent' }}
                onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = 'var(--bg-raised)' }}
                onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent' }}
              >
                <span style={{ color: active ? 'var(--accent-text)' : 'var(--text-3)', flexShrink: 0 }}>
                  <Icon name="flask" size={14} />
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-[12px] font-medium truncate" style={{ color: active ? 'var(--accent-text)' : 'var(--text-1)' }}>
                    {s.name}
                    {s.is_default && (
                      <span className="ml-1 text-[9px] px-1 py-[1px] rounded" style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)' }}>
                        default
                      </span>
                    )}
                  </p>
                  <p className="text-[10px]" style={{ color: 'var(--text-3)' }}>
                    {s.question_count} questions
                  </p>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); setPendingDeleteSet({ id: s.id, name: s.name }) }}
                  className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                  style={{ color: 'var(--text-3)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = '#f87171')}
                  onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-3)')}
                >
                  <Icon name="trash" size={12} />
                </button>
              </div>
            )
          })}
        </div>
      </div>

      <Modal open={newOpen} title="New question set" onClose={() => setNewOpen(false)}>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className={labelCls} style={{ color: 'var(--text-3)' }}>Name</label>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleCreate() }}
              placeholder="e.g. HR questions"
              className={inputCls}
              style={inputStyle}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className={labelCls} style={{ color: 'var(--text-3)' }}>Description</label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional"
              className={inputCls}
              style={inputStyle}
            />
          </div>
          <div className="flex gap-2 pt-1">
            <button
              onClick={() => setNewOpen(false)}
              className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium"
              style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={!name.trim() || createSet.isPending}
              className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium transition-opacity hover:opacity-90 disabled:opacity-40"
              style={{ background: 'var(--accent)', color: '#fff' }}
            >
              Create
            </button>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={pendingDeleteSet !== null}
        title="Delete question set"
        message={`"${pendingDeleteSet?.name}" and all its questions will be permanently deleted.`}
        confirmLabel="Delete"
        onConfirm={() => { if (pendingDeleteSet) deleteSet.mutate(pendingDeleteSet.id) }}
        onClose={() => setPendingDeleteSet(null)}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// Import modal
// ---------------------------------------------------------------------------

function ImportModal({ setId, open, onClose }: { setId: string; open: boolean; onClose: () => void }) {
  const importQ = useImportEvalQuestions()
  const fileRef = useRef<HTMLInputElement>(null)
  const [text, setText] = useState('')
  const [error, setError] = useState('')

  async function handleImport() {
    setError('')
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      setError('Invalid JSON')
      return
    }
    if (!Array.isArray(parsed)) {
      setError('Expected a JSON array of questions')
      return
    }
    try {
      await importQ.mutateAsync({ setId, questions: parsed as never })
      setText('')
      onClose()
    } catch {
      setError('Import failed — check the format')
    }
  }

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => setText(ev.target?.result as string)
    reader.readAsText(file)
  }

  return (
    <Modal open={open} title="Import questions" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <p className="text-[12px]" style={{ color: 'var(--text-2)' }}>
          Paste JSON array or upload a file. Each item needs{' '}
          <code className="px-1 rounded text-[11px]" style={{ background: 'var(--bg-raised)', color: 'var(--accent-text)' }}>question_id</code>{' '}
          and{' '}
          <code className="px-1 rounded text-[11px]" style={{ background: 'var(--bg-raised)', color: 'var(--accent-text)' }}>question</code>.
        </p>
        <button
          onClick={() => fileRef.current?.click()}
          className="flex items-center gap-2 px-3 py-2 rounded-[8px] text-[12px] transition-opacity hover:opacity-70"
          style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}
        >
          <Icon name="notes" size={14} />
          Choose JSON file…
        </button>
        <input ref={fileRef} type="file" accept=".json" className="hidden" onChange={handleFile} />
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={8}
          placeholder='[{"question_id": "q1", "question": "...", "category": "demographics"}]'
          className="px-3 py-2.5 rounded-[8px] text-[11px] font-mono outline-none resize-none"
          style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-1)' }}
        />
        {error && <p className="text-[11px]" style={{ color: '#f87171' }}>{error}</p>}
        <div className="flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium"
            style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}
          >
            Cancel
          </button>
          <button
            onClick={handleImport}
            disabled={!text.trim() || importQ.isPending}
            className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium transition-opacity hover:opacity-90 disabled:opacity-40"
            style={{ background: 'var(--accent)', color: '#fff' }}
          >
            {importQ.isPending ? 'Importing…' : 'Import'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Add single question modal
// ---------------------------------------------------------------------------

function AddQuestionModal({ setId, open, onClose }: { setId: string; open: boolean; onClose: () => void }) {
  const addQ = useAddEvalQuestion()
  const [question, setQuestion] = useState('')
  const [category, setCategory] = useState('')
  const [expectedRoute, setExpectedRoute] = useState('')
  const [error, setError] = useState('')

  async function handleAdd() {
    if (!question.trim()) return
    setError('')
    try {
      await addQ.mutateAsync({
        setId,
        question_id: `manual_${Date.now()}`,
        question: question.trim(),
        category: category.trim() || undefined,
        expected_route: expectedRoute.trim() || undefined,
      })
      setQuestion('')
      setCategory('')
      setExpectedRoute('')
      onClose()
    } catch {
      setError('Failed to add question')
    }
  }

  return (
    <Modal open={open} title="Add question" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label className={labelCls} style={{ color: 'var(--text-3)' }}>Question</label>
          <textarea
            autoFocus
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={3}
            placeholder="تعداد کل کارکنان چقدر است؟"
            className="px-3 py-2.5 rounded-[8px] text-[13px] outline-none resize-none"
            style={inputStyle}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <label className={labelCls} style={{ color: 'var(--text-3)' }}>Category</label>
            <input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="e.g. demographics"
              className={inputCls}
              style={inputStyle}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className={labelCls} style={{ color: 'var(--text-3)' }}>Expected route</label>
            <input
              value={expectedRoute}
              onChange={(e) => setExpectedRoute(e.target.value)}
              placeholder="e.g. SQL"
              className={inputCls}
              style={inputStyle}
            />
          </div>
        </div>
        {error && <p className="text-[11px]" style={{ color: '#f87171' }}>{error}</p>}
        <div className="flex gap-2 pt-1">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium"
            style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}
          >
            Cancel
          </button>
          <button
            onClick={handleAdd}
            disabled={!question.trim() || addQ.isPending}
            className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium transition-opacity hover:opacity-90 disabled:opacity-40"
            style={{ background: 'var(--accent)', color: '#fff' }}
          >
            {addQ.isPending ? 'Adding…' : 'Add'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Run options modal (category + model selection)
// ---------------------------------------------------------------------------

const KNOWN_MODELS = ['', 'llama3.2', 'qwen2.5-coder', 'mistral', 'deepseek-r1']

function RunModal({
  setId,
  categories,
  open,
  onClose,
  onRun,
}: {
  setId: string
  categories: string[]
  open: boolean
  onClose: () => void
  onRun: (runId: string) => void
}) {
  const trigger = useTriggerEvalRun()
  const [category, setCategory] = useState('')
  const [modelName, setModelName] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [error, setError] = useState('')

  const effectiveModel = modelName === '__custom__' ? customModel.trim() : modelName

  async function handleRun() {
    setError('')
    try {
      const run = await trigger.mutateAsync({
        setId,
        category: category || undefined,
        model_name: effectiveModel || undefined,
      })
      onClose()
      onRun(run.id)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Failed to start run')
    }
  }

  return (
    <Modal open={open} title="Run evaluation" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label className={labelCls} style={{ color: 'var(--text-3)' }}>Category (optional)</label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="px-3 py-2.5 rounded-[8px] text-[13px] outline-none"
            style={inputStyle}
          >
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label className={labelCls} style={{ color: 'var(--text-3)' }}>Model (optional)</label>
          <select
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            className="px-3 py-2.5 rounded-[8px] text-[13px] outline-none"
            style={inputStyle}
          >
            <option value="">Default model</option>
            {KNOWN_MODELS.filter(Boolean).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
            <option value="__custom__">Custom…</option>
          </select>
          {modelName === '__custom__' && (
            <input
              autoFocus
              value={customModel}
              onChange={(e) => setCustomModel(e.target.value)}
              placeholder="e.g. llama3.2:8b"
              className={inputCls}
              style={inputStyle}
            />
          )}
        </div>
        {error && <p className="text-[11px]" style={{ color: '#f87171' }}>{error}</p>}
        <div className="flex gap-2 pt-1">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium"
            style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}
          >
            Cancel
          </button>
          <button
            onClick={handleRun}
            disabled={trigger.isPending}
            className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium transition-opacity hover:opacity-90 disabled:opacity-40"
            style={{ background: 'var(--accent)', color: '#fff' }}
          >
            {trigger.isPending ? 'Starting…' : 'Run'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const EVAL_ROUTE_STYLE: Record<string, { bg: string; text: string; border: string }> = {
  SQL:                 { bg: 'var(--accent-bg)',  text: 'var(--accent-text)',  border: 'var(--accent-border)' },
  GAP:                 { bg: 'var(--amber-bg)',   text: 'var(--amber)',        border: 'var(--amber-border)' },
  REJECT:              { bg: 'var(--red-bg)',     text: 'var(--red)',          border: 'var(--red-border)' },
  NEEDS_CLARIFICATION: { bg: 'var(--bg-raised)',  text: 'var(--text-3)',       border: 'var(--border-default)' },
  _default:            { bg: 'var(--bg-raised)',  text: 'var(--text-3)',       border: 'var(--border-subtle)' },
}

const EVAL_STATUS_LABEL: Record<string, string> = {
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

function EvalTracePanel({ steps }: { steps: NonNullable<EvalRunResult['trace_steps']> }) {
  return (
    <div
      className="mt-1 rounded-[6px] overflow-hidden text-[10px] font-mono"
      style={{ border: '1px solid var(--border-subtle)', background: 'var(--bg-raised)' }}
    >
      <div className="grid" style={{ gridTemplateColumns: 'minmax(130px, 1.8fr) minmax(90px, 1fr) 52px 96px', gap: 0 }}>
        {(['step', 'status', 'ms', 'decision'] as const).map((h) => (
          <div key={h} className="px-2.5 py-1.5 font-semibold uppercase tracking-wide text-[9px]"
            style={{ color: 'var(--text-3)', borderBottom: '1px solid var(--border-subtle)' }}>
            {h}
          </div>
        ))}
        {steps.map((t, i) => {
          const isLast = i === steps.length - 1
          const decision = t.decision_by ?? '—'
          const ds = DECISION_STYLE[decision]
          const status = t.status ?? ''
          const statusColor = traceStatusColor(status)
          const rowBorder = !isLast ? '1px solid var(--border-subtle)' : undefined
          return (
            <React.Fragment key={i}>
              <div className="px-2.5 py-[5px]" style={{ color: 'var(--text-2)', borderBottom: rowBorder }}>
                {t.step ?? '—'}
              </div>
              <div className="px-2.5 py-[5px]" style={{ borderBottom: rowBorder }}>
                <span style={{ color: statusColor, fontWeight: statusColor === 'var(--red)' ? 600 : undefined }}>{status || '—'}</span>
              </div>
              <div className="px-2.5 py-[5px] tabular-nums text-right" style={{ color: 'var(--text-3)', borderBottom: rowBorder }}>
                {t.duration_ms != null ? t.duration_ms.toFixed(1) : '—'}
              </div>
              <div className="px-2.5 py-[5px]" style={{ borderBottom: rowBorder }}>
                <span className="px-1.5 py-[2px] rounded-[3px] whitespace-nowrap"
                  style={{ color: ds?.color ?? 'var(--text-3)', background: ds?.bg ?? 'transparent', border: `1px solid ${ds?.border ?? 'var(--border-subtle)'}` }}>
                  {decision}
                </span>
              </div>
            </React.Fragment>
          )
        })}
      </div>
    </div>
  )
}

function humanCategory(cat: string) {
  return cat.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// ---------------------------------------------------------------------------
// Category accordion
// ---------------------------------------------------------------------------

function QuestionRow({ r, isLatest }: { r: EvalRunResult; isLatest: boolean }) {
  const [traceOpen, setTraceOpen] = useState(false)
  const routeStyle = EVAL_ROUTE_STYLE[r.actual_route ?? ''] ?? EVAL_ROUTE_STYLE._default
  const statusLabel = r.actual_status ? (EVAL_STATUS_LABEL[r.actual_status] ?? r.actual_status) : null
  const hasTrace = (r.trace_steps?.length ?? 0) > 0

  return (
    <div className="flex flex-col gap-[3px]">
      {/* badge + bubble */}
      <div className="flex gap-3 items-start">
        <div
          className="w-7 h-7 rounded-[8px] flex items-center justify-center flex-shrink-0 mt-0.5"
          style={
            r.passed
              ? { background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }
              : { background: 'var(--red-bg)', color: 'var(--red)', border: '1px solid var(--red-border)' }
          }
        >
          <Icon name={r.passed ? 'check' : 'x'} size={12} />
        </div>
        <div
          className="flex-1 px-4 py-2 text-[13px] leading-[1.5] min-w-0"
          style={{
            background: 'var(--bg-raised)',
            border: '1px solid var(--border-default)',
            borderRadius: '4px 18px 18px 18px',
            direction: 'rtl',
            textAlign: 'right',
            color: 'var(--text-1)',
            outline: isLatest ? '2px solid var(--accent-border)' : undefined,
            outlineOffset: '1px',
          }}
        >
          {r.question}
        </div>
      </div>

      {/* chips row — like PipelineBadges */}
      <div className="ml-10 flex items-center gap-1.5 flex-wrap" style={{ marginTop: '-2px' }}>
        {isLatest && (
          <span className="text-[9px] px-1.5 py-[2px] rounded-[4px] font-mono animate-pulse"
            style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }}>
            now
          </span>
        )}
        {r.actual_route && (
          <span className="text-[10px] font-mono font-medium px-1.5 py-[3px] rounded-[4px]"
            style={{ background: routeStyle.bg, color: routeStyle.text, border: `1px solid ${routeStyle.border}` }}>
            {r.actual_route}
          </span>
        )}
        {statusLabel && (
          <span className="text-[10px] font-mono px-1.5 py-[3px] rounded-[4px]"
            style={{ background: 'var(--bg-raised)', color: 'var(--text-3)', border: '1px solid var(--border-subtle)' }}>
            {statusLabel}
          </span>
        )}
        <span className="text-[10px] font-mono tabular-nums px-1.5 py-[3px] rounded-[4px]"
          style={{ background: 'var(--bg-raised)', color: 'var(--text-3)', border: '1px solid var(--border-subtle)' }}>
          {Math.round(r.total_duration_ms)}ms
        </span>
        {r.error && (
          <span className="text-[10px] font-mono px-1.5 py-[3px] rounded-[4px]"
            style={{ background: 'var(--red-bg)', color: 'var(--red)', border: '1px solid var(--red-border)' }}
            title={r.error}>
            {r.error.length > 40 ? r.error.slice(0, 40) + '…' : r.error}
          </span>
        )}
        {hasTrace && (
          <button
            onClick={() => setTraceOpen((v) => !v)}
            className="text-[10px] font-mono px-1.5 py-[3px] rounded-[4px]"
            style={{
              background: traceOpen ? 'var(--accent-bg)' : 'var(--bg-raised)',
              color: traceOpen ? 'var(--accent-text)' : 'var(--text-3)',
              border: `1px solid ${traceOpen ? 'var(--accent-border)' : 'var(--border-default)'}`,
            }}
          >
            {traceOpen ? '↑' : '↓'} trace
          </button>
        )}
      </div>

      {/* inline trace panel — like ChatPage */}
      {traceOpen && hasTrace && (
        <div className="ml-10">
          <EvalTracePanel steps={r.trace_steps!} />
        </div>
      )}
    </div>
  )
}

function CategorySection({
  category,
  results,
  isLastActive,
}: {
  category: string
  results: EvalRunResult[]
  isLastActive: boolean
}) {
  const passed = results.filter((r) => r.passed).length
  const total = results.length
  const pct = Math.round((passed / total) * 100)
  const hasFail = passed < total

  const [open, setOpen] = useState(hasFail)

  return (
    <div style={{ borderBottom: '1px solid var(--border-subtle)' }}>
      {/* Header */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2.5 px-4 py-2.5 text-left"
        style={{ background: 'var(--bg-raised)' }}
        onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.85')}
        onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}
      >
        <span style={{ color: 'var(--text-3)', display: 'inline-flex', flexShrink: 0, transition: 'transform 0.15s', transform: open ? 'rotate(90deg)' : 'none' }}>
          <Icon name="arrow-right" size={10} />
        </span>
        <span className="flex-1 text-[12px] font-semibold" style={{ color: 'var(--text-1)' }}>
          {humanCategory(category)}
        </span>
        <div className="flex items-center gap-3 flex-shrink-0">
          <div className="w-[60px] h-[3px] rounded-full overflow-hidden" style={{ background: 'var(--border-default)' }}>
            <div className="h-full rounded-full" style={{ width: `${pct}%`, background: hasFail ? 'var(--red)' : 'var(--accent)' }} />
          </div>
          <span className="text-[11px] tabular-nums" style={{ color: 'var(--text-3)', minWidth: 32, textAlign: 'right' }}>
            {passed}/{total}
          </span>
          {hasFail ? (
            <span className="text-[10px] px-1.5 py-[1px] rounded tabular-nums"
              style={{ background: 'var(--red-bg)', color: 'var(--red)', border: '1px solid var(--red-border)', minWidth: 44, textAlign: 'center' }}>
              {total - passed} fail
            </span>
          ) : (
            <span className="text-[10px] px-1.5 py-[1px] rounded"
              style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)', minWidth: 44, textAlign: 'center' }}>
              {pct}%
            </span>
          )}
        </div>
      </button>

      {/* Questions */}
      {open && (
        <div className="flex flex-col gap-2.5 px-4 py-3">
          {results.map((r, idx) => (
            <QuestionRow key={r.id} r={r} isLatest={isLastActive && idx === results.length - 1} />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Run results — category accordion view
// ---------------------------------------------------------------------------

function RunResults({ runId, isRunning }: { runId: string; isRunning: boolean }) {
  const [filterPassed, setFilterPassed] = useState<'all' | 'pass' | 'fail'>('all')

  const { data: run, isLoading } = useEvalRun(runId, isRunning)

  if (isLoading) return <p className="text-[12px] p-4" style={{ color: 'var(--text-3)' }}>Loading…</p>
  if (!run) return null

  const results = run.results ?? []
  const done = results.length
  const pct = passRate(run)

  // Group by category
  const categoryOrder: string[] = []
  const byCategory: Record<string, EvalRunResult[]> = {}
  for (const r of results) {
    const cat = r.category ?? 'other'
    if (!byCategory[cat]) { byCategory[cat] = []; categoryOrder.push(cat) }
    byCategory[cat].push(r)
  }

  // Failures first, then alphabetical
  const sorted = [...categoryOrder].sort((a, b) => {
    const af = byCategory[a].some((r) => !r.passed) ? 0 : 1
    const bf = byCategory[b].some((r) => !r.passed) ? 0 : 1
    return af !== bf ? af - bf : a.localeCompare(b)
  })

  const visible = sorted.filter((cat) => {
    if (filterPassed === 'pass') return byCategory[cat].every((r) => r.passed)
    if (filterPassed === 'fail') return byCategory[cat].some((r) => !r.passed)
    return true
  })

  const lastCategory = categoryOrder[categoryOrder.length - 1] ?? null

  return (
    <div className="flex flex-col gap-3 h-full">

      {/* Summary bar */}
      <div className="flex items-center gap-3 flex-shrink-0 flex-wrap">
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] font-semibold tabular-nums" style={{ color: 'var(--text-1)' }}>
            {run.passed}/{run.total}
          </span>
          {pct !== null && (
            <span className="text-[12px]" style={{ color: 'var(--text-3)' }}>({pct}%)</span>
          )}
        </div>

        <StatusBadge status={run.status} />

        {run.model_name && (
          <span className="text-[10px] px-2 py-[2px] rounded font-mono" style={{ background: 'var(--bg-raised)', color: 'var(--text-3)' }}>
            {run.model_name}
          </span>
        )}

        {/* progress bar during run */}
        {isRunning && run.total > 0 && (
          <div className="flex items-center gap-2 flex-1 min-w-[80px]">
            <div className="flex-1 h-[3px] rounded-full overflow-hidden" style={{ background: 'var(--border-default)' }}>
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{ width: `${Math.round((done / run.total) * 100)}%`, background: 'var(--accent)' }}
              />
            </div>
            <span className="text-[10px] tabular-nums flex-shrink-0" style={{ color: 'var(--text-3)' }}>
              {done}/{run.total}
            </span>
          </div>
        )}

        {/* filters */}
        <div className="flex gap-1 ml-auto">
          {(['all', 'pass', 'fail'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilterPassed(f)}
              className="px-2.5 py-1 rounded-[6px] text-[11px] font-medium"
              style={{
                background: filterPassed === f ? 'var(--accent-bg)' : 'var(--bg-raised)',
                color: filterPassed === f ? 'var(--accent-text)' : 'var(--text-2)',
                border: `1px solid ${filterPassed === f ? 'var(--accent-border)' : 'var(--border-default)'}`,
              }}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Accordion list */}
      <div
        className="flex-1 overflow-y-auto rounded-[8px]"
        style={{ border: '1px solid var(--border-default)', background: 'var(--bg-surface)' }}
      >
        {visible.length === 0 && (
          <p className="text-center py-10 text-[12px]" style={{ color: 'var(--text-3)' }}>No results yet.</p>
        )}
        {visible.map((cat) => (
          <CategorySection
            key={cat}
            category={cat}
            results={byCategory[cat]}
            isLastActive={isRunning && cat === lastCategory}
          />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Question list (shown before first run)
// ---------------------------------------------------------------------------

function QuestionList({ questions, setId }: { questions: EvalQuestion[]; setId: string }) {
  const deleteQ = useDeleteEvalQuestion()
  const [pendingDeleteQ, setPendingDeleteQ] = useState<{ questionId: string; label: string } | null>(null)

  const byCat: Record<string, EvalQuestion[]> = {}
  for (const q of questions) {
    const cat = q.category ?? ''
    if (!byCat[cat]) byCat[cat] = []
    byCat[cat].push(q)
  }
  const cats = Object.keys(byCat).sort()

  return (
    <div
      className="rounded-[8px] overflow-hidden mx-0"
      style={{ border: '1px solid var(--border-default)', background: 'var(--bg-surface)' }}
    >
      {cats.map((cat, ci) => (
        <div key={cat} style={{ borderBottom: ci < cats.length - 1 ? '1px solid var(--border-subtle)' : undefined }}>
          {/* Category header */}
          {cat && (
            <div
              className="px-4 py-2 text-[11px] font-semibold uppercase tracking-wide"
              style={{ color: 'var(--text-3)', background: 'var(--bg-raised)', borderBottom: '1px solid var(--border-subtle)' }}
            >
              {humanCategory(cat)}
            </div>
          )}
          {/* Questions */}
          {byCat[cat].map((q, qi) => (
            <div
              key={q.id}
              className="group flex items-center gap-3 px-4 py-2.5"
              style={{ borderTop: (qi > 0 || cat) ? '1px solid var(--border-subtle)' : undefined }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-raised)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = '')}
            >
              <span className="flex-shrink-0" style={{ color: 'var(--text-3)' }}>
                <Icon name="list" size={13} />
              </span>
              <span
                className="flex-1 text-[13px] leading-snug"
                style={{ color: 'var(--text-1)', direction: 'rtl', textAlign: 'right' }}
              >
                {q.question}
              </span>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                {q.expected_route && (
                  <span
                    className="text-[10px] font-mono px-1.5 py-[2px] rounded-[4px]"
                    style={
                      EVAL_ROUTE_STYLE[q.expected_route]
                        ? { background: EVAL_ROUTE_STYLE[q.expected_route].bg, color: EVAL_ROUTE_STYLE[q.expected_route].text, border: `1px solid ${EVAL_ROUTE_STYLE[q.expected_route].border}` }
                        : { background: 'var(--bg-raised)', color: 'var(--text-3)', border: '1px solid var(--border-subtle)' }
                    }
                  >
                    {q.expected_route}
                  </span>
                )}
                <button
                  onClick={() => setPendingDeleteQ({ questionId: q.question_id, label: q.question_id })}
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-[5px]"
                  style={{ color: 'var(--text-3)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--red)')}
                  onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-3)')}
                  title="Delete question"
                >
                  <Icon name="trash" size={12} />
                </button>
              </div>
            </div>
          ))}
        </div>
      ))}

      <ConfirmDialog
        open={pendingDeleteQ !== null}
        title="Delete question"
        message={`Question "${pendingDeleteQ?.label}" will be permanently deleted.`}
        confirmLabel="Delete"
        onConfirm={() => { if (pendingDeleteQ) deleteQ.mutate({ setId, questionId: pendingDeleteQ.questionId }) }}
        onClose={() => setPendingDeleteQ(null)}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Set detail panel (right)
// ---------------------------------------------------------------------------

function SetDetail({ setId }: { setId: string }) {
  const { data: sets } = useEvalSets()
  const { data: questions } = useEvalQuestions(setId)
  const { data: runs, isLoading: runsLoading } = useEvalRuns(setId)
  const [importOpen, setImportOpen] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [runOpen, setRunOpen] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  const set = sets?.find((s) => s.id === setId)
  const activeRun = runs?.find((r) => r.status === 'running' || r.status === 'pending')
  const newestRun = runs?.[0] ?? null
  const displayRunId = selectedRunId ?? newestRun?.id ?? null
  const displayRun = runs?.find((r) => r.id === displayRunId) ?? null
  const isRunning = displayRun?.status === 'running' || displayRun?.status === 'pending'

  const categories = [...new Set(
    (questions ?? []).map((q) => q.category).filter(Boolean)
  )] as string[]

  return (
    <>
      <div className="flex-1 flex flex-col h-full overflow-hidden p-5 gap-5">
        {/* Header */}
        <div className="flex items-start gap-3 flex-shrink-0">
          <div className="flex-1 min-w-0">
            <h2 className="text-[15px] font-semibold truncate" style={{ color: 'var(--text-1)' }}>
              {set?.name ?? '…'}
            </h2>
            <p className="text-[12px] mt-0.5" style={{ color: 'var(--text-3)' }}>
              {questions?.length ?? 0} questions
              {set?.description ? ` · ${set.description}` : ''}
            </p>
          </div>
          <div className="flex gap-2 flex-shrink-0 flex-wrap justify-end">
            <button
              onClick={() => setAddOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-[8px] text-[12px] font-medium transition-opacity hover:opacity-80"
              style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}
            >
              <Icon name="plus" size={13} />
              Add question
            </button>
            <button
              onClick={() => setImportOpen(true)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-[8px] text-[12px] font-medium transition-opacity hover:opacity-80"
              style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}
            >
              <Icon name="notes" size={13} />
              Import
            </button>
            <button
              onClick={() => setRunOpen(true)}
              disabled={!questions?.length || !!activeRun}
              className="flex items-center gap-1.5 px-3 py-2 rounded-[8px] text-[12px] font-medium transition-opacity hover:opacity-90 disabled:opacity-40"
              style={{ background: 'var(--accent)', color: '#fff' }}
            >
              <Icon name="play" size={13} />
              {activeRun ? 'Running…' : 'Run eval'}
            </button>
          </div>
        </div>

        {/* Run selector */}
        {!runsLoading && !!runs?.length && (
          <div className="flex-shrink-0">
            <div className="flex gap-1.5 overflow-x-auto pb-1">
              {runs.map((r) => {
                const pct = passRate(r)
                const selected = r.id === displayRunId
                return (
                  <button
                    key={r.id}
                    onClick={() => setSelectedRunId(r.id)}
                    className="flex-shrink-0 flex items-center gap-2 px-3 py-2 rounded-[8px] text-left"
                    style={{
                      background: selected ? 'var(--accent-bg)' : 'var(--bg-raised)',
                      border: `1px solid ${selected ? 'var(--accent-border)' : 'var(--border-default)'}`,
                    }}
                  >
                    <StatusBadge status={r.status} />
                    {pct !== null && r.status === 'done' && (
                      <span
                        className="text-[11px] font-semibold tabular-nums"
                        style={{ color: pct >= 80 ? '#22c55e' : pct >= 50 ? '#f59e0b' : '#f87171' }}
                      >
                        {pct}%
                      </span>
                    )}
                    <span className="text-[10px]" style={{ color: 'var(--text-3)' }}>
                      {fmtDate(r.created_at)}
                    </span>
                    {r.model_name && (
                      <span className="text-[9px] font-mono" style={{ color: 'var(--text-3)' }}>
                        · {r.model_name}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {/* Results or question list */}
        <div className="flex-1 overflow-hidden">
          {displayRunId
            ? <RunResults runId={displayRunId} isRunning={isRunning} />
            : questions?.length
              ? (
                <div className="h-full overflow-y-auto">
                  <QuestionList questions={questions} setId={setId} />
                </div>
              )
              : (
                <div className="flex items-center justify-center h-full" style={{ color: 'var(--text-3)' }}>
                  <div className="text-center">
                    <span className="block mb-3 opacity-30"><Icon name="flask" size={32} /></span>
                    <p className="text-[13px]">Add or import questions, then run the evaluation.</p>
                  </div>
                </div>
              )}
        </div>
      </div>

      <ImportModal setId={setId} open={importOpen} onClose={() => setImportOpen(false)} />
      <AddQuestionModal setId={setId} open={addOpen} onClose={() => setAddOpen(false)} />
      <RunModal
        setId={setId}
        categories={categories}
        open={runOpen}
        onClose={() => setRunOpen(false)}
        onRun={(id) => { setSelectedRunId(id); setRunOpen(false) }}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// Page root
// ---------------------------------------------------------------------------

export function EvalPage() {
  const [selectedSetId, setSelectedSetId] = useState<string | null>(null)
  const { data: sets } = useEvalSets()

  const activeSetId = selectedSetId ?? (sets?.find((s) => s.is_default) ?? sets?.[0])?.id ?? null

  return (
    <div className="flex h-full w-full overflow-hidden">
      <SetList selectedId={activeSetId} onSelect={setSelectedSetId} />

      <div className="flex-1 overflow-hidden" style={{ background: 'var(--bg-base)' }}>
        {activeSetId
          ? <SetDetail key={activeSetId} setId={activeSetId} />
          : (
            <div className="flex items-center justify-center h-full" style={{ color: 'var(--text-3)' }}>
              <div className="text-center">
                <span className="block mb-4 opacity-20"><Icon name="flask" size={40} /></span>
                <p className="text-[13px]">Select a question set to get started.</p>
              </div>
            </div>
          )}
      </div>
    </div>
  )
}
