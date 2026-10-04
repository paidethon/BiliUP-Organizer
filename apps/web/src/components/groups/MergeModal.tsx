import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Group } from "../../api";
import { Button, Modal } from "../ui";

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

/** Fold one local category into another: memberships, aliases and the
 * native-tag mapping move to the target; the source row is deleted. */
export function MergeModal({
  source,
  groups,
  onClose,
  onMerged,
}: {
  source: Group | null;
  groups: Group[];
  onClose: () => void;
  onMerged?: (message: string, undoId: number | null) => void;
}) {
  const queryClient = useQueryClient();
  const [intoId, setIntoId] = useState<number | "">("");
  const [error, setError] = useState("");

  useEffect(() => {
    setIntoId("");
    setError("");
  }, [source]);

  const mergeMutation = useMutation({
    mutationFn: (target: number) =>
      api<{ ok: boolean; moved: number; undo_id: number | null }>(`/groups/${source?.id}/merge`, {
        method: "POST",
        body: { into_id: target },
      }),
    onSuccess: (res) => {
      void queryClient.invalidateQueries({ queryKey: ["groups"] });
      void queryClient.invalidateQueries({ queryKey: ["followings"] });
      onMerged?.(`已合并「${source?.name}」，移动了 ${res.moved} 个 UP`, res.undo_id);
      onClose();
    },
    onError: (err) => setError(errText(err, "合并失败，请重试")),
  });

  const target = groups.find((g) => g.id === intoId);

  return (
    <Modal open={source !== null} onClose={onClose} title="合并分组">
      {source && (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            将把「{source.name}」
            {target ? (
              <>
                的 {source.up_count} 个 UP、别名与 B 站映射并入「{target.name}」，源分组将被删除。
              </>
            ) : (
              "并入所选目标分组，源分组将被删除。"
            )}
          </p>
          <p className="text-xs text-slate-500">合并后可通过页面顶部提示中的「撤销」恢复（24 小时内）。</p>
          <label className="block text-xs text-slate-400">
            目标分组
            <select
              value={intoId}
              onChange={(e) => setIntoId(e.target.value ? Number(e.target.value) : "")}
              aria-label="选择目标分组"
              className="mt-1 w-full bg-slate-900/70 border border-slate-700 rounded-[var(--lumi-radius-sm)] px-2 py-1.5 text-sm outline-none focus:border-indigo-400"
            >
              <option value="">请选择…</option>
              {groups
                .filter((g) => g.id !== source.id)
                .map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}（{g.up_count} 个 UP）
                  </option>
                ))}
            </select>
          </label>
          {error && (
            <p className="text-xs text-red-300" role="alert">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={onClose}>
              取消
            </Button>
            <Button
              variant="danger"
              disabled={!intoId || mergeMutation.isPending}
              onClick={() => intoId && mergeMutation.mutate(intoId)}
              aria-label="确认合并"
            >
              {mergeMutation.isPending ? "合并中…" : "确认合并"}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

/** Manage alternative names that resolve onto this category. */
export function AliasModal({ group, onClose }: { group: Group | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [alias, setAlias] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setAlias("");
    setError("");
  }, [group]);

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["groups"] });
  }

  const addMutation = useMutation({
    mutationFn: (value: string) =>
      api(`/groups/${group?.id}/aliases`, { method: "POST", body: { alias: value } }),
    onSuccess: () => {
      setAlias("");
      setError("");
      invalidate();
    },
    onError: (err) => setError(errText(err, "添加失败")),
  });

  const removeMutation = useMutation({
    mutationFn: (value: string) => api(`/groups/${group?.id}/aliases/${encodeURIComponent(value)}`, { method: "DELETE" }),
    onSuccess: () => invalidate(),
    onError: (err) => setError(errText(err, "删除失败")),
  });

  return (
    <Modal open={group !== null} onClose={onClose} title={`别名 · ${group?.name ?? ""}`}>
      {group && (
        <div className="space-y-3">
          <p className="text-xs text-slate-500">
            别名用于 AI 分类结果归一：命中别名的分类名会落到本分组，避免生成重复分类。
          </p>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (alias.trim()) addMutation.mutate(alias.trim());
            }}
          >
            <input
              value={alias}
              onChange={(e) => setAlias(e.target.value)}
              placeholder="例如：科技区"
              aria-label="新别名"
              maxLength={64}
              className="flex-1 bg-slate-900/70 border border-slate-700 rounded-[var(--lumi-radius-sm)] px-2 py-1.5 text-sm outline-none focus:border-indigo-400"
            />
            <Button type="submit" variant="subtle" disabled={!alias.trim() || addMutation.isPending}>
              添加
            </Button>
          </form>
          <ul className="space-y-1" aria-label="别名列表">
            {(group.aliases ?? []).length === 0 && <li className="text-xs text-slate-600">暂无别名</li>}
            {(group.aliases ?? []).map((a) => (
              <li key={a} className="flex items-center gap-2 text-sm text-slate-300">
                <span className="truncate">{a}</span>
                <Button
                  variant="ghost"
                  className="ml-auto text-red-300 hover:text-red-200"
                  onClick={() => removeMutation.mutate(a)}
                  aria-label={`删除别名 ${a}`}
                >
                  删除
                </Button>
              </li>
            ))}
          </ul>
          {error && (
            <p className="text-xs text-red-300" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </Modal>
  );
}
