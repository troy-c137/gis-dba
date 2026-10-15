SELECT now(), version(), pg_database_size(current_database()) AS database_bytes;
SELECT datname, numbackends, xact_commit, xact_rollback, deadlocks,
       blks_hit, blks_read, stats_reset FROM pg_stat_database WHERE datname=current_database();
SELECT pid, usename, state, wait_event_type, wait_event, now()-xact_start AS transaction_age
FROM pg_stat_activity WHERE datname=current_database() ORDER BY xact_start;
SELECT relname, n_live_tup, n_dead_tup, last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables ORDER BY n_dead_tup DESC;
SELECT relname, indexrelname, idx_scan FROM pg_stat_user_indexes ORDER BY idx_scan;
SELECT count(*) AS waiting_locks FROM pg_locks WHERE NOT granted;
SELECT max(observed_at) AS last_telemetry, count(*) AS current_assets FROM tracking.current_assets;
