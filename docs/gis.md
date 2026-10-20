# QGIS and ArcGIS integration

## QGIS map

1. Install QGIS using the [official downloads](https://qgis.org/download/).
2. In Browser → PostgreSQL → New Connection, use host `127.0.0.1`, port `5432` (native) or `55432` (Docker), database `gis_lab`, user `gis_reader`, and its generated password from `.env`. Avoid saving credentials in a committed QGIS project.
3. Add `tracking.current_assets` with geometry column `geom`, CRS EPSG:4326, unique key `asset_id`. Enable geometryless/view listing if necessary; QGIS may require manually choosing the unique identifier on a view. `assets_in_areas` repeats assets across overlaps and is not suitable for `asset_id` as a globally unique feature key.
4. Add `tracking.operational_areas`, geometry `boundary`, unique key `area_id`.
5. Categorize asset symbols by `status`, label with `equipment_id`, style area fills with transparency, and zoom to the layer. The invented grid is around **140° W, 40° S**. A basemap is optional and requires network access.
6. Enable periodic layer refresh (e.g. 2–5 seconds in layer rendering options) and run `gis-simulate`. Current assets appear only after the first telemetry update. QGIS is read-only with this role.

For a credential-free local snapshot, run `python scripts/export_gis.py` and drag `artifacts/gis/assets.geojson` and `artifacts/gis/areas.geojson` into QGIS. The helper uses the reader role and a consistent read snapshot.

Alternatively, call `/assets` with the API key and save the GeoJSON locally, then open it in QGIS. It is a snapshot and does not auto-update like a database layer. The API also exposes `/areas`, `/assets/nearby`, and `/areas/{area_id}/assets`.

## ArcGIS compatibility evaluation

ArcGIS Pro/Enterprise can connect to supported PostgreSQL databases and to enterprise geodatabases. Compatibility is **release-specific**, including database minor version, PostGIS version, OS, and client/server release; check the [Esri PostgreSQL requirements matrix](https://doc.esri.com/en/arcgis-enterprise/latest/plan/database-requirements-postgresql.html) for the version actually installed. Verify the exact PostgreSQL/PostGIS/client combination before connecting.

A direct PostGIS connection does not turn the database into an Esri enterprise geodatabase. Evaluate a read-only query layer over `tracking.current_assets`, selecting a unique non-null asset identifier, one consistent geometry type, and SRID 4326. If a particular ArcGIS client requires a narrower object-ID type, validate the current asset ID range and expose a dedicated compatibility query rather than narrowing the base identity silently. Validate field types, timestamp interpretation, row identifiers, and refresh behavior with your installed ArcGIS version. Retain `gis_reader` permissions.

An Esri-managed enterprise geodatabase adds geodatabase system tables, metadata, versioning/editing workflows, and ArcGIS-specific administration and licensing requirements. Enabling one is a separate controlled operation; this repository does not create SDE metadata or assume a PostGIS table supports all geodatabase behaviors. Do not modify geodatabase system tables with SQL. Verify supported editing/service publication workflows separately before granting writes. Keep a separate test database for any enterprise-geodatabase experiment and document its licensing, extensions/spatial type, database/client versions, and recovery requirements.

ArcGIS software is not bundled, and ArcGIS compatibility is not covered by this repository’s automated tests.
