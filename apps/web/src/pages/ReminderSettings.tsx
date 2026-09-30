import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Button, Card, ErrorState, Spinner } from "../components/ui";
import { relativeTime } from "../components/followings/helpers";

interface RemindersValue {
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

interface GroupLite {
  id: number;
  name: string;
}

interface FollowingLite {
  mid: number;
  uname: string;
}

interface LastScan {
  created: number;
  resolved: number;
}

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

const RULES: { key: string; title: string; desc: string }[] = [
  { key: "stale_uploader", title: "断更提醒", desc: "UP 超过「断更天数阈值」未投稿（无投稿记录也视为断更）" },
  { key: "long_unwatched", title: "未观看提醒", desc: "上次观看超过任一「未观看窗口」；每档窗口独立一条，可多档并存" },
  { key: "never_watched", title: "从未观看提醒", desc: "关注超过「从未观看天数」且累计观看为 0" },
  { key: "important_unwatched", title: "重要 UP 更新未看", desc: "标记为重要的分组里有新视频晚于上次观看" },
  { key: "low_confidence", title: "低置信度提醒", desc: "AI 分组建议置信度低于阈值时提示复核" },
  { key: "login_expired", title: "登录过期", desc: "B 站 Cookie 失效时告警（不受范围限制）" },
  { key: "sync_failed", title: "同步失败", desc: "最近一次关注同步失败时告警（不受范围限制）" },
  { key: "ai_failed", title: "AI 分类失败", desc: "存在分类失败的 UP 时告警（不受范围限制）" },
];

export default function ReminderSettings() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<{ reminders: RemindersValue }>("/settings"),
  });

  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [scanResult, setScanResult] = useState<LastScan | null>(null);

  const [draft, setDraft] = useState<RemindersValue | null>(null);
  const [windowInput, setWindowInput] = useState("");
  const [upQuery, setUpQuery] = useState("");
  const [knownUps, setKnownUps] = useState<Record<number, string>>({});

  useEffect(() => {
    if (data?.reminders) {
      setDraft({ ...data.reminders, unwatched_days: data.reminders.unwatched_days ?? [data.reminders.long_unwatched_days] });
    }
  }, [data]);

  const groupsQuery = useQuery({
    queryKey: ["groups"],
    queryFn: () => api<GroupLite[]>("/groups"),
    enabled: draft?.scope_mode === "groups",
  });
  const upsQuery = useQuery({
    queryKey: ["followings", "reminder-picker", upQuery],
    queryFn: () =>
      api<{ items: FollowingLite[]; total: number }>("/followings", {
        query: upQuery ? { q: upQuery, page_size: 20 } : { page_size: 20 },
      }),
    enabled: draft?.scope_mode === "ups",
  });

  const saveMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => api("/settings/reminders", { method: "PUT", body }),
    onSuccess: () => {
      setSavedAt(new Date().toISOString());
      setSaveError(null);
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err) => setSaveError(errText(err, "保存失败，请重试")),
  });

  const scanMutation = useMutation({
    mutationFn: () => api<LastScan>("/reminders/scan", { method: "POST" }),
    onSuccess: (res) => {
      setScanResult(res);
      void queryClient.invalidateQueries({ queryKey: ["reminders"] });
    },
  });

  function save() {
    if (!draft) return;
    setSaving(true);
    saveMutation.mutate(
      {
        stale_days: draft.stale_days,
        long_unwatched_days: draft.long_unwatched_days,
        never_watched_days: draft.never_watched_days,
        low_confidence_threshold: draft.low_confidence_threshold,
        email_enabled: draft.email_enabled,
        weekly_report_enabled: draft.weekly_report_enabled,
        unwatched_days: (draft.unwatched_days ?? []).slice(0, 4),
        scope_mode: draft.scope_mode ?? "all",
        scope_group_ids: draft.scope_group_ids ?? [],
        scope_mids: draft.scope_mids ?? [],
        frequency_hours: draft.frequency_hours ?? 24,
      },
      { onSettled: () => setSaving(false) },
    );
  }

  function addWindow() {
    const days = Number(windowInput.trim());
    if (!draft || !Number.isFinite(days) || days < 1 || days > 365) return;
    const next = Array.from(new Set([...(draft.unwatched_days ?? []), days]))
      .sort((a, b) => a - b)
      .slice(0, 4);
    setDraft({ ...draft, unwatched_days: next });
    setWindowInput("");
  }

  function removeWindow(days: number) {
    if (!draft) return;
    const next = (draft.unwatched_days ?? []).filter((d) => d !== days);
    setDraft({ ...draft, unwatched_days: next.length ? next : [draft.long_unwatched_days] });
  }

  function toggleGroup(id: number) {
    if (!draft) return;
    const ids = draft.scope_group_ids ?? [];
    setDraft({
      ...draft,
      scope_group_ids: ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id],
    });
  }

  function toggleUp(mid: number, uname: string) {
    if (!draft) return;
    const ids = draft.scope_mids ?? [];
    setKnownUps((prev) => ({ ...prev, [mid]: uname }));
    setDraft({ ...draft, scope_mids: ids.includes(mid) ? ids.filter((x) => x !== mid) : [...ids, mid] });
  }

  if (isLoading) return <Spinner label="正在加载提醒配置…" />;
  if (error) return <ErrorState message={errText(error, "加载提醒配置失败")} />;
  if (!draft) return null;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">提醒配置</h1>
        {savedAt && (
          <span className="text-xs text-emerald-300" role="status">
            ✓ 已保存 {relativeTime(savedAt)}
          </span>
        )}
        {saveError && (
          <span className="text-xs text-red-300" role="alert">
            {saveError}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {scanResult && (
            <span className="text-xs text-slate-400" role="status">
              上次扫描：新增 {scanResult.created} 条，自动解决 {scanResult.resolved} 条
            </span>
          )}
          <Button
            variant="subtle"
            onClick={() => scanMutation.mutate()}
            disabled={scanMutation.isPending}
            aria-label="立即扫描提醒规则"
          >
            {scanMutation.isPending ? "扫描中…" : "立即扫描"}
          </Button>
          <Button variant="primary" onClick={save} disabled={saving} aria-label="保存提醒配置">
            {saving ? "保存中…" : "保存配置"}
          </Button>
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="space-y-3">
          <h2 className="text-sm font-semibold">未观看提醒窗口</h2>
          <p className="text-xs text-slate-500">
            为「上次观看」设置多档阈值（如 7、14、30 天）；每档独立去重，一个 UP 可同时处于多档提醒中。最多 4 档。
          </p>
          <div className="flex flex-wrap gap-2">
            {(draft.unwatched_days ?? []).map((days) => (
              <span
                key={days}
                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs border border-indigo-400/60 text-indigo-300 bg-indigo-500/10"
              >
                {days} 天
                <button
                  type="button"
                  onClick={() => removeWindow(days)}
                  aria-label={`删除 ${days} 天窗口`}
                  className="text-slate-400 hover:text-white"
                >
                  ✕
                </button>
              </span>
            ))}
            {(draft.unwatched_days ?? []).length === 0 && <span className="text-xs text-slate-500">暂无窗口</span>}
          </div>
          <div className="flex gap-2">
            <input
              value={windowInput}
              onChange={(e) => setWindowInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addWindow()}
              placeholder="输入天数，如 30"
              aria-label="新增窗口天数"
              className="w-36 bg-slate-900/70 border border-slate-700 rounded-[var(--lumi-radius-sm)] px-3 py-1.5 text-sm outline-none focus:border-indigo-400"
            />
            <Button variant="ghost" onClick={addWindow} aria-label="添加窗口">
              添加
            </Button>
          </div>
        </Card>

        <Card className="space-y-3">
          <h2 className="text-sm font-semibold">提醒范围</h2>
          <p className="text-xs text-slate-500">限定哪些 UP 参与 UP 级提醒（系统级告警不受影响）。</p>
          <select
            value={draft.scope_mode ?? "all"}
            onChange={(e) => setDraft({ ...draft, scope_mode: e.target.value })}
            aria-label="提醒范围模式"
            className="w-full bg-slate-900/70 border border-slate-700 rounded-[var(--lumi-radius-sm)] px-2 py-1.5 text-sm outline-none focus:border-indigo-400"
          >
            <option value="all">全部 UP</option>
            <option value="groups">仅指定分组</option>
            <option value="ups">仅指定 UP</option>
          </select>
          {draft.scope_mode === "groups" && (
            <div className="flex flex-wrap gap-2 p-2 rounded-xl border border-slate-800">
              {(groupsQuery.data ?? []).map((g) => (
                <label key={g.id} className="inline-flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={(draft.scope_group_ids ?? []).includes(g.id)}
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
            <div className="space-y-2 p-2 rounded-xl border border-slate-800">
              <input
                value={upQuery}
                onChange={(e) => setUpQuery(e.target.value)}
                placeholder="搜索 UP 昵称后勾选"
                aria-label="搜索 UP"
                className="w-full bg-slate-900/70 border border-slate-700 rounded-[var(--lumi-radius-sm)] px-2 py-1.5 text-sm outline-none focus:border-indigo-400"
              />
              <div className="max-h-40 overflow-auto space-y-1">
                {(upsQuery.data?.items ?? []).map((up) => (
                  <label key={up.mid} className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={(draft.scope_mids ?? []).includes(up.mid)}
                      onChange={() => toggleUp(up.mid, up.uname)}
                      aria-label={`提醒 UP：${up.uname}`}
                    />
                    {up.uname}
                    <span className="text-slate-600">{up.mid}</span>
                  </label>
                ))}
              </div>
              <p className="text-xs text-slate-600">
                已选 {(draft.scope_mids ?? []).length} 个 UP
                {(draft.scope_mids ?? []).length > 0 &&
                  `：${(draft.scope_mids ?? []).map((mid) => knownUps[mid] ?? mid).join("、")}`}
              </p>
            </div>
          )}
        </Card>

        <Card className="space-y-3">
          <h2 className="text-sm font-semibold">阈值与频率</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <NumberBox
              label="断更天数阈值"
              value={draft.stale_days}
              min={1}
              hint="超过该天数未投稿视为断更"
              onChange={(v) => setDraft({ ...draft, stale_days: v })}
            />
            <NumberBox
              label="从未观看天数"
              value={draft.never_watched_days}
              min={1}
              hint="关注超过该天数仍未看过"
              onChange={(v) => setDraft({ ...draft, never_watched_days: v })}
            />
            <NumberBox
              label="低置信度阈值"
              value={draft.low_confidence_threshold}
              min={0}
              max={1}
              step={0.05}
              hint="AI 建议置信度低于该值时提醒（0–1）"
              onChange={(v) => setDraft({ ...draft, low_confidence_threshold: v })}
            />
            <NumberBox
              label="检查频率（小时）"
              value={draft.frequency_hours ?? 24}
              min={1}
              hint="提醒引擎扫描间隔，保存后重启服务生效"
              onChange={(v) => setDraft({ ...draft, frequency_hours: v })}
            />
          </div>
          <div className="flex flex-wrap gap-6 pt-1">
            <label className="inline-flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={draft.email_enabled}
                onChange={(e) => setDraft({ ...draft, email_enabled: e.target.checked })}
              />
              邮件通知新提醒
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={draft.weekly_report_enabled}
                onChange={(e) => setDraft({ ...draft, weekly_report_enabled: e.target.checked })}
              />
              每周周报邮件
            </label>
          </div>
        </Card>

        <Card className="space-y-2">
          <h2 className="text-sm font-semibold">规则说明</h2>
          <ul className="space-y-2 text-xs">
            {RULES.map((rule) => (
              <li key={rule.key} className="flex gap-2">
                <span className="text-indigo-300 shrink-0 font-medium">{rule.title}</span>
                <span className="text-slate-500">{rule.desc}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function NumberBox({
  label,
  value,
  min,
  max,
  step = 1,
  hint,
  onChange,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block text-xs text-slate-400">
      {label}
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n)) onChange(n);
        }}
        aria-label={label}
        className="mt-1 w-full bg-slate-900/70 border border-slate-700 rounded-[var(--lumi-radius-sm)] px-3 py-1.5 text-sm text-slate-200 outline-none focus:border-indigo-400"
      />
      {hint && <span className="mt-1 block text-slate-600">{hint}</span>}
    </label>
  );
}
