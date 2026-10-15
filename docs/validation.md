# Local validation — October 15, 2026

Executed on this Apple Silicon Mac; these are observed results, not target performance guarantees.

| Check | Result |
| --- | --- |
| Native PostgreSQL | 17.11; PostGIS 3.6.4; project-local SCRAM cluster on 127.0.0.1:5432 |
| Docker PostgreSQL | 17.5; PostGIS 3.5.2 from `postgis/postgis:17-3.5`; 127.0.0.1:55432 |
| Python | Host 3.14.8; container 3.12; exact resolved dependencies in requirements.lock |
| Native tests | 28 passed |
| Docker database tests | 28 passed |
| API + simulator | Two cycles / 24 XML updates accepted in each environment; 12 current assets each |
| Native recovery | `backups/native-verified.dump` → `gis_restore_native_verified`: RECOVERY VERIFIED |
| Docker recovery | `backups/docker-verified.dump` → `gis_restore_docker_verified`: RECOVERY VERIFIED |
| Staging change | `gis_restore_migration_rehearsal`: baseline, migration 002, rollback, reapply, repeated no-op verified |
| Restricted monitoring | Docker health query reports 12 current assets and zero waiting locks |
| Ruff / whitespace checks | Passed |

The unit suite reports one upstream Starlette warning about future `httpx2` test-client usage. Current tests pass with the locked httpx version.

## Native million-row benchmark

Full JSON plans and buffer counts: `artifacts/benchmark-native-1m.json` (local, ignored). These are warmed-cache runs on one machine. The isolated table includes one million synthetic telemetry positions, across 100 asset identifiers.

| Query | Before index, median | After index, median |
| --- | ---: | ---: |
| Geography proximity (1 km radius) | 231.954 ms | 14.068 ms |
| Asset/time range, newest 100 | 24.617 ms | 0.024 ms |

Compare plan nodes, buffers, index build duration, and storage in the saved JSON. These numbers are specific to the generated distribution and do not measure concurrent ingestion throughput.

## State left for development

- Colima is running with 2 CPUs, 4 GiB memory, and a 20 GiB virtual disk. QEMU handles the amd64 PostGIS image; Rosetta was not installed.
- Docker DB and API are running and healthy. API docs: http://127.0.0.1:8000/docs.
- Native database remains running on 5432. The temporary native API on 8001 was stopped.
- `.env` selects Docker for host commands; switch with `python scripts/use_database.py native` when needed. Credentials are private in `.env`, not committed.
- No simulator is left running. Start one with `.venv/bin/gis-simulate`.
- The baseline data, benchmark table, staging database, and restored databases remain for inspection.
- No commits or pushes were made. GitHub Actions is configured but has not run remotely.
- QGIS, ArcGIS, and a native Ubuntu VM were not installed or runtime-tested. Their setup and compatibility evaluation are documented separately.

Stop Docker services with `./scripts/compose stop`, stop native PostgreSQL with `.venv/bin/python scripts/native_db.py stop`, and stop the VM with `colima stop` when finished. These commands preserve data.
