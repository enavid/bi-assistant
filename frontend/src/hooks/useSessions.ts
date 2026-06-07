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
mutationFn: ({ title, templateName }: { title: string; templateName: string }) =>
  chatApi.createSession({ title, template_name: templateName, model_name: 'default' }),
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
