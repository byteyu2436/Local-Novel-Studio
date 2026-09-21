#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="$ROOT/infra/milvus/docker-compose.yml"
PROJECT="local-novel-studio-milvus"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not available; nothing to stop for this project's Milvus stack."
  exit 0
fi

docker compose -f "$COMPOSE" -p "$PROJECT" down
echo "Stopped only compose project '$PROJECT'. Other containers were not touched."
