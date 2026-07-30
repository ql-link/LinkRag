# LambdaMART 质检成果生产化完整测试方案

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 适用仓库 | LinkRag |
| 测试对象 | LinkRag-Eval 质检成果在 RAG 问答链路中的生产化实现 |
| 基准模型 | candidate-difference-v3-20260728-final33 |
| 候选契约 | blind_v5_candidate_routing_v1 |
| 目标分支 | feature/ltr-quality-alignment 合入 dev 前后的候选版本 |
| 文档性质 | 完整测试设计、执行清单、证据规范与发布门禁 |
| 非目标 | 本文不修改业务代码，不重新训练模型，不重新运行 Blind v5 |

本文覆盖本次质检引入的候选生成、Query 分型、三路召回、固定权重融合、LambdaMART
在线推理、模型制品校验、启动预加载、四种发布模式、Shadow、异常降级、延迟预算、
可观测性、接口兼容和回滚。本文中的“通过”必须有实际执行证据，不能只依据代码存在或单元测试数量判断。

## 2. 测试目标与验收原则

### 2.1 测试目标

1. 证明 RAG 使用的候选生成口径、38 维特征、模型、固定测试向量和回退排序与评测仓冻结口径一致。
2. 证明 active 能替代旧远程 rerank，并在正常、低置信度、超时、预算超限和异常时返回确定结果。
3. 证明 shadow 只采集旁路数据，不改变主链路召回配置、结果、公开 TopN、正文读取量和用户延迟。
4. 证明 off、shadow、active、baseline 四种模式均有明确且可回滚的行为。
5. 证明纯召回 API、SSE、旧字段和存量数据集配置保持兼容。
6. 证明模型加载、推理、后台任务和正文批量读取受到版本、超时、并发和资源预算约束。
7. 建立可重复的功能、性能、故障注入、监控和回滚证据。

### 2.2 放行原则

- 正确性、兼容性、隔离性、性能和回滚五类门禁必须全部通过。
- 已知阻断项必须先形成会失败的测试，再修复实现，最后由同一测试转绿。
- 单元测试通过不能替代真实数据库、真实召回服务和真实模型制品的 dev 集成验证。
- 当前 1185 条单元测试和 346 条验收测试仅作为回归基线，不自动代表本文全部场景已覆盖。
- Blind v5 已按冻结规则只运行一次；生产化验证不得修改或重跑该 Blind 集合来“优化结论”。

## 3. 冻结契约与预期行为

### 3.1 候选与排序契约

| 项目 | 冻结值 |
| --- | --- |
| 召回来源 | bm25、sparse、dense，三路缺一不可 |
| 召回阶段阈值 | Dense 0.0、Sparse 0.0、BM25 0.0 |
| 固定融合权重 | BM25 0.15、Sparse 0.15、Dense 0.70 |
| weighted fallback 内部阈值 | Dense 0.30、Sparse 0.20、BM25 0.0 |
| LTR 输出数 | Top10 |
| Alias | 禁用 |
| LightGBM | 4.7.0 |
| 特征数 | 38，名称、顺序和签名均冻结 |

注意：召回阶段阈值决定候选是否进入池；fallback 内部阈值只参与冻结 weighted score
计算。两组阈值必须分别测试，不得混为同一配置。

### 3.2 Query 分型 TopK

| 类型 | Dense | Sparse | BM25 |
| --- | ---: | ---: | ---: |
| short_keyword | 300 | 100 | 225 |
| exact_identifier | 150 | 50 | 100 |
| number_time | 275 | 50 | 200 |
| long_multi | 125 | 50 | 75 |
| natural_default | 150 | 50 | 225 |

### 3.3 四种模式

| 模式 | 用户结果 | LambdaMART | 远程 rerank | 预期用途 |
| --- | --- | --- | --- | --- |
| off | 原有数据集配置与旧链路 | 不加载、不执行 | 按旧配置执行 | 兼容和对照 |
| shadow | 必须与 off 主链路等价 | 抽样后台执行 | 主链路仍按旧配置 | 无结果影响采集 |
| active | 候选契约 + LTR Top10 | 执行 | 不调用 | 正式主排 |
| baseline | 候选契约 + weighted Top10 | 不加载、不执行 | 不调用 | 显式安全回滚 |

## 4. 变更与测试追踪矩阵

