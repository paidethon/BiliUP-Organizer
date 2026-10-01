import { useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Group, UpUser } from "../../api";
import { Badge, EmptyState, ErrorState } from "../ui";
import { GroupBadge, StatusLabelBadge, TagBadge, UpAvatar, daysSince, relativeTime } from "./helpers";
import type { DisplayMode } from "./useFollowingsUrl";

/** 虚拟滚动行高（固定值，与 estimateSize 一致）。 */
const ROW_HEIGHT = 64;
const OVERSCAN = 8;
const COLS = 8;
const MAX_TAG_BADGES = 2;

export interface FollowingsTableProps {
  items: UpUser[];
  loading: boolean;
  error: string | null;
  total: number;
  page: number;
  pageSize: number;
  mode: DisplayMode;
  selected: Set<number>;
  /** 全选筛选结果模式：勾选态 = 筛选全集 − excluded。 */
  selectAllFiltered: boolean;
  excluded: Set<number>;
  filtersActive: boolean;
  groups: Group[];
  onToggle: (mid: number) => void;
  onToggleAll: () => void;
  onDetail: (mid: number) => void;
  onPageChange: (page: number) => void;
}

function snoozeActive(up: UpUser): boolean {
  if (!up.snoozed_until) return false;
  return new Date(up.snoozed_until.replace(" ", "T")).getTime() > Date.now();
}

function groupsOf(groups: Group[], up: UpUser): Group[] {
  if (up.groups?.length) {
    return up.groups
      .map((brief) => groups.find((g) => g.id === brief.id))
      .filter((g): g is Group => Boolean(g));
  }
  return up.group_id == null ? [] : groups.filter((g) => g.id === up.group_id);
}

function TableRow({
  up,
  checked,
  groups,
  onToggle,
  onDetail,
}: {
  up: UpUser;
  checked: boolean;
  groups: Group[];
  onToggle: (mid: number) => void;
  onDetail: (mid: number) => void;
}) {
  const days = daysSince(up.last_video_at);
  const stale = days == null || days > 30;
  const upGroups = groupsOf(groups, up);
  const tags = up.tags ?? [];
  const visibleTags = tags.slice(0, MAX_TAG_BADGES);
  const extraTags = tags.slice(MAX_TAG_BADGES);
  const statuses = up.status_labels ?? [];
  const hasFlag =
    up.missing || up.blacklisted || snoozeActive(up) || statuses.length > 0;

  return (
    <tr className="border-b border-slate-800/60 hover:bg-white/[0.03] h-16">
      <td className="px-3 py-2">
        <input
          type="checkbox"
          checked={checked}
          onChange={() => onToggle(up.mid)}
          aria-label={`选择 ${up.uname}`}
        />
      </td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2 min-w-0">
          <UpAvatar face={up.face} uname={up.uname} />
          <div className="min-w-0 max-w-[220px]">
            <p className="truncate font-medium" title={up.uname}>
              {up.uname}
            </p>
            {up.sign && (
              <p className="truncate text-xs text-slate-500" title={up.sign}>
                {up.sign}
              </p>
            )}
          </div>
        </div>
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap items-center gap-1 max-w-[200px]">
          {upGroups.map((g) => (
            <GroupBadge key={g.id} color={g.color} name={g.name} />
          ))}
          {upGroups.length === 0 && <span className="text-xs text-slate-500">未分组</span>}
          {visibleTags.map((t) => (
            <TagBadge key={t.id} name={t.name} color={t.color} />
          ))}
          {extraTags.length > 0 && (
            <span className="text-xs text-slate-500" title={extraTags.map((t) => t.name).join("、")}>
              +{extraTags.length}
            </span>
          )}
        </div>
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        {up.last_video_at ? (
          <span title={up.last_video_title ?? undefined}>
            <span className={stale ? "text-amber-400" : "text-slate-300"}>{relativeTime(up.last_video_at)}</span>
            <span className="text-xs text-slate-500 ml-1">（{days ?? "?"} 天前）</span>
          </span>
        ) : (
          <span className="text-slate-500">—</span>
        )}
      </td>
      <td className="px-3 py-2 whitespace-nowrap text-slate-300">
        {up.last_watched_at ? relativeTime(up.last_watched_at) : <span className="text-slate-500">从未</span>}
      </td>
      <td className="px-3 py-2 text-slate-300">{up.watched_count}</td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1 max-w-[200px]">
          {up.missing && <Badge tone="danger">已取关</Badge>}
          {up.blacklisted && <Badge tone="danger">黑名单</Badge>}
          {snoozeActive(up) && <Badge tone="info">已暂停</Badge>}
          {statuses.map((label) => (
            <StatusLabelBadge key={label} label={label} />
          ))}
          {!hasFlag && <Badge tone="ok">正常</Badge>}
        </div>
      </td>
      <td className="px-3 py-2">
        <button
          type="button"
          onClick={() => onDetail(up.mid)}
          aria-label={`查看 ${up.uname} 详情`}
          className="text-xs text-indigo-300 hover:text-indigo-200 underline underline-offset-2"
        >
          详情
        </button>
      </td>
    </tr>
  );
}

