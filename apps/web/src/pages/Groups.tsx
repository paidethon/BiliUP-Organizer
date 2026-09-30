import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Group } from "../api";
import { Button, Card, EmptyState, ErrorState, Spinner } from "../components/ui";
import { GroupFormModal, type GroupFormValues } from "../components/groups/GroupFormModal";
import { GroupDeleteModal } from "../components/groups/GroupDeleteModal";

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
  const [formError, setFormError] = useState("");
  const [deleteError, setDeleteError] = useState("");

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

  const reorderMutation = useMutation({
    mutationFn: (vars: { a: { id: number; sort_order: number }; b: { id: number; sort_order: number } }) =>
      Promise.all([
        api(`/groups/${vars.a.id}`, { method: "PATCH", body: { sort_order: vars.a.sort_order } }),
        api(`/groups/${vars.b.id}`, { method: "PATCH", body: { sort_order: vars.b.sort_order } }),
      ]),
    onSuccess: () => invalidate(),
  });

  function move(index: number, dir: -1 | 1) {
    const list = data ?? [];
    const other = index + dir;
    if (other < 0 || other >= list.length) return;
    const current = list[index];
    const neighbor = list[other];
    reorderMutation.mutate({
      a: { id: current.id, sort_order: neighbor.sort_order },
      b: { id: neighbor.id, sort_order: current.sort_order },
    });
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
        本地分组仅保存在本站，用于筛选、提醒与 AI 建议审核，不会改动 B 站侧的关注列表；
        如需同步到 B 站原生标签，请在「设置」中配置原生分组同步。
      </p>

      {isLoading && <Spinner label="正在加载分组…" />}
      {error && <ErrorState message={errText(error, "加载失败")} />}
      {data && data.length === 0 && (
        <EmptyState title="还没有本地分组" hint="点击右上角「新建分组」，按内容类型整理你的关注" />
      )}

      {data && data.length > 0 && (
        <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" aria-label="分组列表">
          {data.map((g, index) => (
            <li key={g.id}>
              <Card className="h-full flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="w-3 h-3 rounded-full shrink-0"
                    style={{ backgroundColor: g.color }}
                  />
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
                <div className="mt-auto flex items-center gap-2 pt-1">
                  <Button
                    variant="ghost"
                    onClick={() => move(index, -1)}
                    disabled={index === 0 || reorderMutation.isPending}
                    aria-label={`上移分组 ${g.name}`}
                  >
                    ↑
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => move(index, 1)}
                    disabled={index === data.length - 1 || reorderMutation.isPending}
                    aria-label={`下移分组 ${g.name}`}
                  >
                    ↓
                  </Button>
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
    </div>
  );
}
