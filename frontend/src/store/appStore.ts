import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AppPage, Theme } from '@/types'

interface AppState {
  theme: Theme
  activePage: AppPage
  activeSessionId: string | null
  defaultModelName: string

  setTheme: (t: Theme) => void
  toggleTheme: () => void
  setActivePage: (p: AppPage) => void
  setActiveSession: (id: string | null) => void
  setDefaultModel: (name: string) => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      theme: 'dark',
      activePage: 'chat',
      activeSessionId: null,
      defaultModelName: 'llama3-sqlcoder',

      setTheme: (theme) => {
        set({ theme })
        document.documentElement.className = theme
      },

      toggleTheme: () => {
        const next: Theme = get().theme === 'dark' ? 'light' : 'dark'
        get().setTheme(next)
      },

      setActivePage: (activePage) => set({ activePage }),
      setActiveSession: (activeSessionId) => set({ activeSessionId }),
      setDefaultModel: (defaultModelName) => set({ defaultModelName }),
    }),
    {
      name: 'bi-assistant-app',
      partialState: (s) => ({
        theme: s.theme,
        defaultModelName: s.defaultModelName,
      }),
    }
  )
)
