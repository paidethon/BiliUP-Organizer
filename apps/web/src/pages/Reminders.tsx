import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Reminder } from "../api";
import { Badge, Button, EmptyState, ErrorState, Spinner } from "../components/ui";
import { formatDate, relativeTime } from "../components/followings/helpers";

type ReminderStatus = "open" | "acknowledged" | "all";

const TABS: { key: ReminderStatus; label: string }[] = [
  { key: "open", label: "未读" },
  { key: "acknowledged", label: "已读" },
  { key: "all", label: "全部" },
];

/** 规则键 → 中文名称映射 */
const RULE_NAMES: Record<string, string> = {
  stale_uploader: "断更提醒",
  long_unwatched: "长期未看",
  never_watched: "从未观看",
  important_unwatched: "重要 UP 未看",
  low_confidence: "低置信度",
  login_expired: "登录失效",
  sync_failed: "同步失败",
  risk_control: "风控告警",
  lumirss_failure: "LumiRSS 失败",
  ai_failed: "AI 失败",
};

const SEVERITY: Record<Reminder["severity"], { border: string; badge: "danger" | "warn" | "info"; label: string }> = {
  critical: { border: "border-l-red-500", badge: "danger", label: "严重" },
  warning: { border: "border-l-amber-400", badge: "warn", label: "警告" },
  info: { border: "border-l-indigo-400", badge: "info", label: "提示" },
};

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

export default function Reminders() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<ReminderStatus>("open");
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const listQuery = useQuery({
    queryKey: ["reminders", tab],
    queryFn: () => api<Reminder[]>("/reminders", { query: { status: tab, page_size: 200 } }),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["reminders"] });
    void queryClient.invalidateQueries({ queryKey: ["system-stats"] });
  };

  const ackAllMutation = useMutation({
    mutationFn: () => api<{ ok: boolean; acknowledged: number }>("/reminders/ack-all", { method: "POST" }),
    onSuccess: (res) => {
      setNotice({ tone: "ok", text: `已全部标记已读（${res.acknowledged} 条）` });
      invalidate();
    },
    onError: (err) => setNotice({ tone: "error", text: `操作失败：${errText(err, "请稍后重试")}` }),
  });

  const scanMutation = useMutation({
    mutationFn: () => api<{ created: number; resolved: number }>("/reminders/scan", { method: "POST" }),
    onSuccess: (res) => {
      setNotice({ tone: "ok", text: `扫描完成：新增 ${res.created} 条提醒，自动解决 ${res.resolved} 条` });
      invalidate();
    },
    onError: (err) => setNotice({ tone: "error", text: `扫描失败：${errText(err, "请稍后重试")}` }),
  });

  const ackMutation = useMutation({
    mutationFn: (id: number) => api<{ ok: boolean }>(`/reminders/${id}/ack`, { method: "POST" }),
    onSuccess: () => {
      setNotice({ tone: "ok", text: "已标记为已读" });
      invalidate();
    },
    onError: (err) => setNotice({ tone: "error", text: `操作失败：${errText(err, "请稍后重试")}` }),
  });

  const items = listQuery.data ?? [];
  const busy = ackAllMutation.isPending || scanMutation.isPending || ackMutation.isPending;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">提醒中心</h1>
        {listQuery.data && <span className="text-xs text-slate-500">当前视图 {items.length} 条</span>}
        <div className="ml-auto flex items-center gap-2">
          {(ackAllMutation.isError || scanMutation.isError || ackMutation.isError) && (
            <span className="text-xs text-red-400" role="alert">
              {errText(ackAllMutation.error ?? scanMutation.error ?? ackMutation.error, "操作失败")}
            </span>
          )}
          <Button variant="ghost" onClick={() => scanMutation.mutate()} disabled={scanMutation.isPending} aria-label="立即扫描提醒规则">
            {scanMutation.isPending ? "扫描中…" : "立即扫描"}
          </Button>
          <Button variant="primary" onClick={() => ackAllMutation.mutate()} disabled={ackAllMutation.isPending} aria-label="全部标记已读">
            {ackAllMutation.isPending ? "处理中…" : "全部已读"}
          </Button>
        </div>
      </header>

      <div className="flex items-center gap-2" role="group" aria-label="按状态筛选提醒">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            aria-pressed={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 rounded-full text-xs border transition-colors ${
              tab === t.key ? "border-indigo-400 text-indigo-300 bg-indigo-500/10" : "border-slate-700 text-slate-400 hover:text-white"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {notice && (
        <p
          className={`text-xs px-3 py-2 rounded-lg ${notice.tone === "ok" ? "text-emerald-300 bg-emerald-500/10" : "text-red-300 bg-red-500/10"}`}
          role="status"
          aria-live="polite"
        >
          {notice.text}
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="关闭提示"
            className="ml-2 underline underline-offset-2 hover:text-white"
          >
            关闭
          </button>
        </p>
      )}

      {listQuery.isLoading && <Spinner label="正在加载提醒…" />}
      {listQuery.error && <ErrorState message={errText(listQuery.error, "加载提醒失败")} />}
      {listQuery.data && items.length === 0 && (
        <EmptyState title="没有提醒" hint={tab === "open" ? "一切正常，或点击「立即扫描」检查一遍规则" : "当前状态下暂无记录"} />
      )}

      <ul className="space-y-3" aria-label="提醒列表">
        {items.map((r) => {
          const sev = SEVERITY[r.severity] ?? SEVERITY.info;
          return (
            <li key={r.id}>
              <div className={`surface border-l-4 ${sev.border} p-4 flex flex-wrap items-start gap-3`}>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={sev.badge}>{RULE_NAMES[r.rule_key] ?? r.rule_key}</Badge>
                    <span className="text-xs text-slate-500">{sev.label}</span>
                    <h2 className="text-sm font-medium">{r.title}</h2>
                  </div>
                  {r.body && <p className="mt-1.5 text-xs text-slate-400 whitespace-pre-wrap break-words">{r.body}</p>}
                  <p className="mt-1.5 text-xs text-slate-500" title={formatDate(r.created_at)}>
                    {relativeTime(r.created_at)}
                    {r.status !== "open" && <span className="ml-2 text-slate-600">（已读）</span>}
                  </p>
                </div>
                {r.status === "open" && (
                  <div className="shrink-0">
                    <Button variant="ghost" disabled={busy} onClick={() => ackMutation.mutate(r.id)} aria-label={`标记已读：${r.title}`}>
                      已读
                    </Button>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
