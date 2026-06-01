import { useState } from 'react'
import { clsx } from 'clsx'
import { useProjects, useCreateProject, useUpdateProject, useDeleteProject, useCreateSection, useUpdateSection, useDeleteSection } from '@/hooks'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'
import { chatApi } from '@/services/api'
import { useAppStore } from '@/store/appStore'
import type { Project, Section } from '@/types'

type Tab = 'sections' | 'output' | 'notes' | 'experiments'

export function BuilderPage() {
  const { defaultModelName } = useAppStore()
  const { data: projects } = useProjects()
  const createProject = useCreateProject()
  const updateProject = useUpdateProject()
  const deleteProject = useDeleteProject()
  const createSection = useCreateSection()
  const updateSection = useUpdateSection()
  const deleteSection = useDeleteSection()

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('sections')
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null)
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [newProjectDesc, setNewProjectDesc] = useState('')
  const [newSectionName, setNewSectionName] = useState('')
  const [newSectionOpen, setNewSectionOpen] = useState(false)
  const [testQuestion, setTestQuestion] = useState('')
  const [testResult, setTestResult] = useState<string | null>(null)
  const [testLoading, setTestLoading] = useState(false)

  const selected = projects?.find((p) => p.id === selectedId) ?? projects?.[0] ?? null
  const activeSection = selected?.sections.find((s) => s.id === activeSectionId) ?? selected?.sections[0] ?? null

  async function handleCreateProject() {
    if (!newProjectName.trim()) return
    const p = await createProject.mutateAsync({ name: newProjectName.trim(), description: newProjectDesc.trim() })
    setSelectedId(p.id)
    setNewProjectOpen(false)
    setNewProjectName('')
    setNewProjectDesc('')
  }

  async function handleCreateSection() {
    if (!selected || !newSectionName.trim()) return
    const order = selected.sections.length
    await createSection.mutateAsync({ projectId: selected.id, section: { name: newSectionName.trim(), content: '', order } })
    setNewSectionName('')
    setNewSectionOpen(false)
  }

  async function handleSectionBlur(section: Section, content: string) {
    if (!selected || section.content === content) return
    await updateSection.mutateAsync({ projectId: selected.id, sectionId: section.id, payload: { content } })
  }

  async function handleOutputFormatBlur(value: string) {
    if (!selected || selected.output_format === value) return
    await updateProject.mutateAsync({ id: selected.id, payload: { output_format: value } })
  }

  async function handleNotesBlur(value: string) {
    if (!selected || selected.notes === value) return
    await updateProject.mutateAsync({ id: selected.id, payload: { notes: value } })
  }

  async function handleTest() {
    if (!selected || !testQuestion.trim()) return
    setTestLoading(true)
    setTestResult(null)
    const result = await chatApi.generate(testQuestion, selected.id, defaultModelName)
    setTestResult(result.success ? result.sql : `Error: ${result.error}`)
    setTestLoading(false)
  }

  const assembledPreview = buildPreview(selected)

  return (
    <>
      <div className="flex flex-col flex-1 overflow-hidden">
        <div className="h-[46px] border-b border-border-default flex items-center px-5 gap-3 flex-shrink-0 bg-bg-surface">
          <span className="text-[13px] font-medium text-text-1 flex-1">Prompt Builder</span>
          <Button variant="secondary" size="sm" onClick={() => setNewProjectOpen(true)}>
            <Icon name="plus" size={13} /> New project
          </Button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          {/* Project list */}
          <div className="w-[188px] border-r border-border-default flex flex-col bg-bg-surface flex-shrink-0">
            <div className="h-10 border-b border-border-subtle flex items-center px-3 flex-shrink-0">
              <span className="text-[10px] font-medium text-text-3 uppercase tracking-[0.6px]">Projects</span>
            </div>
            <div className="flex-1 overflow-y-auto p-2">
              {(projects ?? []).map((p) => (
                <div
                  key={p.id}
                  onClick={() => setSelectedId(p.id)}
                  className={clsx(
                    'group flex items-center gap-1.5 px-2.5 py-2 rounded-[7px] mb-1 cursor-pointer transition-colors',
                    selected?.id === p.id ? 'bg-accent-bg border border-accent-border' : 'hover:bg-bg-raised border border-transparent'
                  )}
                >
                  <span className={clsx('text-xs flex-1 truncate font-medium', selected?.id === p.id ? 'text-accent-text' : 'text-text-2')}>
                    {p.name}
                  </span>
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteProject.mutate(p.id) }}
                    className="opacity-0 group-hover:opacity-100 text-text-3 hover:text-red-400 transition-all"
                  >
                    <Icon name="trash" size={12} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Editor */}
          <div className="flex flex-col flex-1 overflow-hidden">
            {selected ? (
              <>
                <div className="flex border-b border-border-default bg-bg-surface flex-shrink-0 px-3">
                  {(['sections', 'output', 'notes', 'experiments'] as Tab[]).map((t) => (
                    <button
                      key={t}
                      onClick={() => setTab(t)}
                      className={clsx(
                        'px-3 py-2.5 text-xs capitalize transition-colors border-b-2 -mb-px',
                        tab === t ? 'text-accent-text border-accent' : 'text-text-2 border-transparent hover:text-text-1'
                      )}
                    >
                      {t === 'sections' ? 'Sections' : t === 'output' ? 'Output format' : t.charAt(0).toUpperCase() + t.slice(1)}
                    </button>
                  ))}
                </div>

                <div className="flex flex-1 overflow-hidden">
                  {tab === 'sections' && (
                    <>
                      {/* Section list */}
                      <div className="w-[160px] border-r border-border-default flex flex-col bg-bg-surface flex-shrink-0">
                        <div className="flex-1 overflow-y-auto p-2">
                          {selected.sections.map((s) => (
                            <div
                              key={s.id}
                              onClick={() => setActiveSectionId(s.id)}
                              className={clsx(
                                'group flex items-center gap-1 px-2.5 py-1.5 rounded-[7px] mb-1 cursor-pointer transition-colors',
                                activeSection?.id === s.id ? 'bg-accent-bg border border-accent-border' : 'hover:bg-bg-raised border border-transparent'
                              )}
                            >
                              <span className={clsx('text-xs flex-1 truncate', activeSection?.id === s.id ? 'text-accent-text' : 'text-text-2')}>
                                {s.name}
                              </span>
                              <button
                                onClick={(e) => { e.stopPropagation(); deleteSection.mutate({ projectId: selected.id, sectionId: s.id }) }}
                                className="opacity-0 group-hover:opacity-100 text-text-3 hover:text-red-400"
                              >
                                <Icon name="trash" size={11} />
                              </button>
                            </div>
                          ))}
                          <button
                            onClick={() => setNewSectionOpen(true)}
                            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-[7px] border border-dashed border-border-default text-text-3 text-[11px] hover:border-border-strong hover:text-text-2 transition-colors mt-1"
                          >
                            <Icon name="plus" size={12} /> Add section
                          </button>
                        </div>
                      </div>

                      {/* Section editor */}
                      <div className="flex-1 flex flex-col p-3 overflow-hidden">
                        {activeSection ? (
                          <>
                            <div className="flex items-center gap-2 mb-2 flex-shrink-0">
                              <span className="text-xs font-medium text-text-1">{activeSection.name}</span>
                              <span className="text-[10px] text-text-3 font-mono bg-bg-raised border border-border-default px-1.5 py-0.5 rounded">
                                {`{${activeSection.id}}`}
                              </span>
                            </div>
                            <textarea
                              key={activeSection.id}
                              defaultValue={activeSection.content}
                              onBlur={(e) => handleSectionBlur(activeSection, e.target.value)}
                              className="flex-1 w-full bg-bg-raised border border-border-default rounded-[8px] p-3 text-xs font-mono text-text-1 leading-[1.75] resize-none outline-none focus:border-accent transition-colors"
                              style={{ direction: 'ltr', textAlign: 'left' }}
                            />
                            <p className="text-[10px] text-text-3 mt-1.5 flex-shrink-0">Auto-saves on blur · Use this section in Output Format as <code className="font-mono">{`{${activeSection.id}}`}</code></p>
                          </>
                        ) : (
                          <div className="flex items-center justify-center h-full text-sm text-text-3">
                            Select or create a section
                          </div>
                        )}
                      </div>
                    </>
                  )}

                  {tab === 'output' && (
                    <div className="flex-1 flex flex-col p-4 overflow-hidden gap-3">
                      <div className="flex-shrink-0">
                        <p className="text-xs text-text-2 mb-1">
                          Define how sections are assembled. Reference sections by their ID:
                        </p>
                        <div className="flex flex-wrap gap-1.5 mb-3">
                          {selected.sections.map((s) => (
                            <span key={s.id} className="text-[10px] font-mono bg-bg-raised border border-border-default px-1.5 py-0.5 rounded text-accent-text">
                              {`{${s.id}}`} = {s.name}
                            </span>
                          ))}
                          <span className="text-[10px] font-mono bg-bg-raised border border-border-default px-1.5 py-0.5 rounded text-text-2">{'{question}'}</span>
                        </div>
                      </div>
                      <textarea
                        key={selected.id + '-output'}
                        defaultValue={selected.output_format}
                        onBlur={(e) => handleOutputFormatBlur(e.target.value)}
                        placeholder={`{section_id_1}\n\n{section_id_2}\n\nQUESTION:\n{question}\n\nSQL:`}
                        className="flex-1 w-full bg-bg-raised border border-border-default rounded-[8px] p-3 text-xs font-mono text-text-1 leading-[1.75] resize-none outline-none focus:border-accent transition-colors"
                        style={{ direction: 'ltr', textAlign: 'left' }}
                      />
                      <div className="flex-shrink-0 border-t border-border-subtle pt-3">
                        <p className="text-[11px] font-medium text-text-2 mb-2">Test prompt</p>
                        <div className="flex gap-2">
                          <input
                            value={testQuestion}
                            onChange={(e) => setTestQuestion(e.target.value)}
                            placeholder="Enter a sample question…"
                            className="flex-1 bg-bg-raised border border-border-default rounded-[7px] px-3 py-1.5 text-xs text-text-1 outline-none focus:border-accent"
                          />
                          <Button variant="primary" size="sm" onClick={handleTest} disabled={testLoading}>
                            <Icon name={testLoading ? 'refresh' : 'play'} size={13} />
                            {testLoading ? 'Testing…' : 'Test'}
                          </Button>
                        </div>
                        {testResult && (
                          <pre className="mt-2 text-[11px] font-mono text-text-2 bg-bg-raised border border-border-default rounded-[7px] p-2.5 overflow-x-auto whitespace-pre-wrap">
                            {testResult}
                          </pre>
                        )}
                      </div>
                    </div>
                  )}

                  {tab === 'notes' && (
                    <div className="flex-1 flex flex-col p-4 overflow-hidden">
                      <textarea
                        key={selected.id + '-notes'}
                        defaultValue={selected.notes}
                        onBlur={(e) => handleNotesBlur(e.target.value)}
                        placeholder="Write observations, results, and conclusions here…"
                        className="flex-1 w-full bg-bg-raised border border-border-default rounded-[8px] p-3 text-[13px] text-text-1 leading-[1.6] resize-none outline-none focus:border-accent transition-colors font-sans"
                      />
                      <p className="text-[10px] text-text-3 mt-1.5 flex-shrink-0">Auto-saves on blur</p>
                    </div>
                  )}

                  {tab === 'experiments' && (
                    <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2">
                      {selected.experiments.length === 0 && (
                        <p className="text-xs text-text-3">No experiments yet. Run queries from Chat to auto-log them here.</p>
                      )}
                      {selected.experiments.map((exp) => (
                        <div key={exp.id} className="bg-bg-raised border border-border-default rounded-[8px] p-3">
                          <div className="flex items-center gap-2 mb-1.5">
                            <span className="text-[11px] font-medium text-text-1">{exp.date.split('T')[0]}</span>
                            <span className={clsx('text-[10px] px-1.5 py-0.5 rounded', exp.correct ? 'bg-[var(--tag-opt-bg)] text-[var(--tag-opt-text)]' : 'bg-red-900/30 text-red-400')}>
                              {exp.correct ? 'correct' : 'wrong'}
                            </span>
                            <span className="text-[10px] text-text-3 ml-auto">{exp.elapsed_ms}ms</span>
                          </div>
                          <div className="text-[11px] text-text-2 mb-1" style={{ direction: 'rtl', textAlign: 'right' }}>{exp.question}</div>
                          {exp.comment && <div className="text-[10px] text-text-3">{exp.comment}</div>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex flex-1 items-center justify-center text-sm text-text-3">
                Create a project to get started
              </div>
            )}
          </div>

          {/* Preview */}
          <div className="w-[240px] border-l border-border-default flex flex-col bg-bg-surface flex-shrink-0">
            <div className="h-10 border-b border-border-subtle flex items-center px-3 flex-shrink-0">
              <span className="text-[10px] font-medium text-text-3 uppercase tracking-[0.6px]">Assembled prompt</span>
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              {assembledPreview ? (
                <pre className="text-[11px] font-mono text-text-3 leading-[1.6] whitespace-pre-wrap break-words">
                  {assembledPreview}
                </pre>
              ) : (
                <p className="text-[11px] text-text-3">Add sections to see the preview</p>
              )}
            </div>
          </div>
        </div>
      </div>

      <Modal open={newProjectOpen} title="New project" onClose={() => setNewProjectOpen(false)}>
        <div className="flex flex-col gap-3">
          <div>
            <label className="text-[11px] font-medium text-text-2 block mb-1.5">Name</label>
            <input
              autoFocus
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleCreateProject() }}
              placeholder="e.g. HR Analysis"
              className="w-full bg-bg-raised border border-border-default rounded-[7px] px-3 py-2 text-xs text-text-1 outline-none focus:border-accent"
            />
          </div>
          <div>
            <label className="text-[11px] font-medium text-text-2 block mb-1.5">Description (optional)</label>
            <input
              value={newProjectDesc}
              onChange={(e) => setNewProjectDesc(e.target.value)}
              placeholder="What is this project for?"
              className="w-full bg-bg-raised border border-border-default rounded-[7px] px-3 py-2 text-xs text-text-1 outline-none focus:border-accent"
            />
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="secondary" size="sm" onClick={() => setNewProjectOpen(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={handleCreateProject} disabled={!newProjectName.trim()}>Create</Button>
          </div>
        </div>
      </Modal>

      <Modal open={newSectionOpen} title="New section" onClose={() => setNewSectionOpen(false)}>
        <div className="flex flex-col gap-3">
          <div>
            <label className="text-[11px] font-medium text-text-2 block mb-1.5">Section name</label>
            <input
              autoFocus
              value={newSectionName}
              onChange={(e) => setNewSectionName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleCreateSection() }}
              placeholder="e.g. Rules, Schema, Examples"
              className="w-full bg-bg-raised border border-border-default rounded-[7px] px-3 py-2 text-xs text-text-1 outline-none focus:border-accent"
            />
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
  if (project.output_format) {
    let result = project.output_format
    for (const s of project.sections) {
      result = result.replace(`{${s.id}}`, s.content || `[${s.name}]`)
    }
    return result.replace('{question}', '[question]')
  }
  const parts = project.sections
    .slice()
    .sort((a, b) => a.order - b.order)
    .map((s) => s.content || `[${s.name}]`)
  return [...parts, 'QUESTION:\n[question]\n\nSQL:'].join('\n\n')
}
