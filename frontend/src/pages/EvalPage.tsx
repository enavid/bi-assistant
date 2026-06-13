import React, { useEffect, useRef, useState } from 'react'
import { Icon } from '@/components/ui/Icon'
import { Modal, ConfirmDialog } from '@/components/ui/Modal'
import { InlineLoader, Spinner } from '@/components/ui/Spinner'
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
  useOllamaConnectionModels,
  useOllamaConnections,
  useTriggerEvalRun,
} from '@/hooks'
import type { EvalQuestion, EvalRun, EvalRunResult } from '@/types'

// ---------------------------------------------------------------------------
// Shared helpers
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

function humanCategory(cat: string) {
  return cat.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function StatusBadge({ status }: { status: EvalRun['status'] }) {
  const map: Record<EvalRun['status'], { label: string; color: string; bg: string }> = {
    pending: { label: 'pending', color: 'var(--text-3)',   bg: 'var(--bg-raised)' },
    running: { label: 'running…',color: '#f59e0b',          bg: 'rgba(245,158,11,0.12)' },
    done:    { label: 'done',    color: '#22c55e',          bg: 'rgba(34,197,94,0.12)' },
    failed:  { label: 'failed',  color: '#f87171',          bg: 'rgba(248,113,113,0.12)' },
  }
  const s = map[status] ?? map.failed
  return (
    <span className="text-[10px] font-semibold px-1.5 py-[2px] rounded-[4px]" style={{ color: s.color, background: s.bg }}>
      {s.label}
    </span>
  )
}

const inputCls  = 'px-3 py-2.5 rounded-[8px] text-[13px] outline-none w-full'
const inputStyle = { background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-1)' }
const labelCls  = 'text-[11px] font-semibold uppercase tracking-[0.6px]'

// ---------------------------------------------------------------------------
// Results: trace panel
// ---------------------------------------------------------------------------

const EVAL_ROUTE_STYLE: Record<string, { bg: string; text: string; border: string }> = {
  SQL:                  { bg: 'var(--accent-bg)',  text: 'var(--accent-text)',  border: 'var(--accent-border)' },
  GAP:                  { bg: 'var(--amber-bg)',   text: 'var(--amber)',        border: 'var(--amber-border)' },
  REJECT:               { bg: 'var(--red-bg)',     text: 'var(--red)',          border: 'var(--red-border)' },
  NEEDS_CLARIFICATION:  { bg: 'var(--bg-raised)',  text: 'var(--text-3)',       border: 'var(--border-default)' },
  _default:             { bg: 'var(--bg-raised)',  text: 'var(--text-3)',       border: 'var(--border-subtle)' },
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
    <div className="mt-1 rounded-[6px] overflow-hidden text-[10px] font-mono" style={{ border: '1px solid var(--border-subtle)', background: 'var(--bg-raised)' }}>
      <div className="grid" style={{ gridTemplateColumns: 'minmax(130px, 1.8fr) minmax(90px, 1fr) 52px 96px' }}>
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
              <div className="px-2.5 py-[5px]" style={{ color: 'var(--text-2)', borderBottom: rowBorder }}>{t.step ?? '—'}</div>
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

// ---------------------------------------------------------------------------
// Results: question row (inside accordion)
// ---------------------------------------------------------------------------

function ResultQuestionRow({ r, isLatest }: { r: EvalRunResult; isLatest: boolean }) {
  const [traceOpen, setTraceOpen] = useState(false)
  const routeStyle = EVAL_ROUTE_STYLE[r.actual_route ?? ''] ?? EVAL_ROUTE_STYLE._default
  const statusLabel = r.actual_status ? (EVAL_STATUS_LABEL[r.actual_status] ?? r.actual_status) : null
  const hasTrace = (r.trace_steps?.length ?? 0) > 0

  return (
    <div className="flex flex-col gap-[3px]">
      <div className="flex gap-3 items-start">
        <div className="w-7 h-7 rounded-[8px] flex items-center justify-center flex-shrink-0 mt-0.5"
          style={r.passed
            ? { background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }
            : { background: 'var(--red-bg)', color: 'var(--red)', border: '1px solid var(--red-border)' }}>
          <Icon name={r.passed ? 'check' : 'x'} size={12} />
        </div>
        <div className="flex-1 px-4 py-2 text-[13px] leading-[1.5] min-w-0"
          style={{
            background: 'var(--bg-raised)', border: '1px solid var(--border-default)',
            borderRadius: '4px 18px 18px 18px', direction: 'rtl', textAlign: 'right', color: 'var(--text-1)',
            outline: isLatest ? '2px solid var(--accent-border)' : undefined, outlineOffset: '1px',
          }}>
          {r.question}
        </div>
      </div>
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
          <button onClick={() => setTraceOpen((v) => !v)}
            className="text-[10px] font-mono px-1.5 py-[3px] rounded-[4px]"
            style={{
              background: traceOpen ? 'var(--accent-bg)' : 'var(--bg-raised)',
              color: traceOpen ? 'var(--accent-text)' : 'var(--text-3)',
              border: `1px solid ${traceOpen ? 'var(--accent-border)' : 'var(--border-default)'}`,
            }}>
            {traceOpen ? '↑' : '↓'} trace
          </button>
        )}
      </div>
      {traceOpen && hasTrace && (
        <div className="ml-10"><EvalTracePanel steps={r.trace_steps!} /></div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Results: category accordion section
// ---------------------------------------------------------------------------

function CategoryResultSection({
  category, results, isLastActive,
}: {
  category: string; results: EvalRunResult[]; isLastActive: boolean
}) {
  const passed = results.filter((r) => r.passed).length
  const total  = results.length
  const pct    = Math.round((passed / total) * 100)
  const hasFail = passed < total
  const [open, setOpen] = useState(hasFail)

  return (
    <div style={{ borderBottom: '1px solid var(--border-subtle)' }}>
      <button onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2.5 px-4 py-2 text-left"
        style={{ background: 'var(--bg-raised)' }}
        onMouseEnter={(e) => (e.currentTarget.style.opacity = '0.85')}
        onMouseLeave={(e) => (e.currentTarget.style.opacity = '1')}>
        <span style={{ color: 'var(--text-3)', display: 'inline-flex', flexShrink: 0, transition: 'transform 0.15s', transform: open ? 'rotate(90deg)' : 'none' }}>
          <Icon name="arrow-right" size={10} />
        </span>
        <span className="flex-1 min-w-0 truncate text-[12px] font-semibold mr-2" style={{ color: 'var(--text-1)' }}>{humanCategory(category)}</span>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-[11px] tabular-nums hidden sm:inline" style={{ color: 'var(--text-3)' }}>
            {passed}/{total}
          </span>
          {hasFail
            ? <span className="text-[10px] px-1.5 py-[1px] rounded tabular-nums font-semibold"
                style={{ background: 'var(--red-bg)', color: 'var(--red)', border: '1px solid var(--red-border)' }}>
                {total - passed} fail
              </span>
            : <span className="text-[10px] px-1.5 py-[1px] rounded font-semibold"
                style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }}>
                {pct}%
              </span>}
        </div>
      </button>
      {open && (
        <div className="flex flex-col gap-2.5 px-4 py-3">
          {results.map((r, idx) => (
            <ResultQuestionRow key={r.id} r={r} isLatest={isLastActive && idx === results.length - 1} />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Results panel (used inside RunsTab)
// ---------------------------------------------------------------------------

function RunResults({ runId, isRunning }: { runId: string; isRunning: boolean }) {
  const [filterPassed, setFilterPassed] = useState<'all' | 'pass' | 'fail'>('all')
  const { data: run, isLoading } = useEvalRun(runId, isRunning)

  if (isLoading) return <div className="flex justify-center p-6"><Spinner size={22} /></div>
  if (!run) return null

  const results  = run.results ?? []
  const done     = results.length
  const pct      = passRate(run)
  const pctColor = pct === null ? 'var(--text-3)' : pct >= 80 ? '#22c55e' : pct >= 50 ? '#f59e0b' : '#f87171'

  const categoryOrder: string[] = []
  const byCategory: Record<string, EvalRunResult[]> = {}
  for (const r of results) {
    const cat = r.category ?? 'other'
    if (!byCategory[cat]) { byCategory[cat] = []; categoryOrder.push(cat) }
    byCategory[cat].push(r)
  }

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
      {/* Summary card */}
      <div className="flex items-center gap-3 flex-shrink-0 px-4 py-3 rounded-[10px] flex-wrap"
        style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)' }}>
        <div className="flex flex-col items-center flex-shrink-0" style={{ minWidth: 48 }}>
          <span className="text-[22px] font-bold tabular-nums leading-none" style={{ color: pctColor }}>
            {pct !== null ? `${pct}%` : '—'}
          </span>
          <span className="text-[9px] uppercase tracking-wide mt-0.5" style={{ color: 'var(--text-3)' }}>pass rate</span>
        </div>
        <div className="w-px self-stretch flex-shrink-0" style={{ background: 'var(--border-subtle)' }} />
        <div className="flex flex-col gap-1 flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <StatusBadge status={run.status} />
            {run.model_name && (
              <span className="text-[10px] font-mono truncate" style={{ color: 'var(--text-3)' }}>{run.model_name}</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-[12px] tabular-nums" style={{ color: 'var(--text-2)' }}>
              <span className="font-semibold" style={{ color: '#22c55e' }}>{run.passed}</span>
              <span style={{ color: 'var(--text-3)' }}>/{run.total} passed</span>
            </span>
            {run.failed > 0 && (
              <span className="text-[12px] tabular-nums font-semibold" style={{ color: '#f87171' }}>
                {run.failed} failed
              </span>
            )}
          </div>
        </div>
        {isRunning && run.total > 0 && (
          <div className="flex items-center gap-2 flex-shrink-0 min-w-[90px]">
            <div className="flex-1 h-[4px] rounded-full overflow-hidden" style={{ background: 'var(--border-default)' }}>
              <div className="h-full rounded-full transition-all duration-700"
                style={{ width: `${Math.round((done / run.total) * 100)}%`, background: 'var(--accent)' }} />
            </div>
            <span className="text-[10px] tabular-nums" style={{ color: 'var(--text-3)' }}>{done}/{run.total}</span>
          </div>
        )}
        <div className="flex gap-1 flex-shrink-0 ml-auto">
          {(['all', 'pass', 'fail'] as const).map((f) => (
            <button key={f} onClick={() => setFilterPassed(f)}
              className="px-2.5 py-1 rounded-[6px] text-[11px] font-medium"
              style={{
                background: filterPassed === f ? 'var(--accent-bg)' : 'var(--bg-surface)',
                color: filterPassed === f ? 'var(--accent-text)' : 'var(--text-2)',
                border: `1px solid ${filterPassed === f ? 'var(--accent-border)' : 'var(--border-default)'}`,
              }}>
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Accordion */}
      <div className="flex-1 overflow-y-auto rounded-[8px]"
        style={{ border: '1px solid var(--border-default)', background: 'var(--bg-surface)' }}>
        {visible.length === 0 && (
          <p className="text-center py-10 text-[12px]" style={{ color: 'var(--text-3)' }}>No results yet.</p>
        )}
        {visible.map((cat) => (
          <CategoryResultSection
            key={cat} category={cat} results={byCategory[cat]}
            isLastActive={isRunning && cat === lastCategory}
          />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Library: question row (CRUD view)
// ---------------------------------------------------------------------------

function QuestionLibraryRow({
  q, setId, canRun, onRun,
}: {
  q: EvalQuestion; setId: string; canRun: boolean; onRun: () => void
}) {
  const deleteQ = useDeleteEvalQuestion()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const routeStyle = q.expected_route
    ? (EVAL_ROUTE_STYLE[q.expected_route] ?? EVAL_ROUTE_STYLE._default)
    : null

  return (
    <div
      className="group flex items-center gap-2.5 px-4 py-2"
      style={{ borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-surface)' }}
      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-raised)')}
      onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--bg-surface)')}
    >
      <span className="flex-shrink-0 opacity-30"><Icon name="list" size={12} /></span>
      <span className="flex-1 text-[12.5px] leading-snug min-w-0"
        style={{ color: 'var(--text-1)', direction: 'rtl', textAlign: 'right' }}>
        {q.question}
      </span>
      <div className="flex items-center gap-1.5 flex-shrink-0">
        {routeStyle && (
          <span className="text-[10px] font-mono px-1.5 py-[2px] rounded-[4px]"
            style={{ background: routeStyle.bg, color: routeStyle.text, border: `1px solid ${routeStyle.border}` }}>
            {q.expected_route}
          </span>
        )}
        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={onRun}
            disabled={!canRun}
            title="Run this question"
            className="w-6 h-6 rounded-[5px] flex items-center justify-center transition-opacity disabled:opacity-30"
            style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }}
          >
            <Icon name="play" size={9} />
          </button>
          <button
            onClick={() => setConfirmDelete(true)}
            title="Delete"
            className="w-6 h-6 rounded-[5px] flex items-center justify-center"
            style={{ color: 'var(--text-3)' }}
            onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--red)')}
            onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-3)')}
          >
            <Icon name="trash" size={11} />
          </button>
        </div>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        title="Delete question"
        message={`Question "${q.question_id}" will be permanently deleted.`}
        confirmLabel="Delete"
        onConfirm={() => deleteQ.mutate({ setId, questionId: q.question_id })}
        onClose={() => setConfirmDelete(false)}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Library: category card
// ---------------------------------------------------------------------------

function CategoryLibraryCard({
  category, questions, setId, canRun, onRunCategory, onRunQuestion,
}: {
  category: string
  questions: EvalQuestion[]
  setId: string
  canRun: boolean
  onRunCategory: (cat: string) => void
  onRunQuestion: (questionId: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [addOpen, setAddOpen] = useState(false)

  const headerRadius = open ? '10px 10px 0 0' : '10px'

  return (
    <div>
      {/* Header — self-contained card with its own full border */}
      <div
        className="flex items-center gap-2 px-3 py-2 cursor-pointer select-none"
        style={{
          background: 'var(--bg-raised)',
          border: '1px solid var(--border-default)',
          borderRadius: headerRadius,
        }}
        onClick={() => setOpen((v) => !v)}
      >
        <span style={{ color: 'var(--text-3)', transition: 'transform .15s', transform: open ? 'rotate(90deg)' : 'none', display: 'inline-flex', flexShrink: 0 }}>
          <Icon name="arrow-right" size={10} />
        </span>
        <span className="flex-1 min-w-0 truncate text-[12px] font-semibold" style={{ color: 'var(--text-1)' }}>
          {humanCategory(category)}
        </span>
        <span className="text-[10px] px-1.5 py-[1px] rounded-[4px] flex-shrink-0"
          style={{ background: 'var(--bg-base)', border: '1px solid var(--border-default)', color: 'var(--text-3)' }}>
          {questions.length}
        </span>
        <div className="flex gap-1.5 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={() => setAddOpen(true)}
            className="h-6 px-2 rounded-[5px] text-[10px] font-medium flex items-center gap-1 transition-opacity hover:opacity-75"
            style={{ background: 'var(--bg-base)', border: '1px solid var(--border-default)', color: 'var(--text-3)' }}
          >
            <Icon name="plus" size={9} />
            <span className="hidden sm:inline">Add</span>
          </button>
          <button
            onClick={() => onRunCategory(category)}
            disabled={!canRun}
            className="h-6 px-2 rounded-[5px] text-[10px] font-semibold flex items-center gap-1 transition-opacity hover:opacity-80 disabled:opacity-30"
            style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }}
          >
            <Icon name="play" size={9} />
            Run
          </button>
        </div>
      </div>

      {/* Questions body — its own border continuing from header */}
      {open && (
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-default)',
            borderTop: 'none',
            borderRadius: '0 0 10px 10px',
          }}
        >
          {questions.map((q) => (
            <QuestionLibraryRow
              key={q.id} q={q} setId={setId} canRun={canRun}
              onRun={() => onRunQuestion(q.id)}
            />
          ))}
        </div>
      )}

      <AddQuestionModal
        setId={setId} open={addOpen} onClose={() => setAddOpen(false)}
        defaultCategory={category}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Library tab
// ---------------------------------------------------------------------------

function LibraryTab({
  setId, questions, canRun, onRunCategory, onRunQuestion,
}: {
  setId: string
  questions: EvalQuestion[]
  canRun: boolean
  onRunCategory: (cat: string) => void
  onRunQuestion: (questionId: string) => void
}) {
  const [addOpen, setAddOpen] = useState(false)

  const categoryOrder: string[] = []
  const byCategory: Record<string, EvalQuestion[]> = {}
  for (const q of questions) {
    const cat = q.category ?? ''
    if (!byCategory[cat]) { byCategory[cat] = []; categoryOrder.push(cat) }
    byCategory[cat].push(q)
  }
  const sortedCats = [...categoryOrder].sort((a, b) => a.localeCompare(b))

  return (
    <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
      {sortedCats.map((cat) => (
        <CategoryLibraryCard
          key={cat} category={cat} questions={byCategory[cat]}
          setId={setId} canRun={canRun}
          onRunCategory={onRunCategory}
          onRunQuestion={onRunQuestion}
        />
      ))}

      {!questions.length && (
        <div className="flex flex-col items-center justify-center flex-1 gap-3 py-16" style={{ color: 'var(--text-3)' }}>
          <span className="opacity-20"><Icon name="flask" size={36} /></span>
          <p className="text-[13px]">No questions yet. Add some or import a JSON file.</p>
        </div>
      )}

      <button
        onClick={() => setAddOpen(true)}
        className="flex items-center justify-center gap-2 px-4 py-3 rounded-[10px] text-[12px] transition-colors"
        style={{ border: '1px dashed var(--border-default)', color: 'var(--text-3)', background: 'transparent' }}
        onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent-border)'; e.currentTarget.style.color = 'var(--accent-text)' }}
        onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border-default)'; e.currentTarget.style.color = 'var(--text-3)' }}
      >
        <Icon name="plus" size={13} />
        Add question to new category
      </button>

      <AddQuestionModal setId={setId} open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Runs tab: history item
// ---------------------------------------------------------------------------

function RunHistoryItem({ run, selected, onClick }: { run: EvalRun; selected: boolean; onClick: () => void }) {
  const pct = passRate(run)
  const pctColor = pct === null ? 'var(--text-3)' : pct >= 80 ? '#22c55e' : pct >= 50 ? '#f59e0b' : '#f87171'

  return (
    <button
      onClick={onClick}
      className="w-full text-left px-3 py-2.5 rounded-[8px] flex flex-col gap-1 transition-colors"
      style={{
        background: selected ? 'var(--accent-bg)' : 'transparent',
        border: `1px solid ${selected ? 'var(--accent-border)' : 'transparent'}`,
      }}
      onMouseEnter={(e) => { if (!selected) e.currentTarget.style.background = 'var(--bg-raised)' }}
      onMouseLeave={(e) => { if (!selected) e.currentTarget.style.background = 'transparent' }}
    >
      <div className="flex items-center gap-2">
        {run.status === 'running' || run.status === 'pending'
          ? <Spinner size={11} />
          : <span className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ background: run.status === 'failed' ? 'var(--red)' : pctColor }} />}
        <span className="text-[13px] font-bold tabular-nums" style={{ color: run.status === 'done' ? pctColor : 'var(--text-3)' }}>
          {run.status === 'done' && pct !== null ? `${pct}%` : run.status}
        </span>
        <StatusBadge status={run.status} />
      </div>
      <span className="text-[10px]" style={{ color: 'var(--text-3)' }}>{fmtDate(run.created_at)}</span>
      {run.model_name && (
        <span className="text-[9px] font-mono" style={{ color: 'var(--text-3)' }}>{run.model_name}</span>
      )}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Runs tab
// ---------------------------------------------------------------------------

function RunsTab({
  setId, questions, runs, runsLoading, selectedRunId, onSelectRun, initialScope,
}: {
  setId: string
  questions: EvalQuestion[]
  runs: EvalRun[] | undefined
  runsLoading: boolean
  selectedRunId: string | null
  onSelectRun: (id: string) => void
  initialScope: string
}) {
  const [scope, setScope] = useState(initialScope)
  const [modelName, setModelName] = useState('')
  const [runError, setRunError] = useState('')
  const trigger = useTriggerEvalRun()

  const { data: ollamaConns } = useOllamaConnections()
  const activeConn = ollamaConns?.find((c) => c.is_active) ?? null
  const { data: modelsData } = useOllamaConnectionModels(activeConn?.id ?? '', !!activeConn)
  const availableModels = modelsData?.models?.map((m) => m.name) ?? []

  const categories = [...new Set(questions.map((q) => q.category).filter(Boolean))] as string[]

  const activeRun   = runs?.find((r) => r.status === 'running' || r.status === 'pending')
  const displayRunId = selectedRunId ?? runs?.[0]?.id ?? null
  const displayRun   = runs?.find((r) => r.id === displayRunId) ?? null
  const isRunning    = displayRun?.status === 'running' || displayRun?.status === 'pending'

  useEffect(() => { setScope(initialScope) }, [initialScope])

  async function handleRun() {
    setRunError('')
    try {
      const run = await trigger.mutateAsync({
        setId,
        category: scope || undefined,
        model_name: modelName || undefined,
      })
      onSelectRun(run.id)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setRunError(msg ?? 'Failed to start run')
    }
  }

  return (
    <div className="flex flex-col sm:flex-row flex-1 overflow-hidden">

      {/* ── Config + History panel ── */}
      <div
        className="flex-shrink-0 flex flex-col sm:w-[220px] sm:overflow-hidden border-b sm:border-b-0 sm:border-r"
        style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-default)' }}
      >
        {/* Config — compact row on mobile, stacked on desktop */}
        <div
          className="flex sm:flex-col gap-2 sm:gap-3 p-3 flex-shrink-0 flex-wrap"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}
        >
          <div className="flex flex-col gap-1 flex-1 min-w-[120px]">
            <label className={labelCls} style={{ color: 'var(--text-3)' }}>Scope</label>
            <select value={scope} onChange={(e) => setScope(e.target.value)}
              className="px-2 py-1.5 rounded-[7px] text-[12px] outline-none"
              style={inputStyle}>
              <option value="">All ({questions.length})</option>
              {categories.map((cat) => {
                const count = questions.filter((q) => q.category === cat).length
                return <option key={cat} value={cat}>{humanCategory(cat)} ({count})</option>
              })}
            </select>
          </div>

          <div className="flex flex-col gap-1 flex-1 min-w-[120px]">
            <label className={labelCls} style={{ color: 'var(--text-3)' }}>Model</label>
            {!activeConn ? (
              <p className="text-[11px] py-1" style={{ color: '#f87171' }}>No Ollama</p>
            ) : (
              <select value={modelName} onChange={(e) => setModelName(e.target.value)}
                className="px-2 py-1.5 rounded-[7px] text-[12px] outline-none"
                style={inputStyle}>
                <option value="">Default</option>
                {availableModels.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            )}
          </div>

          <div className="flex flex-col justify-end w-full sm:w-auto">
            {runError && <p className="text-[10px] mb-1" style={{ color: '#f87171' }}>{runError}</p>}
            <button
              onClick={handleRun}
              disabled={!!activeRun || trigger.isPending || !questions.length}
              className="h-8 flex items-center justify-center gap-2 rounded-[8px] text-[12px] font-semibold transition-opacity hover:opacity-88 disabled:opacity-40 w-full"
              style={{ background: 'var(--accent)', color: '#fff' }}
            >
              {activeRun || trigger.isPending ? <Spinner size={12} /> : <Icon name="play" size={12} />}
              {activeRun ? 'Running…' : 'Run now'}
            </button>
          </div>
        </div>

        {/* History */}
        <div className="overflow-y-auto flex-1" style={{ maxHeight: 'min(160px, 40vh)' }}>
          <p className={`${labelCls} px-3 pt-2.5 pb-1`} style={{ color: 'var(--text-3)' }}>History</p>
          {runsLoading && <div className="px-3"><InlineLoader /></div>}
          {!runsLoading && !runs?.length && (
            <p className="text-[11px] px-3 pb-3" style={{ color: 'var(--text-3)' }}>No runs yet.</p>
          )}
          <div className="px-2 pb-2 flex flex-col gap-0.5">
            {runs?.map((r) => (
              <RunHistoryItem
                key={r.id} run={r}
                selected={r.id === displayRunId}
                onClick={() => onSelectRun(r.id)}
              />
            ))}
          </div>
        </div>
      </div>

      {/* ── Results area ── */}
      <div className="flex-1 overflow-hidden p-3 sm:p-4">
        {displayRunId
          ? <RunResults runId={displayRunId} isRunning={isRunning} />
          : (
            <div className="flex flex-col items-center justify-center h-full gap-3" style={{ color: 'var(--text-3)' }}>
              <span className="opacity-20"><Icon name="flask" size={36} /></span>
              <p className="text-[13px]">Configure scope and model, then click Run now.</p>
            </div>
          )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------

function ImportModal({ setId, open, onClose }: { setId: string; open: boolean; onClose: () => void }) {
  const importQ = useImportEvalQuestions()
  const fileRef = useRef<HTMLInputElement>(null)
  const [text, setText] = useState('')
  const [error, setError] = useState('')

  async function handleImport() {
    setError('')
    let parsed: unknown
    try { parsed = JSON.parse(text) } catch { setError('Invalid JSON'); return }
    if (!Array.isArray(parsed)) { setError('Expected a JSON array of questions'); return }
    try {
      await importQ.mutateAsync({ setId, questions: parsed as never })
      setText('')
      onClose()
    } catch { setError('Import failed — check the format') }
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
        <button onClick={() => fileRef.current?.click()}
          className="flex items-center gap-2 px-3 py-2 rounded-[8px] text-[12px] transition-opacity hover:opacity-70"
          style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}>
          <Icon name="notes" size={14} />
          Choose JSON file…
        </button>
        <input ref={fileRef} type="file" accept=".json" className="hidden" onChange={handleFile} />
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={8}
          placeholder='[{"question_id": "q1", "question": "...", "category": "demographics"}]'
          className="px-3 py-2.5 rounded-[8px] text-[11px] font-mono outline-none resize-none"
          style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-1)' }} />
        {error && <p className="text-[11px]" style={{ color: '#f87171' }}>{error}</p>}
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium"
            style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}>
            Cancel
          </button>
          <button onClick={handleImport} disabled={!text.trim() || importQ.isPending}
            className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium transition-opacity hover:opacity-90 disabled:opacity-40"
            style={{ background: 'var(--accent)', color: '#fff' }}>
            {importQ.isPending ? 'Importing…' : 'Import'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

function AddQuestionModal({
  setId, open, onClose, defaultCategory = '',
}: {
  setId: string; open: boolean; onClose: () => void; defaultCategory?: string
}) {
  const addQ = useAddEvalQuestion()
  const [question, setQuestion] = useState('')
  const [category, setCategory] = useState(defaultCategory)
  const [expectedRoute, setExpectedRoute] = useState('')
  const [error, setError] = useState('')

  useEffect(() => { if (open) setCategory(defaultCategory) }, [open, defaultCategory])

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
      setExpectedRoute('')
      onClose()
    } catch { setError('Failed to add question') }
  }

  return (
    <Modal open={open} title="Add question" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label className={labelCls} style={{ color: 'var(--text-3)' }}>Question</label>
          <textarea autoFocus value={question} onChange={(e) => setQuestion(e.target.value)} rows={3}
            placeholder="تعداد کل کارکنان چقدر است؟"
            className="px-3 py-2.5 rounded-[8px] text-[13px] outline-none resize-none" style={inputStyle} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5">
            <label className={labelCls} style={{ color: 'var(--text-3)' }}>Category</label>
            <input value={category} onChange={(e) => setCategory(e.target.value)}
              placeholder="e.g. demographics" className={inputCls} style={inputStyle} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className={labelCls} style={{ color: 'var(--text-3)' }}>Expected route</label>
            <input value={expectedRoute} onChange={(e) => setExpectedRoute(e.target.value)}
              placeholder="e.g. SQL" className={inputCls} style={inputStyle} />
          </div>
        </div>
        {error && <p className="text-[11px]" style={{ color: '#f87171' }}>{error}</p>}
        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium"
            style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}>
            Cancel
          </button>
          <button onClick={handleAdd} disabled={!question.trim() || addQ.isPending}
            className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium transition-opacity hover:opacity-90 disabled:opacity-40"
            style={{ background: 'var(--accent)', color: '#fff' }}>
            {addQ.isPending ? 'Adding…' : 'Add'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Set detail panel (right)
// ---------------------------------------------------------------------------

function SetDetail({ setId, onBack, onOpenSidebar }: { setId: string; onBack?: () => void; onOpenSidebar?: () => void }) {
  const { data: sets }                          = useEvalSets()
  const { data: questions }                     = useEvalQuestions(setId)
  const { data: runs, isLoading: runsLoading }  = useEvalRuns(setId)
  const trigger                                 = useTriggerEvalRun()

  const [activeTab, setActiveTab]         = useState<'library' | 'runs'>('library')
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [runScope, setRunScope]           = useState('')
  const [importOpen, setImportOpen]       = useState(false)

  const set       = sets?.find((s) => s.id === setId)
  const activeRun = runs?.find((r) => r.status === 'running' || r.status === 'pending')
  const canRun    = !activeRun && !!questions?.length

  function handleRunCategory(category: string) {
    setRunScope(category)
    setActiveTab('runs')
  }

  async function handleRunQuestion(questionId: string) {
    try {
      const run = await trigger.mutateAsync({ setId, question_ids: [questionId] })
      setSelectedRunId(run.id)
      setActiveTab('runs')
    } catch {
      // error visible via trigger.error if needed
    }
  }

  return (
    <>
      <div className="flex-1 flex flex-col h-full overflow-hidden">

        {/* ── Header ── */}
        <div className="h-[52px] px-4 flex items-center gap-2.5 flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)' }}>
          {onBack && (
            <button onClick={onBack}
              className="md:hidden w-7 h-7 flex items-center justify-center rounded-[7px] flex-shrink-0"
              style={{ color: 'var(--text-2)', border: '1px solid var(--border-default)', background: 'var(--bg-raised)' }}>
              <Icon name="arrow-left" size={13} />
            </button>
          )}
          {onOpenSidebar && (
            <button onClick={onOpenSidebar}
              className="md:hidden w-7 h-7 flex items-center justify-center rounded-[7px] flex-shrink-0"
              style={{ color: 'var(--text-2)' }}>
              <Icon name="menu" size={15} />
            </button>
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2 min-w-0">
              <h2 className="text-[14px] font-semibold truncate" style={{ color: 'var(--text-1)' }}>
                {set?.name ?? '…'}
              </h2>
              <span className="text-[11px] flex-shrink-0" style={{ color: 'var(--text-3)' }}>
                {questions?.length ?? 0} questions
              </span>
            </div>
          </div>
          <button onClick={() => setImportOpen(true)}
            className="h-7 px-2.5 flex items-center gap-1.5 rounded-[7px] text-[12px] font-medium transition-opacity hover:opacity-80"
            style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}>
            <Icon name="notes" size={12} />
            <span className="hidden sm:inline">Import</span>
          </button>
        </div>

        {/* ── Tabs ── */}
        <div className="flex flex-shrink-0 px-4"
          style={{ borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)' }}>
          {(['library', 'runs'] as const).map((tab) => (
            <button key={tab} onClick={() => setActiveTab(tab)}
              className="py-2.5 px-3 text-[12px] font-medium capitalize border-b-2 transition-colors"
              style={{
                marginBottom: '-1px',
                borderBottomColor: activeTab === tab ? 'var(--accent)' : 'transparent',
                color: activeTab === tab ? 'var(--accent-text)' : 'var(--text-3)',
                background: 'none', border: 'none',
                borderBottom: `2px solid ${activeTab === tab ? 'var(--accent)' : 'transparent'}`,
              }}>
              {tab === 'library' ? 'Library' : 'Test Runs'}
            </button>
          ))}
        </div>

        {/* ── Tab content ── */}
        {activeTab === 'library' && (
          <LibraryTab
            setId={setId}
            questions={questions ?? []}
            canRun={canRun}
            onRunCategory={handleRunCategory}
            onRunQuestion={handleRunQuestion}
          />
        )}
        {activeTab === 'runs' && (
          <RunsTab
            setId={setId}
            questions={questions ?? []}
            runs={runs}
            runsLoading={runsLoading}
            selectedRunId={selectedRunId}
            onSelectRun={setSelectedRunId}
            initialScope={runScope}
          />
        )}
      </div>

      <ImportModal setId={setId} open={importOpen} onClose={() => setImportOpen(false)} />
    </>
  )
}

// ---------------------------------------------------------------------------
// Set list panel (left)
// ---------------------------------------------------------------------------

function SetList({
  selectedId, onSelect, onOpenSidebar,
}: {
  selectedId: string | null
  onSelect: (id: string) => void
  onOpenSidebar?: () => void
}) {
  const { data: sets, isLoading } = useEvalSets()
  const createSet  = useCreateEvalSet()
  const deleteSet  = useDeleteEvalSet()
  const [newOpen, setNewOpen]     = useState(false)
  const [name, setName]           = useState('')
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
      <div className="w-full md:w-[220px] md:min-w-[220px] flex flex-col h-full"
        style={{ borderRight: '1px solid var(--border-default)', background: 'var(--bg-surface)' }}>
        <div className="h-[52px] px-3 flex items-center gap-2 flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          {onOpenSidebar && (
            <button onClick={onOpenSidebar}
              className="md:hidden w-7 h-7 flex items-center justify-center rounded-[7px] flex-shrink-0"
              style={{ color: 'var(--text-2)' }}>
              <Icon name="menu" size={15} />
            </button>
          )}
          <span className={`${labelCls} flex-1`} style={{ color: 'var(--text-3)' }}>Question Sets</span>
          <button onClick={() => setNewOpen(true)}
            className="w-6 h-6 rounded-[6px] flex items-center justify-center transition-opacity hover:opacity-70"
            style={{ background: 'var(--accent)', color: '#fff' }} title="New set">
            <Icon name="plus" size={13} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {isLoading && <InlineLoader />}
          {!isLoading && !sets?.length && (
            <p className="text-[11px] px-2 py-3 text-center" style={{ color: 'var(--text-3)' }}>No sets yet.</p>
          )}
          {sets?.map((s) => {
            const active = s.id === selectedId
            return (
              <div key={s.id} onClick={() => onSelect(s.id)}
                className="group flex items-center gap-2 px-2.5 py-2.5 rounded-[8px] mb-0.5 cursor-pointer transition-colors"
                style={{ background: active ? 'var(--accent-bg)' : 'transparent' }}
                onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = 'var(--bg-raised)' }}
                onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent' }}>
                <span style={{ color: active ? 'var(--accent-text)' : 'var(--text-3)', flexShrink: 0 }}>
                  <Icon name="flask" size={14} />
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-[12px] font-medium truncate" style={{ color: active ? 'var(--accent-text)' : 'var(--text-1)' }}>
                    {s.name}
                    {s.is_default && (
                      <span className="ml-1 text-[9px] px-1 py-[1px] rounded"
                        style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)' }}>
                        default
                      </span>
                    )}
                  </p>
                  <p className="text-[10px]" style={{ color: 'var(--text-3)' }}>{s.question_count} questions</p>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); setPendingDeleteSet({ id: s.id, name: s.name }) }}
                  className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                  style={{ color: 'var(--text-3)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = '#f87171')}
                  onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-3)')}>
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
            <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleCreate() }}
              placeholder="e.g. HR questions" className={inputCls} style={inputStyle} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className={labelCls} style={{ color: 'var(--text-3)' }}>Description</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional" className={inputCls} style={inputStyle} />
          </div>
          <div className="flex gap-2 pt-1">
            <button onClick={() => setNewOpen(false)} className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium"
              style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}>
              Cancel
            </button>
            <button onClick={handleCreate} disabled={!name.trim() || createSet.isPending}
              className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium transition-opacity hover:opacity-90 disabled:opacity-40"
              style={{ background: 'var(--accent)', color: '#fff' }}>
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
// Page root
// ---------------------------------------------------------------------------

export function EvalPage({ onOpenSidebar }: { onOpenSidebar?: () => void }) {
  const [selectedSetId, setSelectedSetId] = useState<string | null>(null)
  const [mobileView, setMobileView]       = useState<'list' | 'detail'>('list')
  const { data: sets }                    = useEvalSets()

  const activeSetId = selectedSetId ?? (sets?.find((s) => s.is_default) ?? sets?.[0])?.id ?? null

  function handleSelectSet(id: string) {
    setSelectedSetId(id)
    setMobileView('detail')
  }

  return (
    <div className="flex h-full w-full overflow-hidden">
      <div className={mobileView === 'list' ? 'flex w-full md:w-auto md:flex-shrink-0' : 'hidden md:flex md:flex-shrink-0'}>
        <SetList selectedId={activeSetId} onSelect={handleSelectSet} onOpenSidebar={onOpenSidebar} />
      </div>
      <div className={mobileView === 'detail' ? 'flex flex-1 overflow-hidden' : 'hidden md:flex flex-1 overflow-hidden'}
        style={{ background: 'var(--bg-base)' }}>
        {activeSetId
          ? <SetDetail key={activeSetId} setId={activeSetId} onBack={() => setMobileView('list')} onOpenSidebar={onOpenSidebar} />
          : (
            <div className="flex items-center justify-center h-full w-full" style={{ color: 'var(--text-3)' }}>
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
