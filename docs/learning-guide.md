# Learn GIS database administration with this project

This workbook uses the initial build as it exists. You will operate the database, inspect its behavior, introduce small controlled failures, and explain what you observed. No additional application features are needed.

Work through the sessions in order. Allow roughly 45–90 minutes per session; performance, recovery, and troubleshooting may take longer. Repeat an exercise until you can explain the result before running it.

Use Docker for your first pass. Repeat selected exercises against the native database at the end. The two databases have independent data and different ports.

## How to use the workbook

**Terminal** blocks run in VS Code's integrated terminal. **SQL / psql** blocks run after connecting with `psql`. A prompt like `gis_lab=#` means you are inside psql; shell commands such as `gis-simulate` belong in another terminal. Use `\q` to leave psql. SQL statements end with a semicolon; psql commands beginning with `\` do not need one.

Keep a notebook at `artifacts/learning-notes.md`. This folder is ignored by Git. For every exercise, record:

- The question you were investigating and your prediction.
- The database, role, query or command, and relevant output.
- What happened, why it happened, and how you verified your explanation.
- Any changes you made and how you left the environment afterward.

Do not put connection strings, passwords, or API keys in the notebook. SQL output and service versions are enough. Keep reusable SQL you write yourself under a new `sql/practice/` directory if you want it reviewed in Git; keep machine-specific results under `artifacts/`.

The existing [architecture](architecture.md), [setup guide](setup.md), [DBA exercises](dba-labs.md), and [GIS notes](gis.md) are references. This workbook supplies the order and the hands-on steps.

## Session 1 — Know what you are operating

**Goal:** Distinguish the host, container, PostgreSQL server, database, schema, role, and API. A DBA should be able to identify the target before changing it.

### 1. Prepare a terminal

**Terminal A:**

```bash
cd /Users/troywarshaw/Code/Projects/gis-dba
source .venv/bin/activate
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
mkdir -p artifacts
```

The project and virtual environment already exist from the initial build. Do not regenerate `.env` or reinstall the database for this workbook. If they are missing, follow [setup](setup.md) first.

Start Colima if `colima status` says it is stopped. With the existing Colima installation, `colima start` reuses its configured VM.

```bash
colima status
```

### 2. Select Docker and load its connection settings

```bash
python scripts/use_database.py docker
set -a
source .env
set +a
./scripts/compose up -d db api
./scripts/compose ps
```

Expect database and API containers to be running; health may initially show `starting` before changing to `healthy`. For a first build or changed source, use `./scripts/compose up -d --build api`.

Each new terminal that needs database URLs or the API key should run the activation, PATH, and `.env` commands above. Do not print the contents of `.env` to capture evidence.

**Connection trap:** Changing `.env` does not replace variables already exported in a terminal. After switching modes, source `.env` again in every terminal you reuse. Restart any host API process. The Docker API always uses its own container-side `db:5432` connection.

### 3. Verify the database identity

**Terminal A:**

```bash
gis-admin health
psql "$ADMIN_DATABASE_URL" -X
```

**SQL / psql:**

```sql
\conninfo
\pset pager off
SELECT current_database(), current_user, inet_server_addr(), inet_server_port();
SELECT version();
SELECT PostGIS_Full_Version();
SHOW search_path;
SHOW TimeZone;
```

The database should be `gis_lab`; this connection uses the `postgres` administrator. PostgreSQL reports its **internal** server port, 5432, even when the host connects through Docker's published port 55432.

Record the actual versions. Native and Docker PostGIS versions differed in the initial validation; do not assume they are identical.

**Checkpoint:** Draw the path `VS Code terminal → localhost:55432 → container:5432 → gis_lab → tracking schema`. Explain why connecting to native port 5432 would reach a different dataset.

## Session 2 — Read the data model before changing it

**Goal:** Understand relationships, normalization, keys, indexes, and views.

### 1. Discover the objects

In the administrator psql session:

```sql
\dn
\dt tracking.*
\dv tracking.*
\d tracking.units
\d tracking.assets
\d tracking.telemetry_events
\d tracking.locations
\d tracking.current_state
\d tracking.operational_areas
\di tracking.*
```

Read `sql/migrations/001_core.sql` alongside this output. Inspect `002_asset_description.sql` to see the later nullable column.

### 2. Join identities to their owning units

```sql
SELECT a.asset_id, a.equipment_id, a.asset_type, u.code AS unit_code, u.name
FROM tracking.assets a
JOIN tracking.units u ON u.unit_id = a.unit_id
ORDER BY a.asset_id;
```

