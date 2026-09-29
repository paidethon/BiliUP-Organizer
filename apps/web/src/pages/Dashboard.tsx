import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { Badge, Button, Card, ErrorState, Spinner } from "../components/ui";
import { BiliAccountCard } from "../components/bili";
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

  const syncMutation = useMutation({
    mutationFn: () =>
      api<{ id: number; status: string }>("/bilibili/sync/run", { method: "POST", body: { kind: "full" } }),
    onSuccess: () => queryClient.invalidateQueries(),
  });

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
          {syncMutation.isError && (
            <span className="text-xs text-red-400" role="alert">
              同步失败：{syncMutation.error instanceof ApiError ? syncMutation.error.message : "请稍后重试"}
            </span>
          )}
          <Button
            variant="primary"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            aria-label="立即执行完整同步"
          >
            {syncMutation.isPending && (
              <span
                aria-hidden="true"
                className="inline-block h-3.5 w-3.5 mr-1.5 rounded-full border-2 border-white/70 border-t-transparent animate-spin align-[-2px]"
              />
            )}
            {syncMutation.isPending ? "同步中…" : "立即同步"}
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
      </section>
    </div>
  );
}
