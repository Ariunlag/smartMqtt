# Deployment guide

SmartMQTT's supported local deployment is the repository Docker Compose stack. It
runs PostgreSQL with pgvector, InfluxDB, Mosquitto, a one-off Alembic migration, the
FastAPI backend, and the React/Nginx frontend.

## Local startup

```bash
docker compose up -d --build
docker compose ps
```

The backend starts only after PostgreSQL is healthy and the migration job completes.
InfluxDB, Mosquitto, and the backend also expose Compose health checks. Runtime probes
are:

```text
GET /api/health/live     process liveness; independent of dependencies
GET /api/health/ready    200 only when every required dependency is healthy
GET /api/health/details  per-dependency health and bounded check latency
```

The frontend is available at `http://localhost:3000` and proxies `/api` to the backend.
The backend is also published at `http://localhost:8000` for local diagnostics.

## Configuration and secrets

Compose includes developer-only defaults so an isolated workstation can start without
a secret manager. They must not be used for a shared environment.

Use `.env.acceptance.example` as a key inventory, copy it to an untracked env file,
and replace every `CHANGE_ME`. Never commit passwords, tokens, populated DSNs, `.env`
files, or model-provider credentials.

Important runtime settings include:

- PostgreSQL database/user/password and `POSTGRES_DSN`
- InfluxDB initialization password/token, organization, and bucket
- `EMBEDDING_MODEL`, `EMBEDDING_DEVICE`, and the current 384-dimensional embedding
  schema contract
- ingestion and recommendation queue bounds

PostgreSQL must provide the pgvector extension. The repository Compose stack uses
`pgvector/pgvector:pg16`; Alembic migration `0005_pgvector_embeddings` enables the
extension and creates the HNSW-indexed vector tables.

## Safe shutdown and recovery

```bash
docker compose stop
```

The backend stops primary ingestion and bounded recommendation processing, stops
dependency monitoring, and disconnects clients. Compose volumes retain PostgreSQL and
InfluxDB data.

`docker compose down -v` permanently deletes those volumes. It is not part of normal
shutdown, acceptance, or recovery.

The dependency monitor keeps liveness available during broker or database outages.
Readiness becomes unavailable until recovery. MQTT recovery reconnects the existing
client network loop and restores stored subscriptions. Relational metadata, human
decisions, and dense vectors recover from PostgreSQL; there is no separate runtime
vector service to coordinate.

## Production cutover

Take a PostgreSQL backup, ensure the pgvector extension is available, run
`alembic upgrade head`, then start the backend and verify health/readiness plus current
vector materialization before directing production traffic to the deployment.

## Real-stack acceptance

Run the repository-maintained acceptance workflow after deployment or lifecycle
changes:

```bash
python -m scripts.run_real_stack_acceptance --run-id local-001
```

The workflow uses real MQTT publication and configured data services. It verifies
restart recovery, recommendation evidence, canonical duplicate reconciliation, and
vector persistence. It does not delete volumes.

## External deployment hardening

Before exposing the stack beyond a trusted network:

- require API authentication and authorization;
- require authenticated, encrypted MQTT connections;
- terminate HTTPS at a managed ingress or reverse proxy;
- restrict CORS and published database ports;
- store all credentials in a secret manager and rotate local defaults;
- configure backups and tested restore procedures for every persistent store;
- centralize structured logs, metrics, alerts, and capacity monitoring;
- pin and scan container images and dependencies;
- run migration jobs separately from horizontally scaled backend replicas.
