# 验收记录：图表与统计准确性升级（2026-10）

版本 0.5.0（tag `v0.5.0`，镜像 `ghcr.io/paidethon/biliup-organizer@sha256:227c62348c4f…`，
CI Release workflow 从合并后的 main 构建）。所有统计统一 Asia/Shanghai、周一起始
自然周、半开区间；观看时长为按记录进度估算（口径版本 `2026-10-shanghai-v1`），
有效/下界/未知样本分开计数，均值只用有效样本。

## 部署与回滚

- 生产：47.100.64.202，Compose 项目 `biliup-organizer`（/opt/biliup-organizer），
  Caddy 反代 up.oouo.top → 127.0.0.1:8066（配置未改动）。
- 部署前备份：`data/backups/pre-v0.5.0-deploy.db`（SQLite 在线 backup API，
  integrity_check ok，schema v5 快照）；旧镜像 `sha256:5bdcda0a866d…`（0.4.2）保留可回退。
- 迁移：v6 幂等执行——weekly_reports/up_profiles/watch_authors 建表、
  watch_history (bvid,view_at) 去重（0 重复残留）+ 统计索引（EXPLAIN 命中
  覆盖索引）。回滚说明：v6 只新增表/索引/列，旧镜像可直接运行于 v6 库；
  唯一不可逆点是历史重复行被清除（备份中保留）。
- 部署后 /healthz /readyz ok；调度器实测：weekly_report → 周一 08:00+08:00、
  scheduled_backup 保持 03:00 UTC、followings_sync 03:00+08:00。
- 上线后 30 分钟容器日志 0 error/traceback；邻居站点（rss/tab/sc.oouo.top）200。

## 线上验收（真实数据，2026-10-04）

- 观看历史：TOP UP 排行显示真实昵称（此前一半记录只显示 `mid:xxx`——生产库 269 条
  历史 136 条 mid 不在 up_users）；未解析项按设计显示 UID 且注明「不可解析的将显示
  UID」；观看时间列为上海时间（+08:00），50/页全部格式正确；估算时长/样本构成/覆盖
  说明齐备；数据表/CSV/放大可用。
- 周报：日期选择定位自然周（任意日归一同一周）；上一周/下一周导航写 URL 可恢复；
  生成并保存成功（r1），存档横幅 + 数据截至说明出现；HTML/MD/JSON 导出链接可用；
  放大弹窗开/关正常；概览/习惯/UP 与分组/进阶四个标签页全部渲染（C1 热力图、
  C2 对比、C3 覆盖率、C4 变化榜、C5 投稿覆盖、C6 探索回访均在线出图）。
- 移动端 390×844：零横向溢出，移动导航/退出登录入口可用，放大近全屏，零 JS 错误。
- 桌面 1440×900 全程零 pageerror/console error。

## 受控 B 站同步验收（生产真实账号）

- `POST /native-groups/push-plan`（只读）200：修复前同路径 500（上游
  `/x/relation/tag/users` 404）；现在读回 complete=true。
- 远端实况：仅 特别关注(-10, 0 人) + 默认分组(0, 355 人)，无自建组——多分组读回
  无生产实例，由 41 个接口级回归（append R∪D / replace (R−M)∪D / 未托管保留 /
  批次共享 / 校验失败上报）覆盖。
- 受控写入/恢复闭环：create 临时组(389792464) → addUsers 写入 1 个 UP（大 mid
  3706944625838524）→ 读回={389792464} ✓ → delete 临时组 → 读回=原始状态 ✓ →
  标签清单复原 ✓，远端无额外分组丢失。
- 结构化错误实弹验证：组名超长触发上游 22103，返回结构化 `bili_param` 错误（非 500）。

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
