import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Badge, Button, Card, EmptyState, ErrorState, Select, Spinner } from "../components/ui";
import { ChartCard } from "../components/charts/ChartCard";
import {
  compareBarOption,
  cumulativeLineOption,
  dailyBarOption,
  deltaBarOption,
  exploreReturnOption,
  groupCoverageOption,
  hBarOption,
  heatmapOption,
  hourlyBarOption,
  videoCoverageOption,
  weekdayBarOption,
} from "../components/charts/options";
import {
  weeklyApi,
  type RangeStats,
  type WeeklyReportDetail,
  type WeekInfo,
} from "../api";
import {
  WEEKDAY_LABELS,
  addDays,
  formatDateShanghai,
  humanDuration,
  mondayOf,
  relativeTime,
  toISODate,
} from "../lib/time";

type Tab = "overview" | "habit" | "ups" | "advanced";

const TABS: Array<{ key: Tab; label: string }> = [
  { key: "overview", label: "概览" },
  { key: "habit", label: "习惯" },
  { key: "ups", label: "UP 与分组" },
  { key: "advanced", label: "进阶" },
];

export default function WeeklyReport() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "overview");
  const [topUpLimit, setTopUpLimit] = useState(10);
  const [heatMode, setHeatMode] = useState<"views" | "seconds">("views");
  const [dailyMode, setDailyMode] = useState<"daily" | "cumulative">("daily");
  const [message, setMessage] = useState<string | null>(null);

  const dateParam = params.get("date") || undefined;
  const revParam = params.get("rev") || undefined;
  const revId = revParam ? Number(revParam) : undefined;

  const setUrl = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined) next.delete(k);
      else next.set(k, v);
    }
    setParams(next, { replace: false });
  };

  const week = useQuery({
    queryKey: ["weekly-report", "week", dateParam],
    queryFn: () => weeklyApi.week(dateParam),
  });

  const weekStart = week.data?.week_start;
  const weekEnd = week.data?.week_end_exclusive;

  // live stats for the selected week (only when not viewing an archived revision)
  const stats = useQuery({
    queryKey: ["weekly-report", "stats", weekStart, weekEnd],
    queryFn: () => weeklyApi.stats(weekStart!, weekEnd!),
    enabled: Boolean(weekStart && weekEnd) && !revId,
    placeholderData: (prev) => prev, // keep the old week visible while switching
  });

  const archive = useQuery({
    queryKey: ["weekly-report", "archive", revId],
    queryFn: () => weeklyApi.get(revId!),
    enabled: Boolean(revId),
  });

  const archives = useQuery({
    queryKey: ["weekly-report", "archives"],
    queryFn: () => weeklyApi.archives(),
  });

  const shownStats: Partial<RangeStats> | undefined = revId ? archive.data?.stats : stats.data;
  const shownReport: WeeklyReportDetail | undefined = revId ? archive.data : undefined;

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["weekly-report"] });
  };

  const generate = useMutation({
    mutationFn: (save: boolean) => weeklyApi.generate(weekStart!, save),
    onSuccess: (res) => {
      invalidateAll();
      setMessage(res.saved ? `已保存周报 r${res.report.revision}` : "预览已生成（未保存）");
      if (res.saved) setUrl({ rev: String(res.report.id) });
    },
    onError: (e) => setMessage(`生成失败：${e.message}`),
  });

  const regenerate = useMutation({
    mutationFn: (id: number) => weeklyApi.regenerate(id),
    onSuccess: (res) => {
      invalidateAll();
      setMessage(`已创建新修订 r${res.report.revision}，原修订仍可查看`);
      setUrl({ rev: String(res.report.id) });
    },
    onError: (e) => setMessage(`重新生成失败：${e.message}`),
  });

  const send = useMutation({
    mutationFn: (id: number) => weeklyApi.send(id),
    onSuccess: (res) => {
      invalidateAll();
      setMessage(res.message);
    },
    onError: (e) => setMessage(`发送失败：${e.message}`),
  });

  const ai = useMutation({
    mutationFn: (id: number) => weeklyApi.ai(id),
    onSuccess: (res) => {
      invalidateAll();
      setMessage(res.ok ? "AI 解读已生成（不改写统计数字）" : res.message || "AI 未生成");
    },
    onError: (e) => setMessage(`AI 失败：${e.message}`),
  });

  const jumpWeek = (deltaWeeks: number) => {
    const base = weekStart ? new Date(`${weekStart}T00:00:00`) : mondayOf(new Date());
    setUrl({ date: toISODate(addDays(base, deltaWeeks * 7)), rev: undefined });
  };

  const goHistory = (patch: Record<string, string>) => {
    navigate(`/history?${new URLSearchParams(patch).toString()}`);
  };

  if (week.isLoading) return <Spinner />;
  if (week.isError) return <ErrorState message={(week.error as Error).message} />;

  const info: WeekInfo | undefined = week.data;
  const loadingStats = stats.isLoading || (revId !== undefined && archive.isLoading);

  return (
    <div className="flex flex-col gap-4">
      {/* -------- header: week navigation -------- */}
      <Card className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-lg font-bold">周报</h1>
            {info && (
              <p className="text-sm text-slate-400 mt-0.5">
                {info.week_start} ~ {info.week_end_inclusive_label}（周一起始，{info.timezone}）
                {!info.is_complete && (
                  <span className="ml-2">
                    <Badge tone="warn">本周尚未结束</Badge>
                  </span>
                )}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button variant="ghost" onClick={() => jumpWeek(-1)} aria-label="上一周">
              ← 上一周
            </Button>
            <Button variant="ghost" onClick={() => jumpWeek(1)} aria-label="下一周">
              下一周 →
            </Button>
            <Button variant="subtle" onClick={() => setUrl({ date: undefined, rev: undefined })}>
              本周
            </Button>
            <Button variant="subtle" onClick={() => jumpWeek(-1)}>
              上周
            </Button>
            <input
              type="date"
              className="bg-slate-900/70 border border-slate-700 rounded-[var(--lumi-radius-sm)] px-2 py-1.5 text-sm"
              value={info?.week_start ?? ""}
              aria-label="选择日期定位所在周"
              onChange={(e) => e.target.value && setUrl({ date: e.target.value, rev: undefined })}
            />
          </div>
        </div>

        {/* -------- actions -------- */}
        <div className="flex flex-wrap items-center gap-1.5">
          <Button variant="subtle" onClick={() => generate.mutate(false)} disabled={!weekStart || generate.isPending}>
            预览
          </Button>
          <Button onClick={() => generate.mutate(true)} disabled={!weekStart || generate.isPending}>
            生成并保存
          </Button>
          {shownReport && !shownReport.is_legacy && (
            <Button variant="ghost" onClick={() => regenerate.mutate(shownReport.id)} disabled={regenerate.isPending}>
              重新生成（新修订）
            </Button>
          )}
          {shownReport && !shownReport.is_legacy && (
            <Button variant="ghost" onClick={() => send.mutate(shownReport.id)} disabled={send.isPending}>
              发送此修订
            </Button>
          )}
          {shownReport && !shownReport.is_legacy && (
            <Button variant="ghost" onClick={() => ai.mutate(shownReport.id)} disabled={ai.isPending}>
              AI 解读
            </Button>
          )}
          {shownReport && !shownReport.is_legacy && (
            <span className="flex gap-1.5">
              {(["html", "md", "json"] as const).map((fmt) => (
                <a
                  key={fmt}
                  className="px-2 py-1.5 text-sm rounded-[var(--lumi-radius-sm)] border border-slate-700 text-slate-200 hover:bg-white/5"
                  href={weeklyApi.exportUrl(shownReport.id, fmt)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {fmt.toUpperCase()}
                </a>
              ))}
            </span>
          )}
          {archives.data && archives.data.weeks.length > 0 && (
            <Select
              aria-label="查看历史归档"
              value={revParam ?? ""}
              onChange={(e) => {
                const value = e.target.value;
                if (value) {
                  const [period, revision] = value.split("|");
                  setUrl({ date: period, rev: revision });
                } else {
                  setUrl({ rev: undefined });
                }
              }}
            >
              <option value="">实时数据（当前选择周）</option>
              {archives.data.weeks.map((w) => (
                <option key={`${w.period_start}-${w.revision}`} value={`${w.period_start}|${w.revision}`}>
                  {w.period_start} ~ {w.period_end_exclusive}（r{w.revision}）
                </option>
              ))}
            </Select>
          )}
        </div>

        {revId && shownReport && (
          <p className="text-xs text-slate-400">
            正在查看存档修订 r{shownReport.revision}（生成于{" "}
            {formatDateShanghai(shownReport.generated_at_shanghai ?? shownReport.generated_at)}，数据截至{" "}
            {formatDateShanghai(shownReport.data_cutoff)}）——数字为快照冻结值。
            {shownReport.is_legacy && " · 旧版周报（滚动 7 天），无法精确对应自然周。"}
          </p>
        )}
        {message && (
          <p className="text-xs text-indigo-300" role="status" aria-live="polite">
            {message}
          </p>
        )}
      </Card>

      {/* -------- stat cards -------- */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard
          label="观看记录数"
          value={String(shownStats?.views ?? 0)}
          hint="已保存、去重后的记录"
          onClick={() => weekStart && weekEnd && goHistory({ start: weekStart, end: weekEnd })}
        />
        <StatCard
          label="估算观看时长"
          value={humanDuration(shownStats?.watch_seconds_est ?? 0)}
          hint="按记录进度估算"
          onClick={() => weekStart && weekEnd && goHistory({ start: weekStart, end: weekEnd })}
        />
        <StatCard label="去重视频" value={String(shownStats?.distinct_videos ?? 0)} hint="按 bvid 去重" />
        <StatCard label="去重 UP" value={String(shownStats?.distinct_ups ?? 0)} hint="按 mid 去重" />
        <StatCard
          label="样本构成"
          value={`${shownStats?.samples?.valid ?? 0} / ${shownStats?.samples?.bound ?? 0} / ${shownStats?.samples?.unknown ?? 0}`}
          hint="有效 / 下界 / 未知"
        />
      </div>

      {/* -------- coverage strip -------- */}
      {shownStats?.coverage && (
        <p className="text-xs text-slate-500 px-1">
          {shownStats.coverage.note}
          {shownStats.coverage.history_truncated && " · 上次同步因页数上限未完整覆盖，统计不含未拉取部分"}
          {shownStats.coverage.last_history_sync_at && ` · 上次历史同步 ${relativeTime(shownStats.coverage.last_history_sync_at)}`}
          · 口径版本 {shownStats.metrics_version}
        </p>
      )}
      {shownReport?.ai_text && (
        <Card>
          <h3 className="text-sm font-semibold mb-1">AI 解读（可选，不参与统计）</h3>
          <p className="text-sm text-slate-300 whitespace-pre-wrap">{shownReport.ai_text}</p>
        </Card>
      )}

      {/* -------- tabs -------- */}
      <div className="flex gap-1 border-b border-slate-700/60" role="tablist" aria-label="周报图表分组">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={`px-3 py-1.5 text-sm transition-colors border-b-2 ${
              tab === t.key
                ? "border-indigo-400 text-indigo-300 font-semibold"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
            onClick={() => {
              setTab(t.key);
              setUrl({ tab: t.key });
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loadingStats ? (
        <Spinner />
      ) : !shownStats ? (
        <EmptyState title="该周暂无数据" hint="选择其他周，或先在仪表盘运行观看历史同步。" />
      ) : (
        <>
          {tab === "overview" && (
            <OverviewTab
              stats={shownStats}
              dailyMode={dailyMode}
              setDailyMode={setDailyMode}
              onDayClick={(date) =>
                goHistory({ start: date, end: toISODate(addDays(new Date(`${date}T00:00:00`), 1)) })
              }
              onGroupClick={(name) => weekStart && weekEnd && goHistory({ start: weekStart, end: weekEnd, q: name })}
            />
          )}
          {tab === "habit" && (
            <HabitTab
              stats={shownStats}
              heatMode={heatMode}
              setHeatMode={setHeatMode}
              onCellClick={(weekday, hour) => {
                const monday = weekStart ? new Date(`${weekStart}T00:00:00`) : mondayOf(new Date());
                goHistory({
                  start: toISODate(addDays(monday, weekday)),
                  end: toISODate(addDays(monday, weekday + 1)),
                  hour: String(hour),
                });
              }}
            />
          )}
          {tab === "ups" && (
            <UpsTab
              stats={shownStats}
              topUpLimit={topUpLimit}
              setTopUpLimit={setTopUpLimit}
              onUpClick={(mid) =>
                weekStart && weekEnd && goHistory({ start: weekStart, end: weekEnd, up_mid: String(mid) })
              }
              onGroupClick={(name) => weekStart && weekEnd && goHistory({ start: weekStart, end: weekEnd, q: name })}
              onUncoveredClick={(mids) => {
                setMessage(
                  `未覆盖 UP（前 10 个 mid）：${mids.slice(0, 10).join("、")} —— 可在关注列表中搜索查看`
                );
              }}
            />
          )}
          {tab === "advanced" && (
            <AdvancedTab
              stats={shownStats}
              onVideoClick={(bvid) => window.open(`https://www.bilibili.com/video/${bvid}`, "_blank", "noopener")}
            />
          )}
        </>
      )}
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
    <Card className={onClick ? "cursor-pointer hover:border-indigo-400/60 transition-colors" : ""}>
      <button type="button" onClick={onClick} className="w-full text-left" disabled={!onClick}>
        <div className="text-xl font-bold tabular-nums">{value}</div>
        <div className="text-xs text-slate-400 mt-1">{label}</div>
        {hint && <div className="text-[11px] text-slate-500 mt-0.5">{hint}</div>}
      </button>
    </Card>
  );
}

