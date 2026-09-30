# LinkRag 评测原始结果

打包日期：2026-09-30。来源仓库：LinkRag-Eval @ 0de8488。

单源报告为原始运行产物的逐字节拷贝；`r09.json`、`r10.json` 为派生打包文件，
`_bundle.files` 记录每个子文件的原始路径与 SHA-256，`files` 下为未改动的原内容。

## 文件

| 报告 ID | 报告 | 大小 | 原始路径 | SHA-256 |
| --- | --- | ---: | --- | --- |
| `r13.json` | R13 · 前 30 chunk 文本重排 | 4,263 B | `runs/benchmarks/scifact-20260929/rerank_top30/results.json` | `46513f39fbe53036ef1a4611fbdef8d553b82aa013cc81be9053106e296c0471` |
| `r12.json` | R12 · 对比 WeKnora 原生检索 | 4,438 B | `runs/benchmarks/scifact-20260929/weknora/comparison.json` | `bcd1c544ceaa8d1e5a2a34fc7eab3f2c474b857bcdc1729f0eccda4868cf0a8d` |
| `r11.json` | R11 · LambdaMART 排序 | 4,060 B | `runs/benchmarks/scifact-20260929/ltr/test_comparison.json` | `dd71d685e2dd3aa87ee3c19f220eb116033d4d7256a1cb93dc5552996af0850a` |
| `r10.json` | R10 · SciFact 三路消融（summary 为召回指标，audit 为延迟 P50/P95） | 6,217 B | `runs/benchmarks/scifact-20260929/evaluation/summary.json` | `46f580f536ba4456d028101083fc5c83977c62d8f2c180034386f47cc7effe09` |
|  | |  | `runs/benchmarks/scifact-20260929/evaluation/audit.json` | `bbd0386a2bf4c80fe6695f0604e5e3c3980b30686542c7c65ce9d0127bd67286` |
| `blind-v5.json` | Blind v5 生产契约验收 | 201,984 B | `runs/golden_v2/blind_v5_20260728/blind/final_result.json` | `e98d98b9f24ffdabd14b3d8abf6dc5f6c53fc582ce41e160e58d5412e3c92d3b` |
| `blind-v4.json` | Blind v4 最终验收 | 199,099 B | `runs/golden_v2/blind_v4_20260724/blind/final_result.json` | `8a35e292a3f63b964dbb1fc508df23b3e38697c4aaf4933a65565d44db923bae` |
| `r09.json` | R09 · 多路召回正式对照（仅稠密 / 稠密+BM25 / 三路） | 3,364,325 B | `runs/results/route-dense-only-20260704-top10.json` | `c9fa141c6bf77108d13cc5d2542722812a0b7ff6e9881b0ccb8742382d416224` |
|  | |  | `runs/results/route-dense-bm25-20260704-top10.json` | `0aad3e2bb90cd74217ca46daadf3735f1a1b8f1a2632d4a14898ed40c4bedf26` |
|  | |  | `runs/results/route-dense-sparse-bm25-20260704-top10.json` | `aa8a0399fe622e26f45fdcdd2df4829a17e31f3839d31f5f96c34c4e5aa2b503` |
| `fusion.json` | 融合策略对照 | 1,624 B | `runs/tuning/fusion_compare_combined_4domain_clean_20260702.json` | `78ccff90f1682c222c70cb6670b039133b4835cdd2654577d2126187c0371b5f` |

## 口径

- SciFact（r10–r13）：BEIR SciFact 官方包，5,183 篇文档，官方 test 300 题；源文档级计分，
  同一文档的多个 chunk 只计一次；`ndcg_binary@10` 为二值相关度 nDCG。
- r10 延迟：`evaluation/audit.json` 的 `retrieval_elapsed_ms.p50_linear` / `p95_linear`，页面取整毫秒。
- 四域基线（r09、fusion）：combined_4domain_clean，394 题，3,200 chunks；页面保留 4 位小数。
- Blind（blind-v4、blind-v5）：`baseline_mrr` / `ltr_mrr`，页面以百分数保留 2 位。

## 暂缺

以下报告的原始产物在当前备份中未找到，页面对应下载按钮为禁用状态：

- `corpus-size`：运行 20260621-0311-3eb5545-doubao-clean-3way / 20260622-2142-a017e34-doubao-clean-3way-2k
- `two-vs-three`：运行 20260620-1723-3eb5545-doubao-800-5domain / 20260620-1939-3eb5545-doubao-800-3way
- `sparse-models`：报告未给出运行 ID
