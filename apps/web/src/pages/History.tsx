import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Card, EmptyState, ErrorState, Spinner } from "../components/ui";
import { formatDate, relativeTime } from "../components/followings/helpers";

interface DailyCount {
  day: string;
  views: number;
}

interface HistorySummary {
  total_entries: number;
  entries_30d: number;
  distinct_ups_watched: number;
  top_watched: { mid: number; uname: string; views: number }[];
  daily_counts: DailyCount[];
  never_watched_count: number;
}

interface HistoryEntry {
  bvid: string;
  up_mid: number | null;
  up_uname: string | null;
  title: string;
  view_at: string;
  progress: number | null;
}

const PAGE_SIZE = 50;

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

function formatProgress(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 0) return "已看完";
  if (seconds < 60) return `${seconds} 秒`;
  return `${Math.round(seconds / 60)} 分钟`;
}

/** 30 天观看柱状图：纯 div/flex 实现，高度按最大值归一，hover/聚焦显示数值。 */
function DailyChart({ data }: { data: DailyCount[] }) {
  const max = Math.max(0, ...data.map((d) => d.views));
  return (
    <div className="surface p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">近 30 天观看趋势</h2>
        <span className="text-xs text-slate-500">峰值 {max} 条 / 天</span>
      </div>
      {max === 0 ? (
        <EmptyState title="近 30 天暂无观看记录" hint="开启观看历史同步后，这里会展示每日观看趋势" />
      ) : (
        <div className="mt-4 flex items-end gap-[3px] h-36" role="img" aria-label="近 30 天每日观看记录柱状图">
          {data.map((d) => {
            const pct = Math.round((d.views / max) * 100);
            const label = `${d.day}：${d.views} 条`;
            return (
              <div key={d.day} className="group relative flex-1 h-full flex items-end min-w-[4px]">
                <div
                  className={`w-full rounded-t-sm transition-colors ${d.views > 0 ? "bg-indigo-500/70 group-hover:bg-indigo-400" : "bg-slate-700/40"}`}
                  style={{ height: `${d.views > 0 ? Math.max(pct, 4) : 2}%` }}
                />
                <span
                  className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block whitespace-nowrap rounded-md bg-slate-800 px-2 py-1 text-[10px] text-slate-200 border border-slate-700 z-10"
                  role="presentation"
                >
                  {label}
                </span>
                <span className="sr-only">{label}</span>
              </div>
            );
          })}
        </div>
      )}
      <div className="mt-1.5 flex justify-between text-[10px] text-slate-600" aria-hidden="true">
        <span>{data[0]?.day ?? ""}</span>
        <span>{data[data.length - 1]?.day ?? ""}</span>
      </div>
    </div>
  );
}

