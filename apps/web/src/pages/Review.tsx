import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Group, type Paged, type Suggestion } from "../api";
import { Button, Card, ErrorState, Select } from "../components/ui";
import { JobPanel } from "../components/review/JobPanel";
import { SuggestionList } from "../components/review/SuggestionList";
import type { ReviewDecision } from "../components/review/ReviewCard";
import { relativeTime } from "../components/followings/helpers";

type QueueStatus = "pending" | "unclassifiable" | "accepted" | "rejected" | "all";

const TABS: { key: QueueStatus; label: string; countKey?: "pending_count" | "unclassifiable_count" }[] = [
  { key: "pending", label: "待审核", countKey: "pending_count" },
  { key: "unclassifiable", label: "无法确定", countKey: "unclassifiable_count" },
  { key: "accepted", label: "已通过" },
  { key: "rejected", label: "已拒绝" },
  { key: "all", label: "全部" },
];

const PAGE_SIZE = 50;

interface ReviewStatus {
  configured: boolean;
  model: string;
  pending_count: number;
  unclassifiable_count?: number;
  last_run: string | null;
}

const DECIDE_LABEL: Record<ReviewDecision, string> = {
  accept: "已通过",
  reject: "已拒绝",
  unclassifiable: "已标记无法判断",
};

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

/** 队列接口从裸数组迁移为分页对象，这里兼容两种返回。 */
function asPaged(data: Paged<Suggestion> | Suggestion[] | undefined, page: number): Paged<Suggestion> {
  if (!data) return { items: [], total: 0, page, page_size: PAGE_SIZE };
  if (Array.isArray(data)) return { items: data, total: data.length, page, page_size: PAGE_SIZE };
  return data;
}