function OverviewTab({
  stats,
  dailyMode,
  setDailyMode,
  onDayClick,
  onGroupClick,
}: {
  stats: Partial<RangeStats>;
  dailyMode: "daily" | "cumulative";
  setDailyMode: (m: "daily" | "cumulative") => void;
  onDayClick: (date: string) => void;
  onGroupClick: (name: string) => void;
}) {
  const daily = stats.daily ?? [];
  const previous = stats.previous;
  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <ChartCard
        title={dailyMode === "daily" ? "每日观看" : "累计观看"}
        metric="观看记录数（已保存、去重），Asia/Shanghai，周一起始"
        hint="点击柱形查看当天明细"
        optionFactory={(theme) =>
          dailyMode === "daily" ? dailyBarOption(theme, daily) : cumulativeLineOption(theme, daily)
        }
        onPointClick={(p) => {
          const day = daily[p.dataIndex]?.date;
          if (day) onDayClick(day);
        }}
        actions={
          <Select
            aria-label="每日/累计模式"
            value={dailyMode}
            onChange={(e) => setDailyMode(e.target.value as "daily" | "cumulative")}
          >
            <option value="daily">每日</option>
            <option value="cumulative">累计</option>
          </Select>
        }
        table={{
          columns: [{ label: "日期" }, { label: "记录数", align: "right" }, { label: "状态" }],
          rows: daily.map((d) => [d.date, d.views, d.covered ? "已覆盖" : "未到观测时间"]),
        }}
        height={240}
      />
      <ChartCard
        title="本周与上周对比"
        metric="按周一~周日对齐；未观测到的日期不显示（不伪造零值）"
        hint="点击柱形查看对应日期明细"
        optionFactory={(theme) => compareBarOption(theme, daily, previous?.daily ?? [])}
        onPointClick={(p) => {
          const series = p.seriesIndex === 0 ? daily : (previous?.daily ?? []);
          const day = series[p.dataIndex]?.date;
          if (day) onDayClick(day);
        }}
        table={{
          columns: [{ label: "日期" }, { label: "本周", align: "right" }, { label: "上周", align: "right" }],
          rows: daily.map((d, i) => [d.date, d.views, previous?.daily?.[i]?.views ?? null]),
        }}
        height={240}
      />
      {previous && (
        <Card className="xl:col-span-2">
          <h3 className="text-sm font-semibold">两周总量对比</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-2 text-sm">
            <CompareMetric label="观看记录数" current={stats.views ?? 0} prev={previous.views} />
            <CompareMetric label="去重视频" current={stats.distinct_videos ?? 0} prev={previous.distinct_videos} />
            <CompareMetric label="去重 UP" current={stats.distinct_ups ?? 0} prev={previous.distinct_ups} />
          </div>
        </Card>
      )}
      <ChartCard
        title="分组偏好"
        metric="非互斥：同一 UP 可属于多个分组，各组独立计数，比例不可相加"
        hint="点击分组查看该范围内明细"
        optionFactory={(theme) =>
          hBarOption(
            theme,
            (stats.by_group ?? []).map((g) => ({ name: g.name, value: g.views, extra: `${g.ups ?? "—"} 个 UP` })),
            "条"
          )
        }
        onPointClick={(p) => onGroupClick((stats.by_group ?? [])[p.dataIndex]?.name ?? "")}
        table={{
          columns: [{ label: "分组" }, { label: "记录数", align: "right" }, { label: "UP 数", align: "right" }],
          rows: (stats.by_group ?? []).map((g) => [g.name, g.views, g.ups ?? null]),
        }}
      />
      <ChartCard
        title="观看完成率分布"
        metric="有效进度与对应视频时长折算；未知样本单列，均值只用有效样本"
        optionFactory={(theme) =>
          hBarOption(
            theme,
            (stats.completion_buckets?.buckets ?? []).map((b) => ({ name: b.label, value: b.value })),
            "条",
            2
          )
        }
        coverage={
          stats.completion_buckets?.unknown
            ? `${stats.completion_buckets.unknown} 条记录缺少有效进度或时长，未计入`
            : undefined
        }
        table={{
          columns: [{ label: "完成率" }, { label: "记录数", align: "right" }],
          rows: [
            ...(stats.completion_buckets?.buckets ?? []).map((b) => [b.label, b.value] as [string, number]),
            ["未知", stats.completion_buckets?.unknown ?? 0] as [string, number],
          ],
        }}
      />
      <ChartCard
        title="内容分区 TOP"
        metric="按视频分区聚合的记录数"
        coverage={
          stats.tname_coverage && stats.tname_coverage.total > 0
            ? `已匹配 ${stats.tname_coverage.matched}/${stats.tname_coverage.total} 条；其余缺少视频元数据，未计入（不代表无分区）`
            : "该范围内没有已同步视频的分区元数据"
        }
        optionFactory={(theme) =>
          hBarOption(theme, (stats.tname_top ?? []).map((t) => ({ name: t.name, value: t.views })), "条", 5)
        }
        table={{
          columns: [{ label: "分区" }, { label: "记录数", align: "right" }],
          rows: (stats.tname_top ?? []).map((t) => [t.name, t.views]),
        }}
      />
    </div>
  );
}

