import apiClient from './apiClient'
import type {
  ChatSession,
  EvalQuestion,
  EvalQuestionSet,
  EvalRun,
  GenerateResponse,
  OllamaHealth,
  Project,
  QueryDatabase,
  QueryResult,
  Section,
  SystemDatabases,
  TestConnectionResult,
} from '@/types'


export const projectApi = {
  list: () =>
    apiClient.get<Project[]>('/projects').then((r) => r.data),

  get: (id: string) =>
    apiClient.get<Project>(`/projects/${id}`).then((r) => r.data),

  create: (name: string, description = '') =>
    apiClient.post<Project>('/projects', { name, description }).then((r) => r.data),

  update: (id: string, payload: Partial<Pick<Project, 'name' | 'description' | 'notes' | 'output_format'>>) =>
    apiClient.patch<Project>(`/projects/${id}`, payload).then((r) => r.data),

  delete: (id: string) =>
    apiClient.delete(`/projects/${id}`).then((r) => r.data),

  createSection: (projectId: string, section: Partial<Section>) =>
    apiClient.post<Project>(`/projects/${projectId}/sections`, section).then((r) => r.data),

  updateSection: (projectId: string, sectionId: string, payload: Partial<Section>) =>
    apiClient.patch<Project>(`/projects/${projectId}/sections/${sectionId}`, payload).then((r) => r.data),

  deleteSection: (projectId: string, sectionId: string) =>
    apiClient.delete<Project>(`/projects/${projectId}/sections/${sectionId}`).then((r) => r.data),

  addExperiment: (projectId: string, payload: { question: string; sql_output: string; correct: boolean; elapsed_ms: number; comment?: string }) =>
    apiClient.post<Project>(`/projects/${projectId}/experiments`, payload).then((r) => r.data),

  setExperimentFeedback: (experimentId: string, correct: boolean) =>
    apiClient.patch(`/experiments/${experimentId}/feedback`, { correct }).then((r) => r.data),
}

export const chatApi = {
  listSessions: () =>
    apiClient.get<ChatSession[]>('/chat/sessions').then((r) => r.data),

  getSession: (id: string) =>
    apiClient.get<ChatSession>(`/chat/sessions/${id}`).then((r) => r.data),

  createSession: (payload: { title?: string; project_id?: string | null; model_name: string; template_name?: string })  =>
    apiClient.post<ChatSession>('/chat/sessions', payload).then((r) => r.data),

  updateSession: (id: string, payload: { title?: string; project_id?: string | null; model_name?: string }) =>
    apiClient.patch<ChatSession>(`/chat/sessions/${id}`, payload).then((r) => r.data),

  deleteSession: (id: string) =>
    apiClient.delete(`/chat/sessions/${id}`).then((r) => r.data),

  addMessage: (sessionId: string, payload: { role: string; content: string; sql?: string | null; error?: string | null; query_result?: unknown }) =>
    apiClient.post<ChatSession>(`/chat/sessions/${sessionId}/messages`, payload).then((r) => r.data),

  generate: (question: string, projectId?: string | null, modelName?: string) =>
    apiClient.post<GenerateResponse>('/chat/generate', {
      question,
      project_id: projectId,
      model_name: modelName,
    }).then((r) => r.data),

  runQuery: (sql: string, opts?: { session_id?: string; question?: string; project_id?: string | null }) =>
    apiClient.post<QueryResult>('/chat/query', { sql, ...opts }).then((r) => r.data),
}

export const ollamaApi = {
  health: () =>
    apiClient.get<OllamaHealth>('/ollama/health').then((r) => r.data),
}

export const connectionApi = {
  systemDatabases: () =>
    apiClient.get<SystemDatabases>('/connections/system-databases').then((r) => r.data),

  list: () =>
    apiClient.get<QueryDatabase[]>('/connections/databases').then((r) => r.data),

  create: (payload: { name: string; host: string; port: number; db_name: string; username: string; password: string }) =>
    apiClient.post<QueryDatabase>('/connections/databases', payload).then((r) => r.data),

  update: (id: string, payload: Partial<{ name: string; host: string; port: number; db_name: string; username: string; password: string }>) =>
    apiClient.patch<QueryDatabase>(`/connections/databases/${id}`, payload).then((r) => r.data),

  delete: (id: string) =>
    apiClient.delete(`/connections/databases/${id}`).then((r) => r.data),

  activate: (id: string) =>
    apiClient.post<QueryDatabase>(`/connections/databases/${id}/activate`).then((r) => r.data),

  deactivate: () =>
    apiClient.post('/connections/databases/deactivate').then((r) => r.data),

  test: (payload: { host: string; port: number; db_name: string; username: string; password: string }) =>
    apiClient.post<TestConnectionResult>('/connections/databases/test', payload).then((r) => r.data),
}

export const evalApi = {
  listSets: () =>
    apiClient.get<EvalQuestionSet[]>('/eval/question-sets').then((r) => r.data),

  createSet: (name: string, description = '') =>
    apiClient.post<EvalQuestionSet>('/eval/question-sets', { name, description }).then((r) => r.data),

  deleteSet: (id: string) =>
    apiClient.delete(`/eval/question-sets/${id}`).then((r) => r.data),

  listQuestions: (setId: string) =>
    apiClient.get<EvalQuestion[]>(`/eval/question-sets/${setId}/questions`).then((r) => r.data),

  importQuestions: (setId: string, questions: Omit<EvalQuestion, 'id' | 'set_id' | 'created_at'>[]) =>
    apiClient.post(`/eval/question-sets/${setId}/questions`, questions).then((r) => r.data),

  listRuns: (setId: string) =>
    apiClient.get<EvalRun[]>(`/eval/question-sets/${setId}/runs`).then((r) => r.data),

  seedDefaults: () =>
    apiClient.post<EvalQuestionSet>('/eval/seed-defaults').then((r) => r.data),

  triggerRun: (setId: string, opts?: { category?: string; model_name?: string }) =>
    apiClient.post<EvalRun>(`/eval/question-sets/${setId}/run`, opts ?? {}).then((r) => r.data),

  getRun: (runId: string) =>
    apiClient.get<EvalRun>(`/eval/runs/${runId}`).then((r) => r.data),

  addQuestion: (
    setId: string,
    q: { question_id: string; question: string; category?: string; expected_route?: string; expected_status?: string },
  ) =>
    apiClient
      .post(`/eval/question-sets/${setId}/questions`, [q])
      .then((r) => r.data),

  deleteQuestion: (setId: string, questionId: string) =>
    apiClient.delete(`/eval/question-sets/${setId}/questions/${questionId}`).then((r) => r.data),
}

