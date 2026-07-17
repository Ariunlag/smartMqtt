# Database migrations (Alembic)

PostgreSQL schema is owned by **Alembic migrations**, not by the application.
`PostgresClient.connect()` only verifies connectivity — it never creates or
mutates schema. You must run migrations before the backend can serve requests.

Migrations live in `backend/alembic/versions/`. The project uses **raw psycopg
SQL** (no ORM); migrations contain explicit SQL via `op.execute(...)`.

## Configuration

The database URL is read from the `POSTGRES_DSN` environment variable (the same
one the app uses) and normalized to the SQLAlchemy `postgresql+psycopg://`
driver in `backend/alembic/env.py`. Run all commands from the `backend/`
directory.

## Common commands

```bash
cd backend

alembic current              # show the currently applied revision
alembic history              # list all revisions
alembic upgrade head         # apply all pending migrations
alembic downgrade -1         # revert the most recent migration
alembic revision -m "add semantic_jobs table"   # create a new migration
```

Preview SQL without touching a database (useful for review / DBA hand-off):

```bash
alembic upgrade head --sql
```

## Local Docker Compose

`docker compose up` runs a one-off `migrate` service (`alembic upgrade head`)
that must complete successfully before the `backend` service starts. No manual
step is required locally.

## Production

Run migrations as a **separate one-off job** (e.g. a Kubernetes Job or a
pre-deploy step) rather than from every backend replica:

```bash
POSTGRES_DSN=postgresql://user:pass@host:5432/db alembic upgrade head
```

## Baseline & existing databases

`0001_baseline` represents the original schema and uses `CREATE TABLE IF NOT
EXISTS`, so an existing database created by the old startup path adopts the
baseline without data loss; Alembic then records the version in
`alembic_version`. A fresh database is created from scratch.

## Authoring new migrations

Each migration must implement explicit `upgrade()` and `downgrade()`:

```python
def upgrade() -> None:
    op.execute("ALTER TABLE ... ADD COLUMN ...")

def downgrade() -> None:
    op.execute("ALTER TABLE ... DROP COLUMN ...")
```

Prefer idempotent, non-destructive changes. Never drop or rewrite data in an
`upgrade()` without an explicit, reviewed plan.
