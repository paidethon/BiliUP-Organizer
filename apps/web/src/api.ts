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
  recent_videos: { bvid?: string; title: string; tname?: string | null; pubdate: string | null }[];
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
  would_create_tags?: string[];
  would_delete_tags?: string[];
  would_move?: number;
  skipped?: number | string;
  conflicts?: string[];
  notes?: string[];
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ---- weekly report / stats contract (app/services/stats.py) ----

export interface CoverageInfo {
  timezone: string;
  last_history_sync_at: string | null;
  last_history_sync_status: string | null;
  history_max_pages: number | null;
  history_window_days: number | null;
  history_truncated: boolean;
  observation_cutoff: string | null;
  note: string;
}

export interface DayPoint {
  date: string;
  views: number | null;
  seconds: number | null;
  covered: boolean;
}

export interface GroupPrefPoint {
  name: string;
  views: number;
  seconds: number;
  ups?: number;
}

export interface TopUpPoint {
  mid: number;
  uname: string | null;
  name_source: string | null;
  views: number;
  seconds?: number;
}

export interface BucketPoint {
  label: string;
  value: number;
}

export interface GroupCoveragePoint {
  group_id: number | null;
  name: string;
  total: number;
  covered: number;
  ratio: number;
  uncovered_sample: number[];
}

export interface VideoCoveragePoint {
  group_id: number | null;
  name: string;
  synced_videos: number;
  watched_videos: number;
  unwatched_videos: number;
  ratio: number;
  unwatched_sample: string[];
}

export interface UpDeltaItem {
  mid: number;
  uname: string | null;
  name_source: string | null;
  current: number;
  previous: number;
  delta: number;
  change: "up" | "down" | "new" | "flat";
}

export interface ExploreReturnPoint {
  date: string;
  new_ups: number | null;
  returning_ups: number | null;
  covered: boolean;
}

export interface HeatmapDay {
  date: string;
  weekday: number;
  hours: Array<{ views: number | null; seconds: number | null }>;
}

export interface RangeStats {
  metrics_version: string;
  timezone: string;
  period: { start: string; end_exclusive: string; is_complete: boolean; generated_at: string };
  views: number;
  watch_seconds_est: number;
  avg_watch_seconds: number | null;
  samples: { valid: number; bound: number; unknown: number };
  distinct_videos: number;
  distinct_ups: number;
  daily: DayPoint[];
  hourly: number[];
  weekday: Array<{ label: string; value: number }>;
  // extras
  duration_buckets?: { buckets: BucketPoint[]; unknown: number };
  completion_buckets?: { buckets: BucketPoint[]; unknown: number };
  tname_top?: Array<{ name: string; views: number }>;
  tname_coverage?: { matched: number; total: number };
  by_group?: GroupPrefPoint[];
  by_group_primary?: GroupPrefPoint[];
  top_ups?: TopUpPoint[];
  top5_share?: number;
  new_videos?: number;
  heatmap?: { hours: number; days: HeatmapDay[] };
  group_coverage?: GroupCoveragePoint[];
  video_coverage?: VideoCoveragePoint[];
  explore_return?: ExploreReturnPoint[];
  up_delta?: { risers: UpDeltaItem[]; fallers: UpDeltaItem[] };
  previous?: {
    period: { start: string; end_exclusive: string };
    views: number;
    distinct_videos: number;
    distinct_ups: number;
    daily: DayPoint[];
  };
  coverage: CoverageInfo;
  lists?: {
    stale: Array<{ mid: number; uname: string; last_video_at: string | null; days: number }>;
    never_watched: Array<{ mid: number; uname: string; followed_at: string | null; days: number }>;
    important_unwatched: Array<{ mid: number; uname: string; title: string; last_video_at: string | null }>;
  };
}

export interface WeeklyReportMeta {
  id: number;
  period_start: string | null;
  period_end_exclusive: string | null;
  revision: number;
  is_legacy: boolean;
  status: string;
  generated_at: string | null;
  generated_at_shanghai: string | null;
  send_status: string | null;
  sent_at: string | null;
  views?: number | null;
}

export interface WeeklyReportDetail extends WeeklyReportMeta {
  scope: string;
  timezone: string;
  metrics_version: string;
  data_cutoff: string | null;
  stats: Partial<RangeStats>;
  ai_text: string | null;
}

export interface WeekInfo {
  week_start: string;
  week_end_exclusive: string;
  week_end_inclusive_label: string;
  is_complete: boolean;
  today: string;
  timezone: string;
  revisions: Array<{
    id: number;
    revision: number;
    generated_at_shanghai: string | null;
    status: string;
    send_status: string | null;
    views: number | null;
  }>;
}

export interface HistoryItem {
  bvid: string;
  up_mid: number | null;
  up_uname: string | null;
  title: string;
  view_at: string;
  view_at_shanghai: string | null;
  progress: number;
  duration_seconds: number | null;
}

export interface HistorySummary {
  total_entries: number;
  entries_30d: number;
  distinct_ups_watched: number;
  distinct_videos: number;
  watch_seconds_est: number;
  samples: { valid: number; bound: number; unknown: number };
  top_watched: Array<{ mid: number; uname: string | null; name_source: string | null; views: number }>;
  daily_counts: Array<{ day: string; views: number | null; covered: boolean }>;
  never_watched_count: number;
  coverage: CoverageInfo;
  period: RangeStats["period"];
}

// ---- API calls ----

export const weeklyApi = {
  week: (date?: string) =>
    api<WeekInfo>("/weekly-report/week", { query: { date } }),
  stats: (start: string, end: string) =>
    api<RangeStats>("/weekly-report/stats", { query: { start, end } }),
  archives: () => api<{ weeks: Array<WeeklyReportMeta> }>("/weekly-report/archives"),
  generate: (weekStart: string, save: boolean) =>
    api<{ saved: boolean; report: WeeklyReportDetail }>("/weekly-report/generate", {
      method: "POST",
      body: { week_start: weekStart, save },
    }),
  get: (id: number) => api<WeeklyReportDetail>(`/weekly-report/${id}`),
  regenerate: (id: number) =>
    api<{ saved: boolean; report: WeeklyReportDetail }>(`/weekly-report/${id}/regenerate`, { method: "POST" }),
  send: (id: number) => api<{ ok: boolean; message: string }>(`/weekly-report/${id}/send`, { method: "POST" }),
  ai: (id: number) => api<{ ok: boolean; ai_text?: string; message?: string }>(`/weekly-report/${id}/ai`, { method: "POST" }),
  exportUrl: (id: number, format: "html" | "md" | "json") => `/api/v1/weekly-report/${id}/export?format=${format}`,
};

export const historyApi = {
  summary: (params?: { start?: string; end?: string; group_id?: number; up_mid?: number; limit?: number }) =>
    api<HistorySummary>("/history/summary", {
      query: {
        start: params?.start,
        end: params?.end,
        group_id: params?.group_id,
        up_mid: params?.up_mid,
        limit: params?.limit,
      },
    }),
  list: (params: {
    page: number;
    page_size?: number;
    q?: string;
    up_mid?: number;
    group_id?: number;
    start?: string;
    end?: string;
    hour?: number;
  }) => api<Paged<HistoryItem>>("/history", { query: { ...params, page_size: params.page_size ?? 50 } }),
};

export function nativePushPlan(mode: "append" | "replace") {
  return api<Record<string, unknown>>("/bilibili/native-groups/push-plan", { method: "POST", body: { mode } });
}

export function nativePushRun(mode: "append" | "replace") {
  return api<SyncRun>("/bilibili/native-groups/push-run", { method: "POST", body: { mode } });
}
