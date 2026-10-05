// ChartCard — the one wrapper every chart (kept + new) renders through:
// title / unit / metric note / coverage hint, a real zoom button opening a
// large dialog, a data-table view, CSV + PNG export, and explicit loading /
// empty / error states. Zooming and drill-down are separate actions: clicking
// a chart element fires onPointClick, never the dialog.

import { useState, type ReactNode } from "react";
import type { EChartsOption } from "echarts";
import { Card } from "../ui";
import { Modal } from "../ui";
import { downloadText, toCsv } from "../../lib/csv";
import { ChartCanvas } from "./ChartCanvas";
import { ChartDataTable, type TableColumn } from "./ChartDataTable";
import type { ChartTheme, PointClickInfo } from "./useEChart";

export interface ChartCardProps {
  title: string;
  /** 口径/单位说明, shown under the title */
  metric?: string;
  /** 数据覆盖提示 (e.g. "已匹配 120/269 条, 其余缺少元数据") */
  coverage?: string;
  /** 交互钻取说明 (e.g. "点击柱形查看明细") */
  hint?: string;
  /** ECharts option factory (theme-driven) */
  optionFactory?: (theme: ChartTheme) => EChartsOption;
  loading?: boolean;
  error?: string | null;
  /** render children instead of the canvas (custom bodies) */
  children?: ReactNode;
  /** min canvas height inside the card */
  height?: number;
  /** data-table columns + rows for the table view & CSV export */
  table?: { columns: TableColumn[]; rows: Array<Array<string | number | null | undefined>> };
  /** file stem for exports */
  exportName?: string;
  /** click handler on chart graphics (drill-down); NOT the zoom trigger */
  onPointClick?: (info: PointClickInfo) => void;
  /** extra controls (metric switches, legends) rendered in the header */
  actions?: ReactNode;
  /** hide the zoom button for charts that make no sense enlarged */
  noZoom?: boolean;
}

export function ChartCard(props: ChartCardProps) {
  const {
    title,
    metric,
    coverage,
    hint,
    optionFactory,
    loading,
    error,
    children,
    height = 220,
  } = props;
  const [zoomed, setZoomed] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const exportName = title.replace(/[\\/:*?"<>|\s]+/g, "-");

  const exportCsv = () => {
    if (!props.table) return;
    downloadText(
      `${exportName}.csv`,
      toCsv(props.table.rows, props.table.columns.map((c) => c.label)),
      "text/csv;charset=utf-8"
    );
  };

  const body = showTable && props.table ? (
    <ChartDataTable columns={props.table.columns} rows={props.table.rows} />
  ) : children ? (
    children
  ) : optionFactory ? (
    <ChartCanvas optionFactory={optionFactory} height={height} onPointClick={props.onPointClick} ariaLabel={`图表：${title}`} />
  ) : (
    <div className="text-sm text-slate-500 py-10 text-center" role="status">
      暂无数据
    </div>
  );

  return (
    <Card className="flex flex-col gap-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{title}</h3>
          {metric && <p className="text-xs text-slate-400 mt-0.5">{metric}</p>}
          {coverage && <p className="text-xs text-amber-400/90 mt-0.5">⚠ {coverage}</p>}
          {hint && <p className="text-xs text-slate-500 mt-0.5">{hint}</p>}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {props.actions}
          {props.table && (
            <button
              type="button"
              className="px-2 py-1 text-xs rounded-md border border-slate-700 text-slate-300 transition-colors duration-150 hover:bg-white/5"
              onClick={() => setShowTable((v) => !v)}
              aria-pressed={showTable}
            >
              {showTable ? "图表" : "数据表"}
            </button>
          )}
          {props.table && (
            <button
              type="button"
              className="px-2 py-1 text-xs rounded-md border border-slate-700 text-slate-300 transition-colors duration-150 hover:bg-white/5"
              onClick={exportCsv}
            >
              CSV
            </button>
          )}
          {!props.noZoom && (optionFactory || children) && (
            <button
              type="button"
              className="px-2 py-1 text-xs rounded-md border border-indigo-500/60 text-indigo-300 transition-colors duration-150 hover:bg-indigo-500/10"
              onClick={() => setZoomed(true)}
              aria-haspopup="dialog"
            >
              放大
            </button>
          )}
        </div>
      </div>

      <div className="min-h-0">
        {loading ? (
          <div className="flex items-center justify-center text-sm text-slate-500 py-10" role="status">
            加载中…
          </div>
        ) : error ? (
          <div className="text-sm text-red-400 py-10 text-center" role="alert">
            出错了：{error}
          </div>
        ) : (
          body
        )}
      </div>

      {!props.noZoom && (
        <Modal open={zoomed} onClose={() => setZoomed(false)} title={`${title}（放大）`} wide>
          <div className="flex flex-col gap-2">
            {(metric || coverage) && (
              <p className="text-xs text-slate-400">
                {metric} {coverage && <span className="text-amber-400/90">⚠ {coverage}</span>}
              </p>
            )}
            <div className="flex justify-end gap-1.5">
              {props.table && (
                <button
                  type="button"
                  className="px-2 py-1 text-xs rounded-md border border-slate-700 text-slate-300 transition-colors duration-150 hover:bg-white/5"
                  onClick={exportCsv}
                >
                  导出 CSV
                </button>
              )}
              {optionFactory && (
                <button
                  type="button"
                  className="px-2 py-1 text-xs rounded-md border border-slate-700 text-slate-300 transition-colors duration-150 hover:bg-white/5"
                  onClick={() => {
                    const canvas = document.querySelector(".chart-dialog-body canvas");
                    if (canvas instanceof HTMLCanvasElement) {
                      downloadText(`${exportName}.png`, canvas.toDataURL("image/png"), "image/png");
                    }
                  }}
                >
                  导出 PNG
                </button>
              )}
            </div>
            <div className="chart-dialog-body">
              {children ? (
                children
              ) : (
                <ChartCanvas optionFactory={optionFactory ?? (() => ({}))} height={Math.max(320, Math.round(window.innerHeight * 0.55))} onPointClick={props.onPointClick} ariaLabel={`图表（放大）：${title}`} />
              )}
            </div>
          </div>
        </Modal>
      )}
    </Card>
  );
}
