# 开发说明

## 命令

| 目的 | 命令 |
| --- | --- |
| 后端 lint | `cd backend; uv run ruff check .` |
| 后端 format | `cd backend; uv run ruff format .` |
| 后端 test | `cd backend; uv run pytest` |
| 前端 lint | `cd frontend; pnpm lint` |
| 前端 format | `cd frontend; pnpm format` |
| 前端 build | `cd frontend; pnpm build` |
| Milvus 启动 | `.\scripts\milvus-up.ps1` 或 `./scripts/milvus-up.sh` |
| Milvus 健康 | `.\scripts\milvus-health.ps1` 或 `./scripts/milvus-health.sh` |
| Milvus 停止 | `.\scripts\milvus-down.ps1` 或 `./scripts/milvus-down.sh` |

## 约定

- 本机服务只绑定 `127.0.0.1`。
- 不把云 API Key 写入配置。
- SQLite schema 只通过 Alembic 升级，启动时禁止 drop / recreate。
- 一个 Linear Issue 对应一个功能分支；Commit 使用 Conventional Commits 并带 Issue ID。
- v0.1 不实现小说业务。Ollama/Milvus 只做 Adapter 与健康检查，不把向量库当 Canon。
