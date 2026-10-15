# DBA exercises and evidence

Record commands, environment versions, execution plans, and observations under `artifacts/` (ignored). Do not claim a recovery or speedup until you have run it.

## 1. Relational integrity

Initialize and seed the database, then diagram the keys in `docs/architecture.md`. Explain why a unit name belongs in units, why event time differs from receipt time, and why the current-state composite FK matters. Try a nonexistent equipment ID and an invalid battery percentage through ingestion. Verify no partial event/location survives. Integration tests cover this behavior, duplicate messages, concurrent retries, late updates, and denied writes.

```bash
pytest -m 'not integration'
RUN_DB_TESTS=1 pytest
```

Use only a development database: integration tests briefly create `SIM-TEST-ASSET` and clean it up. Do not run this suite concurrently against the same database. GitHub Actions provisions an isolated PostGIS service and runs these checks on push/PR.

## 2. Spatial SQL

```bash
set -a; source .env; set +a
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/spatial_queries.sql
```

Compare geography distances in meters with geometry degrees. Explain why point construction uses longitude before latitude. Query the boundary between the two polygons: `ST_Covers` includes that boundary in both areas. Inspect the GiST node and buffer counts on history queries. Twelve current assets may favor small scans even with a history index.

## 3. Transactions and XML

Run the simulator while reading current positions in QGIS. Replay `examples/telemetry.xml` twice; the second request returns `inserted=false`. Change a coordinate while preserving its UUID: expect 409. Give a new UUID to an older observation: expect a new history row while current position stays newer. Try malformed XML, unknown equipment, coordinates outside bounds, NaN, and a timezone-free timestamp: expect 422 (oversized input: 413). Shut down PostgreSQL briefly: readiness should fail and ingestion should return 503; replay the same message after restart.

The event, location, and current pointer commit together through the psycopg transaction context. If a client loses a response after commit, exact replay is safe. The simulator retries transient failures four times with exponential delays and then exits so failure remains visible.

## 4. Query performance

```bash
python scripts/benchmark.py --rows 100000 --output artifacts/benchmark-100k.json
python scripts/benchmark.py --rows 1000000 --output artifacts/benchmark-1m.json
```

The exercise recreates **only** `lab.benchmark_telemetry`. It uses SQL `generate_series` for scalable synthetic history, runs ANALYZE, records one warm-up plus three measured `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plans before/after geography GiST and asset/time B-tree indexes, index build time, and total relation bytes. Application history and its indexes are untouched. This measures query indexing; it does not measure XML ingestion throughput or concurrent write latency.

Compare median execution times, rows removed by filters, scan type, shared hit/read buffers, sort nodes, planning time, and storage. Do not disable sequential scans to manufacture results. Before/after warm-cache runs do not model cold storage, and Docker emulation affects timings. A small/selectively poor query can correctly choose a sequential scan. Increase data or change selectivity and explain the observed choice. Investigate `VACUUM (ANALYZE)`, dead tuples, and autovacuum rather than changing global memory settings blindly.

## 5. Roles, monitoring, backup, recovery

`gis_reader` reads curated GIS views and polygons. `gis_ingest` executes a single fixed-search-path function; it cannot read or write base tables. `gis_monitor` reads current views and has PostgreSQL's `pg_monitor` privileges, which expose cluster-wide statistics and may reveal query text. Keep monitoring credentials restricted. Admin owns the schema/migrations. These shared cluster role names are intended for a dedicated lab cluster.

```bash
set -a; source .env; set +a
psql "$MONITOR_DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/monitor.sql
gis-admin health
```

Health JSON includes versions, asset count, newest observation, and waiting locks. Compare observation age to the simulator interval; an empty or stale dataset is not the same as a down database. Review database activity for long transactions, locks, deadlocks, connection usage, cache reads, and autovacuum timestamps. Slow queries over 250 ms and lock waits appear in DB logs. The Compose/native start options preload `pg_stat_statements`; enable it as admin with `CREATE EXTENSION IF NOT EXISTS pg_stat_statements;` when studying normalized statement statistics.

For backup/recovery, put PostgreSQL **17** client tools on PATH. A pg_dump client older than the server cannot dump it. Native Homebrew: `export PATH=/opt/homebrew/opt/postgresql@17/bin:$PATH`.

```bash
gis-backup backup backups/exercise-001.dump
gis-backup restore backups/exercise-001.dump --target gis_restore_exercise_001
```

The backup exports a repeatable-read snapshot, captures per-table counts and row fingerprints from it, and passes that same snapshot to `pg_dump`. The sidecar manifest and archive checksum allow validation even while live telemetry continues. Restore creates a **new** target (an existing target fails), uses `pg_restore --single-transaction --exit-on-error`, and checks fingerprints, migration hashes, event/location completeness, and the GIS view. Success prints `RECOVERY VERIFIED`. Review the target manually too; the fingerprint sum is a practical lab check, not a cryptographic proof of relational equality. A failed restore leaves a new database for inspection; it never deletes the source.

Backups exclude ownership/ACLs and cluster-wide roles. The restored database is admin-only until you explicitly apply grants with `ADMIN_DATABASE_URL` pointing to that target and run `gis-admin roles`. In a real recovery, secure role definitions and permissions need separate provisioning. Store archive and manifest together off-host with encryption and retention appropriate to the environment. They contain synthetic data but credentials and any future real datasets need separate care. Logical dumps provide recovery to a snapshot, not automatic failover or WAL-based point-in-time recovery. Record measured dump/restore duration as a first RTO observation and snapshot cadence as an RPO choice.

`bash scripts/docker_backup.sh` is a simple version-matched Docker pg_dump example. It produces an archive only; it does not create the validation manifest used by `gis-backup`.

## 6. Controlled migration and rollback

`001_core.sql` is the baseline. `002_asset_description.sql` is an additive nullable-column change. Migration checksums prevent silently editing already-applied files; new changes get new numbered files. Migration batches use a transaction, an advisory lock to serialize deploys, and a five-second DDL lock timeout.

Automated rehearsal in a new database: `python scripts/rehearse_migration.py --target gis_restore_rehearsal_002`. It checks baseline queries, deployment, rollback, reapplication, and a second no-op migration run. Existing targets fail without being overwritten.

To rehearse before deploying to a populated development database, first create/validate a logical backup, restore it to `gis_restore_staging_001`, and use that target for staging. An existing database already at 002 cannot demonstrate applying 002 again. To practice the full change on an empty staging database:

```bash
# Set ADMIN_DATABASE_URL to the same server with dbname gis_restore_staging_fresh.
# Keep that override for every staging command; .env is not overwritten.
export ADMIN_DATABASE_URL='postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/gis_restore_staging_fresh'
gis-admin create-db
gis-admin migrate --target 001_core.sql
gis-admin roles
gis-admin seed
gis-admin migrate
```

Confirm `description` exists, writes with it omitted still work, and GIS views retain their field set. Test API/ingestion against staging by also overriding DATABASE_URL and INGEST_DATABASE_URL to the staging DB. Review blocking sessions and backup completion before running `gis-admin migrate` on the intended development DB. Use `unset ADMIN_DATABASE_URL DATABASE_URL INGEST_DATABASE_URL` to return to `.env` defaults afterward.

Rollback file: `sql/rollback/002_asset_description.sql`. It **drops stored descriptions**; export those values, confirm applications do not depend on the column, and run it explicitly with psql on staging first. It removes the migration ledger entry so 002 can be reapplied. Prefer a forward fix for populated environments. Never rewrite 001 or automatically run destructive down-migrations at API startup.
