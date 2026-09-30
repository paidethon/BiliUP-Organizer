import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api";
import { Button } from "../ui";
import { NumberField, TextField, TestButton, ToggleField } from "./fields";

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

// ---- GET /settings 返回的分区类型（密钥字段为掩码或空串） ----

export interface AiSectionValue {
  base_url: string;
  api_key: string;
  model: string;
  enabled: boolean;
  configured?: boolean;
  grouping_instructions?: string;
}

export interface SmtpSectionValue {
  host: string;
  port: number;
  username: string;
  password: string;
  from_addr: string;
  to_addr: string;
  use_tls: boolean;
  enabled: boolean;
  configured?: boolean;
}

export interface LumirssSectionValue {
  base_url: string;
  token: string;
  inbox_endpoint: string;
  enabled: boolean;
  configured?: boolean;
}

export interface RemindersSectionValue {
  stale_days: number;
  long_unwatched_days: number;
  never_watched_days: number;
  low_confidence_threshold: number;
  email_enabled: boolean;
  weekly_report_enabled: boolean;
  unwatched_days?: number[];
  scope_mode?: string;
  scope_group_ids?: number[];
  scope_mids?: number[];
  frequency_hours?: number;
}

export interface SyncSectionValue {
  interval_hours: number;
  history_enabled: boolean;
  history_max_pages: number;
  history_window_days?: number;
}

export interface SettingsData {
  ai: AiSectionValue;
  smtp: SmtpSectionValue;
  lumirss: LumirssSectionValue;
  reminders: RemindersSectionValue;
  sync: SyncSectionValue;
}

/** 分区表单公共 props：value 为服务端数据，保存时把整区对象交给页面提交。 */
export interface SectionFormProps<T> {
  value: T;
  saving: boolean;
  saved: boolean;
  error: string | null;
  onSave: (body: Record<string, unknown>) => void;
}

function SectionFooter({
  saveLabel,
  saving,
  saved,
  error,
  onSave,
}: {
  saveLabel: string;
  saving: boolean;
  saved: boolean;
  error: string | null;
  onSave: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-slate-800/60 mt-1 pt-3">
      <Button variant="primary" onClick={onSave} disabled={saving} aria-label={saveLabel}>
        {saving ? "保存中…" : "保存"}
      </Button>
      {saved && (
        <span className="text-xs text-emerald-300" role="status">
          ✓ 已保存
        </span>
      )}
      {error && (
        <span className="text-xs text-red-300" role="alert">
          {error}
        </span>
      )}
      <span className="text-xs text-slate-600">密钥留空或保持掩码表示不修改</span>
    </div>
  );
}

