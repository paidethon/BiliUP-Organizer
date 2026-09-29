# LumiRSS 联动调研（RESEARCH_LUMIRSS）

> 调研日期：2026-09-29。本文为 `docs/ARCHITECTURE.md` 中 `feeds.py`（Atom 渲染）、
> `lumirss.py`（推送适配器）、`feed_tokens` / `lumirss_push_log` 表、
> `lumirss_push`（每 5 分钟）调度任务与 `lumirss_failure` 提醒类型的调研支撑文档。

---

## 1. LumiRSS 项目调研结论

LumiRSS 是公开仓库，资料充分，无需纯"盲适配"：

| 项 | 结论 | 来源 |
|---|---|---|
| 仓库地址 | https://github.com/paidethon/LumiRSS （`paidethon/LumiRSS`，TypeScript，2026-08 创建，main 分支活跃） | [GitHub](https://github.com/paidethon/LumiRSS) |
| License | **AGPL-3.0-only**（仓库根 `LICENSE`） | [README License 节](https://github.com/paidethon/LumiRSS#license) |
| 定位 | 邀请制多账户、自托管、source-first 信息阅读器；含 AI 摘要/翻译、Lumi library、Inbox 推送来源、API 来源、邮件桥 | [README](https://github.com/paidethon/LumiRSS#readme) |
| 架构 | **FreshRSS 作为 RSS 域引擎与真源** + RSSHub 生成非 RSS 源 + 项目自有 **FastAPI BFF** + React Web/PWA | [README Architecture 节](https://github.com/paidethon/LumiRSS#architecture)、[ADR 0001](https://github.com/paidethon/LumiRSS/blob/main/docs/decisions/0001-freshrss-owns-rss-state.md) |
| 数据所有权 | Inbox 推送连接器与其条目为 Lumi 自有（`inbox_sources` + `library_inbox`，条目 kind 为 `api_item`）；RSS 域条目归 FreshRSS | [ADR 0004](https://github.com/paidethon/LumiRSS/blob/main/docs/decisions/0004-phase2-data-ownership.md) |

### 1.1 API 面（对 BiliUP Organizer 直接相关）

代码均位于 `services/bff/src/lumirss/routers/`（下述事实来自源码阅读，路径已标注）。

#### A. 收件箱推送（Inbox push）—— 模式 2 的目标 API

机器对机器端点，**Bearer 鉴权**，路由源码：
[routers/inbox.py](https://github.com/paidethon/LumiRSS/blob/main/services/bff/src/lumirss/routers/inbox.py)、
契约模型：[models.py（`InboxIngestItem`）](https://github.com/paidethon/LumiRSS/blob/main/services/bff/src/lumirss/models.py)。

- **推送**：`POST /api/v1/inbox/ingest/{connector_uuid}`
  - Header：`Authorization: Bearer <connector_secret>`（常数时间比较，secret 落库为哈希，绝不回显、绝不入日志）；
  - Body（JSON，未知字段一律拒绝，`extra: forbid`）：
    | 字段 | 类型 | 必填 | 约束 |
    |---|---|---|---|
    | `guid` | string | 是 | 1–512 字符（幂等键） |
    | `title` | string? | 否 | 1–512 |
    | `url` | string? | 否 | ≤2048，仅 http(s) 绝对 URL |
    | `author` | string? | 否 | 1–256 |
    | `content` | string? | 否 | ≤200,000，纯文本 |
    | `contentHtml` | string? | 否 | ≤500,000，**不受信**，服务端白名单净化 |
    | `publishedAt` | string? | 否 | ≤64，ISO-8601 |
    | `categories` | string[] | 否 | ≤24 项，每项 ≤64 |
  - 幂等：按 `(source, guid)` 去重，重放同 guid 返回 200 `{"status": "exists", "ref": ...}`；首次为 `{"status": "created", ...}`；
  - 错误：secret 错误与来源不存在**同返回 404**（不泄漏存在性）；
  - 限流：`inbox_ingest` 120 次/60 秒（[middleware.py](https://github.com/paidethon/LumiRSS/blob/main/services/bff/src/lumirss/middleware.py)）。
- **连接器管理**（用户 session 鉴权，非 bearer）：
  - `POST /api/v1/inbox/sources`（body `{"name": "..."}`，1–120 字符）→ 返回 `{uuid, name, secret, ingestPath, createdAt}`，**secret 仅此一次展示**；
  - `GET /api/v1/inbox/sources`；`POST /api/v1/inbox/sources/{uuid}/rotate`（轮换，旧 secret 立即失效）；
  - `POST /api/v1/inbox/sources/{uuid}/ingest/dry-run`（零写入契约试跑）；`GET /api/v1/inbox/sources/{uuid}/events`（delivered/duplicate/failed 事件）；`POST /api/v1/inbox/events/{event_id}/replay`（失败重放）；`GET/DELETE /api/v1/inbox/items...`。
  - 另有 N130 凭据轮换端点：`credentials/rotate` 轮换后旧 bearer 保留 **10 分钟宽限**（`fallback_used` 标记），推送脚本滞后不至于丢条目。
- **部署注意**：宿主层 Caddy 若开 basic auth 会先拦截 `/api/v1/inbox/ingest/*`（及 `/api/mail/ingest/*`），需在宿主反代豁免该路径（BFF 侧 bearer 仍生效）。来源：[troubleshoot.md](https://github.com/paidethon/LumiRSS/blob/main/docs/how-to/troubleshoot.md)、[phase2-recovery.md](https://github.com/paidethon/LumiRSS/blob/main/docs/audits/phase2-recovery.md)。

#### B. 订阅注册（API 来源 / 订阅管理）—— 模式 3 的候选 API

- `POST /api/v1/api-sources`：创建"API 来源"（JSON 端点 + 字段映射），Lumi 自行生成 Atom（`GET /feeds/{uuid}.{secret}.atom`，常数时间 secret 校验 + ETag/304）并**自动订阅进 FreshRSS**；删除前强制先向 FreshRSS 退订。源码：[routers/api_sources.py](https://github.com/paidethon/LumiRSS/blob/main/services/bff/src/lumirss/routers/api_sources.py)。
- `POST /api/v1/subscriptions`：**直接按 feed URL 订阅**（"Subscribe to a feed URL; returns the server-confirmed subscription"），另有 GET/PATCH/批量迁移等。源码：[routers/subscriptions.py](https://github.com/paidethon/LumiRSS/blob/main/services/bff/src/lumirss/routers/subscriptions.py)。
- **鉴权限制**：以上管理端点走**用户 session**（`LUMIRSS_AUTH_MODE=session`，`POST /api/v1/auth/login` 铸发 `__Host-` 前缀 Secure Cookie；basic 模式为 Caddy 边缘 basic auth）。机器客户端没有官方 token 化的管理 API——只有 inbox/mail ingest 是 bearer 通道。来源：[configuration.md](https://github.com/paidethon/LumiRSS/blob/main/docs/reference/configuration.md)、[routers/auth.py](https://github.com/paidethon/LumiRSS/blob/main/services/bff/src/lumirss/routers/auth.py)。
- 结论：**模式 3 可行但依赖 session 模拟（用户名/密码 + Cookie 维护），列为可选；主推模式 1/2。**

#### C. 配置键命名惯例（供本项目的适配器配置对齐）

LumiRSS 侧环境变量统一 `LUMIRSS_*` 前缀，全部"留空 = 诚实降级"（如 `LUMIRSS_ATOM_BASE_URL`、`LUMIRSS_INTERNAL_TOKEN`（`X-Lumi-Token` 头）、`FRESHRSS_BASE_URL/FRESHRSS_USERNAME/FRESHRSS_API_PASSWORD`）。来源：[configuration.md](https://github.com/paidethon/LumiRSS/blob/main/docs/reference/configuration.md)、[services/bff/.env.example](https://github.com/paidethon/LumiRSS/blob/main/services/bff/.env.example)。

---

## 2. 通用参考（兼容方案）

### 2.1 FreshRSS Google Reader 兼容 API

LumiRSS 的 RSS 引擎就是 FreshRSS；若用户的 LumiRSS 未启用 inbox 或直连其 FreshRSS 更方便，可走 FreshRSS 标准 API。来源：
[FreshRSS 开发者文档：Google Reader API](https://freshrss.github.io/FreshRSS/en/developers/06_GoogleReader_API.html)、
[移动端接入文档](https://freshrss.github.io/FreshRSS/en/users/06_Mobile_access.html)、
源码 [`p/api/greader.php`](https://github.com/FreshRSS/FreshRSS/blob/edge/p/api/greader.php)。

- 基址：`{FreshRSS}/api/greader.php`；需管理员启用"Allow API access"，且用户在 Profile 中设置**独立 API Password**。
- 登录：`POST /accounts/ClientLogin`，参数 `Email` + `Passwd`（API Password）→ 响应含 `SID`/`LSID`/`Auth`（形如 `user/hash`）。
- 后续请求头：`Authorization: GoogleLogin auth=<Auth>`。
- 添加订阅：`GET/POST /reader/api/0/subscription/quickadd?quickadd=<feed-url>`（`quickadd` 处理器在 greader.php 源码中确认存在）；通用编辑为 `/reader/api/0/subscription/edit`（`ac=subscribe`/`ac=unsubscribe`、`s=feed/<id>`）。
- 只读端点（`output=json`）：`/reader/api/0/subscription/list`、`/reader/api/0/tag/list`、`/reader/api/0/unread-count`、`/reader/api/0/token`、`/reader/api/0/stream/contents/reading-list`。

### 2.2 Webhook push 常见形态

- FreshRSS 本体是**纯拉取**爬虫，无原生 webhook 接收端（其文档仅提供 API 与移动端接入，见上）。
- 生态中"推送进阅读器/收件箱"的通行形态即 LumiRSS inbox ingest 所体现的：**POST JSON + Bearer token 到可配置端点，GUID 幂等去重，事件日志 + 失败重放**。LumiRSS 自身的邮件桥 `POST /api/mail/ingest/{...}` 采用同一 bearer 形态（[troubleshoot.md](https://github.com/paidethon/LumiRSS/blob/main/docs/how-to/troubleshoot.md)）。
- 因此本项目适配器按"通用 webhook：POST JSON + Bearer + 幂等 guid"设计即可同时覆盖 LumiRSS inbox 与其他同形态接收端。

---

## 3. 推荐集成设计

三条模式并存，全部通过 `lumirss.py` 单一模块与 `settings` 中的 LumiRSS 区（`/settings` 页）配置。

### 模式 1（保底，必做）：BiliUP Organizer 输出 Atom 源

- 提供 `GET /feed/{token}.xml`（token 即 `feed_tokens` 表中的随机令牌，支持吊销），渲染为 **Atom**（B 站 UP 主新视频条目：`id`=BV 号 guid、`title`、`link`、`published`、`summary`/`content` 含封面与简介、`category`=UP 主名）。
- 用户在 LumiRSS（或任何阅读器）里手动粘贴 URL 订阅；LumiRSS 的 FreshRSS 引擎原生拉取 Atom。**零 API 依赖，永远可用**，也是模式 2 故障时的兜底。
- 对齐 LumiRSS 生态惯例可提供 `ETag/Last-Modified` + 304（LumiRSS 自己的生成 Atom 即如此，见 §1.1B）。

### 模式 2（主推）：LumiRSS Inbox 推送适配器

- 配置（设置页 + 环境变量，均可；环境变量优先）：
  ```text
  LUMIRSS_BASE_URL=https://rss.example.com        # LumiRSS 站点根（不含 /api）
  LUMIRSS_INBOX_INGEST_URL=                        # 可选：完整 ingest URL，留空则由 BASE_URL + ingest_path 拼接
  LUMIRSS_INBOX_INGEST_PATH=/api/v1/inbox/ingest/<uuid>
  LUMIRSS_INBOX_SECRET=<connector bearer secret>   # 创建连接器时仅展示一次
  LUMIRSS_PUSH_ENABLED=false                       # 总开关，默认关
  ```
- 抽象接口（`app/services/lumirss.py`，与 ARCHITECTURE 冻结契约一致）：
  ```python
  class LumiRSSClient(Protocol):
      def push_items(self, items: list[PushItem]) -> PushReport:
          """POST {base}{ingest_path}，Authorization: Bearer <secret>。
          PushItem: guid=BV号, title, url, content(纯文本简介), contentHtml(可选),
                    publishedAt=ISO8601, categories=[UP主名, 分区]。"""
  ```
- 行为规范：
  - 每 5 分钟的 `lumirss_push` 调度任务增量推送新视频；**天然幂等**：LumiRSS 按 `(source, guid)` 去重，重放返回 `exists`，本地方向以 `lumirss_push_log` 记录 `created/exists` 即可，不需本地去重锁。
  - 失败（网络错误、非 2xx、404/401、429）→ 写 `lumirss_push_log` 并入**重试队列**（指数退避，如 5m→15m→1h→6h，上限 24h 后暂停并保持 failed 状态可手动重推）。
  - 重试连续失败达到阈值（如 3 次）→ 触发 `lumirss_failure` 提醒（走既有 reminders/通知渠道），提醒文案带 base URL 与失败分类。
  - 401/404 时提示"检查连接器 secret / ingest 路径 / 宿主反代豁免"（对应 §1.1A 的部署注意）。
  - 轮换 secret 后：更新设置页配置即可，无需其他操作（LumiRSS 有 10 分钟旧值宽限）。

### 模式 3（可选）：一键把 Atom 源注册进 LumiRSS

- 首选：`POST /api/v1/subscriptions`（body 含 feedUrl；session 鉴权）。实现为设置页"接入 LumiRSS"向导的一步：用户填 LumiRSS 用户名/密码 → BiliUP 调 `POST /api/v1/auth/login` 拿 session Cookie → 调订阅端点把 `GET /feed/{token}.xml` 的绝对 URL 注册进去。**凭据仅在本地设置中保存，明确标注为可选**。
- 备选（用户的 FreshRSS 直接可达且开了 API）：FreshRSS GReader `subscription/quickadd`（§2.1），`FRESHRSS_BASE_URL + Email + API Password` 可配置。
- 该模式涉及密码/Cookie 生命周期管理，收益低（模式 1 手动粘贴一次即可），故列为可选、最后实现。

### 降级原则（硬性）

- `LUMIRSS_PUSH_ENABLED=false` 或 base URL/secret 任一未配置：调度任务直接跳过，**不报错、不产生提醒**，`/settings` 显示"未配置（降级为仅 Atom 源）"。
- 模式 3 未配置登录凭据：仅隐藏向导入口，不影响其他功能（对齐 LumiRSS 自身 `FRESHRSS_PUBLIC_URL` 留空即隐藏链接的"诚实降级"惯例，见 §1.1C）。
- 所有外部调用（推送、登录、quickadd）都经统一 HTTP 客户端：超时（如 10s）、重试入队、失败只落库 + 提醒，绝不让同步主流程因 LumiRSS 失败而中断。

---

## 4. 来源清单

1. LumiRSS 仓库与 README（架构、License、功能清单）：https://github.com/paidethon/LumiRSS
2. ADR 0004（数据所有权、`api_item` 与 inbox ingest 归属）：https://github.com/paidethon/LumiRSS/blob/main/docs/decisions/0004-phase2-data-ownership.md
3. Inbox 路由源码（端点、幂等、事件、重放、轮换）：https://github.com/paidethon/LumiRSS/blob/main/services/bff/src/lumirss/routers/inbox.py
4. 契约模型源码（`InboxIngestItem` 字段与约束）：https://github.com/paidethon/LumiRSS/blob/main/services/bff/src/lumirss/models.py
5. api_sources 路由源码（生成 Atom + 自动订阅 FreshRSS）：https://github.com/paidethon/LumiRSS/blob/main/services/bff/src/lumirss/routers/api_sources.py
6. subscriptions 路由源码（按 feedUrl 订阅）：https://github.com/paidethon/LumiRSS/blob/main/services/bff/src/lumirss/routers/subscriptions.py
7. auth 路由源码（session 登录/登出）：https://github.com/paidethon/LumiRSS/blob/main/services/bff/src/lumirss/routers/auth.py
8. 配置键参考（`LUMIRSS_*` 命名、诚实降级惯例）：https://github.com/paidethon/LumiRSS/blob/main/docs/reference/configuration.md 与 https://github.com/paidethon/LumiRSS/blob/main/services/bff/.env.example
9. 故障排查（机器端点 bearer 鉴权、宿主 Caddy 豁免）：https://github.com/paidethon/LumiRSS/blob/main/docs/how-to/troubleshoot.md
10. FreshRSS Google Reader API 文档：https://freshrss.github.io/FreshRSS/en/developers/06_GoogleReader_API.html 与 https://freshrss.github.io/FreshRSS/en/users/06_Mobile_access.html
11. FreshRSS greader.php 源码（quickadd 确认）：https://github.com/FreshRSS/FreshRSS/blob/edge/p/api/greader.php
