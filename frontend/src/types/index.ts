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
  prompt_template_name: string
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
  experiment_id?: string | null
}

export interface GenerateResponse {
  sql: string
  success: boolean
  error?: string | null
  message_fa?: string | null
  route?: string | null
  status?: string | null
  detected_intent?: string | null
  warnings?: string[]
  traces?: Record<string, unknown>[]
  source?: string | null
  template_id?: string | null
  executed?: boolean
  row_count?: number | null
  model_called?: string | null
}

export interface OllamaModel {
  name: string
  size: string
}

export interface OllamaHealth {
  online: boolean
  model_name: string 
  models: OllamaModel[]
  message: string
}

export interface SystemDbInfo {
  host: string
  port: number
  db_name: string
  username: string
}

export interface SystemDatabases {
  app_db: SystemDbInfo
}

export interface QueryDatabase {
  id: string
  name: string
  host: string
  port: number
  db_name: string
  username: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface TestConnectionResult {
  success: boolean
  error: string | null
  latency_ms: number | null
}

export interface OllamaConnection {
  id: string
  name: string
  base_url: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface OllamaTestResult {
  success: boolean
  error: string | null
  models: string[]
}

export interface ModelConfig {
  model_name: string
  config_json: Record<string, unknown>
  updated_at: string
}

export interface ModelInfo {
  parameters: Record<string, unknown>
  details: Record<string, unknown>
}

export type Theme = 'dark' | 'light' | 'amin-rai'
export type AppPage = 'chat' | 'builder' | 'settings' | 'eval'

// ---------------------------------------------------------------------------
// Eval types
// ---------------------------------------------------------------------------

export interface EvalQuestionSet {
  id: string
  name: string
  description: string
  is_default: boolean
  question_count: number
  created_at: string
}

export interface EvalQuestion {
  id: string
  set_id: string
  question_id: string
  question: string
  category: string | null
  expected_route: string | null
  expected_status: string | null
  expected_intent: string | null
  created_at: string
}

export interface EvalRun {
  id: string
  set_id: string
  status: 'pending' | 'running' | 'done' | 'failed'
  model_name: string | null
  total: number
  passed: number
  failed: number
  started_at: string | null
  finished_at: string | null
  created_at: string
  current_question_idx: number | null
  question_ids_ordered: string[] | null
  results?: EvalRunResult[]
}

export interface EvalRunResult {
  id: string
  run_id: string
  question_id: string
  question: string
  category: string | null
  actual_route: string | null
  actual_status: string | null
  actual_intent: string | null
  source: string | null
  model_called: string | null
  template_id: string | null
  sql_validator_status: string | null
  executed: boolean
  row_count: number | null
  visualization: string | null
  total_duration_ms: number
  passed: boolean
  trace_steps: Array<{
    step?: string
    status?: string
    duration_ms?: number
    decision_by?: string
  }> | null
  error: string | null
  warnings: unknown[] | null
  created_at: string
}
