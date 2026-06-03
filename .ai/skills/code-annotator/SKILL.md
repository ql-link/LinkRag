---
name: code-annotator
description: 代码高质量注释生成工作流。为 Python 项目生成恰到好处的 Docstring 注释，强调全局上下文感知、注释粒度控制和 PEP 257 规范。
when_to_use: "当用户要求为代码生成注释、补充文档字符串、优化代码说明、添加 docstring 或提到生成代码注解时激活。触发示例：'给这个文件加注释'、'补充docstring'、'生成代码注释'、'加一下注释说明'"
---

# 代码高质量注释生成规范

## 描述

资深后端架构师与文档专家，精通 Python Docstring 规范。能够结合文件的本地逻辑以及它在项目中的全局上下文，生成恰到好处的代码注释。既不遗漏关键业务解释，也不浪费笔墨注释显而易见的代码。

---

## 核心原则

**拒绝废话** - 不要对显而易见的代码进行翻译式注释。

- `count = 0  # 初始化计数器` → 废话
- `user.name = name  # 设置用户名` → 废话

---

## 注释分层要求

### 类注释（必须）

说明核心业务职责、设计意图、架构位置。

### 方法/函数注释（必须）

说明业务目的、入参含义、返回值、可能抛出的异常。

### 内部注释（按需严格限制）

必须注释的场景：
- 复杂的核心算法步骤
- 状态流转逻辑
- 跨模块/中间件调用：必须说明"为什么要调用"以及"预期的业务结果"

禁止注释的场景：
- 简单的赋值操作
- 变量声明与基础判空
- 显而易见的流程控制

---

## 文件角色识别

在生成注释前，分析文件在架构中的位置：

- API/Router: FastAPI Router、Flask Blueprint
- Service: 聚合业务逻辑层，编排多个 Repository
- Repository: 数据访问层，DAO、ORM 操作类
- Model/Schema: Pydantic Schema、SQLAlchemy Model
- Middleware: 依赖注入、中间件
- Util: 工具类

---

## Docstring 规范 (Google Style)

### 类注释

```python
class SparseVectorService:
    """稀疏向量服务层。

    编排稀疏向量编码与产出规整，按 provider 复用本地或远程 BGE-M3 编码器，
    向上游提供与 dense 召回对仗的稀疏向量化能力，不直接维护 MySQL/Qdrant 状态。
    """
```

### 方法/函数注释

```python
    async def vectorize_chunk(self, request: SparseChunkVectorizationRequest) -> SparseVector:
        """对单个 chunk 原文生成稀疏向量。

        Args:
            request: 待编码 chunk（含 chunk_id、content、bucket_id 等定位字段）

        Returns:
            indices 升序、values 一一对应的稀疏向量

        Raises:
            SparseVectorEncodingError: 编码失败或返回结构异常时抛出
            SparseVectorOutputError: 清洗后稀疏维度为空时抛出
        """
```

### 内部注释风格

```python
        # 现场过滤：只处理 dense 已成功且 sparse 尚未成功的 chunk（幂等、避免重复写）
        sparse_chunks = [
            c for c in chunks
            if c.dense_vector_status == CHUNK_STATUS_INDEXED
            and c.sparse_vector_status != SPARSE_VECTOR_STATUS_INDEXED
        ]

        # 复用同一套 lexical weights 清洗，保证本地/远程 provider 产出口径一致
        vectors = await self._encoder.aencode([c.content for c in sparse_chunks])
```

---

## 工作流程

1. **接收输入**：获取用户指定的目标文件/文件夹路径
2. **扫描依赖**：提取 `import` 的核心依赖，分析外部模块的业务作用
3. **上下文分析**：理解该文件在架构中的位置（API/Service/Repository/Model/Util）
4. **生成注释**：按分层要求生成恰到好处的注释
5. **输出结果**：保持原有代码的缩进和结构，只补充或优化注释

---

## 约束条件

- **不改变逻辑**：只负责补充或优化注释，不改变现有业务逻辑
- **保持缩进**：输出时保持原有代码的缩进和结构
- **信息密度**：注释应具有信息增量，而非简单翻译代码
- **业务导向**：注释应解释"为什么"，而非"做了什么"

---

## 使用示例

> 示例取自本项目领域（RAG 解析/向量化），不要用与项目无关的样例（如用户注册）。

### 用户输入

为稀疏向量编码器 `http_encoder.py` 生成注释

### Agent 响应

**上下文分析**
- 文件角色：Core 模块（稀疏向量编码器，实现 `SparseVectorEncoderProtocol`）
- 外部依赖：远程 `bge-m3-server`（HTTP）、`httpx`
- 调用关系：由 `sparse_vector/factory.py` 按 `SPARSE_VECTOR_PROVIDER=bge_m3_http` 装配，供 `SparseVectorService` 调用

**输出带注释的代码：**

```python
class BGEM3HttpSparseVectorEncoder:
    """调用远程 bge-m3-server 生成 sparse lexical weights 的编码器。

    与本地 BGEM3SparseVectorEncoder 实现同一 SparseVectorEncoderProtocol，
    上层编排无感切换；本类只负责 HTTP 调用与输出规整，不处理 MySQL/Qdrant 状态。
    """

    async def aencode(self, texts: Sequence[str]) -> list[SparseVector]:
        """调用远程 /encode 接口，把一批文本编码为稀疏向量。

        Args:
            texts: 待编码的 chunk 原文，返回向量与其一一同序。

        Returns:
            与输入同序的稀疏向量列表；输入为空时返回空列表。

        Raises:
            SparseVectorEncodingError: HTTP 调用失败或响应结构异常时抛出。
        """
        if not texts:
            return []

        # 只取 sparse，关闭 dense/colbert，降低远程计算与网络开销
        payload = {"texts": list(texts), "return_dense": False, "return_sparse": True}

        data = await self._post_encode(payload)

        # 远程返回的 sparse 必须与输入数量严格对齐，否则后续与 chunk 配对会错位
        sparse = data.get("sparse")
        if not isinstance(sparse, list) or len(sparse) != len(texts):
            raise SparseVectorEncodingError("bge-m3-server sparse 结构或数量不匹配")

        # 复用与本地推理同一套清洗规则，保证两种 provider 产出口径一致
        return [normalize_lexical_weights(w, top_k=self._top_k) for w in sparse]
```
