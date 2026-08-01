# Real-stack acceptance runbook

This runbook exercises SmartMQTT through the repository's actual Docker
Compose services: Mosquitto, PostgreSQL, Qdrant, InfluxDB, the Alembic
migration job, FastAPI, and the React/Nginx frontend. It uses the configured
`BAAI/bge-small-en-v1.5` CPU embedding implementation and the frozen production
semantic decision thresholds.

The runner does not delete containers, volumes, or persisted records. Each run
uses a topic prefix and semantic persistence state key derived from a unique
run ID, so repeat runs cannot overwrite an earlier acceptance snapshot.

## Prerequisites

- Docker Desktop is running with Linux containers.
- Ports 1883, 3000, 6333, 8000, 8086, and 9001 are available.
- The machine has enough memory and disk for the model and seven services.
- First use has network access for container images and the embedding model, or
  those artifacts are already cached locally.

For shared or non-local environments, copy `.env.acceptance.example` to an
untracked `.env.acceptance`, replace every `CHANGE_ME`, then add
`--env-file .env.acceptance` to Compose commands run manually. Never commit
populated environment files. The checked-in Compose credential defaults are
for an isolated developer workstation only; they are not deployment secrets.

## Execute

From the repository root:

```bash
python -m scripts.run_real_stack_acceptance --run-id local-001
```

Run IDs must contain only lowercase letters, digits, and hyphens and must be at
most 32 characters. Omit `--run-id` to use a UTC timestamp. The exact same
command works from PowerShell.

The runner combines `docker-compose.yml` and
`docker-compose.acceptance.yml`. The override changes operational queue sizing
and debounce/recovery timing only. It does not change representations,
clustering, scoring, or frozen decision thresholds.

## Acceptance phases

The command fails non-zero on the first bounded assertion that does not pass
and prints Compose state plus recent backend logs. A successful run verifies:

1. dependencies become healthy and Alembic completes;
2. backend readiness and frontend availability;
3. API subscription, Mosquitto publication, primary ingestion, and InfluxDB
   query visibility;
4. UNKNOWN processing, representation-specific discovery, pending candidate
   publication, human review, six-view prototypes, and a subsequent decision
   under the existing strict thresholds;
5. exact reviewed class, constraint, candidate, and topic-decision recovery
   after a backend restart;
6. broker outage detection, liveness preservation, reconnect, subscription
   restoration, and resumed ingestion;
7. PostgreSQL outage detection, persistence degradation, explicit retry after
   recovery, and generation convergence;
8. bounded semantic queue drops with internally consistent submitted,
   processed, failed, and dropped counters;
9. bounded backend shutdown, final snapshot flush, and restart recovery.

No embedding vectors, centroid values, database DSNs, SQL text, credentials, or
raw semantic snapshots are returned by the operational API endpoints used by
the runner.

## Validated baseline

The command was executed successfully on 2026-07-31 with run ID
`codex-20260731`. The real strict-threshold follow-up decision was `UNCERTAIN`
with reason `BELOW_KNOWN_SIMILARITY`; this is an accepted observation, not a
threshold change. The 80-message bounded burst processed 3 and explicitly
dropped 77 with no semantic failures. PostgreSQL and broker recovery passed,
and final generation 15 was flushed in 3.5 seconds and restored successfully.

## Cleanup and repeatability

The runner finishes with the stack healthy and running. To stop containers
while preserving all data:

```bash
docker compose stop
```

Do not use `docker compose down -v` unless permanent deletion of PostgreSQL,
Qdrant, and InfluxDB data is explicitly intended. Old acceptance snapshots may
be retained for audit or removed later through a separately reviewed database
maintenance procedure.

## Failure interpretation

- A model download or image pull failure is an environment/network blocker;
  do not substitute a fake embedding implementation.
- Readiness failure names the unhealthy dependency at
  `/api/health/details`; liveness remains available at `/api/health/live`.
- Persistence failures remain dirty and visible through
  `/api/semantic-review/persistence-status`. After PostgreSQL is healthy, the
  runner requests a coalesced retry through
  `/api/semantic-review/persistence-retry`.
- Topic verification uses `/api/semantic-review/topic-states`, which exposes
  only topic, decision state, candidate class ID, and reason codes.
