import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Group, type Paged, type UpUser } from "../api";
import { FollowingsToolbar, type FlagValue, type SortValue } from "../components/followings/Toolbar";
import { FollowingsTable } from "../components/followings/Table";
import { FollowingsBulkBar } from "../components/followings/BulkBar";
import { FollowingDetailModal } from "../components/followings/DetailModal";

const PAGE_SIZE = 50;

export default function Followings() {
  const queryClient = useQueryClient();

  // 筛选状态（q 防抖 400ms）
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [groupId, setGroupId] = useState("");
  const [flag, setFlag] = useState<FlagValue>("");
  const [sort, setSort] = useState<SortValue>("last_video");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [detailMid, setDetailMid] = useState<number | null>(null);
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setQ(qInput.trim()), 400);
    return () => window.clearTimeout(timer);
  }, [qInput]);

  // 筛选条件变化时回到第一页
  useEffect(() => {
    setPage(1);
  }, [q, groupId, flag, sort, order]);

  const groupsQuery = useQuery({
    queryKey: ["groups"],
    queryFn: () => api<Group[]>("/groups"),
  });
  const groups = useMemo(() => groupsQuery.data ?? [], [groupsQuery.data]);

  const listQuery = useQuery({
    queryKey: ["followings", "list", { q, groupId, flag, sort, order, page }],
    queryFn: () =>
      api<Paged<UpUser>>("/followings", {
        query: {
          q: q || undefined,
          group_id: groupId || undefined,
          flag: flag || undefined,
          sort,
          order,
          page,
          page_size: PAGE_SIZE,
        },
      }),
  });

  const bulkMutation = useMutation({
    mutationFn: (vars: { action: string; params?: Record<string, unknown> }) =>
      api<{ ok: boolean; changed: number }>("/followings/bulk", {
        method: "POST",
        body: { mids: [...selected], action: vars.action, params: vars.params ?? {} },
      }),
    onSuccess: (res) => {
      setNotice({ tone: "ok", text: `已更新 ${res.changed} 个 UP 主` });
      setSelected(new Set());
      void queryClient.invalidateQueries({ queryKey: ["followings"] });
      void queryClient.invalidateQueries({ queryKey: ["groups"] });
    },
    onError: (err) => {
      setNotice({ tone: "error", text: err instanceof ApiError ? err.message : "批量操作失败，请重试" });
    },
  });

  function toggle(mid: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(mid)) next.delete(mid);
      else next.add(mid);
      return next;
    });
  }

  function toggleAll() {
    const items = listQuery.data?.items ?? [];
    setSelected((prev) => {
      const allChecked = items.length > 0 && items.every((up) => prev.has(up.mid));
      return allChecked ? new Set<number>() : new Set(items.map((up) => up.mid));
    });
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">关注管理</h1>
        {listQuery.data && (
          <span className="text-xs text-slate-500">
            共 {listQuery.data.total} 个 UP 主 · 每页 {PAGE_SIZE} 条
          </span>
        )}
      </header>

      <FollowingsToolbar
        q={qInput}
        onQChange={setQInput}
        groupId={groupId}
        onGroupIdChange={setGroupId}
        flag={flag}
        onFlagChange={setFlag}
        sort={sort}
        onSortChange={setSort}
        order={order}
        onToggleOrder={() => setOrder((o) => (o === "desc" ? "asc" : "desc"))}
        groups={groups}
      />

      {notice && (
        <p
          className={`text-xs px-3 py-2 rounded-lg ${notice.tone === "ok" ? "text-emerald-300 bg-emerald-500/10" : "text-red-300 bg-red-500/10"}`}
          role="status"
          aria-live="polite"
        >
          {notice.text}
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="关闭提示"
            className="ml-2 underline underline-offset-2 hover:text-white"
          >
            关闭
          </button>
        </p>
      )}

      {selected.size > 0 && (
        <FollowingsBulkBar
          selectedCount={selected.size}
          groups={groups}
          pending={bulkMutation.isPending}
          onSetGroup={(gid) => bulkMutation.mutate({ action: "set_group", params: { group_id: gid } })}
          onClearGroup={() => bulkMutation.mutate({ action: "clear_group" })}
          onMarkWatched={() => bulkMutation.mutate({ action: "mark_watched" })}
          onBlacklist={() => bulkMutation.mutate({ action: "blacklist", params: { value: true } })}
          onRestore={() => bulkMutation.mutate({ action: "restore" })}
          onSnooze={() => bulkMutation.mutate({ action: "snooze", params: { days: 7 } })}
          onClearSelection={() => setSelected(new Set())}
        />
      )}

      <FollowingsTable
        items={listQuery.data?.items ?? []}
        loading={listQuery.isLoading}
        error={listQuery.error instanceof Error ? listQuery.error.message : listQuery.error ? String(listQuery.error) : null}
        total={listQuery.data?.total ?? 0}
        page={page}
        pageSize={PAGE_SIZE}
        selected={selected}
        groups={groups}
        onToggle={toggle}
        onToggleAll={toggleAll}
        onDetail={setDetailMid}
        onPageChange={setPage}
      />

      <FollowingDetailModal mid={detailMid} onClose={() => setDetailMid(null)} />
    </div>
  );
}
