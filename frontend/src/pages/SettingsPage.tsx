import { useState } from 'react'
import { clsx } from 'clsx'
import {
  useActivateQueryDatabase,
  useCreateQueryDatabase,
  useDeactivateQueryDatabases,
  useDeleteQueryDatabase,
  useOllamaHealth,
  useQueryDatabases,
  useTestConnection,
  useUpdateQueryDatabase,
} from '@/hooks'
import { useAppStore } from '@/store/appStore'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import type { QueryDatabase, TestConnectionResult } from '@/types'

type Section = 'ollama' | 'database'

interface DbFormState {
  name: string
  host: string
  port: string
  db_name: string
  username: string
  password: string
}

const EMPTY_FORM: DbFormState = { name: '', host: '', port: '5432', db_name: '', username: '', password: '' }

function DbForm({
  initial,
  onSave,
  onCancel,
  isSaving,
}: {
  initial?: DbFormState
  onSave: (v: DbFormState, testResult: TestConnectionResult | null) => void
  onCancel: () => void
  isSaving: boolean
}) {
  const [form, setForm] = useState<DbFormState>(initial ?? EMPTY_FORM)
  const [showPw, setShowPw] = useState(false)
  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null)
  const testMut = useTestConnection()

  function set(field: keyof DbFormState, value: string) {
    setForm((f) => ({ ...f, [field]: value }))
    setTestResult(null)
  }

  async function handleTest() {
    setTestResult(null)
    const res = await testMut.mutateAsync({
      host: form.host,
      port: Number(form.port),
      db_name: form.db_name,
      username: form.username,
      password: form.password,
    })
    setTestResult(res)
  }

  const canTest = form.host && form.port && form.db_name && form.username && form.password
  const canSave = canTest && form.name

  return (
    <div className="flex flex-col gap-3 p-4 bg-bg-raised border border-border-default rounded-[10px]">
      <div className="grid grid-cols-2 gap-2.5">
        <label className="flex flex-col gap-1 col-span-2">
          <span className="text-[11px] text-text-3 font-medium">Connection name</span>
          <input
            className="bg-bg-surface border border-border-default rounded-[7px] px-3 py-1.5 text-xs text-text-1 outline-none focus:border-accent"
            placeholder="e.g. HR Production"
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-text-3 font-medium">Host</span>
          <input
            className="bg-bg-surface border border-border-default rounded-[7px] px-3 py-1.5 text-xs text-text-1 outline-none focus:border-accent"
            placeholder="localhost"
            value={form.host}
            onChange={(e) => set('host', e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-text-3 font-medium">Port</span>
          <input
            type="number"
            className="bg-bg-surface border border-border-default rounded-[7px] px-3 py-1.5 text-xs text-text-1 outline-none focus:border-accent"
            placeholder="5432"
            value={form.port}
            onChange={(e) => set('port', e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-text-3 font-medium">Database</span>
          <input
            className="bg-bg-surface border border-border-default rounded-[7px] px-3 py-1.5 text-xs text-text-1 outline-none focus:border-accent"
            placeholder="hr_db"
            value={form.db_name}
            onChange={(e) => set('db_name', e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-text-3 font-medium">Username</span>
          <input
            className="bg-bg-surface border border-border-default rounded-[7px] px-3 py-1.5 text-xs text-text-1 outline-none focus:border-accent"
            placeholder="postgres"
            value={form.username}
            onChange={(e) => set('username', e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 col-span-2">
          <span className="text-[11px] text-text-3 font-medium">Password</span>
          <div className="relative">
            <input
              type={showPw ? 'text' : 'password'}
              className="w-full bg-bg-surface border border-border-default rounded-[7px] px-3 py-1.5 pr-8 text-xs text-text-1 outline-none focus:border-accent"
              placeholder="••••••••"
              value={form.password}
              onChange={(e) => set('password', e.target.value)}
            />
            <button
              type="button"
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-3 hover:text-text-1"
              onClick={() => setShowPw((v) => !v)}
            >
              <Icon name={showPw ? 'eye-off' : 'eye'} size={13} />
            </button>
          </div>
        </label>
      </div>

      {testResult && (
        <div className={clsx(
          'flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-[7px] border',
          testResult.success
            ? 'bg-[var(--green-bg)] border-[var(--green-border)] text-[var(--green)]'
            : 'bg-red-900/20 border-red-800/40 text-red-400'
        )}>
          <Icon name={testResult.success ? 'check' : 'x'} size={12} />
          {testResult.success
            ? `Connected${testResult.latency_ms != null ? ` · ${testResult.latency_ms}ms` : ''}`
            : testResult.error}
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <Button
          variant="secondary"
          size="sm"
          onClick={handleTest}
          disabled={!canTest || testMut.isPending}
        >
          <Icon name="zap" size={12} />
          {testMut.isPending ? 'Testing…' : 'Test connection'}
        </Button>
        <div className="flex-1" />
        <Button variant="secondary" size="sm" onClick={onCancel}>Cancel</Button>
        <Button
          variant="primary"
          size="sm"
          onClick={() => onSave(form, testResult)}
          disabled={!canSave || isSaving}
        >
          {isSaving ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  )
}

function DbCard({
  db,
  onActivate,
  onDeactivate,
  onEdit,
  onDelete,
  isActivating,
  isDeactivating,
  isDeleting,
}: {
  db: QueryDatabase
  onActivate: () => void
  onDeactivate: () => void
  onEdit: () => void
  onDelete: () => void
  isActivating: boolean
  isDeactivating: boolean
  isDeleting: boolean
}) {
  return (
    <div className={clsx(
      'flex items-center gap-3 px-3.5 py-3 rounded-[9px] border transition-colors',
      db.is_active
        ? 'border-[var(--green-border)] bg-[var(--green-bg)]'
        : 'border-border-default bg-bg-surface hover:border-border-strong'
    )}>
      <div className={clsx(
        'w-2 h-2 rounded-full flex-shrink-0',
        db.is_active ? 'bg-[var(--green)]' : 'bg-text-3'
      )} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-text-1 truncate">{db.name}</span>
          {db.is_active && (
            <span className="text-[10px] font-medium text-[var(--green)] bg-[var(--green-bg)] border border-[var(--green-border)] px-1.5 py-0.5 rounded-full">
              active
            </span>
          )}
        </div>
        <div className="text-[11px] text-text-3 font-mono mt-0.5 truncate">
          {db.host}:{db.port}/{db.db_name} · {db.username}
        </div>
      </div>
      <div className="flex items-center gap-1 flex-shrink-0">
        <button
          className="p-1.5 rounded-[6px] text-text-3 hover:text-text-1 hover:bg-bg-raised transition-colors"
          title="Edit"
          onClick={onEdit}
        >
          <Icon name="edit" size={13} />
        </button>
        {db.is_active ? (
          <button
            className="p-1.5 rounded-[6px] text-text-3 hover:text-text-1 hover:bg-bg-raised transition-colors disabled:opacity-40"
            title="Deactivate"
            onClick={onDeactivate}
            disabled={isDeactivating}
          >
            <Icon name="pause" size={13} />
          </button>
        ) : (
          <button
            className="p-1.5 rounded-[6px] text-text-3 hover:text-accent-text hover:bg-accent-bg transition-colors disabled:opacity-40"
            title="Activate"
            onClick={onActivate}
            disabled={isActivating}
          >
            <Icon name="play" size={13} />
          </button>
        )}
        <button
          className="p-1.5 rounded-[6px] text-text-3 hover:text-red-400 hover:bg-red-900/20 transition-colors disabled:opacity-40"
          title="Delete"
          onClick={onDelete}
          disabled={isDeleting}
        >
          <Icon name="trash" size={13} />
        </button>
      </div>
    </div>
  )
}

function DatabaseSection() {
  const { data: databases = [], isLoading } = useQueryDatabases()
  const createMut = useCreateQueryDatabase()
  const updateMut = useUpdateQueryDatabase()
  const deleteMut = useDeleteQueryDatabase()
  const activateMut = useActivateQueryDatabase()
  const deactivateMut = useDeactivateQueryDatabases()

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)

  function handleSave(form: DbFormState, _testResult: TestConnectionResult | null) {
    if (editingId) {
      updateMut.mutate(
        {
          id: editingId,
          payload: {
            name: form.name,
            host: form.host,
            port: Number(form.port),
            db_name: form.db_name,
            username: form.username,
            ...(form.password ? { password: form.password } : {}),
          },
        },
        {
          onSuccess: () => {
            setEditingId(null)
            setShowForm(false)
          },
        }
      )
    } else {
      createMut.mutate(
        {
          name: form.name,
          host: form.host,
          port: Number(form.port),
          db_name: form.db_name,
          username: form.username,
          password: form.password,
        },
        {
          onSuccess: () => setShowForm(false),
        }
      )
    }
  }

  function handleEdit(db: QueryDatabase) {
    setEditingId(db.id)
    setShowForm(true)
  }

  function handleCancel() {
    setShowForm(false)
    setEditingId(null)
  }

  const editingDb = editingId ? databases.find((d) => d.id === editingId) : undefined
  const editingInitial: DbFormState | undefined = editingDb
    ? {
        name: editingDb.name,
        host: editingDb.host,
        port: String(editingDb.port),
        db_name: editingDb.db_name,
        username: editingDb.username,
        password: '',
      }
    : undefined

  return (
    <div className="flex flex-col gap-3.5 max-w-xl">
      {/* System databases (read-only) */}
      <div className="bg-bg-surface border border-border-default rounded-[10px] p-4">
        <div className="flex items-center gap-2 mb-1">
          <Icon name="database" size={15} className="text-accent-text" />
          <span className="text-[13px] font-medium text-text-1">System databases</span>
        </div>
        <p className="text-[11px] text-text-2 mb-3">Configured via .env — read-only from UI.</p>
        <div className="flex flex-col gap-2">
          <div className="text-[11px] text-text-3 bg-bg-raised border border-border-default rounded-[8px] px-3.5 py-2.5 font-mono">
            DB_HOST · DB_PORT · DB_NAME · DB_USER · DB_PASSWORD
          </div>
          <div className="text-[11px] text-text-3 bg-bg-raised border border-border-default rounded-[8px] px-3.5 py-2.5 font-mono">
            HR_DB_HOST · HR_DB_PORT · HR_DB_NAME · HR_DB_USER · HR_DB_PASSWORD
          </div>
        </div>
      </div>

      {/* Query databases manager */}
      <div className="bg-bg-surface border border-border-default rounded-[10px] p-4">
        <div className="flex items-center gap-2 mb-1">
          <Icon name="layers" size={15} className="text-accent-text" />
          <span className="text-[13px] font-medium text-text-1">Query databases</span>
          {!showForm && (
            <button
              className="ml-auto flex items-center gap-1 text-[11px] text-accent-text hover:underline"
              onClick={() => { setEditingId(null); setShowForm(true) }}
            >
              <Icon name="plus" size={12} />
              Add connection
            </button>
          )}
        </div>
        <p className="text-[11px] text-text-2 mb-3">
          Define query databases here. Activate one to use it instead of HR_DB env settings.
        </p>

        {showForm && (
          <div className="mb-3">
            <DbForm
              key={editingId ?? 'new'}
              initial={editingInitial}
              onSave={handleSave}
              onCancel={handleCancel}
              isSaving={createMut.isPending || updateMut.isPending}
            />
          </div>
        )}

        {isLoading ? (
          <div className="text-[11px] text-text-3 py-4 text-center">Loading…</div>
        ) : databases.length === 0 ? (
          <div className="text-[11px] text-text-3 py-6 text-center border border-dashed border-border-default rounded-[8px]">
            No connections yet. Click "Add connection" to get started.
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {databases.map((db) => (
              <DbCard
                key={db.id}
                db={db}
                onActivate={() => activateMut.mutate(db.id)}
                onDeactivate={() => deactivateMut.mutate()}
                onEdit={() => handleEdit(db)}
                onDelete={() => deleteMut.mutate(db.id)}
                isActivating={activateMut.isPending && activateMut.variables === db.id}
                isDeactivating={deactivateMut.isPending}
                isDeleting={deleteMut.isPending && deleteMut.variables === db.id}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export function SettingsPage() {
  const [section, setSection] = useState<Section>('ollama')
  const { data: health, refetch, isFetching } = useOllamaHealth()
  const { defaultModelName, setDefaultModel } = useAppStore()

  const NAV: { id: Section; label: string; icon: Parameters<typeof Icon>[0]['name'] }[] = [
    { id: 'ollama',   label: 'Ollama',   icon: 'server'   },
    { id: 'database', label: 'Database', icon: 'database' },
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
                <Button variant="secondary" size="sm" onClick={() => refetch()} disabled={isFetching}>
                  <Icon name="refresh" size={13} />
                  {isFetching ? 'Testing…' : 'Test connection'}
                </Button>
                {health && (
                  <div className={clsx(
                    'flex items-center gap-1.5 text-[11px] mt-2 px-2.5 py-1.5 rounded-[7px] border',
                    health.online ? 'bg-[var(--green-bg)] border-[var(--green-border)] text-[var(--green)]' : 'bg-red-900/20 border-red-800/40 text-red-400'
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
                          defaultModelName === m.name ? 'border-accent bg-accent-bg' : 'border-border-default hover:border-border-strong bg-bg-raised'
                        )}
                      >
                        <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: defaultModelName === m.name ? 'var(--green)' : 'var(--text-3)' }} />
                        <div>
                          <div className="text-xs font-medium text-text-1">{m.name}</div>
                          {m.size && <div className="text-[10px] text-text-3 mt-0.5">{m.size}</div>}
                        </div>
                        {defaultModelName === m.name && <span className="ml-auto text-[10px] text-accent-text">default</span>}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {section === 'database' && <DatabaseSection />}
        </div>
      </div>
    </div>
  )
}
