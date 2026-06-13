import { useEffect, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Sidebar } from '@/components/layout/Sidebar'
import { ChatPage } from '@/pages/ChatPage'
import { BuilderPage } from '@/pages/BuilderPage'
import { EvalPage } from '@/pages/EvalPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { useAppStore } from '@/store/appStore'
import { Icon } from '@/components/ui/Icon'
import apiClient from '@/services/apiClient'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})

function BackendOfflineDialog() {
  const backendOffline = useAppStore((s) => s.backendOffline)
  const [retrying, setRetrying] = useState(false)

  if (!backendOffline) return null

  const retry = async () => {
    setRetrying(true)
    try {
      await apiClient.get('/health')
      useAppStore.getState().setBackendOffline(false)
    } catch {
      useAppStore.getState().setBackendOffline(true)
    } finally {
      setRetrying(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
      <div
        className="w-full max-w-xs mx-4 rounded-2xl shadow-2xl"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-default)' }}
      >
        <div className="px-6 pt-7 pb-6 flex flex-col items-center text-center">
          <div
            className="w-12 h-12 rounded-2xl flex items-center justify-center mb-4"
            style={{ background: 'var(--red-bg)', border: '1px solid var(--red-border)' }}
          >
            <span style={{ color: 'var(--red)' }}>
              <Icon name="server" size={22} />
            </span>
          </div>
          <p className="text-[14px] font-semibold mb-1.5" style={{ color: 'var(--text-1)' }}>
            Connection Lost
          </p>
          <p className="text-[12px] leading-relaxed mb-5" style={{ color: 'var(--text-2)' }}>
            Cannot reach the server. Make sure the backend is running.
          </p>
          <button
            onClick={retry}
            disabled={retrying}
            className="w-full flex items-center justify-center gap-2 text-[12px] py-2 rounded-xl font-medium transition-opacity"
            style={{
              background: 'var(--accent)',
              color: '#fff',
              opacity: retrying ? 0.65 : 1,
            }}
          >
            {retrying && <Icon name="refresh" size={12} className="animate-spin" />}
            {retrying ? 'Connecting...' : 'Retry'}
          </button>
        </div>
      </div>
    </div>
  )
}

function AppShell() {
  const { theme, activePage } = useAppStore()

  useEffect(() => {
    document.documentElement.className = theme
  }, [theme])

  useEffect(() => {
    const ping = async () => {
      try {
        await apiClient.get('/health')
        useAppStore.getState().setBackendOffline(false)
      } catch {
        useAppStore.getState().setBackendOffline(true)
      }
    }
    ping()
    const id = setInterval(ping, 10_000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--bg-base)' }}>
      <Sidebar />
      <main className="flex flex-1 overflow-hidden min-w-0" style={{ background: 'var(--bg-base)' }}>
        {activePage === 'chat'     && <ChatPage />}
        {activePage === 'builder'  && <BuilderPage />}
        {activePage === 'eval'     && <EvalPage />}
        {activePage === 'settings' && <SettingsPage />}
      </main>
      <BackendOfflineDialog />
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppShell />
    </QueryClientProvider>
  )
}
