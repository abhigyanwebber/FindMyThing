# Build from the REPO ROOT:  docker build -f backend/Dockerfile -t findmything-api .
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.source="https://github.com/abhigyanwebber/FindMyThing"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ACCEPT_EULA=Y \
    DEBIAN_FRONTEND=noninteractive

# Microsoft ODBC Driver 18 for SQL Server (required by pyodbc / DATABASE_URL).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates unixodbc \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies come from the maintained manifest, never from a local virtual environment.
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
# Template only; mount or override CAMPUS_CONFIG_PATH with the real campus JSON in deployment.
COPY config/campus.example.json ./config/campus.example.json

# Portable, absolute path (no machine-specific Windows paths). No secrets are baked into the image.
ENV CAMPUS_CONFIG_PATH=/app/config/campus.example.json \
    LOG_LEVEL=INFO

RUN useradd --system --uid 10001 --no-create-home appuser \
    && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