The initial seed creates 12 assets and two units. Existing practice work may add rows. Query rather than assuming a row count.

### 3. Compare identity, history, and current state

```sql
SELECT 'assets' AS relation, count(*) FROM tracking.assets
UNION ALL
SELECT 'events', count(*) FROM tracking.telemetry_events
UNION ALL
SELECT 'locations', count(*) FROM tracking.locations
UNION ALL
SELECT 'current_state', count(*) FROM tracking.current_state;

SELECT equipment_id, unit_code, status, battery_pct, observed_at
FROM tracking.current_assets
ORDER BY equipment_id;
```

An asset can exist before it has telemetry, so it may not appear in `current_assets`. Each accepted event should have one location. Many historical events can belong to one asset, while `current_state` has at most one row per asset.

### 4. Check an invariant yourself

```sql
SELECT count(*) AS events_missing_locations
FROM tracking.telemetry_events e
LEFT JOIN tracking.locations l USING (message_id)
WHERE l.message_id IS NULL;
```

Expect zero. The ingestion function maintains this invariant transactionally. The event-to-location foreign key alone does not require every event to have a location: it requires every location to have a parent event. That distinction matters when reasoning about constraints.

**Checkpoint:** Sketch the tables and foreign keys. Explain why copying a unit name into every event would create update problems, and why `current_state` references both `asset_id` and `message_id` in a composite foreign key.

## Session 3 — Make constraints fail, then practice rollback

**Goal:** See the difference between database enforcement, application validation, and transaction state.

Stop any simulator before these exercises. Use the administrator psql session; the application roles intentionally cannot perform these writes.

### 1. Attempt an invalid foreign key

Execute these statements individually:

```sql
BEGIN;
UPDATE tracking.assets
SET unit_id = -1
WHERE equipment_id = 'SIM-ASSET-001';
```

Expect a foreign-key error in the seeded lab: unit -1 does not exist. The transaction is now failed. Try:

```sql
SELECT 1;
```

Expect a message that commands are ignored until the failed transaction ends. Recover:

```sql
ROLLBACK;
SELECT 1;
```

Now the query succeeds. This is why an ingestion service must roll back after an error before reusing a connection.

### 2. Attempt to delete a referenced unit

```sql
BEGIN;
DELETE FROM tracking.units WHERE code = 'SIM-ALPHA';
ROLLBACK;
```

Expect a foreign-key error because seeded assets still reference that unit. Record the constraint name from the error and find it with `\d tracking.assets`.

### 3. Observe a successful change without keeping it

```sql
BEGIN;
INSERT INTO tracking.units(code, name)
VALUES ('SIM-PRACTICE-ROLLBACK', 'Temporary fictional practice group');
SELECT code, name FROM tracking.units WHERE code = 'SIM-PRACTICE-ROLLBACK';
ROLLBACK;
SELECT code, name FROM tracking.units WHERE code = 'SIM-PRACTICE-ROLLBACK';
```

Expect one row before rollback and zero after it. If that code already exists from other work, choose another unique `SIM-` code before starting.

**Checkpoint:** Explain atomicity and referential integrity using these results. Why would deleting a referenced unit silently be dangerous? Why is a failed transaction different from a failed database server?

## Session 4 — Trace synthetic telemetry from XML to SQL

**Goal:** Understand transactions, duplicate delivery, event time, current state, and error handling.

### 1. Measure a baseline

In psql:

```sql
SELECT count(*) AS events_before FROM tracking.telemetry_events;
```

In a second prepared terminal, with the Docker API running:

```bash
gis-simulate --cycles 3 --interval 2
```

Run the count again. Without other writers, this adds **36 events**: 12 synthetic assets per cycle. Current-state rows should remain at 12 for the original seeded assets.

```sql
SELECT count(*) FROM tracking.current_state;
SELECT a.equipment_id, e.observed_at, e.received_at, e.status
FROM tracking.telemetry_events e
JOIN tracking.assets a USING (asset_id)
ORDER BY e.received_at DESC
LIMIT 15;
```

`observed_at` is the reported observation time; `received_at` is assigned by the database. Delayed delivery can separate them substantially.

### 2. Prepare repeatable message experiments

Keep the simulator stopped. Run this in the prepared terminal; it creates practice files under ignored `artifacts/` without changing the checked-in example:

