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
  useEvalSets,
  useImportEvalQuestions,
  useOllamaConnectionModels,
  useOllamaConnections,
  useSeedEvalDefaults,
  useTriggerEvalRun,
} from '@/hooks'
import type { EvalQuestion, EvalRun, EvalRunResult } from '@/types'

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

function exportRunAsJson(run: EvalRun, setName: string) {
  const results = run.results ?? []
  const payload = {
    set_name: setName,
    run_id: run.id,
    model: run.model_name ?? null,
    started_at: run.started_at,
    finished_at: run.finished_at,
    summary: {
      total: run.total,
      passed: run.passed,
      failed: run.failed,
      pass_rate: run.total > 0 ? Math.round((run.passed / run.total) * 1000) / 1000 : null,
    },
    results: results.map((r) => ({
      question_id: r.question_id,
      category: r.category,
      question: r.question,
      expected_route: null as string | null,
      actual_route: r.actual_route,
      actual_status: r.actual_status,
      actual_intent: r.actual_intent,
      passed: r.passed,
      duration_ms: r.total_duration_ms,
      model_called: r.model_called,
      source: r.source,
      template_id: r.template_id,
      sql_validator_status: r.sql_validator_status,
      visualization: r.visualization,
      error: r.error,
      warnings: r.warnings,
      trace: r.trace_steps ?? [],
    })),
  }

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  const date = new Date().toISOString().slice(0, 10)
  const slug = setName.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '')
  a.href     = url
  a.download = `eval_${slug}_${date}.json`
  a.click()
  URL.revokeObjectURL(url)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function humanCategory(cat: string) {
  return cat.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

const inputCls   = 'px-3 py-2.5 rounded-[8px] text-[13px] outline-none w-full'
const inputStyle = { background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-1)' }
const labelCls   = 'text-[11px] font-semibold uppercase tracking-[0.6px]'

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

// ---------------------------------------------------------------------------
// Trace panel (same richness as ChatPage)
// ---------------------------------------------------------------------------

function isComplex(v: unknown): boolean {
  if (v === null || v === undefined) return false
  if (Array.isArray(v)) return v.length > 0
  if (typeof v === 'object') return Object.keys(v as object).length > 0
  return false
}

function TraceDetails({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details).filter(([k]) => k !== 'decision_by')
  if (entries.length === 0) return null
  const simple  = entries.filter(([, v]) => !isComplex(v))
  const complex = entries.filter(([, v]) => isComplex(v))
  return (
    <div className="text-[10px] font-mono"
      style={{ borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-base)', borderLeft: '3px solid var(--accent-border)' }}>
      {simple.length > 0 && (
        <div className="grid px-3 py-2 gap-x-4 gap-y-[3px]"
          style={{ gridTemplateColumns: 'minmax(100px, max-content) 1fr' }}>
          {simple.map(([k, v]) => (
            <React.Fragment key={k}>
              <span style={{ color: 'var(--text-3)' }}>{k}</span>
              <span className="break-all" style={{ color: 'var(--text-2)' }}>
                {v === null || v === undefined ? '—' : String(v)}
              </span>
            </React.Fragment>
          ))}
        </div>
      )}
      {complex.length > 0 && (
        <div className="flex flex-col gap-2 px-3 pb-2.5"
          style={{ borderTop: simple.length > 0 ? '1px solid var(--border-subtle)' : undefined, paddingTop: '8px' }}>
          {complex.map(([k, v]) => (
            <div key={k}>
              <div className="mb-0.5 font-semibold" style={{ color: 'var(--text-3)' }}>{k}</div>
              <pre className="px-2.5 py-2 rounded-[4px] text-[9.5px] overflow-x-auto leading-relaxed"
                style={{ background: 'var(--bg-raised)', color: 'var(--text-2)', border: '1px solid var(--border-subtle)' }}>
                {JSON.stringify(v, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function EvalTracePanel({ steps }: { steps: NonNullable<EvalRunResult['trace_steps']> }) {
  const [expandedRow, setExpandedRow] = useState<number | null>(null)
  return (
    <div className="mt-1.5 rounded-[6px] overflow-hidden text-[10px] font-mono overflow-x-auto"
      style={{ border: '1px solid var(--border-subtle)', background: 'var(--bg-raised)' }}>
      <div className="grid" style={{ gridTemplateColumns: 'minmax(110px, 1.8fr) minmax(80px, 1fr) 44px 88px', gap: 0, minWidth: 320 }}>
        {(['step', 'status', 'ms', 'decision'] as const).map((h) => (
          <div key={h} className="px-2.5 py-1.5 font-semibold uppercase tracking-wide text-[9px]"
            style={{ color: 'var(--text-3)', borderBottom: '1px solid var(--border-subtle)' }}>
            {h}
          </div>
        ))}
        {steps.map((t, i) => {
          const isLast       = i === steps.length - 1
          const isExpanded   = expandedRow === i
          const details      = t.details ?? {}
          const hasDetails   = Object.keys(details).filter((k) => k !== 'decision_by').length > 0
          const decision     = (details.decision_by as string | undefined) ?? '—'
          const ds           = DECISION_STYLE[decision]
          const status       = t.status ?? ''
          const statusColor  = traceStatusColor(status)
          const rowBorder    = (!isLast || isExpanded) ? '1px solid var(--border-subtle)' : undefined
          return (
            <React.Fragment key={i}>
              <div
                className={hasDetails ? 'px-2.5 py-[5px] cursor-pointer hover:opacity-70' : 'px-2.5 py-[5px]'}
                style={{ color: 'var(--text-2)', borderBottom: rowBorder }}
                onClick={() => hasDetails && setExpandedRow(isExpanded ? null : i)}>
                {hasDetails && <span className="mr-1" style={{ color: 'var(--text-3)' }}>{isExpanded ? '▾' : '▸'}</span>}
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
              {isExpanded && (
                <div className="col-span-4" style={{ borderBottom: isLast ? undefined : '1px solid var(--border-subtle)' }}>
                  <TraceDetails details={details} />
                </div>
              )}
            </React.Fragment>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Inline result panel (expandable, chat-style)
// ---------------------------------------------------------------------------

function InlineResultPanel({ result, modelName }: { result: EvalRunResult; modelName: string | null }) {
  const [traceOpen, setTraceOpen] = useState(false)
  const routeStyle   = EVAL_ROUTE_STYLE[result.actual_route ?? ''] ?? EVAL_ROUTE_STYLE._default
  const statusLabel  = result.actual_status ? (EVAL_STATUS_LABEL[result.actual_status] ?? result.actual_status) : null
  const hasTrace     = (result.trace_steps?.length ?? 0) > 0
  const displayModel = result.model_called || modelName

  return (
    <div className="flex flex-col gap-1.5 px-4 pb-2.5 pt-2"
      style={{ background: result.passed ? 'rgba(34,197,94,0.04)' : 'rgba(248,113,113,0.04)', borderTop: '1px solid var(--border-subtle)' }}>

      {/* Meta badges */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {result.actual_route && (
          <span className="text-[10px] font-mono font-medium px-1.5 py-[3px] rounded-[4px]"
            style={{ background: routeStyle.bg, color: routeStyle.text, border: `1px solid ${routeStyle.border}` }}>
            {result.actual_route}
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
          {Math.round(result.total_duration_ms)}ms
        </span>
        {displayModel && (
          <span className="text-[9px] font-mono px-1.5 py-[3px] rounded-[4px]"
            style={{ background: 'var(--bg-base)', color: 'var(--text-3)', border: '1px solid var(--border-subtle)' }}>
            {displayModel}
          </span>
        )}
        {result.error && (
          <span className="text-[10px] font-mono px-1.5 py-[3px] rounded-[4px]"
            style={{ background: 'var(--red-bg)', color: 'var(--red)', border: '1px solid var(--red-border)' }}
            title={result.error}>
            {result.error.length > 60 ? result.error.slice(0, 60) + '…' : result.error}
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

      {traceOpen && hasTrace && <EvalTracePanel steps={result.trace_steps!} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Question row with inline result
// ---------------------------------------------------------------------------

function QuestionRow({
  q, setId,
  result, isCurrent, isRunning,
  onRun,
}: {
  q: EvalQuestion
  setId: string
  result: EvalRunResult | null
  isCurrent: boolean
  isRunning: boolean
  onRun: () => void
}) {
  const deleteQ = useDeleteEvalQuestion()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [resultOpen, setResultOpen]       = useState(false)
  const routeStyle = q.expected_route ? (EVAL_ROUTE_STYLE[q.expected_route] ?? EVAL_ROUTE_STYLE._default) : null

  // Auto-expand result when it arrives
  useEffect(() => {
    if (result) setResultOpen(true)
  }, [!!result])

  return (
    <div>
      {/* Question row */}
      <div
        className="group flex items-center gap-2.5 px-4 py-2"
        style={{ borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-surface)' }}
        onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-raised)')}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--bg-surface)')}
      >
        {/* Status indicator */}
        <div className="flex-shrink-0 w-5 flex items-center justify-center">
          {isCurrent && isRunning ? (
            <Spinner size={12} />
          ) : result ? (
            <div className="w-4 h-4 rounded-full flex items-center justify-center"
              style={result.passed
                ? { background: 'var(--accent-bg)', color: 'var(--accent-text)' }
                : { background: 'var(--red-bg)', color: 'var(--red)' }}>
              <Icon name={result.passed ? 'check' : 'x'} size={8} />
            </div>
          ) : (
            <span className="opacity-20"><Icon name="list" size={11} /></span>
          )}
        </div>

        {/* Question text */}
        <span
          className="flex-1 text-[12.5px] leading-snug min-w-0 cursor-pointer"
          style={{ color: 'var(--text-1)', direction: 'rtl', textAlign: 'right' }}
          onClick={() => result && setResultOpen((v) => !v)}
        >
          {q.question}
        </span>

        {/* Right side */}
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {routeStyle && (
            <span className="text-[10px] font-mono px-1.5 py-[2px] rounded-[4px]"
              style={{ background: routeStyle.bg, color: routeStyle.text, border: `1px solid ${routeStyle.border}` }}>
              {q.expected_route}
            </span>
          )}
          {result && (
            <span className="text-[9px] font-mono px-1 py-[2px] rounded-[3px]"
              style={{ background: result.passed ? 'var(--accent-bg)' : 'var(--red-bg)', color: result.passed ? 'var(--accent-text)' : 'var(--red)' }}>
              {result.passed ? 'pass' : 'fail'}
            </span>
          )}
          <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              onClick={onRun}
              disabled={isRunning}
              title="Run this question"
              className="w-6 h-6 rounded-[5px] flex items-center justify-center transition-opacity disabled:opacity-30"
              style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }}>
              <Icon name="play" size={9} />
            </button>
            <button
              onClick={() => setConfirmDelete(true)}
              title="Delete"
              className="w-6 h-6 rounded-[5px] flex items-center justify-center"
              style={{ color: 'var(--text-3)' }}
              onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--red)')}
              onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-3)')}>
              <Icon name="trash" size={11} />
            </button>
          </div>
        </div>
      </div>

      {/* Expandable result */}
      {result && resultOpen && (
        <InlineResultPanel result={result} modelName={null} />
      )}

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
// Category card
// ---------------------------------------------------------------------------

function CategoryCard({
  category, questions, setId,
  isRunning, resultsByQuestionId, currentQId,
  onRunCategory, onRunQuestion,
}: {
  category: string
  questions: EvalQuestion[]
  setId: string
  isRunning: boolean
  resultsByQuestionId: Record<string, EvalRunResult>
  currentQId: string | null
  onRunCategory: (cat: string) => void
  onRunQuestion: (qId: string) => void
}) {
  const [open, setOpen]     = useState(false)
  const [addOpen, setAddOpen] = useState(false)

  const doneCount    = questions.filter((q) => resultsByQuestionId[q.question_id]).length
  const passedCount  = questions.filter((q) => resultsByQuestionId[q.question_id]?.passed).length
  const hasResults   = doneCount > 0
  const headerRadius = open ? '10px 10px 0 0' : '10px'

  return (
    <div>
      <div
        className="group/card flex items-center gap-2 px-3 py-1.5 cursor-pointer select-none"
        style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', borderRadius: headerRadius }}
        onClick={() => setOpen((v) => !v)}
      >
        <span style={{ color: 'var(--text-3)', transition: 'transform .15s', transform: open ? 'rotate(90deg)' : 'none', display: 'inline-flex', flexShrink: 0 }}>
          <Icon name="arrow-right" size={10} />
        </span>
        <span className="flex-1 min-w-0 truncate text-[12px] font-semibold" style={{ color: 'var(--text-1)' }}>
          {humanCategory(category)}
        </span>
        {hasResults && (
          <span className="text-[10px] tabular-nums flex-shrink-0 font-mono"
            style={{ color: passedCount === doneCount ? 'var(--accent-text)' : 'var(--red)' }}>
            {passedCount}/{doneCount}
          </span>
        )}
        <span className="text-[10px] px-1.5 py-[1px] rounded-[4px] flex-shrink-0 tabular-nums"
          style={{ background: 'var(--bg-base)', border: '1px solid var(--border-default)', color: 'var(--text-3)' }}>
          {questions.length}
        </span>
        <div className="flex gap-1 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
          {/* Add — icon only, visible on hover */}
          <button
            onClick={() => setAddOpen(true)}
            title="Add question"
            className="w-6 h-6 rounded-[5px] flex items-center justify-center opacity-0 group-hover/card:opacity-100 transition-opacity hover:opacity-75"
            style={{ background: 'var(--bg-base)', border: '1px solid var(--border-default)', color: 'var(--text-3)' }}>
            <Icon name="plus" size={10} />
          </button>
          <button
            onClick={() => onRunCategory(category)}
            disabled={isRunning}
            className="h-6 px-2 rounded-[5px] text-[10px] font-semibold flex items-center gap-1 transition-opacity hover:opacity-80 disabled:opacity-30"
            style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }}>
            <Icon name="play" size={9} />
            Run
          </button>
        </div>
      </div>

      {open && (
        <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderTop: 'none', borderRadius: '0 0 10px 10px' }}>
          {questions.map((q) => (
            <QuestionRow
              key={q.id}
              q={q}
              setId={setId}
              result={resultsByQuestionId[q.question_id] ?? null}
              isCurrent={currentQId === q.question_id}
              isRunning={isRunning}
              onRun={() => onRunQuestion(q.question_id)}
            />
          ))}
        </div>
      )}

      <AddQuestionModal setId={setId} open={addOpen} onClose={() => setAddOpen(false)} defaultCategory={category} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Questions tab
// ---------------------------------------------------------------------------

function QuestionsTab({
  setId, questions,
  isRunning, resultsByQuestionId, currentQId,
  onRunAll, onRunCategory, onRunQuestion,
}: {
  setId: string
  questions: EvalQuestion[]
  isRunning: boolean
  resultsByQuestionId: Record<string, EvalRunResult>
  currentQId: string | null
  onRunAll: () => void
  onRunCategory: (cat: string) => void
  onRunQuestion: (qId: string) => void
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

  const totalResults = Object.keys(resultsByQuestionId).length
  const passedResults = Object.values(resultsByQuestionId).filter((r) => r.passed).length

  return (
    <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-1.5">

      {/* Run All bar */}
      {questions.length > 0 && (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-[8px] flex-shrink-0 mb-1"
          style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)' }}>
          {isRunning ? (
            <>
              <Spinner size={12} />
              <span className="text-[11px] flex-1" style={{ color: 'var(--text-2)' }}>
                Running… <span className="tabular-nums font-medium">{totalResults}/{questions.length}</span>
              </span>
            </>
          ) : totalResults > 0 ? (
            <>
              <div className="w-3.5 h-3.5 rounded-full flex items-center justify-center flex-shrink-0"
                style={passedResults === totalResults
                  ? { background: 'var(--accent-bg)', color: 'var(--accent-text)' }
                  : { background: 'var(--red-bg)', color: 'var(--red)' }}>
                <Icon name={passedResults === totalResults ? 'check' : 'x'} size={7} />
              </div>
              <span className="text-[11px] flex-1 tabular-nums" style={{ color: 'var(--text-2)' }}>
                <span className="font-semibold">{passedResults}</span>/{totalResults} passed
              </span>
            </>
          ) : (
            <span className="text-[11px] flex-1" style={{ color: 'var(--text-3)' }}>
              {questions.length} questions
            </span>
          )}
          <button
            onClick={onRunAll}
            disabled={isRunning}
            className="h-6 px-2.5 flex items-center gap-1.5 rounded-[6px] text-[11px] font-semibold transition-opacity hover:opacity-88 disabled:opacity-40"
            style={{ background: 'var(--accent)', color: '#fff' }}>
            {isRunning ? <Spinner size={10} /> : <Icon name="play" size={10} />}
            {isRunning ? 'Running…' : 'Run All'}
          </button>
        </div>
      )}

      {sortedCats.map((cat) => (
        <CategoryCard
          key={cat}
          category={cat}
          questions={byCategory[cat]}
          setId={setId}
          isRunning={isRunning}
          resultsByQuestionId={resultsByQuestionId}
          currentQId={currentQId}
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
        className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-[8px] text-[11px] transition-colors mt-1"
        style={{ border: '1px dashed var(--border-default)', color: 'var(--text-3)', background: 'transparent' }}
        onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--accent-border)'; e.currentTarget.style.color = 'var(--accent-text)' }}
        onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border-default)'; e.currentTarget.style.color = 'var(--text-3)' }}>
        <Icon name="plus" size={11} />
        New category
      </button>

      <AddQuestionModal setId={setId} open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Run config dialog (model picker)
// ---------------------------------------------------------------------------

function RunConfigDialog({
  open, onClose, onConfirm, isRunning,
}: {
  open: boolean
  onClose: () => void
  onConfirm: (modelName: string | null) => void
  isRunning: boolean
}) {
  const [modelName, setModelName] = useState('')
  const { data: ollamaConns }     = useOllamaConnections()
  const activeConn                = ollamaConns?.find((c) => c.is_active) ?? null
  const { data: modelsData }      = useOllamaConnectionModels(activeConn?.id ?? '', !!activeConn)
  const availableModels           = modelsData?.models?.map((m) => m.name) ?? []

  function handleConfirm() {
    onConfirm(modelName || null)
    onClose()
  }

  return (
    <Modal open={open} title="Run configuration" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <label className={labelCls} style={{ color: 'var(--text-3)' }}>Model</label>
          {!activeConn ? (
            <p className="text-[12px] py-1" style={{ color: '#f87171' }}>
              No active Ollama connection — add one in Settings.
            </p>
          ) : (
            <select
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              className="px-2 py-2 rounded-[7px] text-[13px] outline-none"
              style={inputStyle}>
              <option value="">Default model</option>
              {availableModels.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          )}
        </div>
        <div className="flex gap-2 pt-1">
          <button onClick={onClose}
            className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium"
            style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}>
            Cancel
          </button>
          <button onClick={handleConfirm} disabled={isRunning}
            className="flex-1 py-2.5 rounded-[9px] text-[13px] font-semibold transition-opacity hover:opacity-90 disabled:opacity-40"
            style={{ background: 'var(--accent)', color: '#fff' }}>
            {isRunning ? 'Starting…' : 'Run'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Import modal (with "Import 240" button)
// ---------------------------------------------------------------------------

function ImportModal({ setId, open, onClose }: { setId: string; open: boolean; onClose: () => void }) {
  const importQ     = useImportEvalQuestions()
  const seedDefaults = useSeedEvalDefaults()
  const fileRef     = useRef<HTMLInputElement>(null)
  const [text, setText]   = useState('')
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

  async function handleSeedDefaults() {
    try {
      await seedDefaults.mutateAsync()
      onClose()
    } catch { setError('Failed to import default questions') }
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
        {/* Import 240 shortcut */}
        <div className="flex flex-col gap-2 p-3 rounded-[10px]"
          style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)' }}>
          <p className="text-[12px] font-medium" style={{ color: 'var(--text-1)' }}>
            240 Consultant Questions
          </p>
          <p className="text-[11px]" style={{ color: 'var(--text-3)' }}>
            Import the full default evaluation set covering all HR analytics categories.
          </p>
          <button
            onClick={handleSeedDefaults}
            disabled={seedDefaults.isPending}
            className="flex items-center justify-center gap-2 py-2 rounded-[8px] text-[12px] font-semibold transition-opacity hover:opacity-88 disabled:opacity-40"
            style={{ background: 'var(--accent)', color: '#fff' }}>
            {seedDefaults.isPending ? <Spinner size={12} /> : <Icon name="notes" size={13} />}
            {seedDefaults.isPending ? 'Importing…' : 'Import 240 default questions'}
          </button>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex-1 h-px" style={{ background: 'var(--border-subtle)' }} />
          <span className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--text-3)' }}>or</span>
          <div className="flex-1 h-px" style={{ background: 'var(--border-subtle)' }} />
        </div>

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
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6}
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
            {importQ.isPending ? 'Importing…' : 'Import JSON'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Add question modal
// ---------------------------------------------------------------------------

function AddQuestionModal({
  setId, open, onClose, defaultCategory = '',
}: {
  setId: string; open: boolean; onClose: () => void; defaultCategory?: string
}) {
  const addQ = useAddEvalQuestion()
  const [question, setQuestion]           = useState('')
  const [category, setCategory]           = useState(defaultCategory)
  const [expectedRoute, setExpectedRoute] = useState('')
  const [error, setError]                 = useState('')

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
// Set detail panel
// ---------------------------------------------------------------------------

function SetDetail({ setId, onBack, onOpenSidebar }: { setId: string; onBack?: () => void; onOpenSidebar?: () => void }) {
  const { data: sets }      = useEvalSets()
  const { data: questions } = useEvalQuestions(setId)
  const trigger             = useTriggerEvalRun()

  const [activeRunId, setActiveRunId]   = useState<string | null>(null)
  const [importOpen, setImportOpen]     = useState(false)
  const [runDialogScope, setRunDialogScope] = useState<{ type: 'all' | 'category' | 'question'; value?: string } | null>(null)

  const set        = sets?.find((s) => s.id === setId)
  const { data: activeRun } = useEvalRun(activeRunId)

  // Build result lookup: question_id (string) → result
  const resultsByQuestionId: Record<string, EvalRunResult> = {}
  if (activeRun?.results) {
    for (const r of activeRun.results) {
      resultsByQuestionId[r.question_id] = r
    }
  }

  // Current question being processed
  const currentQId: string | null = (() => {
    if (!activeRun || activeRun.status !== 'running') return null
    const ordered = activeRun.question_ids_ordered
    const idx     = activeRun.current_question_idx
    if (!ordered || idx == null) return null
    // Map internal UUID to question_id via questions list
    const internalId = ordered[idx]
    return questions?.find((q) => q.id === internalId)?.question_id ?? null
  })()

  async function handleRun(modelName: string | null) {
    const scope = runDialogScope
    if (!scope) return
    try {
      let run: EvalRun
      if (scope.type === 'all') {
        run = await trigger.mutateAsync({ setId, model_name: modelName ?? undefined })
      } else if (scope.type === 'category') {
        run = await trigger.mutateAsync({ setId, category: scope.value, model_name: modelName ?? undefined })
      } else {
        // single question — scope.value is question_id (string), need internal id
        const q = questions?.find((q) => q.question_id === scope.value)
        if (!q) return
        run = await trigger.mutateAsync({ setId, question_ids: [q.id], model_name: modelName ?? undefined })
      }
      setActiveRunId(run.id)
    } catch {
      // error surfaces via trigger.error
    }
  }

  return (
    <>
      <div className="flex-1 flex flex-col h-full overflow-hidden">

        {/* Header */}
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
          {activeRun?.status === 'done' && (
            <button
              onClick={() => exportRunAsJson(activeRun, set?.name ?? 'eval')}
              title="Export results as JSON"
              className="h-7 px-2.5 flex items-center gap-1.5 rounded-[7px] text-[12px] font-medium transition-opacity hover:opacity-80"
              style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}>
              <Icon name="download" size={12} />
              <span className="hidden sm:inline">Export</span>
            </button>
          )}
          <button onClick={() => setImportOpen(true)}
            className="h-7 px-2.5 flex items-center gap-1.5 rounded-[7px] text-[12px] font-medium transition-opacity hover:opacity-80"
            style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}>
            <Icon name="notes" size={12} />
            <span className="hidden sm:inline">Import</span>
          </button>
        </div>

        {/* Questions view (no tabs) */}
        <QuestionsTab
          setId={setId}
          questions={questions ?? []}
          isRunning={activeRun?.status === 'running'}
          resultsByQuestionId={resultsByQuestionId}
          currentQId={currentQId}
          onRunAll={() => setRunDialogScope({ type: 'all' })}
          onRunCategory={(cat) => setRunDialogScope({ type: 'category', value: cat })}
          onRunQuestion={(qId) => setRunDialogScope({ type: 'question', value: qId })}
        />
      </div>

      <ImportModal setId={setId} open={importOpen} onClose={() => setImportOpen(false)} />

      <RunConfigDialog
        open={runDialogScope !== null}
        onClose={() => setRunDialogScope(null)}
        onConfirm={handleRun}
        isRunning={trigger.isPending}
      />
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
  const createSet   = useCreateEvalSet()
  const deleteSet   = useDeleteEvalSet()
  const [newOpen, setNewOpen]         = useState(false)
  const [name, setName]               = useState('')
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
              {createSet.isPending ? 'Creating…' : 'Create'}
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
