import { Navigate, NavLink, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { useAuth } from "./auth";
import { Spinner } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import Followings from "./pages/Followings";
import Groups from "./pages/Groups";
import Review from "./pages/Review";
import Reminders from "./pages/Reminders";
import History from "./pages/History";
import WeeklyReport from "./pages/WeeklyReport";
import Settings from "./pages/Settings";

const NAV = [
  { to: "/", label: "仪表盘", end: true },
  { to: "/followings", label: "关注管理" },
  { to: "/groups", label: "本地分组" },
  { to: "/review", label: "AI 审核" },
  { to: "/reminders", label: "提醒中心" },
  { to: "/history", label: "观看历史" },
  { to: "/weekly-report", label: "每周周报" },
  { to: "/settings", label: "设置" },
];

function Shell() {
  const { username, demoMode } = useAuth();
  const navigate = useNavigate();
  if (!username) return <Navigate to="/login" replace />;
  return (
    <div className="flex min-h-screen">
      <aside className="w-52 shrink-0 border-r border-slate-800 bg-slate-950/60 hidden md:flex flex-col">
        <div className="px-4 py-5">
          <p className="text-base font-bold tracking-wide">
            BiliUP <span className="brand-grad">Organizer</span>
          </p>
          <div className="brand-rule mt-2 w-10" aria-hidden="true" />
          {demoMode && (
            <span className="mt-2 inline-block px-2 py-0.5 rounded-full text-xs bg-amber-500/15 text-amber-300">
              演示模式
            </span>
          )}
        </div>
        <nav className="flex-1 px-2 space-y-1" aria-label="主导航">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive ? "bg-indigo-500/15 text-indigo-300" : "text-slate-400 hover:text-white hover:bg-white/5"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 text-xs text-slate-500 border-t border-slate-800">
          <p>{username}</p>
          <button
            className="mt-1 text-slate-400 hover:text-white"
            onClick={async () => {
              await api("/auth/logout", { method: "POST" });
              navigate("/login");
            }}
          >
            退出登录
          </button>
        </div>
      </aside>
      <main className="flex-1 p-4 md:p-6 max-w-[1200px] mx-auto w-full">
        <div className="md:hidden mb-4 flex gap-2 overflow-x-auto">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `whitespace-nowrap px-3 py-1.5 rounded-full text-xs border ${
                  isActive
                    ? "border-indigo-400 text-indigo-300"
                    : "border-slate-700 text-slate-400"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
        <Outlet />
      </main>
    </div>
  );
}

function Guard() {
  const { data, isLoading } = useQuery({
    queryKey: ["auth-status"],
    queryFn: () => api<{ needs_setup: boolean; demo_mode: boolean; authenticated: boolean }>("/auth/status"),
  });
  if (isLoading || !data) return <Spinner />;
  if (data.authenticated) return <Navigate to="/" replace />;
  return <Login needsSetup={data.needs_setup} demoMode={data.demo_mode} />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Guard />} />
      <Route element={<Shell />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/followings" element={<Followings />} />
        <Route path="/groups" element={<Groups />} />
        <Route path="/review" element={<Review />} />
        <Route path="/reminders" element={<Reminders />} />
        <Route path="/history" element={<History />} />
        <Route path="/weekly-report" element={<WeeklyReport />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
