# Markdown Parser -> Splitter Visualization

## Overview

- Fixture: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Source file recorded by parser: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element count: `30`
- Final chunk count: `6`
- Vision mock calls: `1`
- Table mock calls: `1`
- Embedding calls: `1`

## Element Coverage

| Index | Type | Lines | Metadata |
| ---: | --- | --- | --- |
| 0 | `front_matter` | `L0-L4` | `{}` |
| 1 | `heading` | `L6-L6` | `{"heading_level": 1, "heading_text": "Overview"}` |
| 2 | `paragraph` | `L7-L7` | `{}` |
| 3 | `image` | `L9-L9` | `{"alt": "Hero Dashboard", "url": "https://cdn.test.local/hero-dashboard.png"}` |
| 4 | `heading` | `L11-L11` | `{"heading_level": 2, "heading_text": "Quoted Insight"}` |
| 5 | `blockquote` | `L12-L14` | `{}` |
| 6 | `heading` | `L15-L15` | `{"heading_level": 2, "heading_text": "Action Checklist"}` |
| 7 | `list` | `L16-L23` | `{}` |
| 8 | `heading` | `L24-L24` | `{"heading_level": 2, "heading_text": "Code Sample"}` |
| 9 | `paragraph` | `L25-L25` | `{}` |
| 10 | `code_block` | `L27-L32` | `{"language": "python"}` |
| 11 | `heading` | `L34-L34` | `{"heading_level": 2, "heading_text": "Metrics Table"}` |
| 12 | `paragraph` | `L35-L35` | `{}` |
| 13 | `table` | `L37-L41` | `{}` |
| 14 | `heading` | `L43-L43` | `{"heading_level": 2, "heading_text": "Math Notes"}` |
| 15 | `paragraph` | `L44-L44` | `{}` |
| 16 | `math_block` | `L46-L48` | `{}` |
| 17 | `math_block` | `L50-L52` | `{}` |
| 18 | `heading` | `L54-L54` | `{"heading_level": 2, "heading_text": "Deep Dive"}` |
| 19 | `paragraph` | `L55-L55` | `{}` |
| 20 | `paragraph` | `L57-L57` | `{}` |
| 21 | `paragraph` | `L59-L59` | `{}` |
| 22 | `paragraph` | `L61-L61` | `{}` |
| 23 | `heading` | `L63-L63` | `{"heading_level": 2, "heading_text": "Semantic Pressure Test"}` |
| 24 | `paragraph` | `L64-L64` | `{}` |
| 25 | `paragraph` | `L66-L66` | `{}` |
| 26 | `paragraph` | `L68-L68` | `{}` |
| 27 | `paragraph` | `L70-L70` | `{}` |
| 28 | `paragraph` | `L72-L72` | `{}` |
| 29 | `hr` | `L74-L74` | `{}` |

## Mock Call Summary

### Vision

```json
[
  {
    "image_urls": [
      "https://cdn.test.local/hero-dashboard.png",
      "https://cdn.test.local/inline-architecture.png"
    ],
    "source_file": "tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md"
  }
]
```

### Table

```json
[
  {
    "tables": [
      "| Metric | Value | Trend |\n| :--- | ---: | :---: |\n| Recall | 0.82 | up |\n| LatencyMs | 128 | stable |\n| Coverage | 0.97 | up |"
    ],
    "source_file": "tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md"
  }
]
```

### Embedding

