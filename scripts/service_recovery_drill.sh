#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: $0 SERVICE --confirm"
  echo "Kills and recreates one application process to verify restart recovery."
}

service="${1:-}"
confirmation="${2:-}"
if [[ "$service" == "--help" || "$service" == "-h" ]]; then
  usage
  exit 0
fi
if [[ "$confirmation" != "--confirm" ]]; then
  echo "This drill interrupts a running service; pass --confirm" >&2
  exit 2
fi
case "$service" in
  api|literature-worker|literature-completion-worker|code-worker|code-completion-worker)
    ;;
  *)
    echo "Unsupported recovery drill service: $service" >&2
    exit 2
    ;;
esac

docker compose kill --signal KILL "$service"
docker compose up -d "$service"

for _ in $(seq 1 60); do
  if docker compose ps --status running --services | grep -Fxq "$service"; then
    if [[ "$service" != "api" ]] || docker compose exec -T api python -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/ready', timeout=2)" \
      > /dev/null 2>&1; then
      echo "Recovery drill succeeded: $service recovered"
      exit 0
    fi
  fi
  sleep 1
done

echo "Recovery drill failed: $service did not recover within 60 seconds" >&2
docker compose logs --tail 100 "$service" >&2
exit 1