function CompareMetric({
  label,
  current,
  prev,
}: {
  label: string;
  current: number;
  prev?: number;
}) {
  let deltaText = prev === undefined ? "" : "无可比基线";
  if (prev !== undefined && prev > 0) {
    const diff = current - prev;
    const rate = Math.round((diff / prev) * 100);
    deltaText = `${diff >= 0 ? "+" : ""}${diff}（${rate >= 0 ? "+" : ""}${rate}%）`;
  } else if (prev === 0 && current > 0) {
    deltaText = "本期新增";
  } else if (prev === 0 && current === 0) {
    deltaText = "两期均为 0";
  }
  return (
    <div>
      <div className="text-slate-400 text-xs">{label}</div>
      <div className="font-semibold tabular-nums">{current}</div>
      <div className="text-xs text-slate-500">
        {prev !== undefined ? `上周 ${prev}` : ""} · {deltaText}
      </div>
    </div>
  );
}

function HabitTab({
  stats,
  heatMode,
  setHeatMode,
  onCellClick,
}: {
  stats: Partial<RangeStats>;
  heatMode: "views" | "seconds";
  setHeatMode: (m: "views" | "seconds") => void;
  onCellClick: (weekday: number, hour: number) => void;
}) {
  const heatmap = stats.heatmap;
  const hourly = stats.hourly ?? [];
  const weekday = stats.weekday ?? [];
  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <ChartCard
        title="星期 × 小时观看热力图"
        metric="Asia/Shanghai 墙钟时间；横轴 00–23 时，纵轴周一–周日"
        hint="点击格子查看该时段明细"
        optionFactory={(theme) => heatmapOption(theme, heatmap?.days ?? [], WEEKDAY_LABELS, heatMode)}
        onPointClick={(p) => {
          const value = p.value as [number, number, number] | undefined;
          if (!value) return;
          onCellClick(value[1], value[0]);
        }}
        actions={
          <Select
            aria-label="热力图指标"
            value={heatMode}
            onChange={(e) => setHeatMode(e.target.value as "views" | "seconds")}
          >
            <option value="views">记录数</option>
            <option value="seconds">折算时长</option>
          </Select>
        }
        table={{
          columns: [
            { label: "星期\\小时" },
            ...Array.from({ length: 24 }, (_, h) => ({ label: String(h), align: "right" as const })),
          ],
          rows: (heatmap?.days ?? []).map((d) => [
            WEEKDAY_LABELS[d.weekday],
            ...d.hours.map((c) => (heatMode === "seconds" ? c.seconds : c.views)),
          ]),
        }}
        height={300}
      />
      <ChartCard
        title="观看时段分布"
        metric="全天 24 小时记录数（上海时间）"
        hint="点击柱形查看该小时明细"
        optionFactory={(theme) => hourlyBarOption(theme, hourly)}
        onPointClick={(p) => onCellClick(0, p.dataIndex)}
        table={{
          columns: [{ label: "小时" }, { label: "记录数", align: "right" }],
          rows: hourly.map((v, h) => [String(h).padStart(2, "0"), v]),
        }}
      />
      <ChartCard
        title="星期分布"
        metric="一周内各星期的记录数（热力图的辅助视图）"
        optionFactory={(theme) => weekdayBarOption(theme, weekday)}
        onPointClick={(p) => onCellClick(p.dataIndex, 0)}
        table={{
          columns: [{ label: "星期" }, { label: "记录数", align: "right" }],
          rows: weekday.map((w) => [w.label, w.value]),
        }}
      />
      <ChartCard
        title="视频时长分布"
        metric="单条记录对应视频的总时长分桶"
        coverage={
          stats.duration_buckets?.unknown
            ? `${stats.duration_buckets.unknown} 条记录缺少视频时长，未计入`
            : undefined
        }
        optionFactory={(theme) =>
          hBarOption(
            theme,
            (stats.duration_buckets?.buckets ?? []).map((b) => ({ name: b.label, value: b.value })),
            "条",
            4
          )
        }
        table={{
          columns: [{ label: "时长" }, { label: "记录数", align: "right" }],
          rows: (stats.duration_buckets?.buckets ?? []).map((b) => [b.label, b.value]),
        }}
      />
    </div>
  );
}

