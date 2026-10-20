PYTHON ?= python3

.PHONY: install env db init api simulate test integration health benchmark backup
install:
	$(PYTHON) -c 'import sys; assert sys.version_info >= (3, 11), "Use a Python 3.11+ interpreter: make install PYTHON=path/to/python"'
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -r requirements.lock
	.venv/bin/pip install --no-deps -e .
env:
	.venv/bin/gis-admin env
db:
	./scripts/compose up -d db
init:
	.venv/bin/gis-admin create-db
	.venv/bin/gis-admin migrate
	.venv/bin/gis-admin roles
	.venv/bin/gis-admin seed
api:
	.venv/bin/uvicorn gis_dba.api:app --reload --host 127.0.0.1
simulate:
	.venv/bin/gis-simulate
test:
	.venv/bin/pytest -m 'not integration'
integration:
	RUN_DB_TESTS=1 .venv/bin/pytest
health:
	.venv/bin/gis-admin health
benchmark:
	.venv/bin/python scripts/benchmark.py --rows 100000
backup:
	.venv/bin/gis-backup backup backups/gis_lab.dump
