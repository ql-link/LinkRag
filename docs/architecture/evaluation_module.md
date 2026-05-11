# Evaluation Module

This document describes the current structure and responsibilities of `src/evaluation`, the parsing quality evaluation module for LinkRag.

## Scope

`src/evaluation` is an independent evaluation subsystem used to assess parser and chunker quality without coupling the main RAG runtime to evaluation logic.

The module follows the direction defined in [architecture_design.md](../architecture_design.md):

- evaluation code depends on existing RAG public capabilities in `src/core/*`
- business runtime does not depend on `src/evaluation`
- adapters isolate concrete parser and chunker implementations from evaluator logic
- datasets, metrics, reports, and run orchestration are managed inside the evaluation module

## Responsibility Boundaries

`src/evaluation` is responsible for:

- loading evaluation datasets and manifests
- declaring evaluation pipelines from YAML
- adapting parser and chunker implementations into a unified evaluable interface
- executing evaluation runs with hooks, progress reporting, and result persistence
- computing parser and chunker metrics
- rendering evaluation reports in JSON and Markdown

`src/evaluation` should not:

- become a dependency of the HTTP API or MQ mainline flow
- modify `src/core/parser` or `src/core/splitter` behavior for evaluation-only needs
- own production parsing configuration in `src/config.py`

## Current Structure

The current implementation is a practical subset of the architecture draft. The implemented structure is:

```text
src/evaluation/
├── __main__.py                    # python -m src.evaluation entry
├── cli.py                         # run / list / report CLI
├── config.py                      # evaluation-specific configuration
├── contracts/                     # evaluation protocols and shared data contracts
│   ├── dataset.py
│   ├── evaluable.py
│   ├── hook.py
│   ├── judge.py
│   ├── metric.py
│   └── store.py
├── adapters/                      # wraps parser/chunker implementations as evaluables
│   ├── chunker_adapter.py
│   ├── parser_adapter.py
│   └── registry.py
├── datasets/                      # dataset loading and manifest parsing
│   ├── loader.py
│   └── manifest.py
├── evaluators/                    # stage-specific metric aggregation
│   ├── base.py
│   ├── chunker_evaluator.py
│   ├── comparison.py
│   └── parser_evaluator.py
├── hooks/                         # logging and progress callbacks
│   ├── logging_hook.py
│   └── progress_hook.py
├── metrics/                       # parser/chunker metric implementations
│   ├── registry.py
│   ├── chunker/
│   │   ├── boundary.py
│   │   └── length_dist.py
│   └── parser/
│       ├── latency.py
│       ├── md_structure.py
│       └── stability.py
├── reporters/                     # report renderers
│   ├── base.py
│   ├── json_reporter.py
│   └── markdown_reporter.py
├── runners/                       # pipeline validation and run orchestration
│   ├── context.py
│   ├── pipeline.py
│   └── runner.py
└── storage/                       # run result persistence
    └── filesystem.py
```

## Layer Mapping

The current code maps to the architecture draft in the following way:

| Layer | Current location | Main role |
| --- | --- | --- |
| Access layer | `adapters/`, `datasets/` | connect parser and chunker implementations to evaluation flow |
| Metric layer | `metrics/`, `evaluators/` | compute sample-level and aggregate quality indicators |
| Orchestration layer | `runners/`, `storage/` | validate pipeline, run stages, persist run records |
| Output layer | `cli.py`, `reporters/` | expose run, list, report commands and render reports |
| Observability layer | `hooks/` | logging, progress, lifecycle events |

## Runtime Flow

The normal execution path is:

1. `python -m src.evaluation run -c <pipeline.yaml>` enters through [src/evaluation/cli.py](../../src/evaluation/cli.py).
2. `EvalPipeline` loads and validates YAML stage definitions from `configs/eval/`.
3. `MinioDataset` loads dataset metadata from remote `manifest.yaml` in MinIO bucket `test_set`.
4. `EvaluationRunner` executes configured stages in topological order.
5. `EvaluableRegistry` resolves configured adapters by name.
6. Evaluators dispatch metrics from `MetricRegistry`.
7. `MinioResultStore` writes run artifacts, reports, and baseline pointers to MinIO.
8. JSON and Markdown reporters render final reports.

## Dataset and Config Layout

The evaluation module relies on two repo-level companion areas:

| Area | Purpose |
| --- | --- |
| `configs/eval/` | declarative pipeline definitions such as parser-only or parse-plus-chunk runs |
| `test_set/datasets/` | remote evaluation datasets, manifests, samples, and ground truth in MinIO |
| `test_set/runs/`, `test_set/reports/`, `test_set/baselines/` | remote run records, rendered reports, and baseline pointers |

This keeps evaluation configuration in the repository while moving sample assets and run artifacts to remote MinIO storage.

## Relationship To The Architecture Draft

[architecture_design.md](../architecture_design.md) defines a broader target model than the current implementation. The following parts are described in the draft but are not fully present in `src/evaluation` today:

- dedicated `judges/` implementations
- embedding evaluation stages and metrics
- optional HTML reporter
- alternate result stores such as MySQL
- richer built-in dataset filtering and notification hooks

When extending `src/evaluation`, prefer aligning new work with the draft direction instead of introducing parallel patterns.

## Change Guidance

Read this document before changing module boundaries or adding new evaluation capabilities.

Typical extension points:

- add a new parser or chunker under `adapters/` and register it in `registry.py`
- add new metrics under `metrics/parser/` or `metrics/chunker/`
- add new stage orchestration behavior in `runners/pipeline.py` and `runners/runner.py`
- add new report output formats under `reporters/`

If `src/evaluation` gains new top-level subdirectories or becomes a dependency of other modules, also update [project_structure.md](project_structure.md) and [AGENTS.md](../../AGENTS.md).
