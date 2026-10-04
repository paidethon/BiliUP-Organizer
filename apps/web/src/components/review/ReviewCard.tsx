import { useState } from "react";
import type { Group, Suggestion } from "../../api";
import { Badge, Button, Input, Modal, Select } from "../ui";
import { formatDate, relativeTime, UpAvatar } from "../followings/helpers";

export type ReviewDecision = "accept" | "reject" | "unclassifiable";

const STATUS_BADGE: Record<string, { label: string; tone: "info" | "ok" | "warn" | "danger" }> = {
  pending: { label: "待审核", tone: "warn" },
  accepted: { label: "已通过", tone: "ok" },
  rejected: { label: "已拒绝", tone: "danger" },
  unclassifiable: { label: "无法确定", tone: "info" },
};

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
  const high = value >= 0.9;
  const low = value < 0.65;
  const bar = high ? "bg-emerald-400" : low ? "bg-amber-400" : "bg-indigo-400";
  const text = high ? "text-emerald-300" : low ? "text-amber-300" : "text-slate-400";
  return (
    <div className="flex items-center gap-2 min-w-[120px]" title={`置信度 ${pct}%`}>
      <div
        className="h-1.5 w-20 rounded-full bg-slate-700/60 overflow-hidden"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`置信度 ${pct}%`}
      >
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs tabular-nums ${text}`}>{pct}%</span>
    </div>
  );
}

export interface ReviewCardProps {
  suggestion: Suggestion;
  actionable: boolean;
  selected: boolean;
  skipped: boolean;
  pendingDecision: boolean;
  groups: Group[];
  onToggle: (id: number) => void;
  onDecide: (id: number, decision: ReviewDecision) => void;
  onSkip: (id: number) => void;
  onEditAccept: (s: Suggestion, groupId: number | null, tags: string[]) => void;
}

export function ReviewCard({
  suggestion: s,
  actionable,
  selected,
  skipped,
  pendingDecision,
  groups,
  onToggle,
  onDecide,
  onSkip,
  onEditAccept,
}: ReviewCardProps) {
  const [editOpen, setEditOpen] = useState(false);
  const [editGroupId, setEditGroupId] = useState("");
  const [editTags, setEditTags] = useState("");
  const name = s.up_uname || `mid:${s.up_mid}`;
  const disabled = pendingDecision;
  const status = STATUS_BADGE[s.status] ?? { label: s.status, tone: "info" as const };
  const changed = s.previous_group_name != null && s.previous_group_name !== s.suggested_group_name;
  const sameGroup = s.previous_group_name != null && s.previous_group_name === s.suggested_group_name;

  function openEdit() {
    setEditGroupId(s.suggested_group_id != null ? String(s.suggested_group_id) : "");
    setEditTags((s.suggested_tags ?? []).join("，"));
    setEditOpen(true);
  }

  function submitEdit() {
    const tags = editTags
      .split(/[,，]/)
      .map((t) => t.trim())
      .filter(Boolean);
    onEditAccept(s, editGroupId ? Number(editGroupId) : null, tags);
    setEditOpen(false);
  }

  return (
    <div
      role="row"
      data-suggestion-id={s.id}
      className={`surface p-4 transition-opacity ${skipped ? "opacity-50" : ""}`}
    >
      <div role="cell" className="space-y-2.5">
        <div className="flex items-start gap-3">
          {actionable && s.status === "pending" && (
            <input
              type="checkbox"
              className="mt-1.5"
              checked={selected}
              onChange={() => onToggle(s.id)}
              aria-label={`选择 ${name} 的建议`}
            />
          )}
          <UpAvatar face={s.up_face} uname={name} size={36} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium truncate max-w-[240px]" title={name}>
                {s.up_uname || <span className="text-slate-500">mid:{s.up_mid}</span>}
              </span>
              <Badge tone={status.tone}>{status.label}</Badge>
              {s.status_labels.map((label) => (
                <span key={label} className="px-2 py-0.5 rounded-full text-xs bg-slate-700/40 text-slate-400">
                  {label}
                </span>
              ))}
            </div>
            <p className="mt-1 text-xs">
              {sameGroup ? (
                <span className="text-slate-500">分类不变：{s.suggested_group_name || "—"}</span>
              ) : (
                <>
                  <span className="text-slate-500">原分类：{s.previous_group_name ?? "—"}</span>
                  <span aria-hidden="true" className="mx-1.5 text-slate-600">
                    →
                  </span>
                  <span className={changed ? "text-amber-300 font-medium" : "text-slate-300"}>
                    新建议：{s.suggested_group_name || "—"}
                  </span>
                </>
              )}
              {s.current_group_name && s.current_group_name !== s.previous_group_name && (
                <span className="ml-2 text-slate-600" title={`当前实际分组：${s.current_group_name}`}>
                  （现属 {s.current_group_name}）
                </span>
              )}
            </p>
          </div>
          <div className="shrink-0 flex flex-col items-end gap-1">
            <ConfidenceBar value={s.confidence} />
            <span className="text-xs text-slate-500" title={formatDate(s.created_at)}>
              {relativeTime(s.created_at)}
            </span>
          </div>
        </div>

        {(s.suggested_tags ?? []).length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {s.suggested_tags.map((tag) => (
              <Badge key={tag} tone="info">
                {tag}
              </Badge>
            ))}
          </div>
        )}

        {s.rationale && <p className="text-xs text-slate-400 whitespace-pre-wrap break-words">{s.rationale}</p>}

        {(s.evidence?.video_count != null || s.evidence?.source) && (
          <div className="text-xs text-slate-500 space-y-0.5">
            {s.evidence?.video_count != null && <p>依据：最近 {s.evidence.video_count} 个投稿</p>}
            {s.evidence?.source && <p className="text-slate-600">来源：{s.evidence.source}</p>}
          </div>
        )}

        {s.recent_videos.length > 0 && (
          <ul className="text-xs text-slate-500 space-y-0.5" aria-label={`${name} 最近投稿`}>
            {s.recent_videos.slice(0, 3).map((v, i) => (
              <li key={`${s.id}-${i}`} className="truncate" title={`${v.title}${v.tname ? ` · ${v.tname}` : ""}`}>
                <span aria-hidden="true" className="text-slate-600 mr-1">
                  ▸
                </span>
                {v.title}
                {v.tname && <span className="ml-1.5 text-slate-600">[{v.tname}]</span>}
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          <span className="text-xs text-slate-600 truncate max-w-[180px]" title={s.model}>
            {s.model || "—"}
            {s.provider ? ` · ${s.provider}` : ""}
          </span>
          {actionable && s.status === "pending" && (
            <div className="ml-auto flex flex-wrap gap-1.5">
              <button
                type="button"
                disabled={disabled}
                onClick={() => onDecide(s.id, "accept")}
                aria-label={`通过 ${name} 的建议`}
                className="px-2 py-1 rounded-lg text-xs bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50"
              >
                通过
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={openEdit}
                aria-label={`修改并接受 ${name} 的建议`}
                className="px-2 py-1 rounded-lg text-xs bg-indigo-500/15 text-indigo-300 hover:bg-indigo-500/25 disabled:opacity-50"
              >
                修改并接受
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onSkip(s.id)}
                aria-label={`跳过 ${name} 的建议`}
                className="px-2 py-1 rounded-lg text-xs bg-slate-800 text-slate-300 hover:bg-slate-700 disabled:opacity-50"
              >
                跳过
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onDecide(s.id, "unclassifiable")}
                aria-label={`标记 ${name} 无法判断`}
                className="px-2 py-1 rounded-lg text-xs bg-amber-500/10 text-amber-300 hover:bg-amber-500/20 disabled:opacity-50"
              >
                无法判断
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onDecide(s.id, "reject")}
                aria-label={`拒绝 ${name} 的建议`}
                className="px-2 py-1 rounded-lg text-xs bg-red-500/10 text-red-300 hover:bg-red-500/20 disabled:opacity-50"
              >
                拒绝
              </button>
            </div>
          )}
        </div>
      </div>

      <Modal open={editOpen} title={`修改并接受 — ${name}`} onClose={() => setEditOpen(false)}>
        <div className="space-y-3">
          <p className="text-xs text-slate-400">
            先按建议通过，再用下方修改覆盖：主分类会更新为所选分组，标签会追加到该 UP 主。
          </p>
          <div className="space-y-1">
            <label htmlFor="edit-group" className="text-xs text-slate-400">
              主分类
            </label>
            <Select id="edit-group" value={editGroupId} onChange={(e) => setEditGroupId(e.target.value)} className="w-full">
              <option value="">（不修改分组）</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <label htmlFor="edit-tags" className="text-xs text-slate-400">
              标签（逗号分隔）
            </label>
            <Input
              id="edit-tags"
              value={editTags}
              onChange={(e) => setEditTags(e.target.value)}
              placeholder="例如：科技, 数码"
              className="w-full"
            />
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setEditOpen(false)}>
              取消
            </Button>
            <Button variant="primary" disabled={pendingDecision} onClick={submitEdit}>
              确认并通过
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
