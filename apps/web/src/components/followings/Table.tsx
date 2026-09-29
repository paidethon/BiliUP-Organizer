import type { Group, UpUser } from "../../api";
import { Badge, EmptyState, ErrorState, Spinner } from "../ui";
import { GroupBadge, UpAvatar, daysSince, relativeTime } from "./helpers";

export interface FollowingsTableProps {
  items: UpUser[];
  loading: boolean;
  error: string | null;
  total: number;
  page: number;
  pageSize: number;
  selected: Set<number>;
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

function groupOf(groups: Group[], up: UpUser): Group | undefined {
  return up.group_id == null ? undefined : groups.find((g) => g.id === up.group_id);
}

export function FollowingsTable(props: FollowingsTableProps) {
  const { items, loading, error, total, page, pageSize, selected, groups } = props;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const allChecked = items.length > 0 && items.every((up) => selected.has(up.mid));

  if (loading) return <Spinner label="正在加载关注列表…" />;
  if (error) return <ErrorState message={error} />;

  return (
    <div className="surface overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[860px]">
          <caption className="sr-only">关注 UP 主列表</caption>
          <thead>
            <tr className="text-left text-xs text-slate-400 border-b border-slate-700/60">
              <th scope="col" className="px-3 py-2 w-10">
                <input
                  type="checkbox"
                  checked={allChecked}
                  onChange={props.onToggleAll}
                  aria-label="全选本页"
                />
              </th>
              <th scope="col" className="px-3 py-2">UP 主</th>
              <th scope="col" className="px-3 py-2">分组</th>
              <th scope="col" className="px-3 py-2">最近投稿</th>
              <th scope="col" className="px-3 py-2">最近观看</th>
              <th scope="col" className="px-3 py-2 w-20">已看</th>
              <th scope="col" className="px-3 py-2">状态</th>
              <th scope="col" className="px-3 py-2 w-16">操作</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan={8}>
                  <EmptyState title="没有符合条件的关注" hint="试试调整筛选条件，或先执行一次同步" />
                </td>
              </tr>
            )}
            {items.map((up) => {
              const days = daysSince(up.last_video_at);
              const stale = days == null || days > 30;
              return (
                <tr key={up.mid} className="border-b border-slate-800/60 hover:bg-white/[0.03]">
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      checked={selected.has(up.mid)}
                      onChange={() => props.onToggle(up.mid)}
                      aria-label={`选择 ${up.uname}`}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <UpAvatar face={up.face} uname={up.uname} />
                      <div className="min-w-0">
                        <p className="truncate max-w-[220px] font-medium">{up.uname}</p>
                        {up.sign && (
                          <p className="truncate max-w-[220px] text-xs text-slate-500" title={up.sign}>
                            {up.sign}
                          </p>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <GroupBadge color={groupOf(groups, up)?.color} name={up.group_name} />
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
                    <div className="flex flex-wrap gap-1">
                      {up.missing && <Badge tone="danger">已取关</Badge>}
                      {up.blacklisted && <Badge tone="danger">黑名单</Badge>}
                      {snoozeActive(up) && <Badge tone="info">已暂停</Badge>}
                      {!up.missing && !up.blacklisted && !snoozeActive(up) && <Badge tone="ok">正常</Badge>}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => props.onDetail(up.mid)}
                      aria-label={`查看 ${up.uname} 详情`}
                      className="text-xs text-indigo-300 hover:text-indigo-200 underline underline-offset-2"
                    >
                      详情
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
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
    </div>
  );
}
