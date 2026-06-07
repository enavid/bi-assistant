import { useState } from 'react'
import { clsx } from 'clsx'
import { useAppStore } from '@/store/appStore'
import { useOllamaHealth, useProjects, useSessions, useCreateSession, useDeleteSession } from '@/hooks'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import type { AppPage } from '@/types'

const NAV: { page: AppPage; label: string; icon: Parameters<typeof Icon>[0]['name'] }[] = [
  { page: 'chat',     label: 'Chat',           icon: 'message'  },
  { page: 'builder',  label: 'Prompt Builder', icon: 'layers'   },
  { page: 'settings', label: 'Settings',       icon: 'settings' },
]

type Session = { id: string; title: string; project_id: string | null; model_name: string; created_at: string; updated_at: string }

function groupByDate(sessions: Session[]): Record<string, Session[]> {
  const now = new Date()
  const yest = new Date(now); yest.setDate(yest.getDate() - 1)
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
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

export function Sidebar() {
  const { theme, toggleTheme, activePage, setActivePage, activeSessionId, setActiveSession, defaultModelName } = useAppStore()
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

  if (collapsed) {
    return (
      <aside className="w-[56px] min-w-[56px] flex flex-col" style={{ background: 'var(--bg-surface)', borderRight: '1px solid var(--border-default)' }}>
        <div className="p-3 flex flex-col items-center gap-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          <div className="w-8 h-8 rounded-[9px] flex items-center justify-center" style={{ background: 'var(--accent-bg)', border: '1px solid var(--accent-border)' }}>
            <Icon name="bar-chart" size={16} className="text-accent-text" />
          </div>
          <button onClick={() => setCollapsed(false)} className="w-7 h-7 rounded-[7px] flex items-center justify-center transition-colors hover:opacity-70" style={{ color: 'var(--text-3)' }} title="Expand">
            <Icon name="arrow-right" size={14} />
          </button>
        </div>
        <nav className="flex flex-col items-center gap-1 p-2 pt-3">
          {NAV.map((item) => (
            <button key={item.page} onClick={() => setActivePage(item.page)} title={item.label}
              className="w-9 h-9 rounded-[8px] flex items-center justify-center transition-colors"
              style={{
                background: activePage === item.page ? 'var(--accent-bg)' : 'transparent',
                color: activePage === item.page ? 'var(--accent-text)' : 'var(--text-3)',
              }}>
              <Icon name={item.icon} size={17} />
            </button>
          ))}
        </nav>
        <div className="flex-1" />
        <div className="p-2 flex flex-col items-center gap-2" style={{ borderTop: '1px solid var(--border-default)' }}>
          <div className="w-2 h-2 rounded-full" style={{ background: health?.online ? '#22c55e' : 'var(--text-3)' }} />
          <button onClick={toggleTheme} className="w-8 h-8 rounded-[8px] flex items-center justify-center border transition-colors hover:opacity-80" style={{ border: '1px solid var(--border-default)', color: 'var(--text-2)' }}>
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={14} />
          </button>
        </div>
      </aside>
    )
  }

  return (
    <>
      <aside className="w-[224px] min-w-[224px] flex flex-col" style={{ background: 'var(--bg-surface)', borderRight: '1px solid var(--border-default)' }}>

        {/* Header */}
        <div className="px-4 py-3 flex-shrink-0" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          <div className="flex items-center gap-2.5 mb-3">
            <div className="w-8 h-8 rounded-[9px] flex items-center justify-center flex-shrink-0" style={{ background: 'var(--accent-bg)', border: '1px solid var(--accent-border)' }}>
              <Icon name="bar-chart" size={16} className="text-accent-text" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[13px] font-semibold" style={{ color: 'var(--text-1)' }}>BI Assistant</p>
              <p className="text-[10px]" style={{ color: 'var(--text-3)' }}>HR Analytics</p>
            </div>
            <button onClick={() => setCollapsed(true)} className="w-6 h-6 rounded-[6px] flex items-center justify-center flex-shrink-0 transition-colors hover:opacity-70" style={{ color: 'var(--text-3)' }} title="Collapse">
              <Icon name="arrow-left" size={13} />
            </button>
          </div>

          <button
            onClick={() => { setSelectedModel(defaultModelName); setNewChatOpen(true) }}
            className="w-full flex items-center justify-center gap-2 py-2 rounded-[10px] text-xs font-medium transition-opacity hover:opacity-90"
            style={{ background: 'var(--accent)', color: '#fff' }}
          >
            <Icon name="plus" size={14} /> New chat
          </button>
        </div>

        {/* Nav */}
        <nav className="px-2 pt-2 flex-shrink-0">
          {NAV.map((item) => (
            <button key={item.page} onClick={() => setActivePage(item.page)}
              className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-[8px] text-[12.5px] mb-0.5 transition-colors text-left"
              style={{
                background: activePage === item.page ? 'var(--accent-bg)' : 'transparent',
                color: activePage === item.page ? 'var(--accent-text)' : 'var(--text-2)',
              }}>
              <Icon name={item.icon} size={15} />
              {item.label}
            </button>
          ))}
          <div className="h-px my-2 mx-1" style={{ background: 'var(--border-subtle)' }} />
        </nav>

        {/* Session list */}
        <div className="flex-1 overflow-y-auto px-2 pb-2">
          {Object.entries(grouped).map(([group, items]) => (
            <div key={group}>
              <p className="text-[10px] font-semibold uppercase tracking-[0.8px] px-2 pt-3 pb-1.5" style={{ color: 'var(--text-3)' }}>{group}</p>
              {items.map((s) => {
                const isActive = activeSessionId === s.id
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
                      <p className="text-[12px] truncate" style={{ color: isActive ? 'var(--accent-text)' : 'var(--text-1)' }}>
                        {s.title}
                      </p>
                      <p className="text-[10px] mt-0.5" style={{ color: 'var(--text-3)' }}>
                        {s.model_name?.split(':')[0]}
                      </p>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteSession.mutate(s.id) }}
                      className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                      style={{ color: 'var(--text-3)' }}
                      onMouseEnter={(e) => e.currentTarget.style.color = '#f87171'}
                      onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-3)'}
                    >
                      <Icon name="trash" size={13} />
                    </button>
                  </div>
                )
              })}
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="px-3 py-2.5 flex items-center gap-2 flex-shrink-0" style={{ borderTop: '1px solid var(--border-default)' }}>
          <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: health?.online ? '#22c55e' : 'var(--text-3)' }} />
          <span className="text-[11px] flex-1 truncate" style={{ color: 'var(--text-2)' }}>
            {health?.online ? (health.models[0]?.name?.split(':')[0] ?? 'online') : 'offline'}
          </span>
          <button onClick={toggleTheme}
            className="w-7 h-7 rounded-[7px] flex items-center justify-center flex-shrink-0 transition-colors hover:opacity-80"
            style={{ border: '1px solid var(--border-default)', color: 'var(--text-2)' }}>
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={14} />
          </button>
        </div>
      </aside>

      <Modal open={newChatOpen} title="New chat" onClose={() => setNewChatOpen(false)}>
        <div className="flex flex-col gap-3">
          <div>
            <label className="text-[11px] font-medium block mb-1.5" style={{ color: 'var(--text-2)' }}>Project</label>
            <select value={selectedProjectId} onChange={(e) => setSelectedProjectId(e.target.value)} className="w-full rounded-[7px] px-3 py-2 text-xs outline-none" style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-1)' }}>
              <option value="">No project</option>
              {projects?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[11px] font-medium block mb-1.5" style={{ color: 'var(--text-2)' }}>Model</label>
            <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} className="w-full rounded-[7px] px-3 py-2 text-xs outline-none" style={{ background: 'var(--bg-raised)', border: '1px solid var(--border-default)', color: 'var(--text-1)' }}>
              {health?.models.length
                ? health.models.map((m) => <option key={m.name} value={m.name}>{m.name}{m.size ? ` · ${m.size}` : ''}</option>)
                : <option value={defaultModelName}>{defaultModelName}</option>}
            </select>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" size="sm" onClick={() => setNewChatOpen(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={handleCreateSession}>Start chat</Button>
          </div>
        </div>
      </Modal>
    </>
  )
}