function UpsTab({
  stats,
  topUpLimit,
  setTopUpLimit,
  onUpClick,
  onGroupClick,
  onUncoveredClick,
}: {
  stats: Partial<RangeStats>;
  topUpLimit: number;
  setTopUpLimit: (n: number) => void;
  onUpClick: (mid: number) => void;
  onGroupClick: (name: string) => void;
  onUncoveredClick: (mids: number[]) => void;
}) {
  const topUps = stats.top_ups ?? [];
  const shown = topUpLimit === 0 ? topUps : topUps.slice(0, topUpLimit);
  const deltaRows = [...(stats.up_delta?.risers ?? []), ...(stats.up_delta?.fallers ?? [])];
  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <ChartCard
        title="TOP UP 排行"
        metric={`按记录数排序；TOP5 集中度 ${((stats.top5_share ?? 0) * 100).toFixed(1)}%`}
        hint="点击 UP 行查看该周明细"
        optionFactory={(theme) =>
          hBarOption(
            theme,
            shown.map((u) => ({ name: u.uname ?? `昵称暂不可用（UID ${u.mid}）`, value: u.views })),
            "条"
          )
        }
        onPointClick={(p) => {
          const up = shown[p.dataIndex];
          if (up) onUpClick(up.mid);
        }}
        actions={
          <Select
            aria-label="显示数量"
            value={String(topUpLimit)}
            onChange={(e) => setTopUpLimit(Number(e.target.value))}
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
      <ChartCard
        title="分组偏好"
        metric="非互斥：同一 UP 可属于多个分组"
        hint="点击分组查看明细"
        optionFactory={(theme) =>
          hBarOption(
            theme,
            (stats.by_group ?? []).map((g) => ({ name: g.name, value: g.views, extra: `${g.ups ?? "—"} 个 UP` })),
            "条",
            6
          )
        }
        onPointClick={(p) => onGroupClick((stats.by_group ?? [])[p.dataIndex]?.name ?? "")}
        table={{
          columns: [{ label: "分组" }, { label: "记录数", align: "right" }, { label: "UP 数", align: "right" }],
          rows: (stats.by_group ?? []).map((g) => [g.name, g.views, g.ups ?? null]),
        }}
      />
      <ChartCard
        title="分组观看覆盖率"
        metric="期间有观看记录的关注 UP / 该组纳入统计的关注 UP（各组独立计算，比例不可相加）"
        coverage="基于报告生成时刻的成员集合"
        hint="点击「未覆盖」段查看未覆盖 UP"
        optionFactory={(theme) =>
          groupCoverageOption(
            theme,
            (stats.group_coverage ?? []).map((g) => ({ name: g.name, covered: g.covered, total: g.total }))
          )
        }
        onPointClick={(p) => {
          const g = (stats.group_coverage ?? [])[p.dataIndex];
          if (g && p.seriesIndex === 1 && g.uncovered_sample.length) onUncoveredClick(g.uncovered_sample);
        }}
        table={{
          columns: [{ label: "分组" }, { label: "覆盖", align: "right" }, { label: "比例", align: "right" }],
          rows: (stats.group_coverage ?? []).map((g) => [
            g.name,
            `${g.covered}/${g.total}`,
            `${Math.round(g.ratio * 100)}%`,
          ]),
        }}
      />
      <ChartCard
        title="UP 观看变化榜"
        metric="与上一可比周期（上一自然周）按 mid 聚合的记录数增减"
        coverage={
          stats.period?.is_complete === false
            ? "本周尚未结束：对比基于相同的已过去天数，非整周"
            : undefined
        }
        hint="点击 UP 查看两期明细"
        optionFactory={(theme) =>
          deltaBarOption(theme, deltaRows.slice(0, 20).map((u) => ({ name: u.uname ?? `UID ${u.mid}`, delta: u.delta })))
        }
        onPointClick={(p) => {
          const up = deltaRows.slice(0, 20)[p.dataIndex];
          if (up) onUpClick(up.mid);
        }}
        table={{
          columns: [
            { label: "UP" },
            { label: "本期", align: "right" },
            { label: "上期", align: "right" },
            { label: "变化", align: "right" },
          ],
          rows: deltaRows.map((u) => [
            u.uname ?? `UID ${u.mid}`,
            u.current,
            u.previous || null,
            `${u.delta >= 0 ? "+" : ""}${u.delta}${u.change === "new" ? "（新增）" : ""}`,
          ]),
        }}
      />
    </div>
  );
}