| 变更 | 主要风险 | 覆盖章节 |
| --- | --- | --- |
| 动态 Query 分型及五档 TopK | 评测与线上候选分布不一致 | CAN |
| 三路来源与召回阈值冻结 | 某一路静默缺失仍声称契约一致 | CAN、FLT |
| 权重改为 0.15/0.15/0.70 | 配置漂移或回退顺序变化 | CAN、FBK |
| LTR 输出 Top10 | Shadow/旧数据集 TopN 被覆盖 | OUT、SHD |
| RRF 删除、固定 weighted score | 残留配置仍影响结果 | FBK、CMP |
| active 替代远程 rerank | 重复排序或意外外部调用 | MOD、CMP |
| serving_contract 和制品哈希 | 模型与候选配置错配 | ART |
| LightGBM 4.7.0 固定 | 开发、容器和生产运行时漂移 | ART、DEP |
| 启动阶段预加载 | 首请求阻塞或失败状态不明确 | STA |
| 推理超时和延迟预算 | 请求阻塞、线程积压 | TIM、PERF |
| Shadow 后台正文读取和推理 | 主链路延迟、连接池耗尽、任务失控 | SHD、PERF |
| ranking_diagnostics | 客户端兼容、错误原因不准确 | API、OBS |
| /health.ltr 和内存监控 | 无法判断加载、降级和延迟 | OBS |
| 纯召回 API 隔离 | 全局 LTR 覆盖数据集配置 | ISO |
| baseline 回滚 | 故障时仍加载模型或调用 rerank | ROL |

## 5. 测试分层、环境与数据

### 5.1 测试分层

| 层级 | 目的 | 运行环境 |
| --- | --- | --- |
| 单元 | 分型边界、特征签名、排序、采样、降级状态机 | 本地项目虚拟环境 |
| 契约 | Eval 与 RAG 制品、配置、测试向量逐项一致 | 两仓只读对比 |
| 集成 | 真实 SQLite/MySQL 兼容读取、召回、正文批量读取、SSE | 隔离 dev 栈 |
| 故障注入 | 模型损坏、单路失败、超时、连接池饱和 | 隔离 dev 栈 |
| 性能 | 首 token、总耗时、推理和数据库压力 | 与生产同规格或可换算环境 |
| 发布演练 | shadow、active、baseline 切换及回滚 | dev，之后小流量生产 |

### 5.2 环境要求

- 所有 Python 测试使用项目 .venv，确认 LightGBM 为 4.7.0；不得使用仍可能为 4.6.0 的系统 Python。
- 容器镜像内也必须检查 LightGBM 版本和模型可加载性。
- 使用隔离 dev 数据集和只读或测试账户，禁止用故障注入影响生产。
- 记录代码 SHA、镜像 digest、模型目录 SHA、serving contract 版本、环境配置摘要和数据库 schema 版本。
- 日志中不得输出 Query 全文、正文、密钥或用户敏感信息。

### 5.3 配置矩阵

每个环境至少执行以下组合：

| 组合 | LTR 模式 | 模型状态 | Shadow 采样 | 数据集 TopN |
| --- | --- | --- | ---: | ---: |
| C1 | off | 正常 | 0 | 8 |
| C2 | shadow | 正常 | 0 | 8 |
| C3 | shadow | 正常 | 1 | 8 |
| C4 | active | 正常 | 不适用 | 10 |
| C5 | active | 缺失/损坏 | 不适用 | 10 |
| C6 | baseline | 不提供模型 | 不适用 | 10 |
| C7 | off | 正常 | 0 | 3、8、15 |

### 5.4 测试 Query 和语料

测试集必须包含：

- 1 至 2 个词的短关键词，以及低置信度和高置信度两种候选分布。
- 工单号、文档编号、版本号、日期、时间、年份、金额和混合标识符。
- 自然语言问句、长多意图问句、否定表达、同义表达和歧义表达。
- 答案跨多个 Chunk、跨段落、标题与正文分离、编号在一段而解释在下一段的语料。
- 多个正确 Chunk 的多正例 qrels、同文档近重复 Chunk、完全无关负例。
- 空召回、只有单路命中、正文缺失、正文批量读取部分失败和超长正文。
- 中文、英文、数字和中英混合 Query。

