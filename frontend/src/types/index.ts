export interface Section {
  id: string
  name: string
  content: string
  order: number
  created_at: string
}

export interface ExperimentEntry {
  id: string
  question: string
  sql_output: string
  correct: boolean
  elapsed_ms: number
  comment: string
  created_at: string
}

export interface Project {
  id: string
  name: string
  description: string
  notes: string
  output_format: string
  sections: Section[]
  experiments: ExperimentEntry[]
  created_at: string
  updated_at: string
}

export interface Message {
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
  messages: Message[]
  created_at: string
  updated_at: string
}

export interface QueryResult {
  columns: string[]
  rows: unknown[][]
  row_count: number
  elapsed_ms: number
  success: boolean
  error?: string | null
}

export interface GenerateResponse {
  sql: string
  success: boolean
  error?: string | null
}

export interface OllamaModel {
  name: string
  size: string
}

export interface OllamaHealth {
  online: boolean
  models: OllamaModel[]
  message: string
}

export type Theme = 'dark' | 'light'
export type AppPage = 'chat' | 'builder' | 'settings'
