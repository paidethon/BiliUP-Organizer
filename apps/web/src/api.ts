/** Typed API client. CSRF: mutating requests send X-CSRF-Token from the cookie. */

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)biliup_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export async function api<T = unknown>(
  path: string,
  options: { method?: string; body?: unknown; query?: Record<string, string | number | undefined> } = {},
): Promise<T> {
  const url = new URL(`/api/v1${path}`, window.location.origin);
  for (const [k, v] of Object.entries(options.query ?? {})) {
    if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  }
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (!["GET", "HEAD"].includes(method)) headers["X-CSRF-Token"] = csrfToken();
  const res = await fetch(url.toString(), {
    method,
    headers,
    credentials: "same-origin",
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  const contentType = res.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const err = (payload as { error?: { code?: string; message?: string } })?.error;
    throw new ApiError(err?.code ?? "unknown", err?.message ?? `HTTP ${res.status}`, res.status);
  }
  return payload as T;
}

// ---- shared types (mirror app/schemas.py) ----

export interface UpUser {
  mid: number;
  uname: string;
  sign: string;
  face: string;
  official_type: number;
  special: boolean;
  followed_at: string | null;
  group_id: number | null;
  group_name?: string | null;
  groups?: { id: number; name: string; color: string }[];
  last_video_bvid: string | null;
  last_video_title: string | null;
  last_video_at: string | null;
  last_seen_at: string | null;
  missing: boolean;
  last_watched_at: string | null;
  watched_count: number;
  snoozed_until: string | null;
  blacklisted: boolean;
  ai_status: string;
}

export interface Group {
  id: number;
  name: string;
  color: string;
  sort_order: number;
  is_important: boolean;
  description: string;
  up_count: number;
}

export interface Reminder {
  id: number;
  rule_key: string;
  severity: "info" | "warning" | "critical";
  title: string;
  body: string;
  entity_type: string | null;
  entity_id: string | null;
  dedup_key: string;
  status: string;
  created_at: string;
}

export interface Suggestion {
  id: number;
  up_mid: number;
  up_uname: string;
  suggested_group_id: number | null;
  suggested_group_name: string;
  confidence: number;
  rationale: string;
  model: string;
  status: string;
  created_at: string;
}

export interface SyncRun {
  id: number;
  kind: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  stats: Record<string, unknown> | null;
  error: string | null;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
