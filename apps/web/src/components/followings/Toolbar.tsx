import type { ReactNode } from "react";
import type { Group } from "../../api";
import { Select } from "../ui";
import type { DisplayMode, PageSizeValue } from "./useFollowingsUrl";

export type FlagValue = "" | "stale" | "unwatched" | "never" | "missing" | "important";
export type SortValue = "followed" | "name" | "last_video" | "last_watched";

export interface StatusLabelCount {
  label: string;
  count: number;
}

export interface FollowingsToolbarProps {
  q: string;
  onQChange: (value: string) => void;
  groupId: string;
  onGroupIdChange: (value: string) => void;
  flag: FlagValue;
  onFlagChange: (value: FlagValue) => void;
  status: string;
  onStatusChange: (value: string) => void;
  statuses: StatusLabelCount[];
  sort: SortValue;
  onSortChange: (value: SortValue) => void;
  order: "asc" | "desc";
  onToggleOrder: () => void;
  mode: DisplayMode;
  onModeChange: (mode: DisplayMode) => void;
  pageSize: PageSizeValue;
  onPageSizeChange: (size: PageSizeValue) => void;
  groups: Group[];
}

const FLAGS: { value: FlagValue; label: string; title: string }[] = [
  { value: "", label: "全部", title: "所有状态" },
  { value: "stale", label: "断更", title: "30 天未投稿" },
  { value: "unwatched", label: "长期未看", title: "14 天以上未观看" },
  { value: "never", label: "从未观看", title: "关注后累计观看为 0" },
  { value: "missing", label: "已取关", title: "B 站侧已取消关注" },
  { value: "important", label: "重要", title: "位于标记为重要的分组" },
];

const SORTS: { value: SortValue; label: string }[] = [
  { value: "last_video", label: "最近投稿" },
  { value: "followed", label: "关注时间" },
  { value: "last_watched", label: "最近观看" },
  { value: "name", label: "名称" },
];

function Chip({
  selected,
  onClick,
  children,
  title,
  ariaLabel,
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
  title?: string;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      title={title}
      aria-label={ariaLabel}
      onClick={onClick}
      className={`px-3 py-1 rounded-full text-xs border transition-colors ${
        selected
          ? "btn-grad text-white border-transparent shadow-sm"
          : "bg-slate-800/50 border-slate-700 text-slate-300 hover:text-white hover:border-slate-500"
      }`}
    >
      {children}
    </button>
  );
}

function FilterRow({ label, ariaLabel, children }: { label: string; ariaLabel: string; children: ReactNode }) {
  return (
    <div className="flex gap-3" role="group" aria-label={ariaLabel}>
      <span className="w-10 shrink-0 pt-1 text-xs text-slate-500" aria-hidden="true">
        {label}
      </span>
      <div className="flex flex-wrap gap-1.5 items-center">{children}</div>
    </div>
  );
}

export function FollowingsToolbar(props: FollowingsToolbarProps) {
  const activeSort = SORTS.find((s) => s.value === props.sort);
  return (
    <div className="surface glow p-4 space-y-3" role="search" aria-label="关注筛选">
      <input
        type="search"
        value={props.q}
        onChange={(e) => props.onQChange(e.target.value)}
        placeholder="搜索 UP 主或签名…"
        aria-label="搜索 UP 主"
        className="w-full bg-slate-900/70 border border-slate-700 rounded-[var(--lumi-radius-sm)] px-3 py-2 text-sm outline-none focus:border-indigo-400"
      />

      <FilterRow label="显示" ariaLabel="显示模式">
        <Chip selected={props.mode === "paged"} onClick={() => props.onModeChange("paged")} title="服务器分页浏览">
          分页
        </Chip>
        <Chip selected={props.mode === "all"} onClick={() => props.onModeChange("all")} title="一次显示全部筛选结果（虚拟滚动）">
          全部
        </Chip>
        {props.mode === "paged" && (
          <span className="flex items-center gap-1.5 text-xs text-slate-500 ml-1">
            <label htmlFor="followings-page-size">每页数量</label>
            <Select
              id="followings-page-size"
              aria-label="每页数量"
              value={String(props.pageSize)}
              onChange={(e) => props.onPageSizeChange(Number(e.target.value) as PageSizeValue)}
              className="py-0.5 text-xs"
            >
              <option value="50">50</option>
              <option value="100">100</option>
              <option value="200">200</option>
            </Select>
          </span>
        )}
      </FilterRow>

      <FilterRow label="分组" ariaLabel="分组筛选">
        <Chip selected={props.groupId === ""} onClick={() => props.onGroupIdChange("")}>
          全部
        </Chip>
        <Chip selected={props.groupId === "none"} onClick={() => props.onGroupIdChange("none")}>
          未分组
        </Chip>
        {props.groups.map((g) => (
          <Chip
            key={g.id}
            selected={props.groupId === String(g.id)}
            onClick={() => props.onGroupIdChange(props.groupId === String(g.id) ? "" : String(g.id))}
          >
            {g.name}
          </Chip>
        ))}
      </FilterRow>

      <FilterRow label="状态" ariaLabel="状态筛选">
        {FLAGS.map((f) => (
          <Chip
            key={f.value}
            selected={props.flag === f.value}
            onClick={() => props.onFlagChange(props.flag === f.value ? "" : f.value)}
            title={f.title}
          >
            {f.label}
          </Chip>
        ))}
      </FilterRow>

      {props.statuses.length > 0 && (
        <FilterRow label="分类" ariaLabel="分类状态筛选">
          {props.statuses.map((s) => (
            <Chip
              key={s.label}
              selected={props.status === s.label}
              onClick={() => props.onStatusChange(props.status === s.label ? "" : s.label)}
              title={`按状态标签「${s.label}」筛选（${s.count} 个 UP）`}
            >
              {s.label}（{s.count}）
            </Chip>
          ))}
        </FilterRow>
      )}

      <FilterRow label="排序" ariaLabel="排序筛选">
        {SORTS.map((s) => {
          const active = props.sort === s.value;
          return (
            <Chip
              key={s.value}
              selected={active}
              onClick={() => (active ? props.onToggleOrder() : props.onSortChange(s.value))}
              ariaLabel={
                active
                  ? `当前按${s.label}${props.order === "desc" ? "降序" : "升序"}，再次点击切换方向`
                  : `按${s.label}排序`
              }
              title={active ? "再次点击切换升/降序" : undefined}
            >
              {s.label}
              {active && <span aria-hidden="true">{props.order === "desc" ? " ↓" : " ↑"}</span>}
            </Chip>
          );
        })}
      </FilterRow>

      <p className="text-xs text-slate-600" aria-live="polite">
        当前：{props.mode === "all" ? "全部模式" : `分页 · 每页 ${props.pageSize} 条`} · {activeSort?.label}{" "}
        {props.order === "desc" ? "降序" : "升序"}
        {props.groupId === "none" ? " · 未分组" : ""}
        {props.flag ? ` · ${FLAGS.find((f) => f.value === props.flag)?.label}` : ""}
        {props.status ? ` · 状态标签 ${props.status}` : ""}
      </p>
    </div>
  );
}
