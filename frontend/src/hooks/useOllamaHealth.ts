import { useQuery } from '@tanstack/react-query'
import { ollamaApi } from '@/services/api'

export function useOllamaHealth() {
  return useQuery({
    queryKey: ['ollama-health'],
    queryFn: ollamaApi.health,
    refetchInterval: 15_000,
    retry: false,
  })
}
