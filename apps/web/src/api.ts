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
  tags?: { id: number; name: string; color: string }[];
  status_labels?: string[];
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
  aliases?: string[];
}

export interface Tag {
  id: number;
  name: string;
  color: string;
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
  up_face: string;
  suggested_group_id: number | null;
  suggested_group_name: string;
  suggested_tags: string[];
  previous_group_name: string | null;
  confidence: number;
  rationale: string;
  evidence: { sample_titles?: string[]; source?: string; video_count?: number };
  model: string;
  provider: string;
  prompt_version: string;
  status: string;
  created_at: string;
  current_group_name: string | null;
  recent_videos: { title: string; tname: string | null; pubdate: string | null }[];
  status_labels: string[];
}

export interface ClassificationJob {
  id: number;
  kind: "pending" | "full";
  status: "running" | "paused" | "completed" | "cancelled" | "failed";
  batch_size: number;
  auto_apply: boolean;
  threshold: number;
  total: number;
  processed: number;
  classified: number;
  auto_applied: number;
  needs_review: number;
  unclassifiable: number;
  failed: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  progress?: number;
}

export interface UndoRecord {
  id: number;
  action: string;
  summary: string;
  status: string;
  created_at: string;
  expires_at: string;
  item_count: number;
}

export interface BulkQuery {
  q?: string;
  group_id?: string;
  flag?: string;
  status?: string;
  tag_id?: string;
  sort?: string;
  order?: string;
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

export interface NativePlan {
  mode: string;
  dry_run: boolean;
  would_create_tags: string[];
  would_delete_tags: string[];
  would_move: number;
  skipped: number;
  conflicts: string[];
  notes: string[];
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
