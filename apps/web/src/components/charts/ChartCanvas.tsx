// Thin React wrapper around the useEChart hook.

import { useRef } from "react";
import type { EChartsOption } from "echarts";
import { useEChart, type PointClickInfo } from "./useEChart";
import type { ChartTheme } from "./useEChart";

export interface ChartCanvasProps {
  optionFactory: (theme: ChartTheme) => EChartsOption;
  height?: number;
  onPointClick?: (info: PointClickInfo) => void;
  /** accessible name; defaults to a generic label */
  ariaLabel?: string;
}

export function ChartCanvas({ optionFactory, height = 220, onPointClick, ariaLabel }: ChartCanvasProps) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEChart(
    ref,
    (theme) => ({
      ...optionFactory(theme),
      textStyle: {
        fontFamily: "Inter, 'PingFang SC', 'Microsoft YaHei', sans-serif",
        color: theme.text,
      },
    }),
    [optionFactory],
    onPointClick
  );

  return <div ref={ref} style={{ width: "100%", height }} role="img" aria-label={ariaLabel ?? "统计图表"} />;
}
