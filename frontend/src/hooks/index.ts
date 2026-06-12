import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { chatApi, connectionApi, evalApi, ollamaApi, projectApi } from '@/services/api'
import type { EvalQuestion, Project, Section } from '@/types'

export function useOllamaHealth() {
  return useQuery({
    queryKey: ['ollama-health'],
    queryFn: ollamaApi.health,
    refetchInterval: 20_000,
    retry: false,
  })
}

export function useProjects() {
  return useQuery({ queryKey: ['projects'], queryFn: projectApi.list })
}

export function useProject(id: string | null) {
  return useQuery({
    queryKey: ['project', id],
    queryFn: () => projectApi.get(id!),
    enabled: !!id,
  })
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, description }: { name: string; description?: string }) =>
      projectApi.create(name, description),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })
}

export function useUpdateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<Project> }) =>
      projectApi.update(id, payload),
    onSuccess: (_, { id }) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      qc.invalidateQueries({ queryKey: ['project', id] })
    },
  })
}

export function useDeleteProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => projectApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })
}

export function useCreateSection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, section }: { projectId: string; section: Partial<Section> }) =>
      projectApi.createSection(projectId, section),
    onSuccess: (_, { projectId }) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      qc.invalidateQueries({ queryKey: ['project', projectId] })
    },
  })
}

export function useUpdateSection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, sectionId, payload }: { projectId: string; sectionId: string; payload: Partial<Section> }) =>
      projectApi.updateSection(projectId, sectionId, payload),
    onSuccess: (_, { projectId }) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      qc.invalidateQueries({ queryKey: ['project', projectId] })
    },
  })
}

export function useDeleteSection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, sectionId }: { projectId: string; sectionId: string }) =>
      projectApi.deleteSection(projectId, sectionId),
    onSuccess: (_, { projectId }) => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      qc.invalidateQueries({ queryKey: ['project', projectId] })
    },
  })
}

export function useSessions() {
  return useQuery({ queryKey: ['sessions'], queryFn: chatApi.listSessions })
}

export function useSession(id: string | null) {
  return useQuery({
    queryKey: ['session', id],
    queryFn: () => chatApi.getSession(id!),
    enabled: !!id,
  })
}

export function useCreateSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: chatApi.createSession,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sessions'] }),
  })
}

export function useDeleteSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => chatApi.deleteSession(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sessions'] }),
  })
}

// ---------------------------------------------------------------------------
// Connection hooks
// ---------------------------------------------------------------------------

export function useQueryDatabases() {
  return useQuery({ queryKey: ['query-databases'], queryFn: connectionApi.list })
}

export function useCreateQueryDatabase() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: connectionApi.create,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['query-databases'] }),
  })
}

export function useUpdateQueryDatabase() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Parameters<typeof connectionApi.update>[1] }) =>
      connectionApi.update(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['query-databases'] }),
  })
}

export function useDeleteQueryDatabase() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => connectionApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['query-databases'] }),
  })
}

export function useActivateQueryDatabase() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => connectionApi.activate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['query-databases'] }),
  })
}

export function useDeactivateQueryDatabases() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: connectionApi.deactivate,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['query-databases'] }),
  })
}

export function useTestConnection() {
  return useMutation({ mutationFn: connectionApi.test })
}

// ---------------------------------------------------------------------------
// Eval hooks
// ---------------------------------------------------------------------------

export function useEvalSets() {
  return useQuery({ queryKey: ['eval-sets'], queryFn: evalApi.listSets })
}

export function useCreateEvalSet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, description }: { name: string; description?: string }) =>
      evalApi.createSet(name, description),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['eval-sets'] }),
  })
}

export function useDeleteEvalSet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => evalApi.deleteSet(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['eval-sets'] }),
  })
}

export function useEvalQuestions(setId: string | null) {
  return useQuery({
    queryKey: ['eval-questions', setId],
    queryFn: () => evalApi.listQuestions(setId!),
    enabled: !!setId,
  })
}

export function useImportEvalQuestions() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ setId, questions }: { setId: string; questions: Omit<EvalQuestion, 'id' | 'set_id' | 'created_at'>[] }) =>
      evalApi.importQuestions(setId, questions),
    onSuccess: (_, { setId }) => {
      qc.invalidateQueries({ queryKey: ['eval-questions', setId] })
      qc.invalidateQueries({ queryKey: ['eval-sets'] })
    },
  })
}

export function useEvalRuns(setId: string | null) {
  return useQuery({
    queryKey: ['eval-runs', setId],
    queryFn: () => evalApi.listRuns(setId!),
    enabled: !!setId,
  })
}

export function useSeedEvalDefaults() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: evalApi.seedDefaults,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['eval-sets'] }),
  })
}

export function useTriggerEvalRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ setId, category, model_name }: { setId: string; category?: string; model_name?: string }) =>
      evalApi.triggerRun(setId, { category, model_name }),
    onSuccess: (_, { setId }) => qc.invalidateQueries({ queryKey: ['eval-runs', setId] }),
  })
}

export function useAddEvalQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      setId,
      question_id,
      question,
      category,
      expected_route,
    }: {
      setId: string
      question_id: string
      question: string
      category?: string
      expected_route?: string
    }) => evalApi.addQuestion(setId, { question_id, question, category, expected_route }),
    onSuccess: (_, { setId }) => {
      qc.invalidateQueries({ queryKey: ['eval-questions', setId] })
      qc.invalidateQueries({ queryKey: ['eval-sets'] })
    },
  })
}

export function useDeleteEvalQuestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ setId, questionId }: { setId: string; questionId: string }) =>
      evalApi.deleteQuestion(setId, questionId),
    onSuccess: (_, { setId }) => {
      qc.invalidateQueries({ queryKey: ['eval-questions', setId] })
      qc.invalidateQueries({ queryKey: ['eval-sets'] })
    },
  })
}

export function useEvalRun(runId: string | null, isRunning: boolean) {
  return useQuery({
    queryKey: ['eval-run', runId],
    queryFn: () => evalApi.getRun(runId!),
    enabled: !!runId,
    refetchInterval: isRunning ? 3000 : false,
  })
}
