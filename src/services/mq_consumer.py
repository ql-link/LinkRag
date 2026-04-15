from celery import Celery
from src.config import settings
from src.services.parse_task_service import ParseTaskService
from src.utils.file_downloader import FileDownloader
from src.core.database import SessionLocal
from src.models.parse_task import DocumentParseTask

# 初始化 Celery 消费者，使用配置中心的 URL
celery_app = Celery(
    'parse_tasks',
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)


@celery_app.task(bind=True, max_retries=3)
def consume_parse_task(self, task_id: str, document_id: str, file_url: str, file_type: str):
    """Celery 异步任务消费者: 执行闭环操作"""
    db = SessionLocal()
    try:
        # 1. 状态变更为处理中 (PROCESSING)
        task_record = db.query(DocumentParseTask).filter(DocumentParseTask.id == task_id).first()
        if task_record:
            task_record.status = "PROCESSING"
            db.commit()

        # 2. 从 OSS 下载文件
        print(f"MQ Worker 开始处理任务: {task_id}, 下载文件...")
        file_stream = FileDownloader.download(file_url)

        # 3. 核心解析逻辑
        result = ParseTaskService.process_sync(file_stream, file_type)

        # 4. 解析成功，回写数据库
        if task_record:
            task_record.status = "SUCCESS"
            task_record.markdown_content = result["markdown"]
            task_record.page_count = result["metadata"].get("pages_or_length", 0)
            task_record.time_cost_ms = result["time_cost_ms"]
            db.commit()
            print(f"解析成功！已保存至数据库。")

        return {"task_id": task_id, "status": "success"}

    except Exception as e:
        # 5. 解析失败，记录错误并触发重试
        if 'task_record' in locals() and task_record:
            task_record.status = "FAILED"
            task_record.error_message = str(e)[:500]
            db.commit()
            print(f"任务 {task_id} 解析失败: {str(e)}")
        raise self.retry(exc=e, countdown=10)  # 10秒后重试

    finally:
        db.close()