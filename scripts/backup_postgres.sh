#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: $0 [backup-file]"
  echo "Creates and verifies a PostgreSQL custom-format backup."
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="${1:-backups/module-agent-${timestamp}.dump}"
if [[ -z "$backup_file" || "$backup_file" == */ ]]; then
  echo "Backup target must be a file path" >&2
  exit 2
fi

mkdir -p -- "$(dirname -- "$backup_file")"
partial_file="${backup_file}.partial"
trap 'rm -f -- "$partial_file"' EXIT

docker compose exec -T postgres sh -ec \
  'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --no-owner --no-privileges' \
  > "$partial_file"

docker compose exec -T postgres pg_restore --list < "$partial_file" > /dev/null
mv -- "$partial_file" "$backup_file"
trap - EXIT
echo "Verified backup created: $backup_file"
