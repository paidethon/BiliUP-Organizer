// Time display helpers — every timestamp is shown in Asia/Shanghai regardless
// of the viewer's browser/device timezone (T1). Backend stamps arrive either
// as naive-UTC "YYYY-MM-DD HH:MM:SS" (storage convention) or ISO 8601 with an
// explicit offset; both are normalized here.

const TZ = "Asia/Shanghai";

/** Parse a backend stamp into a Date at the correct absolute instant. */
export function parseStamp(value: string | null | undefined): Date | null {
  if (!value) return null;
  let text = String(value).trim().replace(" ", "T");
  if (/[Zz]|[+-]\d{2}:?\d{2}$/.test(text)) {
    const d = new Date(text);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  // naive string: storage convention is UTC
  const d = new Date(`${text}Z`);
  if (!Number.isNaN(d.getTime())) return d;
  const fallback = new Date(text);
  return Number.isNaN(fallback.getTime()) ? null : fallback;
}

const dateTimeFmt = new Intl.DateTimeFormat("zh-CN", {
  timeZone: TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const dateFmt = new Intl.DateTimeFormat("zh-CN", {
  timeZone: TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

export function formatDateTimeShanghai(value: string | null | undefined): string {
  const d = parseStamp(value);
  return d ? dateTimeFmt.format(d).replace(/\//g, "-") : "—";
}

export function formatDateShanghai(value: string | null | undefined): string {
  const d = parseStamp(value);
  return d ? dateFmt.format(d).replace(/\//g, "-") : "—";
}

export function relativeTime(value: string | null | undefined, now: number = Date.now()): string {
  const d = parseStamp(value);
  if (!d) return "—";
  const diff = now - d.getTime();
  const future = diff < 0;
  const abs = Math.abs(diff);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  let text: string;
  if (abs < minute) text = "刚刚";
  else if (abs < hour) text = `${Math.floor(abs / minute)} 分钟`;
  else if (abs < day) text = `${Math.floor(abs / hour)} 小时`;
  else if (abs < 30 * day) text = `${Math.floor(abs / day)} 天`;
  else text = `${Math.floor(abs / (30 * day))} 个月`;
  if (text === "刚刚") return text;
  return future ? `${text}后` : `${text}前`;
}

/** Seconds -> compact zh duration ("2 小时 3 分" / "5 分钟" / "40 秒"). */
export function humanDuration(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.round(Number(seconds ?? 0)));
  const m = Math.floor(total / 60);
  const s = total % 60;
  const h = Math.floor(m / 60);
  if (h > 0) return `${h} 小时 ${m % 60} 分钟`;
  if (m > 0) return `${m} 分钟`;
  return `${s} 秒`;
}

/** Week helpers on the Shanghai calendar (Monday-first). */
export function mondayOf(d: Date): Date {
  const sh = new Date(d.toLocaleString("en-US", { timeZone: TZ }));
  const day = (sh.getDay() + 6) % 7; // 0=Monday
  sh.setDate(sh.getDate() - day);
  sh.setHours(0, 0, 0, 0);
  return sh;
}

export function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function addDays(d: Date, days: number): Date {
  const copy = new Date(d);
  copy.setDate(copy.getDate() + days);
  return copy;
}

export const WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