export default function History() {
  const [page, setPage] = useState(1);

  const summaryQuery = useQuery({
    queryKey: ["history", "summary"],
    queryFn: () => api<HistorySummary>("/history/summary"),
  });

  const listQuery = useQuery({
    queryKey: ["history", "list", page],
    queryFn: () => api<{ items: HistoryEntry[]; total: number; page: number; page_size: number }>("/history", { query: { page, page_size: PAGE_SIZE } }),
  });

  const summary = summaryQuery.data;
  const totalPages = Math.max(1, Math.ceil((listQuery.data?.total ?? 0) / PAGE_SIZE));

  const statCards = summary
    ? [
        { label: "近 30 天观看", value: String(summary.entries_30d), hint: "条观看记录" },
        { label: "总记录", value: String(summary.total_entries), hint: "历史累计" },
        { label: "涉及 UP", value: String(summary.distinct_ups_watched), hint: "看过的不同 UP" },
        { label: "从未观看", value: String(summary.never_watched_count), hint: "关注的 UP 中" },
      ]
    : [];

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">观看历史</h1>
        {listQuery.data && <span className="text-xs text-slate-500">共 {listQuery.data.total} 条记录</span>}
      </header>

      {summaryQuery.isLoading && <Spinner label="正在加载统计…" />}
      {summaryQuery.error && <ErrorState message={errText(summaryQuery.error, "加载统计失败")} />}

      {summary && (
        <>
          <section aria-label="观看统计" className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {statCards.map((c) => (
              <Card key={c.label}>
                <p className="text-xs text-slate-500">{c.label}</p>
                <p className="text-2xl font-bold mt-1 tabular-nums">{c.value}</p>
                {c.hint && <p className="text-xs text-slate-500 mt-1">{c.hint}</p>}
              </Card>
            ))}
          </section>

          <DailyChart data={summary.daily_counts ?? []} />

          <Card>
            <h2 className="text-sm font-semibold">观看最多的 UP（Top 10）</h2>
            {summary.top_watched.length === 0 ? (
              <EmptyState title="还没有观看数据" hint="同步观看历史后即可看到排行" />
            ) : (
              <ol className="mt-3 space-y-1.5" aria-label="观看最多的 UP 排行">
                {summary.top_watched.map((t, i) => (
                  <li key={t.mid} className="flex items-center gap-3 text-sm">
                    <span
                      className={`w-6 text-center text-xs rounded-md py-0.5 tabular-nums ${
                        i < 3 ? "bg-indigo-500/20 text-indigo-300" : "bg-slate-800 text-slate-400"
                      }`}
                    >
                      {i + 1}
                    </span>
                    <span className="truncate font-medium">{t.uname}</span>
                    <span className="ml-auto text-xs text-slate-500 tabular-nums">{t.views} 次</span>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </>
      )}

      <section aria-label="观看明细" className="space-y-2">
        <h2 className="text-sm font-semibold">观看明细</h2>
        {listQuery.isLoading && <Spinner label="正在加载明细…" />}
        {listQuery.error && <ErrorState message={errText(listQuery.error, "加载明细失败")} />}
        {listQuery.data && (
          <div className="surface overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[640px]">
                <caption className="sr-only">观看历史明细</caption>
                <thead>
                  <tr className="text-left text-xs text-slate-400 border-b border-slate-700/60">
                    <th scope="col" className="px-3 py-2">标题</th>
                    <th scope="col" className="px-3 py-2">UP 主</th>
                    <th scope="col" className="px-3 py-2">观看时间</th>
                    <th scope="col" className="px-3 py-2">观看进度</th>
                  </tr>
                </thead>
                <tbody>
                  {listQuery.data.items.length === 0 && (
                    <tr>
                      <td colSpan={4}>
                        <EmptyState title="暂无观看记录" hint="在设置中开启观看历史同步后，这里会展示明细" />
                      </td>
                    </tr>
                  )}
                  {listQuery.data.items.map((e, idx) => (
                    <tr key={`${idx}-${e.bvid}-${e.view_at}`} className="border-b border-slate-800/60 hover:bg-white/[0.03]">
                      <td className="px-3 py-2 max-w-[380px]">
                        <p className="truncate" title={e.title}>
                          {e.title || "（无标题）"}
                        </p>
                        <a
                          href={`https://www.bilibili.com/video/${e.bvid}`}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs text-slate-500 hover:text-indigo-300"
                          aria-label={`在 B 站打开 ${e.title || e.bvid}`}
                        >
                          {e.bvid}
                        </a>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">{e.up_uname ?? <span className="text-slate-500">—</span>}</td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <span title={formatDate(e.view_at)}>{relativeTime(e.view_at)}</span>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-slate-300">{formatProgress(e.progress)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between px-3 py-2 border-t border-slate-700/60 text-xs text-slate-400">
              <span>
                共 {listQuery.data.total} 条 · 第 {page} / {totalPages} 页
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  aria-label="上一页"
                  className="px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40"
                >
                  上一页
                </button>
                <button
                  type="button"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                  aria-label="下一页"
                  className="px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40"
                >
                  下一页
                </button>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
