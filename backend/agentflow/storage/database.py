"""
数据库连接和会话管理
"""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import os

from agentflow.storage.models import Base

# 数据库文件路径
DB_PATH = os.getenv("AGENTFLOW_DB_PATH", "./agentflow_data.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# 创建引擎
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite 特定配置
    echo=False,  # 生产环境设为 False
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 增量列迁移：SQLite 的 create_all 不会给已有表加列，这里做最小 ALTER TABLE。
# 新增列必须是可空或带默认值，保证旧数据仍可读。
_SCHEMA_MIGRATIONS = {
    "workflow_runs": {
        "workflow_name": "VARCHAR(200)",
        "schema_version": "INTEGER",
        "trace_id": "VARCHAR(64)",
        "experiment_id": "VARCHAR(64)",
        "candidate_id": "VARCHAR(64)",
        "case_id": "VARCHAR(64)",
        "fingerprint": "VARCHAR(64)",
        "evidence_ref": "VARCHAR(500)",
        "score": "FLOAT",
        "passed": "BOOLEAN",
        "score_status": "VARCHAR(32)",
        "score_source": "VARCHAR(32)",
        "error": "TEXT",
        "stop_requested": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "step_results": {
        "step_index": "INTEGER",
        "input_text": "TEXT",
        "output_text": "TEXT",
        "model": "VARCHAR(100)",
        "finish_reason": "VARCHAR(50)",
        "error_type": "VARCHAR(32)",
        "attempts": "INTEGER NOT NULL DEFAULT 1",
    },
}


def _migrate_columns():
    """为已有数据库补齐新增列（幂等）"""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, columns in _SCHEMA_MIGRATIONS.items():
            if table not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing_columns:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        # 旧记录没有版本号：迁移列之后统一标记为 schema 1（仅消息 id 的旧格式），
        # 新记录由应用层写入当前版本号（2）。
        if "workflow_runs" in existing_tables:
            connection.execute(
                text("UPDATE workflow_runs SET schema_version = 1 WHERE schema_version IS NULL")
            )


def init_db():
    """初始化数据库，创建所有表并补齐增量列"""
    Base.metadata.create_all(bind=engine)
    _migrate_columns()



@contextmanager
def get_db() -> Session:
    """
    获取数据库会话的上下文管理器

    使用示例:
        with get_db() as db:
            db.query(...)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_session() -> Session:
    """
    获取数据库会话（用于依赖注入）

    使用示例（FastAPI）:
        @app.get("/items")
        def read_items(db: Session = Depends(get_db_session)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        return db
    finally:
        pass  # 由调用者负责关闭
