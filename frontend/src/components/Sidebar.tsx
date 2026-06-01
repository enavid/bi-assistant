import { useNavigate, useLocation } from 'react-router-dom'
import { useOllamaHealth } from '@/hooks/useOllamaHealth'
import { useSessions, useCreateSession } from '@/hooks/useSessions'
import { useTemplates } from '@/hooks/useTemplates'
import { useAppStore } from '@/store/appStore'
import { clsx } from 'clsx'

const NAV_ITEMS = [
  { path: '/', label: 'Chat', icon: 'ti-message' },
  { path: '/builder', label: 'Prompt Builder', icon: 'ti-layout-grid' },
  { path: '/settings', label: 'Settings', icon: 'ti-settings' },
]

export function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { data: health } = useOllamaHealth()
  const { data: sessions } = useSessions()
  const { data: templates } = useTemplates()
  const { theme, toggleTheme, activeSessionId, setActiveSession, defaultModelName } = useAppStore()
  const createSession = useCreateSession()

  const activeTemplate = templates?.find((t) => t.active)

  const grouped = groupByDate(sessions ?? [])

async function handleNewChat() {
  const session = await createSession.mutateAsync({
    title: 'New chat',
    model_name: activeTemplate?.name ?? defaultModelName,
    project_id: null,
  })
  setActiveSession(session.id)
  navigate('/')
}

  return (
    <aside className="w-[236px] min-w-[236px] flex flex-col bg-bg-surface border-r border-border-default">
      <div className="p-3.5 pb-2.5 border-b border-border-subtle">
        <div className="flex items-center gap-2.5 mb-3">
          <div className="w-[30px] h-[30px] rounded-[7px] flex items-center justify-center bg-accent-bg border border-accent-border flex-shrink-0">
            <i className="ti ti-chart-bar text-accent-text" style={{ fontSize: 16 }} aria-hidden />
          </div>
          <div>
            <div className="text-sm font-medium text-text-1">BI Assistant</div>
            <div className="text-[10px] text-text-3 mt-0.5">HR Analytics</div>
          </div>
        </div>
        <button
          onClick={handleNewChat}
          className="w-full px-3 py-1.5 rounded-[8px] bg-accent-bg border border-accent-border text-accent-text text-xs font-medium flex items-center gap-1.5 hover:opacity-90 transition-opacity"
        >
          <i className="ti ti-plus" style={{ fontSize: 15 }} aria-hidden />
          New chat
        </button>
      </div>

      <nav className="px-2 pt-2 flex-shrink-0">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.path}
            onClick={() => navigate(item.path)}
            className={clsx(
              'w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-[7px] text-xs mb-0.5 transition-colors text-left',
              location.pathname === item.path
                ? 'bg-accent-bg text-accent-text'
                : 'text-text-2 hover:bg-bg-raised hover:text-text-1'
            )}
          >
            <i className={clsx('ti', item.icon)} style={{ fontSize: 16 }} aria-hidden />
            {item.label}
          </button>
        ))}
        <div className="h-px bg-border-subtle mx-2 my-1.5" />
      </nav>

      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {Object.entries(grouped).map(([group, items]) => (
          <div key={group}>
            <div className="text-[10px] font-medium text-text-3 uppercase tracking-[0.6px] px-2 py-2.5 pb-1">
              {group}
            </div>
            {items.map((s) => (
              <button
                key={s.id}
                onClick={() => { setActiveSession(s.id); navigate('/') }}
                className={clsx(
                  'w-full px-2.5 py-1.5 rounded-[7px] mb-0.5 text-left transition-colors',
                  activeSessionId === s.id ? 'bg-accent-bg' : 'hover:bg-bg-raised'
                )}
              >
                <div className={clsx('text-xs truncate', activeSessionId === s.id ? 'text-accent-text' : 'text-text-2')}>
                  {s.title}
                </div>
                <div className="flex items-center gap-1 mt-0.5">
                  <span className="text-[9px] px-1.5 py-0.5 rounded-[3px] bg-bg-raised border border-border-default text-text-3">
                    {s.prompt_template_name}
                  </span>
                </div>
              </button>
            ))}
          </div>
        ))}
      </div>

      <div className="px-3.5 py-2.5 border-t border-border-default flex-shrink-0">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            <div
              className="w-[7px] h-[7px] rounded-full flex-shrink-0"
              style={{ background: health?.online ? 'var(--green)' : 'var(--text-3)' }}
            />
            <span className="text-[11px] text-text-2 truncate">
              {health?.models[0]?.name ?? 'connecting…'}
            </span>
          </div>
          <div className="w-[26px] h-[26px] rounded-full flex items-center justify-center bg-accent-bg border border-accent-border text-[10px] font-medium text-accent-text flex-shrink-0 cursor-pointer">
            N
          </div>
          <button
            onClick={toggleTheme}
            className="w-[26px] h-[26px] rounded-[7px] flex items-center justify-center border border-border-default hover:bg-bg-raised flex-shrink-0"
            aria-label="Toggle theme"
          >
            <i className={clsx('ti', theme === 'dark' ? 'ti-sun' : 'ti-moon')} style={{ fontSize: 14, color: 'var(--text-2)' }} aria-hidden />
          </button>
        </div>
      </div>
    </aside>
  )
}

type SessionItem = { id: string; title: string; prompt_template_name?: string; created_at: string }
function groupByDate(sessions: SessionItem[]): Record<string, SessionItem[]> {
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  const groups: Record<string, SessionItem[]> = {}

  for (const s of [...sessions].reverse()) {
    const d = new Date(s.created_at)
    let label = 'Older'
    if (isSameDay(d, today)) label = 'Today'
    else if (isSameDay(d, yesterday)) label = 'Yesterday'
    else if (today.getTime() - d.getTime() < 7 * 86_400_000) label = 'This week'
    if (!groups[label]) groups[label] = []
    groups[label].push(s)
  }
  return groups
}

function isSameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
}
