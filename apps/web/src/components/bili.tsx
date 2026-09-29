import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { api, ApiError } from "../api";
import { Badge, Button, Card, ErrorState, Modal, Spinner } from "./ui";
import { formatDate } from "./followings/helpers";

export interface BilibiliAccount {
  login_status: string;
  mid: number | null;
  uname: string | null;
  avatar: string;
  cookie_updated_at: string | null;
  risk_flag: boolean;
  cookie_masked: string;
}

interface QrStartOut {
  qrcode_key: string;
  qr_url: string;
  expires_at: string;
}

interface QrPollOut {
  status: "waiting" | "scanned" | "confirmed" | "expired";
  account?: BilibiliAccount | null;
}

type QrPhase = "starting" | "waiting" | "scanned" | "confirmed" | "expired" | "failed";

const PHASE_TEXT: Record<QrPhase, string> = {
  starting: "正在获取二维码…",
  waiting: "请使用哔哩哔哩 App 扫描二维码",
  scanned: "已扫描，请在手机上确认登录",
  confirmed: "登录成功，正在刷新数据…",
  expired: "二维码已过期",
  failed: "二维码获取失败",
};

function QrLoginModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<QrPhase>("starting");
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [qrcodeKey, setQrcodeKey] = useState<string | null>(null);
  const [error, setError] = useState("");

  const start = useCallback(async () => {
    setPhase("starting");
    setQrDataUrl(null);
    setQrcodeKey(null);
    setError("");
    try {
      const res = await api<QrStartOut>("/bilibili/qr/start", { method: "POST" });
      const dataUrl = await QRCode.toDataURL(res.qr_url, { margin: 2, width: 220 });
      setQrDataUrl(dataUrl);
      setQrcodeKey(res.qrcode_key);
      setPhase("waiting");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "获取二维码失败，请重试");
      setPhase("failed");
    }
  }, []);

  // 打开时重新开始；关闭时复位状态。
  useEffect(() => {
    if (open) void start();
    else {
      setPhase("starting");
      setQrDataUrl(null);
      setQrcodeKey(null);
      setError("");
    }
  }, [open, start]);

  // 每 2 秒轮询扫码状态。
  useEffect(() => {
    if (!open || !qrcodeKey || phase === "confirmed" || phase === "expired" || phase === "failed") return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      try {
        const res = await api<QrPollOut>("/bilibili/qr/poll", { query: { qrcode_key: qrcodeKey } });
        if (stopped) return;
        if (res.status === "confirmed") {
          setPhase("confirmed");
          await queryClient.invalidateQueries();
          window.setTimeout(onClose, 800);
        } else if (res.status === "expired") {
          setPhase("expired");
        } else if (res.status === "scanned") {
          setPhase("scanned");
        }
      } catch {
        // 单次轮询失败继续重试
      }
    }, 2000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [open, qrcodeKey, phase, queryClient, onClose]);

  return (
    <Modal open={open} title="扫码登录哔哩哔哩" onClose={onClose}>
      <div className="flex flex-col items-center gap-3 py-2">
        {qrDataUrl ? (
          <img src={qrDataUrl} alt="登录二维码" width={220} height={220} className="rounded-lg bg-white p-2" />
        ) : phase === "starting" ? (
          <Spinner label="正在获取二维码…" />
        ) : (
          <div aria-hidden="true" className="w-[220px] h-[220px] rounded-lg bg-slate-900/70 flex items-center justify-center text-slate-500 text-sm">
            无二维码
          </div>
        )}
        <p
          className="text-sm"
          role="status"
          aria-live="polite"
        >
          {phase === "failed" ? (
            <span className="text-red-400">{error || PHASE_TEXT.failed}</span>
          ) : phase === "expired" || phase === "confirmed" ? (
            <span className={phase === "confirmed" ? "text-emerald-300" : "text-amber-300"}>{PHASE_TEXT[phase]}</span>
          ) : (
            <span className="text-slate-400">{PHASE_TEXT[phase]}</span>
          )}
        </p>
        {phase === "expired" && (
          <Button variant="primary" onClick={() => void start()} aria-label="重新获取二维码">
            重新获取
          </Button>
        )}
        <p className="text-xs text-slate-500 text-center">
          扫码确认后本站仅保存 Cookie 用于同步数据；请勿在公共设备上登录。
        </p>
      </div>
    </Modal>
  );
}

const LOGIN_STATUS: Record<string, { label: string; tone: "ok" | "warn" | "danger" }> = {
  active: { label: "已登录", tone: "ok" },
  none: { label: "未登录", tone: "danger" },
  expired: { label: "已过期", tone: "warn" },
  risk: { label: "风控受限", tone: "warn" },
};

export function BiliAccountCard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["bilibili-account"],
    queryFn: () => api<BilibiliAccount>("/bilibili/account"),
  });
  const [qrOpen, setQrOpen] = useState(false);
  const closeQr = useCallback(() => setQrOpen(false), []);
  const status = data ? (LOGIN_STATUS[data.login_status] ?? { label: data.login_status, tone: "warn" as const }) : null;
  const loggedIn = data?.login_status === "active";

  return (
    <Card className="flex items-center gap-4">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">B 站账号</h2>
          {status && <Badge tone={status.tone}>{status.label}</Badge>}
          {data?.risk_flag && <Badge tone="warn">风控风险</Badge>}
        </div>
        {isLoading && <Spinner label="正在获取账号信息…" />}
        {error && <ErrorState message={error instanceof Error ? error.message : String(error)} />}
        {data && (
          <div className="mt-2 flex items-center gap-3 min-w-0">
            {loggedIn && (
              <>
                <AccountAvatar avatar={data.avatar} uname={data.uname ?? ""} />
                <div className="min-w-0 text-sm">
                  <p className="font-medium truncate">{data.uname ?? "未知用户"}</p>
                  <p className="text-xs text-slate-500">
                    MID {data.mid ?? "—"} · Cookie 更新于 {formatDate(data.cookie_updated_at)}
                  </p>
                </div>
              </>
            )}
            {!loggedIn && (
              <p className="text-xs text-slate-400">
                尚未绑定 B 站账号，登录后才能同步关注与观看历史。
              </p>
            )}
          </div>
        )}
      </div>
      {!loggedIn && (
        <Button variant="primary" onClick={() => setQrOpen(true)} aria-label="扫码登录哔哩哔哩">
          扫码登录
        </Button>
      )}
      <QrLoginModal open={qrOpen} onClose={closeQr} />
    </Card>
  );
}

function AccountAvatar({ avatar, uname }: { avatar: string; uname: string }) {
  const [hidden, setHidden] = useState(false);
  if (hidden || !avatar) {
    return (
      <span
        aria-hidden="true"
        className="w-10 h-10 rounded-full bg-indigo-500/20 flex items-center justify-center text-indigo-300 shrink-0"
      >
        {uname.slice(0, 1) || "?"}
      </span>
    );
  }
  return (
    <img
      src={avatar}
      alt=""
      width={40}
      height={40}
      onError={() => setHidden(true)}
      className="w-10 h-10 rounded-full object-cover shrink-0"
    />
  );
}
