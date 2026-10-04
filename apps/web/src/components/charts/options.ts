// ECharts option builders — one per chart, all theme-token driven. Kept pure
// so ChartCard can reuse them for both the inline card and the zoom dialog.

import type { EChartsOption } from "echarts";
import { baseTooltip, type ChartTheme } from "./useEChart";

const Motion = (theme: ChartTheme) => (theme.reducedMotion ? false : undefined);

export function dailyBarOption(
  theme: ChartTheme,
  daily: Array<{ date: string; views: number | null; covered: boolean }>,
  unit = "条"
): EChartsOption {
  const labels = daily.map((d) => d.date.slice(5));
  return {
    animation: Motion(theme),
    grid: { left: 44, right: 12, top: 16, bottom: 28 },
    tooltip: { ...baseTooltip(theme), formatter: (ps: unknown) => fmtOne(ps, unit) },
    xAxis: {
      type: "category",
      data: labels,
      axisLine: { lineStyle: { color: theme.axis } },
      axisLabel: { color: theme.axis, fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      minInterval: 1,
      axisLabel: { color: theme.axis, fontSize: 11 },
      splitLine: { lineStyle: { color: theme.split } },
    },
    series: [
      {
        type: "bar",
        data: daily.map((d) => (d.views === null ? { value: 0, itemStyle: { color: theme.heatEmpty } } : d.views)),
        itemStyle: { color: theme.palette[0], borderRadius: [4, 4, 0, 0] },
        barMaxWidth: 34,
      },
    ],
  };
}

export function cumulativeLineOption(
  theme: ChartTheme,
  daily: Array<{ date: string; views: number | null }>
): EChartsOption {
  let running = 0;
  const data = daily.map((d) => {
    if (d.views !== null) running += d.views;
    return d.views === null ? null : running;
  });
  return {
    animation: Motion(theme),
    grid: { left: 48, right: 12, top: 16, bottom: 28 },
    tooltip: { ...baseTooltip(theme), trigger: "axis" },
    xAxis: {
      type: "category",
      data: daily.map((d) => d.date.slice(5)),
      axisLine: { lineStyle: { color: theme.axis } },
      axisLabel: { color: theme.axis, fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: { type: "value", minInterval: 1, axisLabel: { color: theme.axis }, splitLine: { lineStyle: { color: theme.split } } },
    series: [
      {
        type: "line",
        data,
        connectNulls: false,
        symbol: "circle",
        symbolSize: 5,
        lineStyle: { color: theme.palette[0], width: 2 },
        itemStyle: { color: theme.palette[0] },
        areaStyle: { color: theme.palette[0], opacity: 0.12 },
      },
    ],
  };
}

export function hourlyBarOption(theme: ChartTheme, hourly: number[], unit = "条"): EChartsOption {
  return {
    animation: Motion(theme),
    grid: { left: 40, right: 12, top: 16, bottom: 28 },
    tooltip: { ...baseTooltip(theme), formatter: (ps: unknown) => fmtOne(ps, unit) },
    xAxis: {
      type: "category",
      data: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0")),
      axisLine: { lineStyle: { color: theme.axis } },
      axisLabel: { color: theme.axis, fontSize: 10, interval: 2 },
      axisTick: { show: false },
    },
    yAxis: { type: "value", minInterval: 1, axisLabel: { color: theme.axis }, splitLine: { lineStyle: { color: theme.split } } },
    series: [{ type: "bar", data: hourly, itemStyle: { color: theme.palette[1], borderRadius: [3, 3, 0, 0] } }],
  };
}

export function weekdayBarOption(theme: ChartTheme, weekday: Array<{ label: string; value: number }>, unit = "条"): EChartsOption {
  return {
    animation: Motion(theme),
    grid: { left: 40, right: 12, top: 16, bottom: 28 },
    tooltip: { ...baseTooltip(theme), formatter: (ps: unknown) => fmtOne(ps, unit) },
    xAxis: {
      type: "category",
      data: weekday.map((w) => w.label),
      axisLine: { lineStyle: { color: theme.axis } },
      axisLabel: { color: theme.axis, fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: { type: "value", minInterval: 1, axisLabel: { color: theme.axis }, splitLine: { lineStyle: { color: theme.split } } },
    series: [{ type: "bar", data: weekday.map((w) => w.value), itemStyle: { color: theme.palette[5], borderRadius: [3, 3, 0, 0] } }],
  };
}

/** C1: weekday × hour heatmap (Shanghai wall clock). */
export function heatmapOption(
  theme: ChartTheme,
  days: Array<{ date: string; weekday: number; hours: Array<{ views: number | null; seconds: number | null }> }>,
  weekdayLabels: string[],
  mode: "views" | "seconds" = "views"
): EChartsOption {
  const hours = Array.from({ length: 24 }, (_, i) => i);
  const data: Array<[number, number, number]> = [];
  let max = 0;
  const byWeekday = new Map<number, Array<number | null>>();
  for (const day of days) {
    const row = byWeekday.get(day.weekday) ?? new Array(24).fill(null);
    day.hours.forEach((cell, hour) => {
      const v = mode === "seconds" ? cell.seconds : cell.views;
      const prev = row[hour];
      if (v !== null) {
        row[hour] = (prev ?? 0) + v;
        max = Math.max(max, row[hour] ?? 0);
      }
    });
    byWeekday.set(day.weekday, row);
  }
  for (const [weekday, row] of byWeekday) {
    row.forEach((v, hour) => {
      data.push([hour, weekday, v ?? 0]);
    });
  }
  return {
    animation: Motion(theme),
    grid: { left: 52, right: 12, top: 12, bottom: 48 },
    tooltip: {
      ...baseTooltip(theme),
      trigger: "item",
      formatter: (p: unknown) => {
        const cast = p as { data: [number, number, number] };
        const [hour, weekday, value] = cast.data;
        return `${weekdayLabels[weekday]} ${String(hour).padStart(2, "0")}:00—${String(hour).padStart(2, "0")}:59<br/>${
          mode === "seconds" ? "折算时长" : "记录数"
        }：${value}`;
      },
    },
    xAxis: {
      type: "category",
      data: hours.map((h) => String(h).padStart(2, "0")),
      axisLine: { show: false },
      axisLabel: { color: theme.axis, fontSize: 10, interval: 2 },
      axisTick: { show: false },
      splitArea: { show: false },
    },
    yAxis: {
      type: "category",
      data: weekdayLabels,
      axisLine: { show: false },
      axisLabel: { color: theme.axis, fontSize: 11 },
      axisTick: { show: false },
    },
    visualMap: {
      min: 0,
      max: Math.max(max, 1),
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 10,
      itemHeight: 80,
      textStyle: { color: theme.axis, fontSize: 10 },
      inRange: { color: [theme.heatEmpty, theme.palette[0]] },
    },
    series: [
      {
        type: "heatmap",
        data,
        label: { show: false },
        itemStyle: { borderColor: "transparent", borderRadius: 2 },
      },
    ],
  };
}

/** C2: 本周 vs 上周 aligned Monday-Sunday, integer counts, null for unobserved. */
export function compareBarOption(
  theme: ChartTheme,
  current: Array<{ date: string; views: number | null }>,
  previous: Array<{ date: string; views: number | null }>
): EChartsOption {
  return {
    animation: Motion(theme),
    grid: { left: 44, right: 12, top: 30, bottom: 28 },
    tooltip: { ...baseTooltip(theme), trigger: "axis" },
    legend: {
      data: ["本周", "上周"],
      textStyle: { color: theme.axis, fontSize: 11 },
      top: 0,
    },
    xAxis: {
      type: "category",
      data: current.map((d) => d.date.slice(5)),
      axisLine: { lineStyle: { color: theme.axis } },
      axisLabel: { color: theme.axis, fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: { type: "value", minInterval: 1, axisLabel: { color: theme.axis }, splitLine: { lineStyle: { color: theme.split } } },
    series: [
      {
        name: "本周",
        type: "bar",
        data: current.map((d) => d.views),
        itemStyle: { color: theme.palette[0], borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 18,
      },
      {
        name: "上周",
        type: "bar",
        data: previous.map((d) => d.views),
        itemStyle: { color: theme.palette[1], borderRadius: [3, 3, 0, 0], opacity: 0.75 },
        barMaxWidth: 18,
      },
    ],
  };
}

/** C3: per-group coverage — horizontal stacked covered/uncovered. */
export function groupCoverageOption(
  theme: ChartTheme,
  rows: Array<{ name: string; covered: number; total: number }>
): EChartsOption {
  const names = rows.map((r) => r.name);
  return {
    animation: Motion(theme),
    grid: { left: 90, right: 40, top: 8, bottom: 24 },
    tooltip: {
      ...baseTooltip(theme),
      trigger: "item",
      formatter: (p: unknown) => {
        const cast = p as { seriesName: string; name: string; value: number; dataIndex: number };
        const row = rows[cast.dataIndex];
        return `${cast.name}<br/>${cast.seriesName}: ${cast.value} (${
          row.total ? Math.round((cast.value / row.total) * 100) : 0
        }%)`;
      },
    },
    xAxis: { type: "value", minInterval: 1, axisLabel: { color: theme.axis }, splitLine: { lineStyle: { color: theme.split } } },
    yAxis: {
      type: "category",
      data: names,
      axisLine: { lineStyle: { color: theme.axis } },
      axisLabel: { color: theme.axis, fontSize: 11, width: 82, overflow: "truncate" },
      axisTick: { show: false },
    },
    series: [
      {
        name: "已覆盖",
        type: "bar",
        stack: "cov",
        data: rows.map((r) => r.covered),
        itemStyle: { color: theme.palette[2] },
        barMaxWidth: 16,
      },
      {
        name: "未覆盖",
        type: "bar",
        stack: "cov",
        data: rows.map((r) => Math.max(r.total - r.covered, 0)),
        itemStyle: { color: theme.heatEmpty },
        barMaxWidth: 16,
      },
    ],
  };
}

/** C4: diverging bars for per-UP delta. */
export function deltaBarOption(
  theme: ChartTheme,
  rows: Array<{ name: string; delta: number }>
): EChartsOption {
  const names = rows.map((r) => r.name);
  return {
    animation: Motion(theme),
    grid: { left: 90, right: 30, top: 8, bottom: 24 },
    tooltip: {
      ...baseTooltip(theme),
      trigger: "item",
      formatter: (p: unknown) => {
        const cast = p as { name: string; value: number };
        return `${cast.name}<br/>变化：${cast.value > 0 ? "+" : ""}${cast.value} 条`;
      },
    },
    xAxis: {
      type: "value",
      axisLabel: { color: theme.axis },
      splitLine: { lineStyle: { color: theme.split } },
    },
    yAxis: {
      type: "category",
      data: names,
      axisLine: { lineStyle: { color: theme.axis } },
      axisLabel: { color: theme.axis, fontSize: 11, width: 82, overflow: "truncate" },
      axisTick: { show: false },
    },
    series: [
      {
        type: "bar",
        data: rows.map((r) => ({
          value: r.delta,
          itemStyle: { color: r.delta >= 0 ? theme.palette[2] : theme.palette[6], borderRadius: 3 },
        })),
        barMaxWidth: 14,
      },
    ],
  };
}

/** C5: synced-video coverage per group. */
export function videoCoverageOption(
  theme: ChartTheme,
  rows: Array<{ name: string; watched_videos: number; unwatched_videos: number }>
): EChartsOption {
  const names = rows.map((r) => r.name);
  return {
    animation: Motion(theme),
    grid: { left: 90, right: 40, top: 30, bottom: 24 },
    tooltip: { ...baseTooltip(theme), trigger: "axis" },
    legend: { data: ["发现观看", "未发现观看"], textStyle: { color: theme.axis, fontSize: 11 }, top: 0 },
    xAxis: { type: "value", minInterval: 1, axisLabel: { color: theme.axis }, splitLine: { lineStyle: { color: theme.split } } },
    yAxis: {
      type: "category",
      data: names,
      axisLine: { lineStyle: { color: theme.axis } },
      axisLabel: { color: theme.axis, fontSize: 11, width: 82, overflow: "truncate" },
      axisTick: { show: false },
    },
    series: [
      {
        name: "发现观看",
        type: "bar",
        stack: "vc",
        data: rows.map((r) => r.watched_videos),
        itemStyle: { color: theme.palette[2] },
        barMaxWidth: 16,
      },
      {
        name: "未发现观看",
        type: "bar",
        stack: "vc",
        data: rows.map((r) => r.unwatched_videos),
        itemStyle: { color: theme.heatEmpty },
        barMaxWidth: 16,
      },
    ],
  };
}

/** C6: new vs returning UPs per day (lines, null for unobserved days). */
export function exploreReturnOption(
  theme: ChartTheme,
  rows: Array<{ date: string; new_ups: number | null; returning_ups: number | null }>
): EChartsOption {
  return {
    animation: Motion(theme),
    grid: { left: 40, right: 12, top: 30, bottom: 28 },
    tooltip: { ...baseTooltip(theme), trigger: "axis" },
    legend: { data: ["新出现 UP", "回访 UP"], textStyle: { color: theme.axis, fontSize: 11 }, top: 0 },
    xAxis: {
      type: "category",
      data: rows.map((r) => r.date.slice(5)),
      axisLine: { lineStyle: { color: theme.axis } },
      axisLabel: { color: theme.axis, fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: { type: "value", minInterval: 1, axisLabel: { color: theme.axis }, splitLine: { lineStyle: { color: theme.split } } },
    series: [
      {
        name: "新出现 UP",
        type: "bar",
        stack: "up",
        data: rows.map((r) => r.new_ups),
        itemStyle: { color: theme.palette[0] },
        barMaxWidth: 20,
      },
      {
        name: "回访 UP",
        type: "bar",
        stack: "up",
        data: rows.map((r) => r.returning_ups),
        itemStyle: { color: theme.palette[1] },
        barMaxWidth: 20,
      },
    ],
  };
}

/** Horizontal bars for TOP lists (UP 排行 / 分区 / 分组偏好). */
export function hBarOption(
  theme: ChartTheme,
  rows: Array<{ name: string; value: number; extra?: string }>,
  unit = "条",
  colorIndex = 0
): EChartsOption {
  const names = rows.map((r) => r.name);
  return {
    animation: Motion(theme),
    grid: { left: 90, right: 44, top: 8, bottom: 24 },
    tooltip: {
      ...baseTooltip(theme),
      trigger: "item",
      formatter: (p: unknown) => {
        const cast = p as { name: string; value: number; dataIndex: number };
        const extra = rows[cast.dataIndex]?.extra;
        return `${cast.name}<br/>${cast.value} ${unit}${extra ? `<br/>${extra}` : ""}`;
      },
    },
    xAxis: { type: "value", minInterval: 1, axisLabel: { color: theme.axis }, splitLine: { lineStyle: { color: theme.split } } },
    yAxis: {
      type: "category",
      data: names,
      inverse: true,
      axisLine: { lineStyle: { color: theme.axis } },
      axisLabel: { color: theme.axis, fontSize: 11, width: 82, overflow: "truncate" },
      axisTick: { show: false },
    },
    series: [
      {
        type: "bar",
        data: rows.map((r, i) => ({
          value: r.value,
          itemStyle: { color: theme.palette[colorIndex], opacity: 1 - Math.min(i, 6) * 0.08, borderRadius: [0, 3, 3, 0] },
        })),
        barMaxWidth: 16,
        label: {
          show: true,
          position: "right",
          color: theme.axis,
          fontSize: 11,
          formatter: (p: unknown) => String((p as { value: number }).value),
        },
      },
    ],
  };
}

function fmtOne(ps: unknown, unit: string): string {
  const arr = Array.isArray(ps) ? ps : [ps];
  const first = arr[0] as { name?: string; value?: number; dataIndex?: number };
  const axis = arr[0] && Array.isArray(arr) ? (arr[0] as { axisValue?: string }).axisValue : undefined;
  const name = axis ?? first?.name ?? "";
  return `${name}<br/>${first?.value ?? 0} ${unit}`;
}
