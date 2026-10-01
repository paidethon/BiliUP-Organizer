import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type ClassificationJob } from "../../api";
import { Badge, Button, Select } from "../ui";

const AUTO_APPLY_KEY = "biliup.review.autoApply";

type JobAction = "pause" | "resume" | "cancel" | "retry-failures";

const JOB_STATUS: Record<ClassificationJob["status"], { label: string; tone: "info" | "ok" | "warn" | "danger" }> = {
  running: { label: "运行中", tone: "info" },
  paused: { label: "已暂停", tone: "warn" },
  completed: { label: "已完成", tone: "ok" },
  cancelled: { label: "已取消", tone: "danger" },
  failed: { label: "失败", tone: "danger" },
};

const KIND_LABEL: Record<ClassificationJob["kind"], string> = {
  pending: "仅分类未分类",
  full: "重新分类全部",
};

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

function readAutoApply(): boolean {
  try {
    return window.localStorage.getItem(AUTO_APPLY_KEY) === "true";
  } catch {
    return false;
  }
}

function persistAutoApply(value: boolean): void {
  try {
    window.localStorage.setItem(AUTO_APPLY_KEY, value ? "true" : "false");
  } catch {
    // localStorage 不可用时静默降级为会话内状态
  }
}

type SettingsShape = { ai?: { auto_apply_threshold?: number } };

