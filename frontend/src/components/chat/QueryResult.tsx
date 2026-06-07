import { useState, useMemo, useId } from 'react'
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, AreaChart, Area, CartesianGrid,
} from 'recharts'
import { Icon } from '@/components/ui/Icon'
import type { QueryResult } from '@/types'

type ViewMode = 'table' | 'bar' | 'donut' | 'line' | 'area'

const PALETTE = [
  '#3b6ef5', '#34d399', '#f59e0b', '#f87171', '#a78bfa',
  '#38bdf8', '#fb923c', '#e879f9', '#2dd4bf', '#facc15',
  '#4ade80', '#818cf8',
]

const CHART_H = 300
const BAR_TOP = 12
const PIE_TOP = 8

const TOOLTIP_STYLE: React.CSSProperties = {
  background: 'var(--bg-surface)',
  border: '1px solid var(--border-default)',
  borderRadius: 8,
  fontSize: 12,
  color: 'var(--text-1)',
  boxShadow: '0 4px 16px rgba(0,0,0,0.25)',
}

function isNumericVal(v: unknown): boolean {
  return (
    typeof v === 'number' ||
    (typeof v === 'string' && v.trim() !== '' && !isNaN(Number(v)))
  )
}

function detectCols(result: QueryResult): { labelCol: number; valueCol: number } | null {
  if (result.columns.length < 2 || result.rows.length === 0) return null
  const labelCol = result.columns.findIndex((_, ci) => !isNumericVal(result.rows[0][ci]))
  const valueCol = result.columns.findIndex((_, ci) => isNumericVal(result.rows[0][ci]))
  if (labelCol === -1 || valueCol === -1 || labelCol === valueCol) return null
  return { labelCol, valueCol }
}

function looksLikeTimeSeries(labels: string[]): boolean {
  if (labels.length < 3) return false
  const dateRe = /^\d{4}(-\d{2}(-\d{2})?)?$|^\d{1,2}[/-]\d{4}$|^\d{4}[/-]\d{2}$/
  return labels.slice(0, Math.min(labels.length, 6)).filter((l) => dateRe.test(l.trim())).length >= 2
}

const TABS: { id: ViewMode; label: string; icon: Parameters<typeof Icon>[0]['name'] }[] = [
  { id: 'table', label: 'Table',  icon: 'list'        },
  { id: 'bar',   label: 'Bar',   icon: 'bar-h'       },
  { id: 'donut', label: 'Donut', icon: 'donut'       },
  { id: 'line',  label: 'Line',  icon: 'line-chart'  },
  { id: 'area',  label: 'Area',  icon: 'area-chart'  },
]

