# LambdaMART 质检对齐与上线边界

本文记录 `candidate-difference-v3-20260728-final33` 从 LinkRag-Eval Blind v5 质检结果落到
RAG 生产实现时的完整差异、处理结果与上线边界。它回答三个问题：评测口径是否被线上复现、
哪些旧字段必须兼容保留、合并代码后还需要验证什么。

## 1. 结论

- RAG 问答流已绑定 Blind v5 的候选生成契约，不再只加载模型文件而沿用另一套固定 TopK。
- Active 仍是默认模式。这是项目负责人明确接受的发布选择，不作为本次缺陷处理。
- Active 不调用远程 rerank；模型异常、超时、低置信度或延迟超预算时回退 frozen weighted score。
- `POST /api/v1/recall` 纯召回 JSON 不受全局 LTR 模式覆盖，继续反映数据集/系统配置。
- 代码与契约对齐不等于完成生产验收；发布后仍必须用真实 dev 流量观察延迟、降级率和 Top10 变化。

## 2. 冻结的线上契约

模型目录的 `serving_contract.json` 与代码内 `candidate_routing.py` 共同冻结以下口径；模型加载时
逐字段比较，任何不一致都拒绝模型并走 weighted-score 降级：

| 项目 | 冻结值 |
| --- | --- |
| 模型 | `candidate-difference-v3-20260728-final33` |
| 候选契约 | `blind_v5_candidate_routing_v1` |
| 召回路 | `bm25,sparse,dense` |
| BM25 / Sparse / Dense 阈值 | `0.0 / 0.0 / 0.0` |
| BM25 / Sparse / Dense 权重 | `0.15 / 0.15 / 0.70` |
| 最终候选数 | 10 |
| Alias | 禁用 |

Query 分型深度：

| 档位 | Dense | Sparse | BM25 |
| --- | ---: | ---: | ---: |
| `short_keyword` | 300 | 100 | 225 |
| `exact_identifier` | 150 | 50 | 100 |
| `number_time` | 275 | 50 | 200 |
| `long_multi` | 125 | 50 | 75 |
| `natural_default` | 150 | 50 | 225 |

分型规则只依赖 Query 文本，与 Blind v5 使用同一实现口径。该覆盖仅用于
`RECALL_LTR_MODE=active/baseline` 的 RAG 问答主链；`shadow` 主链、`off` 和纯召回 JSON 仍按数据集配置执行，
其中 Shadow 只在独立后台请求中使用冻结契约做旁路比较。

## 3. 问题与处理结果

| 编号 | 原问题 | 风险 | 本次处理 |
| --- | --- | --- | --- |
| 1 | 线上固定 `100/50/100`，Blind v5 按 Query 动态分路 TopK | 训练/评测与线上候选分布不一致 | 新增版本化候选路由，RAG LTR 模式按五档动态 TopK |
| 2 | 质检发布建议与线上默认 `active` 的节奏差异 | 未经流量观察直接主排 | **按负责人决定保留 active 默认，不作为缺陷**；仍保留 shadow/baseline 开关 |
| 3 | Blind v5 评测 Top10，线上默认只返回 8 条 | Hit@10/MRR@10 与用户实际可见集合不一致 | 系统默认与 LTR 输出统一为 Top10 |
| 4 | 代码/文档默认权重 `0.2/0.3/0.5`，冻结模型口径为 `0.15/0.15/0.70` | 降级顺序与模型评测基线不一致 | 代码、环境样例、数据集 schema 默认和文档统一为冻结权重 |
| 5 | 模型包只校验特征，不校验候选生成配置 | 模型正确但候选口径漂移仍可启动 | 增加 `serving_contract.json`，绑定模型、特征签名、来源、阈值、权重、路由和 TopN |
| 6 | 全局 LTR active 会让纯召回 JSON 也强制系统权重 | 质检/诊断端点无法反映数据集真实配置 | 候选契约覆盖改为 RAG 流显式启用；纯召回保持原语义 |
| 7 | Shadow 虽异步推理，但完整候选正文读取仍在主链路 await | Shadow 增加线上首 token 延迟和数据库压力 | 完整候选正文读取与 LTR 推理一并移入后台任务；主链路只读线上候选正文 |
| 8 | Active 终态只有 `rerank_applied=false` | 无法区分 LTR 正常、Hybrid、超时或 weighted fallback | 新增 `ranking_diagnostics`，返回策略、模式、版本、耗时和原因 |
| 9 | `RankerMonitor` 仅存在内存中，没有采集入口 | 降级率和 p95 无法被运维读取 | `/health.ltr` 暴露模型/契约版本、加载错误、计数和 p50/p95/p99 |
| 10 | 文档仍描述 RRF、8 条、旧权重或“全部由数据集控制” | 生产改造和排障依据错误 | 同步配置、HTTP 契约、召回实现和模型包文档 |
| 11 | Shadow/Active 首个请求同步加载 LightGBM、校验制品并运行测试向量 | 首个真实请求承担初始化延迟，Shadow p95 被污染 | FastAPI startup 通过 worker thread 预加载；请求期只读初始化结果或明确 baseline 状态 |

