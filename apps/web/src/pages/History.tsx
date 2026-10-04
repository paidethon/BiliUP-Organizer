import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, historyApi, type HistoryItem } from "../api";
import { Badge, Card, EmptyState, ErrorState, Input, Select, Spinner } from "../components/ui";
import { ChartCard } from "../components/charts/ChartCard";
import { dailyBarOption, hBarOption } from "../components/charts/options";
import { formatDateTimeShanghai, humanDuration, relativeTime } from "../lib/time";

const PAGE_SIZE = 50;

function errText(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

function formatProgress(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 0) return "已看完";
  if (seconds < 60) return `${seconds} 秒`;
  return `${Math.round(seconds / 60)} 分钟`;
}

export default function History() {
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const [topLimit, setTopLimit] = useState(10);

  const filters = {
    start: params.get("start") || undefined,
    end: params.get("end") || undefined,
    group_id: params.get("group_id") ? Number(params.get("group_id")) : undefined,
    up_mid: params.get("up_mid") ? Number(params.get("up_mid")) : undefined,
    q: params.get("q") || undefined,
    hour: params.get("hour") ? Number(params.get("hour")) : undefined,
  };

  const setFilter = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) next.delete(k);
      else next.set(k, v);
    }
    setParams(next, { replace: false });
    setPage(1);
  };

  const groups = useQuery({
    queryKey: ["groups"],
    queryFn: () => api<{ groups: Array<{ id: number; name: string }> }>("/groups"),
  });

  const summary = useQuery({
    queryKey: ["history", "summary", filters.start, filters.end, filters.group_id, filters.up_mid],
    queryFn: () =>
      historyApi.summary({
        start: filters.start,
        end: filters.end,
        group_id: filters.group_id,
        up_mid: filters.up_mid,
        limit: 20,
      }),
  });

  const list = useQuery({
    queryKey: ["history", "list", page, filters],
    queryFn: () => historyApi.list({ page, page_size: PAGE_SIZE, ...filters }),
  });

  const topUps = summary.data?.top_watched ?? [];
  const shownTop = topLimit === 0 ? topUps : topUps.slice(0, topLimit);
  const hasFilters = Object.values(filters).some((v) => v !== undefined);

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-bold">观看历史</h1>

      {/* -------- filters (real server-side predicates, written to URL) -------- */}
      <Card className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          开始日期（上海）
          <Input
            type="date"
            value={filters.start ?? ""}
            onChange={(e) => setFilter({ start: e.target.value || undefined })}
            className="w-40"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          结束日期（含当日，上海）
          <Input
            type="date"
            value={filters.end ? endDateInput(filters.end) : ""}
            onChange={(e) => {
              const v = e.target.value;
              setFilter({ end: v ? nextDay(v) : undefined });
            }}
            className="w-40"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          分组
          <Select
            value={filters.group_id ?? ""}
            onChange={(e) => setFilter({ group_id: e.target.value || undefined })}
            className="w-36"
          >
            <option value="">全部分组</option>
            {(groups.data?.groups ?? []).map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </Select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          搜索（标题/UP/BV号）
          <Input
            value={filters.q ?? ""}
            onChange={(e) => setFilter({ q: e.target.value || undefined })}
            placeholder="回车或失焦生效"
            className="w-52"
            onBlur={(e) => setFilter({ q: e.target.value || undefined })}
          />
        </label>
        {hasFilters && (
          <button
            type="button"
            className="px-2 py-1.5 text-xs rounded-md border border-slate-700 text-slate-300 hover:bg-white/5"
            onClick={() => setParams(new URLSearchParams(), { replace: false })}
          >
            清除筛选
          </button>
        )}
      </Card>

      {summary.isLoading ? (
        <Spinner />
      ) : summary.isError ? (
        <ErrorState message={errText(summary.error, "加载失败")} />
      ) : (
        summary.data && (
          <>
            {/* -------- stat cards (clickable into filtered detail) -------- */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <StatCard
                label="区间观看记录"
                value={String(summary.data.entries_30d)}
                hint={filters.start ? "当前筛选范围" : "近 30 天（上海）"}
                onClick={() => undefined}
              />
              <StatCard label="去重 UP" value={String(summary.data.distinct_ups_watched)} hint="按 mid 去重" />
              <StatCard label="去重视频" value={String(summary.data.distinct_videos)} hint="按 bvid 去重" />
              <StatCard
                label="估算观看时长"
                value={humanDuration(summary.data.watch_seconds_est)}
                hint="按记录进度估算"
              />
              <StatCard
                label="未发现观看记录"
                value={String(summary.data.never_watched_count)}
                hint="已同步范围内未发现，非终身判断"
              />
            </div>
            <p className="text-xs text-slate-500 px-1">
              {summary.data.coverage.note}
              {summary.data.coverage.history_truncated && " · 上次同步因页数上限未完整覆盖"}
              {" "}· 有效样本 {summary.data.samples.valid}，下界样本 {summary.data.samples.bound}，未知 {summary.data.samples.unknown}
              {" "}· 总记录 {summary.data.total_entries} 条（含区间外）
            </p>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <ChartCard
                title="每日观看"
                metric="记录数（Asia/Shanghai 日界）"
                hint="点击柱形查看当天明细"
                optionFactory={(theme) => dailyBarOption(theme, summary.data!.daily_counts.map((d) => ({ date: d.day, views: d.views, covered: d.covered })))}
                onPointClick={(p) => {
                  const day = summary.data!.daily_counts[p.dataIndex]?.day;
                  if (day) setFilter({ start: day, end: nextDay(day) });
                }}
                table={{
                  columns: [{ label: "日期" }, { label: "记录数", align: "right" }],
                  rows: summary.data.daily_counts.map((d) => [d.day, d.views]),
                }}
                height={240}
              />
              <ChartCard
                title="TOP UP 排行"
                metric="按记录数排序；不可解析的昵称显示 UID（不再显示错误名字）"
                optionFactory={(theme) =>
                  hBarOption(
                    theme,
                    shownTop.map((u) => ({
                      name: u.uname ?? `昵称暂不可用（UID ${u.mid}）`,
                      value: u.views,
                    })),
                    "条"
                  )
                }
                onPointClick={(p) => {
                  const up = shownTop[p.dataIndex];
                  if (up) setFilter({ up_mid: String(up.mid) });
                }}
                actions={
                  <Select
                    aria-label="显示数量"
                    value={String(topLimit)}
                    onChange={(e) => setTopLimit(Number(e.target.value))}
                  >
                    <option value="10">Top 10</option>
                    <option value="20">Top 20</option>
                    <option value="0">全部</option>
                  </Select>
                }
                table={{
                  columns: [{ label: "UP" }, { label: "记录数", align: "right" }, { label: "UID" }],
                  rows: topUps.map((u) => [u.uname ?? "昵称暂不可用", u.views, u.mid]),
                }}
              />
            </div>
          </>
        )
      )}

      {/* -------- detail list -------- */}
      {filters.up_mid && (
        <p className="text-xs text-slate-400 px-1">
          <Badge tone="info">筛选：UP mid={filters.up_mid}</Badge>{" "}
          <button className="underline" onClick={() => setFilter({ up_mid: undefined })}>
            移除
          </button>
        </p>
      )}
      {list.isLoading ? (
        <Spinner />
      ) : list.isError ? (
        <ErrorState message={errText(list.error, "加载失败")} />
      ) : list.data && list.data.items.length === 0 ? (
        <EmptyState title="当前筛选范围内没有观看记录" hint="已同步范围内未发现，不代表从未观看。" />
      ) : list.data ? (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-400 border-b border-slate-700/60">
                  <th scope="col" className="py-2 px-2">标题</th>
                  <th scope="col" className="py-2 px-2">UP</th>
                  <th scope="col" className="py-2 px-2">观看时间（上海）</th>
                  <th scope="col" className="py-2 px-2">进度</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((item: HistoryItem, i) => (
                  <tr key={`${item.bvid}-${item.view_at}-${i}`} className="border-b border-slate-800/60">
                    <td className="py-2 px-2 max-w-[380px]">
                      <a
                        href={`https://www.bilibili.com/video/${item.bvid}`}
                        target="_blank"
                        rel="noreferrer"
                        className="hover:text-indigo-300 line-clamp-1"
                      >
                        {item.title || item.bvid}
                      </a>
                    </td>
                    <td className="py-2 px-2 whitespace-nowrap">
                      {item.up_uname ?? (item.up_mid ? `UID ${item.up_mid}` : "—")}
                    </td>
                    <td className="py-2 px-2 whitespace-nowrap tabular-nums" title={relativeTime(item.view_at)}>
                      {formatDateTimeShanghai(item.view_at_shanghai ?? item.view_at)}
                    </td>
                    <td className="py-2 px-2 whitespace-nowrap">
                      {formatProgress(item.progress)}
                      {item.duration_seconds ? (
                        <span className="text-slate-500 text-xs"> / {Math.round(item.duration_seconds / 60)} 分</span>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between mt-3 text-sm">
            <span className="text-slate-400">
              共 {list.data.total} 条 · 第 {page} / {Math.max(1, Math.ceil(list.data.total / PAGE_SIZE))} 页
            </span>
            <span className="flex gap-2">
              <button
                className="px-3 py-1 rounded-md border border-slate-700 disabled:opacity-40"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                上一页
              </button>
              <button
                className="px-3 py-1 rounded-md border border-slate-700 disabled:opacity-40"
                disabled={page >= Math.ceil(list.data.total / PAGE_SIZE)}
                onClick={() => setPage((p) => p + 1)}
              >
                下一页
              </button>
            </span>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

function StatCard({
  label,
  value,
  hint,
  onClick,
}: {
  label: string;
  value: string;
  hint?: string;
  onClick?: () => void;
}) {
  return (
    <Card className={onClick ? "cursor-pointer" : ""}>
      <div className="text-xl font-bold tabular-nums">{value}</div>
      <div className="text-xs text-slate-400 mt-1">{label}</div>
      {hint && <div className="text-[11px] text-slate-500 mt-0.5">{hint}</div>}
    </Card>
  );
}

/** end filter is exclusive; the date input shows the inclusive last day. */
function endDateInput(exclusive: string): string {
  const d = new Date(`${exclusive}T00:00:00`);
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

function nextDay(day: string): string {
  const d = new Date(`${day}T00:00:00`);
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
}
