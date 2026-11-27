import { request } from './client'

/** 漂移看板相关接口的宽松客户端；后端同时返回中英文业务字段。 */
async function parse<T = any>(response: Response): Promise<T> {
  let data: any = null
  try {
    data = await response.json()
  } catch {
    data = { ok: response.ok, message: `接口返回 ${response.status}` }
  }
  return { status: response.status, ...(data ?? {}) } as T
}

function query(params: Record<string, any>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

async function get<T = any>(path: string, params: Record<string, any> = {}): Promise<T> {
  return parse<T>(await request(`${path}${query(params)}`))
}

async function post<T = any>(path: string, body: Record<string, any> = {}): Promise<T> {
  return parse<T>(await request(path, { method: 'POST', body: JSON.stringify(body) }))
}

export type DriftRound = Record<string, any>
export type DriftBoard = Record<string, any>
export type DriftResult = Record<string, any>

export const driftClient = {
  experiments: () => get('/api/aa-drift/experiments'),
  rounds: (experiment_code: string) => get('/api/aa-drift/rounds', { experiment_code }),
  board: (params: Record<string, any>) => get('/api/aa-drift/board', params),
  compare: (body: Record<string, any>) => post('/api/aa-drift/compare', body),
  createRound: (body: Record<string, any>) => post('/api/aa-drift/rounds', body),
  confirmRound: (id: string | number) => post(`/api/aa-drift/rounds/${id}/confirm`),
  revokeRound: (id: string | number, reason = '') =>
    post(`/api/aa-drift/rounds/${id}/revoke`, { reason }),
  correct: (body: Record<string, any>) => post('/api/aa-drift/assignments/correct', body),
  createRequest: (body: Record<string, any>) => post('/api/aa-drift/requests', body),
  createOrder: (body: Record<string, any>) => post('/api/aa-drift/transfer-orders', body),
  orders: () => get('/api/aa-drift/transfer-orders'),

  applications: () => get('/api/sample-drift/applications'),
  createApplication: (body: Record<string, any>) => post('/api/sample-drift/applications', body),
  application: (id: string | number) => get(`/api/sample-drift/applications/${id}`),
  claim: (id: string | number, resolution?: string) =>
    post(`/api/sample-drift/applications/${id}/claim`, resolution ? { resolution } : {}),
  review: (id: string | number) => post(`/api/sample-drift/applications/${id}/review`),
  trace: (id: string | number) => get(`/api/sample-drift/applications/${id}/trace`),
  traceSampleEntry: (id: string | number) => get(`/api/sample_ratio/${id}/drift-trace`),
}
