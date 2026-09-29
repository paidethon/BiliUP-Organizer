import type { Suggestion } from "../../api";
import { Badge, EmptyState, ErrorState, Spinner } from "../ui";
import { formatDate, relativeTime } from "../followings/helpers";

export interface SuggestionListProps {
  items: Suggestion[];
  loading: boolean;
  error: string | null;
  selected: Set<number>;
  /** 仅 pending 建议可操作；accepted/rejected 视图隐藏操作按钮。 */
  actionable: boolean;
  pendingDecision: boolean;
  onToggle: (id: number) => void;
  onToggleAll: () => void;
  onDecide: (ids: number[], decision: "accept" | "reject") => void;
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  const low = value < 0.6;
  return (
    <div className="flex items-center gap-2 min-w-[120px]" title={`置信度 ${pct}%`}>
      <div
        className="h-1.5 w-20 rounded-full bg-slate-700/60 overflow-hidden"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`置信度 ${pct}%`}
      >
        <div className={`h-full rounded-full ${low ? "bg-amber-400" : "bg-emerald-400"}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs tabular-nums ${low ? "text-amber-300" : "text-slate-400"}`}>{pct}%</span>
    </div>
  );
}

const STATUS_BADGE: Record<string, { label: string; tone: "info" | "ok" | "warn" | "danger" }> = {
  pending: { label: "待审核", tone: "warn" },
  accepted: { label: "已通过", tone: "ok" },
  rejected: { label: "已拒绝", tone: "danger" },
};

export function SuggestionList(props: SuggestionListProps) {
  const { items, loading, error, selected, actionable, pendingDecision } = props;
  const allChecked = items.length > 0 && items.every((s) => selected.has(s.id));

  if (loading) return <Spinner label="正在加载建议队列…" />;
  if (error) return <ErrorState message={error} />;

  return (
    <div className="surface overflow-hidden">
      <table className="w-full text-sm">
        <caption className="sr-only">AI 分组建议列表</caption>
        <thead>
          <tr className="text-left text-xs text-slate-400 border-b border-slate-700/60">
            {actionable && (
              <th scope="col" className="px-3 py-2 w-10">
                <input type="checkbox" checked={allChecked} onChange={props.onToggleAll} aria-label="全选本页建议" />
              </th>
            )}
            <th scope="col" className="px-3 py-2">UP 主</th>
            <th scope="col" className="px-3 py-2">建议分组</th>
            <th scope="col" className="px-3 py-2">置信度</th>
            <th scope="col" className="px-3 py-2">理由</th>
            <th scope="col" className="px-3 py-2">模型 / 时间</th>
            <th scope="col" className="px-3 py-2">状态</th>
            {actionable && <th scope="col" className="px-3 py-2 w-32">操作</th>}
          </tr>
        </thead>
        <tbody>
          {items.length === 0 && (
            <tr>
              <td colSpan={actionable ? 7 : 5}>
                <EmptyState title="队列为空" hint="没有该状态的建议，可尝试运行 AI 分类生成新建议" />
              </td>
            </tr>
          )}
          {items.map((s) => {
            const status = STATUS_BADGE[s.status] ?? { label: s.status, tone: "info" as const };
            return (
              <tr key={s.id} className="border-b border-slate-800/60 hover:bg-white/[0.03] align-top">
                {actionable && (
                  <td className="px-3 py-3">
                    <input
                      type="checkbox"
                      checked={selected.has(s.id)}
                      onChange={() => props.onToggle(s.id)}
                      aria-label={`选择 ${s.up_uname || `mid:${s.up_mid}`} 的建议`}
                    />
                  </td>
                )}
                <td className="px-3 py-3 font-medium">
                  {s.up_uname || <span className="text-slate-500">mid:{s.up_mid}</span>}
                </td>
                <td className="px-3 py-3">
                  {s.suggested_group_name ? (
                    <Badge tone="info">{s.suggested_group_name}</Badge>
                  ) : (
                    <span className="text-xs text-slate-500">未指定</span>
                  )}
                </td>
                <td className="px-3 py-3">
                  <ConfidenceBar value={s.confidence} />
                </td>
                <td className="px-3 py-3 max-w-[280px]">
                  <p className="text-xs text-slate-400 whitespace-pre-wrap break-words">{s.rationale || "—"}</p>
                </td>
                <td className="px-3 py-3 whitespace-nowrap text-xs text-slate-500">
                  <p className="truncate max-w-[140px]" title={s.model}>
                    {s.model || "—"}
                  </p>
                  <p title={formatDate(s.created_at)}>{relativeTime(s.created_at)}</p>
                </td>
                <td className="px-3 py-3">
                  <Badge tone={status.tone}>{status.label}</Badge>
                </td>
                {actionable && (
                  <td className="px-3 py-3">
                    <div className="flex gap-1.5">
                      <button
                        type="button"
                        disabled={pendingDecision}
                        onClick={() => props.onDecide([s.id], "accept")}
                        aria-label={`通过 ${s.up_uname || `mid:${s.up_mid}`} 的建议`}
                        className="px-2 py-1 rounded-lg text-xs bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50"
                      >
                        通过
                      </button>
                      <button
                        type="button"
                        disabled={pendingDecision}
                        onClick={() => props.onDecide([s.id], "reject")}
                        aria-label={`拒绝 ${s.up_uname || `mid:${s.up_mid}`} 的建议`}
                        className="px-2 py-1 rounded-lg text-xs bg-red-500/10 text-red-300 hover:bg-red-500/20 disabled:opacity-50"
                      >
                        拒绝
                      </button>
                    </div>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
