// ---------------------------------------------------------------------------
// Workspace / Project
// ---------------------------------------------------------------------------

export interface Section {
  id: string
  name: string
  content: string
  order: number
}

export interface ExperimentEntry {
  id: string
  date: string
  question: string
  sql_output: string
  correct: boolean
  elapsed_ms: number
  comment: string
}

export interface Project {
  id: string
  name: string
  description: string
  notes: string
  sections: Section[]
  output_format: string
  experiments: ExperimentEntry[]
  created_at: string
  updated_at: string
}

export interface Workspace {
  id: string
  name: string
  projects: Project[]
  created_at: string
}

export interface PromptTemplate {
  id: string
  name: string
  content: string
  active: boolean
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

export interface QueryResult {
  columns: string[]
  rows: unknown[][]
  row_count: number
  elapsed_ms: number
  success: boolean
  error?: string | null
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sql?: string | null
  error?: string | null
  query_result?: QueryResult | null
  created_at: string
}

export interface ChatSession {
  id: string
  title: string
  project_id: string | null
  model_name: string
  messages: ChatMessage[]
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// Ollama
// ---------------------------------------------------------------------------

export interface OllamaModel {
  name: string
  size: string
}

export interface OllamaHealth {
  online: boolean
  models: OllamaModel[]
  message: string
}

// ---------------------------------------------------------------------------
// API responses
// ---------------------------------------------------------------------------

export interface GenerateResponse {
  sql: string
  success: boolean
  error?: string | null
}

// ---------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------

export type Theme = 'dark' | 'light'
export type AppPage = 'chat' | 'builder' | 'settings'
