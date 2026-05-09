# AGENTS

## Project Overview

`toLink-Rag` is a FastAPI-based RAG backend for document parsing, chunking, vector indexing, and MQ-driven integration with Java services.

## How To Use This File

This file is only the stable entry map for agents.

- Start here to decide which document area to read.
- Do not treat this file as the full source of project knowledge.
- Load detailed documents progressively from `docs/` only when the task needs them.
- Keep feature details, architecture details, plans, and references out of this file.

## Primary Code Entrypoints

- Application entry: [src/main.py](src/main.py)
- Runtime settings: [src/config.py](src/config.py)
- Current database structure: [scripts/db/init.sql](scripts/db/init.sql)
- Unit tests: [tests/unit](tests/unit)
- Integration tests: [tests/integration](tests/integration)

## Documentation Map

Use these directories as the source of truth for project knowledge.

| Need | Read |
| --- | --- |
| Overall architecture, module boundaries, project tree | [docs/architecture](docs/architecture) |
| Technical design and implementation status | [docs/design](docs/design) |
| Coding conventions, schema rules, workflow conventions | [docs/conventions](docs/conventions) |
| Current iteration plans and task checklists | [docs/plans](docs/plans) |
| API contracts, error codes, data models, generated references | [docs/reference](docs/reference) |

## Architecture

Read [docs/architecture](docs/architecture) before changing module boundaries or cross-module behavior.

Key documents:

- [Project structure](docs/architecture/project_structure.md)
- [File parser module](docs/architecture/file_parser_module.md)
- [Chunking module](docs/architecture/chunking_module.md)
- [Vectorization module](docs/architecture/vectorization_module.md)

## Design Documents

Read [docs/design](docs/design) for technical design and implementation status.

Design documents should state one of these statuses when applicable:

- `Draft`: still under discussion.
- `Approved`: ready for implementation.
- `Implemented`: completed and verified.

Legacy feature documents that have not yet been moved may still exist under older `docs/` subdirectories. Prefer moving or linking them into `docs/design` when touching them.

## Conventions

Read [docs/conventions](docs/conventions) before changing shared rules.

| Topic | Read |
| --- | --- |
| Naming conventions | [docs/conventions/naming_conventions.md](docs/conventions/naming_conventions.md) |
| Runtime configuration | [src/config.py](src/config.py), [.env.example](.env.example) |
| Current database structure | [scripts/db/init.sql](scripts/db/init.sql) |
| MQ contracts and topics | [src/core/mq](src/core/mq), [docs/reference](docs/reference) |
| Module boundaries | [docs/architecture](docs/architecture) |
| Test scope and markers | [tests/README.md](tests/README.md) |

- All runtime configuration must go through `Settings` in [src/config.py](src/config.py).
- Environment examples belong in [.env.example](.env.example).
- [scripts/db/init.sql](scripts/db/init.sql) is the current source of truth for database tables, columns, indexes, and comments.
- Do not hardcode secrets or credentials.
- Use existing project patterns before adding new abstractions.
- For MQ changes, follow the MQ middleware conventions and existing message contracts.

## Plans

Read [docs/plans](docs/plans) for current iteration plans, task lists, and operational test plans.

Plans are expected to change frequently. Keep stable architecture and long-lived conventions out of this directory.

## Reference

Read [docs/reference](docs/reference) for contracts and generated or semi-generated reference material.

Good candidates: API contracts, MQ message contracts, error code tables, data model references, and external integration notes.

## Working Rules

- Read the relevant docs before editing code.
- Make the smallest change that matches the existing architecture.
- Keep documentation updates close to the kind of knowledge being changed.
- If a structural change affects project layout, update [docs/architecture/project_structure.md](docs/architecture/project_structure.md).
- If a parser-module change affects usage or extension rules, update [docs/architecture/file_parser_module.md](docs/architecture/file_parser_module.md).
- If a feature design changes status, update its design document in [docs/design](docs/design).
