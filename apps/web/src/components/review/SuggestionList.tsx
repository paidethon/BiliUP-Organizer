import { useMemo } from "react";
import type { Group, Suggestion } from "../../api";
import { EmptyState, ErrorState } from "../ui";
import { ReviewCard, type ReviewDecision } from "./ReviewCard";

export interface SuggestionListProps {
  items: Suggestion[];
  loading: boolean;
  error: string | null;
  selected: Set<number>;
  skipped: Set<number>;
  /** 仅待审核视图提供勾选与操作；其余状态只读展示。 */
  actionable: boolean;
  pendingDecision: boolean;
  groups: Group[];
  onToggle: (id: number) => void;
  onToggleAll: () => void;
  onDecide: (id: number, decision: ReviewDecision) => void;
  onSkip: (id: number) => void;
  onEditAccept: (s: Suggestion, groupId: number | null, tags: string[]) => void;
}

function SkeletonCard() {
  return (
    <div className="surface p-4 space-y-3" aria-hidden="true">
      <div className="flex items-center gap-3">
        <div className="h-9 w-9 rounded-full bg-slate-800 animate-pulse" />
        <div className="flex-1 space-y-2">
          <div className="h-3.5 w-40 rounded bg-slate-800 animate-pulse" />
          <div className="h-3 w-64 rounded bg-slate-800/70 animate-pulse" />
        </div>
        <div className="h-3 w-24 rounded bg-slate-800 animate-pulse" />
      </div>
      <div className="h-3 w-full rounded bg-slate-800/70 animate-pulse" />
      <div className="h-3 w-2/3 rounded bg-slate-800/50 animate-pulse" />
    </div>
  );
}

export function SuggestionList(props: SuggestionListProps) {
  const { items, loading, error, selected, skipped, actionable } = props;
  const selectable = useMemo(() => items.filter((s) => s.status === "pending"), [items]);
  // 跳过的卡片沉底，靠前的未处理项自然成为下一张
  const ordered = useMemo(
    () => [...items].sort((a, b) => Number(skipped.has(a.id)) - Number(skipped.has(b.id))),
    [items, skipped],
  );
  const allChecked = selectable.length > 0 && selectable.every((s) => selected.has(s.id));

  if (loading) {
    return (
      <div className="space-y-3" role="status" aria-label="正在加载建议队列">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }
  if (error) return <ErrorState message={error} />;

  if (items.length === 0) {
    return (
      <EmptyState
        title={actionable ? "没有待审核的建议" : "没有符合条件的建议"}
        hint="可尝试运行 AI 分类生成新建议，或调整筛选条件"
      />
    );
  }

  return (
    <div className="space-y-3">
      {actionable && items.length > 0 && (
        <div className="flex items-center gap-3 px-1">
          <label className="flex items-center gap-1.5 text-xs text-slate-400">
            <input type="checkbox" checked={allChecked} onChange={props.onToggleAll} aria-label="全选本页" />
            全选本页
          </label>
          {selected.size > 0 && <span className="text-xs text-slate-500">已选 {selected.size} 条</span>}
        </div>
      )}
      <div role="table" aria-label="AI 分组建议列表" className="space-y-3">
        {ordered.map((s) => (
          <ReviewCard
            key={s.id}
            suggestion={s}
            actionable={actionable}
            selected={selected.has(s.id)}
            skipped={skipped.has(s.id)}
            pendingDecision={props.pendingDecision}
            groups={props.groups}
            onToggle={props.onToggle}
            onDecide={props.onDecide}
            onSkip={props.onSkip}
            onEditAccept={props.onEditAccept}
          />
        ))}
      </div>
    </div>
  );
}
