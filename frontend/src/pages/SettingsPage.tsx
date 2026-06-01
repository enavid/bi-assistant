import { useState } from 'react'
import { clsx } from 'clsx'
import { useOllamaHealth } from '@/hooks'
import { useAppStore } from '@/store/appStore'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'

type Section = 'ollama' | 'database' | 'appearance'

export function SettingsPage() {
  const [section, setSection] = useState<Section>('ollama')
  const { data: health, refetch, isFetching } = useOllamaHealth()
  const { defaultModelName, setDefaultModel } = useAppStore()

  const NAV: { id: Section; label: string; icon: keyof Parameters<typeof Icon>[0]['name'] }[] = [
    { id: 'ollama',     label: 'Ollama',      icon: 'server'    },
    { id: 'database',   label: 'Database',    icon: 'database'  },
    { id: 'appearance', label: 'Appearance',  icon: 'eye'       },
  ]

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      <div className="h-[46px] border-b border-border-default flex items-center px-5 flex-shrink-0 bg-bg-surface">
        <span className="text-[13px] font-medium text-text-1">Settings</span>
      </div>
      <div className="flex flex-1 overflow-hidden">
        <div className="w-[154px] border-r border-border-default p-2 bg-bg-surface flex-shrink-0">
          {NAV.map((item) => (
            <button
              key={item.id}
              onClick={() => setSection(item.id)}
              className={clsx(
                'w-full flex items-center gap-2 px-2.5 py-1.5 rounded-[7px] text-xs mb-0.5 transition-colors',
                section === item.id ? 'bg-accent-bg text-accent-text' : 'text-text-2 hover:bg-bg-raised hover:text-text-1'
              )}
            >
              <Icon name={item.icon} size={14} />
              {item.label}
            </button>
          ))}
          <div className="border-t border-border-subtle mt-2 pt-2">
            <div className="px-2.5 py-1.5 rounded-[7px] text-xs text-text-3 opacity-50 flex items-center gap-2">
              <Icon name="note" size={14} /> Users
            </div>
            <p className="text-[9px] text-text-3 px-2.5 mt-0.5">Coming with auth</p>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {section === 'ollama' && (
            <div className="max-w-xl flex flex-col gap-3.5">
              <div className="bg-bg-surface border border-border-default rounded-[10px] p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Icon name="server" size={15} className="text-accent-text" />
                  <span className="text-[13px] font-medium text-text-1">Connection</span>
                </div>
                <p className="text-[11px] text-text-2 mb-3.5">Configured via .env — read-only from UI.</p>
                <div className="flex gap-2.5 mb-3">
                  <div className="flex-1">
                    <div className="text-[11px] font-medium text-text-2 mb-1">Generate URL</div>
                    <input readOnly defaultValue="http://85.208.254.177:11434/api/generate" className="w-full bg-bg-raised border border-border-default rounded-[7px] px-3 py-1.5 text-xs text-text-1 outline-none" />
                  </div>
                  <div className="w-20">
                    <div className="text-[11px] font-medium text-text-2 mb-1">Timeout</div>
                    <input readOnly defaultValue="120s" className="w-full bg-bg-raised border border-border-default rounded-[7px] px-3 py-1.5 text-xs text-text-1 outline-none" />
                  </div>
                </div>
                <Button variant="secondary" size="sm" onClick={() => refetch()} disabled={isFetching}>
                  <Icon name="refresh" size={13} />
                  {isFetching ? 'Testing…' : 'Test connection'}
                </Button>
                {health && (
                  <div className={clsx(
                    'flex items-center gap-1.5 text-[11px] mt-2 px-2.5 py-1.5 rounded-[7px] border',
                    health.online
                      ? 'bg-[var(--green-bg)] border-[var(--green-border)] text-[var(--green)]'
                      : 'bg-red-900/20 border-red-800/40 text-red-400'
                  )}>
                    <Icon name={health.online ? 'check' : 'x'} size={13} />
                    {health.online ? 'Connected' : 'Unreachable'}
                  </div>
                )}
              </div>

              {health?.online && health.models.length > 0 && (
                <div className="bg-bg-surface border border-border-default rounded-[10px] p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <Icon name="layers" size={15} className="text-accent-text" />
                    <span className="text-[13px] font-medium text-text-1">Available models</span>
                  </div>
                  <div className="flex flex-col gap-2">
                    {health.models.map((m) => (
                      <button
                        key={m.name}
                        onClick={() => setDefaultModel(m.name)}
                        className={clsx(
                          'flex items-center gap-2.5 px-3 py-2.5 rounded-[8px] border text-left transition-colors',
                          defaultModelName === m.name
                            ? 'border-accent bg-accent-bg'
                            : 'border-border-default hover:border-border-strong bg-bg-raised'
                        )}
                      >
                        <div
                          className="w-2 h-2 rounded-full flex-shrink-0"
                          style={{ background: defaultModelName === m.name ? 'var(--green)' : 'var(--text-3)' }}
                        />
                        <div>
                          <div className="text-xs font-medium text-text-1">{m.name}</div>
                          {m.size && <div className="text-[10px] text-text-3 mt-0.5">{m.size}</div>}
                        </div>
                        {defaultModelName === m.name && (
                          <span className="ml-auto text-[10px] text-accent-text">default</span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {section === 'database' && (
            <div className="max-w-xl">
              <div className="bg-bg-surface border border-border-default rounded-[10px] p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Icon name="database" size={15} className="text-accent-text" />
                  <span className="text-[13px] font-medium text-text-1">PostgreSQL</span>
                </div>
                <p className="text-[11px] text-text-2 mb-3">Configured via .env on the server.</p>
                <div className="text-[12px] text-text-3 bg-bg-raised border border-border-default rounded-[8px] px-3.5 py-3 font-mono">
                  DB_HOST · DB_PORT · DB_NAME · DB_USER · DB_PASSWORD
                </div>
              </div>
            </div>
          )}

          {section === 'appearance' && (
            <div className="max-w-xl">
              <div className="bg-bg-surface border border-border-default rounded-[10px] p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Icon name="eye" size={15} className="text-accent-text" />
                  <span className="text-[13px] font-medium text-text-1">Branding</span>
                </div>
                <p className="text-[11px] text-text-2 mb-3.5">Company logo shown in the sidebar.</p>
                <div className="border border-dashed border-border-strong rounded-[8px] p-4 text-center cursor-pointer hover:border-accent transition-colors">
                  <div className="w-11 h-11 rounded-[8px] bg-accent-bg border border-accent-border flex items-center justify-center text-[13px] font-medium text-accent-text mx-auto mb-2">
                    BI
                  </div>
                  <div className="text-[11px] text-text-3">Click to upload · PNG or SVG</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
