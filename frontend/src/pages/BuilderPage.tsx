import { useState } from 'react'
import { clsx } from 'clsx'
import {
  useProjects, useCreateProject, useUpdateProject, useDeleteProject,
  useCreateSection, useUpdateSection, useDeleteSection,
} from '@/hooks'
import { chatApi } from '@/services/api'
import { useAppStore } from '@/store/appStore'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import type { Project, Section } from '@/types'

type Tab = 'sections' | 'output' | 'notes' | 'experiments'
type View = 'gallery' | 'detail'

const AVATAR_COLORS = [
  { bg: 'bg-blue-500/10 border-blue-500/20',    text: 'text-blue-400'   },
  { bg: 'bg-purple-500/10 border-purple-500/20', text: 'text-purple-400' },
  { bg: 'bg-teal-500/10 border-teal-500/20',    text: 'text-teal-400'   },
  { bg: 'bg-orange-500/10 border-orange-500/20', text: 'text-orange-400' },
  { bg: 'bg-pink-500/10 border-pink-500/20',    text: 'text-pink-400'   },
]

function getAvatarColor(id: string) {
  return AVATAR_COLORS[id.charCodeAt(0) % AVATAR_COLORS.length]
}

export function BuilderPage() {
  const { defaultModelName } = useAppStore()
  const { data: projects } = useProjects()
  const createProject = useCreateProject()
  const updateProject = useUpdateProject()
  const deleteProject = useDeleteProject()
  const createSection = useCreateSection()
  const updateSection = useUpdateSection()
  const deleteSection = useDeleteSection()

  const [view, setView] = useState<View>('gallery')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('sections')
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null)
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [newProjectDesc, setNewProjectDesc] = useState('')
  const [newSectionOpen, setNewSectionOpen] = useState(false)
  const [newSectionName, setNewSectionName] = useState('')
  const [testQuestion, setTestQuestion] = useState('')
  const [testResult, setTestResult] = useState<{ sql: string; route?: string; intent?: string } | null>(null)
  const [testLoading, setTestLoading] = useState(false)
  const [previewExpanded, setPreviewExpanded] = useState(false)

  // unsaved changes tracking
  const [sectionDraft, setSectionDraft] = useState<string | null>(null)
  const [outputDraft, setOutputDraft] = useState<string | null>(null)
  const [notesDraft, setNotesDraft] = useState<string | null>(null)

  const selected = projects?.find((p) => p.id === selectedId) ?? null
  const sortedSections = [...(selected?.sections ?? [])].sort((a, b) => a.order - b.order)
  const activeSection = sortedSections.find((s) => s.id === activeSectionId) ?? sortedSections[0] ?? null

  function openProject(id: string) {
    setSelectedId(id); setActiveSectionId(null); setTab('sections')
    setSectionDraft(null); setOutputDraft(null); setNotesDraft(null)
    setView('detail')
  }
  function backToGallery() { setView('gallery'); setSelectedId(null) }

  async function handleCreateProject() {
    if (!newProjectName.trim()) return
    const p = await createProject.mutateAsync({ name: newProjectName.trim(), description: newProjectDesc.trim() })
    setNewProjectOpen(false); setNewProjectName(''); setNewProjectDesc('')
    openProject(p.id)
  }

  async function handleCreateSection() {
    if (!selected || !newSectionName.trim()) return
    const updated = await createSection.mutateAsync({
      projectId: selected.id,
      section: { name: newSectionName.trim(), content: '', order: selected.sections.length },
    })
    const newSec = updated.sections[updated.sections.length - 1]
    if (newSec) setActiveSectionId(newSec.id)
    setNewSectionName(''); setNewSectionOpen(false)
    setSectionDraft(null)
  }

  async function handleSaveSection() {
    if (!selected || !activeSection || sectionDraft === null) return
    await updateSection.mutateAsync({
      projectId: selected.id,
      sectionId: activeSection.id,
      payload: { content: sectionDraft },
    })
    setSectionDraft(null)
  }

  async function handleSaveOutput() {
    if (!selected || outputDraft === null) return
    await updateProject.mutateAsync({ id: selected.id, payload: { output_format: outputDraft } })
    setOutputDraft(null)
  }

  async function handleSaveNotes() {
    if (!selected || notesDraft === null) return
    await updateProject.mutateAsync({ id: selected.id, payload: { notes: notesDraft } })
    setNotesDraft(null)
  }

  async function handleMoveSection(index: number, dir: -1 | 1) {
    if (!selected) return
    const sections = [...sortedSections]
    const target = index + dir
    if (target < 0 || target >= sections.length) return
    const a = sections[index]
    const b = sections[target]
    await Promise.all([
      updateSection.mutateAsync({ projectId: selected.id, sectionId: a.id, payload: { order: b.order } }),
      updateSection.mutateAsync({ projectId: selected.id, sectionId: b.id, payload: { order: a.order } }),
    ])
  }

  function insertIntoOutput(sectionId: string) {
    const placeholder = `{${sectionId}}`
    setOutputDraft((prev) => {
      const base = prev ?? selected?.output_format ?? ''
      return base + (base.endsWith('\n') || base === '' ? '' : '\n') + placeholder
    })
  }

  async function handleTest() {
    if (!selected || !testQuestion.trim()) return
    setTestLoading(true)
    setTestResult(null)
    try {
      const result = await chatApi.generate(testQuestion, selected.id, defaultModelName)
      setTestResult({
        sql: result.success ? result.sql : `-- ${result.error ?? 'No SQL generated'}`,
        route: result.route ?? undefined,
        intent: result.detected_intent ?? undefined,
      })
    } finally {
      setTestLoading(false)
    }
  }

  const preview = buildPreview(selected)

  // ── GALLERY ─────────────────────────────────────────────────────────────────
  if (view === 'gallery') {
    return (
      <>
        <div className="flex flex-col flex-1 overflow-hidden">
          <div className="h-[46px] border-b border-border-default flex items-center px-5 flex-shrink-0 bg-bg-surface">
            <span className="text-[13px] font-medium text-text-1 flex-1">Prompt Builder</span>
            <Button variant="secondary" size="sm" onClick={() => setNewProjectOpen(true)}>
              <Icon name="plus" size={13} /> New project
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto p-7">
            <div className="mb-6">
              <h1 className="text-xl font-medium text-text-1 mb-1">Projects</h1>
              <p className="text-sm text-text-2">Each project contains sections, output format, and experiments.</p>
            </div>
            <div className="grid gap-3.5" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))' }}>
              {(projects ?? []).map((p) => {
                const color = getAvatarColor(p.id)
                const updatedDate = new Date(p.updated_at).toLocaleDateString('en', { month: 'short', day: 'numeric' })
                return (
                  <div key={p.id} onClick={() => openProject(p.id)} className="group bg-bg-surface border border-border-default rounded-xl p-4 cursor-pointer hover:border-accent-border transition-all hover:-translate-y-0.5">
                    <div className={clsx('w-9 h-9 rounded-[9px] border flex items-center justify-center mb-3 text-sm font-semibold', color.bg, color.text)}>
                      {p.name.charAt(0).toUpperCase()}
                    </div>
                    <div className="text-sm font-medium text-text-1 mb-1 truncate">{p.name}</div>
                    <div className="text-xs text-text-2 mb-3 line-clamp-2 leading-relaxed min-h-[32px]">{p.description || 'No description'}</div>
                    <div className="flex items-center gap-1.5 text-[11px] text-text-3 border-t border-border-subtle pt-3">
                      <Icon name="list" size={12} />
                      <span>{p.sections.length} section{p.sections.length !== 1 ? 's' : ''}</span>
                      <span className="mx-1">·</span>
                      <Icon name="flask" size={12} />
                      <span>{p.experiments.length} exp</span>
                      <span className="mx-1">·</span>
                      <span>{updatedDate}</span>
                    </div>
                  </div>
                )
              })}
              <div onClick={() => setNewProjectOpen(true)} className="border border-dashed border-border-strong rounded-xl p-4 cursor-pointer flex flex-col items-center justify-center gap-2.5 min-h-[160px] hover:border-accent hover:bg-accent-bg transition-all">
                <Icon name="plus" size={24} className="text-text-3" />
                <span className="text-sm text-text-2">New project</span>
              </div>
            </div>
          </div>
        </div>
        <Modal open={newProjectOpen} title="New project" onClose={() => setNewProjectOpen(false)}>
          <div className="flex flex-col gap-3">
            <div>
              <label className="text-[11px] font-medium text-text-2 block mb-1.5">Name</label>
              <input autoFocus value={newProjectName} onChange={(e) => setNewProjectName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') handleCreateProject() }} placeholder="e.g. HR Analysis" className="w-full bg-bg-raised border border-border-default rounded-[7px] px-3 py-2 text-xs text-text-1 outline-none focus:border-accent" />
            </div>
            <div>
              <label className="text-[11px] font-medium text-text-2 block mb-1.5">Description (optional)</label>
              <input value={newProjectDesc} onChange={(e) => setNewProjectDesc(e.target.value)} placeholder="What is this project for?" className="w-full bg-bg-raised border border-border-default rounded-[7px] px-3 py-2 text-xs text-text-1 outline-none focus:border-accent" />
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="secondary" size="sm" onClick={() => setNewProjectOpen(false)}>Cancel</Button>
              <Button variant="primary" size="sm" onClick={handleCreateProject} disabled={!newProjectName.trim()}>Create</Button>
            </div>
          </div>
        </Modal>
      </>
    )
  }

  // ── DETAIL ───────────────────────────────────────────────────────────────────
  return (
    <>
      <div className="flex flex-col flex-1 overflow-hidden">
        <div className="h-[46px] border-b border-border-default flex items-center px-5 gap-3 flex-shrink-0 bg-bg-surface">
          <button onClick={backToGallery} className="flex items-center gap-1.5 text-xs text-text-2 hover:text-text-1 transition-colors">
            <Icon name="arrow-left" size={14} /> Projects
          </button>
          <div className="w-px h-4 bg-border-default" />
          <span className="text-[13px] font-medium text-text-1 flex-1 truncate">{selected?.name}</span>
          <Button variant="danger" size="sm" onClick={async () => { if (selected) { await deleteProject.mutateAsync(selected.id); backToGallery() } }}>
            <Icon name="trash" size={13} /> Delete
          </Button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          {/* Section list with ↑ ↓ buttons */}
          <div className="w-[160px] min-w-[160px] border-r-2 border-border-default flex flex-col bg-bg-raised">
            <div className="h-9 border-b border-border-subtle flex items-center px-3 flex-shrink-0">
              <span className="text-[10px] font-medium text-text-3 uppercase tracking-[.7px]">Sections</span>
            </div>
            <div className="flex-1 overflow-y-auto p-1.5">
              {sortedSections.map((s, i) => (
                <div
                  key={s.id}
                  onClick={() => { setActiveSectionId(s.id); setTab('sections'); setSectionDraft(null) }}
                  className={clsx(
                    'group flex items-center gap-1.5 px-2 py-1.5 rounded-[7px] mb-1 cursor-pointer border transition-all',
                    activeSection?.id === s.id && tab === 'sections'
                      ? 'bg-bg-surface border-border-strong'
                      : 'border-transparent hover:bg-bg-surface hover:border-border-subtle'
                  )}
                >
                  {/* ↑ ↓ buttons */}
                  <div className="flex flex-col gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                    <button
                      onClick={(e) => { e.stopPropagation(); handleMoveSection(i, -1) }}
                      disabled={i === 0}
                      className="w-4 h-4 flex items-center justify-center rounded text-text-3 hover:text-text-1 disabled:opacity-20"
                    >
                      <svg width="8" height="8" viewBox="0 0 8 8"><path d="M4 1L7 6H1L4 1Z" fill="currentColor"/></svg>
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleMoveSection(i, 1) }}
                      disabled={i === sortedSections.length - 1}
                      className="w-4 h-4 flex items-center justify-center rounded text-text-3 hover:text-text-1 disabled:opacity-20"
                    >
                      <svg width="8" height="8" viewBox="0 0 8 8"><path d="M4 7L1 2H7L4 7Z" fill="currentColor"/></svg>
                    </button>
                  </div>
                  <div className={clsx('w-1.5 h-1.5 rounded-full flex-shrink-0', activeSection?.id === s.id && tab === 'sections' ? 'bg-accent' : 'bg-border-strong')} />
                  <span className="text-xs text-text-1 flex-1 truncate">{s.name}</span>
                  <button onClick={(e) => { e.stopPropagation(); deleteSection.mutate({ projectId: selected!.id, sectionId: s.id }) }} className="opacity-0 group-hover:opacity-100 text-text-3 hover:text-red-400 transition-all">
                    <Icon name="trash" size={11} />
                  </button>
                </div>
              ))}
            </div>
            <div className="p-2 border-t border-border-subtle flex-shrink-0">
              <button onClick={() => setNewSectionOpen(true)} className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-[7px] border border-border-strong bg-bg-surface text-xs font-medium text-text-1 hover:border-accent transition-colors">
                <Icon name="plus" size={13} className="text-accent" /> Add section
              </button>
            </div>
          </div>

          {/* Editor */}
          <div className="flex flex-col flex-1 overflow-hidden">
            <div className="flex border-b-2 border-border-default flex-shrink-0 px-3 bg-bg-raised">
              {(['sections', 'output', 'notes', 'experiments'] as Tab[]).map((t, i) => {
                const icons: Parameters<typeof Icon>[0]['name'][] = ['list', 'code', 'notes', 'flask']
                const labels = ['Sections', 'Output format', 'Notes', 'Experiments']
                const hasUnsaved = (t === 'sections' && sectionDraft !== null) || (t === 'output' && outputDraft !== null) || (t === 'notes' && notesDraft !== null)
                return (
                  <button key={t} onClick={() => setTab(t)} className={clsx('flex items-center gap-1.5 px-3 py-2.5 text-xs transition-colors border-b-2 -mb-0.5 relative', tab === t ? 'text-text-1 border-accent font-medium' : 'text-text-3 border-transparent hover:text-text-2')}>
                    <Icon name={icons[i]} size={13} />{labels[i]}
                    {hasUnsaved && <span className="w-1.5 h-1.5 rounded-full bg-accent absolute top-2 right-1" />}
                  </button>
                )
              })}
            </div>

            {/* SECTIONS TAB */}
            {tab === 'sections' && (
              <div className="flex-1 flex flex-col p-3.5 overflow-hidden gap-2">
                {activeSection ? (
                  <>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className="text-xs font-medium text-text-1">{activeSection.name}</span>
                      {sectionDraft !== null && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent-bg text-accent-text border border-accent-border">unsaved</span>
                      )}
                      <div className="ml-auto flex items-center gap-1.5">
                        <span className="text-[11px] text-text-3">Reference as</span>
                        <button
                          onClick={() => navigator.clipboard.writeText(`{${activeSection.id}}`)}
                          className="text-[10px] px-1.5 py-0.5 rounded-[20px] bg-accent-bg text-accent-text border border-accent-border font-mono hover:opacity-80"
                          title="Click to copy"
                        >
                          {`{${activeSection.id.slice(0, 8)}…}`}
                        </button>
                      </div>
                    </div>
                    <textarea
                      key={activeSection.id}
                      defaultValue={activeSection.content}
                      onChange={(e) => setSectionDraft(e.target.value)}
                      spellCheck={false}
                      className="flex-1 w-full bg-bg-raised border border-border-default rounded-[8px] p-3 text-xs font-mono text-text-1 leading-[1.75] resize-none outline-none focus:border-accent transition-colors"
                      style={{ direction: 'ltr', textAlign: 'left' }}
                    />
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className="text-[11px] text-text-3">Changes are saved only when you click Save</span>
                      <Button
                        variant="primary"
                        size="sm"
                        className="ml-auto"
                        onClick={handleSaveSection}
                        disabled={sectionDraft === null}
                      >
                        <Icon name="check" size={13} /> Save
                      </Button>
                    </div>
                  </>
                ) : (
                  <div className="flex items-center justify-center h-full text-sm text-text-3">Select or add a section</div>
                )}
              </div>
            )}

            {/* OUTPUT FORMAT TAB */}
            {tab === 'output' && selected && (
              <div className="flex-1 flex flex-col overflow-hidden">
                <div className="flex-shrink-0 px-3.5 pt-3 pb-2">
                  <div className="text-[10px] font-medium text-text-3 uppercase tracking-[.6px] mb-2">
                    Section references — click name to insert, click ID to copy
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {sortedSections.map((s) => (
                      <div key={s.id} className="flex items-center border border-border-strong rounded-[6px] overflow-hidden text-[11px] font-mono">
                        <button
                          onClick={() => insertIntoOutput(s.id)}
                          className="px-2 py-0.5 bg-bg-raised text-text-1 hover:bg-accent-bg hover:text-accent-text transition-colors"
                          title="Click to insert into output format"
                        >
                          {s.name}
                        </button>
                        <button
                          onClick={() => navigator.clipboard.writeText(`{${s.id}}`)}
                          className="px-1.5 py-0.5 bg-bg-surface border-l border-border-default text-text-3 hover:text-text-2 transition-colors"
                          title="Click to copy ID"
                        >
                          ID
                        </button>
                      </div>
                    ))}
                    <button
                      onClick={() => setOutputDraft((prev) => (prev ?? selected.output_format ?? '') + '\n{question}')}
                      className="text-[11px] px-2 py-0.5 rounded-[6px] border border-border-strong bg-bg-raised text-text-2 font-mono hover:border-accent hover:text-accent-text transition-colors"
                    >
                      + {'{question}'}
                    </button>
                  </div>
                </div>

                <div className="flex-1 px-3.5 overflow-hidden flex flex-col gap-2">
                  <textarea
                    key={selected.id + '-out'}
                    value={outputDraft ?? selected.output_format}
                    onChange={(e) => setOutputDraft(e.target.value)}
                    spellCheck={false}
                    placeholder={'{section_id}\n\nQUESTION:\n{question}\n\nSQL:'}
                    className="flex-1 w-full bg-bg-raised border border-border-default rounded-[8px] p-3 text-xs font-mono text-text-1 leading-[1.75] resize-none outline-none focus:border-accent transition-colors"
                    style={{ direction: 'ltr', textAlign: 'left' }}
                  />
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {outputDraft !== null && (
                      <span className="text-[11px] text-text-3">Unsaved changes</span>
                    )}
                    <Button variant="primary" size="sm" className="ml-auto" onClick={handleSaveOutput} disabled={outputDraft === null}>
                      <Icon name="check" size={13} /> Save output format
                    </Button>
                  </div>
                </div>

                {/* Test prompt */}
                <div className="flex-shrink-0 border-t border-border-default p-3.5">
                  <div className="flex items-center gap-2 mb-2">
                    <Icon name="play" size={14} className="text-accent" />
                    <span className="text-[11px] font-medium text-text-1 uppercase tracking-[.5px]">Test prompt</span>
                  </div>
                  <div className="flex gap-2 mb-2">
                    <input
                      value={testQuestion}
                      onChange={(e) => setTestQuestion(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') handleTest() }}
                      placeholder="Enter a question and press Enter…"
                      className="flex-1 bg-bg-raised border border-border-default rounded-[7px] px-3 py-1.5 text-xs text-text-1 outline-none focus:border-accent"
                    />
                    <Button variant="primary" size="sm" onClick={handleTest} disabled={testLoading || !testQuestion.trim()}>
                      <Icon name={testLoading ? 'refresh' : 'play'} size={13} />
                      {testLoading ? 'Running…' : 'Test'}
                    </Button>
                  </div>
                  {testResult && (
                    <div className="rounded-[8px] overflow-hidden border border-border-default">
                      <div className="bg-bg-raised px-3 py-1.5 flex items-center gap-2 border-b border-border-subtle">
                        <span className="text-[10px] font-mono text-text-3">SQL</span>
                        {testResult.route && <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent-bg text-accent-text border border-accent-border font-mono">{testResult.route}</span>}
                        <button onClick={() => navigator.clipboard.writeText(testResult.sql)} className="ml-auto text-[11px] text-text-3 hover:text-text-1 flex items-center gap-1">
                          <Icon name="copy" size={12} /> Copy
                        </button>
                      </div>
                      <pre className="p-3 text-[11px] font-mono text-text-2 leading-[1.65] overflow-x-auto whitespace-pre-wrap bg-bg-raised">{testResult.sql}</pre>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* NOTES TAB */}
            {tab === 'notes' && selected && (
              <div className="flex-1 flex flex-col p-3.5 gap-2 overflow-hidden">
                <textarea
                  key={selected.id + '-notes'}
                  defaultValue={selected.notes}
                  onChange={(e) => setNotesDraft(e.target.value)}
                  placeholder="Write observations, results, and conclusions here…"
                  className="flex-1 w-full bg-bg-raised border border-border-default rounded-[8px] p-3 text-[13px] text-text-1 leading-[1.6] resize-none outline-none focus:border-accent font-sans"
                />
                <div className="flex items-center gap-2 flex-shrink-0">
                  {notesDraft !== null && <span className="text-[11px] text-text-3">Unsaved changes</span>}
                  <Button variant="primary" size="sm" className="ml-auto" onClick={handleSaveNotes} disabled={notesDraft === null}>
                    <Icon name="check" size={13} /> Save notes
                  </Button>
                </div>
              </div>
            )}

            {/* EXPERIMENTS TAB */}
            {tab === 'experiments' && selected && (
              <div className="flex-1 overflow-y-auto p-3.5 flex flex-col gap-2">
                {selected.experiments.length === 0 && (
                  <p className="text-xs text-text-3">No experiments yet. Run queries from Chat to auto-log them here.</p>
                )}
                {selected.experiments.map((exp) => (
                  <div key={exp.id} className="bg-bg-raised border border-border-default rounded-[8px] p-3">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-[11px] font-medium text-text-1">{exp.created_at.split('T')[0]}</span>
                      <span className={clsx('text-[10px] px-1.5 py-0.5 rounded-[20px]', exp.correct ? 'bg-[var(--green-bg)] text-[var(--green)] border border-[var(--green-border)]' : 'bg-red-900/20 text-red-400 border border-red-800/30')}>
                        {exp.correct ? 'correct' : 'wrong'}
                      </span>
                      {exp.elapsed_ms > 0 && <span className="text-[10px] text-text-3 ml-auto">{exp.elapsed_ms}ms</span>}
                    </div>
                    <div className="text-[11px] text-text-2 mb-1.5" style={{ direction: 'rtl', textAlign: 'right' }}>{exp.question}</div>
                    {exp.sql_output && (
                      <pre className="text-[11px] font-mono text-text-3 bg-bg-surface border border-border-subtle rounded-[6px] p-2 overflow-x-auto whitespace-pre-wrap">{exp.sql_output}</pre>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Preview panel with expand button */}
          <div className={clsx('border-l-2 border-border-default flex flex-col bg-bg-raised transition-all', previewExpanded ? 'w-[420px] min-w-[420px]' : 'w-[210px] min-w-[210px]')}>
            <div className="h-9 border-b border-border-subtle flex items-center px-3 flex-shrink-0 gap-2">
              <span className="text-[10px] font-medium text-text-3 uppercase tracking-[.7px] flex-1">Assembled prompt</span>
              <button
                onClick={() => setPreviewExpanded((v) => !v)}
                className="text-text-3 hover:text-text-1 transition-colors"
                title={previewExpanded ? 'Collapse' : 'Expand'}
              >
                <Icon name={previewExpanded ? 'arrow-right' : 'arrow-left'} size={13} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              {preview ? (
                <pre className="text-[12.5px] font-mono text-text-2 leading-[1.7] whitespace-pre-wrap break-words">{preview}</pre>
              ) : (
                <p className="text-[12px] text-text-3">Add sections to see preview</p>
              )}
            </div>
          </div>
        </div>
      </div>

      <Modal open={newSectionOpen} title="New section" onClose={() => setNewSectionOpen(false)}>
        <div className="flex flex-col gap-3">
          <div>
            <label className="text-[11px] font-medium text-text-2 block mb-1.5">Section name</label>
            <input autoFocus value={newSectionName} onChange={(e) => setNewSectionName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') handleCreateSection() }} placeholder="e.g. Rules, Schema, Examples" className="w-full bg-bg-raised border border-border-default rounded-[7px] px-3 py-2 text-xs text-text-1 outline-none focus:border-accent" />
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" size="sm" onClick={() => setNewSectionOpen(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={handleCreateSection} disabled={!newSectionName.trim()}>Add</Button>
          </div>
        </div>
      </Modal>
    </>
  )
}

function buildPreview(project: Project | null): string {
  if (!project) return ''
  const sorted = [...project.sections].sort((a, b) => a.order - b.order)
  if (project.output_format) {
    let result = project.output_format
    for (const s of sorted) result = result.replace(`{${s.id}}`, s.content || `[${s.name}]`)
    return result.replace('{question}', '[question]')
  }
  const parts = sorted.map((s) => s.content || `[${s.name}]`)
  return [...parts, 'QUESTION:\n[question]\n\nSQL:'].join('\n\n')
}
