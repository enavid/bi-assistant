import React, { useState } from 'react'
import { DECISION_STYLE, traceStatusColor, type TraceStep } from './traceUtils'

function isComplex(v: unknown): boolean {
  if (v === null || v === undefined) return false
  if (Array.isArray(v)) return v.length > 0
  if (typeof v === 'object') return Object.keys(v as object).length > 0
  return false
}

export function TraceDetails({ details }: { details: Record<string, unknown> }) {
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
      {simple.length > 0 && (
        <div
          className="grid px-3 py-2 gap-x-4 gap-y-[3px]"
          style={{ gridTemplateColumns: 'minmax(100px, max-content) 1fr' }}
        >
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

function CoverageChip({ status }: { status: string }) {
  const s = status.toUpperCase()
  const color =
    s === 'COMPLETE' ? 'var(--green)' :
    s === 'PATCHED_BY_CONTROLLED_DYNAMIC' ? 'var(--accent-text)' :
    'var(--red)'
  const bg =
    s === 'COMPLETE' ? 'var(--green-bg)' :
    s === 'PATCHED_BY_CONTROLLED_DYNAMIC' ? 'var(--accent-bg)' :
    'var(--red-bg)'
  const border =
    s === 'COMPLETE' ? 'var(--green-border)' :
    s === 'PATCHED_BY_CONTROLLED_DYNAMIC' ? 'var(--accent-border)' :
    'var(--red-border)'
  const label =
    s === 'PATCHED_BY_CONTROLLED_DYNAMIC' ? 'patched' : status
  return (
    <span
      className="px-1.5 py-[2px] rounded-[3px] text-[9px] uppercase tracking-wide"
      style={{ color, background: bg, border: `1px solid ${border}` }}
    >
      {label}
    </span>
  )
}

function ContextWindowBar({ tokens, window: ctxWindow }: { tokens: number; window: number }) {
  const pct = Math.min(100, Math.round((tokens / ctxWindow) * 100))
  const filled = Math.round(pct / 10)
  const bar = '█'.repeat(filled) + '░'.repeat(10 - filled)
  const warn = pct >= 90
  return (
    <span className="flex items-center gap-1.5">
      <span className="font-mono tracking-tighter" style={{ color: warn ? 'var(--red)' : 'var(--text-2)', letterSpacing: '-0.5px' }}>
        {bar}
      </span>
      <span style={{ color: warn ? 'var(--red)' : 'var(--text-3)' }}>
        {tokens.toLocaleString()} / {ctxWindow.toLocaleString()} ({pct}%)
      </span>
      {warn && <span style={{ color: 'var(--red)' }}>⚠️</span>}
    </span>
  )
}

function PipelineFlagsRow({ flags }: { flags: Record<string, boolean> }) {
  const labels: Record<string, string> = {
    use_template_engine: 'template',
    use_controlled_dynamic: 'cd',
    force_llm_for_incomplete_template: 'force-llm',
  }
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {Object.entries(flags).map(([k, v]) => (
        <span
          key={k}
          className="px-1.5 py-[2px] rounded-[3px] text-[9px]"
          style={{
            color: v ? 'var(--accent-text)' : 'var(--text-3)',
            background: v ? 'var(--accent-bg)' : 'var(--bg-raised)',
            border: `1px solid ${v ? 'var(--accent-border)' : 'var(--border-subtle)'}`,
            opacity: v ? 1 : 0.6,
          }}
        >
          {v ? '✓' : '✗'} {labels[k] ?? k}
        </span>
      ))}
    </div>
  )
}

function CollapsibleText({ label, text, accentColor }: { label: string; text: string; accentColor?: string }) {
  const [open, setOpen] = useState(false)
  const color = accentColor ?? 'var(--accent-border)'
  return (
    <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
      <button
        className="w-full flex items-center gap-1.5 px-3 py-1.5 text-left text-[10px] font-mono select-none hover:opacity-70 transition-opacity"
        style={{ color: 'var(--text-3)', background: 'var(--bg-base)' }}
        onClick={() => setOpen((v) => !v)}
      >
        <span style={{ color }}>{open ? '▾' : '▸'}</span>
        {label}
        <span className="ml-auto tabular-nums" style={{ color: 'var(--text-3)' }}>{text.length.toLocaleString()} chars</span>
      </button>
      {open && (
        <pre
          className="px-3 pb-3 text-[9.5px] overflow-x-auto leading-relaxed whitespace-pre-wrap break-words"
          style={{ background: 'var(--bg-base)', color: 'var(--text-2)', borderTop: '1px solid var(--border-subtle)', maxHeight: '400px', overflowY: 'auto' }}
        >
          {text}
        </pre>
      )}
    </div>
  )
}

function SqlPlannerDetails({ details, llmPrompt }: { details: Record<string, unknown>; llmPrompt?: string | null }) {
  const coverageStatus = details.coverage_status as string | null | undefined
  const missingFilters = (details.missing_filters as string[] | null | undefined) ?? []
  const modelCalled = details.model_called as string | null | undefined
  const llmReason = details.model_reason as string | null | undefined
  const source = details.source as string | null | undefined
  const templateId = details.template_id as string | null | undefined
  const pipelineFlags = details.pipeline_flags as Record<string, boolean> | null | undefined
  const meta = details.metadata as Record<string, unknown> | null | undefined
  const promptTokens = typeof meta?.prompt_tokens === 'number' ? meta.prompt_tokens : null
  const ctxWindow = typeof meta?.context_window === 'number' ? meta.context_window : null
  const schemaChars = typeof meta?.schema_context_chars === 'number' ? meta.schema_context_chars : null
  const rawResponse = typeof meta?.raw_response === 'string' ? meta.raw_response : null
  const promptText = llmPrompt ?? (typeof meta?.prompt === 'string' ? meta.prompt : null)

  const rows: Array<[string, React.ReactNode]> = []

  if (source) rows.push(['source', <span style={{ color: 'var(--text-2)' }}>{source}</span>])
  if (templateId) rows.push(['template_id', <span style={{ color: 'var(--text-2)', fontStyle: 'italic' }}>{templateId}</span>])
  if (coverageStatus) rows.push(['coverage', <CoverageChip status={coverageStatus} />])
  if (missingFilters.length > 0) rows.push([
    'missing',
    <span className="flex flex-wrap gap-1">
      {missingFilters.map((f) => (
        <span key={f} className="px-1 py-[1px] rounded-[3px]" style={{ background: 'var(--red-bg)', color: 'var(--red)', border: '1px solid var(--red-border)' }}>{f}</span>
      ))}
    </span>,
  ])
  rows.push(['model_called', modelCalled
    ? <span style={{ color: 'var(--amber)' }}>{modelCalled}</span>
    : <span style={{ color: 'var(--text-3)' }}>—</span>
  ])
  if (llmReason) rows.push(['llm_trigger', <span style={{ color: 'var(--amber)' }}>{llmReason}</span>])
  if (schemaChars !== null) rows.push(['schema_chars', <span style={{ color: 'var(--text-2)' }}>{schemaChars.toLocaleString()}</span>])
  if (promptTokens !== null && ctxWindow !== null) {
    rows.push(['context_window', <ContextWindowBar tokens={promptTokens} window={ctxWindow} />])
  }

  return (
    <div
      className="text-[10px] font-mono"
      style={{
        borderTop: '1px solid var(--border-subtle)',
        background: 'var(--bg-base)',
        borderLeft: '3px solid var(--accent-border)',
      }}
    >
      <div
        className="grid px-3 py-2 gap-x-4 gap-y-[4px] items-center"
        style={{ gridTemplateColumns: 'minmax(90px, max-content) 1fr' }}
      >
        {rows.map(([label, node]) => (
          <React.Fragment key={label}>
            <span style={{ color: 'var(--text-3)' }}>{label}</span>
            <span>{node}</span>
          </React.Fragment>
        ))}
      </div>
      {pipelineFlags && (
        <div
          className="px-3 pb-2 pt-1.5"
          style={{ borderTop: '1px solid var(--border-subtle)' }}
        >
          <div className="mb-1" style={{ color: 'var(--text-3)' }}>pipeline_flags</div>
          <PipelineFlagsRow flags={pipelineFlags} />
        </div>
      )}
      {promptText && <CollapsibleText label="llm_prompt" text={promptText} accentColor="var(--amber-border)" />}
      {rawResponse && <CollapsibleText label="raw_response" text={rawResponse} accentColor="var(--green-border)" />}
    </div>
  )
}

export function TracePanel({ traces, llmPrompt }: { traces: TraceStep[]; llmPrompt?: string | null }) {
  const [expandedRow, setExpandedRow] = useState<number | null>(null)

  return (
    <div
      className="mt-1.5 rounded-[6px] overflow-hidden text-[10px] font-mono overflow-x-auto"
      style={{ border: '1px solid var(--border-subtle)', background: 'var(--bg-raised)' }}
    >
      <div className="grid" style={{ gridTemplateColumns: 'minmax(110px, 1.8fr) minmax(80px, 1fr) 44px 88px', gap: 0, minWidth: 320 }}>
        {(['step', 'status', 'ms', 'decision'] as const).map((h) => (
          <div key={h} className="px-2.5 py-1.5 font-semibold uppercase tracking-wide text-[9px]"
            style={{ color: 'var(--text-3)', borderBottom: '1px solid var(--border-subtle)' }}>
            {h}
          </div>
        ))}
        {traces.map((t, i) => {
          const isLast = i === traces.length - 1
          const isExpanded = expandedRow === i
          const details = t.details ?? {}
          const hasDetails = Object.keys(details).filter((k) => k !== 'decision_by').length > 0
          const decision = (details.decision_by as string | undefined) ?? '—'
          const ds = DECISION_STYLE[decision]
          const status = t.status ?? ''
          const statusColor = traceStatusColor(status)
          const isErrorStatus = statusColor === 'var(--red)'
          const rowBorder = (!isLast || isExpanded) ? '1px solid var(--border-subtle)' : undefined
          return (
            <React.Fragment key={i}>
              <div
                className={hasDetails ? 'px-2.5 py-[5px] cursor-pointer hover:opacity-70' : 'px-2.5 py-[5px]'}
                style={{ color: 'var(--text-2)', borderBottom: rowBorder }}
                onClick={() => hasDetails && setExpandedRow(isExpanded ? null : i)}
              >
                {hasDetails && <span className="mr-1" style={{ color: 'var(--text-3)' }}>{isExpanded ? '▾' : '▸'}</span>}
                {t.step ?? '—'}
              </div>
              <div className="px-2.5 py-[5px]" style={{ borderBottom: rowBorder }}>
                <span style={{ color: statusColor, fontWeight: isErrorStatus ? 600 : undefined }}>{status || '—'}</span>
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
                  {t.step === 'sql_planner'
                    ? <SqlPlannerDetails details={details} llmPrompt={llmPrompt} />
                    : <TraceDetails details={details} />}
                </div>
              )}
            </React.Fragment>
          )
        })}
      </div>
    </div>
  )
}
