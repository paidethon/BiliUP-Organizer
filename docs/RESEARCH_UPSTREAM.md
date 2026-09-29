# 上游调研与 License 审计报告（RESEARCH_UPSTREAM）

- 项目：BiliUP Organizer（自托管 B 站关注列表整理工具：智能分类、提醒、周报、LumiRSS 集成）
- 调研日期：2026-09-29
- 调研方式：GitHub / PyPI / npm 公开元数据核验（WebSearch + WebFetch + registry API）
- 本仓库计划主 License：**MIT**

> **2026 年合规环境重要警示**：2026 年 1 月至 7 月间，B 站（哔哩哔哩）委托律所对多个逆向其非公开 API 的开源项目发出律师函，导致 bilibili-API-collect（2026-01-30）与 Nemo2011/bilibili-api（2026-07-06）先后归档并永久关停。本项目的所有上游参考策略都必须在这一背景下制定：**最小化接口面、仅处理用户本人账号数据、不复刻任何被维权项目的文档文本或代码。**

---

## 1. biliup/biliup（录播上传工具）

- 仓库：https://github.com/biliup/biliup
- License：**MIT**（仓库页面与 LICENSE 徽章确认）
- 维护状态：**活跃**（约 1.1k commits，近期仍有功能合并），未被律师函波及
- 定位：自动直播录制、B 站投稿上传、Twitch/YouTube 频道搬运工具

### 架构要点

混合架构：**Rust 后端 + 精简 Python 包 + Next.js 前端**。

| 组件 | 说明 |
|---|---|
| `crates/biliup` | 核心库：直播流解析（内置 19 个平台）、下载器（默认 Rust 实现 mesio，可选 ffmpeg）、B 站投稿与**凭据管理** |
| `crates/biliup-cli` | 命令行 + Web 服务：REST API、WebUI、录制调度（子模块 `api`、`fleet` 多机调度、`auto_clip` 自动切片） |
| `crates/danmaku` | 弹幕客户端（多平台协议解析、XML 输出） |
| `crates/stream-gears` | PyO3 绑定，向 Python 暴露 `python -m biliup` |
| `app` / `public` | Next.js + React + TypeScript + Semi UI 的 WebUI 源码（构建产物内嵌进后端二进制） |
| `tauri-app` | Windows 桌面端 |
| 数据存储 | SQLite（`data.sqlite3` / `fleet.sqlite3`） |

登录与凭据：支持扫码 / 密码 / 短信 / 网页 Cookie 多种方式；凭据落盘为 `cookies.json` 或 `data/<mid>.json`，由核心库统一做生命周期管理（存储、刷新、失效检测）。

### 与本项目的场景差异

biliup 解决的是**"录制 → 上传投稿"**的内容生产链路；本项目解决的是**"关注列表的读取、分析、分组、AI 分类、提醒与周报"**的账号数据管理链路。两者共享的只有"B 站账号凭据管理 + 对 B 站 HTTP 接口的薄封装 + 本地 Web 服务"这三层基础设施，业务域几乎不重叠。

### 可借鉴的思想（MIT 允许代码级借鉴，但本项目预计无需搬运其录制/上传代码）

1. **凭据生命周期管理**：凭据独立落盘、按 mid 归档、失效检测与刷新——直接适用于本项目的登录态管理。
2. **服务分层**：REST API + 内嵌 WebUI + SQLite 的自托管单机部署形态，与本项目 FastAPI + SQLAlchemy + Jinja2 的规划一致，可参考其部署与配置组织。
3. **调度思想**：以调度器统一编排周期任务（其录制调度 ↔ 本项目的提醒/周报任务）。

**引用方式：思想借鉴（License 兼容，无 NC/GPL 风险；不做代码搬运，因业务域不同）。**

---

## 2. Nemo2011/bilibili-api（Python 库）

- 仓库：https://github.com/Nemo2011/bilibili-api —— **已于 2026-07-06 归档并永久关停**（README 仅剩上海市弘安律师事务所代表哔哩哔哩发出的侵权告知函；函件指控范围包括逆向非公开接口、绕过反爬与签名鉴权等）。仅存 1 个 commit，代码不可见。
- PyPI 包名：`bilibili-api-python`，最后版本 17.4.2
- **License：GPL-3.0-or-later**（PyPI 分类器 `License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)` 确认）——**不是 MIT**
- 历史核心模块（基于最后公开版本的记忆性归纳，仓库已不可访问）：
  - `login`：扫码登录（`login_v2`）、密码登录、Cookie 导入，凭据类 `Credential`
  - `user`：用户信息、关系数据（粉丝/关注列表、分组标签操作）
  - 其他：`video`、`rank`、`live`、`search`、`article` 等，底层为 httpx 异步客户端

