import { useState, useMemo, useId } from 'react'
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, AreaChart, Area, CartesianGrid,
  LabelList, Legend,
} from 'recharts'
import { Icon } from '@/components/ui/Icon'
import type { QueryResult } from '@/types'

type ViewMode = 'table' | 'bar' | 'donut' | 'line' | 'area'

const PALETTE = [
  '#3b6ef5', '#34d399', '#f59e0b', '#f87171', '#a78bfa',
  '#38bdf8', '#fb923c', '#e879f9', '#2dd4bf', '#facc15',
  '#4ade80', '#818cf8',
]

const CHART_H  = 380
const BAR_TOP  = 15
const PIE_TOP  = 9
const LINE_MAX = 50

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

function hasPersian(s: string): boolean {
  return /[؀-ۿ]/.test(s)
}

// Simple layout: one text label column + one numeric value column
function detectCols(result: QueryResult): { labelCol: number; valueCol: number } | null {
  if (result.columns.length < 2 || result.rows.length === 0) return null
  const labelCol = result.columns.findIndex((_, ci) => !isNumericVal(result.rows[0][ci]))
  const valueCol = result.columns.findIndex((_, ci) => isNumericVal(result.rows[0][ci]))
  if (labelCol === -1 || valueCol === -1 || labelCol === valueCol) return null
  return { labelCol, valueCol }
}

// Grouped layout: 2 categorical columns × 1 numeric column (e.g. DOMAIN × GENDER × COUNT)
type GroupedLayout = {
  groupCol: number    // X-axis groups (e.g. SERVICE_DOMAIN)
  seriesCol: number   // series/legend key (e.g. GENDER)
  valueCol: number    // numeric value (e.g. EMPLOYEE_COUNT)
  seriesKeys: string[]
}

type GroupedRow = Record<string, string | number>

function detectGroupedCols(result: QueryResult): GroupedLayout | null {
  const { rows } = result
  if (rows.length === 0 || result.columns.length < 3) return null

  const textCols: number[] = []
  const numericCols: number[] = []
  for (let ci = 0; ci < result.columns.length; ci++) {
    if (rows.every(row => isNumericVal(row[ci]))) numericCols.push(ci)
    else textCols.push(ci)
  }

  if (textCols.length < 2 || numericCols.length < 1) return null

  const uniqueCounts = textCols.map(ci => new Set(rows.map(r => String(r[ci] ?? ''))).size)
  const maxUniq = Math.max(...uniqueCounts)
  const minUniq = Math.min(...uniqueCounts)

  // Series must have 2-8 distinct values to be renderable as grouped chart
  if (minUniq === maxUniq || minUniq < 2 || minUniq > 8) return null

  const seriesColIdx = textCols[uniqueCounts.indexOf(minUniq)]
  const groupColIdx  = textCols[uniqueCounts.indexOf(maxUniq)]
  const valueCol     = numericCols[0]

  // Confirm cross-product pattern: rows ≈ groups × series
  const expectedRows = maxUniq * minUniq
  if (Math.abs(expectedRows - rows.length) > Math.max(2, rows.length * 0.2)) return null

  const seriesKeys = [...new Set(rows.map(r => String(r[seriesColIdx] ?? '')))]
  return { groupCol: groupColIdx, seriesCol: seriesColIdx, valueCol, seriesKeys }
}

function buildGroupedData(result: QueryResult, layout: GroupedLayout): GroupedRow[] {
  const { rows } = result
  const { groupCol, seriesCol, valueCol } = layout

  const seen = new Set<string>()
  const groupOrder: string[] = []
  for (const row of rows) {
    const g = String(row[groupCol] ?? '')
    if (!seen.has(g)) { seen.add(g); groupOrder.push(g) }
  }

  const map: Record<string, Record<string, number>> = {}
  for (const g of groupOrder) map[g] = {}
  for (const row of rows) {
    const g = String(row[groupCol] ?? '')
    const s = String(row[seriesCol] ?? '')
    map[g][s] = Number(row[valueCol])
  }

  return groupOrder.map(g => ({ name: g, ...map[g] }))
}