```json
[
  {
    "texts": [
      "# Overview\n\nThis opening paragraph mixes plain text with an inline image ![Architecture Inline](https://cdn.test.local/inline-architecture.png) so the parser keeps it inside a paragraph element and the vision mock can append a description for visual review.\n\n[视觉描述: A compact architecture sketch that highlights parser, splitter, and vector stages.]\n\n![Hero Dashboard](https://cdn.test.local/hero-dashboard.png)\n\n[视觉描述: A dashboard screenshot with cards, charts, and highlighted retrieval metrics.]\n\n## Quoted Insight\n\n> Retrieval quality improves when chunk boundaries respect structure.\n> Semantic splitting should only refine the oversized narrative sections.\n\n\n## Action Checklist\n\n- Collect parser output carefully\n- Preserve metadata for headings and source files\n- Keep isolated blocks independent\n\n1. Parse markdown into structured elements\n2. Enrich tables and images with mocked network results\n3. Split oversized narrative sections semantically\n\n\n## Code Sample\n\nThe code fence below should become its own isolated chunk.\n\n```python def summarize_metrics(total_requests: int, failures: int) -> float: if total_requests == 0: return 0.0 return round((total_requests - failures) / total_requests, 4) ``` ## Metrics Table The table block below should stay isolated and also receive a mocked table summary. | Metric | Value | Trend | | :--- | ---: | :---: | | Recall | 0.82 | up | | LatencyMs | 128",
      "Semantic splitting should only refine the oversized narrative sections.\n\n\n## Action Checklist\n\n- Collect parser output carefully\n- Preserve metadata for headings and source files\n- Keep isolated blocks independent\n\n1. Parse markdown into structured elements\n2. Enrich tables and images with mocked network results\n3. Split oversized narrative sections semantically\n\n\n## Code Sample\n\nThe code fence below should become its own isolated chunk.\n\n```python\ndef summarize_metrics(total_requests: int, failures: int) -> float:\n    if total_requests == 0:\n        return 0.0\n    return round((total_requests - failures) / total_requests, 4)\n```\n\n## Metrics Table\n\nThe table block below should stay isolated and also receive a mocked table summary.\n\n| Metric | Value | Trend |\n| :--- | ---: | :---: |\n| Recall | 0.82 | up |\n| LatencyMs | 128 | stable |\n| Coverage | 0.97 | up |\n\n[表格总结: The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline.]\n\n## Math Notes\n\nThe parser should also isolate math blocks.\n\n$$\nE = mc^2\n$$\n\n\\[\n\\int_0^1 x^2 dx = \\frac{1}{3}\n\\]\n\n## Deep Dive\n\nChunking quality depends on keeping the overview sentence near the heading for retrieval and human review in realistic systems.\n\nThe next paragraph continues the same topic with nearby wording so the semantic splitter should still keep it close during chunk construction. A different subsection discusses incident response runbooks, rollback plans, pager fatigue, and on-call escalation details for critical outages. The closing paragraph stays in the incident response theme and should therefore remain with the previous paragraph after splitting. ## Semantic Pressure Test Calibration",
      "| 0.97 | up |\n\n[表格总结: The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline.]\n\n## Math Notes\n\nThe parser should also isolate math blocks.\n\n$$\nE = mc^2\n$$\n\n\\[\n\\int_0^1 x^2 dx = \\frac{1}{3}\n\\]\n\n## Deep Dive\n\nChunking quality depends on keeping the overview sentence near the heading for retrieval and human review in realistic systems.\n\nThe next paragraph continues the same topic with nearby wording so the semantic splitter should still keep it close during chunk construction.\n\nA different subsection discusses incident response runbooks, rollback plans, pager fatigue, and on-call escalation details for critical outages.\n\nThe closing paragraph stays in the incident response theme and should therefore remain with the previous paragraph after splitting.\n\n## Semantic Pressure Test\n\nCalibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis.\n\nQuery planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached",
      "context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis.\n\nQuery planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation.\n\nEvidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close",
      "a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation.\n\nEvidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context.\n\nIncident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder",
      "compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context.\n\nIncident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services.\n\nRecovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact."
    ],
    "model": "visual-test-embedding",
    "kwargs": {}
  }
]
```

## Final Chunks

| Chunk | Strategy | Heading Trail | Lines | Cached | Prev Ctx | Next Ctx | Vector Preview |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 0 | `candidate_boundary` | `Overview > Code Sample` | `L6-L25` | `False` | `0` | `64` | `0.3472, 0.7781, 0.3962, 0.8987` |
| 1 | `candidate_boundary` | `Overview > Deep Dive` | `L27-L55` | `False` | `64` | `64` | `0.3575, 0.8718, 0.0164, 0.1303` |
| 2 | `candidate_boundary` | `Overview > Semantic Pressure Test` | `L57-L64` | `False` | `64` | `64` | `0.7863, 0.8879, 0.8826, 0.5483` |
| 3 | `candidate_boundary` | `Overview > Semantic Pressure Test` | `L66-L66` | `False` | `64` | `64` | `0.0975, 0.2753, 0.0848, 0.5624` |
| 4 | `candidate_boundary` | `Overview > Semantic Pressure Test` | `L68-L68` | `False` | `64` | `64` | `0.6311, 0.4808, 0.1865, 0.4029` |
| 5 | `candidate_boundary` | `Overview > Semantic Pressure Test` | `L70-L72` | `False` | `64` | `0` | `0.4904, 0.4763, 0.7377, 0.0930` |

### Chunk 0

