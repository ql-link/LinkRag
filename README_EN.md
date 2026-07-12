<div align="center">

# LinkRag

An enterprise-grade RAG system for everyone — turn complex documents into knowledge you can talk to.

</div>

<p align="center">
  <a href="./README.md">简体中文</a> · <b>English</b>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white">
  <img alt="Kafka" src="https://img.shields.io/badge/Kafka-MQ-231F20?logo=apachekafka&logoColor=white">
  <img alt="Qdrant" src="https://img.shields.io/badge/Qdrant-Dense%20%26%20Sparse-DC244C">
  <img alt="Manticore Search" src="https://img.shields.io/badge/Manticore-BM25-ffcc00">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-blue">
</p>

<p align="center">
  <a href="http://linkrag.cn/"><img alt="Live Demo linkrag.cn" src="https://img.shields.io/badge/Live%20Demo-linkrag.cn-c8a06a?style=for-the-badge&logo=googlechrome&logoColor=white"></a>
</p>

<p align="center">
  <img alt="LinkRag system overview" src="./docs/assets/sketches/sketch-architecture.png" width="840">
</p>

## What is LinkRag?

`LinkRag` is an enterprise-grade RAG system that lets anyone turn their own documents into a conversational knowledge base — covering the full pipeline from document ingestion, parsing, chunking, and vectorization to retrieval and answer generation.

This repository is the **Python RAG service** at its core, and the engine of the whole system: it parses documents in all kinds of complex formats into structured Markdown, splits them semantically into retrievable knowledge units, and builds three indexes — dense, sparse, and full-text. At query time it recalls across multiple paths in parallel, fuses, and reranks, finally producing grounded answers based only on what was actually retrieved. The entire process integrates asynchronously with a Java business system over a message queue — the business side only dispatches tasks and reads terminal states, without needing to know how parsing and retrieval work inside.

For capability details, see the technical docs: [File Parsing](./docs/internals/file_parser.md) · [Chunking](./docs/internals/chunking.md) · [Vectorization](./docs/internals/vectorization.md) · [Recall](./docs/internals/recall_pipeline.md).

## Key Features

From parsing to Q&A, every stage is built in-house, with extensive engineering trade-offs made for the real-world complexity of enterprise documents. The seven points below are where LinkRag stands apart from "gluing a few open-source libraries together."

**1. Complex documents in, clean knowledge out — deep document understanding**

Enterprise documents are never tidy: PDFs with tangled layouts, tables with merged cells, web pages stuffed with images and ads. LinkRag parses PDF, Word, and HTML uniformly into structured Markdown, picking a dedicated engine per format — PDFs choose among MinerU (precise parsing), OpenDataLoader, and PyMuPDF along a configurable fallback chain; HTML first uses trafilatura to locate the main content and strip navigation and boilerplate, then an in-house renderer faithfully restores tables, images, and lists, degrading complex structures like merged cells and nested tables into "record-style Markdown" rather than dropping them. Images are stored in object storage and can be further enriched by a vision model. Large files are streamed to disk throughout parsing, never loading the whole source into memory.

<p align="center">
  <img alt="File parsing: heterogeneous formats unified into Markdown" src="./docs/assets/sketches/sketch-file-parse.png" width="680">
</p>

<p align="center">
  <img alt="Markdown parsing and enhancement" src="./docs/assets/sketches/sketch-markdown.png" width="680">
</p>

**2. Chunk it right, or you'll never retrieve it — structure-aware hierarchical chunking**

The ceiling of retrieval quality is set the moment you chunk. LinkRag avoids crude fixed-length truncation and chunks in two stages instead: first it draws candidate boundaries by heading level and a soft token floor, then a semantic refinement algorithm (TextTiling depth valleys) cuts where the topic actually shifts. Tables, code, formulas, and images are marked as "protected elements" and kept whole, never cut in half; tables and images also spawn independently retrievable derived fragments, so "that table in section 3" can be hit on its own. Every chunk carries its own heading trail as a context anchor.

<p align="center">
  <img alt="Structure-aware hierarchical chunking" src="./docs/assets/sketches/sketch-chunking.png" width="680">
</p>

**3. Three retrieval paths, each to its strength — hybrid search + RRF fusion**

No single retrieval method wins at everything. LinkRag runs three paths at once: dense vectors (Qdrant, strong at semantic similarity), sparse vectors (lexical weights, strong at exact term and keyword matching), and BM25 full-text (Manticore). The three fire in parallel; if one times out or errors, a fault-tolerance policy degrades gracefully without dragging down the whole, then RRF (which looks only at rank, not raw scores) fuses physically incomparable scores stably. The recall path is a pluggable protocol — adding GraphRAG or a wiki later takes only implementing one interface; after fusion, a rerank stage can refine results, automatically falling back to RRF order when the rerank model is unavailable.

<p align="center">
  <img alt="Three-path hybrid recall + RRF fusion" src="./docs/assets/sketches/sketch-recall.png" width="680">
</p>

**4. Answers you can trace, not invented — hallucination-resistant streaming Q&A**

The biggest fear in RAG is "confidently making things up." LinkRag fills retrieved passages back into context, assembles them into a numbered context within a token budget, and injects it into the prompt, requiring the model to answer only from these passages and to clearly say "cannot answer" when there is no basis. Answers stream back token by token over SSE; terminal-state semantics are strictly distinguished: zero hits take the "no answer" branch, generation failures are reported honestly, and a response with no answer is never disguised as success. Q&A uses the model configured by the requesting user, never silently falling back to a system default.

**5. Ingestion survives interruptions, failures resume — a reliable processing pipeline**

