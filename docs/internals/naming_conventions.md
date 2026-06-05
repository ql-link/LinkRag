# Naming Conventions

This document records project-level naming rules that should stay stable across features.

## Python Code

- Modules and files use `snake_case.py`.
- Functions, methods, and variables use `snake_case`.
- Classes use `PascalCase`.
- Constants use `UPPER_SNAKE_CASE`.
- Private helpers use a leading underscore, for example `_build_vector_storage`.
- Async functions that expose an async variant may use an `a` prefix when the existing local pattern does, for example `aprocess`.

## Packages And Directories

- Source package directories use lowercase names.
- Multi-word package directories use `snake_case`, for example `vector_storage`.
- Keep domain modules under the existing ownership boundaries:
  - API routes: `src/api/routes`
  - API schemas: `src/api/schemas`
  - Services: `src/services`
  - Core infrastructure: `src/core`
  - ORM models: `src/models`
  - Tests: `tests/unit` and `tests/integration`

## Configuration

- Runtime settings fields use `UPPER_SNAKE_CASE` in `src/config.py`.
- Environment variables use the same `UPPER_SNAKE_CASE` names.
- New runtime configuration must be added to both `src/config.py` and `.env.example`.
- Do not encode secrets or environment-specific credentials in docs or source code.

## Database

- The current database structure is [scripts/db/init.sql](../../scripts/db/init.sql); the frozen 0001 baseline is [migrations/db.sql](../../migrations/db.sql).
- Table and column names use `snake_case`.
- Status-like values use uppercase string constants in code.
- Keep database comments in DDL when adding or changing business columns.

## MQ

- Message classes use `PascalCase` and end with `Message` or `Payload` when they model MQ messages.
- MQ payload fields use `snake_case`.
- Topic and group names must match the Java-side contract exactly.
- When changing MQ names or payload fields, update tests and reference docs together.

## Tests

- Test files use `test_*.py`.
- Test names should describe behavior, for example `test_parse_msg_supports_flat_payload`.
- Unit tests should stay under `tests/unit`.
- Real infrastructure tests should stay under `tests/integration`.