所有固定用例记录 Query ID、来源、来源元数据、预期分型、相关 Chunk ID 和允许的多正例集合；
测试报告不复制敏感原文。

## 6. 模型制品与运行时测试（ART）

| ID | 场景 | 执行要点 | 预期结果 |
| --- | --- | --- | --- |
| ART-001 | 本地依赖版本 | 用项目 .venv 查询 LightGBM | 精确为 4.7.0 |
| ART-002 | 容器依赖版本 | 在最终镜像查询版本并加载模型 | 精确为 4.7.0，加载成功 |
| ART-003 | 错误版本 | 构造非 4.7.0 运行环境 | 明确拒绝或健康状态失败，不静默服务 LTR |
| ART-004 | Eval 主制品一致性 | 逐文件比对模型、特征和测试向量等五个主文件 | SHA-256 完全一致 |
| ART-005 | SHA 清单来源策略 | 校验 RAG 扩展后的 SHA256SUMS 与 Eval 原清单的关系 | 能明确证明原始五文件来源；不能误称六文件 bundle 字节一致 |
| ART-006 | 文件篡改 | 分别修改模型、特征、测试向量 | 预加载失败，active 降级，错误可观测 |
| ART-007 | serving contract 篡改 | 修改来源、TopK、阈值、权重、TopN 或版本 | 模型拒绝加载 |
| ART-008 | 38 维签名 | 校验名称、数量、顺序和签名 | 与 Eval 冻结值逐项一致 |
| ART-009 | 三个冻结向量 | 加载时运行特征矩阵、LTR 顺序和 fallback 顺序 | 三组全部通过 |
| ART-010 | Alias 与离线字段 | 检查在线路径输入 | Alias 禁用；label、qrel、未来信息不得进入在线特征 |

ART-005 的验收证据必须同时保留 Eval 原始清单、RAG 清单及逐文件计算结果。若 RAG
因增加 serving_contract.json 修改了清单，报告必须写明“主制品来源一致，扩展清单不同”，
不得写“六个制品与 Eval 逐字节一致”。

## 7. 候选生成与 Query 路由测试（CAN）

| ID | 场景 | 预期结果 |
| --- | --- | --- |
| CAN-001 | short_keyword 代表 Query | 使用 300/100/225 |
| CAN-002 | exact_identifier 代表 Query | 使用 150/50/100 |
| CAN-003 | number_time 代表 Query | 使用 275/50/200 |
| CAN-004 | long_multi 代表 Query | 使用 125/50/75 |
| CAN-005 | natural_default 代表 Query | 使用 150/50/225 |
| CAN-006 | 分型边界 | 长度、数字、日期、编号边界与冻结实现一致 |
| CAN-007 | 确定性 | 同一规范化 Query 重复执行分型和 TopK 完全一致 |
| CAN-008 | Unicode 和空白 | 全角数字、中英标点、前后空白行为有固定预期 |
| CAN-009 | 来源完整 | active/baseline 实际装配 bm25、sparse、dense 三路 |
| CAN-010 | 来源缺失 | 任一路未装配时不得静默以不完整池运行冻结模型 |
| CAN-011 | 召回阈值 | 三路候选进入池均按 0.0 阈值 |
| CAN-012 | fallback 阈值 | weighted fallback 独立使用 0.30/0.20/0.0 |
| CAN-013 | 融合权重 | 三路权重为 0.15/0.15/0.70，和为 1 |
| CAN-014 | 单路超时 | strict 和非 strict 的结果、诊断和降级符合约定 |
| CAN-015 | 两路失败 | 不完整候选契约不能伪装成正常 LTR |
| CAN-016 | 全路失败 | 返回稳定空结果或标准错误，不产生 500 泄漏 |

CAN-010 必须针对真实 pipeline 装配测试，不能只构造包含三路的伪响应。若配置声明 dense
但实际 retriever 未注册，预期为 fail closed 或明确 baseline，并在 diagnostics 和健康状态中显示原因。

## 8. 输出数量与上下文预算测试（OUT）