export function JobPanel() {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [batchSize, setBatchSize] = useState(50);
  const [autoApply, setAutoApply] = useState(readAutoApply);

  const settingsQuery = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<SettingsShape>("/settings"),
    staleTime: 60_000,
  });
  const threshold = settingsQuery.data?.ai?.auto_apply_threshold;

  const currentJobQuery = useQuery({
    queryKey: ["review", "jobs", "current"],
    queryFn: () => api<ClassificationJob | null>("/review/jobs/current"),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
  });
  const job = currentJobQuery.data ?? null;
  const busy = job?.status === "running" || job?.status === "paused";

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["review"] });
    void queryClient.invalidateQueries({ queryKey: ["system-stats"] });
  };

  const createMutation = useMutation({
    mutationFn: (kind: ClassificationJob["kind"]) =>
      api<ClassificationJob>("/review/jobs", {
        method: "POST",
        body: { kind, batch_size: batchSize, auto_apply: autoApply, threshold: threshold ?? 0.9 },
      }),
    onSuccess: (created) => {
      setNotice({ tone: "ok", text: `已创建分类任务：${KIND_LABEL[created.kind]}（共 ${created.total} 个 UP）` });
      invalidate();
    },
    onError: (err) => {
      const active = err instanceof ApiError && (err.status === 409 || err.code === "classification_job_active");
      setNotice({ tone: "error", text: active ? "已有任务在运行" : `创建失败：${errText(err, "请稍后重试")}` });
    },
  });

  const actionMutation = useMutation({
    mutationFn: (vars: { id: number; action: JobAction }) =>
      api<ClassificationJob>(`/review/jobs/${vars.id}/${vars.action}`, { method: "POST" }),
    onSuccess: (updated) => {
      setNotice({ tone: "ok", text: `任务状态：${JOB_STATUS[updated.status].label}` });
      invalidate();
    },
    onError: (err) => setNotice({ tone: "error", text: `操作失败：${errText(err, "请稍后重试")}` }),
  });

  function createJob(kind: ClassificationJob["kind"]) {
    if (kind === "full") {
      const confirmed = window.confirm(
        "重新分类全部会重新分析所有 UP 主并生成新建议；结果进入审核队列，确认后才会写入分组，不会静默覆盖现有分类。确定继续？",
      );
      if (!confirmed) return;
    }
    createMutation.mutate(kind);
  }

  function toggleAutoApply(value: boolean) {
    setAutoApply(value);
    persistAutoApply(value);
  }

  const pct = job && job.total > 0 ? Math.min(100, (job.processed / job.total) * 100) : 0;
  const statusMeta = job ? JOB_STATUS[job.status] : null;
  const showCreate = !busy;
  const counts: { label: string; value: number | undefined }[] = job
    ? [
        { label: "总数", value: job.total },
        { label: "已处理", value: job.processed },
        { label: "已分析", value: job.classified },
        { label: "自动通过", value: job.auto_applied },
        { label: "待审核", value: job.needs_review },
        { label: "无法确定", value: job.unclassifiable },
        { label: "失败", value: job.failed },
      ]
    : [];

  return (
    <section className="surface p-4 space-y-3" aria-label="分类任务">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">全量分类任务</h2>
        {job && statusMeta && <Badge tone={statusMeta.tone}>{statusMeta.label}</Badge>}
        {job && <span className="text-xs text-slate-500">{KIND_LABEL[job.kind]} · 批次 {job.batch_size}</span>}
        {job?.status === "running" && (
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-full bg-indigo-400 animate-pulse"
          />
        )}
      </div>

      {currentJobQuery.isLoading ? (
        <div className="h-10 rounded-[var(--lumi-radius-sm)] bg-slate-800/60 animate-pulse" aria-hidden="true" />
      ) : currentJobQuery.error ? (
        <p className="text-xs text-red-300">任务状态加载失败：{errText(currentJobQuery.error, "请稍后重试")}</p>
      ) : job ? (
        <div className="space-y-3">
          <div className="space-y-1">
            <div
              className="h-2 rounded-full bg-slate-700/60 overflow-hidden"
              role="progressbar"
              aria-valuenow={Math.round(pct)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="分类任务进度"
            >
              <div
                className="h-full rounded-full"
                style={{ width: `${pct}%`, background: "var(--lumi-grad)" }}
              />
            </div>
            <p className="text-xs text-slate-400 tabular-nums">进度 {pct.toFixed(1)}%</p>
          </div>

          <dl className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 text-xs">
            {counts.map((c) => (
              <div key={c.label} className="rounded-[var(--lumi-radius-sm)] bg-slate-900/50 px-2.5 py-2">
                <dt className="text-slate-500">{c.label}</dt>
                <dd className="mt-0.5 text-slate-200 tabular-nums">{c.value ?? "—"}</dd>
              </div>
            ))}
          </dl>

          {job.error && <p className="text-xs text-red-300 break-words">{job.error}</p>}

          <div className="flex flex-wrap items-center gap-2">
            {job.status === "running" && (
              <>
                <Button
                  variant="subtle"
                  disabled={actionMutation.isPending}
                  onClick={() => actionMutation.mutate({ id: job.id, action: "pause" })}
                >
                  暂停
                </Button>
                <Button
                  variant="danger"
                  disabled={actionMutation.isPending}
                  onClick={() => actionMutation.mutate({ id: job.id, action: "cancel" })}
                >
                  取消
                </Button>
              </>
            )}
            {job.status === "paused" && (
              <>
                <Button
                  variant="primary"
                  disabled={actionMutation.isPending}
                  onClick={() => actionMutation.mutate({ id: job.id, action: "resume" })}
                >
                  继续
                </Button>
                <Button
                  variant="danger"
                  disabled={actionMutation.isPending}
                  onClick={() => actionMutation.mutate({ id: job.id, action: "cancel" })}
                >
                  取消
                </Button>
              </>
            )}
            {job.status === "completed" && <span className="text-xs text-emerald-300">已完成</span>}
            {(job.status === "completed" || job.status === "failed") && job.failed > 0 && (
              <Button
                variant="subtle"
                disabled={actionMutation.isPending}
                onClick={() => actionMutation.mutate({ id: job.id, action: "retry-failures" })}
              >
                重试失败 {job.failed}
              </Button>
            )}
          </div>
        </div>
      ) : null}

      {showCreate && (
        <div className="flex flex-wrap items-end gap-x-4 gap-y-2 border-t border-slate-700/40 pt-3">
          <div className="flex items-center gap-2">
            <Button variant="primary" disabled={createMutation.isPending} onClick={() => createJob("pending")}>
              仅分类未分类
            </Button>
            <Button variant="ghost" disabled={createMutation.isPending} onClick={() => createJob("full")}>
              重新分类全部
            </Button>
          </div>
          <label className="flex items-center gap-1.5 text-xs text-slate-400">
            每批数量
            <Select value={batchSize} onChange={(e) => setBatchSize(Number(e.target.value))} aria-label="每批分类数量">
              <option value={20}>20</option>
              <option value={50}>50</option>
            </Select>
          </label>
          <label className="flex items-center gap-1.5 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={autoApply}
              onChange={(e) => toggleAutoApply(e.target.checked)}
            />
            自动应用高置信度
          </label>
          <span className="text-xs text-slate-500" title="在设置页调整 AI 自动应用阈值">
            {typeof threshold === "number" ? `自动应用阈值 ≥${threshold}` : "阈值在设置页调整"}
          </span>
        </div>
      )}

      {notice && (
        <p
          className={`text-xs px-3 py-2 rounded-lg ${
            notice.tone === "ok" ? "text-emerald-300 bg-emerald-500/10" : "text-red-300 bg-red-500/10"
          }`}
        >
          {notice.text}
        </p>
      )}
    </section>
  );
}
