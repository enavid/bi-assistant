import { useState } from 'react'
import { BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { Icon } from '@/components/ui/Icon'
import type { QueryResult } from '@/types'

type ViewMode = 'table' | 'bar' | 'pie'

interface QueryResultViewProps {
  result: QueryResult
}

const COLORS = ['#3b6ef5', '#82aaff', '#34d399', '#f59e0b', '#f87171', '#a78bfa', '#38bdf8', '#fb923c']

function isNumeric(val: unknown): boolean {
  return typeof val === 'number' || (typeof val === 'string' && !isNaN(Number(val)) && val.trim() !== '')
}

function detectChartable(result: QueryResult): { labelCol: number; valueCol: number } | null {
  if (result.columns.length < 2 || result.rows.length === 0) return null
  const labelCol = result.columns.findIndex((_, ci) => !isNumeric(result.rows[0][ci]))
  const valueCol = result.columns.findIndex((_, ci) => isNumeric(result.rows[0][ci]))
  if (labelCol === -1 || valueCol === -1 || labelCol === valueCol) return null
  return { labelCol, valueCol }
}

export function QueryResultView({ result }: QueryResultViewProps) {
  const [view, setView] = useState<ViewMode>('table')
  const chartable = detectChartable(result)

  const chartData = chartable
    ? result.rows.map((row) => ({
        name: String(row[chartable.labelCol] ?? ''),
        value: Number(row[chartable.valueCol]),
      }))
    : []

  const iconMap: Record<ViewMode, Parameters<typeof Icon>[0]['name']> = {
    table: 'list', bar: 'bar-chart', pie: 'flask',
  }

  return (
    <div className="bg-bg-surface border border-border-default rounded-[10px] overflow-hidden">
      <div className="bg-bg-raised px-3 py-1.5 border-b border-border-subtle flex items-center gap-2">
        <Icon name="check" size={12} className="text-success flex-shrink-0" />
        <span className="text-[11px] text-text-2">{result.row_count} row{result.row_count !== 1 ? 's' : ''}</span>
        <span className="text-[11px] text-text-3">· {result.elapsed_ms} ms</span>
        {chartable && (
          <div className="ml-auto flex items-center gap-1">
            {(['table', 'bar', 'pie'] as ViewMode[]).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`flex items-center gap-1 px-2 py-0.5 rounded-[5px] text-[11px] border transition-colors ${
                  view === v
                    ? 'bg-accent-bg text-accent-text border-accent-border'
                    : 'border-border-default text-text-3 hover:border-border-strong hover:text-text-2'
                }`}
              >
                <Icon name={iconMap[v]} size={12} />
                {v.charAt(0).toUpperCase() + v.slice(1)}
              </button>
            ))}
          </div>
        )}
      </div>

      {view === 'table' && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr>
                {result.columns.map((col) => (
                  <th key={col} className="px-3 py-2 text-left text-[10px] uppercase tracking-[0.5px] text-text-3 border-b border-border-subtle font-medium whitespace-nowrap">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, ri) => (
                <tr key={ri} className="hover:bg-bg-raised transition-colors">
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-3 py-2 text-[12px] text-text-1 border-b border-border-subtle last:border-b-0">{String(cell ?? '')}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {view === 'bar' && chartable && (
        <div className="p-4" style={{ height: 220 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 20 }}>
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-2)' }} axisLine={{ stroke: 'var(--border-default)' }} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-2)' }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: '8px', fontSize: '12px', color: 'var(--text-1)' }} cursor={{ fill: 'var(--bg-raised)' }} />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {chartData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {view === 'pie' && chartable && (
        <div className="p-4 flex items-center gap-6" style={{ height: 220 }}>
          <ResponsiveContainer width={180} height="100%">
            <PieChart>
              <Pie data={chartData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value" paddingAngle={2}>
                {chartData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
              <Tooltip contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: '8px', fontSize: '12px', color: 'var(--text-1)' }} />
            </PieChart>
          </ResponsiveContainer>
          <div className="flex flex-col gap-2 flex-1">
            {chartData.map((d, i) => {
              const total = chartData.reduce((s, r) => s + r.value, 0)
              const pct = total > 0 ? Math.round((d.value / total) * 100) : 0
              return (
                <div key={i} className="flex items-center gap-2 text-[12px]">
                  <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: COLORS[i % COLORS.length] }} />
                  <span className="text-text-1 flex-1 truncate">{d.name}</span>
                  <span className="text-text-2 tabular-nums">{d.value.toLocaleString()}</span>
                  <span className="text-text-3 tabular-nums w-10 text-right">{pct}%</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