| ID | 场景 | 预期结果 |
| --- | --- | --- |
| OUT-001 | active 命中超过 10 | 最终公开候选恰为 Top10 |
| OUT-002 | baseline 命中超过 10 | weighted score Top10 |
| OUT-003 | 命中少于 10 | 返回实际数量，不补空项 |
| OUT-004 | off + 数据集 TopN=3/8/15 | 分别保持 3/8/15 |
| OUT-005 | shadow + 数据集 TopN=3/8/15 | 公开结果仍分别为 3/8/15 |
| OUT-006 | 多个同分候选 | 由冻结 tie-break 产生稳定顺序 |
| OUT-007 | 上下文超过 4000 tokens | 按上下文预算截断，不因 Top10 强塞全部正文 |
| OUT-008 | Top1 超长正文 | 安全截断且后续候选处理符合上下文构造约定 |

## 9. 纯召回 API 隔离测试（ISO）

| ID | 场景 | 预期结果 |
| --- | --- | --- |
| ISO-001 | 全局 active，调用纯召回 JSON | 使用数据集来源、TopK、阈值、权重、TopN |
| ISO-002 | 全局 shadow，调用纯召回 JSON | 不启动 Shadow LTR，不覆盖数据集配置 |
| ISO-003 | 数据集只启用部分来源 | 纯召回按数据集配置执行，不套用三路 LTR 契约 |
| ISO-004 | 数据集自定义权重 | 纯召回结果反映自定义权重 |
| ISO-005 | 请求含已删除 rrf_k | 返回稳定 422 或约定兼容错误，RRF 不参与执行 |
| ISO-006 | 连续切换全局模式 | 同一纯召回请求结果和配置摘要不变 |

## 10. 四种发布模式测试（MOD）

| ID | 模式与场景 | 预期结果 |
| --- | --- | --- |
| MOD-001 | off 正常 | 不加载 LTR；旧链路和数据集配置保持可用 |
| MOD-002 | off 启用旧 rerank | 仅旧兼容链路可调用远程 rerank |
| MOD-003 | shadow 未抽中 | 与 off 的公开结果、调用和延迟路径等价 |
| MOD-004 | shadow 抽中 | 主链路等价；后台产生 Shadow 诊断 |
| MOD-005 | active 正常 | LTR Top10；远程 rerank 调用数为 0 |
| MOD-006 | active 模型不可用 | frozen weighted score Top10，诊断给出原因 |
| MOD-007 | baseline 正常 | 不加载模型、不调用远程 rerank，直接 weighted Top10 |
| MOD-008 | baseline 无模型目录 | 服务仍能启动和返回 |
| MOD-009 | 非法模式值 | 配置启动失败并说明合法值 |
| MOD-010 | 模式重启切换 | 新进程行为与配置一致，无旧全局状态残留 |

## 11. Shadow 隔离与资源治理测试（SHD）

| ID | 场景 | 预期结果 |
| --- | --- | --- |
| SHD-001 | off 与 shadow 同 Query、同数据 | 公开候选 ID、顺序、数量完全一致 |
| SHD-002 | 比较实际召回调用 | shadow 不改变主链路来源、动态 TopK、阈值和权重 |
| SHD-003 | 数据集 TopN 非 10 | shadow 不强制 Top10 |
| SHD-004 | 采样率 0 | 不创建后台任务、不读取完整候选正文 |
| SHD-005 | 采样率 1 | 每个合格请求只创建一个受控后台任务 |
| SHD-006 | 固定采样键 | 同一采样键结果稳定，分布符合比例 |
| SHD-007 | 慢正文读取 | 不阻塞主链路首 token 和总返回 |
| SHD-008 | 慢模型推理 | 不阻塞主链路；后台按预算结束 |
| SHD-009 | 高并发抽样 | 任务数受 semaphore/队列上限控制，饱和时丢弃并计数 |
| SHD-010 | 正文读取永久挂起 | 总超时生效，任务和数据库连接最终释放 |
| SHD-011 | 数据库连接池压力 | 主链路连接优先，不因 Shadow 耗尽连接池 |
| SHD-012 | 后台异常 | 异常被消费并记录，不出现未处理 Task exception |
| SHD-013 | 服务关闭 | 未完成任务被有界等待或取消，退出不无限阻塞 |
| SHD-014 | Shadow 旧 rerank 失败 | 用户结果不受影响，Shadow 状态准确记录 |
| SHD-015 | 敏感信息 | Shadow 日志和指标不包含 Query/正文原文 |
| SHD-016 | 多副本 | 单实例计数可解释，外部聚合可区分实例和版本 |