```bash
python - <<'PY'
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

out = Path('artifacts/xml-practice')
out.mkdir(parents=True, exist_ok=True)
base = ET.parse('examples/telemetry.xml').getroot()
now = datetime.now(timezone.utc)
base.find('message_id').text = str(uuid4())
base.find('observed_at').text = now.isoformat()
ET.ElementTree(base).write(out / 'valid.xml', encoding='utf-8')

conflict = deepcopy(base)
conflict.find('longitude').text = '-140.10'
ET.ElementTree(conflict).write(out / 'conflict.xml', encoding='utf-8')

late = deepcopy(base)
late.find('message_id').text = str(uuid4())
late.find('observed_at').text = (now - timedelta(minutes=10)).isoformat()
ET.ElementTree(late).write(out / 'late.xml', encoding='utf-8')

invalid = deepcopy(base)
invalid.find('message_id').text = str(uuid4())
invalid.find('battery_pct').text = '101'
ET.ElementTree(invalid).write(out / 'invalid.xml', encoding='utf-8')

unknown = deepcopy(base)
unknown.find('message_id').text = str(uuid4())
unknown.find('equipment_id').text = 'SIM-UNKNOWN'
ET.ElementTree(unknown).write(out / 'unknown.xml', encoding='utf-8')
print('Created valid, conflict, late, invalid, and unknown messages')
PY
```

This uses only the standard Python library and the existing XML contract. Creating the files again generates new UUIDs, so finish one experiment before regenerating them.

### 3. Submit a valid message twice

Run this exact command twice:

```bash
curl -sS -w '\nHTTP %{http_code}\n' \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/xml' \
  --data-binary @artifacts/xml-practice/valid.xml \
  http://127.0.0.1:8000/telemetry/xml
```

Expect HTTP 200 both times: first `inserted:true`, then `inserted:false`. Only one new event is stored. This is idempotency: retrying the same accepted message does not duplicate its effects.

### 4. Test the other files

Repeat the curl command, changing only the filename:

| File | Expected result | What to verify in SQL |
| --- | --- | --- |
| `conflict.xml` | HTTP 409 | Same UUID with changed content is rejected; no extra event |
| `late.xml` | HTTP 200, inserted true | History grows; current position remains the newer valid message |
| `invalid.xml` | HTTP 422 | Battery 101 is rejected; no event or location inserted |
| `unknown.xml` | HTTP 422 | Equipment not in the asset registry is rejected |

After valid and late submissions:

```sql
SELECT e.message_id, e.observed_at, e.status,
       ST_X(l.position::geometry) AS longitude,
       ST_Y(l.position::geometry) AS latitude
FROM tracking.telemetry_events e
JOIN tracking.assets a USING (asset_id)
JOIN tracking.locations l USING (message_id)
WHERE a.equipment_id = 'SIM-ASSET-001'
ORDER BY e.observed_at DESC, e.message_id DESC
LIMIT 5;

SELECT equipment_id, message_id, observed_at, ST_AsText(geom)
FROM tracking.current_assets
WHERE equipment_id = 'SIM-ASSET-001';
```

The current pointer should reference the valid message, assuming no other writer or pre-existing future observation superseded it. The late row should still be present in history. With only this session's writers, the five files add two events total.

Read `src/gis_dba/telemetry.py`, the API's XML handler, and `tracking.ingest` in migration 001. Follow the transaction from event insertion to location insertion to current-pointer update. Note where Python rejects malformed input and where PostgreSQL independently enforces constraints.

### 5. Run the existing tests as supporting evidence

**Terminal:**

```bash
pytest -m 'not integration'
RUN_DB_TESTS=1 pytest
```

Run one integration suite at a time against this development database. The initial build has 28 tests, including concurrent duplicate submissions, late arrivals, rollback after invalid writes, and role restrictions.

**Checkpoint:** Explain what happens if the server commits but the client loses the response. Why must the client retry the same UUID? Why would “last received wins” produce an incorrect current position?

## Session 5 — Practice the GIS-specific database work

**Goal:** Understand coordinate order, SRIDs, spatial types, spatial predicates, and map data quality.

### 1. Inspect stored coordinates

In administrator psql:

```sql
SELECT equipment_id, ST_SRID(geom) AS srid,
       ST_X(geom) AS longitude, ST_Y(geom) AS latitude
FROM tracking.current_assets
ORDER BY equipment_id;

SELECT name, ST_IsValid(boundary), ST_SRID(boundary)
FROM tracking.operational_areas;
```

