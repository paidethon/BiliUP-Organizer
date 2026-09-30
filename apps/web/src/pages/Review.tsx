import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Suggestion } from "../api";
import { Badge, Button, Card, ErrorState, Spinner } from "../components/ui";
import { SuggestionList } from "../components/review/SuggestionList";
import { relativeTime } from "../components/followings/helpers";

type QueueStatus = "pending" | "accepted" | "rejected" | "all";

const TABS: { key: QueueStatus; label: string }[] = [
  { key: "pending", label: "待审核" },
  { key: "accepted", label: "已通过" },
  { key: "rejected", label: "已拒绝" },
  { key: "all", label: "全部" },
];

const PAGE_SIZE = 50;

interface ReviewStatus {
  configured: boolean;
  model: string;
  pending_count: number;
  last_run: string | null;
}

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

export default function Review() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<QueueStatus>("pending");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    setPage(1);
    setSelected(new Set());
  }, [tab]);

  const statusQuery = useQuery({
    queryKey: ["review", "status"],
    queryFn: () => api<ReviewStatus>("/review/status"),
  });

  const queueQuery = useQuery({
    queryKey: ["review", "queue", { tab, page }],
    queryFn: () => api<Suggestion[]>("/review/queue", { query: { status: tab, page, page_size: PAGE_SIZE } }),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["review"] });
    void queryClient.invalidateQueries({ queryKey: ["system-stats"] });
    void queryClient.invalidateQueries({ queryKey: ["followings"] });
  };

  const [instruction, setInstruction] = useState("");

  const runMutation = useMutation({
    mutationFn: () =>
      api<{ classified?: number; pending?: number }>("/review/run", {
        method: "POST",
        body: { batch_size: 20, instruction: instruction.trim() },
      }),
    onSuccess: (res) => {
      const parts = ["AI 分类完成"];
      if (typeof res.classified === "number") parts.push(`本轮分类 ${res.classified} 个 UP`);
      if (typeof res.pending === "number") parts.push(`剩余待审 ${res.pending} 条`);
      setNotice({ tone: "ok", text: parts.join("，") });
      invalidate();
    },
    onError: (err) => setNotice({ tone: "error", text: `运行失败：${errText(err, "请稍后重试")}` }),
  });

  const decideMutation = useMutation({
    mutationFn: (vars: { ids: number[]; decision: "accept" | "reject" }) =>
      api<{ ok: boolean; decided: number; applied: number }>("/review/decide", {
        method: "POST",
        body: { ids: vars.ids, decision: vars.decision },
      }),
    onSuccess: (res, vars) => {
      const label = vars.decision === "accept" ? "已通过" : "已拒绝";
      const extra = vars.decision === "accept" && res.applied !== res.decided ? `，其中 ${res.applied} 条已写入分组` : "";
      setNotice({ tone: "ok", text: `${label} ${res.decided} 条建议${extra}` });
      setSelected(new Set());
      invalidate();
    },
    onError: (err) => setNotice({ tone: "error", text: `操作失败：${errText(err, "请稍后重试")}` }),
  });

  const status = statusQuery.data;
  const items = queueQuery.data ?? [];
  const hasMore = items.length === PAGE_SIZE;
  const actionable = tab !== "all";
  const pending = runMutation.isPending || decideMutation.isPending;

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((prev) => {
      const allChecked = items.length > 0 && items.every((s) => prev.has(s.id));
      return allChecked ? new Set<number>() : new Set(items.map((s) => s.id));
    });
  }

  function decide(ids: number[], decision: "accept" | "reject") {
    decideMutation.mutate({ ids, decision });
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">AI 审核</h1>
        {status && (
          <span className="text-xs text-slate-500">
            {status.configured ? "已配置" : "未配置"}
            {status.model ? ` · 模型 ${status.model}` : ""} · 待审 {status.pending_count} 条
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {runMutation.isError && (
            <span className="text-xs text-red-400" role="alert">
              {errText(runMutation.error, "运行失败")}
            </span>
          )}
          <Button
            variant="primary"
            onClick={() => runMutation.mutate()}
            disabled={runMutation.isPending}
            aria-label="运行 AI 分类"
          >
            {runMutation.isPending && (
              <span
                aria-hidden="true"
                className="inline-block h-3.5 w-3.5 mr-1.5 rounded-full border-2 border-white/70 border-t-transparent animate-spin align-[-2px]"
              />
            )}
            {runMutation.isPending ? "分类中…" : "运行 AI 分类"}
          </Button>
        </div>
      </header>

      {status && (
        <Card className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm" aria-label="AI 状态">
          <span className="flex items-center gap-2">
            <span className="text-xs text-slate-500">服务状态</span>
            {status.configured ? <Badge tone="ok">已配置</Badge> : <Badge tone="warn">未配置</Badge>}
          </span>
          <span className="flex items-center gap-2">
            <span className="text-xs text-slate-500">模型</span>
            <span className="text-slate-300">{status.model || "—"}</span>
          </span>
          <span className="flex items-center gap-2">
            <span className="text-xs text-slate-500">待审建议</span>
            <span className="text-slate-300 tabular-nums">{status.pending_count}</span>
          </span>
          <span className="flex items-center gap-2">
            <span className="text-xs text-slate-500">上次运行</span>
            <span className="text-slate-300" title={status.last_run ?? undefined}>
              {status.last_run ? relativeTime(status.last_run) : "从未"}
            </span>
          </span>
        </Card>
      )}
      {statusQuery.error && <ErrorState message={errText(statusQuery.error, "加载状态失败")} />}

      <Card className="space-y-2">
        <label htmlFor="ai-instruction" className="text-xs text-slate-400">
          对 AI 的要求（可选，留空则使用设置中的分组指引）
        </label>
        <textarea
          id="ai-instruction"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={2}
          maxLength={500}
          placeholder="例如：分组尽可能详细，优先使用已有分组；B 站关注分组上限 20 个"
          className="w-full bg-slate-900/70 border border-slate-700 rounded-[var(--lumi-radius-sm)] px-3 py-2 text-sm outline-none focus:border-indigo-400 resize-y"
        />
      </Card>

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

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="按状态筛选建议">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            aria-pressed={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 rounded-full text-xs border transition-colors ${
              tab === t.key ? "border-indigo-400 text-indigo-300 bg-indigo-500/10" : "border-slate-700 text-slate-400 hover:text-white"
            }`}
          >
            {t.label}
          </button>
        ))}
        {selected.size > 0 && actionable && (
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-slate-400">已选 {selected.size} 条</span>
            <Button
              variant="primary"
              disabled={pending}
              onClick={() => decide([...selected], "accept")}
              aria-label="批量通过所选建议"
            >
              通过
            </Button>
            <Button variant="danger" disabled={pending} onClick={() => decide([...selected], "reject")} aria-label="批量拒绝所选建议">
              拒绝
            </Button>
            <Button variant="ghost" onClick={() => setSelected(new Set())} aria-label="清除选择">
              取消选择
            </Button>
          </div>
        )}
      </div>

      {queueQuery.isLoading ? (
        <Spinner label="正在加载建议队列…" />
      ) : queueQuery.error ? (
        <ErrorState message={errText(queueQuery.error, "加载队列失败")} />
      ) : (
        <>
          <SuggestionList
            items={items}
            loading={false}
            error={null}
            selected={selected}
            actionable={actionable}
            pendingDecision={decideMutation.isPending}
            onToggle={toggle}
            onToggleAll={toggleAll}
            onDecide={decide}
          />
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>第 {page} 页 · 每页 {PAGE_SIZE} 条</span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                aria-label="上一页"
                className="px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40"
              >
                上一页
              </button>
              <button
                type="button"
                disabled={!hasMore}
                onClick={() => setPage((p) => p + 1)}
                aria-label="下一页"
                className="px-2 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40"
              >
                下一页
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
