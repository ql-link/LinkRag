---
name: code-annotator
description: 代码高质量注释生成工作流。为 Python 项目生成恰到好处的 Docstring 注释，强调全局上下文感知、注释粒度控制和 PEP 257 规范。
when_to_use: "当用户提供或指定目标文件/文件夹，要求生成、补充、优化代码注释，或提到代码注解、文档注释时激活"
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
-显而易见的流程控制

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
class UserService:
    """用户服务层。

    负责用户注册、登录、信息修改等核心业务流程的编排，
    协调 UserRepository 与 RedisCache 实现数据持久化与缓存策略。
    """
```

### 方法/函数注释

```python
    def register(self, request: RegisterRequest) -> int:
        """用户注册。

        Args:
            request: 注册请求（包含手机号、密码）

        Returns:
            注册成功后的用户ID

        Raises:
            BusinessError: 手机号已存在或校验失败时抛出
        """
```

### 内部注释风格

```python
        # 1. 校验手机号是否已被注册（调用Repository查询数据库）
        if await self.user_repository.exists_by_phone(request.phone):
            raise BusinessError("手机号已被注册")

        # 2. 密码加密后入库（不加密会导致安全风险）
        encrypted_password = self.password_encoder.encode(request.password)

        # 3. 写入缓存（预期：提升后续查询性能）
        await self.redis_cache.set(f"user:{user_id}", user)
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

### 用户输入

为 user_service.py 生成注释

### Agent 响应

**上下文分析**
- 文件角色：Service 层
- 外部依赖：UserRepository、RedisCache
- 调用关系：被 UserRouter 依赖注入

**输出带注释的代码：**

```python
class UserService:
    """用户服务层。

    负责用户注册、登录、信息修改等核心业务流程的编排，
    协调 UserRepository 与 RedisCache 实现数据持久化与缓存策略。
    """

    def __init__(
        self,
        user_repository: UserRepository,
        redis_cache: RedisCache,
    ) -> None:
        self.user_repository = user_repository
        self.redis_cache = redis_cache

    async def register(self, request: RegisterRequest) -> int:
        """用户注册。

        Args:
            request: 注册请求（包含手机号、密码）

        Returns:
            注册成功后的用户ID

        Raises:
            BusinessError: 手机号已存在或校验失败时抛出
        """
        # 校验手机号是否已被注册（调用Repository查询数据库）
        if await self.user_repository.exists_by_phone(request.phone):
            raise BusinessError("手机号已被注册")

        # 密码加密后入库（不加密会导致安全风险）
        encrypted_password = self.password_encoder.encode(request.password)
        user = User(phone=request.phone, password=encrypted_password)
        user_id = await self.user_repository.save(user)

        # 写入缓存（预期：提升后续查询性能）
        await self.redis_cache.set(f"user:{user_id}", user)

        return user_id

    async def get_user_by_id(self, user_id: int) -> User | None:
        """根据ID获取用户。

        先查缓存，缓存未命中时查数据库并回填缓存。

        Args:
            user_id: 用户ID

        Returns:
            用户对象，不存在返回 None
        """
        # 尝试从缓存获取（减少数据库压力）
        cached_user = await self.redis_cache.get(f"user:{user_id}")
        if cached_user:
            return cached_user

        # 缓存未命中，查数据库
        user = await self.user_repository.find_by_id(user_id)
        if user:
            # 回填缓存（预期：下次查询直接命中）
            await self.redis_cache.set(f"user:{user_id}", user)

        return user
```
