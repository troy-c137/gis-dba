CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA tracking;
REVOKE ALL ON SCHEMA tracking FROM PUBLIC;
CREATE TABLE tracking.units (
    unit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE CHECK (code ~ '^SIM-[A-Z0-9-]+$'),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120)
);
CREATE TABLE tracking.assets (
    asset_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    equipment_id text NOT NULL UNIQUE CHECK (equipment_id ~ '^SIM-[A-Z0-9-]+$'),
    unit_id bigint NOT NULL REFERENCES tracking.units ON DELETE RESTRICT,
    asset_type text NOT NULL CHECK (asset_type IN ('relay', 'sensor', 'terminal')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX assets_unit_idx ON tracking.assets(unit_id);
CREATE TABLE tracking.telemetry_events (
    message_id uuid PRIMARY KEY,
    asset_id bigint NOT NULL REFERENCES tracking.assets ON DELETE RESTRICT,
    observed_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    status text NOT NULL CHECK (status IN ('online', 'degraded', 'offline')),
    battery_pct smallint NOT NULL CHECK (battery_pct BETWEEN 0 AND 100),
    source text NOT NULL CHECK (length(source) BETWEEN 1 AND 80),
    UNIQUE (asset_id, message_id)
);
CREATE INDEX events_asset_time_idx ON tracking.telemetry_events(asset_id, observed_at DESC);
CREATE INDEX events_time_idx ON tracking.telemetry_events(observed_at DESC);
CREATE TABLE tracking.locations (
    message_id uuid PRIMARY KEY REFERENCES tracking.telemetry_events ON DELETE CASCADE,
    position geography(Point, 4326) NOT NULL,
    CHECK (ST_X(position::geometry) BETWEEN -180 AND 180),
    CHECK (ST_Y(position::geometry) BETWEEN -90 AND 90)
);
CREATE INDEX locations_position_gix ON tracking.locations USING gist(position);
CREATE TABLE tracking.current_state (
    asset_id bigint PRIMARY KEY REFERENCES tracking.assets ON DELETE RESTRICT,
    message_id uuid NOT NULL UNIQUE,
    FOREIGN KEY (asset_id, message_id)
        REFERENCES tracking.telemetry_events(asset_id, message_id) ON DELETE RESTRICT
);
CREATE TABLE tracking.operational_areas (
    area_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL UNIQUE,
    boundary geometry(Polygon, 4326) NOT NULL CHECK (ST_IsValid(boundary))
);
CREATE INDEX areas_boundary_gix ON tracking.operational_areas USING gist(boundary);
CREATE VIEW tracking.current_assets AS
SELECT a.asset_id, a.equipment_id, a.asset_type, u.code AS unit_code,
       e.message_id, e.observed_at, e.status, e.battery_pct,
       l.position::geometry(Point,4326) AS geom
FROM tracking.assets a
JOIN tracking.units u USING (unit_id)
JOIN tracking.current_state c USING (asset_id)
JOIN tracking.telemetry_events e ON e.message_id = c.message_id
JOIN tracking.locations l ON l.message_id = e.message_id;
CREATE VIEW tracking.assets_in_areas AS
SELECT a.*, p.area_id, p.name AS area_name
FROM tracking.current_assets a
JOIN tracking.operational_areas p ON ST_Covers(p.boundary, a.geom);

-- Narrow write interface. The owner is the migration administrator; callers cannot write tables.
CREATE FUNCTION tracking.ingest(
    p_message uuid, p_equipment text, p_observed timestamptz,
    p_lon double precision, p_lat double precision,
    p_status text, p_battery smallint, p_source text
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, tracking AS $$
DECLARE
    v_asset bigint;
    v_old tracking.telemetry_events%ROWTYPE;
    v_position public.geography;
BEGIN
    IF p_message IS NULL OR p_equipment IS NULL OR p_observed IS NULL
       OR p_lon IS NULL OR p_lat IS NULL OR p_status IS NULL
       OR p_battery IS NULL OR p_source IS NULL
       OR NOT (p_lon BETWEEN -180 AND 180) OR NOT (p_lat BETWEEN -90 AND 90)
       OR p_observed > clock_timestamp() + interval '5 minutes' THEN
        RAISE EXCEPTION 'Invalid telemetry values' USING ERRCODE = '22023';
    END IF;
    -- Per-asset lock serializes updates and prevents a stale current-state decision.
    SELECT asset_id INTO v_asset FROM tracking.assets
        WHERE equipment_id = p_equipment FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown synthetic equipment ID' USING ERRCODE = '23503';
    END IF;
    v_position := public.ST_SetSRID(public.ST_MakePoint(p_lon, p_lat),4326)::public.geography;
    INSERT INTO tracking.telemetry_events(message_id, asset_id, observed_at, status, battery_pct, source)
        VALUES(p_message, v_asset, p_observed, p_status, p_battery, p_source)
        ON CONFLICT(message_id) DO NOTHING;
    IF NOT FOUND THEN
        SELECT * INTO v_old FROM tracking.telemetry_events WHERE message_id = p_message;
        IF v_old.asset_id IS DISTINCT FROM v_asset
           OR v_old.observed_at IS DISTINCT FROM p_observed
           OR v_old.status IS DISTINCT FROM p_status
           OR v_old.battery_pct IS DISTINCT FROM p_battery
           OR v_old.source IS DISTINCT FROM p_source
           OR NOT EXISTS (SELECT 1 FROM tracking.locations
                WHERE message_id = p_message AND public.ST_Equals(position::public.geometry,
                                                               v_position::public.geometry)) THEN
            RAISE EXCEPTION 'Message ID reused with different content' USING ERRCODE = '23505';
        END IF;
        RETURN false;
    END IF;
    INSERT INTO tracking.locations VALUES(p_message, v_position);
    INSERT INTO tracking.current_state VALUES(v_asset, p_message)
    ON CONFLICT(asset_id) DO UPDATE SET message_id = EXCLUDED.message_id
    WHERE (p_observed, p_message) > (
        SELECT observed_at, message_id FROM tracking.telemetry_events
        WHERE message_id = tracking.current_state.message_id
    );
    RETURN true;
END $$;
REVOKE ALL ON FUNCTION tracking.ingest(uuid,text,timestamptz,double precision,double precision,text,smallint,text) FROM PUBLIC;
