from fastapi import FastAPI
import uvicorn
from src.api.routes import parse
from src.core.database import engine
from src.models.parse_task import Base

# 启动时自动在 MySQL 中创建 document_parse_task 表 (如果不存在)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="toLink-Rag Document Parser API",
    description="多格式文档解析至 Markdown 引擎"
)

# 挂载我们刚刚写的解析路由
app.include_router(parse.router)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "document_parser"}

if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)