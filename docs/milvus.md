# Milvus Standalone

Milvus is a **rebuildable vector index**, not Canon. SQLite (`DATA_DIR/app.db`) is the business source of truth. If you delete Milvus volumes or containers, the application should still start; later versions will rebuild the index from SQLite/files.

## Start / stop

```powershell
.\scripts\milvus-up.ps1
.\scripts\milvus-down.ps1
.\scripts\health-check.ps1
```

Images are pinned in `infra/milvus/docker-compose.yml` (no `latest`).

- gRPC: `127.0.0.1:19530`
- healthz: `http://127.0.0.1:9091/healthz`

The backend health adapter never crashes the process when Milvus is down; it returns an unavailable status and a rebuild hint.
