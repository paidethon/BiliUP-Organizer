// Data-table view for charts: scrollable, sticky header, sorted by the order
// the rows are given (charts decide the sort). Numeric null renders as "—".

export interface TableColumn {
  label: string;
  align?: "left" | "right";
}

export function ChartDataTable({
  columns,
  rows,
  maxRows = 500,
}: {
  columns: TableColumn[];
  rows: Array<Array<string | number | null | undefined>>;
  maxRows?: number;
}) {
  const shown = rows.slice(0, maxRows);
  return (
    <div className="overflow-auto max-h-[420px] rounded-lg border border-slate-700/60">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-slate-900/95 backdrop-blur">
          <tr>
            {columns.map((c) => (
              <th
                key={c.label}
                className={`px-2.5 py-2 font-medium text-slate-400 border-b border-slate-700/60 ${
                  c.align === "right" ? "text-right" : "text-left"
                }`}
                scope="col"
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, i) => (
            <tr key={i} className="odd:bg-white/[0.02]">
              {row.map((cell, j) => (
                <td
                  key={j}
                  className={`px-2.5 py-1.5 border-b border-slate-800/60 ${
                    columns[j]?.align === "right" ? "text-right tabular-nums" : "text-left"
                  }`}
                >
                  {cell === null || cell === undefined ? "—" : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > maxRows && (
        <p className="px-2.5 py-1.5 text-[11px] text-slate-500">
          仅显示前 {maxRows} 行（共 {rows.length} 行），完整数据请导出 CSV。
        </p>
      )}
    </div>
  );
}