/** 数值字符串 → 数字；非法输入时回退到当前值。 */
function num(value: string, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

const secretPlaceholder = (filled: boolean) => (filled ? "已配置，留空保持不变" : "未配置");

// ---- AI ----

export function AiSectionForm({ value, saving, saved, error, onSave }: SectionFormProps<AiSectionValue>) {
  const [draft, setDraft] = useState({
    base_url: value.base_url,
    api_key: value.api_key,
    model: value.model,
    enabled: value.enabled,
    grouping_instructions: value.grouping_instructions ?? "",
  });
  useEffect(() => {
    setDraft({
      base_url: value.base_url,
      api_key: value.api_key,
      model: value.model,
      enabled: value.enabled,
      grouping_instructions: value.grouping_instructions ?? "",
    });
  }, [value]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <TextField
          label="Base URL"
          value={draft.base_url}
          onChange={(e) => setDraft((d) => ({ ...d, base_url: e.target.value }))}
          placeholder="https://api.example.com/v1"
          autoComplete="off"
        />
        <TextField
          label="API Key"
          type="password"
          value={draft.api_key}
          onChange={(e) => setDraft((d) => ({ ...d, api_key: e.target.value }))}
          placeholder={secretPlaceholder(Boolean(value.api_key))}
          autoComplete="new-password"
        />
        <TextField
          label="模型"
          value={draft.model}
          onChange={(e) => setDraft((d) => ({ ...d, model: e.target.value }))}
          placeholder="例如 gpt-4o-mini / deepseek-chat"
          autoComplete="off"
        />
        <div className="flex items-end pb-1.5">
          <ToggleField label="启用 AI 分类" checked={draft.enabled} onChange={(v) => setDraft((d) => ({ ...d, enabled: v }))} />
        </div>
      </div>
      <label className="block text-xs text-slate-400">
        分组指引（长期要求，随每次分类附加到提示词末尾）
        <textarea
          value={draft.grouping_instructions}
          onChange={(e) => setDraft((d) => ({ ...d, grouping_instructions: e.target.value }))}
          rows={3}
          maxLength={500}
          placeholder="例如：分组尽可能详细，优先使用已有分组；B 站关注分组上限 20 个"
          className="mt-1 w-full bg-slate-900/70 border border-slate-700 rounded-[var(--lumi-radius-sm)] px-3 py-2 text-sm text-slate-200 outline-none focus:border-indigo-400 resize-y"
        />
      </label>
      <TestButton what="ai" label="测试连接" hint="使用已保存的配置发起测试" />
      <SectionFooter saveLabel="保存 AI 分类" saving={saving} saved={saved} error={error} onSave={() => onSave(draft)} />
    </div>
  );
}

// ---- SMTP ----

export function SmtpSectionForm({ value, saving, saved, error, onSave }: SectionFormProps<SmtpSectionValue>) {
  const [draft, setDraft] = useState({
    host: value.host,
    port: String(value.port),
    username: value.username,
    password: value.password,
    from_addr: value.from_addr,
    to_addr: value.to_addr,
    use_tls: value.use_tls,
    enabled: value.enabled,
  });
  useEffect(() => {
    setDraft({
      host: value.host,
      port: String(value.port),
      username: value.username,
      password: value.password,
      from_addr: value.from_addr,
      to_addr: value.to_addr,
      use_tls: value.use_tls,
      enabled: value.enabled,
    });
  }, [value]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <TextField
          label="SMTP 服务器"
          value={draft.host}
          onChange={(e) => setDraft((d) => ({ ...d, host: e.target.value }))}
          placeholder="smtp.example.com"
        />
        <NumberField
          label="端口"
          value={draft.port}
          onChange={(v) => setDraft((d) => ({ ...d, port: v }))}
          min={1}
          max={65535}
          hint="465（SSL）或 587（STARTTLS）"
        />
        <TextField
          label="用户名"
          value={draft.username}
          onChange={(e) => setDraft((d) => ({ ...d, username: e.target.value }))}
          autoComplete="off"
        />
        <TextField
          label="密码 / 授权码"
          type="password"
          value={draft.password}
          onChange={(e) => setDraft((d) => ({ ...d, password: e.target.value }))}
          placeholder={secretPlaceholder(Boolean(value.password))}
          autoComplete="new-password"
        />
        <TextField
          label="发件地址"
          value={draft.from_addr}
          onChange={(e) => setDraft((d) => ({ ...d, from_addr: e.target.value }))}
          placeholder="biliup@example.com"
        />
        <TextField
          label="收件地址"
          value={draft.to_addr}
          onChange={(e) => setDraft((d) => ({ ...d, to_addr: e.target.value }))}
          placeholder="me@example.com"
        />
        <div className="flex items-end gap-6 pb-1.5">
          <ToggleField label="使用 TLS" checked={draft.use_tls} onChange={(v) => setDraft((d) => ({ ...d, use_tls: v }))} />
          <ToggleField label="启用邮件提醒" checked={draft.enabled} onChange={(v) => setDraft((d) => ({ ...d, enabled: v }))} />
        </div>
      </div>
      <TestButton what="email" label="发送测试邮件" hint="使用已保存的配置发送" />
      <SectionFooter
        saveLabel="保存邮件设置"
        saving={saving}
        saved={saved}
        error={error}
        onSave={() => onSave({ ...draft, port: num(draft.port, value.port) })}
      />
    </div>
  );
}

// ---- LumiRSS ----

export function LumirssSectionForm({ value, saving, saved, error, onSave }: SectionFormProps<LumirssSectionValue>) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState({
    base_url: value.base_url,
    token: value.token,
    inbox_endpoint: value.inbox_endpoint,
    enabled: value.enabled,
  });
  useEffect(() => {
    setDraft({
      base_url: value.base_url,
      token: value.token,
      inbox_endpoint: value.inbox_endpoint,
      enabled: value.enabled,
    });
  }, [value]);
  const [detectMsg, setDetectMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const detectMutation = useMutation({
    mutationFn: () =>
      api<{ ok: boolean; message: string; base_url: string | null }>("/settings/lumirss/detect", {
        method: "POST",
        body: draft.base_url ? { base_url: draft.base_url } : {},
      }),
    onSuccess: (res) => {
      setDetectMsg({ ok: res.ok, text: res.message });
      // detection writes base_url/inbox_endpoint server-side; refresh + resync draft
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err) => setDetectMsg({ ok: false, text: errText(err, "检测失败，请稍后重试") }),
  });

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <TextField
          label="Base URL"
          value={draft.base_url}
          onChange={(e) => setDraft((d) => ({ ...d, base_url: e.target.value }))}
          placeholder="http://127.0.0.1:8787"
          autoComplete="off"
        />
        <TextField
          label="Token"
          type="password"
          value={draft.token}
          onChange={(e) => setDraft((d) => ({ ...d, token: e.target.value }))}
          placeholder={secretPlaceholder(Boolean(value.token))}
          autoComplete="new-password"
        />
        <TextField
          label="Inbox 端点"
          value={draft.inbox_endpoint}
          onChange={(e) => setDraft((d) => ({ ...d, inbox_endpoint: e.target.value }))}
          placeholder="/inbox"
        />
        <div className="flex items-end pb-1.5">
          <ToggleField label="启用 LumiRSS" checked={draft.enabled} onChange={(v) => setDraft((d) => ({ ...d, enabled: v }))} />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="subtle"
          onClick={() => detectMutation.mutate()}
          disabled={detectMutation.isPending}
          aria-label="自动检测 LumiRSS 服务"
        >
          {detectMutation.isPending ? "检测中…" : "自动检测"}
        </Button>
        <span className="text-xs text-slate-500">只读探测（GET），发现服务后自动写入 Base URL 与 Inbox 端点</span>
        {detectMsg && (
          <span className={`text-xs ${detectMsg.ok ? "text-emerald-300" : "text-red-300"}`} role="status">
            {detectMsg.text}
          </span>
        )}
      </div>
      <TestButton what="lumirss" label="测试连接" hint="使用已保存的配置发起测试" />
      <SectionFooter saveLabel="保存 LumiRSS 设置" saving={saving} saved={saved} error={error} onSave={() => onSave(draft)} />
    </div>
  );
}

