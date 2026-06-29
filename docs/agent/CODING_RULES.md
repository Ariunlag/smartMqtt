# Coding Rules for Smart-MQTT++

> These rules are for coding agents and contributors.

## General Rules

1. Do not rewrite unrelated files.
2. Do not delete existing features unless explicitly instructed.
3. Keep changes small, testable, and easy to review.
4. Before editing, identify which files will change and why.
5. Preserve the current FastAPI, React, MQTT, and InfluxDB structure unless a task explicitly requires refactoring.
6. Avoid large refactors during feature implementation.
7. Do not introduce new external services unless the task explicitly requires them.
8. Do not change public API routes unless required.
9. When behavior changes, update relevant documentation.
10. Prefer readable, maintainable code over clever code.

## Git Rules

1. Work on a feature branch.
2. One feature branch should contain one logical change.
3. Run `git status` before and after changes.
4. Review `git diff` before committing.
5. Do not use `git push --force`.
6. Do not commit `.env`, `.venv`, `node_modules`, cache files, generated logs, or local data.

## Backend Rules

1. Use FastAPI routers and Pydantic models where appropriate.
2. Validate incoming API and MQTT payloads.
3. Use environment variables for configuration.
4. Avoid hardcoded localhost URLs in production-facing code.
5. Replace print debugging with structured logging over time.
6. Add timeout and error handling for external calls where possible.
7. Keep MQTT ingestion, storage, semantic analysis, and WebSocket broadcasting separated.

## Frontend Rules

1. Keep API calls inside frontend service files.
2. Keep state logic inside Zustand stores.
3. Do not hardcode backend URLs where environment configuration is possible.
4. Preserve existing UI behavior unless the task requires a UI change.
5. Keep components focused and small.

## Documentation Rules

1. Public documentation should describe stable behavior.
2. Internal engineering documents may describe risks, limitations, and future work.
3. Claims about performance must be backed by benchmark results.
4. Do not claim production readiness until deployment, security, and benchmark work are complete.
