import { useState, useRef, useEffect } from 'react'
import { clsx } from 'clsx'
import { useAppStore } from '@/store/appStore'
import { useOllamaHealth, useProjects, useSessions, useCreateSession, useDeleteSession } from '@/hooks'
import { Modal } from '@/components/ui/Modal'
import { Icon } from '@/components/ui/Icon'
import type { AppPage } from '@/types'
import amrLogo from '@/assets/amr-logo.png'

const NAV: { page: AppPage; label: string; icon: Parameters<typeof Icon>[0]['name'] }[] = [
  { page: 'chat',    label: 'Chat',           icon: 'message' },
  { page: 'builder', label: 'Prompt Builder', icon: 'layers'  },
  { page: 'eval',    label: 'Evaluation',     icon: 'flask'   },
]

function SelectField({
  value, onChange, options, placeholder,
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
  placeholder?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const selected = options.find((o) => o.value === value)

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between rounded-[9px] px-3 py-2.5 text-[13px] text-left"
        style={{
          background: 'var(--bg-raised)',
          border: `1px solid ${open ? 'var(--accent)' : 'var(--border-default)'}`,
          color: selected ? 'var(--text-1)' : 'var(--text-3)',
        }}
      >
        <span className="truncate">{selected?.label ?? placeholder ?? 'Select…'}</span>
        <span style={{ color: 'var(--text-3)', flexShrink: 0, marginLeft: 8, transition: 'transform 150ms', transform: open ? 'rotate(180deg)' : 'rotate(0deg)', display: 'flex' }}>
          <Icon name="chevron-down" size={13} />
        </span>
      </button>

      {open && (
        <div
          className="absolute z-[100] left-0 right-0 mt-1 rounded-[9px] overflow-y-auto"
          style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)', boxShadow: '0 8px 24px rgba(0,0,0,0.18)', maxHeight: 220 }}
        >
          {options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => { onChange(opt.value); setOpen(false) }}
              className="w-full text-left px-3 py-2.5 text-[13px]"
              style={{
                background: opt.value === value ? 'var(--accent-bg)' : 'transparent',
                color: opt.value === value ? 'var(--accent-text)' : 'var(--text-1)',
              }}
              onMouseEnter={(e) => { if (opt.value !== value) e.currentTarget.style.background = 'var(--bg-raised)' }}
              onMouseLeave={(e) => { if (opt.value !== value) e.currentTarget.style.background = 'transparent' }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

type Session = {
  id: string
  title: string
  project_id: string | null
  model_name: string
  created_at: string
  updated_at: string
}

function groupByDate(sessions: Session[]): Record<string, Session[]> {
  const now = new Date()
  const yest = new Date(now)
  yest.setDate(yest.getDate() - 1)
  const groups: Record<string, Session[]> = {}
  for (const s of sessions) {
    const d = new Date(s.updated_at || s.created_at)
    let label = 'Older'
    if (sameDay(d, now)) label = 'Today'
    else if (sameDay(d, yest)) label = 'Yesterday'
    else if (now.getTime() - d.getTime() < 7 * 86_400_000) label = 'This week'
    if (!groups[label]) groups[label] = []
    groups[label].push(s)
  }
  return groups
}

function sameDay(a: Date, b: Date) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

export function Sidebar() {
  const { theme, toggleTheme, activePage, setActivePage, activeSessionId, setActiveSession, defaultModelName } =
    useAppStore()
  const { data: health } = useOllamaHealth()
  const { data: sessions } = useSessions()
  const { data: projects } = useProjects()
  const createSession = useCreateSession()
  const deleteSession = useDeleteSession()

  const [collapsed, setCollapsed] = useState(false)
  const [newChatOpen, setNewChatOpen] = useState(false)
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [selectedModel, setSelectedModel] = useState(defaultModelName)

  const grouped = groupByDate((sessions ?? []) as Session[])
  const isOnline = health?.online ?? false
  const modelName = health?.models[0]?.name?.split(':')[0] ?? ''

  function openNewChat() {
    setSelectedModel(defaultModelName)
    setNewChatOpen(true)
  }

  async function handleCreateSession() {
    const session = await createSession.mutateAsync({
      project_id: selectedProjectId || null,
      model_name: selectedModel,
      title: 'New chat',
    })
    setActiveSession(session.id)
    setActivePage('chat')
    setNewChatOpen(false)
  }

  // ── COLLAPSED ──────────────────────────────────────────────────────────────
  if (collapsed) {
    return (
      <aside
        className="w-[56px] min-w-[56px] flex flex-col"
        style={{ background: 'var(--bg-surface)', borderRight: '1px solid var(--border-default)' }}
      >
        {/* Brand mark */}
        <div
          className="py-3 flex justify-center flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}
        >
          <img src={amrLogo} alt="Amin Raay" className="w-8 h-8 object-contain" />
        </div>

        {/* Expand + Nav */}
        <div className="flex flex-col items-center gap-1 p-2 pt-3">
          <button
            onClick={() => setCollapsed(false)}
            className="w-7 h-7 rounded-[7px] flex items-center justify-center transition-opacity hover:opacity-70"
            style={{ color: 'var(--text-3)' }}
            title="Expand"
          >
            <Icon name="arrow-right" size={14} />
          </button>
          <div className="h-px w-6 my-1" style={{ background: 'var(--border-subtle)' }} />
          {NAV.map((item) => (
            <button
              key={item.page}
              onClick={() => setActivePage(item.page)}
              title={item.label}
              className="w-9 h-9 rounded-[8px] flex items-center justify-center transition-colors"
              style={{
                background: activePage === item.page ? 'var(--accent-bg)' : 'transparent',
                color: activePage === item.page ? 'var(--accent-text)' : 'var(--text-3)',
              }}
            >
              <Icon name={item.icon} size={17} />
            </button>
          ))}
        </div>

        <div className="flex-1" />

        {/* Bottom actions */}
        <div
          className="p-2 flex flex-col items-center gap-2 flex-shrink-0"
          style={{ borderTop: '1px solid var(--border-default)' }}
        >
          <button
            onClick={openNewChat}
            title="New chat"
            className="w-8 h-8 rounded-[8px] flex items-center justify-center transition-opacity hover:opacity-80"
            style={{ background: 'var(--accent)', color: '#fff' }}
          >
            <Icon name="plus" size={15} />
          </button>
          <button
            onClick={() => setActivePage('settings')}
            title="Settings"
            className="w-8 h-8 rounded-[8px] flex items-center justify-center transition-colors"
            style={{
              background: activePage === 'settings' ? 'var(--accent-bg)' : 'transparent',
              color: activePage === 'settings' ? 'var(--accent-text)' : 'var(--text-3)',
            }}
          >
            <Icon name="settings" size={14} />
          </button>
          <div
            className="w-2 h-2 rounded-full"
            style={{ background: isOnline ? '#22c55e' : 'var(--text-3)' }}
            title={isOnline ? 'Ollama online' : 'Ollama offline'}
          />
          <button
            onClick={toggleTheme}
            title={`Theme: ${theme} — click to switch`}
            className="w-8 h-8 rounded-[8px] flex items-center justify-center transition-colors hover:opacity-80"
            style={{ border: '1px solid var(--border-default)', color: 'var(--text-2)' }}
          >
            {theme === 'amin-rai'
              ? <span style={{ width: 14, height: 14, borderRadius: '50%', background: '#3DBFB9', display: 'inline-block', flexShrink: 0 }} />
              : <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={14} />}
          </button>
        </div>
      </aside>
    )
  }

  // ── EXPANDED ───────────────────────────────────────────────────────────────
  return (
    <>
      <aside
        className="w-[224px] min-w-[224px] flex flex-col"
        style={{ background: 'var(--bg-surface)', borderRight: '1px solid var(--border-default)' }}
      >
        {/* ── Brand header ── */}
        <div
          className="px-3.5 py-3 flex items-center gap-2.5 flex-shrink-0"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}
        >
          <img src={amrLogo} alt="Amin Raay" className="w-8 h-8 object-contain flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-[13px] font-semibold truncate" style={{ color: 'var(--text-1)' }}>AminRaay</p>
            <p className="text-[10px]" style={{ color: 'var(--text-3)' }}>BI Assistant</p>
          </div>
          <button
            onClick={() => setCollapsed(true)}
            className="w-6 h-6 rounded-[6px] flex items-center justify-center flex-shrink-0 transition-opacity hover:opacity-70"
            style={{ color: 'var(--text-3)' }}
            title="Collapse"
          >
            <Icon name="arrow-left" size={13} />
          </button>
        </div>

        {/* ── Nav (Chat + Builder only) ── */}
        <nav className="px-2 pt-2 flex-shrink-0">
          {NAV.map((item) => (
            <button
              key={item.page}
              onClick={() => setActivePage(item.page)}
              className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-[8px] text-[12.5px] mb-0.5 transition-colors text-left"
              style={{
                background: activePage === item.page ? 'var(--accent-bg)' : 'transparent',
                color: activePage === item.page ? 'var(--accent-text)' : 'var(--text-2)',
              }}
            >
              <Icon name={item.icon} size={15} />
              {item.label}
            </button>
          ))}
          <div className="h-px my-2 mx-1" style={{ background: 'var(--border-subtle)' }} />
        </nav>

        {/* ── Session list ── */}
        <div className="flex-1 overflow-y-auto px-2 pb-2">
          {Object.entries(grouped).map(([group, items]) => (
            <div key={group}>
              <p
                className="text-[10px] font-semibold uppercase tracking-[0.8px] px-2 pt-3 pb-1.5"
                style={{ color: 'var(--text-3)' }}
              >
                {group}
              </p>
              {items.map((s) => {
                const isActive = activeSessionId === s.id
                const projectName = s.project_id ? (projects ?? []).find((p) => p.id === s.project_id)?.name : null
                return (
                  <div
                    key={s.id}
                    onClick={() => { setActiveSession(s.id); setActivePage('chat') }}
                    className="group flex items-center gap-2 px-2.5 py-2 rounded-[8px] mb-0.5 cursor-pointer transition-colors"
                    style={{ background: isActive ? 'var(--accent-bg)' : 'transparent' }}
                    onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--bg-raised)' }}
                    onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent' }}
                  >
                    <div className="flex-1 min-w-0">
                      <p
                        className="text-[12px] truncate"
                        style={{ color: isActive ? 'var(--accent-text)' : 'var(--text-1)' }}
                      >
                        {s.title}
                      </p>
                      <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                        {projectName && (
                          <span
                            className="text-[9px] font-medium px-1.5 py-[2px] rounded-[4px] flex-shrink-0 max-w-[90px] truncate"
                            style={{ background: 'var(--accent-bg)', color: 'var(--accent-text)', border: '1px solid var(--accent-border)' }}
                          >
                            {projectName}
                          </span>
                        )}
                        <span className="text-[10px] truncate" style={{ color: 'var(--text-3)' }}>
                          {s.model_name?.split(':')[0]}
                        </span>
                      </div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        deleteSession.mutate(s.id)
                        if (activeSessionId === s.id) setActiveSession(null)
                      }}
                      className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                      style={{ color: 'var(--text-3)' }}
                      onMouseEnter={(e) => (e.currentTarget.style.color = '#f87171')}
                      onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-3)')}
                    >
                      <Icon name="trash" size={13} />
                    </button>
                  </div>
                )
              })}
            </div>
          ))}
        </div>

        {/* ── New chat button ── */}
        <div
          className="px-2 py-2 flex-shrink-0"
          style={{ borderTop: '1px solid var(--border-subtle)' }}
        >
          <button
            onClick={openNewChat}
            className="w-full relative flex items-center justify-center py-2 rounded-[10px] text-xs font-medium transition-opacity hover:opacity-90"
            style={{ background: 'var(--accent)', color: '#fff' }}
          >
            <Icon name="plus" size={14} className="absolute left-3 top-1/2 -translate-y-1/2" />
            <span>New chat</span>
          </button>
        </div>

        {/* ── Footer: Settings + Ollama status + Theme ── */}
        <div
          className="px-3 py-2.5 flex items-center gap-2 flex-shrink-0"
          style={{ borderTop: '1px solid var(--border-default)' }}
        >
          <button
            onClick={() => setActivePage('settings')}
            className={clsx(
              'flex items-center gap-1.5 text-[11px] transition-opacity hover:opacity-80 flex-shrink-0',
            )}
            style={{ color: activePage === 'settings' ? 'var(--accent-text)' : 'var(--text-3)' }}
          >
            <Icon name="settings" size={13} />
            Settings
          </button>

          <div className="flex items-center gap-1.5 flex-1 justify-end min-w-0 overflow-hidden">
            <div
              className="w-1.5 h-1.5 rounded-full flex-shrink-0"
              style={{ background: isOnline ? '#22c55e' : 'var(--text-3)' }}
            />
            {modelName && (
              <span className="text-[10px] truncate" style={{ color: 'var(--text-3)' }}>
                {modelName}
              </span>
            )}
          </div>

          <button
            onClick={toggleTheme}
            title={`Theme: ${theme} — click to switch`}
            className="w-7 h-7 rounded-[7px] flex items-center justify-center flex-shrink-0 transition-colors hover:opacity-80"
            style={{ border: '1px solid var(--border-default)', color: 'var(--text-2)' }}
          >
            {theme === 'amin-rai'
              ? <span style={{ width: 12, height: 12, borderRadius: '50%', background: '#3DBFB9', display: 'inline-block' }} />
              : <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={14} />}
          </button>
        </div>
      </aside>

      {/* ── New chat modal ── */}
      <Modal open={newChatOpen} title="New chat" onClose={() => setNewChatOpen(false)}>
        <div className="flex flex-col gap-5">
          {/* Project */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-semibold uppercase tracking-[0.6px]" style={{ color: 'var(--text-3)' }}>
              Project
            </label>
            <SelectField
              value={selectedProjectId}
              onChange={setSelectedProjectId}
              placeholder="No project"
              options={[
                { value: '', label: 'No project' },
                ...(projects ?? []).map((p) => ({ value: p.id, label: p.name })),
              ]}
            />
          </div>

          {/* Model */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-semibold uppercase tracking-[0.6px]" style={{ color: 'var(--text-3)' }}>
              Model
            </label>
            <SelectField
              value={selectedModel}
              onChange={setSelectedModel}
              options={
                health?.models.length
                  ? health.models.map((m) => ({
                      value: m.name,
                      label: m.name.replace(/:latest$/, '') + (m.size ? `  ·  ${m.size}` : ''),
                    }))
                  : [{ value: defaultModelName, label: defaultModelName.replace(/:latest$/, '') }]
              }
            />
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            <button
              onClick={() => setNewChatOpen(false)}
              className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium transition-opacity hover:opacity-70"
              style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-2)' }}
            >
              Cancel
            </button>
            <button
              onClick={handleCreateSession}
              className="flex-1 py-2.5 rounded-[9px] text-[13px] font-medium transition-opacity hover:opacity-90"
              style={{ background: 'var(--accent)', color: '#fff' }}
            >
              Start chat
            </button>
          </div>
        </div>
      </Modal>
    </>
  )
}
