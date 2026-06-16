---
title: "Markdown Parser to Splitter Integration Fixture"
author: "Codex"
date: "2026-04-18"
---

# Overview
This opening paragraph mixes plain text with an inline image ![Architecture Inline](https://cdn.test.local/inline-architecture.png) so the parser keeps it inside a paragraph element and the vision mock can append a description for visual review.

![Hero Dashboard](https://cdn.test.local/hero-dashboard.png)

## Quoted Insight
> Retrieval quality improves when chunk boundaries respect structure.
> Oversized narrative sections should wait for the next mixed-aware Stage 2 design.

## Action Checklist
- Collect parser output carefully
- Preserve metadata for headings and source files
- Keep isolated blocks independent

1. Parse markdown into structured elements
2. Enrich tables and images with mocked network results
3. Preserve oversized narrative sections for the next Stage 2 design

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

Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation. Query planning keeps entity mentions attached to nearby evidence, preserves heading cues for retrieval scoring, reduces accidental topic drift, and leaves operators with a stable document narrative during evaluation.

Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context. Evidence packaging keeps benchmark summaries close to the surrounding claims, ensures evaluators can inspect assumptions quickly, limits brittle fragment boundaries, and helps reviewers compare nearby reasoning without losing context.

Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services. Incident coordination shifts the topic toward paging policy, rollback sequencing, legal communication checklists, stakeholder updates, and night shift fatigue when production failures cascade across services.

Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact. Recovery rehearsal stays with the incident theme by focusing on postmortem ownership, backlog triage, responder rotation, service warmup timing, and communication templates for severe customer impact.

---
