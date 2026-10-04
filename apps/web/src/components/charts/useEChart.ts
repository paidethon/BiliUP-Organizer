// Lazy ECharts integration: echarts/core + only the charts/components in use
// are dynamically imported, so the main bundle stays small. The hook handles
// theme token refresh, container resize, reduced motion and disposal.

import { useEffect, useRef, type RefObject } from "react";
import type { EChartsOption } from "echarts";

type EChartsModule = typeof import("echarts/core");
type EChartsInstance = ReturnType<EChartsModule["init"]>;

export interface PointClickInfo {
  seriesIndex: number;
  dataIndex: number;
  name: string;
  value: unknown;
}

let echartsPromise: Promise<EChartsModule> | null = null;

async function loadECharts(): Promise<EChartsModule> {
  if (!echartsPromise) {
    echartsPromise = Promise.all([
      import("echarts/core"),
      import("echarts/charts"),
      import("echarts/components"),
    ]).then(([core, charts, components]) => {
      core.use([
        charts.BarChart,
        charts.LineChart,
        charts.HeatmapChart,
        components.GridComponent,
        components.TooltipComponent,
        components.LegendComponent,
        components.DataZoomComponent,
        components.TitleComponent,
        components.MarkLineComponent,
      ]);
      return core;
    });
  }
  return echartsPromise;
}

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export interface ChartTheme {
  palette: string[];
  axis: string;
  split: string;
  text: string;
  heatEmpty: string;
  reducedMotion: boolean;
}

export function readChartTheme(): ChartTheme {
  return {
    palette: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => cssVar(`--chart-${i}`, "#ec4899")),
    axis: cssVar("--chart-axis", "#8b8b98"),
    split: cssVar("--chart-split", "rgba(139,139,152,0.18)"),
    text: cssVar("--lumi-text", "#ececf1"),
    heatEmpty: cssVar("--chart-heat-empty", "rgba(139,139,152,0.08)"),
    reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  };
}

export function baseTooltip(theme: ChartTheme) {
  return {
    trigger: "axis" as const,
    backgroundColor: "rgba(13,13,18,0.94)",
    borderColor: cssVar("--lumi-border", "#232330"),
    textStyle: { color: theme.text, fontSize: 12 },
    confine: true,
  };
}

/**
 * Mounts an ECharts instance into the returned ref. The option factory is
 * re-invoked whenever `deps` change OR the theme attribute flips, so colors
 * always come from the live CSS tokens. `onPointClick` is bridged by ref so
 * re-renders never re-init the chart.
 */
export function useEChart(
  containerRef: RefObject<HTMLDivElement | null>,
  optionFactory: (theme: ChartTheme) => EChartsOption,
  deps: unknown[],
  onPointClick?: (info: PointClickInfo) => void
): void {
  const optionRef = useRef(optionFactory);
  optionRef.current = optionFactory;
  const clickRef = useRef(onPointClick);
  clickRef.current = onPointClick;

  useEffect(() => {
    let disposed = false;
    let chart: EChartsInstance | null = null;
    let resizeObserver: ResizeObserver | null = null;
    let themeObserver: MutationObserver | null = null;

    loadECharts().then((echarts) => {
      if (disposed || !containerRef.current) return;
      chart = echarts.init(containerRef.current);
      chart.setOption(optionRef.current(readChartTheme()));
      chart.on("click", (params: { seriesIndex?: number; dataIndex?: number; name?: string; value?: unknown }) => {
        clickRef.current?.({
          seriesIndex: params.seriesIndex ?? 0,
          dataIndex: params.dataIndex ?? 0,
          name: params.name ?? "",
          value: params.value,
        });
      });
      resizeObserver = new ResizeObserver(() => chart?.resize());
      resizeObserver.observe(containerRef.current);
      // re-render on dark/light switch (tokens are CSS vars)
      themeObserver = new MutationObserver(() => {
        chart?.setOption(optionRef.current(readChartTheme()), { notMerge: true });
      });
      themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    });

    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      themeObserver?.disconnect();
      chart?.dispose();
      chart = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, containerRef]);
}
