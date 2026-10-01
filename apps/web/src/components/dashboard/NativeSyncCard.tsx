import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError, type NativePlan } from "../../api";
import { Button, Card } from "../ui";

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

/** Local-group -> native-tag push, always previewed first: dry run computes
 * the plan with remote reads only; a separate confirmation performs the write
 * (with a server-side backup). Never triggered by AI classification. */
export function NativeSyncCard() {
  const [plan, setPlan] = useState<NativePlan | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [error, setError] = useState("");

  const previewMutation = useMutation({
    mutationFn: () => api<NativePlan>("/bilibili/native-groups/push-overwrite", { method: "POST", body: { dry_run: true } }),
    onSuccess: (res) => {
      setPlan(res);
      setError("");
      setResult(null);
    },
    onError: (err) => setError(errText(err, "预览失败")),
  });

  const pushMutation = useMutation({
    mutationFn: () =>
      api<Record<string, unknown>>("/bilibili/native-groups/push-overwrite", { method: "POST", body: { dry_run: false } }),
    onSuccess: () => {
      setPlan(null);
      setResult({ ok: true, text: "已按本地分组重建 B 站原生分组（推送前已自动备份）" });
    },
    onError: (err) => setError(errText(err, "推送失败")),
  });

  const busy = previewMutation.isPending || pushMutation.isPending;

  return (
    <Card className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold">B 站原生分组同步</h2>
        <span className="text-xs text-slate-500">远端写操作，先预览再执行</span>
      </div>
      <p className="text-xs text-slate-500">
        把本地分组（任意数量）映射写入 B 站原生关注分组（上游上限 20）。AI 分类与定时同步
        不会自动执行此操作。
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="subtle"
          onClick={() => previewMutation.mutate()}
          disabled={busy}
          aria-label="预览原生分组同步计划"
        >
          {previewMutation.isPending ? "预览中…" : "预览同步计划（Dry Run）"}
        </Button>
        {plan && (
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => {
              if (window.confirm(`确认按计划写入 B 站原生分组？将先自动备份现有分组。`)) pushMutation.mutate();
            }}
            aria-label="确认执行原生分组同步"
          >
            {pushMutation.isPending ? "执行中…" : "执行同步"}
          </Button>
        )}
        {result && (
          <span className={`text-xs ${result.ok ? "text-emerald-300" : "text-red-300"}`} role="status">
            {result.text}
          </span>
        )}
        {error && (
          <span className="text-xs text-red-300" role="alert">
            {error}
          </span>
        )}
      </div>
      {plan && (
        <div className="rounded-[var(--lumi-radius)] border border-slate-700/70 bg-slate-900/40 p-3 text-xs text-slate-300 space-y-1">
          <p className="text-slate-400">{plan.mode === "overwrite" ? "覆盖重建计划" : "增量计划"}（{plan.notes?.[0]}）</p>
          <p>
            预计创建分组：{plan.would_create_tags?.length ? plan.would_create_tags.join("、") : "无"}；
            预计删除分组：{plan.would_delete_tags?.length ? plan.would_delete_tags.join("、") : "无"}
          </p>
          <p>
            预计移动成员：{plan.would_move ?? 0}
            ；预计跳过：{plan.skipped ?? 0}
            {plan.conflicts?.length ? `；冲突：${plan.conflicts.join("、")}` : ""}
          </p>
        </div>
      )}
    </Card>
  );
}