Expect SRID 4326 and valid polygons. The fictional grid is near longitude -140 and latitude -40. X is longitude; Y is latitude. Swapping values here would put -140 in the latitude position, outside its valid range.

`ST_SetSRID` labels coordinates with their reference system; it does not convert coordinates from another system. `ST_Transform` performs a conversion when the source SRID is correctly known. This project receives WGS 84 coordinates directly, so labeling the generated points as 4326 is appropriate.

### 2. Find assets within five kilometers of a point

```sql
WITH origin AS (
  SELECT ST_SetSRID(ST_MakePoint(-140, -40), 4326)::geography AS point
)
SELECT a.equipment_id,
       round(ST_Distance(a.geom::geography, o.point)::numeric, 1) AS meters
FROM tracking.current_assets a
CROSS JOIN origin o
WHERE ST_DWithin(a.geom::geography, o.point, 5000)
ORDER BY meters;
```

Change 5000 to 15000. Results may be empty for the smaller radius; that is valid. The larger radius should include at least as many rows if the data is unchanged. Explain why the query casts geometry to geography: distance is expressed in meters rather than degrees.

### 3. Perform a spatial join

```sql
SELECT equipment_id, area_name
FROM tracking.assets_in_areas
ORDER BY equipment_id, area_name;
```

Then test a point exactly on the shared edge:

```sql
SELECT name,
       ST_Covers(boundary, ST_SetSRID(ST_MakePoint(-140, -40), 4326)) AS covers,
       ST_Contains(boundary, ST_SetSRID(ST_MakePoint(-140, -40), 4326)) AS contains
FROM tracking.operational_areas
ORDER BY name;
```

Expect the shared-edge point to be covered by both seeded polygons but not contained in their interiors. Therefore area-membership rows do not always equal a count of distinct assets. Choose the boundary rule deliberately when reporting GIS results.

### 4. Compare the API with SQL

**Terminal:**

```bash
curl -sS -H "X-API-Key: $API_KEY" \
  'http://127.0.0.1:8000/assets/nearby?longitude=-140&latitude=-40&radius_m=5000' \
  | python -m json.tool
python scripts/export_gis.py
```

The API returns GeoJSON. Export creates `artifacts/gis/assets.geojson` and `areas.geojson`. Open them in VS Code to inspect the coordinates and feature properties. These exports are snapshots; exporting again refreshes them.

If QGIS is available, follow [the connection instructions](gis.md), add `tracking.current_assets` and `tracking.operational_areas`, and style assets by status. Use `asset_id` as the current-assets feature identifier. Enable layer refresh, run the simulator briefly, and compare the map with a SQL result. QGIS was not installed in the initial build, so SQL and GeoJSON inspection let you finish this session without installing it.

**Checkpoint:** Diagnose three hypothetical problems: points appear in the wrong hemisphere; a distance query treats 5000 as degrees; an asset is counted twice along an area boundary. Identify the query or metadata you would inspect first.

## Session 6 — Demonstrate least privilege

**Goal:** Prove permissions through successful and denied actions.

### 1. Inspect permissions as administrator

```sql
\du
\dp tracking.*
\df+ tracking.ingest
```

Compare what you see with `roles()` in `src/gis_dba/admin.py`.

| Role | Intended work |
| --- | --- |
| `postgres` | Lab administration, migrations, backups, and restores |
| `gis_reader` | Read curated GIS views and operational areas |
| `gis_ingest` | Execute the transactional ingestion function |
| `gis_monitor` | Read current GIS views and PostgreSQL monitoring statistics |

The API key controls access to API endpoints. Database roles separately control what each database connection can do.

### 2. Connect as the reader

**New prepared terminal:**

```bash
psql "$DATABASE_URL" -X
```

**SQL / psql:**

```sql
SELECT current_user;
SELECT equipment_id, status FROM tracking.current_assets LIMIT 5;
UPDATE tracking.assets SET description = 'Not permitted'
WHERE equipment_id = 'SIM-ASSET-001';
SELECT * FROM tracking.telemetry_events LIMIT 1;
```

The view read should succeed. Both base-table actions should fail with permission errors. These statements run individually in psql's default autocommit mode, so each denied statement does not leave a manually opened transaction behind. Exit with `\q`.

### 3. Connect as the ingestion role

```bash
psql "$INGEST_DATABASE_URL" -X
```