export default function Review() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<QueueStatus>("pending");
  const [page, setPage] = useState(1);
  const [minConfidence, setMinConfidence] = useState("");
  const [maxConfidence, setMaxConfidence] = useState("");
  const [changedOnly, setChangedOnly] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [skipped, setSkipped] = useState<Set<number>>(new Set());
  const [notice, setNotice] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [instruction, setInstruction] = useState("");

  useEffect(() => {
    setPage(1);
    setSelected(new Set());
    setSkipped(new Set());
  }, [tab, minConfidence, maxConfidence, changedOnly]);

  const statusQuery = useQuery({
    queryKey: ["review", "status"],
    queryFn: () => api<ReviewStatus>("/review/status"),
  });

  const settingsQuery = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<{ ai?: { auto_apply_threshold?: number } }>("/settings"),
    staleTime: 60_000,
  });
  const autoApplyThreshold = settingsQuery.data?.ai?.auto_apply_threshold ?? 0.9;

  const groupsQuery = useQuery({
    queryKey: ["groups"],
    queryFn: () => api<Group[]>("/groups"),
  });

  const queueQuery = useQuery({
    queryKey: ["review", "queue", { tab, page, minConfidence, maxConfidence, changedOnly }],
    queryFn: () =>
      api<Paged<Suggestion> | Suggestion[]>("/review/queue", {
        query: {
          status: tab,
          page,
          page_size: PAGE_SIZE,
          min_confidence: minConfidence || undefined,
          max_confidence: maxConfidence || undefined,
          changed_only: changedOnly ? "true" : undefined,
        },
      }),
  });
  const queue = asPaged(queueQuery.data, page);
  const items = queue.items;
  const hasMore = items.length === queue.page_size;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["review"] });
    void queryClient.invalidateQueries({ queryKey: ["system-stats"] });
    void queryClient.invalidateQueries({ queryKey: ["followings"] });
  };

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
    mutationFn: (vars: { ids: number[]; decision: ReviewDecision }) =>
      api<{ ok: boolean; decided: number; applied: number }>("/review/decide", {
        method: "POST",
        body: { ids: vars.ids, decision: vars.decision },
      }),
    onSuccess: (res, vars) => {
      const extra =
        vars.decision === "accept" && res.applied !== res.decided ? `，其中 ${res.applied} 条已写入分组` : "";
      setNotice({ tone: "ok", text: `${DECIDE_LABEL[vars.decision]} ${res.decided} 条建议${extra}` });
      setSelected(new Set());
      invalidate();
    },
    onError: (err) => setNotice({ tone: "error", text: `操作失败：${errText(err, "请稍后重试")}` }),
  });

  const editAcceptMutation = useMutation({
    mutationFn: async (vars: { suggestion: Suggestion; groupId: number | null; tags: string[] }) => {
      await api("/review/decide", { method: "POST", body: { ids: [vars.suggestion.id], decision: "accept" } });
      if (vars.groupId != null) {
        await api("/followings/bulk", {
          method: "POST",
          body: { mids: [vars.suggestion.up_mid], action: "set_group", params: { group_id: vars.groupId } },
        });
      }
      if (vars.tags.length > 0) {
        await api("/followings/bulk", {
          method: "POST",
          body: { mids: [vars.suggestion.up_mid], action: "add_tags", params: { tags: vars.tags } },
        });
      }
    },
    onSuccess: () => {
      setNotice({ tone: "ok", text: "已按修改通过建议" });
      invalidate();
    },
    onError: (err) => setNotice({ tone: "error", text: `修改并接受失败：${errText(err, "请稍后重试")}` }),
  });

  const status = statusQuery.data;
  const actionable = tab === "pending";
  const pending = runMutation.isPending || decideMutation.isPending || editAcceptMutation.isPending;

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    const selectable = items.filter((s) => s.status === "pending");
    setSelected((prev) => {
      const allChecked = selectable.length > 0 && selectable.every((s) => prev.has(s.id));
      return allChecked ? new Set<number>() : new Set(selectable.map((s) => s.id));
    });
  }

  function skip(id: number) {
    setSkipped((prev) => new Set(prev).add(id));
    const next = items.find((s) => s.id !== id && !skipped.has(s.id));
    if (next) {
      document
        .querySelector(`[data-suggestion-id="${next.id}"]`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  function acceptHighConfidence() {
    const ids = items
      .filter((s) => selected.has(s.id) && s.status === "pending" && s.confidence >= autoApplyThreshold)
      .map((s) => s.id);
    if (ids.length === 0) {
      setNotice({ tone: "error", text: `选中项中没有置信度 ≥ ${autoApplyThreshold} 的建议` });
      return;
    }
    decideMutation.mutate({ ids, decision: "accept" });
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">AI 审核</h1>
        {status && (
          <span className="text-xs text-slate-500">
            {status.configured ? "已配置" : "未配置"}
            {status.model ? ` · 模型 ${status.model}` : ""} · 待审 {status.pending_count} 条
            {typeof status.unclassifiable_count === "number" ? ` · 无法确定 ${status.unclassifiable_count} 条` : ""}
            {status.last_run ? ` · 上次运行 ${relativeTime(status.last_run)}` : ""}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {runMutation.isError && (
            <span className="text-xs text-red-400">{errText(runMutation.error, "运行失败")}</span>
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

      <JobPanel />

      <Card className="space-y-2">
        <label htmlFor="ai-instruction" className="text-xs text-slate-400">
          对 AI 的要求（可选，作用于「运行 AI 分类」单批试用；留空则使用设置中的分组指引）
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
        {TABS.map((t) => {
          const count = t.countKey && status ? status[t.countKey] : undefined;
          return (
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
              {typeof count === "number" ? ` ${count}` : ""}
            </button>
          );
        })}
        {selected.size > 0 && actionable && (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              disabled={pending}
              onClick={() => decideMutation.mutate({ ids: [...selected], decision: "accept" })}
              aria-label="批量通过所选建议"
            >
              批量通过
            </Button>
            <Button
              variant="danger"
              disabled={pending}
              onClick={() => decideMutation.mutate({ ids: [...selected], decision: "reject" })}
              aria-label="批量拒绝所选建议"
            >
              批量拒绝
            </Button>
            <Button
              variant="subtle"
              disabled={pending}
              onClick={acceptHighConfidence}
              aria-label="批量接受高置信度建议"
              title={`仅通过置信度 ≥ ${autoApplyThreshold} 的选中项`}
            >
              批量接受高置信度
            </Button>
            <Button variant="ghost" onClick={() => setSelected(new Set())} aria-label="清除选择">
              取消选择
            </Button>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm" role="group" aria-label="筛选条件">
        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          最低置信度
          <Select value={minConfidence} onChange={(e) => setMinConfidence(e.target.value)} aria-label="最低置信度">
            <option value="">全部</option>
            <option value="0.9">≥ 0.9</option>
            <option value="0.8">≥ 0.8</option>
            <option value="0.65">≥ 0.65</option>
          </Select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          最高置信度
          <Select value={maxConfidence} onChange={(e) => setMaxConfidence(e.target.value)} aria-label="最高置信度">
            <option value="">全部</option>
            <option value="0.9">≤ 0.9</option>
            <option value="0.8">≤ 0.8</option>
            <option value="0.65">≤ 0.65</option>
          </Select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          <input type="checkbox" checked={changedOnly} onChange={(e) => setChangedOnly(e.target.checked)} />
          只看分类变化
        </label>
      </div>

      {queueQuery.error ? (
        <ErrorState message={errText(queueQuery.error, "加载队列失败")} />
      ) : (
        <>
          <SuggestionList
            items={items}
            loading={queueQuery.isLoading}
            error={null}
            selected={selected}
            skipped={skipped}
            actionable={actionable}
            pendingDecision={pending}
            groups={groupsQuery.data ?? []}
            onToggle={toggle}
            onToggleAll={toggleAll}
            onDecide={(id, decision) => decideMutation.mutate({ ids: [id], decision })}
            onSkip={skip}
            onEditAccept={(s, groupId, tags) => editAcceptMutation.mutate({ suggestion: s, groupId, tags })}
          />
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>
              共 {queue.total} 条 · 第 {page} 页 · 每页 {PAGE_SIZE} 条
            </span>
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
