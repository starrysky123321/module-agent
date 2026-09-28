#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage: $0 BACKUP_FILE [DRILL_DATABASE]"
  echo "Restores into an isolated database whose name ends with _restore_drill."
  echo "The primary application database is always refused."
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

backup_file="${1:-}"
target_database="${2:-module_agent_restore_drill}"
if [[ -z "$backup_file" || ! -f "$backup_file" ]]; then
  echo "A readable backup file is required" >&2
  exit 2
fi
if [[ ! "$target_database" =~ ^[A-Za-z0-9_]+_restore_drill$ ]]; then
  echo "Drill database name must end with _restore_drill" >&2
  exit 2
fi

primary_database="$(docker compose exec -T postgres sh -ec 'printf "%s" "$POSTGRES_DB"')"
database_user="$(docker compose exec -T postgres sh -ec 'printf "%s" "$POSTGRES_USER"')"
if [[ "$target_database" == "$primary_database" ]]; then
  echo "Refusing to overwrite the primary database" >&2
  exit 2
fi

docker compose exec -T postgres pg_restore --list < "$backup_file" > /dev/null
docker compose exec -T postgres dropdb \
  --username "$database_user" --if-exists "$target_database"
docker compose exec -T postgres createdb \
  --username "$database_user" "$target_database"
docker compose exec -T postgres pg_restore \
  --username "$database_user" \
  --dbname "$target_database" \
  --no-owner \
  --no-privileges \
  < "$backup_file"
docker compose exec -T postgres pg_isready \
  --username "$database_user" --dbname "$target_database"

echo "Restore drill succeeded in database: $target_database"
echo "Inspect it, then remove it with:"
echo "docker compose exec -T postgres dropdb --username $database_user $target_database"
