import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, ApiError, nativePushPlan, nativePushRun, type NativePlan, type SyncRun } from "../../api";
import { Button, Card, Badge } from "../ui";

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

interface ConvergePlan extends NativePlan {
  managed_tags?: Record<string, number>;
  unmapped_local_groups?: string[];
  to_add?: Record<string, number[]>;
  to_remove?: Record<string, number[]>;
  planned_up_writes?: number;
  total_managed_memberships?: number;
  tag_reads_complete?: boolean;
  protected_remote_tags?: string[];
  unmanaged_note?: string;
  skipped_cancelled?: number[];
}

type Mode = "append" | "replace";

/** Local-group -> native-tag synchronization, previewed first. Three explicit
 * levels: append (non-destructive default), replace-managed (explicit
 * destructive within managed scope), and managed-scope rebuild. Every write
 * path runs as a tracked background task (poll /sync/runs) with a completed
 * backup taken before any remote write. */
export function NativeSyncCard() {
  const [plan, setPlan] = useState<ConvergePlan | null>(null);
  const [mode, setMode] = useState<Mode>("append");
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [error, setError] = useState("");

  const runs = useQuery({
    queryKey: ["bilibili", "sync-runs-native"],
    queryFn: () => api<SyncRun[]>("/bilibili/sync/runs", { query: { limit: 5 } }),
    refetchInterval: (query) => {
      const rows = query.state.data ?? [];
      return rows.some((r) => r.kind === "native_push" && r.status === "running") ? 2500 : false;
    },
  });

  const previewMutation = useMutation({
    mutationFn: (m: Mode) => nativePushPlan(m),
    onSuccess: (res) => {
      setPlan(res as unknown as ConvergePlan);
      setMode(((res as unknown as ConvergePlan).mode as Mode) ?? "append");
      setError("");
      setResult(null);
    },
    onError: (err) => setError(errText(err, "预览失败")),
  });

  const overwritePreview = useMutation({
    mutationFn: () =>
      api<ConvergePlan>("/bilibili/native-groups/push-overwrite", { method: "POST", body: { dry_run: true } }),
    onSuccess: (res) => {
      setPlan({ ...res, mode: "overwrite" });
      setError("");
    },
    onError: (err) => setError(errText(err, "预览失败")),
  });

  const overwritePush = useMutation({
    mutationFn: () =>
      api<Record<string, unknown>>("/bilibili/native-groups/push-overwrite", { method: "POST", body: { dry_run: false } }),
    onSuccess: () => {
      setPlan(null);
      setResult({ ok: true, text: "已按本地分组重建托管的 B 站原生分组（推送前已自动备份；未托管的远端分组保持不变）" });
    },
    onError: (err) => setError(errText(err, "推送失败")),
  });

  const pushRun = useMutation({
    mutationFn: (m: Mode) => nativePushRun(m),
    onSuccess: () => {
      setPlan(null);
      setResult({ ok: true, text: "同步任务已提交，正在后台执行（见下方任务状态）" });
    },
    onError: (err) => setError(errText(err, "提交失败")),
  });

  const busy = previewMutation.isPending || overwritePreview.isPending || overwritePush.isPending || pushRun.isPending;
  const nativeRun = (runs.data ?? []).find((r) => r.kind === "native_push");

  return (
    <Card className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold">B 站原生分组同步</h2>
        <span className="text-xs text-slate-500">远端写操作，先预览再执行；写入前自动备份</span>
      </div>
      <p className="text-xs text-slate-500">
        把本地分组（多对多）收敛写入 B 站原生关注分组（上游上限 20）。默认「追加」模式非破坏：
        未托管的原生分组与特别关注保持不变。AI 分类与定时同步不会自动执行此操作。
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="subtle" onClick={() => previewMutation.mutate("append")} disabled={busy}>
          {previewMutation.isPending && mode === "append" ? "预览中…" : "预览追加同步（推荐）"}
        </Button>
        <Button variant="subtle" onClick={() => previewMutation.mutate("replace")} disabled={busy}>
          预览替换同步
        </Button>
        {plan && plan.mode !== "overwrite" && (
          <Button
            variant={plan.mode === "replace" ? "danger" : "primary"}
            disabled={busy}
            onClick={() => {
              const text =
                plan.mode === "replace"
                  ? "替换模式会从「托管范围内」移除多余关系（未托管分组仍保留）。确认执行？将先自动备份。"
                  : "确认按计划追加写入 B 站原生分组？将先自动备份现有分组。";
              if (window.confirm(text)) pushRun.mutate(plan.mode as Mode);
            }}
          >
            {pushRun.isPending ? "提交中…" : "执行同步（后台任务）"}
          </Button>
        )}
        <Button variant="ghost" onClick={() => overwritePreview.mutate()} disabled={busy}>
          重建托管标签（Dry Run）
        </Button>
        {plan?.mode === "overwrite" && (
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => {
              if (window.confirm("确认重建托管的原生标签？将先自动备份；未托管的远端分组不会被删除。"))
                overwritePush.mutate();
            }}
          >
            {overwritePush.isPending ? "执行中…" : "确认重建"}
          </Button>
        )}
      </div>
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
      {nativeRun && (
        <div className="rounded-[var(--lumi-radius-sm)] border border-slate-700/70 bg-slate-900/40 p-2 text-xs text-slate-300">
          <span className="text-slate-400">最近同步任务 #{nativeRun.id}：</span>
          {nativeRun.status === "running" ? (
            <Badge tone="info">运行中</Badge>
          ) : nativeRun.status === "success" ? (
            <Badge tone="ok">成功</Badge>
          ) : (
            <Badge tone="danger">失败</Badge>
          )}
          {nativeRun.stats && (
            <span className="ml-2">
              写入 {String(nativeRun.stats.written_ups ?? 0)} · 校验通过 {String(nativeRun.stats.verified_ups ?? 0)}
              {nativeRun.stats.failed_ups ? ` · 校验失败 ${String(nativeRun.stats.failed_ups)}` : ""}
              {Array.isArray(nativeRun.stats.skipped_cancelled_mids) &&
                nativeRun.stats.skipped_cancelled_mids.length > 0 &&
                ` · 已注销跳过 ${nativeRun.stats.skipped_cancelled_mids.length}`}
            </span>
          )}
          {nativeRun.error && <span className="text-red-300 ml-2">{nativeRun.error}</span>}
        </div>
      )}
      {plan && (
        <div className="rounded-[var(--lumi-radius)] border border-slate-700/70 bg-slate-900/40 p-3 text-xs text-slate-300 space-y-1">
          <p className="text-slate-400">
            {plan.mode === "append" && "追加计划（R ∪ D：远端现有关系全部保留，补齐本地分组）"}
            {plan.mode === "replace" && "替换计划（托管范围内 (R − M) ∪ D：清除托管范围多余关系，未托管分组保留）"}
            {plan.mode === "overwrite" && "托管范围重建计划（仅重建映射到本地分组的标签）"}
          </p>
          {plan.managed_tags && (
            <p>
              托管标签：{Object.entries(plan.managed_tags).map(([name, id]) => `${name}(#${id})`).join("、") || "无"}
            </p>
          )}
          {plan.mode === "overwrite" && plan.protected_remote_tags && (
            <p>保护（不删除）：{plan.protected_remote_tags.join("、") || "无未托管标签"}</p>
          )}
          {plan.to_add && (
            <p>
              预计补齐成员：
              {Object.entries(plan.to_add)
                .map(([tag, mids]) => `组#${tag} +${mids.length}`)
                .join("；") || "无"}
            </p>
          )}
          {plan.to_remove && (
            <p>
              预计移除成员：
              {Object.entries(plan.to_remove)
                .map(([tag, mids]) => `组#${tag} -${mids.length}`)
                .join("；") || "无"}
            </p>
          )}
          {typeof plan.planned_up_writes === "number" && <p>预计写入 UP 数：{plan.planned_up_writes}</p>}
          {plan.skipped_cancelled && plan.skipped_cancelled.length > 0 && (
            <p className="text-amber-300">
              ⚠ {plan.skipped_cancelled.length} 个 UP 的 B 站账号已注销，将跳过其分组写入（mid：
              {plan.skipped_cancelled.join("、")}）。
            </p>
          )}
          {plan.tag_reads_complete === false && (
            <p className="text-amber-300">⚠ 远端成员读取被页数上限截断，写入前请确认或调大上限。</p>
          )}
          {plan.unmapped_local_groups?.length ? (
            <p className="text-amber-300">未映射到原生标签的本地分组：{plan.unmapped_local_groups.join("、")}（执行时将自动创建）</p>
          ) : null}
          {plan.notes?.map((n) => (
            <p key={n} className="text-slate-500">
              {n}
            </p>
          ))}
        </div>
      )}
    </Card>
  );
}