// ---- 提醒阈值 ----

interface GroupLite {
  id: number;
  name: string;
}

interface FollowingLite {
  mid: number;
  uname: string;
}

function parseWindows(text: string, fallback: number[]): number[] {
  const days = text
    .split(/[,，\s]+/)
    .map((part) => Number(part.trim()))
    .filter((n) => Number.isFinite(n) && n >= 1 && n <= 365);
  const unique = Array.from(new Set(days)).sort((a, b) => a - b).slice(0, 4);
  return unique.length ? unique : fallback;
}

export function RemindersSectionForm({ value, saving, saved, error, onSave }: SectionFormProps<RemindersSectionValue>) {
  const [draft, setDraft] = useState({
    stale_days: String(value.stale_days),
    unwatched_days: (value.unwatched_days ?? [value.long_unwatched_days]).join(","),
    never_watched_days: String(value.never_watched_days),
    low_confidence_threshold: String(value.low_confidence_threshold),
    frequency_hours: String(value.frequency_hours ?? 24),
    scope_mode: value.scope_mode ?? "all",
    scope_group_ids: value.scope_group_ids ?? [],
    scope_mids: value.scope_mids ?? [],
  });
  useEffect(() => {
    setDraft({
      stale_days: String(value.stale_days),
      unwatched_days: (value.unwatched_days ?? [value.long_unwatched_days]).join(","),
      never_watched_days: String(value.never_watched_days),
      low_confidence_threshold: String(value.low_confidence_threshold),
      frequency_hours: String(value.frequency_hours ?? 24),
      scope_mode: value.scope_mode ?? "all",
      scope_group_ids: value.scope_group_ids ?? [],
      scope_mids: value.scope_mids ?? [],
    });
  }, [value]);

  const [upQuery, setUpQuery] = useState("");
  const groupsQuery = useQuery({
    queryKey: ["groups"],
    queryFn: () => api<GroupLite[]>("/groups"),
    enabled: draft.scope_mode === "groups",
  });
  const upsQuery = useQuery({
    queryKey: ["followings", "scope-picker", upQuery],
    queryFn: () => api<{ items: FollowingLite[]; total: number }>("/followings", {
      query: upQuery ? { q: upQuery, page_size: 20 } : { page_size: 20 },
    }),
    enabled: draft.scope_mode === "ups",
  });

  function toggleGroup(id: number) {
    setDraft((d) => ({
      ...d,
      scope_group_ids: d.scope_group_ids.includes(id)
        ? d.scope_group_ids.filter((x) => x !== id)
        : [...d.scope_group_ids, id],
    }));
  }

  function toggleUp(mid: number, uname: string) {
    setDraft((d) => {
      const next = d.scope_mids.includes(mid)
        ? d.scope_mids.filter((x) => x !== mid)
        : [...d.scope_mids, mid];
      return { ...d, scope_mids: next };
    });
    setKnownUps((prev) => ({ ...prev, [mid]: uname }));
  }

  const [knownUps, setKnownUps] = useState<Record<number, string>>({});

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <NumberField
          label="断更天数阈值"
          value={draft.stale_days}
          onChange={(v) => setDraft((d) => ({ ...d, stale_days: v }))}
          min={1}
          hint="UP 超过该天数未投稿视为断更"
        />
        <TextField
          label="未观看提醒窗口（天）"
          value={draft.unwatched_days}
          onChange={(e) => setDraft((d) => ({ ...d, unwatched_days: e.target.value }))}
          placeholder="7,14,30"
          autoComplete="off"
          hint="逗号分隔，最多 4 档，例如 7,14,30"
        />
        <NumberField
          label="从未观看天数"
          value={draft.never_watched_days}
          onChange={(v) => setDraft((d) => ({ ...d, never_watched_days: v }))}
          min={1}
          hint="关注超过该天数仍未看过则提醒"
        />
        <NumberField
          label="低置信度阈值"
          value={draft.low_confidence_threshold}
          onChange={(v) => setDraft((d) => ({ ...d, low_confidence_threshold: v }))}
          min={0}
          max={1}
          step={0.05}
          hint="AI 置信度低于该值时生成低置信度提醒（0–1）"
        />
        <NumberField
          label="提醒检查频率（小时）"
          value={draft.frequency_hours}
          onChange={(v) => setDraft((d) => ({ ...d, frequency_hours: v }))}
          min={1}
          hint="提醒引擎按该间隔扫描；保存后重启服务生效"
        />
      </div>

      <div className="space-y-2">
        <label className="text-xs text-slate-400" htmlFor="scope-mode">提醒范围</label>
        <select
          id="scope-mode"
          value={draft.scope_mode}
          onChange={(e) => setDraft((d) => ({ ...d, scope_mode: e.target.value }))}
          className="bg-slate-900/70 border border-slate-700 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-indigo-400"
        >
          <option value="all">全部 UP</option>
          <option value="groups">仅指定分组</option>
          <option value="ups">仅指定 UP</option>
        </select>
        {draft.scope_mode === "groups" && (
          <div className="flex flex-wrap gap-2 p-2 rounded-lg border border-slate-800">
            {(groupsQuery.data ?? []).map((g) => (
              <label key={g.id} className="inline-flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={draft.scope_group_ids.includes(g.id)}
                  onChange={() => toggleGroup(g.id)}
                  aria-label={`提醒分组：${g.name}`}
                />
                {g.name}
              </label>
            ))}
            {groupsQuery.isLoading && <span className="text-xs text-slate-500">加载分组…</span>}
          </div>
        )}
        {draft.scope_mode === "ups" && (
          <div className="space-y-2 p-2 rounded-lg border border-slate-800">
            <input
              value={upQuery}
              onChange={(e) => setUpQuery(e.target.value)}
              placeholder="搜索 UP 昵称后勾选"
              aria-label="搜索 UP"
              className="w-full bg-slate-900/70 border border-slate-700 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-indigo-400"
            />
            <div className="max-h-44 overflow-auto space-y-1">
              {(upsQuery.data?.items ?? []).map((up) => (
                <label key={up.mid} className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={draft.scope_mids.includes(up.mid)}
                    onChange={() => toggleUp(up.mid, up.uname)}
                    aria-label={`提醒 UP：${up.uname}`}
                  />
                  {up.uname}
                  <span className="text-slate-600">{up.mid}</span>
                </label>
              ))}
            </div>
            <p className="text-xs text-slate-600">
              已选 {draft.scope_mids.length} 个 UP
              {draft.scope_mids.length > 0 && `：${draft.scope_mids.map((mid) => knownUps[mid] ?? mid).join("、")}`}
            </p>
          </div>
        )}
      </div>

      <SectionFooter
        saveLabel="保存提醒阈值"
        saving={saving}
        saved={saved}
        error={error}
        onSave={() =>
          onSave({
            stale_days: num(draft.stale_days, value.stale_days),
            long_unwatched_days: value.long_unwatched_days,
            unwatched_days: parseWindows(draft.unwatched_days, value.unwatched_days ?? [value.long_unwatched_days]),
            never_watched_days: num(draft.never_watched_days, value.never_watched_days),
            low_confidence_threshold: num(draft.low_confidence_threshold, value.low_confidence_threshold),
            frequency_hours: num(draft.frequency_hours, value.frequency_hours ?? 24),
            scope_mode: draft.scope_mode,
            scope_group_ids: draft.scope_group_ids,
            scope_mids: draft.scope_mids,
          })
        }
      />
    </div>
  );
}

