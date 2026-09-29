import { useMutation } from "@tanstack/react-query";
import type { InputHTMLAttributes, ReactNode } from "react";
import { api } from "../../api";
import { Input } from "../ui";

/** 后端返回的密钥掩码；提交时原样传回即表示「保留原值」。 */
export const SECRET_MASK = "••••••••";

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs text-slate-400">{label}</span>
      {children}
      {hint && <span className="text-xs text-slate-600">{hint}</span>}
    </label>
  );
}

export function TextField({
  label,
  hint,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  return (
    <Field label={label} hint={hint}>
      <Input {...rest} />
    </Field>
  );
}

export function NumberField({
  label,
  value,
  onChange,
  hint,
  min,
  max,
  step,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <Field label={label} hint={hint}>
      <input
        type="number"
        className="bg-slate-900/70 border border-slate-700 rounded-lg px-3 py-1.5 text-sm outline-none focus:border-indigo-400"
        value={value}
        min={min}
        max={max}
        step={step ?? "any"}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  );
}

export function ToggleField({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
}) {
  return (
    <label className="flex items-start gap-2 text-sm cursor-pointer select-none">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 accent-indigo-500"
      />
      <span>
        <span className="text-slate-300">{label}</span>
        {hint && <span className="block text-xs text-slate-600">{hint}</span>}
      </span>
    </label>
  );
}

/** 测试连接 / 发送测试邮件按钮 + 结果文案。what ∈ {ai, email, lumirss}，测试使用后端已保存的配置。 */
export function TestButton({
  what,
  label,
  hint,
  disabled,
}: {
  what: "ai" | "email" | "lumirss";
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  const mutation = useMutation({
    mutationFn: () => api<{ ok: boolean; message: string }>(`/settings/test/${what}`, { method: "POST" }),
  });
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => mutation.mutate()}
          disabled={disabled || mutation.isPending}
          aria-label={label}
          className="px-3 py-1.5 rounded-lg text-sm border border-slate-700 text-slate-200 hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {mutation.isPending ? "测试中…" : label}
        </button>
        {mutation.data && (
          <span className={`text-xs ${mutation.data.ok ? "text-emerald-300" : "text-red-300"}`} role="status">
            {mutation.data.ok ? "✓ " : "✕ "}
            {mutation.data.message}
          </span>
        )}
        {mutation.isError && (
          <span className="text-xs text-red-300" role="alert">
            测试失败：{mutation.error instanceof Error ? mutation.error.message : "请稍后重试"}
          </span>
        )}
      </div>
      {hint && <span className="text-xs text-slate-600">{hint}</span>}
    </div>
  );
}
