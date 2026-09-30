import type { ReactNode } from "react";
import type { Group } from "../../api";

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
      <div className="flex flex-wrap gap-1.5">{children}</div>
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
        当前：{activeSort?.label} {props.order === "desc" ? "降序" : "升序"}
        {props.groupId === "none" ? " · 未分组" : ""}
        {props.flag ? ` · ${FLAGS.find((f) => f.value === props.flag)?.label}` : ""}
      </p>
    </div>
  );
}