SHD-001 至 SHD-003 是 Shadow 语义门禁；SHD-007 至 SHD-013 是零主链路影响和资源门禁。
任一失败均不得用 Shadow 数据决定 active 切换。

## 12. 启动预加载测试（STA）

| ID | 场景 | 预期结果 |
| --- | --- | --- |
| STA-001 | active 启动 | lifespan 通过 worker 预加载并完成全部校验 |
| STA-002 | shadow 启动 | 同上，不把加载成本留给首请求 |
| STA-003 | off/baseline 启动 | 不导入和构造 Booster |
| STA-004 | 首请求 | 只读取已初始化 ranker 或明确 baseline 状态 |
| STA-005 | 模型损坏 | 启动策略符合约定，health 显示 preload_completed 和错误 |
| STA-006 | 并发首请求 | 不发生重复加载和初始化竞争 |
| STA-007 | 多 worker | 每个 worker 状态独立、版本一致 |
| STA-008 | 重启换模型 | 新进程加载新版本，不复用旧 Booster |

首请求性能测试必须分别记录冷进程启动耗时和启动完成后的首个业务请求；不得把预加载时间
混进在线 p95，也不得让业务请求触发同步首次加载。

## 13. 排序、低置信度与降级测试（FBK）

| ID | 场景 | 预期策略 |
| --- | --- | --- |
| FBK-001 | 正常推理 | ltr |
| FBK-002 | 短关键词且低置信度 | hybrid_short_low_confidence |
| FBK-003 | 短关键词高置信度 | ltr |
| FBK-004 | 非短关键词低分 | 按冻结规则，不错误触发短关键词 Hybrid |
| FBK-005 | 模型缺失/加载失败 | fallback_error 或明确 baseline |
| FBK-006 | 特征签名不一致 | 拒绝 LTR，weighted fallback |
| FBK-007 | 特征含 NaN/Inf | 不返回不确定顺序，安全 fallback |
| FBK-008 | 推理抛异常 | fallback_error |
| FBK-009 | 推理超时 | fallback_timeout |
| FBK-010 | 总延迟预算不足 | fallback_budget_exceeded |
| FBK-011 | 所有分数相同 | 结果稳定，tie-break 可复现 |
| FBK-012 | 重复 Chunk ID | 去重和顺序符合契约 |
| FBK-013 | 部分候选正文缺失 | 特征和回退行为明确，不抛未处理异常 |
| FBK-014 | weighted score 对照 | 与 Eval 冻结计算逐候选一致 |
| FBK-015 | active 外部调用 | 远程 rerank 调用数始终为 0 |

每个用例同时断言候选顺序、ranking_diagnostics.strategy、reason、model_version、
candidate_contract_version 和 latency 字段，避免“结果碰巧正确但状态错误”。

## 14. 超时、并发与资源测试（TIM）

| ID | 场景 | 预期结果 |
| --- | --- | --- |
| TIM-001 | 模型推理超过 LTR 超时 | 请求及时 fallback |
| TIM-002 | 推理未超单项但超过总预算 | fallback_budget_exceeded |
| TIM-003 | 主链路正文读取变慢 | 受到召回流总超时或独立明确预算约束 |
| TIM-004 | Shadow 正文读取变慢 | 受到后台总超时约束 |
| TIM-005 | 远程 rerank 变慢（off） | 原链路按既有超时降级 |
| TIM-006 | 连续超时 | to_thread 底层线程不会无限积压到拖垮服务 |
| TIM-007 | 突发并发 | 事件循环无长时间阻塞，连接池和线程池有余量 |
| TIM-008 | 客户端取消 | 主任务及时结束，后台任务按设计处理 |

asyncio.to_thread 的超时只能停止等待，不能杀死底层 LightGBM 线程。因此 TIM-006 必须观测
活跃线程、排队任务、CPU 和后续请求延迟；若线程持续积压，则即使单请求及时 fallback 也不能放行。

## 15. API、SSE 与存量配置兼容测试（API/CMP）

