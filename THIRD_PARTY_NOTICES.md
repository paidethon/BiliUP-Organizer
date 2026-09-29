# THIRD_PARTY_NOTICES — 第三方组件声明

> **本仓库主 License 计划为 MIT。**
>
> 本文件声明 BiliUP Organizer 计划引入的第三方运行时依赖及其许可证信息。
> 所有组件均以其原始许可证使用；各组件的完整许可证文本随其发行版（PyPI sdist/wheel、npm tarball）附带，或可在对应官方仓库获取。
> 许可证信息核对日期：**2026-09-29**（数据来源：pypi.org 与 registry.npmjs.org 的包元数据）；SPDX 标识符为版本无关写法，若后续升级依赖请同步复核本表。

## 后端依赖（Python / PyPI）

| 组件 | 用途 | License (SPDX) | 版权归属（通用格式） |
|---|---|---|---|
| fastapi | Web 框架（REST API） | MIT | Copyright (c) FastAPI contributors（Sebastián Ramírez） |
| uvicorn | ASGI 服务器 | BSD-3-Clause | Copyright (c) Uvicorn contributors（Encode OSS Ltd.） |
| sqlalchemy | ORM / 数据库访问 | MIT | Copyright (c) SQLAlchemy authors and contributors |
| pydantic | 数据校验 / 模型 | MIT | Copyright (c) Pydantic contributors（Samuel Colvin、Pydantic Services Inc.） |
| pydantic-settings | 配置管理 | MIT | Copyright (c) Pydantic Services Inc. and contributors |
| httpx | 异步 HTTP 客户端（B 站接口薄封装） | BSD-3-Clause | Copyright (c) HTTPX contributors（Encode OSS Ltd.） |
| apscheduler | 定时任务调度（提醒、周报） | MIT | Copyright (c) APScheduler contributors（Alex Grünebaum） |
| jinja2 | 服务端模板渲染 | BSD-3-Clause | Copyright (c) Jinja contributors（Pallets） |
| aiosmtplib | 异步 SMTP（提醒邮件发送） | MIT | Copyright (c) aiosmtplib contributors |
| argon2-cffi | 密码/凭据哈希 | MIT | Copyright (c) argon2-cffi contributors（Hynek Schlawack） |
| python-multipart | multipart/form-data 解析（文件上传） | Apache-2.0 | Copyright (c) python-multipart contributors（Andrew Dunham 等） |

## 前端依赖（JavaScript / npm）

| 组件 | 用途 | License (SPDX) | 版权归属（通用格式） |
|---|---|---|---|
| react | UI 框架 | MIT | Copyright (c) Meta Platforms, Inc. and affiliates |
| react-dom | React DOM 渲染器 | MIT | Copyright (c) Meta Platforms, Inc. and affiliates |
| react-router-dom | 前端路由 | MIT | Copyright (c) Remix Software Inc. |
| @tanstack/react-query | 服务端状态管理 / 数据请求 | MIT | Copyright (c) TanStack contributors（Tanner Linsley） |
| tailwindcss | 原子化 CSS 框架 | MIT | Copyright (c) Tailwind Labs, Inc. |
| qrcode | 二维码生成（扫码登录） | MIT | Copyright (c) Ryan Day (soldair) and contributors |
| vite | 前端构建工具 | MIT | Copyright (c) Vite contributors（VoidZero Inc. / Evan You） |

## 说明

1. **MIT 主 License 兼容性**：上表全部组件（MIT / BSD-3-Clause / Apache-2.0）均与 MIT 兼容，可安全用于本项目及其衍生分发。
2. **Apache-2.0 附加条款**：`python-multipart` 采用 Apache-2.0，含专利授权与 NOTICE 条款；分发时如该项目附有 NOTICE 文件，应一并保留。
3. **BSD-3-Clause 义务**：`uvicorn`、`httpx`、`jinja2` 的许可证要求在分发副本中保留版权声明与免责声明，本文件即作为集中保留位置。
4. **版权归属为通用格式**：表中归属按 "Copyright (c) <组件名> contributors" 的通用写法给出，括号内为常见的上游版权持有人信息，仅作提示；具有法律效力的以各组件随发行版附带的 LICENSE 文件为准。
5. **传递依赖**：本表仅覆盖直接运行时依赖；各直接依赖自身的传递依赖许可证由包管理器（pip / npm）锁文件与 `pip-licenses` / `license-checker` 类工具在构建时另行核验。
