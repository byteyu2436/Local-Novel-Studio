# Milvus Standalone

Milvus is a **rebuildable vector index**, not Canon. SQLite (`DATA_DIR/app.db`) is the business source of truth. Deleting Milvus volumes or containers does not delete novels, chapters, or memory; later versions rebuild the index from SQLite/files.

## Prerequisites

- Windows 11: Docker Desktop with WSL2 backend, Compose plugin enabled. Start Docker Desktop before `milvus-up`; `docker --version` alone is not enough if the engine pipe is missing.
- Linux: Docker Engine + Compose plugin. Do not install Milvus as a host binary for v0.1.0.

Pinned images in `infra/milvus/docker-compose.yml` (never `latest`):

- `milvusdb/milvus:v2.5.4`
- `quay.io/coreos/etcd:v3.5.16`
- `minio/minio:RELEASE.2024-12-18T13-15-44Z`

Compose project name: `local-novel-studio-milvus`. Scripts never stop unrelated containers.

## Ports

- gRPC: `127.0.0.1:19530` (`MILVUS_HOST` / `MILVUS_PORT`)
- healthz: `http://127.0.0.1:9091/healthz` (`MILVUS_HEALTH_PORT`)

## Commands

Windows PowerShell (repo root):

```powershell
.\scripts\milvus-up.ps1
.\scripts\milvus-health.ps1
.\scripts\milvus-down.ps1
```

Linux / Git Bash:

```bash
./scripts/milvus-up.sh
./scripts/milvus-health.sh
./scripts/milvus-down.sh
```

Validate compose without starting:

```powershell
docker compose -f infra/milvus/docker-compose.yml config
```

The backend health adapter never crashes FastAPI when Milvus is down; Diagnostics returns warning/unavailable and a rebuild hint.

## Common failures

| Symptom | What to do |
| --- | --- |
| Docker is not available | Install Docker Desktop (Windows/WSL2) or Docker Engine. Scripts do not install it. |
| Docker Engine is not running (`milvus-health` exit 7) | Start Docker Desktop and wait until `docker info` shows a ServerVersion. Do not run `milvus-up` until the engine is up. |
| Port 19530 is already in use | Stop the other listener, or skip starting this stack until the port is free. |
| Registry mirror EOF (USTC / Hub) | Retry, or pull the pinned tags from a working Hub mirror and `docker tag` them to the compose names. Do not unpin versions. |
| Containers are not started | Run `milvus-up`. |
| Port 9091 is not reachable | Wait for the standalone healthcheck (`start_period` 90s) and inspect `docker compose logs`. |
| healthz failed / not ready | Retry health after the container becomes healthy. FastAPI can stay up. |

## Integration smoke (recorded)

Windows 11 + Docker Desktop 29.7.2 + Compose v5.5.1, 2026-09-21. Full log: `docs/handoff/CY-125-milvus-smoke.md`.

1. Compose config validates.
2. `milvus-up` + `milvus-health` — healthz OK; FastAPI Diagnostics milvus = `ok`.
3. `milvus-down` — FastAPI still HTTP 200; milvus check is warning/unavailable with a rebuildable-index hint.
4. Repeat up/down is safe; scripts only target project `local-novel-studio-milvus`.

Do not treat Milvus volumes as a backup of Canon.
