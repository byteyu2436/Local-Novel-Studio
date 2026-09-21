# CY-125 Milvus Windows integration smoke

Environment: Windows 11, Docker Desktop 29.7.2, Compose v5.5.1.

Pinned images: `milvusdb/milvus:v2.5.4`, `quay.io/coreos/etcd:v3.5.16`, `minio/minio:RELEASE.2024-12-18T13-15-44Z`.

## Recorded result (2026-09-21)

1. `docker compose -f infra/milvus/docker-compose.yml config` — valid.
2. Docker Desktop engine was stopped; starting Docker Desktop made `docker info` return ServerVersion 29.7.2.
3. Default Hub mirror `docker.mirrors.ustc.edu.cn` returned EOF for minio/milvus. Workaround: pull via `docker.m.daocloud.io/...` then `docker tag` to the pinned names. Compose file was not changed.
4. `.\scripts\milvus-up.ps1` — stack `local-novel-studio-milvus` started.
5. `.\scripts\milvus-health.ps1` — healthz OK after ~20s. Message: vector index is rebuildable and is not Canon.
6. FastAPI `GET /api/system/diagnostics` while up — HTTP 200, milvus check `ok` (`Milvus healthz returned OK.`).
7. `.\scripts\milvus-down.ps1` — only this compose project stopped.
8. Health script after down — exit 4, containers not started.
9. FastAPI diagnostics after down — HTTP 200, milvus `warning`, rebuildable-index hint, process stayed up.

Do not treat this as Collection schema or index rebuild work. Those are later issues.
