import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { templateApi } from '@/services/api'
import type { PromptTemplate } from '@/types'

export function useTemplates() {
  return useQuery({
    queryKey: ['templates'],
    queryFn: templateApi.list,
  })
}

export function useActivateTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => templateApi.activate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['templates'] }),
  })
}

export function useUpdateTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<PromptTemplate> }) =>
      templateApi.update(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['templates'] }),
  })
}

export function useDeleteTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => templateApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['templates'] }),
  })
}