Ingesting one document goes through six steps (cleaning → chunking → vectorization → pre-tokenization → BM25 indexing → sparse vectorization), and any step can fail due to a flaky external service. LinkRag treats MySQL as the authoritative source of truth and persists the state of every step: any stage failure is terminal, and on retry it resumes from the first unfinished stage, skipping the ones that already succeeded; a unique index on task_id ensures the same task is never processed twice, and retries use CAS to claim the task and prevent concurrent duplicate execution. Vector and full-text indexes are both rebuildable replicas; once they drift from the source of truth, a compensation flow reconverges them.

After chunking, the dense, sparse, and BM25 indexes are built in parallel; the BM25 path first goes through pre-tokenization — the indexing side and the recall side share the same tokenizer, so the term distribution never drifts:

<p align="center">
  <img alt="Three indexes built in parallel" src="./docs/assets/sketches/sketch-indexing.png" width="680">
</p>

**6. One service, every tenant their own model — decoupled integration + per-user config**

LinkRag integrates asynchronously with a Java business system over a message queue; the business side only dispatches tasks and reads terminal states, never coupling to the parsing implementation. It is multi-tenant by design: the five capabilities — Embedding, Chat, Vision, Rerank, and sparse encoding — are each resolved by the requesting user's own config, so different users can use different models; parsing behavior is also configurable per dataset (PDF backend, chunking parameters, enhancement switches). Each user's vector data is hash-routed into an isolated bucket, never interfering with others.

<p align="center">
  <img alt="LLM integration: a unified adapter layer dispatched by protocol" src="./docs/assets/sketches/sketch-llm-adapter.png" width="680">
</p>

**7. Declare dependencies, parallelize automatically — a lightweight DAG orchestrator**

The project ships a business-agnostic, lightweight DAG orchestration kernel. Each node only declares what artifacts it "requires" and "provides"; the engine derives the dependencies, arranges them into a directed acyclic graph, and catches definition errors — cycles, duplicate artifacts, dangling dependencies — at startup. At runtime, mutually independent nodes run concurrently (with a concurrency cap), while completion events advance serially to avoid duplicate scheduling; nodes marked as allowed-to-fail won't drag down the whole. It supports resuming from a previous run — successful nodes are skipped, artifacts needed downstream are `restore`d on demand, and the previous run is read-only; runtime state can be persisted to MySQL for cross-process recovery.

<p align="center">
  <img alt="Lightweight DAG orchestration" src="./docs/assets/sketches/sketch-dag.png" width="680">
</p>

## Live Demo

Live at [http://linkrag.cn/](http://linkrag.cn/). Upload documents, build a knowledge base automatically, ask questions directly about the content, and get answers streamed token by token, traced back to the source passages.

<p align="center">
  <a href="http://linkrag.cn/"><img alt="LinkRag landing page" src="./docs/assets/screenshots/screenshot-landing.png" width="880"></a>
</p>

<p align="center">
  <img alt="Chat Q&A interface: answers stream token by token and trace back to retrieved passages" src="./docs/assets/screenshots/screenshot-chat.png" width="880">
</p>

## Related Repositories

LinkRag is built from three repositories working together:

| Repository | Role |
| --- | --- |
| [ql-link/LinkRag](https://github.com/ql-link/LinkRag) (this repo) | Python RAG service: document parsing, chunking, vectorization, indexing, and recall |
| [ql-link/LinkRag-Service](https://github.com/ql-link/LinkRag-Service) | Java admin backend: business orchestration, task dispatch, and terminal-state collection |
| [ql-link/LinkRag-Web](https://github.com/ql-link/LinkRag-Web) | Frontend: knowledge base management and interactive UI |

## Architecture Overview

LinkRag centers on this repo's Python RAG service; the frontend and Java admin backend collaborate on the business side, integrate asynchronously with the RAG service over a message queue, and data lands in shared infrastructure. See the overview diagram at the top.

- **External collaboration boundary**: the frontend and Java admin backend handle business orchestration and interact with the RAG service only via the message queue (Java dispatches `parse_task` to trigger parsing; terminal states are written to the shared database and polled by the business side), never coupling directly to the parsing implementation.
- **In-repo main pipeline**: document ingestion → parsing → Markdown → chunking → vectorization → indexing/recall, with state maintained in MySQL to support failure compensation and consistency recovery.

### Parse Pipeline

Document ingestion runs a six-stage state machine; any stage failure is terminal and its failure reason is persisted. For full state semantics, see [Parse Task State Machine](./docs/internals/parse_task_pipeline.md) and [Parse Pipeline Architecture](./docs/internals/pipeline_architecture.md).

### Recall Pipeline

The query side fires multiple Retrievers in parallel, converges them under a fault-tolerance policy, then does a coarse RRF fusion. See [Recall Pipeline](./docs/internals/recall_pipeline.md).

## Documentation

For full navigation, see [docs/README.md](./docs/README.md). Common entry points:

- **External contracts**: [HTTP](./docs/api/http_contracts.md) / [MQ](./docs/api/mq_contracts.md) / [Error Codes](./docs/api/error_codes.md) / [MySQL](./docs/api/schemas/mysql.md) · [Qdrant](./docs/api/schemas/qdrant.md) schemas
- **Internals**: [file_parser](./docs/internals/file_parser.md) / [chunking](./docs/internals/chunking.md) / [vectorization](./docs/internals/vectorization.md) / [recall_pipeline](./docs/internals/recall_pipeline.md) / [workflow_engine](./docs/internals/workflow_engine.md) / [mq](./docs/internals/mq.md)
- **Deployment & configuration**: [deploy](./docs/ops/deploy.md) / [configure](./docs/ops/configure.md)
- **Contributing**: [docs/contributing.md](./docs/contributing.md) — branching, commits, testing, migrations, doc sync
- **Project entry (AI / new members)**: [CLAUDE.md](./CLAUDE.md)

## License

Released under the MIT License.
