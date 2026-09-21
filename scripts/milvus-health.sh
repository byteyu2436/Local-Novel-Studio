#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="$ROOT/infra/milvus/docker-compose.yml"
PROJECT="local-novel-studio-milvus"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not available. Install Docker Engine before starting Milvus."
  exit 2
fi

NAMES="$(docker compose -f "$COMPOSE" -p "$PROJECT" ps --format '{{.Name}}' 2>/dev/null || true)"
if [ -z "$NAMES" ]; then
  echo "This project's Milvus containers are not started. Run scripts/milvus-up.sh."
  exit 4
fi

if ! python - <<'PY'
import socket
s = socket.socket()
s.settimeout(0.4)
try:
    s.connect(("127.0.0.1", 9091))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
PY
then
  echo "Port 9091 is not reachable. The container exists but the health port is closed; wait for startup or inspect docker compose logs."
  exit 5
fi

if curl -fsS --max-time 5 "http://127.0.0.1:9091/healthz" >/dev/null; then
  echo "Milvus healthz OK. Vector index is rebuildable and is not Canon."
  exit 0
fi

echo "Milvus is not ready yet (healthz failed). Wait for the standalone healthcheck, then retry."
exit 6
