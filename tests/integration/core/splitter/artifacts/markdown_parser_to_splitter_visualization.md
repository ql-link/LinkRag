# Markdown Parser -> Splitter Visualization

## Overview

- Fixture: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Source file recorded by parser: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element count: `30`
- Final chunk count: `14`
- Vision mock calls: `1`
- Table mock calls: `1`
- Embedding calls: `2`

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
      "## Semantic Pressure Test",
      "Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis.",
      "Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation.",
      "Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context.",
      "Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services.",
      "Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact."
    ],
    "model": null,
    "kwargs": {}
  },
  {
    "texts": [
      "# Overview\n\nThis opening paragraph mixes plain text with an inline image ![Architecture Inline](https://cdn.test.local/inline-architecture.png) so the parser keeps it inside a paragraph element and the vision mock can append a description for visual review.\n\n[视觉描述: A compact architecture sketch that highlights parser, splitter, and vector stages.]\n\n![Hero Dashboard](https://cdn.test.local/hero-dashboard.png) [视觉描述: A dashboard screenshot with cards, charts, and highlighted retrieval metrics.]",
      "# Overview\n\nThis opening paragraph mixes plain text with an inline image ![Architecture Inline](https://cdn.test.local/inline-architecture.png) so the parser keeps it inside a paragraph element and the vision mock can append a description for visual review.\n\n[视觉描述: A compact architecture sketch that highlights parser, splitter, and vector stages.]\n\n![Hero Dashboard](https://cdn.test.local/hero-dashboard.png)\n\n[视觉描述: A dashboard screenshot with cards, charts, and highlighted retrieval metrics.]\n\n## Quoted Insight > Retrieval quality improves when chunk boundaries respect structure. > Semantic splitting should only refine the oversized narrative sections.",
      "![Hero Dashboard](https://cdn.test.local/hero-dashboard.png)\n\n[视觉描述: A dashboard screenshot with cards, charts, and highlighted retrieval metrics.]\n\n## Quoted Insight\n\n> Retrieval quality improves when chunk boundaries respect structure.\n> Semantic splitting should only refine the oversized narrative sections.\n\n\n## Action Checklist - Collect parser output carefully - Preserve metadata for headings and source files - Keep isolated blocks independent 1. Parse markdown into structured elements 2. Enrich tables and images with mocked network results 3. Split oversized narrative sections semantically",
      "## Quoted Insight\n\n> Retrieval quality improves when chunk boundaries respect structure.\n> Semantic splitting should only refine the oversized narrative sections.\n\n## Action Checklist\n\n- Collect parser output carefully\n- Preserve metadata for headings and source files\n- Keep isolated blocks independent\n\n1. Parse markdown into structured elements\n2. Enrich tables and images with mocked network results\n3. Split oversized narrative sections semantically\n\n\n## Code Sample The code fence below should become its own isolated chunk.",
      "## Action Checklist\n\n- Collect parser output carefully\n- Preserve metadata for headings and source files\n- Keep isolated blocks independent\n\n1. Parse markdown into structured elements\n2. Enrich tables and images with mocked network results\n3. Split oversized narrative sections semantically\n\n## Code Sample\n\nThe code fence below should become its own isolated chunk.\n\n```python def summarize_metrics(total_requests: int, failures: int) -> float: if total_requests == 0: return 0.0 return round((total_requests - failures) / total_requests, 4) ```",
      "## Code Sample\n\nThe code fence below should become its own isolated chunk.\n\n```python\ndef summarize_metrics(total_requests: int, failures: int) -> float:\n    if total_requests == 0:\n        return 0.0\n    return round((total_requests - failures) / total_requests, 4)\n```\n\n## Metrics Table The table block below should stay isolated and also receive a mocked table summary.",
      "```python\ndef summarize_metrics(total_requests: int, failures: int) -> float:\n    if total_requests == 0:\n        return 0.0\n    return round((total_requests - failures) / total_requests, 4)\n```\n\n## Metrics Table\n\nThe table block below should stay isolated and also receive a mocked table summary.\n\n| Metric | Value | Trend | | :--- | ---: | :---: | | Recall | 0.82 | up | | LatencyMs | 128 | stable | | Coverage | 0.97 | up | [表格总结: The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline.]",
      "## Metrics Table\n\nThe table block below should stay isolated and also receive a mocked table summary.\n\n| Metric | Value | Trend |\n| :--- | ---: | :---: |\n| Recall | 0.82 | up |\n| LatencyMs | 128 | stable |\n| Coverage | 0.97 | up |\n\n[表格总结: The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline.]\n\n## Math Notes The parser should also isolate math blocks.",
      "| Metric | Value | Trend |\n| :--- | ---: | :---: |\n| Recall | 0.82 | up |\n| LatencyMs | 128 | stable |\n| Coverage | 0.97 | up |\n\n[表格总结: The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline.]\n\n## Math Notes\n\nThe parser should also isolate math blocks.\n\n$$ E = mc^2 $$",
      "## Math Notes\n\nThe parser should also isolate math blocks.\n\n$$\nE = mc^2\n$$\n\n\\[ \\int_0^1 x^2 dx = \\frac{1}{3} \\]",
      "$$\nE = mc^2\n$$\n\n\\[\n\\int_0^1 x^2 dx = \\frac{1}{3}\n\\]\n\n## Deep Dive Chunking quality depends on keeping the overview sentence near the heading for retrieval and human review in realistic systems. The next paragraph continues the same topic with nearby wording so the semantic splitter should still keep it close during chunk construction. A different subsection discusses incident response runbooks, rollback plans, pager fatigue, and on-call escalation details for critical outages. The closing",
      "\\[\n\\int_0^1 x^2 dx = \\frac{1}{3}\n\\]\n\n## Deep Dive\n\nChunking quality depends on keeping the overview sentence near the heading for retrieval and human review in realistic systems.\n\nThe next paragraph continues the same topic with nearby wording so the semantic splitter should still keep it close during chunk construction.\n\nA different subsection discusses incident response runbooks, rollback plans, pager fatigue, and on-call escalation details for critical outages.\n\nThe closing paragraph stays in the incident response theme and should therefore remain with the previous paragraph after splitting.\n\n## Semantic Pressure Test Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains",
      "human review in realistic systems.\n\nThe next paragraph continues the same topic with nearby wording so the semantic splitter should still keep it close during chunk construction.\n\nA different subsection discusses incident response runbooks, rollback plans, pager fatigue, and on-call escalation details for critical outages.\n\nThe closing paragraph stays in the incident response theme and should therefore remain with the previous paragraph after splitting.\n\n## Semantic Pressure Test\n\nCalibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis.\n\nQuery planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation.\n\nEvidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context.\n\nIncident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder",
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
| 0 | `rule` | `Overview` | `L6-L7` | `False` | `0` | `13` | `0.4371, 0.4266, 0.6400, 0.9441` |
| 1 | `isolated` | `Overview` | `L9-L9` | `False` | `46` | `22` | `0.9155, 0.7214, 0.3417, 0.8444` |
| 2 | `rule` | `Overview > Quoted Insight` | `L11-L14` | `False` | `13` | `42` | `0.5940, 0.0905, 0.7829, 0.5679` |
| 3 | `rule` | `Overview > Action Checklist` | `L15-L23` | `False` | `22` | `13` | `0.2529, 0.6596, 0.0945, 0.2615` |
| 4 | `rule` | `Overview > Code Sample` | `L24-L25` | `False` | `42` | `22` | `0.0910, 0.6313, 0.4537, 0.9489` |
| 5 | `isolated` | `Overview > Code Sample` | `L27-L32` | `False` | `13` | `17` | `0.9728, 0.4878, 0.6448, 0.4158` |
| 6 | `rule` | `Overview > Metrics Table` | `L34-L35` | `False` | `22` | `50` | `0.1408, 0.5891, 0.5834, 0.2654` |
| 7 | `isolated` | `Overview > Metrics Table` | `L37-L41` | `False` | `17` | `10` | `0.5709, 0.2119, 0.3222, 0.0327` |
| 8 | `rule` | `Overview > Math Notes` | `L43-L44` | `False` | `50` | `5` | `0.2641, 0.3744, 0.1657, 0.4141` |
| 9 | `isolated` | `Overview > Math Notes` | `L46-L48` | `False` | `10` | `7` | `0.0186, 0.1877, 0.7101, 0.6793` |
| 10 | `isolated` | `Overview > Math Notes` | `L50-L52` | `False` | `5` | `64` | `0.0442, 0.9257, 0.7805, 0.1883` |
| 11 | `rule` | `Overview > Deep Dive` | `L54-L61` | `False` | `7` | `64` | `0.8191, 0.5244, 0.3819, 0.9920` |
| 12 | `semantic` | `Overview > Semantic Pressure Test` | `L63-L68` | `False` | `64` | `64` | `0.6519, 0.3505, 0.0224, 0.5572` |
| 13 | `semantic` | `Overview > Semantic Pressure Test` | `L70-L72` | `False` | `64` | `0` | `0.4904, 0.4763, 0.7377, 0.0930` |

### Chunk 0

- Strategy: `rule`
- Heading trail: `['Overview']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['heading', 'paragraph']`
- Context prev tokens: `0`
- Context next tokens: `13`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.437121, 0.426615, 0.640019, 0.944060`

````markdown
# Overview

This opening paragraph mixes plain text with an inline image ![Architecture Inline](https://cdn.test.local/inline-architecture.png) so the parser keeps it inside a paragraph element and the vision mock can append a description for visual review.

[视觉描述: A compact architecture sketch that highlights parser, splitter, and vector stages.]

![Hero Dashboard](https://cdn.test.local/hero-dashboard.png) [视觉描述: A dashboard screenshot with cards, charts, and highlighted retrieval metrics.]
````

### Chunk 1

- Strategy: `isolated`
- Heading trail: `['Overview']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['image']`
- Context prev tokens: `46`
- Context next tokens: `22`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.915549, 0.721412, 0.341730, 0.844369`

````markdown
# Overview

This opening paragraph mixes plain text with an inline image ![Architecture Inline](https://cdn.test.local/inline-architecture.png) so the parser keeps it inside a paragraph element and the vision mock can append a description for visual review.

[视觉描述: A compact architecture sketch that highlights parser, splitter, and vector stages.]

![Hero Dashboard](https://cdn.test.local/hero-dashboard.png)

[视觉描述: A dashboard screenshot with cards, charts, and highlighted retrieval metrics.]

## Quoted Insight > Retrieval quality improves when chunk boundaries respect structure. > Semantic splitting should only refine the oversized narrative sections.
````

### Chunk 2

- Strategy: `rule`
- Heading trail: `['Overview', 'Quoted Insight']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['blockquote', 'heading']`
- Context prev tokens: `13`
- Context next tokens: `42`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.593983, 0.090545, 0.782916, 0.567862`

````markdown
![Hero Dashboard](https://cdn.test.local/hero-dashboard.png)

[视觉描述: A dashboard screenshot with cards, charts, and highlighted retrieval metrics.]

## Quoted Insight

> Retrieval quality improves when chunk boundaries respect structure.
> Semantic splitting should only refine the oversized narrative sections.


## Action Checklist - Collect parser output carefully - Preserve metadata for headings and source files - Keep isolated blocks independent 1. Parse markdown into structured elements 2. Enrich tables and images with mocked network results 3. Split oversized narrative sections semantically
````

### Chunk 3

- Strategy: `rule`
- Heading trail: `['Overview', 'Action Checklist']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['heading', 'list']`
- Context prev tokens: `22`
- Context next tokens: `13`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.252865, 0.659588, 0.094547, 0.261462`

````markdown
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


## Code Sample The code fence below should become its own isolated chunk.
````

### Chunk 4

- Strategy: `rule`
- Heading trail: `['Overview', 'Code Sample']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['heading', 'paragraph']`
- Context prev tokens: `42`
- Context next tokens: `22`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.090953, 0.631302, 0.453661, 0.948870`

````markdown
## Action Checklist

- Collect parser output carefully
- Preserve metadata for headings and source files
- Keep isolated blocks independent

1. Parse markdown into structured elements
2. Enrich tables and images with mocked network results
3. Split oversized narrative sections semantically

## Code Sample

The code fence below should become its own isolated chunk.

```python def summarize_metrics(total_requests: int, failures: int) -> float: if total_requests == 0: return 0.0 return round((total_requests - failures) / total_requests, 4) ```
````

### Chunk 5

- Strategy: `isolated`
- Heading trail: `['Overview', 'Code Sample']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['code_block']`
- Context prev tokens: `13`
- Context next tokens: `17`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.972803, 0.487756, 0.644751, 0.415772`

````markdown
## Code Sample

The code fence below should become its own isolated chunk.

```python
def summarize_metrics(total_requests: int, failures: int) -> float:
    if total_requests == 0:
        return 0.0
    return round((total_requests - failures) / total_requests, 4)
```

## Metrics Table The table block below should stay isolated and also receive a mocked table summary.
````

### Chunk 6

- Strategy: `rule`
- Heading trail: `['Overview', 'Metrics Table']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['heading', 'paragraph']`
- Context prev tokens: `22`
- Context next tokens: `50`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.140805, 0.589099, 0.583353, 0.265449`

````markdown
```python
def summarize_metrics(total_requests: int, failures: int) -> float:
    if total_requests == 0:
        return 0.0
    return round((total_requests - failures) / total_requests, 4)
```

## Metrics Table

The table block below should stay isolated and also receive a mocked table summary.

| Metric | Value | Trend | | :--- | ---: | :---: | | Recall | 0.82 | up | | LatencyMs | 128 | stable | | Coverage | 0.97 | up | [表格总结: The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline.]
````

### Chunk 7

- Strategy: `isolated`
- Heading trail: `['Overview', 'Metrics Table']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['table']`
- Context prev tokens: `17`
- Context next tokens: `10`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.570890, 0.211854, 0.322199, 0.032733`

````markdown
## Metrics Table

The table block below should stay isolated and also receive a mocked table summary.

| Metric | Value | Trend |
| :--- | ---: | :---: |
| Recall | 0.82 | up |
| LatencyMs | 128 | stable |
| Coverage | 0.97 | up |

[表格总结: The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline.]

## Math Notes The parser should also isolate math blocks.
````

### Chunk 8

- Strategy: `rule`
- Heading trail: `['Overview', 'Math Notes']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['heading', 'paragraph']`
- Context prev tokens: `50`
- Context next tokens: `5`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.264084, 0.374358, 0.165734, 0.414140`

````markdown
| Metric | Value | Trend |
| :--- | ---: | :---: |
| Recall | 0.82 | up |
| LatencyMs | 128 | stable |
| Coverage | 0.97 | up |

[表格总结: The metrics table shows healthy recall, stable latency, and broad coverage for the pipeline.]

## Math Notes

The parser should also isolate math blocks.

$$ E = mc^2 $$
````

### Chunk 9

- Strategy: `isolated`
- Heading trail: `['Overview', 'Math Notes']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['math_block']`
- Context prev tokens: `10`
- Context next tokens: `7`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.018600, 0.187728, 0.710064, 0.679263`

````markdown
## Math Notes

The parser should also isolate math blocks.

$$
E = mc^2
$$

\[ \int_0^1 x^2 dx = \frac{1}{3} \]
````

### Chunk 10

- Strategy: `isolated`
- Heading trail: `['Overview', 'Math Notes']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['math_block']`
- Context prev tokens: `5`
- Context next tokens: `64`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.044218, 0.925717, 0.780488, 0.188302`

````markdown
$$
E = mc^2
$$

\[
\int_0^1 x^2 dx = \frac{1}{3}
\]

## Deep Dive Chunking quality depends on keeping the overview sentence near the heading for retrieval and human review in realistic systems. The next paragraph continues the same topic with nearby wording so the semantic splitter should still keep it close during chunk construction. A different subsection discusses incident response runbooks, rollback plans, pager fatigue, and on-call escalation details for critical outages. The closing
````

### Chunk 11

- Strategy: `rule`
- Heading trail: `['Overview', 'Deep Dive']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['heading', 'paragraph']`
- Context prev tokens: `7`
- Context next tokens: `64`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.819149, 0.524409, 0.381874, 0.991987`

````markdown
\[
\int_0^1 x^2 dx = \frac{1}{3}
\]

## Deep Dive

Chunking quality depends on keeping the overview sentence near the heading for retrieval and human review in realistic systems.

The next paragraph continues the same topic with nearby wording so the semantic splitter should still keep it close during chunk construction.

A different subsection discusses incident response runbooks, rollback plans, pager fatigue, and on-call escalation details for critical outages.

The closing paragraph stays in the incident response theme and should therefore remain with the previous paragraph after splitting.

## Semantic Pressure Test Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains
````

### Chunk 12

- Strategy: `semantic`
- Heading trail: `['Overview', 'Semantic Pressure Test']`
- Source file: `tests/integration/core/splitter/fixtures/full_markdown_pipeline_fixture.md`
- Element types: `['heading', 'paragraph']`
- Context prev tokens: `64`
- Context next tokens: `64`
- Embedding model: `visual-test-embedding`
- Cached: `False`
- Vector preview: `0.651883, 0.350518, 0.022401, 0.557197`

````markdown
human review in realistic systems.

The next paragraph continues the same topic with nearby wording so the semantic splitter should still keep it close during chunk construction.

A different subsection discusses incident response runbooks, rollback plans, pager fatigue, and on-call escalation details for critical outages.

The closing paragraph stays in the incident response theme and should therefore remain with the previous paragraph after splitting.

## Semantic Pressure Test

Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis. Calibration review keeps retrieval evidence aligned with section intent, maintains stable context windows, protects citation anchors, and gives auditors a readable trail for incident analysis.

Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation.

Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context.

Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder
````

### Chunk 13

- Strategy: `semantic`
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