- Strategy: `candidate_boundary`
- Heading trail: `['Overview', 'Code Sample']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['blockquote', 'heading', 'image', 'list', 'paragraph']`
- Context prev tokens: `0`
- Context next tokens: `64`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.347247, 0.778140, 0.396232, 0.898722`

````markdown
# Overview

This opening paragraph mixes plain text with an inline image ![Architecture Inline](https://cdn.test.local/inline-architecture.png) so the parser keeps it inside a paragraph element and the vision mock can append a description for visual review.

[视觉描述: A compact architecture sketch that highlights parser, splitter, and vector stages.]

![Hero Dashboard](https://cdn.test.local/hero-dashboard.png)

[视觉描述: A dashboard screenshot with cards, charts, and highlighted retrieval metrics.]

## Quoted Insight

> Retrieval quality improves when chunk boundaries respect structure.
> Semantic splitting should only refine the oversized narrative sections.


## Action Checklist

- Collect parser output carefully
- Preserve metadata for headings and source files
- Keep isolated blocks independent

1. Parse markdown into structured elements
2. Enrich tables and images with mocked network results
3. Split oversized narrative sections semantically


## Code Sample

The code fence below should become its own isolated chunk.

```python def summarize_metrics(total_requests: int, failures: int) -> float: if total_requests == 0: return 0.0 return round((total_requests - failures) / total_requests, 4) ``` ## Metrics Table The table block below should stay isolated and also receive a mocked table summary. | Metric | Value | Trend | | :--- | ---: | :---: | | Recall | 0.82 | up | | LatencyMs | 128
````

### Chunk 1

- Strategy: `candidate_boundary`
- Heading trail: `['Overview', 'Deep Dive']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['code_block', 'heading', 'math_block', 'paragraph', 'table']`
- Context prev tokens: `64`
- Context next tokens: `64`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.357534, 0.871777, 0.016407, 0.130276`

````markdown
Semantic splitting should only refine the oversized narrative sections.


## Action Checklist

- Collect parser output carefully
- Preserve metadata for headings and source files
- Keep isolated blocks independent

1. Parse markdown into structured elements
2. Enrich tables and images with mocked network results
3. Split oversized narrative sections semantically


## Code Sample

The code fence below should become its own isolated chunk.

```python
def summarize_metrics(total_requests: int, failures: int) -> float:
    if total_requests == 0:
        return 0.0
    return round((total_requests - failures) / total_requests, 4)
```

## Metrics Table

The table block below should stay isolated and also receive a mocked table summary.

| Metric | Value | Trend |
| :--- | ---: | :---: |
| Recall | 0.82 | up |
| LatencyMs | 128 | stable |
| Coverage | 0.97 | up |

[表格总结: The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline.]

## Math Notes

The parser should also isolate math blocks.

$$
E = mc^2
$$

\[
\int_0^1 x^2 dx = \frac{1}{3}
\]

## Deep Dive

Chunking quality depends on keeping the overview sentence near the heading for retrieval and human review in realistic systems.

The next paragraph continues the same topic with nearby wording so the semantic splitter should still keep it close during chunk construction. A different subsection discusses incident response runbooks, rollback plans, pager fatigue, and on-call escalation details for critical outages. The closing paragraph stays in the incident response theme and should therefore remain with the previous paragraph after splitting. ## Semantic Pressure Test Calibration
````

### Chunk 2

- Strategy: `candidate_boundary`
- Heading trail: `['Overview', 'Semantic Pressure Test']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['heading', 'paragraph']`
- Context prev tokens: `64`
- Context next tokens: `64`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.786295, 0.887876, 0.882642, 0.548255`

````markdown
| 0.97 | up |

[表格总结: The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline.]

## Math Notes

The parser should also isolate math blocks.

$$
E = mc^2
$$

\[
\int_0^1 x^2 dx = \frac{1}{3}
\]

## Deep Dive

Chunking quality depends on keeping the overview sentence near the heading for retrieval and human review in realistic systems.

The next paragraph continues the same topic with nearby wording so the semantic splitter should still keep it close during chunk construction.

A different subsection discusses incident response runbooks, rollback plans, pager fatigue, and on-call escalation details for critical outages.

The closing paragraph stays in the incident response theme and should therefore remain with the previous paragraph after splitting.

## Semantic Pressure Test

Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis.

Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached
````

### Chunk 3

- Strategy: `candidate_boundary`
- Heading trail: `['Overview', 'Semantic Pressure Test']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['paragraph']`
- Context prev tokens: `64`
- Context next tokens: `64`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.097494, 0.275307, 0.084822, 0.562432`

````markdown
context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis.

Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation.

Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close
````

### Chunk 4

- Strategy: `candidate_boundary`
- Heading trail: `['Overview', 'Semantic Pressure Test']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['paragraph']`
- Context prev tokens: `64`
- Context next tokens: `64`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.631056, 0.480819, 0.186461, 0.402936`

````markdown
a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation.

Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context.

Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder
````

### Chunk 5

- Strategy: `candidate_boundary`
- Heading trail: `['Overview', 'Semantic Pressure Test']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['paragraph']`
- Context prev tokens: `64`
- Context next tokens: `0`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.490415, 0.476334, 0.737722, 0.092984`

````markdown
compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context.

Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services.

Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact.
````