## 4. 有意保留的兼容项

以下名称看起来属于旧 rerank/RRF 阶段，但现在不能直接删除：

- `RERANK_DEFAULT_TOP_N`、数据集 `rerank_top_n` 和 `enable_rerank` 仍被旧 `off` 链路、数据库 JSON
  或上下游服务消费。当前只把默认值统一为 10，不做跨服务字段迁移。
- 远程 `PostRecallReranker` 保留给 `off` 和 Shadow 的线上对照路径；Active 不调用它。
- SSE 顶层 `rerank_applied` 保留以兼容旧客户端；Active 是否使用 LTR 以新增
  `ranking_diagnostics` 为准。
- 请求体拒绝列表中的 `rrf_k` 等旧字段只用于稳定返回 `422`，不表示 RRF 仍参与排序。

删除这些兼容项需要 Java、Web、存量数据和 API 消费者联合迁移，不属于本次 RAG 单仓改造范围。

## 5. 仍需完成的生产验证

这些事项不能由单元测试或评测仓库替代，合并后仍是上线门槛：

1. 在 dev 用真实 Query 和真实数据分别跑 Shadow 与 Active，核对候选档位、Top10、空召回、
   单路失败和短关键词低置信度回退。
2. 采集 `/health.ltr.monitor` 与结构化日志，观察 `ltr`、`hybrid_short_low_confidence`、
   `fallback_timeout`、`fallback_error`、`fallback_budget_exceeded` 的占比及 p95/p99。
3. 比较改造前后的召回耗时、首 token、总生成耗时、数据库正文批量读取耗时和上下文 token 使用量。
   Top10 不代表一定塞入 10 段，最终上下文仍受 4000 token 预算限制。
4. 验证手工回滚：把 `RECALL_LTR_MODE` 改为 `baseline` 并重启，确认不加载模型、不调用远程
   rerank，且服务继续返回 frozen weighted-score Top10。
5. 保留发布前后同一批 Query 的响应和日志证据。若要重新宣称效果提升，需要新的 Tune/Blind
   数据或生产 A/B；本次代码对齐不能重写已经只运行一次的 Blind v5 结论。

## 6. 已知限制与后续清理

- 当前回滚是显式配置 + 重启，不是自动熔断切换；请求级异常会自动降级，但系统不会自动把全局
  模式改成 `baseline`。
- `asyncio.to_thread` 超时能及时让请求降级，但不能强制终止已进入 LightGBM 的底层线程。若线上出现
  持续卡死而非普通慢请求，需要将推理隔离到可终止的独立进程。
- `/health.ltr.monitor` 是单进程内存快照，进程重启会清零，多副本聚合与长期告警由外部监控负责。
- startup 完成后，active/shadow 的 `preload_completed=true` 且 `loaded=false` 表示预加载失败；
  结合 `last_load_error` 告警。`off`/`baseline` 不加载模型，`loaded=false` 属预期状态。
- 候选契约冻结检索形状，不冻结每个数据集绑定的 dense/sparse 编码模型。读写编码器一致性仍由现有
  数据集模型绑定契约保证；若未来允许同一 LTR 模型跨异构编码器大规模使用，应增加编码器兼容矩阵。
- 仓库全量 mypy 当前存在既有基线（本次检查为 51 个文件 128 条错误），并非本次 LTR 改造引入；
  本次新增的候选路由、模型校验和 provider 模块在隔离导入检查下通过。全仓类型基线应单独治理，
  不能把它误记为本分支已清零。
- 工作机系统 Python 曾安装 LightGBM 4.6.0，而模型明确要求 4.7.0；当前分支已创建 gitignored
  项目 `.venv` 并验证为 4.7.0，`pyproject.toml` 与 Docker 构建也精确固定 4.7.0。后续本地测试应使用
  `.venv/bin/python`，构建和部署必须使用项目依赖，不能绕过版本校验复用系统包。
- 旧 rerank 命名的跨服务清理、自动回滚控制器和集中式指标持久化应分别立项，避免在本次质检对齐中
  扩大变更面。

## 7. 合并与发布检查

1. 代码格式、文档同步和相关单元/验收测试通过。
2. 使用模型声明的 LightGBM `4.7.0` 加载 bundle，并通过文件哈希、特征、候选契约和测试向量校验。
3. 检查 dev 实际环境仍为 `RECALL_LTR_MODE=active`，模型目录与本文件版本一致。
4. 发布后确认 `/health.ltr` 为 `preload_completed=true`、`loaded=true`、
   `serving_strategy=lambdamart`，且模型与候选契约版本正确，
   再执行第 5 节真实流量验证。
5. 指标超出预算或错误率异常时切换 `baseline`，保留故障窗口日志后再分析。
