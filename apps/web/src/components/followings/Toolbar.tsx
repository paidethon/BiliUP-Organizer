import type { Group } from "../../api";
import { Select } from "../ui";

export type FlagValue = "" | "stale" | "unwatched" | "never" | "missing" | "important";
export type SortValue = "followed" | "name" | "last_video" | "last_watched";

export interface FollowingsToolbarProps {
  q: string;
  onQChange: (value: string) => void;
  groupId: string;
  onGroupIdChange: (value: string) => void;
  flag: FlagValue;
  onFlagChange: (value: FlagValue) => void;
  sort: SortValue;
  onSortChange: (value: SortValue) => void;
  order: "asc" | "desc";
  onToggleOrder: () => void;
  groups: Group[];
}

const FLAGS: { value: FlagValue; label: string }[] = [
  { value: "", label: "全部状态" },
  { value: "stale", label: "断更（30 天未投稿）" },
  { value: "unwatched", label: "长期未看（14 天+）" },
  { value: "never", label: "从未观看" },
  { value: "missing", label: "已取关" },
  { value: "important", label: "重要分组" },
];

const SORTS: { value: SortValue; label: string }[] = [
  { value: "last_video", label: "最近投稿" },
  { value: "followed", label: "关注时间" },
  { value: "last_watched", label: "最近观看" },
  { value: "name", label: "名称" },
];

export function FollowingsToolbar(props: FollowingsToolbarProps) {
  return (
    <div className="surface p-3 flex flex-wrap items-center gap-2" role="search" aria-label="关注筛选">
      <input
        type="search"
        value={props.q}
        onChange={(e) => props.onQChange(e.target.value)}
        placeholder="搜索 UP 主或签名…"
        aria-label="搜索 UP 主"
        className="bg-slate-900/70 border border-slate-700 rounded-lg px-3 py-1.5 text-sm outline-none focus:border-indigo-400 w-56"
      />
      <label className="flex items-center gap-1 text-xs text-slate-400">
        分组
        <Select
          value={props.groupId}
          onChange={(e) => props.onGroupIdChange(e.target.value)}
          aria-label="按分组筛选"
        >
          <option value="">全部分组</option>
          <option value="none">未分组</option>
          {props.groups.map((g) => (
            <option key={g.id} value={String(g.id)}>
              {g.name}
            </option>
          ))}
        </Select>
      </label>
      <label className="flex items-center gap-1 text-xs text-slate-400">
        状态
        <Select
          value={props.flag}
          onChange={(e) => props.onFlagChange(e.target.value as FlagValue)}
          aria-label="按状态筛选"
        >
          {FLAGS.map((f) => (
            <option key={f.value} value={f.value}>
              {f.label}
            </option>
          ))}
        </Select>
      </label>
      <label className="flex items-center gap-1 text-xs text-slate-400">
        排序
        <Select
          value={props.sort}
          onChange={(e) => props.onSortChange(e.target.value as SortValue)}
          aria-label="排序字段"
        >
          {SORTS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </Select>
      </label>
      <button
        type="button"
        onClick={props.onToggleOrder}
        aria-label={props.order === "desc" ? "当前降序，切换为升序" : "当前升序，切换为降序"}
        className="px-2.5 py-1.5 rounded-lg text-sm bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700"
      >
        {props.order === "desc" ? "↓ 降序" : "↑ 升序"}
      </button>
    </div>
  );
}