export function QueryResultView({ result }: { result: QueryResult }) {
  const gradId = useId().replace(/:/g, 'g')

  const cols = useMemo(() => detectCols(result), [result])

  const sortedData = useMemo(() => {
    if (!cols) return []
    return result.rows
      .map((row) => ({
        name: String(row[cols.labelCol] ?? ''),
        value: Number(row[cols.valueCol]),
      }))
      .sort((a, b) => b.value - a.value)
  }, [result, cols])

  const originalData = useMemo(() => {
    if (!cols) return []
    return result.rows.map((row) => ({
      name: String(row[cols.labelCol] ?? ''),
      value: Number(row[cols.valueCol]),
    }))
  }, [result, cols])

  const timeSeries = useMemo(() => looksLikeTimeSeries(originalData.map((d) => d.name)), [originalData])

  const defaultView: ViewMode = !cols ? 'table' : timeSeries ? 'line' : 'bar'
  const [view, setView] = useState<ViewMode>(defaultView)

  const barData = sortedData.slice(0, BAR_TOP)

  const donutData = useMemo(() => {
    if (sortedData.length <= PIE_TOP) return sortedData
    const top = sortedData.slice(0, PIE_TOP)
    const otherVal = sortedData.slice(PIE_TOP).reduce((s, d) => s + d.value, 0)
    return [...top, { name: 'سایر', value: otherVal }]
  }, [sortedData])

  const total = sortedData.reduce((s, d) => s + d.value, 0)

  const visibleTabs = cols ? TABS : TABS.filter((t) => t.id === 'table')

  if (!result.success) {
    return (
      <div
        className="rounded-[10px] border px-4 py-3 text-[12px]"
        style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-default)', color: '#f87171' }}
      >
        {result.error ?? 'Query failed'}
      </div>
    )
  }

  return (
    <div
      className="rounded-[10px] overflow-hidden border"
      style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-default)' }}
    >
      {/* ── Header ── */}
      <div
        className="flex items-center gap-2 px-3 py-1.5 border-b"
        style={{ background: 'var(--bg-raised)', borderColor: 'var(--border-subtle)' }}
      >
        <span className="text-[11px] font-medium" style={{ color: 'var(--green)' }}>✓</span>
        <span className="text-[11px]" style={{ color: 'var(--text-2)' }}>
          {result.row_count} row{result.row_count !== 1 ? 's' : ''}
        </span>
        <span className="text-[11px]" style={{ color: 'var(--text-3)' }}>· {result.elapsed_ms} ms</span>

        <div className="ml-auto flex items-center gap-1">
          {visibleTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setView(tab.id)}
              className="flex items-center gap-1 px-2 py-1 rounded-[6px] text-[11px] border transition-all"
              style={
                view === tab.id
                  ? { background: 'var(--accent-bg)', color: 'var(--accent-text)', borderColor: 'var(--accent-border)' }
                  : { background: 'transparent', color: 'var(--text-3)', borderColor: 'var(--border-default)' }
              }
            >
              <Icon name={tab.icon} size={11} />
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── TABLE ── */}
      {view === 'table' && (
        <div style={{ maxHeight: 280, overflowY: 'auto', overflowX: 'auto' }}>
          <table className="w-full text-xs border-collapse">
            <thead style={{ position: 'sticky', top: 0, zIndex: 1, background: 'var(--bg-raised)' }}>
              <tr>
                {result.columns.map((col) => (
                  <th
                    key={col}
                    className="px-3 py-2 text-left text-[10px] uppercase tracking-[0.5px] font-medium whitespace-nowrap border-b"
                    style={{ color: 'var(--text-3)', borderColor: 'var(--border-default)' }}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, ri) => (
                <tr
                  key={ri}
                  style={{ background: ri % 2 === 1 ? 'var(--bg-raised)' : 'transparent' }}
                >
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      className="px-3 py-2 text-[12px] border-b"
                      style={{ color: 'var(--text-1)', borderColor: 'var(--border-subtle)' }}
                    >
                      {String(cell ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── HORIZONTAL BAR ── */}
      {view === 'bar' && cols && (
        <div style={{ height: CHART_H, padding: '12px 16px 12px 0' }}>
          {sortedData.length > BAR_TOP && (
            <p className="text-right text-[10px] px-4 mb-1" style={{ color: 'var(--text-3)' }}>
              Top {BAR_TOP} of {sortedData.length}
            </p>
          )}
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={barData}
              layout="vertical"
              margin={{ top: 4, right: 28, left: 8, bottom: 4 }}
            >
              <CartesianGrid horizontal={false} stroke="var(--border-subtle)" strokeDasharray="3 3" />
              <XAxis
                type="number"
                tick={{ fontSize: 10, fill: 'var(--text-3)' }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                type="category"
                dataKey="name"
                tick={{ fontSize: 11, fill: 'var(--text-2)' }}
                axisLine={false}
                tickLine={false}
                width={120}
              />
              <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--bg-raised)' }} />
              <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={20}>
                {barData.map((_, i) => (
                  <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── DONUT ── */}
      {view === 'donut' && cols && (
        <div className="flex" style={{ height: CHART_H }}>
          {/* Chart */}
          <div style={{ width: 220, flexShrink: 0 }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={donutData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={90}
                  dataKey="value"
                  paddingAngle={2}
                  startAngle={90}
                  endAngle={-270}
                >
                  {donutData.map((_, i) => (
                    <Cell key={i} fill={PALETTE[i % PALETTE.length]} stroke="none" />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v) => [Number(v).toLocaleString('fa-IR'), '']}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Legend */}
          <div className="flex-1 overflow-y-auto py-3 pr-4" style={{ maxHeight: CHART_H }}>
            {donutData.map((d, i) => {
              const pct = total > 0 ? ((d.value / total) * 100).toFixed(1) : '0'
              return (
                <div
                  key={i}
                  className="flex items-center gap-2 py-1.5 border-b text-[12px] last:border-0"
                  style={{ borderColor: 'var(--border-subtle)' }}
                >
                  <div
                    className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ background: PALETTE[i % PALETTE.length] }}
                  />
                  <span className="flex-1 truncate" style={{ color: 'var(--text-1)' }}>{d.name}</span>
                  <span className="tabular-nums" style={{ color: 'var(--text-2)' }}>
                    {d.value.toLocaleString('fa-IR')}
                  </span>
                  <span className="tabular-nums w-12 text-right text-[11px]" style={{ color: 'var(--text-3)' }}>
                    {pct}%
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── LINE ── */}
      {view === 'line' && cols && (
        <div className="p-4" style={{ height: CHART_H }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={originalData} margin={{ top: 10, right: 16, left: -10, bottom: 30 }}>
              <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="4 2" />
              <XAxis
                dataKey="name"
                tick={{ fontSize: 10, fill: 'var(--text-3)' }}
                axisLine={{ stroke: 'var(--border-default)' }}
                tickLine={false}
                angle={-30}
                textAnchor="end"
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fontSize: 11, fill: 'var(--text-3)' }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Line
                type="monotone"
                dataKey="value"
                stroke="var(--accent)"
                strokeWidth={2}
                dot={{ fill: 'var(--accent)', strokeWidth: 0, r: 3 }}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── AREA ── */}
      {view === 'area' && cols && (
        <div className="p-4" style={{ height: CHART_H }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={originalData} margin={{ top: 10, right: 16, left: -10, bottom: 30 }}>
              <defs>
                <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b6ef5" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#3b6ef5" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="4 2" />
              <XAxis
                dataKey="name"
                tick={{ fontSize: 10, fill: 'var(--text-3)' }}
                axisLine={{ stroke: 'var(--border-default)' }}
                tickLine={false}
                angle={-30}
                textAnchor="end"
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fontSize: 11, fill: 'var(--text-3)' }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Area
                type="monotone"
                dataKey="value"
                stroke="var(--accent)"
                strokeWidth={2}
                fill={`url(#${gradId})`}
                dot={false}
                activeDot={{ r: 5, fill: 'var(--accent)' }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