```sql
SELECT current_user;
SELECT * FROM tracking.assets LIMIT 1;
```

Expect a permission error for the table read. Yet XML ingestion through the API succeeds because that role may execute `tracking.ingest`.

Read the function's `SECURITY DEFINER` declaration and fixed `search_path`. It performs a narrow operation using its owner's privileges. That makes its validation, qualified table references, and protection against writable schemas particularly important.

**Checkpoint:** Explain why giving the API administrator credentials would defeat these controls. Why should monitoring credentials also be protected even though they are not application writers? The monitoring role can see cluster statistics and other sessions' query details through `pg_monitor`.

## Session 7 — Measure performance before tuning

**Goal:** Read actual execution plans and justify an index with evidence.

### 1. Start with 100,000 synthetic rows

**Prepared terminal:**

```bash
python scripts/benchmark.py --rows 100000 --output artifacts/practice-100k.json
```

Read `scripts/benchmark.py` before increasing the size. Each run recreates **only** `lab.benchmark_telemetry`. It does not drop tracking tables or their indexes. The table is independent synthetic benchmark history, not XML simulator traffic.

### 2. Repeat with one million rows

```bash
python scripts/benchmark.py --rows 1000000 --output artifacts/practice-1m.json
```

Each output file preserves before/after plans. The database table itself contains only the most recent run. The script warms each query, collects three measured plans per phase, and records index build time and relation size.

Summarize the measured results:

```bash
python - <<'PY'
import json
from pathlib import Path
from statistics import median

for filename in ('practice-100k.json', 'practice-1m.json'):
    report = json.loads((Path('artifacts') / filename).read_text())
    print(filename, 'rows:', report['rows'])
    for phase in ('before', 'after'):
        for name in ('spatial', 'asset_time'):
            plans = report['phases'][phase][name]
            print(phase, name, 'median ms:', median(p['Execution Time'] for p in plans))
        print(phase, 'bytes:', report['phases'][phase]['relation_bytes'])
    print('index build seconds:', report['index_build_seconds'])
PY
```

### 3. Read the plans, not just the timings

Open the JSON in VS Code. Compare the same query across phases. Locate:

- Scan nodes: sequential, index, bitmap, or parallel scans where chosen.
- Estimated `Plan Rows` versus `Actual Rows`, accounting for loops and aggregation nodes.
- Rows removed by filters and any sort nodes.
- Shared hit/read buffers and total execution time.

A PostgreSQL planner `cost` is an estimate in planner cost units, not elapsed milliseconds. Buffer hits are cached page accesses, not proof that a query needed no work. A small dataset or broad search can legitimately favor a sequential scan.

### 4. Examine selectivity yourself

In administrator psql after the benchmark:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM lab.benchmark_telemetry
WHERE ST_DWithin(position,
  ST_SetSRID(ST_MakePoint(-140, -40), 4326)::geography, 1000);
```

Repeat with radius 100000 and compare the plan. The larger radius returns a much broader selection. Do not force the planner to use an index.

**Checkpoint:** Write a short tuning recommendation containing query, row count, before/after medians, plan evidence, index storage cost, and one limitation. Explain why geography GiST helps proximity and an `(asset_id, observed_at DESC)` B-tree helps asset/time history. Include the added costs to future writes. Your results need not match the native timings in `validation.md`, especially under Docker emulation.

## Session 8 — Monitor activity, observe blocking, and maintain statistics

**Goal:** Distinguish a slow query, a blocked query, stale data, and a down server.

### 1. Establish normal behavior

**Prepared terminal:**

```bash
gis-admin health
psql "$MONITOR_DATABASE_URL" -X -f sql/monitor.sql
./scripts/compose logs --tail=50 db api
```

Record connections, waiting locks, newest observation time, and vacuum/analyze information. A healthy database with an old observation time may simply have a stopped simulator. PostgreSQL statistics are estimates or accumulated counters; check their reset times and allow for reporting delay.

### 2. Hold a row lock in Terminal A

Open an administrator psql connection:

```sql
BEGIN;
SELECT asset_id FROM tracking.assets
WHERE equipment_id = 'SIM-ASSET-001'
FOR UPDATE;
```

Leave the transaction open. No values have changed, but the row is locked until the transaction ends.

### 3. Wait for the same lock in Terminal B

Open another administrator psql connection:

```sql
SET lock_timeout = '30s';
BEGIN;
SELECT asset_id FROM tracking.assets
WHERE equipment_id = 'SIM-ASSET-001'
FOR UPDATE;
```

This query waits. Before 30 seconds elapse, inspect it in Terminal C connected with `MONITOR_DATABASE_URL`:

```sql
SELECT pid, usename, state, wait_event_type, wait_event,
       pg_blocking_pids(pid) AS blockers,
       now() - xact_start AS transaction_age
