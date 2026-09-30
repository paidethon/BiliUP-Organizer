import type { Group } from "../../api";
import { Button, Select } from "../ui";

export interface BulkBarProps {
  selectedCount: number;
  groups: Group[];
  pending: boolean;
  targetGroup: string;
  onTargetGroupChange: (value: string) => void;
  onAddToGroup: () => void;
  onRemoveFromGroup: () => void;
  onSetGroup: (groupId: number) => void;
  onClearGroup: () => void;
  onMarkWatched: () => void;
  onBlacklist: () => void;
  onRestore: () => void;
  onSnooze: () => void;
  onClearSelection: () => void;
}

export function FollowingsBulkBar(props: BulkBarProps) {
  const count = props.selectedCount;

  return (
    <div
      className="surface glow p-3 flex flex-wrap items-center gap-2 text-sm"
      role="toolbar"
      aria-label={`已选中 ${count} 个 UP 的批量操作`}
    >
      <span className="text-slate-300">
        已选 <strong className="text-indigo-300">{count}</strong> 个
      </span>
      <div className="flex items-center gap-1">
        <Select
          value={props.targetGroup}
          onChange={(e) => props.onTargetGroupChange(e.target.value)}
          aria-label="选择目标分组"
          className="min-w-[140px]"
        >
          <option value="">选择分组…</option>
          {props.groups.map((g) => (
            <option key={g.id} value={String(g.id)}>
              {g.name}
            </option>
          ))}
        </Select>
        <Button
          variant="primary"
          disabled={!props.targetGroup || props.pending}
          onClick={props.onAddToGroup}
        >
          添加到分组
        </Button>
        <Button
          variant="subtle"
          disabled={!props.targetGroup || props.pending}
          onClick={props.onRemoveFromGroup}
        >
          从分组移除
        </Button>
        <Button
          variant="ghost"
          disabled={!props.targetGroup || props.pending}
          onClick={() => {
            const gid = Number(props.targetGroup);
            if (!Number.isNaN(gid)) props.onSetGroup(gid);
          }}
        >
          仅设为该组
        </Button>
      </div>
      <Button variant="subtle" disabled={props.pending} onClick={props.onClearGroup} aria-label="清除所选 UP 的全部分组">
        清除全部分组
      </Button>
      <Button variant="subtle" disabled={props.pending} onClick={props.onMarkWatched} aria-label="将所选标记为已看">
        标记已看
      </Button>
      <Button variant="subtle" disabled={props.pending} onClick={props.onBlacklist} aria-label="将所选加入黑名单">
        加入黑名单
      </Button>
      <Button variant="subtle" disabled={props.pending} onClick={props.onRestore} aria-label="恢复所选（清除已取关标记）">
        恢复
      </Button>
      <Button variant="subtle" disabled={props.pending} onClick={props.onSnooze} aria-label="将所选暂停提醒 7 天">
        暂停 7 天
      </Button>
      <button
        type="button"
        onClick={props.onClearSelection}
        aria-label="取消选择"
        className="ml-auto text-xs text-slate-400 hover:text-white underline underline-offset-2"
      >
        取消选择
      </button>
    </div>
  );
}