function SpacerRow({ height }: { height: number }) {
  if (height <= 0) return null;
  return (
    <tr aria-hidden="true">
      <td colSpan={COLS} style={{ height, padding: 0, border: "none" }} />
    </tr>
  );
}

export function FollowingsTable(props: FollowingsTableProps) {
  const {
    items,
    loading,
    error,
    total,
    page,
    pageSize,
    mode,
    selected,
    selectAllFiltered,
    excluded,
    filtersActive,
    groups,
  } = props;
  const virtualized = mode === "all";
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const rowVirtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: OVERSCAN,
  });

  if (error) return <ErrorState message={error} />;

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const isChecked = (mid: number) => (selectAllFiltered ? !excluded.has(mid) : selected.has(mid));
  const allChecked = items.length > 0 && items.every((up) => isChecked(up.mid));
  const virtualRows = virtualized ? rowVirtualizer.getVirtualItems() : [];
  const lastVirtual = virtualRows[virtualRows.length - 1];
  const topPad = virtualRows.length > 0 ? virtualRows[0].start : 0;
  const bottomPad =
    virtualRows.length > 0 ? rowVirtualizer.getTotalSize() - (lastVirtual.start + lastVirtual.size) : 0;
  const showSkeleton = loading && items.length === 0;

  return (
    <div className="surface overflow-hidden">
      <div
        ref={virtualized ? scrollRef : undefined}
        role="region"
        aria-label="关注列表"
        className={virtualized ? "overflow-auto max-h-[65vh]" : "overflow-x-auto"}
      >
        <table className="w-full text-sm min-w-[860px]">
          <caption className="sr-only">关注 UP 主列表</caption>
          <thead>
            <tr className="text-left text-xs text-slate-400 border-b border-slate-700/60">
              <th
                scope="col"
                className={`px-3 py-2 w-10 ${virtualized ? "sticky top-0 z-10 bg-slate-900" : ""}`}
              >
                <input
                  type="checkbox"
                  checked={allChecked}
                  onChange={props.onToggleAll}
                  aria-label={virtualized ? "全选当前结果" : "全选本页"}
                />
              </th>
              {["UP 主", "分组", "最近投稿", "最近观看", "已看", "状态", "操作"].map((label, i) => (
                <th
                  key={label}
                  scope="col"
                  className={`px-3 py-2 ${i === 4 ? "w-20" : ""} ${virtualized ? "sticky top-0 z-10 bg-slate-900" : ""}`}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {showSkeleton &&
              Array.from({ length: 8 }, (_, i) => (
                <tr key={`skeleton-${i}`} className="border-b border-slate-800/60">
                  <td colSpan={COLS} className="px-3 py-3">
                    <div
                      className="h-4 rounded bg-slate-800/80 animate-pulse"
                      style={{ width: `${52 + ((i * 11) % 36)}%` }}
                    />
                  </td>
                </tr>
              ))}
            {!showSkeleton && items.length === 0 && (
              <tr>
                <td colSpan={COLS}>
                  {filtersActive || page > 1 ? (
                    <EmptyState title="没有符合条件的关注" hint="试试调整筛选条件，或回到第一页" />
                  ) : (
                    <EmptyState title="还没有关注数据" hint="先执行一次同步，把 B 站关注列表同步过来" />
                  )}
                </td>
              </tr>
            )}
            {virtualRows.length > 0 && <SpacerRow height={topPad} />}
            {virtualRows.map((virtualRow) => {
              const up = items[virtualRow.index];
              return (
                <TableRow
                  key={up.mid}
                  up={up}
                  checked={isChecked(up.mid)}
                  groups={groups}
                  onToggle={props.onToggle}
                  onDetail={props.onDetail}
                />
              );
            })}
            {virtualRows.length === 0 &&
              !showSkeleton &&
              items.map((up) => (
                <TableRow
                  key={up.mid}
                  up={up}
                  checked={isChecked(up.mid)}
                  groups={groups}
                  onToggle={props.onToggle}
                  onDetail={props.onDetail}
                />
              ))}
            {virtualRows.length > 0 && <SpacerRow height={bottomPad} />}
          </tbody>
        </table>
      </div>
      {mode === "paged" ? (
        <div className="flex items-center justify-between px-3 py-2 border-t border-slate-700/60 text-xs text-slate-400">
          <span>
            共 {total} 条 · 第 {page} / {totalPages} 页
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => props.onPageChange(page - 1)}
              aria-label="上一页"
              className="px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40"
            >
              上一页
            </button>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => props.onPageChange(page + 1)}
              aria-label="下一页"
              className="px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40"
            >
              下一页
            </button>
          </div>
        </div>
      ) : (
        <div
          className="px-3 py-2 border-t border-slate-700/60 text-xs text-slate-400"
          style={{ backgroundColor: "color-mix(in srgb, var(--lumi-surface) 94%, transparent)" }}
        >
          共 {total} 个 UP 主 · 已全部显示
        </div>
      )}
    </div>
  );
}
