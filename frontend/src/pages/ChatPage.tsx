import { useState, useRef, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { chatApi } from '@/services/api'
import { useAppStore } from '@/store/appStore'
import { useProjects, useSessions} from '@/hooks'
import { Icon } from '@/components/ui/Icon'
import { Button } from '@/components/ui/Button'
import type { ChatMessage, QueryResult } from '@/types'

export function ChatPage() {
  const { activeSessionId } = useAppStore()
  const { data: sessions } = useSessions()
  const { data: projects } = useProjects()
  const qc = useQueryClient()

  const session = sessions?.find((s) => s.id === activeSessionId)
  const project = projects?.find((p) => p.id === session?.project_id)

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [queryResults, setQueryResults] = useState<Record<string, QueryResult>>({})
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const bodyRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (session?.messages) setMessages(session.messages)
    else setMessages([])
  }, [session?.id])

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  async function handleSend() {
    const q = question.trim()
    if (!q || loading || !session) return
    setQuestion('')

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: q,
      created_at: new Date().toISOString(),
    }
    const nextMessages = [...messages, userMsg]
    setMessages(nextMessages)
    setLoading(true)

    const result = await chatApi.generate(q, session.project_id, session.model_name)
    setLoading(false)

    const aiMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      sql: result.success ? result.sql : null,
      error: result.error ?? null,
      created_at: new Date().toISOString(),
    }
    const finalMessages = [...nextMessages, aiMsg]
    setMessages(finalMessages)

    const updatedSession = {
      ...session,
      messages: finalMessages,
      title: nextMessages.find((m) => m.role === 'user')?.content.slice(0, 60) ?? session.title,
    }
    await chatApi.updateSession(session.id, updatedSession)
    qc.invalidateQueries({ queryKey: ['sessions'] })
  }

  async function handleRunQuery(msg: ChatMessage) {
    if (!msg.sql || !session) return
    const result = await chatApi.runQuery(msg.sql, {
      session_id: session.id,
      question: messages.find((m) => m.role === 'user' && new Date(m.created_at) < new Date(msg.created_at))?.content,
      project_id: session.project_id,
    })
    setQueryResults((prev) => ({ ...prev, [msg.id]: result }))
  }

  if (!session) {
    return (
      <div className="flex flex-col flex-1 items-center justify-center gap-3">
        <Icon name="message" size={32} className="text-text-3" />
        <p className="text-sm text-text-2">Select a chat or create a new one</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      <div className="h-[46px] border-b border-border-default flex items-center px-5 gap-3 flex-shrink-0 bg-bg-surface">
        <span className="text-[13px] font-medium text-text-1 flex-1 truncate">{session.title}</span>
        {project && (
          <span className="text-[11px] px-2.5 py-1 rounded-full bg-accent-bg text-accent-text border border-accent-border whitespace-nowrap">
            {project.name}
          </span>
        )}
        <span className="text-[11px] text-text-3 hidden sm:block">{session.model_name}</span>
      </div>

      <div ref={bodyRef} className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-3.5">
        {messages.map((msg) => (
          <div key={msg.id}>
            {msg.role === 'user' ? (
              <div className="flex flex-row-reverse gap-2.5 items-start">
                <div className="w-[27px] h-[27px] rounded-[7px] flex items-center justify-center bg-[var(--tag-opt-bg)] border border-[var(--green-border)] text-[10px] font-medium text-[var(--tag-opt-text)] flex-shrink-0">
                  U
                </div>
                <div className="max-w-[62%] bg-accent-bg border border-accent-border rounded-[10px_10px_2px_10px] px-3.5 py-2.5 text-[13px] text-accent-text" style={{ direction: 'rtl', textAlign: 'right' }}>
                  {msg.content}
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                <div className="flex gap-2.5 items-start">
                  <div className="w-[27px] h-[27px] rounded-[7px] flex items-center justify-center bg-accent-bg border border-accent-border text-[10px] font-medium text-accent-text flex-shrink-0">
                    AI
                  </div>
                  {msg.error ? (
                    <div className="text-[13px] text-red-400 pt-1">{msg.error}</div>
                  ) : (
                    <div className="flex-1 max-w-[88%] bg-bg-surface border border-border-default rounded-[10px] overflow-hidden">
                      <div className="bg-bg-raised px-3 py-1.5 flex items-center justify-between border-b border-border-subtle">
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent-bg text-accent-text border border-accent-border font-mono">PostgreSQL</span>
                        <Button variant="ghost" size="sm" onClick={() => navigator.clipboard.writeText(msg.sql ?? '')}>
                          <Icon name="copy" size={13} /> Copy
                        </Button>
                      </div>
                      <pre className="px-3.5 py-3 text-xs font-mono leading-[1.75] text-text-2 overflow-x-auto whitespace-pre-wrap">
                        {msg.sql}
                      </pre>
                      {!queryResults[msg.id] && !dismissed.has(msg.id) && (
                        <div className="px-3 py-2 border-t border-border-subtle bg-bg-raised flex gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleRunQuery(msg)}
                            className="border border-success text-success hover:bg-success-bg"
                          >
                            <Icon name="play" size={12} /> Run on DB
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setDismissed((p) => new Set([...p, msg.id]))}>
                            Dismiss
                          </Button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
                {queryResults[msg.id] && (
                  <div className="ml-9 max-w-[88%] bg-bg-surface border border-border-default rounded-[10px] overflow-hidden">
                    <div className="bg-bg-raised px-3 py-1.5 border-b border-border-subtle flex items-center gap-2">
                      {queryResults[msg.id].success ? (
                        <>
                          <Icon name="check" size={13} className="text-success" />
                          <span className="text-[11px] text-success">{queryResults[msg.id].row_count} row{queryResults[msg.id].row_count !== 1 ? 's' : ''}</span>
                          <span className="text-[11px] text-text-3">· {queryResults[msg.id].elapsed_ms} ms</span>
                        </>
                      ) : (
                        <>
                          <Icon name="x" size={13} className="text-red-400" />
                          <span className="text-[11px] text-red-400">Error</span>
                        </>
                      )}
                    </div>
                    {queryResults[msg.id].success ? (
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs border-collapse">
                          <thead>
                            <tr>
                              {queryResults[msg.id].columns.map((col) => (
                                <th key={col} className="px-3 py-1.5 text-left text-[10px] uppercase tracking-[0.5px] text-text-3 border-b border-border-subtle font-medium whitespace-nowrap">
                                  {col}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {queryResults[msg.id].rows.map((row, ri) => (
                              <tr key={ri} className="hover:bg-bg-raised">
                                {row.map((cell, ci) => (
                                  <td key={ci} className="px-3 py-1.5 text-text-1 border-b border-border-subtle last:border-b-0">{String(cell ?? '')}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="px-3 py-2 text-xs text-red-400">{queryResults[msg.id].error}</div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="flex gap-2.5 items-center">
            <div className="w-[27px] h-[27px] rounded-[7px] bg-accent-bg border border-accent-border flex items-center justify-center text-[10px] text-accent-text">AI</div>
            <div className="flex gap-1">
              {[0, 1, 2].map((i) => (
                <div key={i} className="w-1.5 h-1.5 rounded-full bg-accent-text animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="px-5 pb-3.5 pt-3 border-t border-border-default bg-bg-surface flex-shrink-0">
        <div className="flex gap-2 items-end bg-bg-raised border border-border-default rounded-[10px] px-4 py-2 focus-within:border-accent transition-colors">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
            placeholder="Ask a question about HR data…"
            rows={1}
            className="flex-1 bg-transparent border-none outline-none text-[13px] text-text-1 resize-none font-sans leading-[1.5] placeholder:text-text-3"
            style={{ direction: 'rtl', textAlign: 'right' }}
          />
          <button
            onClick={handleSend}
            disabled={loading || !question.trim()}
            className="w-8 h-8 rounded-[7px] bg-accent flex items-center justify-center flex-shrink-0 disabled:opacity-40 hover:opacity-90 transition-opacity text-white"
          >
            <Icon name="send" size={15} />
          </button>
        </div>
        <div className="text-[10px] text-text-3 text-center mt-1.5">Enter to send · Shift+Enter for new line</div>
      </div>
    </div>
  )
}
