import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Badge, Button, Card, EmptyState, ErrorState, Spinner } from "../components/ui";
import { formatDate, relativeTime } from "../components/followings/helpers";

interface ReportPayload {
  generated_at: string | null;
  html: string | null;
}

interface StatsPayload {
  days: number;
  views: number;
  watch_seconds: number;
  avg_video_seconds: number;
  new_videos: number;
  daily: { date: string; views: number; seconds: number }[];
  by_group: { name: string; views: number; seconds: number }[];
  top_ups: { uname: string; views: number; seconds: number }[];
}

function humanDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  if (hours > 0) return `${hours} 小时 ${minutes % 60} 分钟`;
  if (minutes > 0) return `${minutes} 分钟`;
  return `${seconds} 秒`;
}

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

/** Minimal inline SVG bar chart — no chart library, no extra bundle weight. */
function DailyBars({ daily }: { daily: StatsPayload["daily"] }) {
  if (!daily.length) return <p className="text-xs text-slate-500">本窗口暂无观看记录</p>;
  const max = Math.max(...daily.map((d) => d.views), 1);
  const width = Math.max(280, daily.length * 44);
  const height = 120;
  const barW = 24;
  const gap = (width - daily.length * barW) / (daily.length + 1);
  return (
    <svg role="img" aria-label="每日观看次数柱状图" className="w-full max-w-full" viewBox={`0 0 ${width} ${height}`}>
      {daily.map((d, i) => {
        const h = Math.max(3, (d.views / max) * (height - 36));
        const x = gap + i * (barW + gap);
        return (
          <g key={d.date}>
            <rect x={x} y={height - 20 - h} width={barW} height={h} rx={4} fill="url(#weekly-grad)" />
            <text x={x + barW / 2} y={height - 24 - h} textAnchor="middle" className="fill-slate-400" fontSize="10">
              {d.views}
            </text>
            <text x={x + barW / 2} y={height - 6} textAnchor="middle" className="fill-slate-500" fontSize="10">
              {d.date.slice(5)}
            </text>
          </g>
        );
      })}
      <defs>
        <linearGradient id="weekly-grad" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0%" stopColor="#ff2f7e" />
          <stop offset="100%" stopColor="#ff8ac2" />
        </linearGradient>
      </defs>
    </svg>
  );
}