function looksLikeTimeSeries(labels: string[]): boolean {
  if (labels.length < 3) return false
  const dateRe = /^\d{4}(-\d{2}(-\d{2})?)?$|^\d{1,2}[/-]\d{4}$|^\d{4}[/-]\d{2}$/
  return labels.slice(0, Math.min(labels.length, 6)).filter((l) => dateRe.test(l.trim())).length >= 2
}

function cellStyle(ci: number, rows: unknown[][]): React.CSSProperties {
  if (rows.length === 0) return {}
  const val = rows[0][ci]
  if (isNumericVal(val)) return { textAlign: 'center', fontVariantNumeric: 'tabular-nums' }
  const str = String(val ?? '')
  if (hasPersian(str)) return { textAlign: 'right', direction: 'rtl' }
  return { textAlign: 'left' }
}

function XTick({ x, y, payload }: { x?: number; y?: number; payload?: { value: string } }) {
  const raw = String(payload?.value ?? '')
  const label = raw.length > 18 ? raw.slice(0, 17) + '…' : raw
  return (
    <g transform={`translate(${x ?? 0},${y ?? 0})`}>
      <text
        x={0} y={0} dx={-4}
        textAnchor="end"
        fill="var(--text-3)"
        fontSize={10}
        transform="rotate(-90)"
      >
        <title>{raw}</title>
        {label}
      </text>
    </g>
  )
}

const TABS: { id: ViewMode; label: string; icon: Parameters<typeof Icon>[0]['name'] }[] = [
  { id: 'table', label: 'Table', icon: 'list'       },
  { id: 'bar',   label: 'Bar',   icon: 'bar-h'      },
  { id: 'donut', label: 'Donut', icon: 'donut'      },
  { id: 'line',  label: 'Line',  icon: 'line-chart' },
  { id: 'area',  label: 'Area',  icon: 'area-chart' },
]

