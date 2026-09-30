import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Badge, Button, Card, EmptyState, ErrorState, Spinner } from "../components/ui";
import { AreaChart, BarChart, Donut, HBars } from "../components/charts";
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
  hourly: number[];
  weekday: { label: string; value: number }[];
  duration_buckets: { label: string; value: number }[];
  completion_buckets: { label: string; value: number }[];
  tname_top: { name: string; views: number }[];
  daily_30: { date: string; views: number }[];
  cumulative: { date: string; views: number; total: number }[];
  follow_trend: { month: string; count: number }[];
  top5_share: number;
  never_watched_ratio: number;
  group_completion: { name: string; ratio: number }[];
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

function ChartCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <h2 className="text-sm font-semibold mb-3">{title}</h2>
      {children}
    </Card>
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
    mutationFn: () =>
      api<{ ok: boolean; html: string; fallback: boolean; message: string }>("/weekly-report/ai", { method: "POST" }),
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
          <Button variant="ghost" onClick={() => aiMutation.mutate()} disabled={aiMutation.isPending} aria-label="生成 AI 分析周报">
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

          {/* 12 张图表：2 张由原数据换用新组件重绘，10 张为新增 */}
          <div className="grid gap-3 md:grid-cols-2">
            <ChartCard title={`每日观看（近 ${stats.days} 天）`}>
              <BarChart points={stats.daily.map((d) => ({ label: d.date.slice(5), value: d.views }))} />
            </ChartCard>
            <ChartCard title="近 30 天累计观看">
              <AreaChart points={stats.cumulative.map((d) => ({ label: d.date.slice(5), value: d.total }))} />
            </ChartCard>
            <ChartCard title="观看时段分布（UTC+8）">
              <BarChart
                points={stats.hourly.map((v, h) => ({ label: h % 3 === 0 ? `${h}时` : "", value: v }))}
                height={160}
              />
            </ChartCard>
            <ChartCard title="星期分布">
              <BarChart points={stats.weekday} />
            </ChartCard>
            <ChartCard title="视频时长分布">
              <HBars points={stats.duration_buckets} unit=" 次" />
            </ChartCard>
            <ChartCard title="观看完成率分布">
              <HBars points={stats.completion_buckets} unit=" 次" />
            </ChartCard>
            <ChartCard title="内容分区 TOP（B站分区）">
              <HBars points={stats.tname_top.map((t) => ({ label: t.name, value: t.views }))} />
            </ChartCard>
            <ChartCard title="本地分组偏好">
              <HBars points={stats.by_group.map((g) => ({ label: g.name, value: g.views }))} />
            </ChartCard>
            <ChartCard title="TOP5 UP 观看集中度">
              <Donut
                segments={[
                  { label: "TOP5 UP", value: Math.round(stats.top5_share * 100) },
                  { label: "其余", value: 100 - Math.round(stats.top5_share * 100) },
                ]}
                centerValue={`${Math.round(stats.top5_share * 100)}%`}
                centerLabel="TOP5 占比"
              />
            </ChartCard>
            <ChartCard title="关注后从未观看占比（30 天前关注）">
              <Donut
                segments={[
                  { label: "从未观看", value: Math.round(stats.never_watched_ratio * 100) },
                  { label: "已观看", value: 100 - Math.round(stats.never_watched_ratio * 100) },
                ]}
                centerValue={`${Math.round(stats.never_watched_ratio * 100)}%`}
                centerLabel="从未观看"
              />
            </ChartCard>
            <ChartCard title="分组平均完成率">
              <HBars
                points={stats.group_completion.map((g) => ({ label: g.name, value: Math.round(g.ratio * 100) }))}
                unit="%"
              />
            </ChartCard>
            <ChartCard title="关注增长趋势（按月）">
              <BarChart points={stats.follow_trend.map((f) => ({ label: f.month.slice(2), value: f.count }))} />
            </ChartCard>
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
