# Local Novel Studio

开源、本地优先、单用户的长篇小说续写工具。浏览器访问 React UI，FastAPI 提供本机 API；所有 AI 模型默认在本机运行，不设计账号、协作或云端控制面。

当前版本目标是 **v0.1.0 Foundation & Local Runtime**：先建立可启动的前后端骨架与开发基线。小说导入、分析、检索和续写会在后续版本落地。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Frontend | React + TypeScript + Vite + shadcn/ui |
| Backend | Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2 |
| Main DB | SQLite（后续 Issue 接入 Alembic） |
| LLM | Ollama（后续 Issue 接入 Adapter） |
| Vector DB | Milvus Standalone（后续 Issue 接入） |

默认绑定 `127.0.0.1`。推荐端口：Frontend `5173`，Backend `8000`。

## 环境要求

- Python 3.12+
- Node.js LTS（pnpm 或 npm）
- Git

真实 Ollama / GPU 模型验证只在目标 Windows GPU 机器上进行。日常开发默认 `LNS_EXECUTION_PROFILE=cpu-dev`。

## 快速开始

在仓库根目录：

```powershell
Copy-Item .env.example .env
```

后端：

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开一个终端启动前端：

```powershell
cd frontend
pnpm install
pnpm dev
```

- Backend health: http://127.0.0.1:8000/health
- Frontend: http://127.0.0.1:5173

首次启动会在 `DATA_DIR`（默认 `./data`）下创建 `logs/`、`novels/`、`cache/` 和 `app.db`，并通过 Alembic 升级 SQLite schema。数据库路径可用 `SQLITE_PATH` 覆盖；应用不会自动删除或重建已有数据库。

Milvus 是可重建的向量索引，不是 Canon。启动/停止见 `docs/milvus.md` 与 `scripts/milvus-up.ps1`。容器未运行时后端仍应启动。

也可使用 `scripts/dev-backend.ps1` 与 `scripts/dev-frontend.ps1`。

## 质量命令

在仓库根目录：

```powershell
.\scripts\lint.ps1
.\scripts\format.ps1
.\scripts\test.ps1
```

- 后端：`ruff check` / `ruff format` / `pytest`
- 前端：`pnpm lint` / `pnpm format` / `pnpm build`

## 仓库结构

```text
backend/     FastAPI 应用
frontend/    React UI
infra/       本地基础设施（Milvus Compose 等后续接入）
scripts/     开发与质量脚本
docs/        开发说明
tests/       测试入口说明（实现位于 backend/tests）
```
