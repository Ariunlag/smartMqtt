# System recommendation real-stack acceptance

Run the full Docker Compose stack without deleting volumes:

```powershell
docker compose up -d --build
python scripts/run_real_stack_acceptance.py --run-id local-check
```

The acceptance runner uses a unique topic prefix and verifies:

- PostgreSQL starts with the pgvector extension and Alembic head applied;
- MQTT telemetry reaches InfluxDB;
- topic and pair vectors materialize in PostgreSQL vector tables;
- the topic embedding HNSW cosine index exists;
- system-derived Recommended Classes are returned independently from Saved Classes;
- recommendation responses expose discovery channels, pair evidence, and coverage
  without a fused `overall_score`;
- duplicate keep-both preserves independent canonical topics;
- confirmed duplicate aliases disappear from independent recommendation membership;
- vector evidence survives backend restart.

Acceptance configuration shortens duplicate delays and allows a single HDBSCAN
cluster so a small isolated fixture can exercise candidate discovery. Those settings
are operational test controls, not production similarity weights.

The runner never deletes Docker volumes or resets databases. Test data remains
namespaced by the run ID.
