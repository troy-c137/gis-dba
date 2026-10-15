# Local and Docker setup

Use the repository terminal in VS Code. Python 3.11+ is required (Docker uses 3.12). Both modes run the same schema and code; native uses port **5432**, Docker **55432**. They hold independent data. The host API uses **8000**, so run one API at a time.

## Python environment

On this Apple Silicon Mac, Homebrew Python is available as `/opt/homebrew/bin/python3.14`; `/usr/bin/python3` is too old. On Ubuntu use `python3` after installing Python 3.11+ and its venv package.

```bash
/opt/homebrew/bin/python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e .
gis-admin env
```

The last command creates `.env` with random credentials, refuses to replace an existing file, and sets mode 0600. Never commit `.env`, backups, or database files. You can use the checked-in VS Code launch configurations after selecting `.venv` as the interpreter.

## Docker on macOS

Install Docker Desktop **or** use the existing Homebrew Docker CLI with Colima:

```bash
brew install docker-compose colima
colima start --cpu 2 --memory 4 --disk 20 --vm-type vz --vz-rosetta
```

On Apple Silicon, Colima uses Rosetta when it is available and can fall back to QEMU if it is not installed. The upstream `postgis/postgis:17-3.5` image is amd64; the Compose service explicitly selects that platform. Emulation adds overhead. On Intel or Linux omit the Colima command. Docker Desktop also supports amd64 emulation.

The checked-in `./scripts/compose` wrapper selects either Docker's `docker compose` plugin or Homebrew's standalone `docker-compose`. No global Docker configuration changes are required.

```bash
python scripts/use_database.py docker
./scripts/compose up -d db
gis-admin migrate
gis-admin roles
gis-admin seed
./scripts/compose up -d --build api
```

Alternatively, initialize without host Python DB connections using:

```bash
./scripts/compose run --rm admin migrate
./scripts/compose run --rm admin roles
./scripts/compose run --rm admin seed
```

Migrations run explicitly, including after an existing volume is reused. They are not confined to Docker's first-boot init directory. `./scripts/compose logs --tail=100 db api` shows startup and slow-query logs. `./scripts/compose stop` preserves the named volume. `./scripts/compose down` removes containers and the network but preserves data. **Adding `-v` deletes the lab database volume.** Changing a password in `.env` does not reset an existing PostgreSQL admin password; use `ALTER ROLE` with the old credentials or update `.env` to match.

## Native macOS PostgreSQL 17

```bash
brew install postgresql@17 postgis
export PG_BIN=/opt/homebrew/opt/postgresql@17/bin
export PATH="$PG_BIN:$PATH"
python scripts/native_db.py start
python scripts/use_database.py native
gis-admin create-db
gis-admin migrate
gis-admin roles
gis-admin seed
uvicorn gis_dba.api:app --reload --host 127.0.0.1
```

The helper initializes `.pgdata` inside this repository with a `postgres` administrator and the generated password, SCRAM authentication, loopback binding, and a project-local socket. It does not start Homebrew's global service or modify an existing cluster. Stop it with `python scripts/native_db.py stop`; inspect it with `status`. Logs are in `.pgdata/server.log`.

Homebrew PostGIS packaging changes: verify availability for PostgreSQL **17** before migrating (`SELECT * FROM pg_available_extensions WHERE name='postgis';`). Do not assume an extension installed for another PostgreSQL major works on 17. [PostGIS documents macOS installation options](https://postgis.net/documentation/getting_started/install_macos/), including Postgres.app with bundled PostGIS. Use a single distribution consistently.

## Native Ubuntu Linux

An Ubuntu VM accessed through VS Code Remote SSH provides a real Linux administration environment. Docker's database image is Linux but is not a full Ubuntu host. Configure the [official PostgreSQL APT repository](https://www.postgresql.org/download/linux/ubuntu/) first, then:

```bash
sudo apt install postgresql-17 postgresql-client-17 postgresql-17-postgis-3 python3-venv
export PG_BIN=/usr/lib/postgresql/17/bin
```

APT may automatically start a system cluster on 5432. Either use that cluster (set a strong administrator password interactively with `sudo -u postgres psql`, then `\password postgres`) or stop that lab system cluster before using `scripts/native_db.py`. Do not stop a shared database. Keep `listen_addresses='localhost'` and SCRAM rules for `127.0.0.1/32` and `::1/128` in `pg_hba.conf`; reload configuration after edits. For remote VS Code, forward 8000 and the selected DB port through SSH instead of exposing PostgreSQL publicly.

Then create the venv, generate `.env`, select native mode, and run the same create-db/migrate/roles/seed commands. [PostGIS's Ubuntu instructions](https://postgis.net/documentation/getting_started/install_ubuntu/) explain version-specific extension packages.

## First telemetry

With the API running, in a second activated terminal:

```bash
gis-simulate --cycles 5 --interval 2
gis-admin health
```

The simulator updates 12 synthetic assets per cycle. `http://127.0.0.1:8000/docs` lists endpoints. For direct XML and GeoJSON requests, load `.env` only in your local shell and provide the key:

```bash
set -a
source .env
set +a
curl -H "X-API-Key: $API_KEY" -H 'Content-Type: application/xml' \
  --data-binary @examples/telemetry.xml http://127.0.0.1:8000/telemetry/xml
curl -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/assets
curl -H "X-API-Key: $API_KEY" \
  'http://127.0.0.1:8000/assets/nearby?longitude=-140&latitude=-40&radius_m=10000'
```

Switching `.env` requires restarting a host API, because configuration loads at process startup. Compose injects its own `db:5432` URLs so the container API is unaffected by the host-port switch.