FROM pg_stat_activity
WHERE datname = current_database()
ORDER BY xact_start;
```

Expect a waiting session with a nonempty blocker list. Terminal A may show `idle in transaction`. If you miss the window, roll back both sessions and repeat; the timeout is intentional.

### 4. Release and clean up

In Terminal A:

```sql
ROLLBACK;
```

If Terminal B was still waiting, its SELECT now finishes. If it timed out, its transaction is failed. In either case, run in Terminal B:

```sql
ROLLBACK;
RESET lock_timeout;
```

Verify that both sessions are out of their transactions and that the wait has cleared. Do not leave the lock demonstration open when you resume telemetry.

### 5. Practice maintenance on the benchmark table

In an administrator psql session, outside any explicit transaction:

```sql
SELECT relname, n_live_tup, n_dead_tup, last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables
WHERE schemaname IN ('tracking', 'lab')
ORDER BY schemaname, relname;

VACUUM (ANALYZE, VERBOSE) lab.benchmark_telemetry;
```

This requires Session 7's table. `VACUUM` makes space occupied by removable dead tuples reusable; it does not generally shrink the operating-system file. `ANALYZE` updates planner statistics. A fresh, insert-only table may have few dead tuples, so this exercise may change little. Do not manufacture a large result or routinely substitute `VACUUM FULL`, which rewrites the table and needs stronger locking.

**Checkpoint:** Explain which session was the cause of the wait and why restarting everything would hide the evidence. What would you check before canceling a query or terminating a backend in a shared system?

## Session 9 — Prove that a backup can be recovered

**Goal:** Recover to a separate database, validate its contents, and understand the recovery boundary.

### 1. Verify the target and client tools

Use a prepared terminal with no overrides pointing to a staging or restored database:

```bash
psql "$ADMIN_DATABASE_URL" -X -c 'SELECT current_database(), current_user;'
pg_dump --version
pg_restore --version
```

Expect source database `gis_lab`. The PATH from Session 1 selects the installed PostgreSQL 17 tools.

### 2. Create a uniquely named backup

Keep this terminal open through the exercise:

```bash
LAB_RUN=$(date -u +%Y%m%d%H%M%S)
ARCHIVE="backups/practice_${LAB_RUN}.dump"
RESTORE_TARGET="gis_restore_practice_${LAB_RUN}"
time gis-backup backup "$ARCHIVE"
```

The script produces an archive and a `.dump.json` manifest. Keep them together. The manifest is captured from the same exported database snapshot used by pg_dump. The dump covers this database, including the benchmark table if it exists, so the million-row exercise increases backup size and time.

### 3. Restore to a new database

```bash
time gis-backup restore "$ARCHIVE" --target "$RESTORE_TARGET"
```

Expect `RECOVERY VERIFIED`. An existing target name fails rather than being overwritten. For another attempt, choose a new name. On failure, inspect the error and preserved target rather than deleting the source.

The validator compares row counts and row fingerprints for tracking tables, migration hashes, and location completeness, and queries the GIS view. Its fingerprint sums are practical lab checks, not a cryptographic proof of equality for every table in the database.

### 4. Inspect the recovered database yourself

```bash
export RESTORE_TARGET
python - <<'PY'
import os
import psycopg
from psycopg.conninfo import make_conninfo
from gis_dba.config import database_url

dsn = make_conninfo(database_url('ADMIN_DATABASE_URL'), dbname=os.environ['RESTORE_TARGET'])
with psycopg.connect(dsn) as conn:
    print('Recovered database:', conn.execute('SELECT current_database()').fetchone()[0])
    print('Events:', conn.execute('SELECT count(*) FROM tracking.telemetry_events').fetchone()[0])
    print('Current assets:', conn.execute('SELECT count(*) FROM tracking.current_assets').fetchone()[0])
    print('Sample:', conn.execute(
        'SELECT equipment_id,status FROM tracking.current_assets ORDER BY equipment_id LIMIT 3'
    ).fetchall())
