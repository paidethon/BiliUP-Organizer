import { useId, useState, type ReactNode } from "react";
import { Badge, Button } from "../ui";

export interface SectionCardProps {
  title: string;
  description?: string;
  /** 后端 reported 的 configured 状态；undefined 时不显示徽标。 */
  configured?: boolean;
  children: ReactNode;
}

/** 可折叠设置分区卡：头部为展开/收起按钮（含配置状态徽标），展开后渲染表单内容。 */
export function SectionCard({ title, description, configured, children }: SectionCardProps) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();

  return (
    <section className="surface" aria-label={title}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={bodyId}
        className="w-full flex flex-wrap items-center gap-2 px-4 py-3 text-left"
      >
        <span aria-hidden="true" className={`text-xs text-slate-500 transition-transform ${open ? "rotate-90" : ""}`}>
          ▶
        </span>
        <h2 className="text-sm font-semibold">{title}</h2>
        {typeof configured === "boolean" && (
          <Badge tone={configured ? "ok" : "warn"}>{configured ? "已配置" : "未配置"}</Badge>
        )}
        {description && <span className="text-xs text-slate-500 ml-2 hidden sm:inline">{description}</span>}
        <span className="ml-auto text-xs text-slate-500" aria-hidden="true">
          {open ? "收起" : "展开"}
        </span>
      </button>
      {open && (
        <div id={bodyId} className="px-4 pb-4 border-t border-slate-700/60 pt-4">
          {children}
        </div>
      )}
    </section>
  );
}

/** 分区表单共用底栏：保存按钮 + 成功 / 错误提示。 */
export function SectionSaveFooter({
  saving,
  saved,
  error,
  onSave,
}: {
  saving: boolean;
  saved: boolean;
  error: string | null;
  onSave: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-slate-800/60 mt-4 pt-3">
      <Button variant="primary" onClick={onSave} disabled={saving}>
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
    </div>
  );
}
