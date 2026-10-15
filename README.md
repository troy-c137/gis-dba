# Tactical Geospatial Asset & Telemetry Database

A hands-on **entirely synthetic** PostgreSQL 17/PostGIS DBA lab: fictional equipment, invented locations, XML ingestion, GeoJSON API, spatial queries, performance engineering, least privilege, monitoring, and verified logical recovery.

Python 3.11+ · FastAPI · psycopg 3 · PostgreSQL 17 · PostGIS · Docker Compose · QGIS

## Start here

[Local/Docker setup and VS Code workflow](docs/setup.md) covers native macOS, Ubuntu, and Docker. Native PostgreSQL uses **5432**; Docker uses **55432**, so both databases can coexist. One set of migrations serves both. The [validation record](docs/validation.md) lists actual tests, recovery results, and measured timings. See [architecture](docs/architecture.md), [six DBA exercises](docs/dba-labs.md), and [QGIS / ArcGIS guidance](docs/gis.md).

Once Python dependencies are installed and a Docker engine with Compose is running:

```bash
source .venv/bin/activate
gis-admin env                    # once; generates private .env credentials
./scripts/compose up -d db
gis-admin migrate
gis-admin roles
gis-admin seed
./scripts/compose up -d --build api
gis-simulate --cycles 5
gis-admin health
```

API: [interactive documentation](http://127.0.0.1:8000/docs). All data endpoints require `X-API-Key` from `.env`. [Example XML](examples/telemetry.xml) demonstrates the strict input contract. Exact retries are idempotent; out-of-order messages preserve history and keep the newest current position.

## Project map

| Path | Purpose |
| --- | --- |
| `sql/migrations/` | Checksummed schema, spatial indexes/views, transactional ingestion function |
| `src/gis_dba/` | API, XML validation, simulator, admin, backup/verified recovery |
| `scripts/` | Native cluster lifecycle, environment switch, bulk performance lab |
| `sql/monitor.sql`, `sql/spatial_queries.sql` | Monitoring and spatial query exercises |
| `tests/`, `.github/workflows/test.yml` | Validation, API, transactional/PostGIS integration checks |
| `.vscode/` | Python interpreter, debugger, and extension recommendations |

```bash
pytest -m 'not integration'       # no database needed
RUN_DB_TESTS=1 pytest             # initialized, seeded development database required
python scripts/benchmark.py --rows 1000000
# PostgreSQL 17 client tools must be on PATH:
gis-backup backup backups/first.dump
gis-backup restore backups/first.dump --target gis_restore_first
```

The recovery exercise checks a new database against a manifest from the same snapshot as the dump. Performance runs save real execution plans and timings under `artifacts/`; no speedup is assumed. GitHub Actions runs isolated database tests.

All sample coordinates describe an invented training grid in the South Pacific. No operational information, real unit movements, or sensitive coordinates are used. This is a local educational system; [architecture limitations](docs/architecture.md) describe its boundaries.
