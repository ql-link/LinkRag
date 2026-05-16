---
name: swagger-annotation
description: FastAPI Swagger 中文注解生成工作流。为 Controller 路由和 Pydantic 模型生成符合企业级规范的中文 Swagger 注解。
when_to_use: "当用户要求为 FastAPI 路由、Pydantic 模型添加 Swagger/OpenAPI 注解、补充 API 文档说明或优化 /docs 页面显示时激活。触发示例：'给这个接口加swagger注解'、'补充API文档'、'添加openapi描述'"
---

# FastAPI Swagger 中文注解生成规范

## 描述
精通 FastAPI + Pydantic v2 的 OpenAPI Schema 生成机制，能够为任意 Controller（路由）和实体模型（Pydantic BaseModel）产出符合企业级规范的中文 Swagger 注解，确保生成的 `/docs` 页面对前端和 Java 协作方具有自解释性。

---

## 核心原则

| 原则 | 说明 |
|------|------|
| **中文文档** | 所有 `title`、`summary`、`description` 必须为中文 |
| **API-First** | 良好的 Swagger 注解能显著降低前后端联调成本 |
| **自解释性** | 确保 `/docs` 页面对前端和 Java 协作方具有自解释性 |

---

## 📋 注解覆盖清单

每次面对需要为一组接口添加 Swagger 注解的请求时：

1. **扫描目标**：识别所有待处理的路由端点和 Pydantic 模型
2. **分析现状**：检查哪些端点/模型已经有注解，哪些缺失或不完整
3. **分组规划**：确定路由分组标签 (tags)，在 `main.py` 的 `openapi_tags` 中注册
4. **逐层标注**：按顺序完善注解

### 标注顺序
1. Router tag → 2. 端点装饰器 → 3. 函数参数 → 4. 请求体模型 → 5. 响应体模型

---

## ✏️ 注解规范

### 1. FastAPI 应用层 (main.py)

在 `FastAPI()` 构造器中必须配置：

```python
app = FastAPI(
    title="项目名称",
    version="1.0.0",
    description="""
## 系统简介
- 🤖 **能力一**：简要说明
- 📐 **能力二**：简要说明
""",
    openapi_tags=[
        {"name": "分组中文名", "description": "该分组的职责说明"},
    ],
)
```

### 2. Router 路由分组 (tags)

每个 `APIRouter` 的 `tags` 必须使用**与 `openapi_tags` 中 `name` 一致的中文标签**：

```python
router = APIRouter(
    prefix="/api/v1/xxx",
    tags=["中文分组名称"],
)
```

### 3. 路由端点装饰器

每个 `@router.get / .post / .put / .delete` 必须携带以下参数：

| 参数 | 说明 |
|------|------|
| `summary` | 一句话描述接口功能（显示在 Swagger 列表中每个接口标题处） |
| `description` | 详细说明接口的业务语义、适用场景或注意事项 |
| `response_model` | 指定返回的 Pydantic 数据模型（非流式接口必填） |

```python
@router.post(
    "/generate",
    response_model=APIResponse,
    summary="文本生成 (非流式)",
    description="调用大模型生成文本回应。支持用户自定义配置路由、参数覆盖以及系统级自动降级兜底。",
)
async def generate_text(...):
    ...
```

### 4. 路由函数参数注解

| 参数类型 | 要求 |
|----------|------|
| `Header` 参数 | 必须添加 `description` 说明该 Header 的来源与含义 |
| `Query` 参数 | 必须添加 `description` 说明该参数的格式与用途 |

```python
x_user_id: str = Header(..., alias="X-User-Id", description="调用方用户唯一标识")
start_date: Optional[str] = Query(None, description="起始日期，格式 YYYY-MM-DD")
```

### 5. Pydantic 请求体模型 (Request Body)

每个字段必须使用 `Field()` 并配置：

| 配置项 | 说明 |
|--------|------|
| `title` | 字段的中文短标题（Swagger Schema 中显示） |
| `description` | 字段的详细用途说明 |

模型类必须配置 `model_config`：

```python
class GenerateRequest(BaseModel):
    """生成文本请求"""
    prompt: str = Field(..., title="提示词", description="发送给大模型的输入文本内容")
    temperature: float = Field(0.7, ge=0, le=2, title="采样温度", description="控制输出的随机性")

    model_config = {
        "title": "文本生成请求体"
    }
```

### 6. Pydantic 响应体模型 (Response Model)

与请求体同理，每个字段 `Field()` 必须有 `title` + `description`。
可额外配置 `json_schema_extra.example` 提供示例值：

```python
class UsageInfo(BaseModel):
    """Token 使用量信息"""
    prompt_tokens: int = Field(0, title="提示词Token数", description="输入内容的Token消耗量")
    total_tokens: int = Field(0, title="总Token数", description="总计Token消耗量")

    model_config = {
        "title": "Token使用量统计",
        "json_schema_extra": {
            "example": {
                "prompt_tokens": 15,
                "total_tokens": 115,
            }
        }
    }
```

---

## 🚫 禁止事项

| 禁止项 | 说明 |
|--------|------|
| **英文 title/summary/description** | 本项目约定中文文档 |
| **遗漏 model_config.title** | 否则 Swagger Schemas 面板会显示类名而非业务语义 |
| **路由端点不带 summary** | 否则在 Swagger 列表中该接口没有可读标题 |
| **Field() 只写 description** | `title` 和 `description` 两者都必须提供 |

---

## ✅ 验证建议

```bash
# 启动服务后访问 Swagger UI 验证
uvicorn src.main:app --reload
# 浏览器打开 http://localhost:8000/docs
```

---

## 📝 输出格式

每次添加 Swagger 注解时，按以下结构应答：

```markdown
### 📋 注解覆盖清单
- **目标文件**：<文件路径>
- **路由端点**：列出所有待标注的 endpoint
- **数据模型**：列出所有待标注的 Pydantic 类
- **缺失项分析**：哪些已有、哪些缺失

### ✏️ 注解代码
```python
# 输出完整的 Swagger 注解修改代码
```

### ✅ 验证建议
```bash
# 启动服务后访问 Swagger UI 验证
uvicorn src.main:app --reload
# 浏览器打开 http://localhost:8000/docs
```
