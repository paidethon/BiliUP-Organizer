import { useEffect, useState } from "react";
import { Button } from "../ui";
import { NumberField, TextField, TestButton, ToggleField } from "./fields";

// ---- GET /settings 返回的分区类型（密钥字段为掩码或空串） ----

export interface AiSectionValue {
  base_url: string;
  api_key: string;
  model: string;
  enabled: boolean;
  configured?: boolean;
}

export interface SmtpSectionValue {
  host: string;
  port: number;
  username: string;
  password: string;
  from_addr: string;
  to_addr: string;
  use_tls: boolean;
  enabled: boolean;
  configured?: boolean;
}

export interface LumirssSectionValue {
  base_url: string;
  token: string;
  inbox_endpoint: string;
  enabled: boolean;
  configured?: boolean;
}

export interface RemindersSectionValue {
  stale_days: number;
  long_unwatched_days: number;
  never_watched_days: number;
  low_confidence_threshold: number;
  email_enabled: boolean;
  weekly_report_enabled: boolean;
}

export interface SyncSectionValue {
  interval_hours: number;
  history_enabled: boolean;
  history_max_pages: number;
}

export interface SettingsData {
  ai: AiSectionValue;
  smtp: SmtpSectionValue;
  lumirss: LumirssSectionValue;
  reminders: RemindersSectionValue;
  sync: SyncSectionValue;
}

/** 分区表单公共 props：value 为服务端数据，保存时把整区对象交给页面提交。 */
export interface SectionFormProps<T> {
  value: T;
  saving: boolean;
  saved: boolean;
  error: string | null;
  onSave: (body: Record<string, unknown>) => void;
}

function SectionFooter({
  saveLabel,
  saving,
  saved,
  error,
  onSave,
}: {
  saveLabel: string;
  saving: boolean;
  saved: boolean;
  error: string | null;
  onSave: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-slate-800/60 mt-1 pt-3">
      <Button variant="primary" onClick={onSave} disabled={saving} aria-label={saveLabel}>
        {saving ? "保存中…" : "保存"}
      </Button>
      {saved && (
        <span className="text-xs text-emerald-300" role="status">
          ✓ 已保存
        </span>
      )}
      {error && (
        <span className="text-xs text-red-300" role="alert">
          {error}
        </span>
      )}
      <span className="text-xs text-slate-600">密钥留空或保持掩码表示不修改</span>
    </div>
  );
}

