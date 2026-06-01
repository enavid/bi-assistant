import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 130_000,
  headers: { 'Content-Type': 'application/json' },
})

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

apiClient.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) localStorage.removeItem('access_token')
    return Promise.reject(err)
  }
)

export default apiClient