| ID | 场景 | 预期结果 |
| --- | --- | --- |
| API-001 | active SSE | 新增 ranking_diagnostics，事件顺序和终止帧稳定 |
| API-002 | off SSE | 旧 rerank_applied 字段仍存在且语义不变 |
| API-003 | 旧客户端忽略新字段 | 可正常消费完整流 |
| API-004 | 公开序列化 | 内部完整候选池和 Shadow 结果不进入 JSON/SSE |
| API-005 | diagnostics 降级 | 不包含堆栈、路径、正文和敏感配置 |
| API-006 | health.ltr | 返回约定字段且状态码稳定 |
| CMP-001 | 存量 Dataset JSON 含旧 RRF 字段 | 可读取或按迁移规则清理，不参与排序 |
| CMP-002 | 存量 rerank_top_n | off 保持兼容；active/baseline 行为符合模式契约 |
| CMP-003 | enable_rerank 旧字段 | active/baseline 不因此调用远程 rerank |
| CMP-004 | 缺少新增字段的旧配置 | 使用明确默认值，不报 500 |
| CMP-005 | 多版本客户端 | 新旧字段组合均有契约测试 |
| CMP-006 | 数据库只读兼容 | 本次排序改造不要求破坏性数据迁移 |

## 16. 可观测性与健康检查（OBS）

health.ltr 至少验证以下字段：

- configured_mode
- serving_strategy
- preload_completed
- loaded
- model_version
- candidate_contract_version
- last_load_error
- monitor

| ID | 场景 | 预期结果 |
| --- | --- | --- |
| OBS-001 | active 正常 | preload_completed=true、loaded=true、strategy=lambdamart |
| OBS-002 | active 预加载失败 | loaded=false、错误非空、请求可降级 |
| OBS-003 | off/baseline | loaded=false 属预期，不产生错误告警 |
| OBS-004 | 各策略请求 | ltr、hybrid 和各 fallback 计数准确 |
| OBS-005 | 延迟统计 | p50/p95/p99 与原始样本抽查一致 |
| OBS-006 | 进程重启 | 内存计数清零被识别，不误判长期趋势 |
| OBS-007 | 多副本 | 外部监控按实例、模型和契约版本聚合 |
| OBS-008 | Shadow 饱和/丢弃 | 有独立计数和告警 |
| OBS-009 | 结构化日志 | 包含 request correlation、策略、原因和耗时，不含敏感正文 |
| OBS-010 | 告警阈值 | 预加载失败、fallback 激增、p95 超预算、任务饱和可触发告警 |

## 17. 性能与容量方案（PERF）

### 17.1 指标

- 召回总耗时、正文批量读取耗时、排序耗时、首 token、完整响应耗时。
- p50、p95、p99、最大值、错误率、fallback 率。
- QPS、并发数、CPU、RSS、事件循环延迟、线程数和排队数。
- 数据库连接池占用、等待时长、批量查询次数和行数。
- Shadow 任务创建、完成、超时、异常、丢弃和当前活跃数。

### 17.2 对比组

1. off 基线。
2. shadow 采样率 0。
3. shadow 采样率为计划生产值。
4. shadow 采样率 1 的压力上界。
5. active 正常。
6. active 强制 timeout fallback。
7. baseline。

### 17.3 负载形态

- 稳态 30 分钟：目标生产 QPS。
- 阶梯压测：25%、50%、75%、100%、125% 目标 QPS。
- 突发：在 10 秒内从空闲提升到 2 倍目标并发。
- 持续慢推理：验证底层线程是否累积。
- 慢数据库与小连接池：验证 Shadow 是否抢占主链路资源。

### 17.4 性能放行标准

具体毫秒预算由生产 SLO 在执行前填写并冻结。至少满足：

- shadow 相对 off 的公开结果完全一致。
- shadow 主链路 p95/首 token 增量在预先批准预算内，且无连接池饥饿。
- active 排序 p95 低于 LTR 预算，超时请求能在总预算内 fallback。
- 压测后线程、任务和连接数能回落到稳态，无持续增长。
- Top10 上下文仍受 4000 token 预算约束，生成耗时无不可接受放大。

## 18. 故障注入矩阵（FLT）

