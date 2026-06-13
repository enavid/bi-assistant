import { useState } from 'react'
import { clsx } from 'clsx'
import { InlineLoader, Spinner } from '@/components/ui/Spinner'
import {
  useActivateOllamaConnection,
  useActivateQueryDatabase,
  useCreateOllamaConnection,
  useCreateQueryDatabase,
  useDeactivateOllamaConnections,
  useDeactivateQueryDatabases,
  useDeleteModelConfig,
  useDeleteOllamaConnection,
  useDeleteQueryDatabase,
  useModelConfigs,
  useModelInfo,
  useOllamaConnectionModels,
  useOllamaConnections,
  useQueryDatabases,
  useSaveModelConfig,
  useSystemDatabases,
  useTestConnection,
  useTestOllamaConnection,
  useUpdateOllamaConnection,
  useUpdateQueryDatabase,
} from '@/hooks'
import { useAppStore } from '@/store/appStore'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/Modal'
import { Icon } from '@/components/ui/Icon'
import type { OllamaConnection, QueryDatabase, TestConnectionResult } from '@/types'

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
  isEditing,
  onSave,
  onCancel,
  isSaving,
}: {
  initial?: DbFormState
  isEditing?: boolean
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

  const hasCredentials = form.host && form.port && form.db_name && form.username && (form.password || isEditing)
  const canTest = !!(form.host && form.port && form.db_name && form.username && form.password)
  const canSave = !!(hasCredentials && form.name)

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
          <span className="text-[11px] text-text-3 font-medium">
            Password{isEditing && <span className="ml-1 font-normal opacity-60">(leave blank to keep current)</span>}
          </span>
          <div className="relative">
            <input
              type={showPw ? 'text' : 'password'}
              className="w-full bg-bg-surface border border-border-default rounded-[7px] px-3 py-1.5 pr-8 text-xs text-text-1 outline-none focus:border-accent"
              placeholder={isEditing ? 'unchanged' : '••••••••'}
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
  const [confirming, setConfirming] = useState(false)

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
          onClick={() => setConfirming(true)}
          disabled={isDeleting}
        >
          <Icon name="trash" size={13} />
        </button>
      </div>

      <ConfirmDialog
        open={confirming}
        title="Delete database connection"
        message={`"${db.name}" will be permanently removed.`}
        confirmLabel="Delete"
        onConfirm={onDelete}
        onClose={() => setConfirming(false)}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Ollama section
// ---------------------------------------------------------------------------

interface OllamaFormState {
  name: string
  base_url: string
}

const EMPTY_OLLAMA_FORM: OllamaFormState = { name: '', base_url: '' }

function OllamaForm({
  initial,
  onSave,
  onCancel,
  isSaving,
}: {
  initial?: OllamaFormState
  onSave: (v: OllamaFormState) => void
  onCancel: () => void
  isSaving: boolean
}) {
  const [form, setForm] = useState<OllamaFormState>(initial ?? EMPTY_OLLAMA_FORM)
  const [testResult, setTestResult] = useState<{ success: boolean; error: string | null; models: string[] } | null>(null)
  const testMut = useTestOllamaConnection()

  function set(field: keyof OllamaFormState, value: string) {
    setForm((f) => ({ ...f, [field]: value }))
    setTestResult(null)
  }

  async function handleTest() {
    setTestResult(null)
    const res = await testMut.mutateAsync({ base_url: form.base_url })
    setTestResult(res)
  }

  const canTest = !!form.base_url
  const canSave = canTest && !!form.name

  return (
    <div className="flex flex-col gap-3 p-4 bg-bg-raised border border-border-default rounded-[10px]">
      <div className="flex flex-col gap-2.5">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-text-3 font-medium">Connection name</span>
          <input
            className="bg-bg-surface border border-border-default rounded-[7px] px-3 py-1.5 text-xs text-text-1 outline-none focus:border-accent"
            placeholder="e.g. Local Ollama"
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-text-3 font-medium">Base URL</span>
          <input
            className="bg-bg-surface border border-border-default rounded-[7px] px-3 py-1.5 text-xs text-text-1 outline-none focus:border-accent font-mono"
            placeholder="http://localhost:11434"
            value={form.base_url}
            onChange={(e) => set('base_url', e.target.value)}
          />
        </label>
      </div>

      {testResult && (
        <div className={clsx(
          'text-[11px] px-2.5 py-1.5 rounded-[7px] border',
          testResult.success
            ? 'bg-[var(--green-bg)] border-[var(--green-border)] text-[var(--green)]'
            : 'bg-red-900/20 border-red-800/40 text-red-400'
        )}>
          <div className="flex items-center gap-1.5 mb-1">
            <Icon name={testResult.success ? 'check' : 'x'} size={12} />
            {testResult.success ? `Connected · ${testResult.models.length} model(s)` : testResult.error}
          </div>
          {testResult.success && testResult.models.length > 0 && (
            <div className="font-mono text-[10px] text-text-2 pl-3.5">
              {testResult.models.slice(0, 5).join(', ')}
              {testResult.models.length > 5 && ` +${testResult.models.length - 5} more`}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <Button variant="secondary" size="sm" onClick={handleTest} disabled={!canTest || testMut.isPending}>
          <Icon name="zap" size={12} />
          {testMut.isPending ? 'Testing…' : 'Test connection'}
        </Button>
        <div className="flex-1" />
        <Button variant="secondary" size="sm" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" size="sm" onClick={() => onSave(form)} disabled={!canSave || isSaving}>
          {isSaving ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  )
}

function OllamaConnectionPanel({
  conn,
  configMap,
  defaultModelName,
  onSetDefault,
  onActivate,
  onDeactivate,
  onEdit,
  onDelete,
  isActivating,
  isDeactivating,
  isDeleting,
}: {
  conn: OllamaConnection
  configMap: Record<string, Record<string, unknown>>
  defaultModelName: string
  onSetDefault: (name: string) => void
  onActivate: () => void
  onDeactivate: () => void
  onEdit: () => void
  onDelete: () => void
  isActivating: boolean
  isDeactivating: boolean
  isDeleting: boolean
}) {
  const [open, setOpen] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const { data: modelsData, isLoading: modelsLoading, isError: modelsError } = useOllamaConnectionModels(conn.id, open)
  const models = modelsData?.models ?? []

  return (
    <div className={clsx(
      'rounded-[9px] border transition-colors overflow-hidden',
      conn.is_active ? 'border-[var(--green-border)]' : 'border-border-default'
    )}>
      {/* Header row */}
      <div className={clsx(
        'flex items-center gap-2 px-3 py-2.5',
        conn.is_active ? 'bg-[var(--green-bg)]' : 'bg-bg-surface'
      )}>
        <button
          className="p-0.5 text-text-3 hover:text-text-1 transition-colors flex-shrink-0"
          onClick={() => setOpen((v) => !v)}
          title={open ? 'Collapse' : 'Show models'}
        >
          <Icon name={open ? 'chevron-down' : 'chevron-right'} size={13} />
        </button>
        <div className={clsx('w-2 h-2 rounded-full flex-shrink-0', conn.is_active ? 'bg-[var(--green)]' : 'bg-text-3')} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-text-1 truncate">{conn.name}</span>
            {conn.is_active && (
              <span className="text-[10px] font-medium text-[var(--green)] bg-[var(--green-bg)] border border-[var(--green-border)] px-1.5 py-0.5 rounded-full">
                active
              </span>
            )}
          </div>
          <div className="text-[11px] text-text-3 font-mono mt-0.5 truncate">{conn.base_url}</div>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button className="p-1.5 rounded-[6px] text-text-3 hover:text-text-1 hover:bg-bg-raised transition-colors" title="Edit" onClick={onEdit}>
            <Icon name="edit" size={13} />
          </button>
          {conn.is_active ? (
            <button
              className="p-1.5 rounded-[6px] text-text-3 hover:text-text-1 hover:bg-bg-raised transition-colors disabled:opacity-40"
              title="Deactivate" onClick={onDeactivate} disabled={isDeactivating}
            >
              <Icon name="pause" size={13} />
            </button>
          ) : (
            <button
              className="p-1.5 rounded-[6px] text-text-3 hover:text-accent-text hover:bg-accent-bg transition-colors disabled:opacity-40"
              title="Activate" onClick={onActivate} disabled={isActivating}
            >
              <Icon name="play" size={13} />
            </button>
          )}
          <button
            className="p-1.5 rounded-[6px] text-text-3 hover:text-red-400 hover:bg-red-900/20 transition-colors disabled:opacity-40"
            title="Delete" onClick={() => setConfirming(true)} disabled={isDeleting}
          >
            <Icon name="trash" size={13} />
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={confirming}
        title="Delete Ollama connection"
        message={`"${conn.name}" will be permanently removed.`}
        confirmLabel="Delete"
        onConfirm={onDelete}
        onClose={() => setConfirming(false)}
      />

      {/* Expandable models list */}
      {open && (
        <div className="border-t border-border-default bg-bg-raised px-3 py-3">
          {modelsLoading && <InlineLoader label="Loading models…" />}
          {modelsError && (
            <div className="text-[11px] text-amber-400 py-1">Could not reach Ollama server.</div>
          )}
          {!modelsLoading && !modelsError && models.length === 0 && (
            <div className="text-[11px] text-text-3 py-1">No models found on this server.</div>
          )}
          {models.length > 0 && (
            <div className="flex flex-col gap-1.5">
              {models.map((m) => (
                <ModelAccordionItem
                  key={m.name}
                  connectionId={conn.id}
                  modelName={m.name}
                  modelSize={m.size}
                  savedConfigJson={configMap[m.name] ?? null}
                  isDefault={defaultModelName === m.name}
                  onSetDefault={() => onSetDefault(m.name)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ModelConfigEditor({
  modelName,
  defaults,
  savedConfigJson,
  isLoading,
  isError,
}: {
  modelName: string
  defaults: Record<string, unknown>
  savedConfigJson: Record<string, unknown> | null
  isLoading: boolean
  isError: boolean
}) {
  const saveMut = useSaveModelConfig()
  const deleteMut = useDeleteModelConfig()

  const hasOllamaParams = Object.keys(defaults).length > 0

  const [text, setText] = useState(() =>
    JSON.stringify({ ...defaults, ...savedConfigJson }, null, 2)
  )
  const [parseError, setParseError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  function handleChange(v: string) {
    setText(v)
    setSaved(false)
    try {
      JSON.parse(v)
      setParseError(null)
    } catch {
      setParseError('Invalid JSON')
    }
  }

  async function handleSave() {
    const parsed = JSON.parse(text)
    await saveMut.mutateAsync({ modelName, config_json: parsed })
    setSaved(true)
  }

  async function handleReset() {
    await deleteMut.mutateAsync(modelName)
    setText(JSON.stringify(defaults, null, 2))
    setParseError(null)
    setSaved(false)
  }

  const hasSaved = savedConfigJson !== null
  const canSave = !parseError && !saveMut.isPending

  return (
    <div className="mt-2 flex flex-col gap-2">
      {isLoading && <InlineLoader label="Loading Ollama defaults…" />}
      {!isLoading && isError && (
        <div className="text-[11px] text-amber-400 flex items-center gap-1.5">
          <Icon name="x" size={11} />
          Could not fetch Ollama defaults — add custom overrides below.
        </div>
      )}
      {!isLoading && !isError && !hasOllamaParams && (
        <div className="text-[11px] text-text-3">
          No parameters in Ollama Modelfile — add custom overrides below (e.g. temperature, top_p, num_ctx, think).
        </div>
      )}
      {!isLoading && (
        <>
          <textarea
            className={clsx(
              'w-full font-mono text-[11px] bg-bg-surface border rounded-[7px] px-3 py-2 text-text-1 outline-none resize-y min-h-[120px]',
              parseError ? 'border-red-600' : 'border-border-default focus:border-accent'
            )}
            value={text}
            onChange={(e) => handleChange(e.target.value)}
            spellCheck={false}
          />
          {parseError && <div className="text-[10px] text-red-400">{parseError}</div>}
          <div className="flex items-center gap-2">
            {hasSaved && (
              <Button variant="secondary" size="sm" onClick={handleReset} disabled={deleteMut.isPending}>
                Reset to defaults
              </Button>
            )}
            <div className="flex-1" />
            {saved && !saveMut.isPending && (
              <span className="text-[10px] text-[var(--green)] flex items-center gap-1">
                <Icon name="check" size={11} /> Saved
              </span>
            )}
            <Button variant="primary" size="sm" onClick={handleSave} disabled={!canSave}>
              {saveMut.isPending ? 'Saving…' : 'Save config'}
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

function ModelAccordionItem({
  connectionId,
  modelName,
  modelSize,
  savedConfigJson,
  isDefault,
  onSetDefault,
}: {
  connectionId: string
  modelName: string
  modelSize: string
  savedConfigJson: Record<string, unknown> | null
  isDefault: boolean
  onSetDefault: () => void
}) {
  const [open, setOpen] = useState(false)
  const { data: info, isLoading, isError } = useModelInfo(open ? modelName : null, connectionId)
  const defaults = info?.parameters ?? {}

  return (
    <div className={clsx(
      'border rounded-[9px] overflow-hidden transition-colors',
      open ? 'border-accent' : 'border-border-default'
    )}>
      <button
        className="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left hover:bg-bg-raised transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        <Icon name={open ? 'chevron-down' : 'chevron-right'} size={13} className="text-text-3 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <span className="text-xs font-medium text-text-1 font-mono">{modelName}</span>
          {modelSize && <span className="ml-2 text-[10px] text-text-3">{modelSize}</span>}
        </div>
        {savedConfigJson && (
          <span className="text-[10px] text-accent-text border border-accent rounded px-1.5 py-0.5 flex-shrink-0">
            configured
          </span>
        )}
        {isDefault ? (
          <span className="text-[10px] text-[var(--green)] border border-[var(--green-border)] rounded px-1.5 py-0.5 flex-shrink-0">
            default
          </span>
        ) : (
          <button
            className="text-[10px] px-2 py-0.5 rounded flex-shrink-0 text-text-2 hover:text-text-1 hover:bg-bg-raised border border-border-default transition-colors"
            onClick={(e) => { e.stopPropagation(); onSetDefault() }}
          >
            set default
          </button>
        )}
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 border-t border-border-default bg-bg-raised">
          <ModelConfigEditor
            key={JSON.stringify(defaults)}
            modelName={modelName}
            defaults={defaults}
            savedConfigJson={savedConfigJson}
            isLoading={isLoading}
            isError={isError}
          />
        </div>
      )}
    </div>
  )
}

function OllamaSection() {
  const { data: conns = [], isLoading: connsLoading } = useOllamaConnections()
  const { data: modelConfigs = [] } = useModelConfigs()
  const { defaultModelName, setDefaultModel } = useAppStore()

  const createMut = useCreateOllamaConnection()
  const updateMut = useUpdateOllamaConnection()
  const deleteMut = useDeleteOllamaConnection()
  const activateMut = useActivateOllamaConnection()
  const deactivateMut = useDeactivateOllamaConnections()

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)

  function handleSave(form: OllamaFormState) {
    if (editingId) {
      updateMut.mutate(
        { id: editingId, payload: { name: form.name, base_url: form.base_url } },
        { onSuccess: () => { setEditingId(null); setShowForm(false) } }
      )
    } else {
      createMut.mutate(form, { onSuccess: () => setShowForm(false) })
    }
  }

  function handleEdit(conn: OllamaConnection) {
    setEditingId(conn.id)
    setShowForm(true)
  }

  function handleCancel() {
    setShowForm(false)
    setEditingId(null)
  }

  const editingConn = editingId ? conns.find((c) => c.id === editingId) : undefined
  const editingInitial: OllamaFormState | undefined = editingConn
    ? { name: editingConn.name, base_url: editingConn.base_url }
    : undefined

  const configMap = Object.fromEntries(modelConfigs.map((c) => [c.model_name, c.config_json]))

  return (
    <div className="flex flex-col gap-3.5 max-w-xl">
      <div className="bg-bg-surface border border-border-default rounded-[10px] p-4">
        <div className="flex items-center gap-2 mb-1">
          <Icon name="server" size={15} className="text-accent-text" />
          <span className="text-[13px] font-medium text-text-1">Ollama connections</span>
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
          Define Ollama servers here. Activate one to use it for all queries. Expand a connection to view and configure its models.
        </p>

        {showForm && (
          <div className="mb-3">
            <OllamaForm
              key={editingId ?? 'new'}
              initial={editingInitial}
              onSave={handleSave}
              onCancel={handleCancel}
              isSaving={createMut.isPending || updateMut.isPending}
            />
          </div>
        )}

        {connsLoading ? (
          <div className="flex justify-center py-4"><Spinner size={20} /></div>
        ) : conns.length === 0 ? (
          <div className="text-[11px] text-text-3 py-6 text-center border border-dashed border-border-default rounded-[8px]">
            No connections yet. Click "Add connection" to get started.
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {conns.map((conn) => (
              <OllamaConnectionPanel
                key={conn.id}
                conn={conn}
                configMap={configMap}
                defaultModelName={defaultModelName}
                onSetDefault={setDefaultModel}
                onActivate={() => activateMut.mutate(conn.id)}
                onDeactivate={() => deactivateMut.mutate()}
                onEdit={() => handleEdit(conn)}
                onDelete={() => deleteMut.mutate(conn.id)}
                isActivating={activateMut.isPending && activateMut.variables === conn.id}
                isDeactivating={deactivateMut.isPending}
                isDeleting={deleteMut.isPending && deleteMut.variables === conn.id}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Database section
// ---------------------------------------------------------------------------

function SystemDbCard() {
  const { data: sys, isLoading, isError } = useSystemDatabases()
  const info = sys?.app_db

  return (
    <div className="text-[11px] bg-bg-raised border border-border-default rounded-[7px] px-3 py-2 font-mono text-text-2">
      {isLoading && <span className="text-text-3">loading…</span>}
      {isError && <span className="text-text-3">DB_HOST · DB_PORT · DB_NAME · DB_USER</span>}
      {info && (
        <span>
          <span className="text-text-1">{info.host}</span>:{info.port}/
          <span className="text-text-1">{info.db_name}</span> · {info.username}
        </span>
      )}
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
        <p className="text-[11px] text-text-2 mb-3.5">
          Read-only. To change these connections, update the corresponding variables in <code className="text-[10px] bg-bg-raised border border-border-default rounded px-1 py-0.5">.env</code> on the server and restart the service.
        </p>
        <SystemDbCard />
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
          Define query databases here. Activate one to use it for HR data queries.
        </p>

        {showForm && (
          <div className="mb-3">
            <DbForm
              key={editingId ?? 'new'}
              initial={editingInitial}
              isEditing={!!editingId}
              onSave={handleSave}
              onCancel={handleCancel}
              isSaving={createMut.isPending || updateMut.isPending}
            />
          </div>
        )}

        {isLoading ? (
          <div className="flex justify-center py-4"><Spinner size={20} /></div>
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

export function SettingsPage({ onOpenSidebar }: { onOpenSidebar?: () => void }) {
  const [section, setSection] = useState<Section>('ollama')

  const NAV: { id: Section; label: string; icon: Parameters<typeof Icon>[0]['name'] }[] = [
    { id: 'ollama',   label: 'Ollama',   icon: 'server'   },
    { id: 'database', label: 'Database', icon: 'database' },
  ]

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Header */}
      <div className="h-[46px] border-b border-border-default flex items-center px-3 sm:px-5 gap-2 flex-shrink-0 bg-bg-surface">
        <button
          onClick={onOpenSidebar}
          className="md:hidden w-8 h-8 flex items-center justify-center rounded-[8px] flex-shrink-0"
          style={{ color: 'var(--text-2)' }}
        >
          <Icon name="menu" size={16} />
        </button>
        <span className="text-[13px] font-medium text-text-1">Settings</span>
      </div>

      <div className="flex flex-col md:flex-row flex-1 overflow-hidden">
        {/* Nav — horizontal scrollable tabs on mobile, vertical panel on desktop */}
        <div className="flex md:flex-col md:w-[154px] border-b md:border-b-0 md:border-r border-border-default p-2 bg-bg-surface flex-shrink-0 overflow-x-auto gap-0.5 md:gap-0">
          {NAV.map((item) => (
            <button
              key={item.id}
              onClick={() => setSection(item.id)}
              className={clsx(
                'flex items-center gap-2 px-3 md:px-2.5 py-2 md:py-1.5 rounded-[7px] text-xs whitespace-nowrap md:w-full md:mb-0.5 transition-colors flex-shrink-0',
                section === item.id ? 'bg-accent-bg text-accent-text' : 'text-text-2 hover:bg-bg-raised hover:text-text-1'
              )}
            >
              <Icon name={item.icon} size={14} />
              {item.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-4 sm:p-6">
          {section === 'ollama' && <OllamaSection />}
          {section === 'database' && <DatabaseSection />}
        </div>
      </div>
    </div>
  )
}
