import { useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Group } from "../api";
import { Button, Card, EmptyState, ErrorState, Spinner } from "../components/ui";
import { GroupFormModal, type GroupFormValues } from "../components/groups/GroupFormModal";
import { GroupDeleteModal } from "../components/groups/GroupDeleteModal";
import { AliasModal, MergeModal } from "../components/groups/MergeModal";
import { TagManager } from "../components/groups/TagManager";

interface SimilarClusters {
  clusters: { ids: number[]; names: string[] }[];
}

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

export default function Groups() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["groups"],
    queryFn: () => api<Group[]>("/groups"),
  });

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Group | null>(null);
  const [deleting, setDeleting] = useState<Group | null>(null);
  const [merging, setMerging] = useState<Group | null>(null);
  const [aliasing, setAliasing] = useState<Group | null>(null);
  const [formError, setFormError] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [notice, setNotice] = useState("");

  const similarQuery = useQuery({
    queryKey: ["groups", "similar"],
    queryFn: () => api<SimilarClusters>("/groups/similar"),
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["groups"] });
    void queryClient.invalidateQueries({ queryKey: ["followings"] });
  }

  const createMutation = useMutation({
    mutationFn: (values: GroupFormValues) => api("/groups", { method: "POST", body: values }),
    onSuccess: () => {
      setFormOpen(false);
      setFormError("");
      invalidate();
    },
    onError: (err) => setFormError(errText(err, "创建失败，请重试")),
  });

  const updateMutation = useMutation({
    mutationFn: (vars: { id: number; values: Partial<GroupFormValues> }) =>
      api(`/groups/${vars.id}`, { method: "PATCH", body: vars.values }),
    onSuccess: () => {
      setFormOpen(false);
      setEditing(null);
      setFormError("");
      invalidate();
    },
    onError: (err) => setFormError(errText(err, "保存失败，请重试")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api(`/groups/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setDeleting(null);
      setDeleteError("");
      invalidate();
    },
    onError: (err) => setDeleteError(errText(err, "删除失败，请重试")),
  });

  function invalidateWithNotice(message: string) {
    setNotice(message);
    invalidate();
  }

  const reorderMutation = useMutation({
    mutationFn: (updates: { id: number; sort_order: number }[]) =>
      Promise.all(
        updates.map((u) => api(`/groups/${u.id}`, { method: "PATCH", body: { sort_order: u.sort_order } })),
      ),
    onSuccess: () => invalidate(),
  });

  // Drag & drop reorder: the visible number badge is derived from the display
  // index only — group names are never touched.
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [overIndex, setOverIndex] = useState<number | null>(null);

  function commitOrder(list: Group[]) {
    const updates = list
      .map((g, i) => ({ id: g.id, sort_order: i + 1 }))
      .filter((u, i) => list[i].sort_order !== u.sort_order);
    if (!updates.length) return;
    // optimistic: renumber the cached list so the badges move instantly
    queryClient.setQueryData<{ id: number; sort_order: number }[]>(["groups"], (old) =>
      old ? old.map((g) => ({ ...g, sort_order: (list.find((x) => x.id === g.id) as Group).sort_order })) : old,
    );
    reorderMutation.mutate(updates);
  }

  function handleDrop(targetIndex: number) {
    const list = data ?? [];
    if (dragIndex == null || dragIndex === targetIndex || !list.length) return;
    const next = [...list];
    const [moved] = next.splice(dragIndex, 1);
    next.splice(targetIndex, 0, moved);
    setDragIndex(null);
    setOverIndex(null);
    commitOrder(next);
  }

  function handleKeyDown(event: ReactKeyboardEvent, index: number) {
    // keyboard fallback for reorder (accessibility / touch-free devices)
    const dir = event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0;
    if (!dir || !event.altKey || !data) return;
    event.preventDefault();
    const other = index + dir;
    if (other < 0 || other >= data.length) return;
    const next = [...data];
    [next[index], next[other]] = [next[other], next[index]];
    commitOrder(next);
  }

  function submitForm(values: GroupFormValues) {
    setFormError("");
    if (editing) updateMutation.mutate({ id: editing.id, values });
    else createMutation.mutate(values);
  }

  const pending = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">本地分组</h1>
        {data && (
          <span className="text-xs text-slate-500">
            共 {data.length} 个分组 · 覆盖 {data.reduce((sum, g) => sum + g.up_count, 0)} 个 UP
          </span>
        )}
        <div className="ml-auto">
          <Button
            variant="primary"
            onClick={() => {
              setEditing(null);
              setFormError("");
              setFormOpen(true);
            }}
            aria-label="新建分组"
          >
            ＋ 新建分组
          </Button>
        </div>
      </header>

      <p className="text-xs text-slate-500">
        本地分组即 UP 主的内容分类，可任意数量；与 B 站原生分组（上限 20）通过映射同步。
        拖动卡片（或聚焦后按 Alt+↑/↓）调整顺序，序号仅为显示顺序，不会写入分组名称；
        本地分组仅保存在本站，用于筛选、提醒与 AI 建议审核，不会改动 B 站侧的关注列表；
        如需同步到 B 站原生标签，请在「设置」中配置原生分组同步。
      </p>

      {notice && (
        <p className="text-xs text-emerald-300 flex items-center gap-2" role="status">
          {notice}
          <button type="button" className="text-slate-500" onClick={() => setNotice("")} aria-label="关闭提示">
            ✕
          </button>
        </p>
      )}

      {similarQuery.data && similarQuery.data.clusters.length > 0 && (
        <div className="rounded-[var(--lumi-radius)] border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-xs text-amber-200 space-y-1">
          <p>
            发现 {similarQuery.data.clusters.length} 组相似分类，可能需要合并：
          </p>
          <ul className="flex flex-wrap gap-2">
            {similarQuery.data.clusters.map((cluster) => (
              <li key={cluster.ids.join("-")} className="inline-flex items-center gap-1">
                <span>{cluster.names.join(" ≈ ")}</span>
                <Button
                  variant="ghost"
                  className="text-amber-200"
                  onClick={() => setMerging(data?.find((g) => g.id === cluster.ids[0]) ?? null)}
                  aria-label={`合并相似分类 ${cluster.names.join("、")}`}
                >
                  去合并
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {isLoading && <Spinner label="正在加载分组…" />}
      {error && <ErrorState message={errText(error, "加载失败")} />}
      {data && data.length === 0 && (
        <EmptyState title="还没有本地分组" hint="点击右上角「新建分组」，按内容类型整理你的关注" />
      )}

      {data && data.length > 0 && (
        <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" aria-label="分组列表">          {data.map((g, index) => (
            <li
              key={g.id}
              draggable
              onDragStart={(e) => {
                setDragIndex(index);
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", String(index));
              }}
              onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
                setOverIndex(index);
              }}
              onDragLeave={() => setOverIndex((prev) => (prev === index ? null : prev))}
              onDrop={(e) => {
                e.preventDefault();
                handleDrop(index);
              }}
              onDragEnd={() => {
                setDragIndex(null);
                setOverIndex(null);
              }}
              onKeyDown={(e) => handleKeyDown(e, index)}
              tabIndex={0}
              aria-label={`第 ${index + 1} 位：分组 ${g.name}，可拖动排序`}
              className={`cursor-grab active:cursor-grabbing rounded-[var(--lumi-radius)] outline-none transition-[box-shadow,opacity] focus-visible:ring-2 focus-visible:ring-indigo-400 ${
                dragIndex === index ? "opacity-40" : ""
              } ${overIndex === index && dragIndex !== null && dragIndex !== index ? "ring-2 ring-indigo-400 ring-offset-0" : ""}`}
            >
              <Card className="h-full flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="shrink-0 min-w-6 h-6 px-1 inline-flex items-center justify-center rounded-md text-xs font-bold text-white tabular-nums btn-grad"
                  >
                    {index + 1}
                  </span>
                  <h2 className="font-medium truncate">{g.name}</h2>
                  {g.is_important && (
                    <span title="重要分组" aria-label="重要分组" className="text-amber-300">
                      ★
                    </span>
                  )}
                  <span className="ml-auto text-xs text-slate-500">{g.up_count} 个 UP</span>
                </div>
                {g.description ? (
                  <p className="text-xs text-slate-400 line-clamp-2">{g.description}</p>
                ) : (
                  <p className="text-xs text-slate-600">暂无描述</p>
                )}
                {g.aliases && g.aliases.length > 0 && (
                  <p className="text-xs text-slate-500 truncate" title={g.aliases.join(" / ")}>
                    别名: {g.aliases.slice(0, 3).join(" / ")}
                    {g.aliases.length > 3 ? " …" : ""}
                  </p>
                )}
                <div className="mt-auto flex items-center gap-1.5 pt-1 flex-wrap">
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setEditing(g);
                      setFormError("");
                      setFormOpen(true);
                    }}
                    aria-label={`编辑分组 ${g.name}`}
                  >
                    编辑
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setAliasing(g)}
                    aria-label={`管理别名 ${g.name}`}
                  >
                    别名
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setMerging(g)}
                    aria-label={`合并分组 ${g.name}`}
                  >
                    合并…
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setDeleting(g);
                      setDeleteError("");
                    }}
                    aria-label={`删除分组 ${g.name}`}
                    className="text-red-300 hover:text-red-200"
                  >
                    删除
                  </Button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}

      <GroupFormModal
        open={formOpen}
        editing={editing}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
          setFormError("");
        }}
        onSubmit={submitForm}
        pending={pending}
        error={formError}
      />
      <GroupDeleteModal
        group={deleting}
        onClose={() => {
          setDeleting(null);
          setDeleteError("");
        }}
        onConfirm={() => deleting && deleteMutation.mutate(deleting.id)}
        pending={deleteMutation.isPending}
        error={deleteError}
      />
      <MergeModal
        source={merging}
        groups={data ?? []}
        onClose={() => setMerging(null)}
        onMerged={invalidateWithNotice}
      />
      <AliasModal group={aliasing} onClose={() => setAliasing(null)} />

      <TagManager />
    </div>
  );
}
