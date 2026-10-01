# BiliUP Organizer

Self-hosted Bilibili following organizer with smart classification, reminders,
weekly reports and LumiRSS integration.

BiliUP Organizer 拉取你的 B 站关注列表，用本地分组（任意数量与命名）+ B 站原生分组
映射 + AI 建议与人工审核来整理 UP 主，并提供断更/长期未看/从未观看/重要 UP 未看/
低置信度/登录失效/同步失败/风控等提醒、SMTP 邮件与每周 HTML 周报、RSS/Atom 输出、
LumiRSS 联动、备份恢复与审计日志。

## Features

- **B 站账号**：扫码登录或手动粘贴 Cookie；登录失效与风控自动检测
- **关注同步**：增量同步关注列表与最近投稿，检测新关注/取关/断更
- **关注列表**：分页（50/100/200）或「全部一页」（虚拟滚动，数千 UP 依然流畅）自由切换；
  筛选/排序/模式写入 URL 可分享；全选本页或全选当前筛选结果
- **分类体系**：主分类（本地分组，任意数量、可新增/重命名/合并/别名）+ 内容标签
  （一个 UP 多个）+ 状态标签（待整理/吃灰/重点关注等），三个维度相互独立；
  「吃灰」是状态不是内容分类
- **AI 全量分类**：持久化后台任务一次分类全部 UP（可只分类新增），支持暂停/继续/
  取消/失败重试，页面刷新进度不丢；输出 主分类 + 标签 + 置信度 + 依据；
  高置信度可自动应用，中置信度进入人工审核，低置信度标记「无法确定」而不强行猜测；
  别名与相似分类归一避免重复分类膨胀；重新分类保留 旧分类 → 新建议 对照
- **批量操作**：列表多维筛选 + 大规模批量移动/标签/标记（单请求提交，非逐条风暴）+
  撤销（Undo）；B 站原生分组写入需显式确认且支持 Dry Run 预览
- **B 站原生分组**：与本地分类解耦，手动推送（先备份），定时自动推送默认关闭
- **提醒中心**：断更、长期未看、从未观看、重要 UP 未看、低置信度、登录失效、同步失败、风控、LumiRSS 失败
- **周报**：每周一自动生成并发送 HTML 周报（可手动预览/补发）
- **RSS/Atom**：按分组生成订阅源（token 鉴权），可直接被 LumiRSS/FreshRSS 等订阅
- **LumiRSS 联动**：新视频自动推送到 LumiRSS Inbox（可配置端点与 Token，失败提醒）
- **备份恢复**：SQLite 在线备份/下载/上传恢复；审计日志记录所有变更

## Quickstart (development, WSL2/Linux)

```bash
# backend (Python 3.11+, uv)
uv sync
DEMO_MODE=1 uv run uvicorn app.main:app --port 8066   # demo data, no external calls

# frontend (Node 18+)
cd apps/web && npm install && npm run dev              # http://localhost:5173 (proxies /api)

# tests
uv run pytest -q                                       # backend
cd apps/web && npm run e2e                             # Playwright e2e (demo mode)
```

Demo mode seeds synthetic data and never calls Bilibili/AI/SMTP/LumiRSS —
use it for development, screenshots and e2e.

## Production

Single versioned Docker image (built by GitHub Actions, published to GHCR);
Caddy reverse-proxies `up.oouo.top` to the container. The production server
never builds anything — it only pulls images. See `docs/DEPLOY.md` and
`deploy/`.

```bash
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml pull
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d
```

## Configuration

Copy `.env.example` to `.env` (never commit it). Secrets can also be managed in
the Settings UI (AI / SMTP / LumiRSS sections); env values act as defaults.

## Security

- Session cookie HttpOnly + CSRF double-submit; argon2 password hashing
- All SQL via SQLAlchemy ORM or parameter-bound literals; no string-built SQL
- Audit log for every mutation; secrets masked in API responses
- Security scans in CI: CodeQL, Gitleaks, Trivy, OSV-Scanner

## Documentation

- [Architecture & frozen contracts](docs/ARCHITECTURE.md)
- [API reference](docs/API.md)
- [Bilibili API research](docs/RESEARCH_BILIBILI.md)
- [Upstream & license audit](docs/RESEARCH_UPSTREAM.md)
- [LumiRSS integration](docs/RESEARCH_LUMIRSS.md)
- [Deployment guide](docs/DEPLOY.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## License

MIT — see [LICENSE](LICENSE). Upstream API facts are referenced (not copied)
from community documentation; see the research docs for attribution.
