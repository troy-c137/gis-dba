#!/usr/bin/env bash
# Docker clients are version-matched to PostgreSQL 17; archives are streamed to the host.
set -euo pipefail
umask 077
mkdir -p backups
archive="backups/docker-$(date -u +%Y%m%dT%H%M%SZ).dump"
./scripts/compose exec -T db pg_dump -U postgres -d gis_lab --format=custom --no-owner --no-acl > "$archive"
printf 'Archive: %s\nUse gis-backup for snapshot manifests and verified recovery.\n' "$archive"
