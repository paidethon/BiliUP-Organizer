import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { Badge, Button, EmptyState, ErrorState, Spinner } from "../components/ui";
import { formatDate, relativeTime } from "../components/followings/helpers";

interface ReportPayload {
  generated_at: string | null;
  html: string | null;
}

function errText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
}

export default function WeeklyReport() {
  const queryClient = useQueryClient();
  const [preview, setPreview] = useState<ReportPayload | null>(null);
  const [sendResult, setSendResult] = useState<{ ok: boolean; message: string } | null>(null);

  const latestQuery = useQuery({
    queryKey: ["weekly-report"],
    queryFn: () => api<ReportPayload>("/weekly-report"),
  });

  const previewMutation = useMutation({
    mutationFn: () => api<ReportPayload>("/weekly-report/preview", { method: "POST" }),
    onSuccess: (res) => {
      setPreview(res);
      void queryClient.invalidateQueries({ queryKey: ["weekly-report"] });
    },
  });

  const sendMutation = useMutation({
    mutationFn: () => api<{ ok: boolean; message?: string }>("/weekly-report/send", { method: "POST" }),
    onSuccess: (res) => {
      setSendResult({ ok: res.ok !== false, message: res.message ?? (res.ok !== false ? "周报已发送" : "发送失败") });
      void queryClient.invalidateQueries({ queryKey: ["weekly-report"] });
    },
    onError: (err) => setSendResult({ ok: false, message: errText(err, "发送失败，请稍后重试") }),
  });

  const latest = latestQuery.data;
  const shown: ReportPayload | null = preview ?? (latest?.html ? latest : null);
  const isPreview = preview != null;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">每周周报</h1>
        {shown?.generated_at && (
          <span className="text-xs text-slate-500" title={formatDate(shown.generated_at)}>
            {isPreview ? "预览生成于 " : "上次生成 "}
            {relativeTime(shown.generated_at)}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {(previewMutation.isError || sendMutation.isError) && (
            <span className="text-xs text-red-400" role="alert">
              {errText(previewMutation.error ?? sendMutation.error, "操作失败")}
            </span>
          )}
          <Button
            variant="ghost"
            onClick={() => previewMutation.mutate()}
            disabled={previewMutation.isPending}
            aria-label="生成周报预览"
          >
            {previewMutation.isPending ? "生成中…" : "生成预览"}
          </Button>
          <Button
            variant="primary"
            onClick={() => sendMutation.mutate()}
            disabled={sendMutation.isPending}
            aria-label="立即发送周报邮件"
          >
            {sendMutation.isPending ? "发送中…" : "立即发送"}
          </Button>
        </div>
      </header>

      {latestQuery.isLoading && <Spinner label="正在加载最新周报…" />}
      {latestQuery.error && <ErrorState message={errText(latestQuery.error, "加载周报失败")} />}

      {sendResult && (
        <p
          className={`text-xs px-3 py-2 rounded-lg ${sendResult.ok ? "text-emerald-300 bg-emerald-500/10" : "text-red-300 bg-red-500/10"}`}
          role="status"
          aria-live="polite"
        >
          {sendResult.message}
          <button
            type="button"
            onClick={() => setSendResult(null)}
            aria-label="关闭提示"
            className="ml-2 underline underline-offset-2 hover:text-white"
          >
            关闭
          </button>
        </p>
      )}

      {shown?.html ? (
        <section aria-label="周报内容" className="space-y-2">
          {isPreview && <Badge tone="info">预览（尚未存为最新报告，点「立即发送」生成并发送）</Badge>}
          <div className="surface p-2">
            <iframe
              title="周报内容预览"
              srcDoc={shown.html}
              sandbox="allow-same-origin"
              className="w-full h-[560px] rounded-lg bg-white"
            />
          </div>
        </section>
      ) : (
        !latestQuery.isLoading &&
        !latestQuery.error && (
          <EmptyState title="还没有生成过周报" hint="点击「生成预览」查看本周观看总结，或配置 SMTP 后「立即发送」到邮箱" />
        )
      )}
    </div>
  );
}
