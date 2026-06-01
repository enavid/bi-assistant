import { useState } from 'react'
import { clsx } from 'clsx'
import { useAppStore } from '@/store/appStore'
import { useOllamaHealth, useProjects, useSessions, useCreateSession, useDeleteSession } from '@/hooks'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import type { AppPage } from '@/types'

const NAV: { page: AppPage; label: string; icon: Parameters<typeof Icon>[0]['name'] }[] = [
  { page: 'chat',     label: 'Chat',           icon: 'message' },
  { page: 'builder',  label: 'Prompt Builder', icon: 'layers'  },
  { page: 'settings', label: 'Settings',       icon: 'settings'},
]

export function Sidebar() {
  const { theme, toggleTheme, activePage, setActivePage, activeSessionId, setActiveSession, defaultModelName } = useAppStore()
  const { data: health } = useOllamaHealth()
  const { data: sessions } = useSessions()
  const { data: projects } = useProjects()
  const createSession = useCreateSession()
  const deleteSession = useDeleteSession()

  const [newChatOpen, setNewChatOpen] = useState(false)
  const [selectedProjectId, setSelectedProjectId] = useState<string>('')
  const [selectedModel, setSelectedModel] = useState(defaultModelName)

  const grouped = groupSessionsByDate(sessions ?? [])

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

  return (
    <>
      <aside className="w-[236px] min-w-[236px] flex flex-col bg-bg-surface border-r border-border-default">
        {/* Brand */}
        <div className="p-3.5 pb-2.5 border-b border-border-subtle">
          <div className="flex items-center gap-2.5 mb-3">
            <div className="w-[30px] h-[30px] rounded-[7px] flex items-center justify-center bg-accent-bg border border-accent-border flex-shrink-0">
              <Icon name="bar-chart" size={16} className="text-accent-text" />
            </div>
            <div>
              <div className="text-sm font-medium text-text-1">BI Assistant</div>
              <div className="text-[10px] text-text-3 mt-0.5">HR Analytics</div>
            </div>
          </div>
          <button
            onClick={() => setNewChatOpen(true)}
            className="w-full px-3 py-1.5 rounded-[8px] bg-accent-bg border border-accent-border text-accent-text text-xs font-medium flex items-center gap-1.5 hover:opacity-90 transition-opacity"
          >
            <Icon name="plus" size={14} /> New chat
          </button>
        </div>

        {/* Nav */}
        <nav className="px-2 pt-2 flex-shrink-0">
          {NAV.map((item) => (
            <button
              key={item.page}
              onClick={() => setActivePage(item.page)}
              className={clsx(
                'w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-[7px] text-xs mb-0.5 transition-colors text-left',
                activePage === item.page
                  ? 'bg-accent-bg text-accent-text'
                  : 'text-text-2 hover:bg-bg-raised hover:text-text-1'
              )}
            >
              <Icon name={item.icon} size={15} />
              {item.label}
            </button>
          ))}
          <div className="h-px bg-border-subtle mx-2 my-1.5" />
        </nav>

        {/* History */}
        <div className="flex-1 overflow-y-auto px-2 pb-2">
          {Object.entries(grouped).map(([group, items]) => (
            <div key={group}>
              <div className="text-[10px] font-medium text-text-3 uppercase tracking-[0.6px] px-2 py-2.5 pb-1">
                {group}
              </div>
              {items.map((s) => {
                const project = projects?.find((p) => p.id === s.project_id)
                return (
                  <div
                    key={s.id}
                    className={clsx(
                      'group flex items-start gap-1 px-2 py-1.5 rounded-[7px] mb-0.5 cursor-pointer transition-colors',
                      activeSessionId === s.id ? 'bg-accent-bg' : 'hover:bg-bg-raised'
                    )}
                    onClick={() => { setActiveSession(s.id); setActivePage('chat') }}
                  >
                    <div className="flex-1 min-w-0">
                      <div className={clsx('text-xs truncate', activeSessionId === s.id ? 'text-accent-text' : 'text-text-2')}>
                        {s.title}
                      </div>
                      <div className="flex items-center gap-1 mt-0.5">
                        {project && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded-[3px] bg-bg-raised border border-border-default text-text-3 truncate max-w-[100px]">
                            {project.name}
                          </span>
                        )}
                        <span className="text-[9px] text-text-3">{s.model_name.split(':')[0]}</span>
                      </div>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteSession.mutate(s.id) }}
                      className="opacity-0 group-hover:opacity-100 text-text-3 hover:text-red-400 transition-all flex-shrink-0 mt-0.5"
                    >
                      <Icon name="trash" size={12} />
                    </button>
                  </div>
                )
              })}
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="px-3.5 py-2.5 border-t border-border-default flex items-center gap-2 flex-shrink-0">
          <div
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{ background: health?.online ? 'var(--green)' : 'var(--text-3)' }}
          />
          <span className="text-[11px] text-text-2 flex-1 truncate">
            {health?.online ? health.models[0]?.name ?? 'online' : 'offline'}
          </span>
          <div className="w-[26px] h-[26px] rounded-full flex items-center justify-center bg-accent-bg border border-accent-border text-[10px] font-medium text-accent-text flex-shrink-0 cursor-pointer">
            N
          </div>
          <button
            onClick={toggleTheme}
            className="w-[26px] h-[26px] rounded-[7px] flex items-center justify-center border border-border-default hover:bg-bg-raised flex-shrink-0 text-text-2"
            aria-label="Toggle theme"
          >
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={14} />
          </button>
        </div>
      </aside>

      {/* New Chat Modal */}
      <Modal open={newChatOpen} title="New chat" onClose={() => setNewChatOpen(false)}>
        <div className="flex flex-col gap-3">
          <div>
            <label className="text-[11px] font-medium text-text-2 block mb-1.5">Project</label>
            <select
              value={selectedProjectId}
              onChange={(e) => setSelectedProjectId(e.target.value)}
              className="w-full bg-bg-raised border border-border-default rounded-[7px] px-3 py-2 text-xs text-text-1 outline-none focus:border-accent"
            >
              <option value="">No project</option>
              {projects?.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[11px] font-medium text-text-2 block mb-1.5">Model</label>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="w-full bg-bg-raised border border-border-default rounded-[7px] px-3 py-2 text-xs text-text-1 outline-none focus:border-accent"
            >
              {health?.models.length
                ? health.models.map((m) => (
                    <option key={m.name} value={m.name}>{m.name} {m.size && `· ${m.size}`}</option>
                  ))
                : <option value={defaultModelName}>{defaultModelName}</option>
              }
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

type S = { id: string; title: string; project_id: string | null; model_name: string; created_at: string }

function groupSessionsByDate(sessions: S[]): Record<string, S[]> {
  const today = new Date()
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1)
  const groups: Record<string, S[]> = {}
  for (const s of [...sessions].reverse()) {
    const d = new Date(s.created_at)
    let label = 'Older'
    if (sameDay(d, today)) label = 'Today'
    else if (sameDay(d, yesterday)) label = 'Yesterday'
    else if (today.getTime() - d.getTime() < 7 * 86_400_000) label = 'This week'
    if (!groups[label]) groups[label] = []
    groups[label].push(s)
  }
  return groups
}

function sameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}
