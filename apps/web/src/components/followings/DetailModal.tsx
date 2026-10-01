import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import { Badge, ErrorState, Modal, Spinner } from "../ui";
import { GroupBadge, StatusLabelBadge, TagBadge, UpAvatar, formatDuration, formatDate, relativeTime } from "./helpers";

interface DetailVideo {
  bvid: string;
  title: string;
  pubdate: string;
  cover: string;
  duration: string | number | null;
}

interface DetailSuggestion {
  id: number;
  suggested_group_name: string;
  confidence: number;
  rationale: string;
  model: string;
  status: string;
  created_at: string;
}

interface DetailReminder {
  id: number;
  rule_key: string;
  title: string;
  body: string;
  severity: "info" | "warning" | "critical";
}

interface FollowingDetail {
  up: {
    mid: number;
    uname: string;
    sign: string;
    face: string;
    group_name: string | null;
    groups?: { id: number; name: string; color: string }[];
    tags?: { id: number; name: string; color: string }[];
    status_labels?: string[];
    followed_at: string | null;
    last_video_at: string | null;
    last_watched_at: string | null;
    watched_count: number;
    missing: boolean;
    blacklisted: boolean;
    snoozed_until: string | null;
  };
  videos: DetailVideo[];
  suggestions: DetailSuggestion[];
  reminders: DetailReminder[];
}

const SEVERITY_TONE: Record<DetailReminder["severity"], "info" | "warn" | "danger"> = {
  info: "info",
  warning: "warn",
  critical: "danger",
};

export function FollowingDetailModal({
  mid,
  onClose,
}: {
  mid: number | null;
  onClose: () => void;
}) {
  const open = mid != null;
  const { data, isLoading, error } = useQuery({
    queryKey: ["followings", "detail", mid],
    queryFn: () => api<FollowingDetail>(`/followings/${mid}`),
    enabled: open,
  });

  return (
    <Modal open={open} title="UP 主详情" onClose={onClose}>
      {isLoading && <Spinner label="正在加载详情…" />}
      {error && <ErrorState message={error instanceof Error ? error.message : String(error)} />}
      {data && (
        <div className="space-y-5 text-sm">
          <section className="flex items-start gap-3" aria-label="基本信息">
            <UpAvatar face={data.up.face} uname={data.up.uname} size={48} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-base font-semibold">{data.up.uname}</h3>
                <span className="text-xs text-slate-500">MID {data.up.mid}</span>
                {data.up.missing && <Badge tone="danger">已取关</Badge>}
                {data.up.blacklisted && <Badge tone="danger">黑名单</Badge>}
              </div>
              {data.up.sign && <p className="text-xs text-slate-400 mt-0.5">{data.up.sign}</p>}
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 mt-2 text-xs text-slate-400">
                <div className="flex gap-1">
                  <dt className="text-slate-500">分组：</dt>
                  <dd>
                    <GroupBadge color={data.up.groups?.[0]?.color} name={data.up.group_name} />
                  </dd>
                </div>
                {data.up.tags && data.up.tags.length > 0 && (
                  <div className="flex gap-1 col-span-2">
                    <dt className="text-slate-500 shrink-0">标签：</dt>
                    <dd className="flex flex-wrap gap-1">
                      {data.up.tags.map((t) => (
                        <TagBadge key={t.id} name={t.name} color={t.color} />
                      ))}
                    </dd>
                  </div>
                )}
                {data.up.status_labels && data.up.status_labels.length > 0 && (
                  <div className="flex gap-1 col-span-2">
                    <dt className="text-slate-500 shrink-0">状态：</dt>
                    <dd className="flex flex-wrap gap-1">
                      {data.up.status_labels.map((label) => (
                        <StatusLabelBadge key={label} label={label} />
                      ))}
                    </dd>
                  </div>
                )}
                <div className="flex gap-1">
                  <dt className="text-slate-500">关注于：</dt>
                  <dd>{formatDate(data.up.followed_at)}</dd>
                </div>
                <div className="flex gap-1">
                  <dt className="text-slate-500">最近投稿：</dt>
                  <dd>{relativeTime(data.up.last_video_at)}</dd>
                </div>
                <div className="flex gap-1">
                  <dt className="text-slate-500">最近观看：</dt>
                  <dd>{data.up.last_watched_at ? relativeTime(data.up.last_watched_at) : "从未"}</dd>
                </div>
                <div className="flex gap-1">
                  <dt className="text-slate-500">已看视频：</dt>
                  <dd>{data.up.watched_count} 个</dd>
                </div>
                {data.up.snoozed_until && (
                  <div className="flex gap-1">
                    <dt className="text-slate-500">暂停至：</dt>
                    <dd>{formatDate(data.up.snoozed_until)}</dd>
                  </div>
                )}
              </dl>
            </div>
          </section>

          <section aria-label="最近投稿">
            <h4 className="text-xs text-slate-400 uppercase tracking-wide mb-2">最近投稿（{data.videos.length}）</h4>
            {data.videos.length === 0 ? (
              <p className="text-xs text-slate-500">暂无投稿记录</p>
            ) : (
              <ul className="space-y-1.5">
                {data.videos.map((v) => (
                  <li key={v.bvid} className="flex items-center gap-2 justify-between bg-slate-900/50 rounded-lg px-3 py-1.5">
                    <a
                      href={`https://www.bilibili.com/video/${v.bvid}`}
                      target="_blank"
                      rel="noreferrer"
                      className="truncate max-w-[300px] text-slate-200 hover:text-indigo-300"
                      aria-label={`打开视频 ${v.title}`}
                    >
                      {v.title}
                    </a>
                    <span className="text-xs text-slate-500 whitespace-nowrap">
                      {relativeTime(v.pubdate)} · {formatDuration(v.duration)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-label="AI 建议">
            <h4 className="text-xs text-slate-400 uppercase tracking-wide mb-2">AI 分组建议</h4>
            {data.suggestions.length === 0 ? (
              <p className="text-xs text-slate-500">暂无 AI 建议</p>
            ) : (
              <ul className="space-y-1.5">
                {data.suggestions.map((s) => (
                  <li key={s.id} className="bg-slate-900/50 rounded-lg px-3 py-2">
                    <div className="flex items-center gap-2">
                      <Badge tone={s.status === "pending" ? "warn" : "info"}>
                        {s.status === "pending" ? "待审核" : s.status}
                      </Badge>
                      <span className="text-slate-200">建议分组：{s.suggested_group_name || "未分组"}</span>
                      <span className="text-xs text-slate-500">置信度 {(s.confidence * 100).toFixed(0)}%</span>
                    </div>
                    {s.rationale && <p className="text-xs text-slate-400 mt-1">{s.rationale}</p>}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-label="开放提醒">
            <h4 className="text-xs text-slate-400 uppercase tracking-wide mb-2">提醒</h4>
            {data.reminders.length === 0 ? (
              <p className="text-xs text-slate-500">暂无开放提醒</p>
            ) : (
              <ul className="space-y-1.5">
                {data.reminders.map((r) => (
                  <li key={r.id} className="bg-slate-900/50 rounded-lg px-3 py-2">
                    <div className="flex items-center gap-2">
                      <Badge tone={SEVERITY_TONE[r.severity]}>{r.title}</Badge>
                      <span className="text-xs text-slate-500">{r.rule_key}</span>
                    </div>
                    {r.body && <p className="text-xs text-slate-400 mt-1">{r.body}</p>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </Modal>
  );
}
