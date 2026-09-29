import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

export function Button({
  variant = "primary",
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" | "subtle" }) {
  const styles: Record<string, string> = {
    primary: "bg-indigo-500 hover:bg-indigo-400 text-white",
    ghost: "bg-transparent hover:bg-white/5 text-slate-200 border border-slate-700",
    subtle: "bg-slate-800 hover:bg-slate-700 text-slate-200",
    danger: "bg-red-500/90 hover:bg-red-500 text-white",
  };
  return (
    <button
      className={`px-3 py-1.5 rounded-lg text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${styles[variant]} ${className}`}
      {...rest}
    />
  );
}

export function Input({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`bg-slate-900/70 border border-slate-700 rounded-lg px-3 py-1.5 text-sm outline-none focus:border-indigo-400 ${className}`}
      {...rest}
    />
  );
}

export function Select({ className = "", children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={`bg-slate-900/70 border border-slate-700 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-indigo-400 ${className}`}
      {...rest}
    >
      {children}
    </select>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`surface p-4 ${className}`}>{children}</div>;
}

export function Badge({ tone = "info", children }: { tone?: "info" | "ok" | "warn" | "danger"; children: ReactNode }) {
  const tones: Record<string, string> = {
    info: "bg-indigo-500/15 text-indigo-300",
    ok: "bg-emerald-500/15 text-emerald-300",
    warn: "bg-amber-500/15 text-amber-300",
    danger: "bg-red-500/15 text-red-300",
  };
  return <span className={`px-2 py-0.5 rounded-full text-xs ${tones[tone]}`}>{children}</span>;
}

export function Spinner({ label = "加载中…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-slate-400 text-sm py-8 justify-center" role="status">
      <span className="h-4 w-4 rounded-full border-2 border-indigo-400 border-t-transparent animate-spin" />
      {label}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="text-center py-12 text-slate-500">
      <p className="text-sm">{title}</p>
      {hint && <p className="text-xs mt-1">{hint}</p>}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="text-center py-12 text-red-400 text-sm" role="alert">
      出错了：{message}
    </div>
  );
}

export function Modal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="surface glow w-full max-w-lg max-h-[85vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/60">
          <h2 className="text-sm font-semibold">{title}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white" aria-label="关闭">
            ✕
          </button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}
