import { getApiBaseUrl } from '../lib/env'

export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(message: string, status: number, body: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function joinUrl(base: string, path: string): string {
  const b = base.replace(/\/$/, '')
  const p = path.startsWith('/') ? path : `/${path}`
  return `${b}${p}`
}

function extractMessage(status: number, body: unknown): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const d = (body as { detail: unknown }).detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) return JSON.stringify(d)
  }
  if (typeof body === 'string' && body.length > 0) return body
  return `Request failed (${status})`
}

async function readBody(res: Response): Promise<unknown> {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text) as unknown
  } catch {
    return text
  }
}

/**
 * Typed JSON fetch against the Chudbet API. Throws {@link ApiError} on non-OK responses.
 */
export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const url = joinUrl(getApiBaseUrl(), path)
  const hasBody = init?.body != null && init.body !== ''

  const res = await fetch(url, {
    ...init,
    headers: {
      ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })

  const body = await readBody(res)

  if (!res.ok) {
    throw new ApiError(extractMessage(res.status, body), res.status, body)
  }

  return body as T
}