export function QueryResultView({ result }: { result: QueryResult }) {
  const gradId = useId().replace(/:/g, 'g')

  const cols          = useMemo(() => detectCols(result), [result])
  const groupedLayout = useMemo(() => detectGroupedCols(result), [result])

  // --- Simple flat data (no grouping) ---
  const sortedData = useMemo(() => {
    if (!cols || groupedLayout) return []
    return result.rows
      .map((row) => ({ name: String(row[cols.labelCol] ?? ''), value: Number(row[cols.valueCol]) }))
      .sort((a, b) => b.value - a.value)
  }, [result, cols, groupedLayout])

  const originalData = useMemo(() => {
    if (!cols || groupedLayout) return []
    return result.rows.map((row) => ({
      name: String(row[cols.labelCol] ?? ''),
      value: Number(row[cols.valueCol]),
    }))
  }, [result, cols, groupedLayout])

  const timeSeries = useMemo(() => looksLikeTimeSeries(originalData.map((d) => d.name)), [originalData])

  // --- Grouped multi-series data ---
  const groupedData = useMemo(() => {
    if (!groupedLayout) return []
    return buildGroupedData(result, groupedLayout)
  }, [result, groupedLayout])

  const groupedBarData = useMemo(() => {
    if (!groupedLayout) return []
    return [...groupedData].sort((a, b) => {
      const sumA = groupedLayout.seriesKeys.reduce((s, k) => s + ((a[k] as number) ?? 0), 0)
      const sumB = groupedLayout.seriesKeys.reduce((s, k) => s + ((b[k] as number) ?? 0), 0)
      return sumB - sumA
    })
  }, [groupedData, groupedLayout])

  // Donut in grouped mode: aggregate each series key across all groups
  const groupedDonutData = useMemo(() => {
    if (!groupedLayout) return []
    return groupedLayout.seriesKeys.map(key => ({
      name: key,
      value: result.rows
        .filter(row => String(row[groupedLayout.seriesCol] ?? '') === key)
        .reduce((s, row) => s + Number(row[groupedLayout.valueCol]), 0),
    }))
  }, [result, groupedLayout])

  const [view, setView] = useState<ViewMode>('table')

  const barData = sortedData.slice(0, BAR_TOP)

  const donutData = useMemo(() => {
    if (sortedData.length <= PIE_TOP) return sortedData
    const top = sortedData.slice(0, PIE_TOP)
    const otherVal = sortedData.slice(PIE_TOP).reduce((s, d) => s + d.value, 0)
    return [...top, { name: 'سایر', value: otherVal }]
  }, [sortedData])

  const total        = sortedData.reduce((s, d) => s + d.value, 0)
  const groupedTotal = groupedDonutData.reduce((s, d) => s + d.value, 0)

  const lineData      = timeSeries ? originalData : originalData.slice(0, LINE_MAX)
  const showLineLimit = !timeSeries && originalData.length > LINE_MAX

  const hasChartData = !!(cols || groupedLayout)
  const visibleTabs  = hasChartData ? TABS : TABS.filter((t) => t.id === 'table')

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
    <div className="rounded-[10px] overflow-hidden border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-default)' }}>

      {/* ── Header ── */}
      <div className="flex items-center gap-2 px-3 py-2 border-b" style={{ background: 'var(--bg-raised)', borderColor: 'var(--border-subtle)' }}>
        <span className="text-[12px] font-medium" style={{ color: 'var(--green)' }}>✓</span>
        <span className="text-[12px] font-medium" style={{ color: 'var(--text-1)' }}>
          {result.row_count.toLocaleString()} row{result.row_count !== 1 ? 's' : ''}
        </span>
        <span className="text-[11px]" style={{ color: 'var(--text-3)' }}>· {result.elapsed_ms} ms</span>

        <div className="ml-auto flex items-center gap-1">
          {visibleTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setView(tab.id)}
              className="flex items-center gap-1 px-1.5 sm:px-2 py-1 rounded-[6px] text-[11px] border transition-all"
              style={
                view === tab.id
                  ? { background: 'var(--accent-bg)', color: 'var(--accent-text)', borderColor: 'var(--accent-border)' }
                  : { background: 'transparent', color: 'var(--text-3)', borderColor: 'var(--border-default)' }
              }
            >
              <Icon name={tab.icon} size={11} />
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* ── TABLE ── */}
      {view === 'table' && (
        <div style={{ overflowX: 'auto' }}>
          <table className="w-full text-xs border-collapse" style={{ tableLayout: 'fixed' }}>
            <thead style={{ position: 'sticky', top: 0, zIndex: 1, background: 'var(--bg-raised)' }}>
              <tr>
                {result.columns.map((col, ci) => (
                  <th
                    key={col}
                    className="px-3 py-2 text-[10px] uppercase tracking-[0.5px] font-medium border-b"
                    style={{
                      color: 'var(--text-3)',
                      borderColor: 'var(--border-default)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      ...cellStyle(ci, result.rows),
                    }}
                    title={col}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, ri) => (
                <tr key={ri} style={{ background: ri % 2 === 1 ? 'var(--bg-raised)' : 'transparent' }}>
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      className="px-3 py-2 text-[12px] border-b"
                      style={{ color: 'var(--text-1)', borderColor: 'var(--border-subtle)', ...cellStyle(ci, result.rows) }}
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

      {/* ── BAR: simple (flat) ── */}
      {view === 'bar' && cols && !groupedLayout && (
        <div style={{ padding: '8px 16px 8px 0' }}>
          {sortedData.length > BAR_TOP && (
            <p className="text-right text-[10px] px-3 mb-1" style={{ color: 'var(--text-3)' }}>
              Top {BAR_TOP} of {sortedData.length}
            </p>
          )}
          <div style={{ height: Math.max(120, Math.min(CHART_H, barData.length * 40 + 60)) }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={barData} layout="vertical" margin={{ top: 4, right: 52, left: 8, bottom: 4 }}>
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
                  width={155}
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ fill: 'var(--bg-raised)' }}
                  formatter={(v) => [Number(v).toLocaleString(), result.columns[cols.valueCol]]}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={22}>
                  {barData.map((_, i) => (
                    <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                  ))}
                  <LabelList
                    dataKey="value"
                    position="right"
                    style={{ fontSize: 11, fill: 'var(--text-2)', fontVariantNumeric: 'tabular-nums' }}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ── BAR: grouped (multi-series) ── */}
      {view === 'bar' && groupedLayout && (
        <div style={{ padding: '8px 16px 8px 0' }}>
          <div style={{ height: Math.max(120, Math.min(CHART_H, groupedBarData.length * groupedLayout.seriesKeys.length * 26 + 80)) }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={groupedBarData} layout="vertical" margin={{ top: 4, right: 52, left: 8, bottom: 4 }}>
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
                  width={155}
                />
                <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'var(--bg-raised)' }} />
                <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-2)', paddingTop: 8 }} />
                {groupedLayout.seriesKeys.map((key, i) => (
                  <Bar key={key} dataKey={key} fill={PALETTE[i % PALETTE.length]} maxBarSize={18} radius={[0, 4, 4, 0]}>
                    <LabelList
                      dataKey={key}
                      position="right"
                      style={{ fontSize: 10, fill: 'var(--text-2)', fontVariantNumeric: 'tabular-nums' }}
                    />
                  </Bar>
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ── DONUT: simple ── */}
      {view === 'donut' && cols && !groupedLayout && (
        <div className="flex flex-col sm:flex-row sm:items-center">
          <div className="w-full sm:w-[280px] sm:flex-shrink-0 relative" style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={donutData}
                  cx="50%"
                  cy="50%"
                  innerRadius={72}
                  outerRadius={108}
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
                  formatter={(v) => [Number(v).toLocaleString(), '']}
                />
              </PieChart>
            </ResponsiveContainer>
            <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
              <span style={{ fontSize: 20, fontWeight: 600, color: 'var(--text-1)', fontVariantNumeric: 'tabular-nums' }}>
                {total.toLocaleString()}
              </span>
              <span style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>total</span>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto py-3 px-3 sm:pr-4 sm:pl-1" style={{ maxHeight: CHART_H }}>
            {donutData.map((d, i) => {
              const pct = total > 0 ? ((d.value / total) * 100).toFixed(1) : '0'
              return (
                <div key={i} className="flex items-center gap-2 py-1.5 border-b last:border-0" style={{ borderColor: 'var(--border-subtle)' }}>
                  <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: PALETTE[i % PALETTE.length] }} />
                  <span
                    className="flex-1 text-[12px] truncate"
                    style={{ color: 'var(--text-1)', direction: hasPersian(d.name) ? 'rtl' : 'ltr' }}
                  >
                    {d.name}
                  </span>
                  <span className="text-[12px] tabular-nums flex-shrink-0" style={{ color: 'var(--text-2)' }}>
                    {d.value.toLocaleString()}
                  </span>
                  <span className="text-[11px] tabular-nums w-10 text-right flex-shrink-0" style={{ color: 'var(--text-3)' }}>
                    {pct}%
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── DONUT: grouped (aggregate by series key) ── */}
      {view === 'donut' && groupedLayout && (
        <div className="flex flex-col sm:flex-row sm:items-center">
          <div className="w-full sm:w-[280px] sm:flex-shrink-0 relative" style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={groupedDonutData}
                  cx="50%"
                  cy="50%"
                  innerRadius={72}
                  outerRadius={108}
                  dataKey="value"
                  paddingAngle={2}
                  startAngle={90}
                  endAngle={-270}
                >
                  {groupedDonutData.map((_, i) => (
                    <Cell key={i} fill={PALETTE[i % PALETTE.length]} stroke="none" />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v) => [Number(v).toLocaleString(), '']}
                />
              </PieChart>
            </ResponsiveContainer>
            <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
              <span style={{ fontSize: 20, fontWeight: 600, color: 'var(--text-1)', fontVariantNumeric: 'tabular-nums' }}>
                {groupedTotal.toLocaleString()}
              </span>
              <span style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>total</span>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto py-3 px-3 sm:pr-4 sm:pl-1" style={{ maxHeight: CHART_H }}>
            {groupedDonutData.map((d, i) => {
              const pct = groupedTotal > 0 ? ((d.value / groupedTotal) * 100).toFixed(1) : '0'
              return (
                <div key={i} className="flex items-center gap-2 py-1.5 border-b last:border-0" style={{ borderColor: 'var(--border-subtle)' }}>
                  <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: PALETTE[i % PALETTE.length] }} />
                  <span
                    className="flex-1 text-[12px] truncate"
                    style={{ color: 'var(--text-1)', direction: hasPersian(d.name) ? 'rtl' : 'ltr' }}
                  >
                    {d.name}
                  </span>
                  <span className="text-[12px] tabular-nums flex-shrink-0" style={{ color: 'var(--text-2)' }}>
                    {d.value.toLocaleString()}
                  </span>
                  <span className="text-[11px] tabular-nums w-10 text-right flex-shrink-0" style={{ color: 'var(--text-3)' }}>
                    {pct}%
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── LINE: simple ── */}
      {view === 'line' && cols && !groupedLayout && (
        <div className="p-4" style={{ height: CHART_H }}>
          {showLineLimit && (
            <p className="text-right text-[10px] mb-1" style={{ color: 'var(--text-3)' }}>
              First {LINE_MAX} of {originalData.length} rows
            </p>
          )}
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={lineData} margin={{ top: 10, right: 16, left: -10, bottom: 0 }}>
              <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="4 2" />
              <XAxis
                dataKey="name"
                tick={<XTick />}
                axisLine={{ stroke: 'var(--border-default)' }}
                tickLine={false}
                height={130}
                interval={Math.max(0, Math.ceil(lineData.length / 15) - 1)}
              />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-3)' }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(v) => [Number(v).toLocaleString(), result.columns[cols.valueCol]]}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="var(--accent)"
                strokeWidth={2}
                dot={lineData.length <= 20 ? { fill: 'var(--accent)', strokeWidth: 0, r: 3 } : false}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── LINE: grouped (one line per series key) ── */}
      {view === 'line' && groupedLayout && (
        <div className="p-4" style={{ height: CHART_H }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={groupedData} margin={{ top: 10, right: 16, left: -10, bottom: 0 }}>
              <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="4 2" />
              <XAxis
                dataKey="name"
                tick={<XTick />}
                axisLine={{ stroke: 'var(--border-default)' }}
                tickLine={false}
                height={130}
                interval={0}
              />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-3)' }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-2)' }} />
              {groupedLayout.seriesKeys.map((key, i) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={PALETTE[i % PALETTE.length]}
                  strokeWidth={2}
                  dot={{ fill: PALETTE[i % PALETTE.length], strokeWidth: 0, r: 3 }}
                  activeDot={{ r: 5 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── AREA: simple ── */}
      {view === 'area' && cols && !groupedLayout && (
        <div className="p-4" style={{ height: CHART_H }}>
          {showLineLimit && (
            <p className="text-right text-[10px] mb-1" style={{ color: 'var(--text-3)' }}>
              First {LINE_MAX} of {originalData.length} rows
            </p>
          )}
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={lineData} margin={{ top: 10, right: 16, left: -10, bottom: 0 }}>
              <defs>
                <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b6ef5" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#3b6ef5" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="4 2" />
              <XAxis
                dataKey="name"
                tick={<XTick />}
                axisLine={{ stroke: 'var(--border-default)' }}
                tickLine={false}
                height={130}
                interval={Math.max(0, Math.ceil(lineData.length / 15) - 1)}
              />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-3)' }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(v) => [Number(v).toLocaleString(), result.columns[cols.valueCol]]}
              />
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

      {/* ── AREA: grouped (one area per series key) ── */}
      {view === 'area' && groupedLayout && (
        <div className="p-4" style={{ height: CHART_H }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={groupedData} margin={{ top: 10, right: 16, left: -10, bottom: 0 }}>
              <defs>
                {groupedLayout.seriesKeys.map((key, i) => (
                  <linearGradient key={key} id={`${gradId}-${i}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0.3} />
                    <stop offset="95%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0.02} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="4 2" />
              <XAxis
                dataKey="name"
                tick={<XTick />}
                axisLine={{ stroke: 'var(--border-default)' }}
                tickLine={false}
                height={130}
                interval={0}
              />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-3)' }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-2)' }} />
              {groupedLayout.seriesKeys.map((key, i) => (
                <Area
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={PALETTE[i % PALETTE.length]}
                  strokeWidth={2}
                  fill={`url(#${gradId}-${i})`}
                  dot={false}
                  activeDot={{ r: 5, fill: PALETTE[i % PALETTE.length] }}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
