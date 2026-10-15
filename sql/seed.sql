INSERT INTO tracking.units(code,name) VALUES
('SIM-ALPHA','Fictional Alpha Research Group'),('SIM-BRAVO','Fictional Bravo Research Group')
ON CONFLICT DO NOTHING;
INSERT INTO tracking.assets(equipment_id,unit_id,asset_type)
SELECT 'SIM-ASSET-' || lpad(i::text,3,'0'),
       (SELECT unit_id FROM tracking.units WHERE code=CASE WHEN i <= 6 THEN 'SIM-ALPHA' ELSE 'SIM-BRAVO' END),
       (ARRAY['relay','sensor','terminal'])[1 + (i % 3)]
FROM generate_series(1,12) i ON CONFLICT DO NOTHING;
-- Entirely invented training grid in the South Pacific; no real facilities or movements.
INSERT INTO tracking.operational_areas(name,boundary) VALUES
('Synthetic West',ST_GeomFromText('POLYGON((-140.2 -40.2,-140 -40.2,-140 -39.8,-140.2 -39.8,-140.2 -40.2))',4326)),
('Synthetic East',ST_GeomFromText('POLYGON((-140 -40.2,-139.8 -40.2,-139.8 -39.8,-140 -39.8,-140 -40.2))',4326))
ON CONFLICT DO NOTHING;
