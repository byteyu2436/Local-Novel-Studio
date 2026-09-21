#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="$ROOT/infra/milvus/docker-compose.yml"
PROJECT="local-novel-studio-milvus"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not available. Install Docker Engine, then retry."
  exit 2
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose is not available. Enable the Compose plugin, then retry."
  exit 2
fi

port_open() {
  python -c "import socket,sys; s=socket.socket(); s.settimeout(0.4); raise SystemExit(0 if s.connect_ex(('127.0.0.1', int(sys.argv[1])))==0 else 1)" "$1"
}

RUNNING="$(docker compose -f "$COMPOSE" -p "$PROJECT" ps --status running --format '{{.Name}}' 2>/dev/null || true)"
if port_open 19530 && ! echo "$RUNNING" | grep -q "lns-milvus-standalone"; then
  echo "Port 19530 is already in use by another process. Stop that listener before starting this project's Milvus stack."
  exit 3
fi

docker compose -f "$COMPOSE" -p "$PROJECT" up -d
echo "Milvus Standalone is starting (stack: $PROJECT). Health: http://127.0.0.1:9091/healthz"
echo "Repeatable: running this script again is safe. Stop with scripts/milvus-down.sh"
