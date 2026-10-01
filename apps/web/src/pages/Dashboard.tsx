import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Button, Card, ErrorState, Spinner } from "../components/ui";
import { BiliAccountCard } from "../components/bili";
import { NativeSyncCard } from "../components/dashboard/NativeSyncCard";
import { relativeTime } from "../components/followings/helpers";

interface SystemStats {
  total_ups: number;
  grouped_ups: number;
  ungrouped_ups: number;
  missing_ups: number;
  groups: number;
  open_reminders: number;
  pending_suggestions: number;
  videos_tracked: number;
  last_sync: string | null;
  login_status: string;
}

const LOGIN_BADGE: Record<string, { label: string; tone: "ok" | "warn" | "danger" }> = {
  active: { label: "已登录", tone: "ok" },
  none: { label: "未登录", tone: "danger" },
  expired: { label: "登录过期", tone: "warn" },
  risk: { label: "风控受限", tone: "warn" },
};

export default function Dashboard() {
  const { demoMode } = useAuth();
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["system-stats"],
    queryFn: () => api<SystemStats>("/system/stats"),
  });

  // The sync endpoint returns a run id immediately and works in the background;
  // poll the run until it settles so the button reflects real progress.
  const [runId, setRunId] = useState<number | null>(null);
  const [syncNote, setSyncNote] = useState<{ ok: boolean; text: string } | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (runId == null) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const runs = await api<Array<{ id: number; status: string; error: string | null }>>(
          "/bilibili/sync/runs",
          { query: { limit: 5 } },
        );
        if (cancelled) return;
        const mine = runs.find((r) => r.id === runId);
        if (!mine) return;
        if (mine.status === "success") {
          setSyncNote({ ok: true, text: "同步完成（关注与观看历史已更新；B 站原生分组推送需在下方单独执行）" });
          setRunId(null);
          void queryClient.invalidateQueries();
        } else if (mine.status === "failed") {
          setSyncNote({ ok: false, text: `同步失败：${mine.error ?? "未知错误"}` });
          setRunId(null);
        }
      } catch {
        /* transient poll error: keep waiting */
      }
      if (!cancelled && runId != null) {
        timerRef.current = window.setTimeout(() => void poll(), 3000);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, [runId, queryClient]);

  const syncMutation = useMutation({
    mutationFn: () =>
      api<{ id: number; status: string }>("/bilibili/sync/run", { method: "POST", body: { kind: "full" } }),
    onSuccess: (res) => setRunId(res.id),
    onError: () => setRunId(null),
  });
  const syncing = syncMutation.isPending || runId != null;

  const loginBadge = data ? (LOGIN_BADGE[data.login_status] ?? { label: data.login_status, tone: "warn" as const }) : null;

  const statCards = data
    ? [
        { label: "总 UP 数", value: String(data.total_ups), hint: `已分组 ${data.grouped_ups}`, to: "/followings" },
        { label: "未分组", value: String(data.ungrouped_ups), hint: "待整理", to: "/followings" },
        { label: "断更 UP", value: String(data.missing_ups), hint: "含已取关", to: "/followings" },
        { label: "本地分组", value: String(data.groups), hint: "自定义分组", to: "/groups" },
        { label: "待审建议", value: String(data.pending_suggestions), hint: "AI 分组建议", to: "/review" },
        { label: "开放提醒", value: String(data.open_reminders), hint: "待处理", to: "/reminders" },
        { label: "追踪视频", value: String(data.videos_tracked), hint: "投稿记录", to: "/history" },
        { label: "最近同步", value: relativeTime(data.last_sync), hint: data.last_sync ? "成功同步" : "从未同步" },
      ]
    : [];

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">仪表盘</h1>
        {demoMode && <Badge tone="warn">演示模式</Badge>}
        {loginBadge && <Badge tone={loginBadge.tone}>B 站{loginBadge.label}</Badge>}
        <div className="ml-auto flex items-center gap-2">
          {syncNote && !syncing && (
            <span className={`text-xs ${syncNote.ok ? "text-emerald-300" : "text-red-400"}`} role="status">
              {syncNote.text}
            </span>
          )}
          {syncing && (
            <span className="text-xs text-slate-400" role="status">
              正在同步关注列表与观看历史…
            </span>
          )}
          <Button
            variant="primary"
            onClick={() => {
              setSyncNote(null);
              syncMutation.mutate();
            }}
            disabled={syncing}
            aria-label="立即执行完整同步"
          >
            {syncing && (
              <span
                aria-hidden="true"
                className="inline-block h-3.5 w-3.5 mr-1.5 rounded-full border-2 border-white/70 border-t-transparent animate-spin align-[-2px]"
              />
            )}
            {syncing ? "同步中…" : "立即同步"}
          </Button>
        </div>
      </header>

      {isLoading && <Spinner label="正在加载统计数据…" />}
      {error && <ErrorState message={error instanceof Error ? error.message : String(error)} />}

      {data && (
        <section aria-label="统计概览" className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {statCards.map((card) => {
            const body = (
              <Card className="h-full transition-colors hover:border-indigo-400/50">
                <p className="text-xs text-slate-500">{card.label}</p>
                <p className="text-2xl font-bold mt-1 tabular-nums">{card.value}</p>
                {card.hint && <p className="text-xs text-slate-500 mt-1">{card.hint}</p>}
              </Card>
            );
            return card.to ? (
              <Link key={card.label} to={card.to} className="block" aria-label={`${card.label}：${card.value}，前往查看`}>
                {body}
              </Link>
            ) : (
              <div key={card.label}>{body}</div>
            );
          })}
        </section>
      )}

      <section aria-label="快捷操作" className="grid gap-3 md:grid-cols-2">
        <BiliAccountCard />
        <Card>
          <h2 className="text-sm font-semibold">快捷操作</h2>
          <ul className="mt-2 space-y-1.5 text-sm">
            <li>
              <Link to="/followings" className="text-indigo-300 hover:text-indigo-200" aria-label="前往关注管理">
                → 整理未分组与断更 UP
              </Link>
            </li>
            <li>
              <Link to="/review" className="text-indigo-300 hover:text-indigo-200" aria-label="前往 AI 审核">
                → 审核 AI 分组建议
              </Link>
            </li>
            <li>
              <Link to="/groups" className="text-indigo-300 hover:text-indigo-200" aria-label="前往本地分组">
                → 管理本地分组
              </Link>
            </li>
          </ul>
        </Card>
        <NativeSyncCard />
      </section>
    </div>
  );
}
