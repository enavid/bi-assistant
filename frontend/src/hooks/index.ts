import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { chatApi, ollamaApi, projectApi } from '@/services/api'
import type { Project, Section } from '@/types'

// ---------------------------------------------------------------------------
// Ollama
// ---------------------------------------------------------------------------

export function useOllamaHealth() {
  return useQuery({
    queryKey: ['ollama-health'],
    queryFn: ollamaApi.health,
    refetchInterval: 20_000,
    retry: false,
  })
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

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
    mutationFn: ({
      projectId,
      sectionId,
      payload,
    }: {
      projectId: string
      sectionId: string
      payload: Partial<Section>
    }) => projectApi.updateSection(projectId, sectionId, payload),
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

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export function useSessions() {
  return useQuery({ queryKey: ['sessions'], queryFn: chatApi.listSessions })
}

export function useCreateSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: chatApi.createSession,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sessions'] }),
  })
}

export function useUpdateSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Parameters<typeof chatApi.updateSession>[1] }) =>
      chatApi.updateSession(id, payload),
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
