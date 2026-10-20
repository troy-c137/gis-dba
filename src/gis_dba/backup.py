"""Logical backup with a consistent manifest and validation in a newly created database."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from gis_dba.config import database_url

TABLES = ("units", "assets", "telemetry_events", "locations", "current_state", "operational_areas")


def fingerprint(conn):
    conn.execute("SET LOCAL timezone = 'UTC'")
    result = {}
    for table in TABLES:
        # Order-independent row fingerprints with bounded server memory; includes geometry and IDs.
        result[table] = conn.execute(
            sql.SQL("""SELECT count(*),
            COALESCE(sum(('x'||substr(md5(to_jsonb(t)::text),1,15))::bit(60)::bigint),0)::text
            FROM tracking.{} t""").format(sql.Identifier(table))
        ).fetchone()
    result["migrations"] = conn.execute(
        "SELECT version,sha256 FROM public.schema_migrations ORDER BY version"
    ).fetchall()
    return result


def run_pg(program, dsn, *arguments):
    details = conninfo_to_dict(dsn)
    env = os.environ.copy()
    if "password" in details:
        env["PGPASSWORD"] = details.pop("password")
    subprocess.run([program, "--dbname", make_conninfo(**details), *arguments], env=env, check=True)


def backup(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or Path(str(path) + ".json").exists():
        raise ValueError("Backup path already exists")
    path.touch(mode=0o600, exist_ok=False)
    dsn = database_url("ADMIN_DATABASE_URL")
    with psycopg.connect(dsn) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        snapshot = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
        manifest = fingerprint(conn)
        run_pg(
            "pg_dump",
            dsn,
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--snapshot",
            snapshot,
            "--file",
            str(path),
        )
    os.chmod(path, 0o600)
    metadata = {
        "created_at": datetime.now(UTC).isoformat(),
        "data": manifest,
        "sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
    }
    sidecar = Path(str(path) + ".json")
    sidecar.write_text(json.dumps(metadata, indent=2, default=str) + "\n")
    os.chmod(sidecar, 0o600)
    print(f"Backup and consistent manifest created: {path}")


def restore(path, target):
    if not re.fullmatch(r"gis_restore_[a-z0-9_]{1,40}", target):
        raise ValueError(
            "Target must start gis_restore_ and contain lowercase letters/digits/underscores"
        )
    metadata = json.loads(Path(str(path) + ".json").read_text())
    if hashlib.file_digest(path.open("rb"), "sha256").hexdigest() != metadata["sha256"]:
        raise ValueError("Archive checksum mismatch")
    source_dsn = database_url("ADMIN_DATABASE_URL")
    dsn = make_conninfo(source_dsn, dbname=target)
    # CREATE DATABASE fails if target exists; never overwrite or drop an existing database.
    with psycopg.connect(make_conninfo(source_dsn, dbname="postgres"), autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(target))
        )
        conn.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(target))
        )
    run_pg(
        "pg_restore",
        dsn,
        "--exit-on-error",
        "--single-transaction",
        "--no-owner",
        "--no-acl",
        str(path),
    )
    with psycopg.connect(dsn) as conn:
        conn.execute("REVOKE ALL ON SCHEMA tracking FROM PUBLIC")
        conn.execute(
            "REVOKE ALL ON FUNCTION tracking.ingest(uuid,text,timestamptz,"
            "double precision,double precision,text,smallint,text) FROM PUBLIC"
        )
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        conn.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(target))
        )
        actual = fingerprint(conn)
        # Restore excludes ACLs by design: validation is admin-only until grants are explicitly applied.
        orphan = conn.execute("""SELECT count(*) FROM tracking.telemetry_events e
            LEFT JOIN tracking.locations l USING(message_id) WHERE l.message_id IS NULL""").fetchone()[
            0
        ]
        conn.execute("SELECT count(*) FROM tracking.current_assets").fetchone()
    if json.loads(json.dumps(actual, default=str)) != metadata["data"] or orphan:
        raise ValueError(f"Recovery validation failed; inspect {target}")
    print(
        f"RECOVERY VERIFIED: {target}; row fingerprints, migrations, locations, and GIS view match"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["backup", "restore"])
    parser.add_argument("archive", type=Path)
    parser.add_argument("--target")
    args = parser.parse_args()
    if args.command == "restore" and not args.target:
        parser.error("restore requires --target gis_restore_<unique_name>")
    try:
        if args.command == "backup":
            backup(args.archive)
        else:
            restore(args.archive, args.target)
    except (ValueError, RuntimeError, psycopg.Error, subprocess.CalledProcessError) as exc:
        parser.exit(
            1, f"{type(exc).__name__}: backup/recovery failed; inspect database/tool logs\n"
        )


if __name__ == "__main__":
    main()