| 故障 | off | shadow | active | baseline |
| --- | --- | --- | --- | --- |
| 模型目录缺失 | 不受影响 | 主链路不受影响，Shadow 记录失败 | weighted fallback | 不受影响 |
| 模型 SHA 错误 | 不受影响 | 同上 | weighted fallback | 不加载 |
| serving contract 错误 | 不受影响 | 同上 | weighted fallback | 不加载 |
| Dense 未装配 | 按数据集语义 | 不改变主链路 | 不得伪装为正常 LTR | 明确失败或降级 |
| Sparse 超时 | 按 strict 约定 | 主链路同 off | diagnostics 明确 | diagnostics 明确 |
| BM25 异常 | 按 strict 约定 | 主链路同 off | diagnostics 明确 | diagnostics 明确 |
| 正文读取部分失败 | 兼容返回 | 用户链路同 off | 安全处理 | 安全处理 |
| 数据库连接池饱和 | 标准超时 | Shadow 先丢弃/超时 | 主链路可降级 | 主链路可降级 |
| LightGBM 卡死 | 不受影响 | 后台有界 | 请求有界 fallback，线程不失控 | 不受影响 |
| 远程 rerank 不可用 | 旧链路降级 | 用户链路按旧约定 | 不调用 | 不调用 |
| 监控写入失败 | 业务不受影响 | 业务不受影响 | 业务不受影响 | 业务不受影响 |

## 19. 回滚与恢复测试（ROL）

| ID | 场景 | 预期结果 |
| --- | --- | --- |
| ROL-001 | active 改 baseline 并重启 | 不加载模型、不调用远程 rerank，weighted Top10 可用 |
| ROL-002 | shadow 改 off 并重启 | 不再创建后台任务，旧链路完全恢复 |
| ROL-003 | 回滚代码但保留旧 Dataset JSON | 服务可启动且旧字段兼容 |
| ROL-004 | 模型目录移除后 baseline 启动 | 启动成功 |
| ROL-005 | 多副本滚动回滚 | 不同副本版本可从 health 和日志区分 |
| ROL-006 | 回滚后数据核对 | 无排序改造产生的不可逆数据库写入 |
| ROL-007 | 恢复 active | 重新预加载并通过版本、SHA、签名和向量校验 |

回滚演练必须记录配置变更、重启时间、健康状态、首个成功请求和外部 rerank 调用数。
当前自动降级不等于全局自动回滚；全局模式切换仍是显式配置和重启流程。

## 20. 阻断项修复与回归门禁

以下不是可接受的“已知限制”。实现完成后仍必须由同一批自动化、真实依赖和压力测试持续证明未回归：

| 编号 | 阻断项 | 对应测试 | 放行条件 |
| --- | --- | --- | --- |
| B1 | shadow 当前可能对全部流量套用 LTR 候选契约，改变主链路 TopK、来源和权重 | SHD-001、SHD-002 | shadow 与 off 的主链路召回调用和结果完全一致 |
| B2 | shadow 当前可能强制 Top10，覆盖数据集 TopN | OUT-005、SHD-003 | 数据集 TopN 在 shadow 下保持不变 |
| B3 | 冻结三路来源未与真实 pipeline 装配强校验，可能静默缺少 Dense | CAN-009、CAN-010 | 缺任一路时 fail closed 或明确 baseline |
| B4 | Shadow 后台任务无并发上限和饱和丢弃 | SHD-009 | 有界并发、队列或丢弃策略及指标 |
| B5 | Shadow 完整候选正文读取缺少总超时 | SHD-010、TIM-004 | 超时后任务和连接均释放 |
| B6 | 主链路正文读取可能处于召回流总超时之外 | TIM-003 | 正文读取被纳入可证明的总延迟预算 |
| B7 | RAG 扩展 SHA256SUMS 后与 Eval 六文件清单不再字节一致 | ART-004、ART-005 | 来源声明准确，五个主制品逐文件一致且扩展清单可验证 |
| B8 | `ranking_diagnostics` 未携带候选契约版本，无法从单次响应证明排序所用候选口径 | FBK-001 至 FBK-010、API-001、API-005 | active/baseline 每个诊断都返回 `candidate_contract_version`，并与 health 和模型 serving contract 一致 |
| B9 | 开发环境 Qdrant 使用明文 HTTP + 非空 API key，但应用按 host/port 构造客户端时被 qdrant-client 自动切到 HTTPS | CAN-009、CAN-010、FLT-002 | 应用真实 `QdrantIndexStore` 能带认证访问开发 Qdrant，且连通性测试使用相同协议和认证参数 |
| B10 | `asyncio.wait_for(asyncio.to_thread(...))` 超时只取消等待者，不能停止已进入 LightGBM 推理的 worker thread | STA-003、TIM-001、TIM-002 | 连续推理超时后 worker、默认 executor 队列和内存均有界，且能在固定时间内恢复 |

