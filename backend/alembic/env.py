"""Alembic environment.

The project uses raw psycopg SQL (no ORM), so there is no model metadata to
autogenerate from. Migrations contain explicit SQL / Alembic operations and
``target_metadata`` is intentionally None. The database URL is taken from the
POSTGRES_DSN environment variable (falling back to the app config default) and
normalized to the SQLAlchemy psycopg (v3) driver.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _database_url() -> str:
    url = os.getenv("POSTGRES_DSN") or os.getenv("DATABASE_URL")
    if not url:
        try:
            from config import config as app_config

            url = app_config.POSTGRES_DSN
        except Exception:
            url = "postgresql://influxai:influxai@localhost:5432/influxai"

    # SQLAlchemy needs the driver-qualified scheme for psycopg v3.
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
