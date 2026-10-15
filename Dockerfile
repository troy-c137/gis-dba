FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 GIS_PROJECT_ROOT=/app
WORKDIR /app
COPY pyproject.toml requirements.lock ./
RUN pip install -r requirements.lock
COPY src ./src
RUN pip install --no-deps . && useradd --create-home app
COPY sql ./sql
COPY scripts ./scripts
USER app
EXPOSE 8000
CMD ["uvicorn", "gis_dba.api:app", "--host", "0.0.0.0", "--port", "8000"]
