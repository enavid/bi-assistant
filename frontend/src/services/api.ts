import apiClient from './apiClient'
import type {
  ChatSession,
  GenerateResponse,
  OllamaHealth,
  Project,
  QueryResult,
  Section,
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
    apiClient.patch(`/workspace/experiments/${experimentId}/feedback`, { correct }).then((r) => r.data),
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