在这些用例尚未转绿前，可以验证模型排序正确性和降级能力，但不能声明“Shadow 零主链路影响”
或“完整生产验收通过”。

2026-07-30 修复实现已为 B1 至 B10 补齐正式回归：Shadow serving/off 请求等价、独立冻结请求、
Dataset TopN、必备来源 fail closed、有界 Shadow executor、正文总预算、diagnostics、显式 Qdrant URL
与认证、专用有界推理 executor。代码回归与开发 Qdrant 连通性已通过；这不替代第 22 节的真实三路
质量、压力、最终镜像和回滚门禁。

## 21. 自动化建议与执行顺序

### 21.1 每次提交

1. 候选分型、特征、排序、fallback、provider 和 API 单元测试。
2. 模型 bundle、serving contract、冻结向量契约测试。
3. 纯召回隔离、四模式和 SSE 验收测试。
4. 文档同步、格式、静态检查。

### 21.2 合入 dev 前

1. 执行全部单元和验收测试，并与 1185/346 当前基线核对是否有意变化。
2. 在最终容器执行 ART、STA、MOD、ISO、API、CMP。
3. 执行全部 B1 至 B10 阻断用例。
4. 运行故障注入和回滚演练。

### 21.3 dev 真实流量

1. 先 off 建立同一批 Query 的延迟和结果基线。
2. 开 shadow，从低采样逐步提高；只有 SHD 全绿后才使用 Shadow 指标。
3. 核对候选分型、Top10、空召回、单路失败、短关键词低置信度和多 Chunk 场景。
4. 切 active 小流量，持续比较策略占比、fallback、p95/p99、首 token 和生成质量。
5. 演练 baseline 回滚并保存恢复证据。

## 22. 最终发布门禁

只有以下条件全部满足，才可提交生产端验收：

- ART：LightGBM 4.7.0、主制品 SHA、38 维签名、契约和三个冻结向量全部通过。
- CAN：五类 Query TopK 正确，三路真实装配被强制校验，阈值与权重无漂移。
- OUT/ISO：active/baseline Top10 正确；off、shadow 和纯召回不被错误覆盖。
- MOD/FBK：四模式、Hybrid、超时、异常和预算降级全部可解释、可重复。
- SHD：公开结果零影响，后台任务、正文读取、超时和连接池均有界。
- STA/TIM：首请求不承担模型初始化；连续超时不会导致线程或任务持续积压。
- API/CMP：SSE、health、旧字段、旧 Dataset JSON 和客户端兼容通过。
- OBS/PERF：监控、日志、告警和预先冻结的性能预算通过。
- ROL：baseline 和 off 回滚演练成功。
- B1 至 B10 全部转绿。
- 证据包经过独立复核，代码 SHA、镜像 digest、模型版本和执行环境可追溯。

## 23. 测试证据与报告模板

每次正式执行生成一份不可覆盖的报告，至少包含：

| 字段 | 内容 |
| --- | --- |
| 执行时间与人员 | 开始/结束时间、执行者、复核者 |
| 版本 | Git SHA、分支、镜像 digest |
| 模型 | model_version、bundle SHA、LightGBM 版本 |
| 候选契约 | candidate_contract_version、serving contract SHA |
| 环境 | 配置摘要、实例规格、worker 数、数据库与召回服务版本 |
| 数据 | 测试集版本、Query 数、分型分布、qrels 版本 |
| 自动化结果 | 总数、通过、失败、跳过及报告链接 |
| 功能证据 | 各模式样例、候选顺序、diagnostics、外部调用计数 |
| 性能证据 | p50/p95/p99、资源、连接池和任务曲线 |
| 故障与回滚 | 故障注入结果、回滚耗时、恢复验证 |
| 阻断项 | B1 至 B10 状态、负责人、修复版本 |
| 结论 | 通过、条件通过或拒绝；不得只写“测试完成” |

失败用例必须保留输入 ID、预期、实际、日志关联 ID、环境和复现步骤。涉及线上真实 Query 时只保存
脱敏 ID 和必要元数据，不在报告中复制原文或候选正文。
