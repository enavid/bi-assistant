import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { chatApi } from '@/services/api'

export function useSessions() {
  return useQuery({
    queryKey: ['sessions'],
    queryFn: chatApi.listSessions,
  })
}

export function useCreateSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ title, project_id, model_name }: { title: string; project_id?: string | null; model_name: string }) =>
      chatApi.createSession({ title, project_id, model_name }),
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
