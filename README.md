# GIS DBA

A geospatial asset and telemetry database built with PostgreSQL 17, PostGIS, and FastAPI. It combines XML ingestion, GeoJSON endpoints, spatial queries, database administration, and verified logical backups in a reproducible local environment.

All sample assets and telemetry are synthetic. Coordinates represent a fictional grid in the South Pacific.

## Features

- Strict XML validation with a 16 KiB request limit and API key authentication.
- Transactional ingestion with idempotent retries, conflict detection, and ordered current-state updates.
- GeoJSON endpoints for current assets, proximity searches, and polygon membership.
- Separate database roles for reads, ingestion, and monitoring.
- Checksummed migrations, a rollback script, and an isolated migration rehearsal.
- Snapshot-consistent backup manifests and recovery verification in a new database.
- Synthetic telemetry generation, query benchmarks, and QGIS integration.

## Quick start

Install Python 3.11+ and a Docker engine with Compose. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e .

gis-admin env
./scripts/compose up -d --wait db
gis-admin migrate
gis-admin roles
gis-admin seed
./scripts/compose up -d --build --wait api

gis-simulate --cycles 5
gis-admin health
```

`gis-admin env` generates random credentials in a private `.env` file and refuses to overwrite an existing file. The example configuration contains placeholders; generate credentials before starting services.

The API listens on [localhost:8000](http://127.0.0.1:8000/docs), and Docker PostgreSQL uses `127.0.0.1:55432`. Data endpoints require the `X-API-Key` header from `.env`. See the [setup guide](docs/setup.md) for request examples, native PostgreSQL setup, and service lifecycle commands.

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /telemetry/xml` | Validate and ingest a telemetry event |
| `GET /assets` | Current asset positions as GeoJSON |
| `GET /assets/nearby` | Search by longitude, latitude, and radius in meters |
| `GET /areas` | Operational area polygons as GeoJSON |
| `GET /areas/{area_id}/assets` | Assets covered by an area, including its boundary |
| `GET /health/live`, `GET /health/ready` | Liveness and database readiness |

The [example XML](examples/telemetry.xml) defines the input shape. Exact retries return `inserted=false`; reusing a message ID with different content returns HTTP 409. Out-of-order events remain in history while the newest observation determines current state.

## Development and validation

```bash
ruff check .
pytest -m 'not integration'

# Requires an initialized development database with roles and seed data:
RUN_DB_TESTS=1 pytest

# Records execution plans and timings under artifacts/:
python scripts/benchmark.py --rows 100000
```

GitHub Actions runs linting and the test suite against an isolated PostGIS service. Integration tests create and remove their own test assets in the configured database.

For verified backups, install PostgreSQL 17 client tools and add them to `PATH`:

```bash
gis-backup backup backups/first.dump
gis-backup restore backups/first.dump --target gis_restore_first
```

Keep each archive with its `.dump.json` manifest. Recovery creates a new database and verifies its row fingerprints and migration checksums against the backup snapshot. The target must be a new name beginning with `gis_restore_`.

## Repository layout

| Path | Purpose |
| --- | --- |
| `src/gis_dba/` | API, XML validation, simulator, administration, and recovery |
| `sql/migrations/`, `sql/rollback/` | Versioned schema changes and rollback |
| `sql/monitor.sql`, `sql/spatial_queries.sql` | Monitoring and spatial query examples |
| `scripts/` | Native cluster tools, GIS export, benchmarks, and migration rehearsal |
| `tests/` | XML, API, and PostGIS integration tests |
| `docs/` | [Setup](docs/setup.md), [architecture](docs/architecture.md), and [GIS integration](docs/gis.md) |

## Configuration and scope

Credentials, database files, backups, generated reports, GIS connection projects, and personal working files are excluded from Git and Docker build contexts. Keep secrets in `.env` or environment variables; use `.env.example` as the public configuration reference. Review generated exports before sharing them.

This is a local demonstration with loopback-bound services. Production deployment requires additional authentication, TLS, availability, and recovery controls; see the [architecture and limitations](docs/architecture.md). Logical backups recover the captured snapshot; point-in-time recovery is not configured.