### 直接引入 vs 自研轻量 httpx 客户端

| 维度 | 直接引入 bilibili-api | 自研轻量 httpx 客户端 |
|---|---|---|
| License | **GPL-3.0-or-later，与本仓库 MIT 计划直接冲突**（引入即整体 GPL 化） | 无冲突，MIT 可控 |
| 上游健康度 | **已归档永久关停**，无修复、无跟进 B 站接口变动 | 自主演进，接口面最小化 |
| 法律风险 | 高（正是被律师函打击的项目之一，且函件点名"逆向非公开接口"行为） | 中（仍需自行谨慎，但接口面与依赖面都最小） |
| 依赖面 | 库体量大，覆盖视频/直播/专栏/排行等大量本项目用不到的模块 | 仅关注关系相关少量端点，依赖面极小 |
| 开发成本 | 低（但接口变动无人维护） | 中（仅需实现登录凭据 + 关注列表/分组 CRUD 几个端点） |

### 推荐：自研轻量 httpx 客户端

理由（按权重排序）：

1. **License 硬冲突**：上游为 GPL-3.0-or-later，直接引入或 vendor 任何代码都会迫使 MIT 仓库整体转为 GPL，与项目计划矛盾；该库**必须无接触**。
2. **上游已死亡**：仓库被归档、代码删除，引入一个无人维护且正被法律打击的库等于埋雷。
3. **法律环境**：2026 年 B 站已实际启动维权，依赖面越小、行为越克制（仅用户本人数据、限速），风险越可控。
4. **需求面窄**：本项目只需要登录凭据 + 关注列表读取 + 分组（标签）增删改 + 提醒所需的少量信息接口，自研成本可控（httpx 已是既定依赖）。

**引用方式：无接触（不得 vendor 代码、不得依赖其包）；其历史模块划分仅作为"哪些端点存在"的间接事实线索。**

---

## 3. SocialSisterYi/bilibili-API-collect（API 文档整理）

- 仓库：https://github.com/SocialSisterYi/bilibili-API-collect —— **已于 2026-01-30 存档并永久关停**，20.2k stars / 2.9k forks
- 时间线：2026-01-28 维护者收到 B 站委托律所律师函（指控系统性收集传播 B 站非公开 API 构成侵权）→ 即日起停止维护、删除 `deprecated` 分支下全部文档与源码，仓库仅剩 README 说明与告知函图片
- **License（历史）：CC BY-NC 4.0**（非商业署名许可）——任务假设正确，且该状态随仓库关停已进一步恶化

### NC 许可对我们意味着什么

- **只能做"事实引用"**：接口端点、参数名、返回字段这类事实性信息本身不是版权保护的对象，我们可以据此自行实现客户端；这属于对事实的利用，不触发 CC 许可的复制权。
- **禁止复制表达**：其文档的文字描述、表格组织、示例代码属于受版权保护的表达，**任何片段都不得复制进本 MIT 仓库**（CC BY-NC 与 MIT 也不兼容，且 NC 禁止商用场景，与本项目潜在的 Docker 镜像分发存在解释空间）。
- **额外警示**：该项目被律师函关停说明"搬运/传播 B 站 API 文档"本身已被权利方明确反对。本项目**不应在仓库内沉淀任何系统性的 B 站 API 文档**，接口知识只保留在最小必要代码与少量行内注释中，且以"对官方网页行为的观察"为依据。

**引用方式：事实引用（不复制任何文本进仓库；不在本仓库建立 API 文档副本；接口知识仅存在于实现代码层面）。**

---

## 4. 同类开源项目对比（关注列表管理 / 分组 / AI 分类）

经 GitHub 检索，该领域**没有大型成熟项目**，现存项目均为小型脚本或工具，且多数未声明 License。选取代表性项目：

