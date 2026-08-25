# Pair-level recommendation real-stack acceptance

Run the full Docker Compose stack without deleting volumes:

```powershell
docker compose up -d --build
python scripts/run_real_stack_acceptance.py --run-id local-check
```

The acceptance runner uses a unique topic prefix and verifies health, MQTT to
Influx ingestion, authoritative flat topic vectors, pair vectors, class profile
materialization, topic- and class-oriented recommendations, factual evidence,
accept/reject/dismiss/manual actions, duplicate pending/keep-both/confirmation,
canonical membership reconciliation, restart recovery from durable source
state, bounded recommendation processing, and concurrent action behavior.

It never runs `docker compose down -v`, deletes a Docker volume, resets the
database, or clears Qdrant. Test data remains namespaced by the run ID.
