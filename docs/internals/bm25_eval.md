# BM25 召回评测（ES / Qdrant / Manticore 对齐验证）

记录 Qdrant BM25 后端的召回质量评测——回答"切到 `BM25_BACKEND=qdrant` 后能否替代
ES 全文检索"。配套工具在 `scripts/dev/`，结论可复现。

> 评测全程只连本地 docker（Qdrant / ES），用独立 eval collection / index，跑完即删；
> 不连生产、不动业务 `kb_bucket_*` 与业务 index。

## 评测工具

| 脚本 | 作用 |
| --- | --- |
| [calibrate_bm25_avgdl.py](../../scripts/dev/calibrate_bm25_avgdl.py) | 扫真实语料统计 coarse/fine token 长度，校准 `BM25_AVGDL` / `BM25_AVGDL_FINE` |
| [fetch_cmteb_retrieval.py](../../scripts/dev/fetch_cmteb_retrieval.py) | 从 hf-mirror 下载 C-MTEB 中文检索集，转成 BEIR 格式 |
| [eval_bm25_recall.py](../../scripts/dev/eval_bm25_recall.py) | 召回评测：recall@k / nDCG@k / 后端 overlap@k；支持合成 / `--from-db` / `--from-beir` / `--with-es` / `--with-manticore` 及质量门禁 |

## 测了哪些

| 数据集 | 语言 | 标注 | 规模 | 说明 |
| --- | --- | --- | --- | --- |
| 合成语料 | 中文 | 字面 gold | 12 doc | 可复现基线，验证 fine-only 召回 |
| MySQL chunk | 中文 | self-retrieval | 109 | docker 里真实项目语料 |
| NFCorpus | 英文 | 人工 qrels | 3633 doc / 323 q | BEIR 标准集，难 query |
| CovidRetrieval | 中文 | 人工 qrels | 采样 1 万 / 949 q | C-MTEB 标准集，中文问答 |

## 结论

| 数据集 | Qdrant R@10 / nDCG | Manticore R@10 / nDCG | ES R@10 / nDCG | Manticore↔Qdrant overlap@10 |
| --- | --- | --- | --- | --- |
| NFCorpus（英文） | 0.156 / 0.323 | 0.156 / 0.323 | 0.154 / 0.322 | 0.934 |
| CovidRetrieval（中文） | 0.914 / 0.815 | 0.919 / 0.818 | 0.918 / 0.819 | 0.861 |

1. **Qdrant 与 ES 检索质量等同**：中英文上 recall@10 / nDCG@10 差异都在 1 个百分点内。
2. **实现是标准 BM25**：NFCorpus nDCG@10=0.323 与 BEIR 公布的 BM25 基线（≈0.325）几乎
   吻合，侧面交叉验证打分逻辑没写歪。
3. **中文 top-k 排序差异更大，但不影响召回集**：中文 overlap@10=0.789 明显低于英文
   0.941。原因是 Qdrant 用 sum 融合（`coarse_boost×coarse_BM25 + fine_BM25`），ES 用
   best_fields 取 max；中文复合词 fine 段命中多，放大了 top-k 排序分歧。但两者召回的
   **相关文档集合**高度一致（recall / nDCG 几乎相同），差异只在边缘干扰文档的排位上，
   对最终 RAG（取 top-k 喂 LLM）影响很小。
4. **fine 路有效**：合成 / 中文集上"只在 fine 段命中（query 词嵌在长词里被细分出，如
   query『网络』命中文档的『无线网络』）"的文档能被召回，纯 coarse 召不到。
5. **Manticore 采用 coarse-only**：早期 coarse+fine BM25F 在 CovidRetrieval 上只有
   recall@10=0.656、nDCG@10=0.538；修正 IDF 后仍只有 0.760/0.635。coarse-only 加显式
   `idf='plain,tfidf_unnormalized'` 后达到 0.919/0.818，因此 v2 表不再混入 fine 字段。

## 局限

- CovidRetrieval corpus 采样 1 万 / 10 万，干扰文档少，recall 绝对值偏高；但 es / qdrant
  同等条件，overlap 与相对对比仍有效。
- 单数据集、单主题（医疗），不代表所有中文场景；规模也远小于生产十万级。
- `avgdl` 写入时冻结，存量需重灌才完全对齐，务必用 calibrate 脚本按真实语料校准。

## 复现

```bash
# 中文集：hf-mirror 下载 + 转 BEIR，再评测（对比 ES）
python scripts/dev/fetch_cmteb_retrieval.py --dataset CovidRetrieval --sample 10000 --out /tmp/covid_beir
python scripts/dev/eval_bm25_recall.py --from-beir /tmp/covid_beir --k 10 --with-es --es-password ***

# 英文 NFCorpus（BEIR 官方 zip 解压后同样 --from-beir 跑）
python scripts/dev/eval_bm25_recall.py --from-beir ./nfcorpus --k 10 --with-es --es-password ***

# Manticore 质量门禁（示例阈值应按固定评测集固化在 CI）
python scripts/dev/eval_bm25_recall.py --from-beir ./nfcorpus --k 10 --with-manticore \
  --manticore-min-recall 0.15 --manticore-min-ndcg 0.31

# avgdl 校准（按真实库统计）
python scripts/dev/calibrate_bm25_avgdl.py --from-db --port 33306 --password ***
```
