#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

cleanup() {
    docker compose down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose build mommy-web
docker compose up -d mommy-web

for _ in $(seq 1 45); do
    if curl --fail --silent http://127.0.0.1:8000/api/health >/tmp/mommy-health.json; then
        break
    fi
    sleep 1
done

curl --fail --silent http://127.0.0.1:8000/api/health | grep '"ok":true' >/dev/null
curl --fail --silent http://127.0.0.1:8000/ | grep '<div id="app">' >/dev/null

container_user="$(docker compose exec -T mommy-web id -u)"
test "$container_user" != "0"

docker compose exec -T mommy-web sh -c 'test -w /app/data'

echo "Docker smoke test passed"
