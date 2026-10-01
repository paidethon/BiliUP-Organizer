import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { FlagValue, SortValue } from "./Toolbar";

/** 展示模式：分页 / 全部（虚拟滚动，一次拉全量筛选结果）。 */
export type DisplayMode = "paged" | "all";
export type PageSizeValue = 50 | 100 | 200;
export type OrderValue = "asc" | "desc";

/** 展示偏好持久化键；URL 缺省时回退到这里，刷新后仍生效。 */
const MODE_KEY = "biliup.followings.displayMode";
const SIZE_KEY = "biliup.followings.pageSize";

const FLAGS: readonly string[] = ["", "stale", "unwatched", "never", "missing", "important"];
const SORTS: readonly string[] = ["followed", "name", "last_video", "last_watched"];
const SIZES: readonly string[] = ["50", "100", "200"];

/** 列表视图完整状态；q 为防抖后的提交值。 */
export interface FollowingsView {
  q: string;
  groupId: string;
  flag: FlagValue;
  status: string;
  sort: SortValue;
  order: OrderValue;
  mode: DisplayMode;
  pageSize: PageSizeValue;
  page: number;
}

const DEFAULT_VIEW: FollowingsView = {
  q: "",
  groupId: "",
  flag: "",
  status: "",
  sort: "last_video",
  order: "desc",
  mode: "paged",
  pageSize: 50,
  page: 1,
};

function readStored(key: string, allowed: readonly string[], fallback: string): string {
  try {
    const value = window.localStorage.getItem(key);
    return value != null && allowed.includes(value) ? value : fallback;
  } catch {
    return fallback;
  }
}

/** URL → 视图状态；非法值忽略，缺省项依次回退 localStorage、默认值。 */
function fromSearchParams(params: URLSearchParams): FollowingsView {
  const urlMode = params.get("mode");
  const urlSize = params.get("size");
  const flag = params.get("flag") ?? "";
  const sort = params.get("sort") ?? "";
  const order = params.get("order") ?? "";
  const page = Number(params.get("page"));
  return {
    q: (params.get("q") ?? "").trim(),
    groupId: params.get("group") ?? "",
    flag: FLAGS.includes(flag) ? (flag as FlagValue) : "",
    status: params.get("status") ?? "",
    sort: SORTS.includes(sort) ? (sort as SortValue) : DEFAULT_VIEW.sort,
    order: order === "asc" ? "asc" : order === "desc" ? "desc" : DEFAULT_VIEW.order,
    mode: urlMode === "all" || urlMode === "paged" ? urlMode : (readStored(MODE_KEY, ["paged", "all"], DEFAULT_VIEW.mode) as DisplayMode),
    pageSize: urlSize != null && SIZES.includes(urlSize) ? (Number(urlSize) as PageSizeValue) : (Number(readStored(SIZE_KEY, SIZES, String(DEFAULT_VIEW.pageSize))) as PageSizeValue),
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  };
}

/** 视图状态 → URL（只写非默认项）；同时把展示偏好写入 localStorage。 */
function toSearchParams(view: FollowingsView): URLSearchParams {
  const next = new URLSearchParams();
  if (view.q) next.set("q", view.q);
  if (view.groupId) next.set("group", view.groupId);
  if (view.flag) next.set("flag", view.flag);
  if (view.status) next.set("status", view.status);
  if (view.sort !== DEFAULT_VIEW.sort) next.set("sort", view.sort);
  if (view.order !== DEFAULT_VIEW.order) next.set("order", view.order);
  if (view.mode !== DEFAULT_VIEW.mode) next.set("mode", view.mode);
  if (view.pageSize !== DEFAULT_VIEW.pageSize) next.set("size", String(view.pageSize));
  if (view.page !== 1) next.set("page", String(view.page));
  return next;
}

/**
 * 关注列表的 URL 同步 + 偏好持久化 + q 防抖。
 * 挂载时从 URL（其次 localStorage）一次性恢复；此后状态是唯一事实来源，
 * 变更经 replace 写回 URL，避免历史记录膨胀。筛选/模式变化自动回到第 1 页。
 */
export function useFollowingsUrl() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [qInput, setQInput] = useState(() => searchParams.get("q") ?? "");
  const [view, setView] = useState<FollowingsView>(() => fromSearchParams(searchParams));

  // q 防抖 400ms 提交；q 变化属筛选变化，重置回第 1 页
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const nextQ = qInput.trim();
      setView((prev) => (prev.q === nextQ ? prev : { ...prev, q: nextQ, page: 1 }));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [qInput]);

  // 状态 → URL + 偏好持久化（replace，防历史爆炸）
  useEffect(() => {
    setSearchParams(toSearchParams(view), { replace: true });
    try {
      window.localStorage.setItem(MODE_KEY, view.mode);
      window.localStorage.setItem(SIZE_KEY, String(view.pageSize));
    } catch {
      // localStorage 不可用时静默降级，仅会话内生效
    }
  }, [view, setSearchParams]);

  const update = useCallback((partial: Partial<FollowingsView>) => {
    setView((prev) => {
      const next = { ...prev, ...partial };
      const filterChanged =
        next.q !== prev.q ||
        next.groupId !== prev.groupId ||
        next.flag !== prev.flag ||
        next.status !== prev.status ||
        next.sort !== prev.sort ||
        next.order !== prev.order ||
        next.mode !== prev.mode;
      if (filterChanged) next.page = 1;
      return next;
    });
  }, []);

  return {
    qInput,
    setQInput,
    view,
    setGroupId: useCallback((groupId: string) => update({ groupId }), [update]),
    setFlag: useCallback((flag: FlagValue) => update({ flag }), [update]),
    setStatus: useCallback((status: string) => update({ status }), [update]),
    setSort: useCallback((sort: SortValue) => update({ sort }), [update]),
    setOrder: useCallback((order: OrderValue) => update({ order }), [update]),
    setMode: useCallback((mode: DisplayMode) => update({ mode }), [update]),
    setPageSize: useCallback((pageSize: PageSizeValue) => update({ pageSize }), [update]),
    setPage: useCallback((page: number) => setView((prev) => ({ ...prev, page })), []),
  };
}
