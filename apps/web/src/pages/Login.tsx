import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";

export default function Login({ needsSetup, demoMode }: { needsSetup: boolean; demoMode: boolean }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const queryClient = useQueryClient();

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(needsSetup ? "/auth/setup" : "/auth/login", {
        method: "POST",
        body: { username, password },
      });
      await queryClient.invalidateQueries();
      window.location.href = "/";
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="surface glow w-full max-w-sm p-8">
        <h1 className="text-xl font-bold text-center">
          BiliUP <span className="text-indigo-400">Organizer</span>
        </h1>
        <p className="text-xs text-slate-500 text-center mt-1">
          {needsSetup ? "首次使用，创建管理员账号" : "登录以继续"}
        </p>
        <form className="mt-6 space-y-4" onSubmit={submit}>
          <label className="block text-sm">
            <span className="text-slate-400">用户名</span>
            <input
              className="mt-1 w-full bg-slate-900/70 border border-slate-700 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-400"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-400">密码</span>
            <input
              type="password"
              className="mt-1 w-full bg-slate-900/70 border border-slate-700 rounded-lg px-3 py-2 text-sm outline-none focus:border-indigo-400"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && (
            <p className="text-xs text-red-400" role="alert">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={busy}
            className="w-full bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white rounded-lg py-2 text-sm font-medium"
          >
            {busy ? "请稍候…" : needsSetup ? "创建账号" : "登录"}
          </button>
        </form>
        {demoMode && (
          <p className="mt-4 text-xs text-amber-300/80 text-center">演示模式：任意用户名密码均可登录</p>
        )}
      </div>
    </div>
  );
}
