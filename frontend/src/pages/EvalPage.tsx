import { useEffect, useRef, useState } from 'react'
import { Icon } from '@/components/ui/Icon'
import { Modal } from '@/components/ui/Modal'
import {
  useAddEvalQuestion,
  useCreateEvalSet,
  useDeleteEvalSet,
  useEvalQuestions,
  useEvalRun,
  useEvalRuns,
  useEvalSets,
  useImportEvalQuestions,
  useTriggerEvalRun,
} from '@/hooks'
import type { EvalRun, EvalRunResult } from '@/types'

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
// Trace detail modal
// ---------------------------------------------------------------------------

function TraceModal({ result, onClose }: { result: EvalRunResult; onClose: () => void }) {
  const steps: Array<{ step?: string; status?: string; duration_ms?: number; decision_by?: string }> =
    result.trace_steps ?? []

  return (
    <Modal open title={`Trace — ${result.question_id}`} onClose={onClose}>
      <div className="flex flex-col gap-4" style={{ maxHeight: '70vh', overflowY: 'auto' }}>
        <div className="grid grid-cols-2 gap-3 text-[12px]">
          <div>
            <span style={{ color: 'var(--text-3)' }}>Route: </span>
            <span className="font-mono" style={{ color: 'var(--text-1)' }}>{result.actual_route ?? '—'}</span>
          </div>
          <div>
            <span style={{ color: 'var(--text-3)' }}>Status: </span>
            <span className="font-mono" style={{ color: 'var(--text-1)' }}>{result.actual_status ?? '—'}</span>
          </div>
          <div>
            <span style={{ color: 'var(--text-3)' }}>Source: </span>
            <span className="font-mono" style={{ color: 'var(--text-1)' }}>{result.source ?? '—'}</span>
          </div>
          <div>
            <span style={{ color: 'var(--text-3)' }}>Model: </span>
            <span className="font-mono" style={{ color: 'var(--text-1)' }}>{result.model_called ?? '—'}</span>
          </div>
          <div>
            <span style={{ color: 'var(--text-3)' }}>Template: </span>
            <span className="font-mono" style={{ color: 'var(--text-1)' }}>{result.template_id ?? '—'}</span>
          </div>
          <div>
            <span style={{ color: 'var(--text-3)' }}>Duration: </span>
            <span className="font-mono" style={{ color: 'var(--text-1)' }}>{Math.round(result.total_duration_ms)} ms</span>
          </div>
        </div>

        {result.error && (
          <div className="px-3 py-2 rounded-[8px] text-[11px]" style={{ background: 'rgba(248,113,113,0.1)', color: '#f87171' }}>
            {result.error}
          </div>
        )}

        {steps.length > 0 && (
          <div>
            <p className={`${labelCls} mb-2`} style={{ color: 'var(--text-3)' }}>Steps</p>
            <div className="flex flex-col gap-1">
              {steps.map((s, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 px-3 py-2 rounded-[6px] text-[11px]"
                  style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-subtle)' }}
                >
                  <span className="font-mono font-semibold" style={{ color: 'var(--accent-text)', minWidth: 160 }}>
                    {s.step}
                  </span>
                  <span
                    className="px-1.5 py-[1px] rounded-[4px] text-[10px]"
                    style={{
                      background: s.status === 'ok' ? 'rgba(34,197,94,0.15)' : 'rgba(248,113,113,0.15)',
                      color: s.status === 'ok' ? '#22c55e' : '#f87171',
                    }}
                  >
                    {s.status}
                  </span>
                  {s.decision_by && (
                    <span style={{ color: 'var(--text-3)' }}>via {s.decision_by}</span>
                  )}
                  {s.duration_ms != null && (
                    <span className="ml-auto" style={{ color: 'var(--text-3)' }}>{Math.round(s.duration_ms)} ms</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {(result.warnings ?? []).length > 0 && (
          <div>
            <p className={`${labelCls} mb-2`} style={{ color: 'var(--text-3)' }}>Warnings</p>
            <ul className="flex flex-col gap-1">
              {result.warnings!.map((w, i) => (
                <li key={i} className="text-[11px]" style={{ color: '#f59e0b' }}>• {String(w)}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Modal>
  )
}

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
                  onClick={(e) => { e.stopPropagation(); deleteSet.mutate(s.id) }}
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

function humanCategory(cat: string) {
  return cat.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// ---------------------------------------------------------------------------
// Category accordion
// ---------------------------------------------------------------------------

function CategorySection({
  category,
  results,
  isLastActive,
  onTrace,
}: {
  category: string
  results: EvalRunResult[]
  isLastActive: boolean
  onTrace: (r: EvalRunResult) => void
}) {
  const passed = results.filter((r) => r.passed).length
  const total = results.length
  const pct = Math.round((passed / total) * 100)
  const hasFail = passed < total

  // Open by default only when there are failures
  const [open, setOpen] = useState(hasFail)

  const accentColor = pct >= 80 ? '#22c55e' : pct >= 50 ? '#f59e0b' : '#f87171'

  return (
    <div
      className="rounded-[8px] overflow-hidden"
      style={{
        border: '1px solid var(--border-default)',
        borderLeft: `3px solid ${accentColor}`,
      }}
    >
      {/* Header */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left"
        style={{ background: 'var(--bg-raised)' }}
      >
        <span
          className="flex-shrink-0 transition-transform duration-150"
          style={{ color: 'var(--text-3)', transform: open ? 'rotate(90deg)' : 'none', display: 'inline-flex' }}
        >
          <Icon name="arrow-right" size={11} />
        </span>

        <span className="flex-1 text-[12px] font-semibold" style={{ color: 'var(--text-1)' }}>
          {humanCategory(category)}
        </span>

        <div className="flex items-center gap-3 flex-shrink-0">
          {/* mini bar */}
          <div className="w-[72px] h-[4px] rounded-full overflow-hidden" style={{ background: 'var(--border-default)' }}>
            <div className="h-full rounded-full" style={{ width: `${pct}%`, background: accentColor }} />
          </div>
          <span className="text-[11px] font-semibold tabular-nums" style={{ color: accentColor, minWidth: 32, textAlign: 'right' }}>
            {pct}%
          </span>
          <span className="text-[11px] tabular-nums" style={{ color: 'var(--text-3)', minWidth: 36, textAlign: 'right' }}>
            {passed}/{total}
          </span>
          <span
            className="text-[10px] px-1.5 py-[1px] rounded font-medium"
            style={{
              background: hasFail ? 'rgba(248,113,113,0.12)' : 'rgba(34,197,94,0.10)',
              color: hasFail ? '#f87171' : '#22c55e',
              minWidth: 52,
              textAlign: 'center',
            }}
          >
            {hasFail ? `${total - passed} fail` : 'all pass'}
          </span>
        </div>
      </button>

      {/* Rows */}
      {open && (
        <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
          {results.map((r, idx) => {
            const isLatest = isLastActive && idx === results.length - 1
            return (
              <div
                key={r.id}
                className="flex items-center gap-2 px-3 py-1.5 group"
                style={{
                  borderTop: idx > 0 ? '1px solid var(--border-subtle)' : undefined,
                  background: isLatest ? 'rgba(99,102,241,0.05)' : undefined,
                }}
                onMouseEnter={(e) => { if (!isLatest) e.currentTarget.style.background = 'var(--bg-raised)' }}
                onMouseLeave={(e) => { e.currentTarget.style.background = isLatest ? 'rgba(99,102,241,0.05)' : '' }}
              >
                {/* icon */}
                <span className="flex-shrink-0 w-4 flex justify-center">
                  {r.passed
                    ? <span style={{ color: '#22c55e' }}><Icon name="check" size={12} /></span>
                    : <span style={{ color: '#f87171' }}><Icon name="x" size={12} /></span>}
                </span>

                {/* question */}
                <span
                  className="flex-1 text-[12px] truncate"
                  style={{ color: r.passed ? 'var(--text-1)' : 'var(--text-1)', direction: 'rtl', textAlign: 'right' }}
                  title={r.question}
                >
                  {r.question}
                </span>

                {/* error inline */}
                {r.error && (
                  <span className="text-[10px] truncate max-w-[140px] flex-shrink-0" style={{ color: '#f87171' }} title={r.error}>
                    {r.error}
                  </span>
                )}

                {/* meta */}
                <div className="flex items-center gap-2 flex-shrink-0">
                  {isLatest && (
                    <span className="text-[9px] px-1 py-[1px] rounded animate-pulse" style={{ background: 'rgba(99,102,241,0.15)', color: '#818cf8' }}>
                      now
                    </span>
                  )}
                  <span className="font-mono text-[10px] tabular-nums" style={{ color: 'var(--text-3)', minWidth: 36 }}>
                    {r.actual_route ?? '—'}
                  </span>
                  <span className="font-mono text-[10px] tabular-nums" style={{ color: 'var(--text-3)', minWidth: 88 }}>
                    {r.actual_status ?? '—'}
                  </span>
                  <span className="text-[10px] tabular-nums" style={{ color: 'var(--text-3)', minWidth: 40, textAlign: 'right' }}>
                    {Math.round(r.total_duration_ms)}ms
                  </span>
                  {(r.trace_steps?.length ?? 0) > 0 ? (
                    <button
                      onClick={() => onTrace(r)}
                      className="text-[10px] px-1.5 py-[1px] rounded opacity-0 group-hover:opacity-100 transition-opacity"
                      style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-3)' }}
                    >
                      trace
                    </button>
                  ) : (
                    <span className="w-[38px]" />
                  )}
                </div>
              </div>
            )
          })}
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
  const [traceResult, setTraceResult] = useState<EvalRunResult | null>(null)

  const { data: run, isLoading } = useEvalRun(runId, isRunning)

  if (isLoading) return <p className="text-[12px] p-4" style={{ color: 'var(--text-3)' }}>Loading…</p>
  if (!run) return null

  const results = run.results ?? []
  const done = results.length
  const pct = passRate(run)
  const overallColor = (pct ?? 0) >= 80 ? '#22c55e' : (pct ?? 0) >= 50 ? '#f59e0b' : '#f87171'

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

      {/* ── Summary bar ── */}
      <div className="flex items-center gap-3 flex-shrink-0 flex-wrap">

        {/* big pass count */}
        <div className="flex items-baseline gap-1.5">
          <span className="text-[22px] font-bold tabular-nums leading-none" style={{ color: overallColor }}>
            {run.passed}
          </span>
          <span className="text-[13px]" style={{ color: 'var(--text-3)' }}>/ {run.total}</span>
          {pct !== null && (
            <span className="text-[12px] font-semibold" style={{ color: overallColor }}>({pct}%)</span>
          )}
        </div>

        <StatusBadge status={run.status} />
        {run.model_name && (
          <span className="text-[10px] px-2 py-[2px] rounded font-mono" style={{ background: 'var(--bg-raised)', color: 'var(--text-3)' }}>
            {run.model_name}
          </span>
        )}

        {/* live progress bar */}
        {isRunning && run.total > 0 && (
          <div className="flex items-center gap-2 flex-1 min-w-[100px]">
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

      {/* ── Accordions ── */}
      <div className="flex-1 overflow-y-auto flex flex-col gap-1.5 pr-0.5">
        {visible.length === 0 && (
          <p className="text-center py-10 text-[12px]" style={{ color: 'var(--text-3)' }}>No results yet.</p>
        )}
        {visible.map((cat) => (
          <CategorySection
            key={cat}
            category={cat}
            results={byCategory[cat]}
            isLastActive={isRunning && cat === lastCategory}
            onTrace={setTraceResult}
          />
        ))}
      </div>

      {traceResult && (
        <TraceModal result={traceResult} onClose={() => setTraceResult(null)} />
      )}
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

        {/* Results */}
        <div className="flex-1 overflow-hidden">
          {displayRunId
            ? <RunResults runId={displayRunId} isRunning={isRunning} />
            : (
              <div className="flex items-center justify-center h-full" style={{ color: 'var(--text-3)' }}>
                <div className="text-center">
                  <span className="block mb-3 opacity-30"><Icon name="flask" size={32} /></span>
                  <p className="text-[13px]">
                    {questions?.length
                      ? 'Press "Run eval" to start the first evaluation.'
                      : 'Add or import questions first, then run the evaluation.'}
                  </p>
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

  useEffect(() => {
    if (selectedSetId || !sets?.length) return
    const defaultSet = sets.find((s) => s.is_default) ?? sets[0]
    if (defaultSet) setSelectedSetId(defaultSet.id)
  }, [sets, selectedSetId])

  return (
    <div className="flex h-full w-full overflow-hidden">
      <SetList selectedId={selectedSetId} onSelect={setSelectedSetId} />

      <div className="flex-1 overflow-hidden" style={{ background: 'var(--bg-base)' }}>
        {selectedSetId
          ? <SetDetail key={selectedSetId} setId={selectedSetId} />
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
