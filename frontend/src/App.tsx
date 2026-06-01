import { useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Sidebar } from '@/components/layout/Sidebar'
import { ChatPage } from '@/pages/ChatPage'
import { BuilderPage } from '@/pages/BuilderPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { useAppStore } from '@/store/appStore'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})

function AppShell() {
  const { theme, activePage } = useAppStore()

  useEffect(() => {
    document.documentElement.className = theme
  }, [theme])

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--bg-base)' }}>
      <Sidebar />
      <main className="flex flex-1 overflow-hidden min-w-0" style={{ background: 'var(--bg-base)' }}>
        {activePage === 'chat'     && <ChatPage />}
        {activePage === 'builder'  && <BuilderPage />}
        {activePage === 'settings' && <SettingsPage />}
      </main>
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