/** 数值字符串 → 数字；非法输入时回退到当前值。 */
function num(value: string, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

const secretPlaceholder = (filled: boolean) => (filled ? "已配置，留空保持不变" : "未配置");

// ---- AI ----

export function AiSectionForm({ value, saving, saved, error, onSave }: SectionFormProps<AiSectionValue>) {
  const [draft, setDraft] = useState({
    base_url: value.base_url,
    api_key: value.api_key,
    model: value.model,
    enabled: value.enabled,
  });
  useEffect(() => {
    setDraft({ base_url: value.base_url, api_key: value.api_key, model: value.model, enabled: value.enabled });
  }, [value]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <TextField
          label="Base URL"
          value={draft.base_url}
          onChange={(e) => setDraft((d) => ({ ...d, base_url: e.target.value }))}
          placeholder="https://api.example.com/v1"
          autoComplete="off"
        />
        <TextField
          label="API Key"
          type="password"
          value={draft.api_key}
          onChange={(e) => setDraft((d) => ({ ...d, api_key: e.target.value }))}
          placeholder={secretPlaceholder(Boolean(value.api_key))}
          autoComplete="new-password"
        />
        <TextField
          label="模型"
          value={draft.model}
          onChange={(e) => setDraft((d) => ({ ...d, model: e.target.value }))}
          placeholder="例如 gpt-4o-mini / deepseek-chat"
          autoComplete="off"
        />
        <div className="flex items-end pb-1.5">
          <ToggleField label="启用 AI 分类" checked={draft.enabled} onChange={(v) => setDraft((d) => ({ ...d, enabled: v }))} />
        </div>
      </div>
      <TestButton what="ai" label="测试连接" hint="使用已保存的配置发起测试" />
      <SectionFooter saveLabel="保存 AI 分类" saving={saving} saved={saved} error={error} onSave={() => onSave(draft)} />
    </div>
  );
}

// ---- SMTP ----

export function SmtpSectionForm({ value, saving, saved, error, onSave }: SectionFormProps<SmtpSectionValue>) {
  const [draft, setDraft] = useState({
    host: value.host,
    port: String(value.port),
    username: value.username,
    password: value.password,
    from_addr: value.from_addr,
    to_addr: value.to_addr,
    use_tls: value.use_tls,
    enabled: value.enabled,
  });
  useEffect(() => {
    setDraft({
      host: value.host,
      port: String(value.port),
      username: value.username,
      password: value.password,
      from_addr: value.from_addr,
      to_addr: value.to_addr,
      use_tls: value.use_tls,
      enabled: value.enabled,
    });
  }, [value]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <TextField
          label="SMTP 服务器"
          value={draft.host}
          onChange={(e) => setDraft((d) => ({ ...d, host: e.target.value }))}
          placeholder="smtp.example.com"
        />
        <NumberField
          label="端口"
          value={draft.port}
          onChange={(v) => setDraft((d) => ({ ...d, port: v }))}
          min={1}
          max={65535}
          hint="465（SSL）或 587（STARTTLS）"
        />
        <TextField
          label="用户名"
          value={draft.username}
          onChange={(e) => setDraft((d) => ({ ...d, username: e.target.value }))}
          autoComplete="off"
        />
        <TextField
          label="密码 / 授权码"
          type="password"
          value={draft.password}
          onChange={(e) => setDraft((d) => ({ ...d, password: e.target.value }))}
          placeholder={secretPlaceholder(Boolean(value.password))}
          autoComplete="new-password"
        />
        <TextField
          label="发件地址"
          value={draft.from_addr}
          onChange={(e) => setDraft((d) => ({ ...d, from_addr: e.target.value }))}
          placeholder="biliup@example.com"
        />
        <TextField
          label="收件地址"
          value={draft.to_addr}
          onChange={(e) => setDraft((d) => ({ ...d, to_addr: e.target.value }))}
          placeholder="me@example.com"
        />
        <div className="flex items-end gap-6 pb-1.5">
          <ToggleField label="使用 TLS" checked={draft.use_tls} onChange={(v) => setDraft((d) => ({ ...d, use_tls: v }))} />
          <ToggleField label="启用邮件提醒" checked={draft.enabled} onChange={(v) => setDraft((d) => ({ ...d, enabled: v }))} />
        </div>
      </div>
      <TestButton what="email" label="发送测试邮件" hint="使用已保存的配置发送" />
      <SectionFooter
        saveLabel="保存邮件设置"
        saving={saving}
        saved={saved}
        error={error}
        onSave={() => onSave({ ...draft, port: num(draft.port, value.port) })}
      />
    </div>
  );
}

// ---- LumiRSS ----

export function LumirssSectionForm({ value, saving, saved, error, onSave }: SectionFormProps<LumirssSectionValue>) {
  const [draft, setDraft] = useState({
    base_url: value.base_url,
    token: value.token,
    inbox_endpoint: value.inbox_endpoint,
    enabled: value.enabled,
  });
  useEffect(() => {
    setDraft({
      base_url: value.base_url,
      token: value.token,
      inbox_endpoint: value.inbox_endpoint,
      enabled: value.enabled,
    });
  }, [value]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <TextField
          label="Base URL"
          value={draft.base_url}
          onChange={(e) => setDraft((d) => ({ ...d, base_url: e.target.value }))}
          placeholder="http://127.0.0.1:8787"
          autoComplete="off"
        />
        <TextField
          label="Token"
          type="password"
          value={draft.token}
          onChange={(e) => setDraft((d) => ({ ...d, token: e.target.value }))}
          placeholder={secretPlaceholder(Boolean(value.token))}
          autoComplete="new-password"
        />
        <TextField
          label="Inbox 端点"
          value={draft.inbox_endpoint}
          onChange={(e) => setDraft((d) => ({ ...d, inbox_endpoint: e.target.value }))}
          placeholder="/inbox"
        />
        <div className="flex items-end pb-1.5">
          <ToggleField label="启用 LumiRSS" checked={draft.enabled} onChange={(v) => setDraft((d) => ({ ...d, enabled: v }))} />
        </div>
      </div>
      <TestButton what="lumirss" label="测试连接" hint="使用已保存的配置发起测试" />
      <SectionFooter saveLabel="保存 LumiRSS 设置" saving={saving} saved={saved} error={error} onSave={() => onSave(draft)} />
    </div>
  );
}

// ---- 提醒阈值 ----

export function RemindersSectionForm({ value, saving, saved, error, onSave }: SectionFormProps<RemindersSectionValue>) {
  const [draft, setDraft] = useState({
    stale_days: String(value.stale_days),
    long_unwatched_days: String(value.long_unwatched_days),
    never_watched_days: String(value.never_watched_days),
    low_confidence_threshold: String(value.low_confidence_threshold),
  });
  useEffect(() => {
    setDraft({
      stale_days: String(value.stale_days),
      long_unwatched_days: String(value.long_unwatched_days),
      never_watched_days: String(value.never_watched_days),
      low_confidence_threshold: String(value.low_confidence_threshold),
    });
  }, [value]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <NumberField
          label="断更天数阈值"
          value={draft.stale_days}
          onChange={(v) => setDraft((d) => ({ ...d, stale_days: v }))}
          min={1}
          hint="UP 超过该天数未投稿视为断更"
        />
        <NumberField
          label="长期未看天数"
          value={draft.long_unwatched_days}
          onChange={(v) => setDraft((d) => ({ ...d, long_unwatched_days: v }))}
          min={1}
          hint="超过该天数未观看则提醒"
        />
        <NumberField
          label="从未观看天数"
          value={draft.never_watched_days}
          onChange={(v) => setDraft((d) => ({ ...d, never_watched_days: v }))}
          min={1}
          hint="关注超过该天数仍未看过则提醒"
        />
        <NumberField
          label="低置信度阈值"
          value={draft.low_confidence_threshold}
          onChange={(v) => setDraft((d) => ({ ...d, low_confidence_threshold: v }))}
          min={0}
          max={1}
          step={0.05}
          hint="AI 置信度低于该值时生成低置信度提醒（0–1）"
        />
      </div>
      <SectionFooter
        saveLabel="保存提醒阈值"
        saving={saving}
        saved={saved}
        error={error}
        onSave={() =>
          onSave({
            stale_days: num(draft.stale_days, value.stale_days),
            long_unwatched_days: num(draft.long_unwatched_days, value.long_unwatched_days),
            never_watched_days: num(draft.never_watched_days, value.never_watched_days),
            low_confidence_threshold: num(draft.low_confidence_threshold, value.low_confidence_threshold),
          })
        }
      />
    </div>
  );
}

// ---- 同步 ----

export function SyncSectionForm({ value, saving, saved, error, onSave }: SectionFormProps<SyncSectionValue>) {
  const [draft, setDraft] = useState({
    interval_hours: String(value.interval_hours),
    history_max_pages: String(value.history_max_pages),
    history_enabled: value.history_enabled,
  });
  useEffect(() => {
    setDraft({
      interval_hours: String(value.interval_hours),
      history_max_pages: String(value.history_max_pages),
      history_enabled: value.history_enabled,
    });
  }, [value]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <NumberField
          label="同步间隔（小时）"
          value={draft.interval_hours}
          onChange={(v) => setDraft((d) => ({ ...d, interval_hours: v }))}
          min={1}
          hint="定时任务按该间隔执行完整同步"
        />
        <NumberField
          label="历史最大抓取页数"
          value={draft.history_max_pages}
          onChange={(v) => setDraft((d) => ({ ...d, history_max_pages: v }))}
          min={1}
          hint="每次同步最多拉取的观看历史页数"
        />
        <div className="flex items-end pb-1.5">
          <ToggleField
            label="同步观看历史"
            checked={draft.history_enabled}
            onChange={(v) => setDraft((d) => ({ ...d, history_enabled: v }))}
            hint="关闭后不再抓取观看记录，统计与周报将停滞"
          />
        </div>
      </div>
      <SectionFooter
        saveLabel="保存同步设置"
        saving={saving}
        saved={saved}
        error={error}
        onSave={() =>
          onSave({
            interval_hours: num(draft.interval_hours, value.interval_hours),
            history_max_pages: num(draft.history_max_pages, value.history_max_pages),
            history_enabled: draft.history_enabled,
          })
        }
      />
    </div>
  );
}

// ---- 共用底栏 ----（SectionFooter 定义见文件上方）
