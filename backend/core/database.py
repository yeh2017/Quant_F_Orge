"""
数据库引擎与会话管理
==================
- SQLite WAL 模式 + 性能 pragma
- 上下文管理器 db_session() 替代手动 try/finally/close
"""

from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

# ---------- 引擎 ----------

import os as _os
_BACKEND_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
SQLALCHEMY_DATABASE_URL = f"sqlite:///{_os.path.join(_BACKEND_DIR, 'quant_data.db')}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """每次取得新的 SQLite 原生连接时设置性能 pragma"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA page_size=16384")          # 16KB 页：减少 B-tree 深度，加速大范围扫描
    cursor.execute("PRAGMA cache_size=-64000")         # 64 MB 页面缓存
    cursor.execute("PRAGMA journal_size_limit=67108864")  # WAL 文件上限 64 MB
    cursor.execute("PRAGMA busy_timeout=30000")        # 锁等待 30 秒
    cursor.execute("PRAGMA mmap_size=2147483648")      # 2 GB 内存映射，避免 read() 系统调用
    cursor.execute("PRAGMA temp_store=MEMORY")         # 临时表/排序在内存完成
    cursor.close()


def _auto_vacuum_if_needed():
    """首次启动时检查 page_size，不一致则自动 VACUUM（一次性操作）。

    PRAGMA page_size 对已有 DB 只在 VACUUM 后生效，
    且 **必须在非 WAL 模式下执行**（SQLite 限制）。
    因此使用原生 sqlite3 连接，绕过 SQLAlchemy 的 connect 事件（那里会设 WAL）。
    """
    import os
    db_path = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "")
    if not os.path.exists(db_path):
        return  # 新 DB，create_all 时自动用新 page_size

    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA page_size")
        current = cur.fetchone()[0]
        if current != 16384:
            import structlog
            log = structlog.get_logger("database")
            log.info("auto_vacuum_start",
                     current_page_size=current, target=16384,
                     hint="一次性操作，1.6GB 约需2-5分钟")
            # 必须先退出 WAL 模式才能改 page_size
            cur.execute("PRAGMA journal_mode=DELETE")
            cur.execute("PRAGMA page_size=16384")
            cur.execute("VACUUM")
            # 恢复 WAL 模式
            cur.execute("PRAGMA journal_mode=WAL")
            log.info("auto_vacuum_done", new_page_size=16384)
        cur.close()
        conn.close()
    except Exception as e:
        import structlog
        structlog.get_logger("database").warning(
            "auto_vacuum_failed", error=str(e),
            hint="可手动执行: PRAGMA journal_mode=DELETE; PRAGMA page_size=16384; VACUUM; PRAGMA journal_mode=WAL;")


_auto_vacuum_if_needed()


# ---------- 会话工厂 ----------

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# ---------- 上下文管理器 ----------

@contextmanager
def db_session():
    """
    安全的数据库会话上下文管理器。

    用法::

        with db_session() as db:
            db.execute(...)
            # 正常退出自动 commit，异常自动 rollback
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


def get_db():
    """FastAPI Depends 注入用 — 正常退出自动 commit，异常自动 rollback"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _migrate_table(table_name: str, new_cols: dict):
    """
    通用列迁移：给已有表安全补列（幂等）。
    - 表不存在 → 跳过（create_all 会建完整表）
    - 列已存在 → 跳过
    - 列缺失   → ALTER TABLE ADD COLUMN
    """
    import structlog as _sl
    _log = _sl.get_logger("db_migrate")
    try:
        with engine.connect() as conn:
            sa_text = __import__("sqlalchemy").text
            result = conn.execute(sa_text(f"PRAGMA table_info({table_name})"))
            existing = {row[1] for row in result}
            if not existing:
                # 表不存在或无列 → create_all 已建好完整表，无需 ALTER
                return
            added = []
            for col, col_type in new_cols.items():
                if col not in existing:
                    conn.execute(sa_text(
                        f"ALTER TABLE {table_name} ADD COLUMN {col} {col_type}"
                    ))
                    added.append(col)
            if added:
                _log.info(f"{table_name}_migrated", added=added)
    except Exception as e:
        _log.warning(f"{table_name}_migrate_failed", error=str(e))


def migrate_backtest_results():
    """安全补全 backtest_results 表中新增的列（幂等）"""
    _migrate_table("backtest_results", {
        "task_id": "TEXT", "strategy_type": "TEXT", "codes": "TEXT",
        "start_date": "TEXT", "end_date": "TEXT",
        "win_rate": "REAL", "result_json": "TEXT",
    })


def migrate_stock_news():
    """安全补全 stock_news 表中 NLP 新增列（幂等）"""
    _migrate_table("stock_news", {
        "event_type": "TEXT", "nlp_reason": "TEXT",
    })


def migrate_financial_columns():
    """安全补全 stock_financials 表中质量因子新增列（幂等）"""
    _migrate_table("stock_financials", {
        "cashflow_oper": "REAL", "debt_to_assets": "REAL",
    })

