# Deployment guide

SmartMQTT's supported local deployment is the repository Docker Compose stack.
It runs PostgreSQL, Qdrant, InfluxDB, Mosquitto, a one-off Alembic migration,
the FastAPI backend, and the React/Nginx frontend.

## Local startup

```bash
docker compose up -d --build
docker compose ps
```

The backend container starts only after PostgreSQL is healthy and the migration
job completes. InfluxDB, Mosquitto, Qdrant, and the backend also expose Compose
health checks. Runtime probes are:

```text
GET /api/health/live     process liveness; independent of dependencies
GET /api/health/ready    200 only when every required dependency is healthy
GET /api/health/details  per-dependency health and bounded check latency
```

The frontend is available at `http://localhost:3000` and proxies `/api` to the
backend. The backend is also published at `http://localhost:8000` for local
diagnostics.

## Configuration and secrets

Compose includes developer-only defaults so an isolated workstation can start
without a secret manager. They must not be used for a shared environment.

Use `.env.acceptance.example` as a key inventory, copy it to an untracked env
file, and replace every `CHANGE_ME`. Never commit passwords, tokens, populated
DSNs, `.env` files, or model-provider credentials. In a managed deployment,
inject secrets with the platform's secret store and restrict published ports.

Important runtime settings include:

- PostgreSQL database/user/password and `POSTGRES_DSN`
- InfluxDB initialization password/token, organization, and bucket
- optional `QDRANT_API_KEY`
- `EMBEDDING_MODEL` and `EMBEDDING_DEVICE`
- ingestion and semantic queue bounds
- discovery and persistence lifecycle timeouts

## Safe shutdown and recovery

```bash
docker compose stop
```

The backend stops primary ingestion, drains bounded processing, performs the
final semantic persistence flush, stops dependency monitoring, and disconnects
clients. Compose volumes retain PostgreSQL, Qdrant, and InfluxDB data.

`docker compose down -v` permanently deletes those volumes. It is not part of
normal shutdown, acceptance, or recovery.

The dependency monitor keeps liveness available during broker or database
outages. Readiness becomes unavailable until recovery. MQTT recovery reconnects
the existing client network loop and restores stored subscriptions. Failed
semantic persistence remains dirty; after PostgreSQL recovery an operator may
request the existing coalesced save path through:

```text
POST /api/semantic-review/persistence-retry
```

## Real-stack acceptance

Run the repository-maintained acceptance workflow after deployment or lifecycle
changes:

```bash
python -m scripts.run_real_stack_acceptance --run-id local-001
```

The workflow uses real MQTT publication and all configured data services. It
also verifies restart recovery, broker recovery, PostgreSQL persistence retry,
bounded queue behavior, and final flush. It does not delete volumes. Full
details and failure guidance are in
[`docs/REAL_STACK_ACCEPTANCE.md`](REAL_STACK_ACCEPTANCE.md).

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
