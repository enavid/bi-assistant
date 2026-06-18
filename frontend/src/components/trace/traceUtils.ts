export type TraceStep = {
  step?: string
  status?: string
  duration_ms?: number
  details?: Record<string, unknown>
}

export const DECISION_STYLE: Record<string, { color: string; bg: string; border: string }> = {
  rule:               { color: 'var(--text-3)',      bg: 'var(--bg-raised)',   border: 'var(--border-subtle)' },
  policy:             { color: 'var(--red)',         bg: 'var(--red-bg)',      border: 'var(--red-border)' },
  template:           { color: 'var(--accent-text)', bg: 'var(--accent-bg)',   border: 'var(--accent-border)' },
  controlled_dynamic: { color: 'var(--green)',       bg: 'var(--green-bg)',    border: 'var(--green-border)' },
  llm:                { color: 'var(--amber)',       bg: 'var(--amber-bg)',    border: 'var(--amber-border)' },
  db:                 { color: 'var(--text-2)',      bg: 'var(--bg-raised)',   border: 'var(--border-default)' },
  component:          { color: 'var(--text-2)',      bg: 'var(--bg-raised)',   border: 'var(--border-default)' },
}

export function traceStatusColor(status: string): string {
  const s = status.toLowerCase()
  if (s.includes('fail') || s.includes('error') || s.includes('invalid') || s.includes('denied') || s.includes('blocked'))
    return 'var(--red)'
  if (s === 'warning' || s === 'not_configured' || s === 'unknown')
    return 'var(--amber)'
  return 'var(--text-3)'
}