export default function WeeklyReport() {
  const queryClient = useQueryClient();
  const [preview, setPreview] = useState<ReportPayload | null>(null);
  const [aiPreview, setAiPreview] = useState<ReportPayload | null>(null);
  const [sendResult, setSendResult] = useState<{ ok: boolean; message: string } | null>(null);

  const latestQuery = useQuery({
    queryKey: ["weekly-report"],
    queryFn: () => api<ReportPayload>("/weekly-report"),
  });

  const statsQuery = useQuery({
    queryKey: ["weekly-report", "stats"],
    queryFn: () => api<StatsPayload>("/weekly-report/stats", { query: { days: 7 } }),
  });

  const previewMutation = useMutation({
    mutationFn: () => api<ReportPayload>("/weekly-report/preview", { method: "POST" }),
    onSuccess: (res) => {
      setPreview(res);
      setAiPreview(null);
      void queryClient.invalidateQueries({ queryKey: ["weekly-report"] });
    },
  });

  const aiMutation = useMutation({
    mutationFn: () => api<{ ok: boolean; html: string; fallback: boolean; message: string }>("/weekly-report/ai", { method: "POST" }),
    onSuccess: (res) => {
      setAiPreview({ generated_at: null, html: res.html });
      setPreview(null);
      setSendResult({ ok: !res.fallback, message: res.message });
    },
  });

  const sendMutation = useMutation({
    mutationFn: () => api<{ ok: boolean; message?: string }>("/weekly-report/send", { method: "POST" }),
    onSuccess: (res) => {
      setSendResult({ ok: res.ok !== false, message: res.message ?? (res.ok !== false ? "周报已发送" : "发送失败") });
      void queryClient.invalidateQueries({ queryKey: ["weekly-report"] });
    },
    onError: (err) => setSendResult({ ok: false, message: errText(err, "发送失败，请稍后重试") }),
  });

  const latest = latestQuery.data;
  const stats = statsQuery.data;
  const shown: ReportPayload | null = aiPreview ?? preview ?? (latest?.html ? latest : null);
  const isPreview = aiPreview != null || preview != null;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">每周周报</h1>
        {shown?.generated_at && (
          <span className="text-xs text-slate-500" title={formatDate(shown.generated_at)}>
            {aiPreview ? "AI 分析 · " : isPreview ? "预览生成于 " : "上次生成 "}
            {relativeTime(shown.generated_at ?? "")}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {(previewMutation.isError || sendMutation.isError || aiMutation.isError) && (
            <span className="text-xs text-red-400" role="alert">
              {errText(previewMutation.error ?? sendMutation.error ?? aiMutation.error, "操作失败")}
            </span>
          )}
          <Button
            variant="ghost"
            onClick={() => aiMutation.mutate()}
            disabled={aiMutation.isPending}
            aria-label="生成 AI 分析周报"
          >
            {aiMutation.isPending ? "AI 分析中…" : "AI 分析"}
          </Button>
          <Button
            variant="ghost"
            onClick={() => previewMutation.mutate()}
            disabled={previewMutation.isPending}
            aria-label="生成周报预览"
          >
            {previewMutation.isPending ? "生成中…" : "生成预览"}
          </Button>
          <Button
            variant="primary"
            onClick={() => sendMutation.mutate()}
            disabled={sendMutation.isPending}
            aria-label="立即发送周报邮件"
          >
            {sendMutation.isPending ? "发送中…" : "立即发送"}
          </Button>
        </div>
      </header>

      {latestQuery.isLoading && <Spinner label="正在加载最新周报…" />}
      {latestQuery.error && <ErrorState message={errText(latestQuery.error, "加载周报失败")} />}

      {sendResult && (
        <p
          className={`text-xs px-3 py-2 rounded-lg ${sendResult.ok ? "text-emerald-300 bg-emerald-500/10" : "text-red-300 bg-red-500/10"}`}
          role="status"
          aria-live="polite"
        >
          {sendResult.message}
          <button
            type="button"
            onClick={() => setSendResult(null)}
            aria-label="关闭提示"
            className="ml-2 underline underline-offset-2 hover:text-white"
          >
            关闭
          </button>
        </p>
      )}

      {stats && (
        <section aria-label="观看统计" className="space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Card>
              <p className="text-xs text-slate-500">观看次数</p>
              <p className="text-2xl font-bold mt-1 tabular-nums">{stats.views}</p>
            </Card>
            <Card>
              <p className="text-xs text-slate-500">观看时长</p>
              <p className="text-2xl font-bold mt-1 tabular-nums">{humanDuration(stats.watch_seconds)}</p>
            </Card>
            <Card>
              <p className="text-xs text-slate-500">平均单视频</p>
              <p className="text-2xl font-bold mt-1 tabular-nums">{humanDuration(stats.avg_video_seconds)}</p>
            </Card>
            <Card>
              <p className="text-xs text-slate-500">新增投稿</p>
              <p className="text-2xl font-bold mt-1 tabular-nums">{stats.new_videos}</p>
            </Card>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <Card>
              <h2 className="text-sm font-semibold mb-2">每日观看（近 {stats.days} 天）</h2>
              <DailyBars daily={stats.daily} />
            </Card>
            <Card>
              <h2 className="text-sm font-semibold mb-2">分组偏好</h2>
              {stats.by_group.length ? (
                <ul className="space-y-1.5 text-sm">
                  {stats.by_group.map((g) => (
                    <li key={g.name} className="flex items-center gap-2">
                      <span className="w-24 shrink-0 truncate text-slate-300">{g.name}</span>
                      <span className="flex-1 h-2 rounded-full bg-slate-800 overflow-hidden" aria-hidden="true">
                        <span
                          className="block h-full rounded-full btn-grad"
                          style={{ width: `${Math.max(4, (g.views / Math.max(...stats.by_group.map((x) => x.views), 1)) * 100)}%` }}
                        />
                      </span>
                      <span className="text-xs text-slate-500 tabular-nums w-20 text-right">
                        {g.views} 次 · {humanDuration(g.seconds)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-slate-500">暂无分组观看数据</p>
              )}
              {stats.top_ups.length > 0 && (
                <>
                  <h3 className="text-sm font-semibold mt-4 mb-1">最常看的 UP</h3>
                  <p className="text-xs text-slate-400">
                    {stats.top_ups.map((up) => `${up.uname}（${up.views}）`).join("、")}
                  </p>
                </>
              )}
            </Card>
          </div>
        </section>
      )}

      {shown?.html ? (
        <section aria-label="周报内容" className="space-y-2">
          {isPreview && (
            <Badge tone="info">
              {aiPreview ? "AI 分析（不写入存档）" : "预览（尚未存为最新报告，点「立即发送」生成并发送）"}
            </Badge>
          )}
          <div className="surface p-2">
            <iframe
              title="周报内容预览"
              srcDoc={shown.html}
              sandbox="allow-same-origin"
              className="w-full h-[560px] rounded-lg bg-white"
            />
          </div>
        </section>
      ) : (
        !latestQuery.isLoading &&
        !latestQuery.error && (
          <EmptyState title="还没有生成过周报" hint="点击「生成预览」查看本周观看总结，或配置 SMTP 后「立即发送」到邮箱" />
        )
      )}
    </div>
  );
}