| 仓库 | License | 技术栈/形态 | 功能 | 与本项目差距 | 可借鉴点 | 引用方式 |
|---|---|---|---|---|---|---|
| [Noeky/bilibili-follow-manager](https://github.com/Noeky/bilibili-follow-manager)（13★） | MIT | Python | 关注列表管理 | 功能较基础，无 AI 分类、无提醒/周报 | MIT 兼容，可代码级参考其接口调用写法 | 思想借鉴（必要时可引用代码，需保留版权声明） |
| [ZhiLin-Sam/bilibili-follow-manager](https://github.com/ZhiLin-Sam/bilibili-follow-manager)（2★，2026-07 仍活跃） | **无 License** | Tkinter GUI + FastAPI + React/shadcnUI 双前端 | 关注列表分析清理 | 与本项目技术栈高度相似，但无 AI 分类、无 RSS 集成 | 验证了 "FastAPI + React" 自托管选型的可行性 | 无接触（无 License 即保留所有权利，不可复制代码，仅可参考其公开描述的功能设计） |
| [Franklinyung/bilibili-following-manager](https://github.com/Franklinyung/bilibili-following-manager)（1★，2026-08 活跃） | **无 License** | 油猴脚本 (JS) | 批量分组、动态页分组筛选、死粉识别、**AI 智能分类** | 功能上最接近本项目，但为浏览器端脚本，无服务端持久化、无提醒/周报 | **AI 分类提示词设计与分类维度**的思想参考；死粉识别规则 | 思想借鉴（仅功能思想，无代码接触） |
| [YZz-S/Bilibili-batch-operation-tool](https://github.com/YZz-S/Bilibili-batch-operation-tool)（6★，2026-09 活跃） | NOASSERTION | Python | 批量分析与处理关注列表 | 无分类/AI/提醒，纯批量操作 | 批量操作的限速与分页处理思路 | 事实/思想参考（License 不明，禁止复制代码） |
| [fangd123/bilibili-following-exporter](https://github.com/fangd123/bilibili-following-exporter)（2★） | MIT | Python | 关注列表导出 Excel | 仅导出单一功能 | 导出数据结构/列设计参考 | 思想借鉴（MIT 兼容） |

补充观察：[sw1128/Bilibili_UnFollow](https://github.com/sw1128/Bilibili_UnFollow)（44★，无 License，批量取关工具）star 数最高，印证"批量管理关注"是真实需求；[xiaoyan94/bili-follow-manager](https://github.com/xiaoyan94/bili-follow-manager)（多平台关注管理，无 License）展示了多平台抽象思路，与本项目无关不展开。

**领域结论**：无可整体复用的成熟方案；多数项目无 License（法律上不可复制）；有 AI 分类的项目仅浏览器脚本形态。本项目的"服务端持久化 + 定时提醒 + 周报 + RSS 集成"组合存在明确空白。

---

## 5. 总结论与引用策略

1. **本项目自研 FastAPI 服务**，不 vendor 任何上游代码，不引入 bilibili-api（GPL-3.0 且已死亡）。
2. 对上游一律**只参考"API 事实"与"设计思想"**，不复制任何受版权保护的文本或代码：
   - bilibili-API-collect 的文档文本（CC BY-NC 4.0）零复制；
   - Nemo2011/bilibili-api 零接触（避免 GPL 传染与法律连带）；
   - 无 License 的同类项目零代码接触。
3. **不在本仓库沉淀系统性 B 站 API 文档**；接口调用面保持最小白名单（登录凭据、关注列表/分组 CRUD、用户基本信息），全部限定于用户本人账号授权的数据。
4. 运行时措施：请求限速与退避、凭据本地加密落盘、README 中声明工具性质与用户自担风险、不提供任何绕过反爬/签名鉴权的实现。

### 参考对象引用方式一览

| 对象 | License | 引用方式 |
|---|---|---|
| biliup/biliup | MIT | 思想借鉴（凭据管理、服务分层、调度）；无代码搬运 |
| Nemo2011/bilibili-api | GPL-3.0-or-later（已关停） | **无接触**；仅作 API 事实的间接线索 |
| SocialSisterYi/bilibili-API-collect | CC BY-NC 4.0（已关停） | 事实引用；**不复制文本**、不在仓库沉淀文档 |
| Noeky/bilibili-follow-manager | MIT | 思想借鉴（可代码级，需保留声明） |
| ZhiLin-Sam/bilibili-follow-manager | 无 License | 无接触；思想借鉴 |
| Franklinyung/bilibili-following-manager | 无 License | 思想借鉴（AI 分类维度、死粉识别思路） |
| YZz-S/Bilibili-batch-operation-tool | NOASSERTION | 事实/思想参考；无代码接触 |
| fangd123/bilibili-following-exporter | MIT | 思想借鉴（导出结构） |

### 参考链接

- https://github.com/biliup/biliup
- https://github.com/Nemo2011/bilibili-api （已归档关停）
- https://pypi.org/project/bilibili-api-python/
- https://github.com/SocialSisterYi/bilibili-API-collect （已归档关停）
- 上文表格中各同类项目仓库链接
