import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  ApiError,
  type BulkQuery,
  type Group,
  type Paged,
  type UpUser,
} from "../api";
import { FollowingsToolbar, type StatusLabelCount } from "../components/followings/Toolbar";
import { FollowingsTable } from "../components/followings/Table";
import { FollowingsBulkBar } from "../components/followings/BulkBar";
import { FollowingDetailModal } from "../components/followings/DetailModal";
import { useFollowingsUrl } from "../components/followings/useFollowingsUrl";

interface BulkResult {
  ok: boolean;
  changed: number;
  undo_id: number | null;
}

interface Notice {
  tone: "ok" | "error";
  text: string;
}

export default function Followings() {
  const queryClient = useQueryClient();
  const url = useFollowingsUrl();
  const { view } = url;
  const { q, groupId, flag, status, sort, order, mode, pageSize, page } = view;

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [selectAllFiltered, setSelectAllFiltered] = useState(false);
  const [excluded, setExcluded] = useState<Set<number>>(new Set());
  const [bulkGroup, setBulkGroup] = useState("");
  const [detailMid, setDetailMid] = useState<number | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [undoId, setUndoId] = useState<number | null>(null);

  const groupsQuery = useQuery({
    queryKey: ["groups"],
    queryFn: () => api<Group[]>("/groups"),
  });
  const groups = useMemo(() => groupsQuery.data ?? [], [groupsQuery.data]);

  const statusesQuery = useQuery({
    queryKey: ["followings", "statuses"],
    queryFn: () => api<{ labels: StatusLabelCount[] }>("/followings/statuses"),
  });
  const statuses = useMemo(() => statusesQuery.data?.labels ?? [], [statusesQuery.data]);

  // 两模式缓存严格区分：all 模式 page 固定 1，请求参数 all=true
  const listQuery = useQuery({
    queryKey: ["followings", "list", { q, groupId, flag, status, sort, order, mode, pageSize, page }],
    queryFn: () =>
      api<Paged<UpUser>>("/followings", {
        query: {
          q: q || undefined,
          group_id: groupId || undefined,
          flag: flag || undefined,
          status: status || undefined,
          sort,
          order,
          page: mode === "all" ? 1 : page,
          page_size: pageSize,
          all: mode === "all" ? "true" : undefined,
        },
      }),
  });

  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total ?? 0;
  const filtersActive = Boolean(q || groupId || flag || status);
  const effectiveCount = selectAllFiltered ? Math.max(0, total - excluded.size) : selected.size;

  function clearSelection() {
    setSelected(new Set());
    setExcluded(new Set());
    setSelectAllFiltered(false);
  }

  // 选择集只对产生它时的筛选有效：筛选/排序/模式一变就整体作废，
  // 否则「全选筛选结果 − 排除集」会按新筛选解析出与用户所见不符的范围。
  useEffect(() => {
    setSelected(new Set());
    setExcluded(new Set());
    setSelectAllFiltered(false);
  }, [q, groupId, flag, status, sort, order, mode]);

  const bulkMutation = useMutation({
    mutationFn: (vars: { action: string; params?: Record<string, unknown> }) => {
      // 全选筛选结果 → 按条件整包提交（减去手动取消的）；否则按勾选 mids。均一次请求。
      const body = selectAllFiltered
        ? {
            query: {
              q: q || undefined,
              group_id: groupId || undefined,
              flag: flag || undefined,
              status: status || undefined,
              tag_id: undefined,
              sort,
              order,
            } satisfies BulkQuery,
            exclude_mids: [...excluded],
            action: vars.action,
            params: vars.params ?? {},
          }
        : { mids: [...selected], action: vars.action, params: vars.params ?? {} };
      return api<BulkResult>("/followings/bulk", { method: "POST", body });
    },
    onSuccess: (res) => {
      setNotice({ tone: "ok", text: `已更新 ${res.changed} 个 UP 主` });
      setUndoId(res.undo_id ?? null);
      clearSelection();
      void queryClient.invalidateQueries({ queryKey: ["followings"] });
      void queryClient.invalidateQueries({ queryKey: ["groups"] });
    },
    onError: (err) => {
      setNotice({ tone: "error", text: err instanceof ApiError ? err.message : "批量操作失败，请重试" });
      setUndoId(null);
    },
  });

  const undoMutation = useMutation({
    mutationFn: (recordId: number) =>
      api<{ ok: boolean; restored: number }>(`/followings/undo/${recordId}`, { method: "POST" }),
    onSuccess: (res) => {
      setNotice({ tone: "ok", text: `已撤销（恢复 ${res.restored} 项）` });
      setUndoId(null);
      void queryClient.invalidateQueries({ queryKey: ["followings"] });
      void queryClient.invalidateQueries({ queryKey: ["groups"] });
    },
    onError: (err) => {
      setNotice({ tone: "error", text: err instanceof ApiError ? err.message : "撤销失败，请重试" });
      setUndoId(null);
    },
  });

  // 撤销 toast 8 秒自动消失
  useEffect(() => {
    if (undoId == null) return;
    const timer = window.setTimeout(() => {
      setNotice(null);
      setUndoId(null);
    }, 8000);
    return () => window.clearTimeout(timer);
  }, [undoId]);

  function toggle(mid: number) {
    if (selectAllFiltered) {
      // 全选筛选结果模式：手动取消勾选进入排除集
      setExcluded((prev) => {
        const next = new Set(prev);
        if (next.has(mid)) next.delete(mid);
        else next.add(mid);
        return next;
      });
      return;
    }
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(mid)) next.delete(mid);
      else next.add(mid);
      return next;
    });
  }

  function toggleAll() {
    const isChecked = (mid: number) => (selectAllFiltered ? !excluded.has(mid) : selected.has(mid));
    const allChecked = items.length > 0 && items.every((up) => isChecked(up.mid));
    if (allChecked) {
      // 全部已勾选 → 取消；处于全选筛选结果模式时一并退出该模式
      clearSelection();
      return;
    }
    if (selectAllFiltered) {
      setExcluded((prev) => {
        const next = new Set(prev);
        for (const up of items) next.delete(up.mid);
        return next;
      });
      return;
    }
    setSelected(new Set(items.map((up) => up.mid)));
  }

  function toggleSelectAllFiltered() {
    if (selectAllFiltered) {
      clearSelection();
      return;
    }
    setSelectAllFiltered(true);
    setExcluded(new Set());
    setSelected(new Set());
  }

  function runBulk(action: string, params?: Record<string, unknown>) {
    if (bulkMutation.isPending) return;
    if (!selectAllFiltered && selected.size === 0) return;
    bulkMutation.mutate({ action, params });
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">关注管理</h1>
        {listQuery.data && (
          <span className="text-xs text-slate-500">
            共 {total} 个 UP 主{mode === "all" ? " · 全部模式" : ` · 每页 ${pageSize} 条`}
          </span>
        )}
        <button
          type="button"
          aria-label="选择全部筛选结果"
          aria-pressed={selectAllFiltered}
          disabled={total === 0 || listQuery.isLoading}
          onClick={toggleSelectAllFiltered}
          className={`ml-auto px-3 py-1 rounded-full text-xs border transition-colors ${
            selectAllFiltered
              ? "btn-grad text-white border-transparent shadow-sm"
              : "bg-slate-800/50 border-slate-700 text-slate-300 hover:text-white hover:border-slate-500"
          }`}
        >
          选择全部筛选结果（{total}）
        </button>
      </header>

      <FollowingsToolbar
        q={url.qInput}
        onQChange={url.setQInput}
        groupId={groupId}
        onGroupIdChange={url.setGroupId}
        flag={flag}
        onFlagChange={url.setFlag}
        status={status}
        onStatusChange={url.setStatus}
        statuses={statuses}
        sort={sort}
        onSortChange={url.setSort}
        order={order}
        onToggleOrder={() => url.setOrder(order === "desc" ? "asc" : "desc")}
        mode={mode}
        onModeChange={url.setMode}
        pageSize={pageSize}
        onPageSizeChange={url.setPageSize}
        groups={groups}
      />

      {notice && (
        <p
          className={`text-xs px-3 py-2 rounded-lg ${notice.tone === "ok" ? "text-emerald-300 bg-emerald-500/10" : "text-red-300 bg-red-500/10"}`}
          role="status"
          aria-live="polite"
        >
          {notice.text}
          {undoId != null && (
            <button
              type="button"
              onClick={() => undoMutation.mutate(undoId)}
              disabled={undoMutation.isPending}
              className="ml-2 underline underline-offset-2 hover:text-white"
            >
              撤销
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              setNotice(null);
              setUndoId(null);
            }}
            aria-label="关闭提示"
            className="ml-2 underline underline-offset-2 hover:text-white"
          >
            关闭
          </button>
        </p>
      )}

      {effectiveCount > 0 && (
        <FollowingsBulkBar
          selectedCount={effectiveCount}
          selectAllFiltered={selectAllFiltered}
          groups={groups}
          pending={bulkMutation.isPending}
          targetGroup={bulkGroup}
          onTargetGroupChange={setBulkGroup}
          onAddToGroup={() => {
            if (bulkGroup) runBulk("add_to_group", { group_id: Number(bulkGroup) });
          }}
          onRemoveFromGroup={() => {
            if (bulkGroup) runBulk("remove_from_group", { group_id: Number(bulkGroup) });
          }}
          onSetGroup={(gid) => runBulk("set_group", { group_id: gid })}
          onReplaceGroup={(gid) => runBulk("replace_group", { group_id: gid })}
          onClearGroup={() => runBulk("clear_group")}
          onMarkWatched={() => runBulk("mark_watched")}
          onBlacklist={() => runBulk("blacklist", { value: true })}
          onRestore={() => runBulk("restore")}
          onSnooze={() => runBulk("snooze", { days: 7 })}
          onClearSelection={clearSelection}
        />
      )}

      <FollowingsTable
        items={items}
        loading={listQuery.isLoading}
        error={
          listQuery.error instanceof Error
            ? listQuery.error.message
            : listQuery.error
              ? String(listQuery.error)
              : null
        }
        total={total}
        page={page}
        pageSize={pageSize}
        mode={mode}
        selected={selected}
        selectAllFiltered={selectAllFiltered}
        excluded={excluded}
        filtersActive={filtersActive}
        groups={groups}
        onToggle={toggle}
        onToggleAll={toggleAll}
        onDetail={setDetailMid}
        onPageChange={url.setPage}
      />

      <FollowingDetailModal mid={detailMid} onClose={() => setDetailMid(null)} />
    </div>
  );
}
