import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Tag } from "../../api";
import { Button, Card, ErrorState, Spinner } from "../ui";

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

/** Content-tag vocabulary manager. Tags are a separate dimension from primary
 * categories; one UP can carry many. */
export function TagManager() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["tags"],
    queryFn: () => api<Tag[]>("/tags"),
  });
  const [name, setName] = useState("");
  const [color, setColor] = useState("#64748b");
  const [formError, setFormError] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState("");
  const [deleteError, setDeleteError] = useState("");

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["tags"] });
    void queryClient.invalidateQueries({ queryKey: ["followings"] });
  }

  const createMutation = useMutation({
    mutationFn: () => api("/tags", { method: "POST", body: { name: name.trim(), color } }),
    onSuccess: () => {
      setName("");
      setFormError("");
      invalidate();
    },
    onError: (err) => setFormError(errText(err, "创建失败")),
  });

  const updateMutation = useMutation({
    mutationFn: (vars: { id: number; name: string }) =>
      api(`/tags/${vars.id}`, { method: "PATCH", body: { name: vars.name } }),
    onSuccess: () => {
      setEditingId(null);
      invalidate();
    },
    onError: (err) => setFormError(errText(err, "重命名失败")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api(`/tags/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setDeleteError("");
      invalidate();
    },
    onError: (err) => setDeleteError(errText(err, "删除失败")),
  });

  return (
    <Card className="p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-medium">内容标签</h2>
        <span className="text-xs text-slate-500">与主分类相互独立，一个 UP 可挂多个标签</span>
      </div>
      {isLoading && <Spinner label="正在加载标签…" />}
      {error && <ErrorState message={errText(error, "加载失败")} />}
      {data && (
        <ul className="flex flex-wrap gap-2" aria-label="标签列表">
          {data.length === 0 && <li className="text-xs text-slate-600">还没有标签</li>}
          {data.map((tag) => (
            <li
              key={tag.id}
              className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs"
              style={{ borderColor: `${tag.color}66`, color: tag.color }}
            >
              {editingId === tag.id ? (
                <form
                  className="flex items-center gap-1"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (editingName.trim()) updateMutation.mutate({ id: tag.id, name: editingName.trim() });
                  }}
                >
                  <input
                    value={editingName}
                    onChange={(e) => setEditingName(e.target.value)}
                    autoFocus
                    maxLength={32}
                    aria-label={`重命名标签 ${tag.name}`}
                    className="w-24 bg-slate-900/70 border border-slate-700 rounded px-1 py-0.5 outline-none focus:border-indigo-400"
                  />
                  <button type="submit" className="text-emerald-300" aria-label="保存标签名">
                    ✓
                  </button>
                  <button type="button" className="text-slate-500" onClick={() => setEditingId(null)} aria-label="取消重命名">
                    ✕
                  </button>
                </form>
              ) : (
                <>
                  <span>{tag.name}</span>
                  <span className="text-slate-600">{tag.up_count}</span>
                  <button
                    type="button"
                    className="text-slate-500 hover:text-slate-300"
                    onClick={() => {
                      setEditingId(tag.id);
                      setEditingName(tag.name);
                    }}
                    aria-label={`编辑标签 ${tag.name}`}
                  >
                    ✎
                  </button>
                  <button
                    type="button"
                    className="text-red-300/70 hover:text-red-300"
                    onClick={() => {
                      if (window.confirm(`删除标签「${tag.name}」？它会从所有 UP 上移除。`)) deleteMutation.mutate(tag.id);
                    }}
                    aria-label={`删除标签 ${tag.name}`}
                  >
                    ✕
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) createMutation.mutate();
        }}
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="新标签名称"
          aria-label="新标签名称"
          maxLength={32}
          className="w-40 bg-slate-900/70 border border-slate-700 rounded-[var(--lumi-radius-sm)] px-2 py-1.5 text-sm outline-none focus:border-indigo-400"
        />
        <input
          type="color"
          value={color}
          onChange={(e) => setColor(e.target.value)}
          aria-label="标签颜色"
          className="h-8 w-10 cursor-pointer rounded border border-slate-700 bg-transparent"
        />
        <Button type="submit" variant="subtle" disabled={!name.trim() || createMutation.isPending} aria-label="创建标签">
          添加标签
        </Button>
        {formError && (
          <span className="text-xs text-red-300" role="alert">
            {formError}
          </span>
        )}
        {deleteError && (
          <span className="text-xs text-red-300" role="alert">
            {deleteError}
          </span>
        )}
      </form>
    </Card>
  );
}
