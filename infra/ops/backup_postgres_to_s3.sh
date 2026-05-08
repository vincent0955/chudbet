#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/opt/chudbet"
ENV_FILE="${ROOT_DIR}/.env.prod"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.prod.yml"
BACKUP_DIR="${ROOT_DIR}/backups"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}"
  exit 1
fi

mkdir -p "${BACKUP_DIR}"

# shellcheck disable=SC1090
source "${ENV_FILE}"

if [[ -z "${S3_BACKUP_BUCKET:-}" ]]; then
  echo "S3_BACKUP_BUCKET is not set in ${ENV_FILE}"
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive_name="chudbet_db_${timestamp}.sql.gz"
archive_path="${BACKUP_DIR}/${archive_name}"

docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T postgres \
  pg_dump -U "${POSTGRES_USER}" "${POSTGRES_DB}" | gzip > "${archive_path}"

aws s3 cp "${archive_path}" "s3://${S3_BACKUP_BUCKET}/${archive_name}"

# keep only 7 most recent local copies
ls -1t "${BACKUP_DIR}"/chudbet_db_*.sql.gz | awk 'NR>7' | xargs -r rm -f

echo "Backup uploaded: s3://${S3_BACKUP_BUCKET}/${archive_name}"