// ---- 同步 ----

export function SyncSectionForm({ value, saving, saved, error, onSave }: SectionFormProps<SyncSectionValue>) {
  const [draft, setDraft] = useState({
    interval_hours: String(value.interval_hours),
    history_max_pages: String(value.history_max_pages),
    history_window_days: String(value.history_window_days ?? 14),
    history_enabled: value.history_enabled,
  });
  useEffect(() => {
    setDraft({
      interval_hours: String(value.interval_hours),
      history_max_pages: String(value.history_max_pages),
      history_window_days: String(value.history_window_days ?? 14),
      history_enabled: value.history_enabled,
    });
  }, [value]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <NumberField
          label="同步间隔（小时）"
          value={draft.interval_hours}
          onChange={(v) => setDraft((d) => ({ ...d, interval_hours: v }))}
          min={1}
          hint="定时任务按该间隔执行完整同步"
        />
        <NumberField
          label="历史最大抓取页数"
          value={draft.history_max_pages}
          onChange={(v) => setDraft((d) => ({ ...d, history_max_pages: v }))}
          min={1}
          hint="每次同步最多拉取的观看历史页数"
        />
        <NumberField
          label="历史统计窗口（天）"
          value={draft.history_window_days}
          onChange={(v) => setDraft((d) => ({ ...d, history_window_days: v }))}
          min={1}
          hint="按窗口完整拉取历史，14 天等统计以此为准"
        />
        <div className="flex items-end pb-1.5">
          <ToggleField
            label="同步观看历史"
            checked={draft.history_enabled}
            onChange={(v) => setDraft((d) => ({ ...d, history_enabled: v }))}
            hint="关闭后不再抓取观看记录，统计与周报将停滞"
          />
        </div>
      </div>
      <SectionFooter
        saveLabel="保存同步设置"
        saving={saving}
        saved={saved}
        error={error}
        onSave={() =>
          onSave({
            interval_hours: num(draft.interval_hours, value.interval_hours),
            history_max_pages: num(draft.history_max_pages, value.history_max_pages),
            history_window_days: num(draft.history_window_days, value.history_window_days ?? 14),
            history_enabled: draft.history_enabled,
          })
        }
      />
    </div>
  );
}

// ---- 共用底栏 ----（SectionFooter 定义见文件上方）
