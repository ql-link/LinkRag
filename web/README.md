# LinkRag Web（用户端）

LinkRag 用户端前端，按 Figma「LinkRag · 重设计 · V1」还原。技术栈：React 19 + Vite 6 + TypeScript + Tailwind CSS 4。

## 开发

```bash
cd web
npm install
npm run dev        # http://localhost:3000
npm run build      # 类型检查 + 生产构建
npm test           # Vitest 单元 / 交互测试
```

## 数据模式

默认使用内存 Mock（离线演示、单元测试）；设置 `VITE_USE_MOCK=false` 连接 Python 后端。

```bash
cp .env.example .env.local   # VITE_USE_MOCK=false，VITE_API_TARGET=http://localhost:8000
npm run dev                  # Vite 把 /api 代理到 VITE_API_TARGET
```

后端需先按仓库根目录 README 启动（`docker compose up -d` → `alembic upgrade head` → `uvicorn src.main:app --reload`），
并在后端 env 中开启：

| 变量 | 作用 |
| --- | --- |
| `JAVA_ACCESS_JWT_ENABLED=true`、`JAVA_ACCESS_JWT_PUBLIC_KEY_PATH` | 管理端鉴权（未开启时所有管理接口 503） |
| `B1_PYTHON_ISSUER_ENABLED=true`、`B1_JAVA_PROTECTED_ROUTES_RETIRED=true`、`B1_ACCESS_JWT_PRIVATE_KEY_PATH` | Python 登录签发（与上面的公钥为一对 RSA 密钥） |
| `B3_CONTROL_WRITES_ENABLED=true` | 模型配置写入 |
| `B4_DATASET_WRITES_ENABLED=true` | 知识库创建 / 修改 / 启停 |
| `B5_FILE_WRITES_ENABLED=true`、`B5_DELETE_WRITES_ENABLED=true` | 文件上传 / 解析 / 删除 |

本地生成密钥对：

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out access_jwt_private.pem
openssl pkey -in access_jwt_private.pem -pubout -out access_jwt_public.pem
```

对接说明：

- 请求层 `src/api/http.ts`：管理接口带 `satoken` 头、RAG 流带 `Authorization: Bearer`（同一 token）；统一解包 `{code,message,data}`，401 自动退出，过期前 10 分钟自动续期（`POST /api/v1/auth/refresh`）。
- 接口定义 `src/api/endpoints.ts`，问答流 `src/api/stream.ts`（fetch + ReadableStream 读 SSE）。
- 服务层 `src/services/*` 保持同步选择器不变：`services/backend.ts` 登录后拉取数据写入 store，写操作调用接口后更新 store；页面组件不区分两种模式。
- 问答流事件映射：`recall_started` / `recall_hits` / `generation_started` → 思考步骤；`answer_delta` → 流式正文；回答中的「[片段N]」解析为可点击引用；停止生成调用 `POST /api/v1/rag/stream/{turn_id}/cancel`。
- 真实模式暂不支持：文件级百分比进度（显示为进行中）、页码级原文预览、首页 Token 概览（请在「用量」页查看）。

## 目录

| 路径 | 说明 |
| --- | --- |
| `src/index.css` | 设计 token（颜色、字体、阴影） |
| `src/components/ui/` | 基础组件：Button、Chip、Segmented、Dialog、Menu、Switch 等 |
| `src/layouts/` | 侧栏与应用外壳 |
| `src/pages/` | 页面，按模块分目录 |
| `src/mock/` | Mock 数据与模拟后端 |
| `src/api/` | 后端请求层与接口定义 |
| `src/services/` | 服务层（按 `VITE_USE_MOCK` 选择 Mock 或真实接口） |
