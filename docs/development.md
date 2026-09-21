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
| 统一入口 | `.\scripts\lint.ps1` / `.\scripts\format.ps1` / `.\scripts\test.ps1` |

## 约定

- 本机服务只绑定 `127.0.0.1`。
- 不把云 API Key 写入配置。
- 一个 Linear Issue 对应一个功能分支；Commit 使用 Conventional Commits 并带 Issue ID。
- v0.1 骨架不实现小说业务，也不直接调用 Ollama / Milvus。
