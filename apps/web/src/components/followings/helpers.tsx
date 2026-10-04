import { useState } from "react";
import { Badge } from "../ui";

/** Parse backend naive "YYYY-MM-DD HH:MM:SS" (or ISO) timestamps; null on failure. */
export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "3 天前" style relative label, or "—" when unknown. */
export function relativeTime(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "—";
  const diffMs = Date.now() - d.getTime();
  if (diffMs < 0) return "刚刚";
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 365) return `${days} 天前`;
  return `${Math.floor(days / 365)} 年前`;
}

/** Whole days since the timestamp (0 when in the future), or null when unknown. */
export function daysSince(value: string | null | undefined): number | null {
  const d = parseDate(value);
  if (!d) return null;
  return Math.max(0, Math.floor((Date.now() - d.getTime()) / 86_400_000));
}

/** Localized absolute timestamp for tooltips / detail views. */
export function formatDate(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "—";
  return d.toLocaleString("zh-CN", { hour12: false });
}

/** 视频时长：后端存储为 "mm:ss" 文本；数字则格式化为 mm:ss。 */
export function formatDuration(seconds: string | number | null | undefined): string {
  if (seconds == null || seconds === "") return "—";
  if (typeof seconds === "string") return seconds.includes(":") ? seconds : "—";
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** UP 主头像；加载失败或无头像时退化为首字占位。 */
export function UpAvatar({ face, uname, size = 32 }: { face: string; uname: string; size?: number }) {
  const [hidden, setHidden] = useState(false);
  const style = { width: size, height: size };
  if (hidden || !face) {
    return (
      <span
        aria-hidden="true"
        style={style}
        className="flex items-center justify-center rounded-full bg-indigo-500/20 text-xs text-indigo-300 shrink-0"
      >
        {uname.slice(0, 1) || "?"}
      </span>
    );
  }
  return (
    <img
      src={face}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      onError={() => setHidden(true)}
      className="rounded-full object-cover shrink-0"
    />
  );
}

/** 组色圆点 + 组名徽标；无分组时显示灰色「未分组」。 */
export function GroupBadge({
  color,
  name,
}: {
  color: string | undefined;
  name: string | null | undefined;
}) {
  if (!name) {
    return <span className="px-2 py-0.5 rounded-full text-xs bg-slate-700/40 text-slate-400">未分组</span>;
  }
  return (
    <span
      className="px-2 py-0.5 rounded-full text-xs whitespace-nowrap"
      style={color ? { backgroundColor: `${color}26`, color } : undefined}
    >
      {color && (
        <span
          aria-hidden="true"
          className="inline-block w-2 h-2 rounded-full mr-1 align-middle"
          style={{ backgroundColor: color }}
        />
      )}
      {name}
    </span>
  );
}

/** 标签小徽标：内联 tag.color 作为边框与文字色，超长截断。 */
export function TagBadge({ name, color }: { name: string; color?: string | null }) {
  return (
    <span
      title={name}
      className="px-1.5 py-0.5 rounded-full text-xs border whitespace-nowrap max-w-[110px] truncate align-middle"
      style={color ? { borderColor: color, color } : undefined}
    >
      {name}
    </span>
  );
}

const STATUS_WARN_LABELS = new Set(["待整理", "吃灰", "无法确定"]);

/** 状态标签 → Badge tone：待整理/吃灰/无法确定 → warn，重点关注等 → info。 */
export function StatusLabelBadge({ label }: { label: string }) {
  return <Badge tone={STATUS_WARN_LABELS.has(label) ? "warn" : "info"}>{label}</Badge>;
}