PY
```

No password is printed, and the source connection setting is not changed.

### 5. Explain the recovery boundary

Read the backup manifest's `created_at` and record the measured backup and restore durations. The database snapshot is established before the dump finishes; `created_at` is metadata written afterward, not an exact timestamp of the last included event.

Answer: If new events arrive after the backup snapshot, will restoring this archive recover them? No. A successful dump does not provide automatic recovery of later changes. Backups here omit ownership/ACLs and cluster role definitions; the restored target is admin-only until privileges are explicitly provisioned. You have demonstrated logical snapshot recovery, not automatic failover or point-in-time recovery.

Define an example **RPO**, the amount of recent data you could tolerate losing, and **RTO**, the acceptable time to restore useful service. Restore command duration is only part of RTO; inspection, permissions, application reconnection, and GIS validation also take time.

**Checkpoint:** Write a recovery report naming source, archive/manifest, target, validation results, elapsed time, and limitations. “The file exists” is not sufficient evidence of recoverability.

## Session 10 — Rehearse a database change safely

**Goal:** Separate deployment from experimentation and understand compatibility and rollback.

### 1. Read the existing change

Open:

- `sql/migrations/001_core.sql`
- `sql/migrations/002_asset_description.sql`
- `sql/rollback/002_asset_description.sql`
- `scripts/rehearse_migration.py`

Migration 002 adds nullable `assets.description`. Old inserts can omit it. The existing views explicitly list their fields, so they do not automatically expose the new column. The rollback drops that column and its values and removes the corresponding migration-ledger entry.

### 2. Predict the outcome, then run the rehearsal

**Prepared terminal:**

```bash
STAGING_RUN=$(date -u +%Y%m%d%H%M%S)
STAGING_DB="gis_restore_training_${STAGING_RUN}"
python scripts/rehearse_migration.py --target "$STAGING_DB"
```

The script creates a **new** database on the selected server. It applies the baseline, seeds synthetic identities, adds the description column, writes sample descriptions, rolls back the change, reapplies it, and verifies a repeated migration run is a no-op. Expect `MIGRATION REHEARSAL VERIFIED`.

This script does not downgrade the main `gis_lab` database. It checks baseline asset queries and the migration workflow; it is not a replacement for running application and GIS compatibility checks against staging.

### 3. Inspect the migration ledger on your main database

In the main administrator psql connection:

```sql
SELECT version, sha256, applied_at
FROM public.schema_migrations
ORDER BY version;
```

Read `migrate()` in `src/gis_dba/admin.py`. Find the checksum comparison, advisory lock, transaction, and DDL lock timeout. Explain the problem each addresses.

Do not edit migration 001 or 002 to make an already-initialized database behave differently. The initial project detects changes to applied files. A real future change would get a new migration, but writing that new feature is outside this workbook.

### 4. Write a change plan

Use this existing nullable-column change as your example. Your plan should identify the affected table and clients, a verified backup, staging checks, lock considerations, deployment command, post-deployment checks, and a rollback/forward-fix decision. Explain why rollback requires exporting descriptions first if their values matter.

**Checkpoint:** Explain why an additive schema change can still affect applications and why a successful migration command alone does not prove a GIS client works afterward. ArcGIS-specific behavior remains an optional evaluation in [GIS notes](gis.md), not a claim of tested enterprise-geodatabase support.

## Session 11 — Run a small incident drill

**Goal:** Diagnose availability independently at the API and database layers.

Stop the simulator and finish all lock experiments first. This drill temporarily stops only the dedicated Docker lab database.

### 1. Establish the healthy responses

**Prepared terminal:**

```bash
curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/health/live
curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/health/ready
```

Both should return HTTP 200.

### 2. Stop the database while leaving the API running

```bash
./scripts/compose stop db
curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/health/live
curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/health/ready
```

Expect liveness 200 and readiness 503. The API process exists but cannot serve database-backed work. Its Docker health status may take several check intervals to reflect this.

Submit the same `valid.xml` from Session 4 while the database is down. Expect HTTP 503. Save the message; do not generate a replacement UUID just because a request failed.

### 3. Recover service

```bash
./scripts/compose start db
./scripts/compose ps
```

Wait for the database to become healthy, then repeat readiness until it returns 200. Replay `valid.xml`: because it was accepted earlier, expect `inserted:false`. Finally:

```bash
gis-admin health
gis-simulate --cycles 1
./scripts/compose logs --tail=50 db api
```

**Checkpoint:** Write a short incident note: symptom, affected component, evidence, recovery action, verification, and whether any accepted data was lost. Explain why API liveness alone was insufficient.

## Session 12 — Repeat selected work on native PostgreSQL

**Goal:** Recognize which skills transfer across deployment methods.

Use a fresh terminal rather than carrying old overrides into the comparison. Prepare it as in Session 1. Check the project-local native cluster:

```bash
python scripts/native_db.py status
```

If it is stopped, start it with `python scripts/native_db.py start`. If startup fails, inspect `.pgdata/server.log`; do not initialize a second cluster over the data directory.

Then:

```bash
python scripts/use_database.py native
set -a
source .env
set +a
psql "$ADMIN_DATABASE_URL" -X -c 'SELECT current_database(),version();'
gis-admin health
```

Repeat schema inspection, a spatial query, restricted-role reads, and a uniquely named backup/recovery exercise. The native database has its own history and practice databases. A source-level change or copied `.env` does not synchronize data between servers.

**API trap:** The still-running Docker API on port 8000 continues using Docker even after this host switch. To generate native telemetry, run a host API in another prepared native terminal:

```bash
uvicorn gis_dba.api:app --host 127.0.0.1 --port 8001
```

Then, from the native client terminal:

```bash
gis-simulate --url http://127.0.0.1:8001 --cycles 1
```

Stop the host API with Ctrl-C afterward. For the first learning pass, a second million-row benchmark is optional. If you compare native and Docker timings, hold data size and query parameters constant and document the different versions and emulation overhead.

Return host commands to Docker when finished:

```bash
python scripts/use_database.py docker
set -a
source .env
set +a
```

Reload `.env` in other reused terminals too. This native Mac installation is useful database practice; Ubuntu service management remains a separate infrastructure exercise described in setup, not an environment installed by this workbook.

## A repeatable practice routine

At the start of a session, identify the target server/database/role, check health and data freshness, and review recent logs. Choose one hypothesis and save a baseline before making a change. End by checking integrity, closing transactions, stopping temporary simulators, and recording what you learned.

For a weekly capstone, demonstrate these tasks without following the commands line by line:

- Explain the asset-to-event-to-location relationships and prove one invalid write is rejected.
- Accept a message, replay it safely, and show why a late update does not replace the latest state.
- Find nearby assets in meters and explain boundary behavior in an area join.
- Demonstrate that reader credentials cannot modify base tables.
- Justify a performance change with a measured plan rather than an assumed speedup.
- Identify a blocker, release it cleanly, and distinguish stale telemetry from an outage.
- Recover a backup to a new target and explain what the validation does and does not prove.
- Explain a schema deployment and rollback using the existing staging rehearsal.

Your deliverables are a schema sketch, query examples, a tuning report, a recovery report, a change plan, and an incident note. Together they show practical DBA reasoning beyond simply starting the application.

## Troubleshooting reference

| Symptom | First checks |
| --- | --- |
| `psql` or `pg_dump` not found | Restore the PostgreSQL 17 PATH from Session 1 |
| Host commands reach unexpected data | Source `.env` again; verify `\conninfo`; compare 5432 with 55432 |
| API still shows Docker data in native mode | Port 8000 is Docker; native host API must use its own configuration and port 8001 |
| HTTP 401 | Load the matching `.env`; send `X-API-Key`; do not regenerate credentials blindly |
| HTTP 422 | Check XML fields, equipment registry, coordinates, status, battery, and timestamp timezone |
| HTTP 409 | An existing message UUID was reused with changed content |
| HTTP 503 or readiness failure | Check service state, connectivity, logs, schema availability, and locks |
| `current transaction is aborted` | End the failed transaction with `ROLLBACK`, then diagnose the original error |
| Map has fewer assets than the registry | Assets need an accepted position before appearing in the current-assets view |
| Maintenance fails inside a transaction | Run VACUUM outside an explicit BEGIN/COMMIT block |
| Restore or rehearsal target already exists | Pick a new `gis_restore_...` name; existing targets are intentionally preserved |
| Migration checksum mismatch | Check source history; do not overwrite an applied migration to bypass the check |

To stop work while preserving data:

```bash
./scripts/compose stop
python scripts/native_db.py stop
colima stop
```

Stop only components you started or are finished using. Avoid `./scripts/compose down -v`: it deletes the Docker database volume and is not a learning-session cleanup step. Backups, restored databases, and the benchmark table remain for inspection; deliberate retention and cleanup can be planned separately.
