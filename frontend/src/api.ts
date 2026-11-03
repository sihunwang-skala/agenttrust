export class ApiError extends Error {
  constructor(public code: string, message: string, public details?: unknown) { super(message); }
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const e = body?.error ?? {};
    throw new ApiError(e.code ?? "HTTP_ERROR", e.message ?? `HTTP ${res.status}`, e.details);
  }
  return body as T;
}

export const post = <T = any>(path: string, data?: unknown) =>
  api<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data) });

export const krw = (n: number | null | undefined) => (n == null ? "-" : `${n.toLocaleString("en-US")} KRW`);