function AdvancedTab({
  stats,
  onVideoClick,
}: {
  stats: Partial<RangeStats>;
  onVideoClick: (bvid: string) => void;
}) {
  const explore = stats.explore_return ?? [];
  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <ChartCard
        title="已同步投稿的观看覆盖"
        metric="已同步投稿中发现观看记录 / 未发现观看记录（去重视频数，按组）"
        coverage="仅统计已同步的投稿；未抓到的投稿不会计入，也不能视为零投稿"
        hint="点击「未发现观看」段打开一个未覆盖视频"
        optionFactory={(theme) =>
          videoCoverageOption(
            theme,
            (stats.video_coverage ?? []).map((v) => ({
              name: v.name,
              watched_videos: v.watched_videos,
              unwatched_videos: v.unwatched_videos,
            }))
          )
        }
        onPointClick={(p) => {
          const v = (stats.video_coverage ?? [])[p.dataIndex];
          if (v && p.seriesIndex === 1) {
            const first = v.unwatched_sample[0];
            if (first) onVideoClick(first);
          }
        }}
        table={{
          columns: [
            { label: "分组" },
            { label: "已同步", align: "right" },
            { label: "发现观看", align: "right" },
            { label: "未发现", align: "right" },
          ],
          rows: (stats.video_coverage ?? []).map((v) => [v.name, v.synced_videos, v.watched_videos, v.unwatched_videos]),
        }}
      />
      <ChartCard
        title="新探索与回访趋势"
        metric="按天：当日首次出现在本地已保存历史的 UP vs 此前已有记录、当日再次出现的 UP（每日按 UP 去重）"
        hint="每日两类之和 = 当天去重 UP 数；跨天求和 ≠ 整周去重 UP 数"
        optionFactory={(theme) => exploreReturnOption(theme, explore)}
        table={{
          columns: [
            { label: "日期" },
            { label: "新出现 UP", align: "right" },
            { label: "回访 UP", align: "right" },
          ],
          rows: explore.map((d) => [d.date, d.new_ups, d.returning_ups]),
        }}
      />
      <Card className="xl:col-span-2">
        <h3 className="text-sm font-semibold">口径说明</h3>
        <ul className="text-xs text-slate-400 mt-2 space-y-1.5 list-disc list-inside">
          <li>观看时长为「按记录进度估算」：有效进度与对应时长折算，非精确实际播放耗时（拖动、倍速、重复观看无法还原）。</li>
          <li>「已同步范围内未发现观看记录」只描述已同步数据的范围，不是终身判断。</li>
          <li>新探索/回访的基线是本地已保存历史，非用户终身首次观看。</li>
          <li>分组为非互斥关系；需要份额口径时使用主分组归属。</li>
          <li>邮箱与导出的 HTML 为静态图表 + 数据表；交互放大与钻取仅在网页版提供。</li>
        </ul>
      </Card>
    </div>
  );
}
