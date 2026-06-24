# Container Deployment

JobRun Sentinel can run as three portable containers:

- `jobrun-sentinel-api`: FastAPI backend.
- `jobrun-sentinel-frontend`: static React build served by Nginx.
- `postgres:16-alpine`: Sentinel database.

The frontend calls `/api` and Nginx proxies that path to the API service. This keeps the same frontend image deployable across hosts because the browser does not need an environment-specific API URL baked into the JavaScript bundle.

## Local Compose

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Frontend: `http://localhost:5173/dashboard`
- API docs: `http://localhost:8000/docs`
- Health: `http://localhost:5173/health` or `http://localhost:8000/health`

If you change `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB`, update `DATABASE_URL` to match.

For production, set `AUTO_SEED=false` after the database has been initialized with the data you intend to keep. Demo mode intentionally seeds synthetic customers and incidents.

## Build Images

```bash
docker build -t jobrun-sentinel-api:local ./backend
docker build -t jobrun-sentinel-frontend:local ./frontend
```

For a registry:

```bash
export REGISTRY=ghcr.io/your-org
export VERSION=0.1.0

docker build -t "$REGISTRY/jobrun-sentinel-api:$VERSION" ./backend
docker build -t "$REGISTRY/jobrun-sentinel-frontend:$VERSION" ./frontend
docker push "$REGISTRY/jobrun-sentinel-api:$VERSION"
docker push "$REGISTRY/jobrun-sentinel-frontend:$VERSION"
```

Set these in `.env` or your deployment system:

```bash
JOBRUN_API_IMAGE=ghcr.io/your-org/jobrun-sentinel-api:0.1.0
JOBRUN_FRONTEND_IMAGE=ghcr.io/your-org/jobrun-sentinel-frontend:0.1.0
```

## Required Runtime Environment

API:

- `DATABASE_URL`: SQLAlchemy URL for the Sentinel database.
- `AUTO_SEED`: `true` for demo/local environments, usually `false` for production after initial setup.
- `JOBRUN_CONNECTOR_MODE`: `mock` or `oracle`.
- `JOBRUN_ALLOW_ORACLE_CONNECTOR`: `true` only when read-only Oracle credentials are configured.
- `JOBRUN_SCHEDULER_ENABLED`: `true` only after connector health and query-template validation are green.
- `DEFAULT_ALERT_DASHBOARD_URL`: externally reachable dashboard URL for alert payloads.

Frontend:

- `API_UPSTREAM`: internal URL for the API, for example `http://api:8000`.

Database:

- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`

Do not store Oracle passwords, wallet passwords, Slack tokens, or Confluence PATs in the Sentinel database. Use environment variables or your platform secret manager.

## Health Checks

API:

```bash
GET /health
```

Frontend:

```bash
GET /health
```

The frontend health endpoint proxies to the API health endpoint, so a healthy frontend confirms both static serving and API reachability.

## Kubernetes Or Any Container Platform

Use the same two app images:

- API container port: `8000`
- Frontend container port: `8080`

Recommended objects:

- PostgreSQL from your managed database service or a StatefulSet.
- API Deployment with `DATABASE_URL` and connector secrets from a Secret.
- Frontend Deployment with `API_UPSTREAM=http://jobrun-sentinel-api:8000`.
- Service for API on port `8000`.
- Service/Ingress for frontend on port `8080`.
- Readiness/liveness probes against `/health`.

Keep `AUTO_SEED=false` for production once initial seed/demo data is no longer desired. Leave `JOBRUN_RUN_MIGRATIONS=false` unless you intentionally want the container to run Alembic migrations at startup.

## Read-Only Production Connector

The app remains non-destructive. Oracle integration must use read-only credentials and SELECT/WITH query templates only. Configure connector secrets with env vars matching each `ConnectorConfig.env_var_prefix`, then validate:

```bash
python -m app.cli connector-health
python -m app.cli validate-templates
python -m app.cli sync-once
```

In containers, run these with `docker compose exec api ...` or as one-off jobs in your platform.
