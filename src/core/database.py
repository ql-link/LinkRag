from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.config import settings

# 从 config.py 读取数据库连接 URL
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)