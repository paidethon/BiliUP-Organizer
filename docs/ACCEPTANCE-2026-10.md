# 验收记录：图表与统计准确性升级（2026-10）

版本 0.5.0。所有统计统一 Asia/Shanghai、周一起始自然周、半开区间；观看时长为
按记录进度估算（口径版本 `2026-10-shanghai-v1`），有效/下界/未知样本分开计数，
均值只用有效样本。

## 原问题与根因

| 原问题 | 真实根因（生产日志/数据实证） | 修复入口 |
| --- | --- | --- |
| 「同步分组」500 | 生产堆栈：`push_overwrite → backup_native_groups → list_tag_users` 调 `GET /x/relation/tag/users`，上游返回 HTTP 404 → `BiliError` 未捕获 → 通用 500 | `native_groups.py` 改用文档核实的 `GET /x/relation/tag`（纯数组响应防御解析）；`moveUsers` 路径修正为 `/x/relation/tags/moveUsers`（beforeTagids/afterTagids）；全局 `BiliError` 处理器映射结构化 502 |
| 排行榜显示 `mid:xxx` | 生产库 269 条观看历史中 136 条的 up_mid 不在 up_users；同步丢弃上游 author_name/author_face | 同步保留作者快照（watch_authors）+ up_profiles 缓存（含未关注 UP）；排行榜三级解析 profile→followed→snapshot；不可解析显示「昵称暂不可用（UID）」 |
| 时区漂移 | 前端 `new Date("naive")` 按浏览器时区解析 UTC 串；周报小时/星期列与历史页日界不一致 | `app/timeutil.py` 统一上海墙钟；API 输出带 +08:00 的 ISO；前端 `lib/time.ts` 固定 Asia/Shanghai 展示 |
| 周报只有滚动 7 天、依赖发邮件才保存 | 旧实现仅 `weekly_report:latest` 且 `_weekly` 绑定发送 | `weekly_reports` 表（schema v6）：任意周、修订制、快照冻结、导出、发送选定修订；旧 `weekly_report:latest` 迁移为 legacy 行保留原文 |
| 分组覆盖风险 | overwrite 删除全部远端标签；增量 diff>30% 静默全量重建；重建只用 group_id 单分组 | 托管范围限定（native_group_map 本地映射）、追加 R∪D 语义、删除 diff 阈值兜底、写前备份完整性校验、写后读回 |

## 图表审查结论（改造前 12 张）

- 保留并升级：每日观看（统一时间趋势组件，可切累计）、观看时段、星期分布、视频时长、
  完成率分布、内容分区 TOP（附覆盖提示）、本地分组偏好（标注非互斥）。
- 合并/降级：近 30 天累计 → 每日图的「累计」模式；TOP5 集中度 → TOP UP 排行的附属指标；
  分组平均完成率 → 并入完成率口径说明（样本量提示）。
- 重新表述：「未观看占比」→「已同步范围内未发现观看记录」（明确非终身判断）；
  「关注增长趋势」→ 移除（无历史快照，无法还原净增长，避免伪造）。
- TOP UP 排行改紧凑横向条形（ECharts），支持 Top10/20/全部与点击钻取。

## 新增六张图（周报页「概览 / 习惯 / UP 与分组 / 进阶」）

C1 星期×小时热力图（习惯）、C2 本周vs上周对比（概览）、C3 分组观看覆盖率（UP 与分组）、
C4 UP 观看变化榜（UP 与分组）、C5 已同步投稿观看覆盖（进阶）、C6 新探索与回访趋势（进阶）。
全部接入真实聚合接口、可放大、有数据表/CSV 导出、空态与覆盖提示；C3/C5 归档时冻结
成员集合与观测截止。

## 测试

- 后端：`uv run pytest -q` 218 passed（含新增 时区口径/多分组/昵称缓存 三份定向回归）。
- 前端：`npm run build` 通过；`npm run test`（vitest）13 passed（时区显示、周起点、CSV 注入防护）。
- E2E：`npm run e2e` 72 passed（Chromium 桌面 1440×900、WebKit 桌面、Chromium 移动 390×844）。
- 性能：合成 10 万行历史 + 800 UP + 多分组（固定种子），`scripts/perf_stats.py`：
  完整周统计 329ms、30 天核心统计 247ms、周报生成 301ms；EXPLAIN 确认范围扫描命中
  覆盖索引 `ix_watch_history_view_at`，TOP UP 查询 9.2ms。

## 边界与已知限制

- 观看时长是「按记录进度估算」，不代表精确播放秒数（拖动/倍速/重复观看不可还原）。
- 排行榜昵称依赖同步覆盖；未同步期间的记录无法回溯作者名，仅能显示 UID。
- C6「新探索」以本地已保存历史为基线，不是用户终身首次观看。
- 原生分组写入的恢复依赖推送前自动备份 JSON（SQLite 回滚不能撤销远端变更）。
- 邮件/导出 HTML 为静态图表 + 数据表；交互放大与钻取仅在网页版提供。
